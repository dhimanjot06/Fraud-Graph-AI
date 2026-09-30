"""Layer 3: turn graph structure into scored, explainable fraud-ring candidates.

Three patterns are searched:
  cycle          closed loops of similar-sized, closely timed transfers
  collector_hub  many accounts pay similar amounts to one account that forwards the pool
  dense_cluster  a tight community whose members transact heavily among themselves

Each candidate is scored 0-100 from six weighted signals and comes with
plain-language reasons, so an analyst can see *why* it was flagged.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd

from .data_service import to_epoch_seconds
from .graph_service import GraphAnalysis
from .settings import DetectionSettings

# Coincidental loops are common in dense networks, so the loop itself carries
# little weight; repeated, similar-sized, closely timed transfers carry the most.
WEIGHTS = {
    "structure": 0.10,
    "amount_similarity": 0.25,
    "timing": 0.20,
    "repeat_interaction": 0.15,
    "connectivity": 0.10,
    "flow_balance": 0.20,
}
COMPONENT_LABELS = {
    "structure": "Ring structure",
    "amount_similarity": "Similar amounts",
    "timing": "Tight timing",
    "repeat_interaction": "Repeated interaction",
    "connectivity": "Accounts both send and receive",
    "flow_balance": "Money passes through",
}
TYPE_LABELS = {
    "cycle": "Circular money movement",
    "collector_hub": "Collector account",
    "dense_cluster": "Dense account cluster",
}


@dataclass
class Ring:
    ring_type: str
    nodes: list
    tx_index: list
    score: float = 0.0
    level: str = "low"
    code: str = ""
    components: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    roles: dict = field(default_factory=dict)
    edges: list = field(default_factory=list)
    loops: list = field(default_factory=list)
    hub: str | None = None

    def roles_by(self, role):
        return [n for n, r in self.roles.items() if r == role]


# ---------------------------------------------------------------- candidates
def _union_cycles(cycles, max_size):
    """Merge loops that share two or more accounts into one ring."""
    parent = list(range(len(cycles)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    node_to_cycles = defaultdict(list)
    for i, cyc in enumerate(cycles):
        for n in cyc:
            node_to_cycles[n].append(i)
    for i, cyc in enumerate(cycles):
        shared = Counter()
        for n in cyc:
            for j in node_to_cycles[n]:
                if j != i:
                    shared[j] += 1
        for j, count in shared.items():
            if count >= 2:
                parent[find(i)] = find(j)

    groups = defaultdict(list)
    for i in range(len(cycles)):
        groups[find(i)].append(cycles[i])
    out = []
    for loops in groups.values():
        nodes = sorted({n for c in loops for n in c})
        if len(nodes) <= max_size:
            out.append((nodes, loops))
    return out


def _densest_window(ts: np.ndarray, hours: float):
    """Return (max transactions inside one window, start index) for sorted timestamps."""
    if len(ts) == 0:
        return 0, 0
    span, best, best_i, j = hours * 3600.0, 0, 0, 0
    for i in range(len(ts)):
        while ts[i] - ts[j] > span:
            j += 1
        if i - j + 1 > best:
            best, best_i = i - j + 1, j
    return best, best_i


def _hub_candidates(df, G, has_ts, settings):
    """Accounts that gather similar payments from many senders and forward the pool."""
    found = []
    unique_in = sorted(((G.in_degree(n), n) for n in G.nodes), reverse=True)[:500]
    ts_all = to_epoch_seconds(df["timestamp"]).to_numpy(dtype=float)
    by_receiver = df.groupby("receiver").indices
    by_sender = df.groupby("sender").indices
    for deg, hub in unique_in:
        if deg < settings.hub_min_senders:
            break
        idx = np.asarray(by_receiver[hub])
        order = np.argsort(ts_all[idx], kind="stable")
        idx = idx[order]
        senders = df["sender"].to_numpy()[idx]
        times = ts_all[idx]
        amounts = df["amount"].to_numpy()[idx]

        best_set = None
        j, counts = 0, Counter()
        window = settings.time_window_hours * 3600.0 if has_ts else float("inf")
        for i in range(len(idx)):
            counts[senders[i]] += 1
            while times[i] - times[j] > window:
                counts[senders[j]] -= 1
                if counts[senders[j]] == 0:
                    del counts[senders[j]]
                j += 1
            if len(counts) >= settings.hub_min_senders and (best_set is None or len(counts) > best_set[0]):
                best_set = (len(counts), j, i)
        if best_set is None:
            continue
        _, lo, hi = best_set
        w_idx, w_amt = idx[lo:hi + 1], amounts[lo:hi + 1]
        med = float(np.median(w_amt))
        keep = np.abs(w_amt - med) <= 0.30 * med
        w_idx, w_amt = w_idx[keep], w_amt[keep]
        feeders = sorted({df["sender"].iat[i] for i in w_idx})
        if len(feeders) < settings.hub_min_senders:
            continue
        cv = float(np.std(w_amt) / np.mean(w_amt))
        if cv > settings.hub_amount_cv_max:
            continue
        pooled = float(w_amt.sum())
        inbound_total = float(amounts.sum())
        concentration = pooled / inbound_total if inbound_total else 0.0
        if concentration < 0.4:      # a busy legitimate account, not a pooling account
            continue

        out_idx = np.asarray(by_sender.get(hub, []), dtype=int)
        if len(out_idx) == 0:
            continue
        out_mask = ts_all[out_idx] >= ts_all[w_idx].min()
        out_idx = out_idx[out_mask]
        if len(out_idx) == 0:
            continue
        out_frame = df.iloc[out_idx]
        out_totals = out_frame.groupby("receiver")["amount"].sum()
        beneficiary = out_totals.idxmax()
        forwarded = float(out_totals.max())
        if forwarded < settings.hub_min_forward_ratio * pooled:
            continue
        nodes = sorted(set(feeders) | {hub, beneficiary})
        if len(nodes) > settings.max_ring_size:
            continue
        forward_idx = out_frame.index[out_frame["receiver"] == beneficiary].tolist()
        found.append({"hub": hub, "beneficiary": beneficiary, "feeders": feeders,
                      "feeder_idx": [int(i) for i in w_idx], "forward_idx": forward_idx,
                      "nodes": nodes, "pooled": pooled, "forwarded": forwarded,
                      "concentration": concentration})
    return found


# ------------------------------------------------------------------- scoring
def _internal_frame(df, nodes):
    mask = df["sender"].isin(nodes) & df["receiver"].isin(nodes)
    return df.loc[mask]


def _flow_balance(sub: pd.DataFrame):
    out_tot = sub.groupby("sender")["amount"].sum()
    in_tot = sub.groupby("receiver")["amount"].sum()
    both = out_tot.index.intersection(in_tot.index)
    if len(both) == 0:
        return 0.0
    hi = pd.concat([out_tot[both], in_tot[both]], axis=1).max(axis=1)
    lo = pd.concat([out_tot[both], in_tot[both]], axis=1).min(axis=1)
    return float((lo / hi).mean())


def _participation(sub: pd.DataFrame, nodes):
    senders, receivers = set(sub["sender"]), set(sub["receiver"])
    return len(senders & receivers & set(nodes)) / max(len(nodes), 1)


def _score(ring: Ring, df, G, has_ts, settings, amount_frame=None, extra=None):
    extra = extra or {}
    nodes = ring.nodes
    sub = df.loc[ring.tx_index]
    amounts_src = amount_frame if amount_frame is not None else sub
    amounts = amounts_src["amount"].to_numpy(dtype=float)
    mean_amt = float(amounts.mean())
    cv = float(amounts.std() / mean_amt) if mean_amt > 0 else 1.0

    n = len(nodes)
    pairs = sub.groupby(["sender", "receiver"]).size()
    avg_repeat = float(pairs.mean()) if len(pairs) else 1.0
    density = len(pairs) / (n * (n - 1)) if n > 1 else 0.0
    participation = _participation(sub, nodes)
    balance = _flow_balance(sub)

    if ring.ring_type == "cycle":
        structure = min(1.0, 0.75 + 0.08 * (len(ring.loops) - 1))
    elif ring.ring_type == "collector_hub":
        n_feed = len(extra["feeders"])
        size_term = min(1.0, 0.5 + 0.5 * (n_feed - settings.hub_min_senders) / settings.hub_min_senders)
        structure = 0.5 * size_term + 0.5 * min(1.0, extra["concentration"])
    else:
        structure = min(1.0, density / 0.8) * 0.7

    window_frac = None
    if has_ts:
        ts = np.sort(to_epoch_seconds(sub["timestamp"]).to_numpy(dtype=float))
        best, _ = _densest_window(ts, settings.time_window_hours)
        window_frac = best / len(ts) if len(ts) else 0.0

    is_hub = ring.ring_type == "collector_hub"
    comps = {
        "structure": structure,
        "amount_similarity": float(np.clip(1 - cv / 0.3, 0, 1)),
        "timing": window_frac,
        # Feeders of a collector pay once by design, so these two do not apply.
        "repeat_interaction": None if is_hub else float(min(1.0, max(0.0, (avg_repeat - 1) / 2))),
        "connectivity": None if is_hub else participation,
        "flow_balance": float(np.clip((balance - 0.5) / 0.5, 0, 1)),
    }
    active = {k: v for k, v in comps.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in active)
    score = 100.0 * sum(WEIGHTS[k] * v for k, v in active.items()) / total_w

    ring.score = round(float(score), 1)
    ring.level = settings.level(ring.score)
    ring.components = {k: {"label": COMPONENT_LABELS[k], "value": round(float(v), 3), "weight": WEIGHTS[k]}
                       for k, v in active.items()}
    ring.metrics = {
        "accounts": n,
        "transactions": int(len(sub)),
        "total_amount": round(float(sub["amount"].sum()), 2),
        "min_amount": round(float(amounts.min()), 2),
        "max_amount": round(float(amounts.max()), 2),
        "amount_spread": round(cv, 3),
        "density": round(density, 3),
        "participation": round(participation, 3),
        "flow_balance": round(balance, 3),
        "window_fraction": None if window_frac is None else round(window_frac, 3),
        "concentration": round(extra["concentration"], 3) if is_hub else None,
        "avg_repeat": round(avg_repeat, 2),
        "loops": len(ring.loops),
        "first_seen": sub["timestamp"].min().isoformat() if has_ts else None,
        "last_seen": sub["timestamp"].max().isoformat() if has_ts else None,
    }
    ring.edges = [
        {"source": s, "target": t, "count": int(c),
         "total": round(float(sub[(sub["sender"] == s) & (sub["receiver"] == t)]["amount"].sum()), 2)}
        for (s, t), c in pairs.items()
    ]


def _money(settings, value):
    return f"{settings.currency_symbol}{value:,.0f}"


def _explain(ring: Ring, settings) -> list:
    m, c, cur = ring.metrics, {k: v["value"] for k, v in ring.components.items()}, settings
    reasons = []
    if ring.ring_type == "cycle":
        path = " → ".join(ring.loops[0] + [ring.loops[0][0]]) if ring.loops else ""
        text = f"Circular money movement: funds return to where they started through a closed loop ({path})."
        if len(ring.loops) > 1:
            text += f" {len(ring.loops)} overlapping loops were found."
        reasons.append(text)
    elif ring.ring_type == "collector_hub":
        reasons.append(f"{len(ring.roles_by('feeder'))} accounts paid similar amounts to {ring.hub}, "
                       f"which forwarded the pooled money onward. {m['concentration']:.0%} of the money "
                       f"{ring.hub} received came from this group.")
    else:
        reasons.append(f"Unusually dense group: {m['accounts']} accounts share {len(ring.edges)} transfer links "
                       f"(density {m['density']:.0%}).")
    if c["amount_similarity"] >= 0.6:
        reasons.append(f"Transfers are close in size ({_money(cur, m['min_amount'])} to {_money(cur, m['max_amount'])}, "
                       f"spread {m['amount_spread']:.0%}), which is what a system built to look ordinary produces.")
    if c.get("timing", 0) >= 0.6 and m["window_fraction"] is not None:
        reasons.append(f"{m['window_fraction']:.0%} of the group's transfers happened inside a "
                       f"{settings.time_window_hours}-hour window.")
    if c.get("repeat_interaction", 0) >= 0.4:
        reasons.append(f"The same account pairs transact repeatedly (average {m['avg_repeat']:.1f} transfers per link).")
    if "connectivity" in c:
        if c["connectivity"] >= 0.9:
            reasons.append("Every account both sends and receives money inside the group.")
        elif c["connectivity"] >= 0.5:
            reasons.append(f"{c['connectivity']:.0%} of accounts both send and receive inside the group.")
    if m["flow_balance"] >= 0.8:
        reasons.append(f"Accounts pass on about {m['flow_balance']:.0%} of the money they receive, "
                       f"a sign of pass-through rather than real spending.")
    return reasons


def _roles(ring: Ring, analysis: GraphAnalysis, extra):
    if ring.ring_type == "cycle":
        roles = {n: "loop member" for n in ring.nodes}
    elif ring.ring_type == "collector_hub":
        roles = {n: "feeder" for n in extra["feeders"]}
        roles[extra["hub"]] = "collector"
        roles[extra["beneficiary"]] = "beneficiary"
    else:
        roles = {n: "cluster member" for n in ring.nodes}
        best = max(ring.nodes, key=lambda n: analysis.betweenness.get(n, 0.0) + analysis.pagerank.get(n, 0.0))
        roles[best] = "bridge"
    return roles


# ------------------------------------------------------------------- driver
def detect_rings(df: pd.DataFrame, analysis: GraphAnalysis, has_ts: bool, settings: DetectionSettings):
    G = analysis.graph
    if df.empty or G.number_of_nodes() == 0:
        return []
    candidates = []

    pair_rows = df.groupby(["sender", "receiver"]).indices if analysis.cycles else {}
    for nodes, loops in _union_cycles(analysis.cycles, settings.max_ring_size):
        # Score the loop's own transfers; stray payments between members are not part of the pattern.
        edges = {(l[i], l[(i + 1) % len(l)]) for l in loops for i in range(len(l))}
        sub_idx = sorted(int(i) for e in edges for i in pair_rows[e])
        ring = Ring("cycle", nodes, sub_idx, loops=[list(l) for l in loops])
        candidates.append((ring, None, None))

    for h in _hub_candidates(df, G, has_ts, settings):
        sub_idx = sorted(set(h["feeder_idx"]) | set(h["forward_idx"]))
        ring = Ring("collector_hub", h["nodes"], sub_idx, hub=h["hub"])
        feeder_frame = df.loc[h["feeder_idx"]]
        candidates.append((ring, feeder_frame, h))

    covered = [set(r.nodes) for r, _, _ in candidates]
    for comm in analysis.communities:
        if not (max(4, settings.min_ring_size) <= len(comm) <= settings.max_ring_size):
            continue
        if any(len(comm & c) / len(comm) >= 0.6 for c in covered):
            continue
        sub = G.subgraph(comm)
        if nx.density(sub) < settings.cluster_min_density or sub.number_of_edges() < 1.5 * len(comm):
            continue
        sub_idx = _internal_frame(df, comm).index.tolist()
        candidates.append((Ring("dense_cluster", sorted(comm), sub_idx), None, None))

    scored = []
    for ring, amount_frame, extra in candidates:
        if not ring.tx_index:
            continue
        _score(ring, df, G, has_ts, settings, amount_frame=amount_frame, extra=extra)
        ring.roles = _roles(ring, analysis, extra)
        if ring.score >= settings.ring_report_min_score:
            scored.append(ring)

    scored.sort(key=lambda r: r.score, reverse=True)
    kept = []
    for ring in scored:
        nodes = set(ring.nodes)
        if any(len(nodes & set(k.nodes)) / len(nodes | set(k.nodes)) > 0.8 for k in kept):
            continue
        kept.append(ring)

    for i, ring in enumerate(kept, 1):
        ring.code = f"FR-{i:03d}"
        ring.reasons = _explain(ring, settings)
    return kept
