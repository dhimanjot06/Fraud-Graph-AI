"""Layer 2: build the account network and run graph analytics.

Every account is a node, every (sender, receiver) pair an edge carrying the
number of transfers, total and median amount and first/last timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd

from .data_service import to_epoch_seconds
from .settings import DetectionSettings


@dataclass
class GraphAnalysis:
    graph: nx.DiGraph
    cycles: list
    communities: list
    node_community: dict
    pagerank: dict
    betweenness: dict
    stats: dict
    warnings: list = field(default_factory=list)


def build_graph(df: pd.DataFrame, has_timestamps: bool) -> nx.DiGraph:
    work = df[["sender", "receiver", "amount"]].copy()
    work["ts"] = to_epoch_seconds(df["timestamp"]) if has_timestamps else np.nan
    agg = work.groupby(["sender", "receiver"], sort=False).agg(
        count=("amount", "size"), total=("amount", "sum"), med=("amount", "median"),
        first=("ts", "min"), last=("ts", "max"),
    )
    G = nx.DiGraph()
    for (s, r), row in agg.iterrows():
        G.add_edge(s, r, count=int(row["count"]), total=float(row["total"]), med=float(row["med"]),
                   first=None if pd.isna(row["first"]) else float(row["first"]),
                   last=None if pd.isna(row["last"]) else float(row["last"]),
                   weight=int(row["count"]))
    return G


def find_round_trips(G: nx.DiGraph, settings: DetectionSettings, has_timestamps: bool):
    """Enumerate coherent closed loops of length 3..max_cycle_length.

    A loop is only reported when neighbouring legs carry similar amounts and,
    if timestamps exist, every leg first appears inside one time window.
    This keeps the search tractable on dense networks and matches the
    behaviour of real round-tripping (money returns with little change, fast).
    """
    tol = 1.0 + settings.cycle_amount_tolerance
    window = settings.cycle_window_hours * 3600.0
    cycles, warnings = [], []
    expansions = 0
    budget_hit = False

    sccs = [c for c in nx.strongly_connected_components(G) if len(c) >= 3]
    for comp in sorted(sccs, key=len):
        order = {n: i for i, n in enumerate(sorted(comp))}
        sub = {n: [(m, G[n][m]) for m in G.successors(n) if m in comp] for n in comp}
        for start in sorted(comp, key=order.get):
            s_idx = order[start]
            # iterative DFS: stack of (node, iterator, path, prev_amount, tmin, tmax)
            stack = [(start, iter(sub[start]), [start], None, None, None)]
            while stack:
                node, it, path, prev_amt, tmin, tmax = stack[-1]
                advanced = False
                for nxt, edata in it:
                    expansions += 1
                    if expansions > settings.max_dfs_expansions:
                        budget_hit = True
                        break
                    amt = edata["med"]
                    if prev_amt is not None:
                        ratio = max(amt, prev_amt) / max(min(amt, prev_amt), 1e-9)
                        if ratio > tol:
                            continue
                    new_min, new_max = tmin, tmax
                    if has_timestamps and edata["first"] is not None:
                        new_min = edata["first"] if tmin is None else min(tmin, edata["first"])
                        new_max = edata["first"] if tmax is None else max(tmax, edata["first"])
                        if new_max - new_min > window:
                            continue
                    if nxt == start:
                        if len(path) >= 3:
                            first_amt = G[path[0]][path[1]]["med"]
                            if max(amt, first_amt) / max(min(amt, first_amt), 1e-9) <= tol:
                                cycles.append(list(path))
                        continue
                    if order.get(nxt, -1) <= s_idx or nxt in path or len(path) >= settings.max_cycle_length:
                        continue
                    stack.append((nxt, iter(sub[nxt]), path + [nxt], amt, new_min, new_max))
                    advanced = True
                    break
                if budget_hit or len(cycles) >= settings.max_cycles:
                    break
                if not advanced:
                    stack.pop()
            if budget_hit or len(cycles) >= settings.max_cycles:
                break
        if budget_hit or len(cycles) >= settings.max_cycles:
            break

    if budget_hit or len(cycles) >= settings.max_cycles:
        warnings.append("The loop search reached its safety limit, so very large networks may have unreported loops. Raise max_cycles or max_dfs_expansions to search further.")
    return cycles, warnings


def _louvain(UG: nx.Graph, settings: DetectionSettings, resolution: float):
    return [set(c) for c in nx.community.louvain_communities(
        UG, weight="weight", resolution=resolution, seed=settings.random_state)]


def detect_communities(G: nx.DiGraph, settings: DetectionSettings):
    """Louvain communities; oversized ones are split again so dense cores surface.

    Accounts are relabelled to integers first: NetworkX's Louvain iterates over
    sets, and string sets iterate in a hash-dependent order, which would make
    results differ between runs.
    """
    if G.number_of_nodes() == 0:
        return [], {}
    names = sorted(G.nodes)
    index = {n: i for i, n in enumerate(names)}
    UG = nx.Graph()
    UG.add_nodes_from(range(len(names)))
    for u, v, d in sorted(G.edges(data=True), key=lambda e: (index[e[0]], index[e[1]])):
        a, b = index[u], index[v]
        if UG.has_edge(a, b):
            UG[a][b]["weight"] += d["count"]
        else:
            UG.add_edge(a, b, weight=d["count"])

    final, queue = [], [(c, settings.louvain_resolution, 0) for c in _louvain(UG, settings, settings.louvain_resolution)]
    while queue:
        comm, res, depth = queue.pop()
        if len(comm) <= settings.max_ring_size or depth >= 3:
            final.append(comm)
            continue
        parts = _louvain(UG.subgraph(sorted(comm)), settings, res * 2.0)
        if len(parts) == 1:
            final.append(comm)
        else:
            queue.extend((p, res * 2.0, depth + 1) for p in parts)
    communities = sorted(({names[i] for i in c} for c in final), key=lambda c: min(c))
    node_community = {n: i for i, c in enumerate(communities) for n in c}
    return communities, node_community


def compute_centrality(G: nx.DiGraph, settings: DetectionSettings):
    n = G.number_of_nodes()
    if n == 0:
        return {}, {}
    pagerank = nx.pagerank(G, weight="count", max_iter=200)
    if n > 100_000:
        return pagerank, {}
    k = None if n <= 400 else 300
    betweenness = nx.betweenness_centrality(G, k=k, seed=settings.random_state, normalized=True)
    return pagerank, betweenness


def analyse_graph(df: pd.DataFrame, has_timestamps: bool, settings: DetectionSettings) -> GraphAnalysis:
    G = build_graph(df, has_timestamps)
    cycles, warnings = find_round_trips(G, settings, has_timestamps)
    communities, node_community = detect_communities(G, settings)
    pagerank, betweenness = compute_centrality(G, settings)
    sccs = [c for c in nx.strongly_connected_components(G) if len(c) >= 3]
    stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "density": nx.density(G) if G.number_of_nodes() > 1 else 0.0,
        "reciprocal_pairs": sum(1 for u, v in G.edges if u < v and G.has_edge(v, u)),
        "strongly_connected_groups": len(sccs),
        "largest_connected_group": max((len(c) for c in sccs), default=0),
        "communities": len(communities),
        "round_trip_loops": len(cycles),
    }
    return GraphAnalysis(G, cycles, communities, node_community, pagerank, betweenness, stats, warnings)
