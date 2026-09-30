"""Risk aggregation and the end-to-end analysis pipeline.

Pipeline: features -> Isolation Forest -> graph -> loops/communities/centrality
-> ring detection & scoring -> transaction and account risk -> summary.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ml.evaluation import evaluate_rings, evaluate_transactions

from .anomaly_service import detect_anomalies, explain_row
from .fraud_ring_service import TYPE_LABELS, detect_rings
from .graph_service import analyse_graph
from .settings import DetectionSettings

ANOMALY_WEIGHT = 0.60
RING_WEIGHT = 0.95


@dataclass
class AnalysisResult:
    summary: dict
    rings: list
    accounts: list
    transactions: list
    tx_risk: pd.Series = field(repr=False, default=None)


def sharpen(percentile):
    """Only the most unusual ~10% of transactions contribute; the top 1% contribute strongly."""
    return ((percentile - 0.90) / 0.10).clip(lower=0.0, upper=1.0) ** 2


def _noisy_or(*terms):
    """Combine independent risk signals: any strong signal lifts the total."""
    remaining = 1.0
    for t in terms:
        remaining *= 1.0 - float(np.clip(t, 0.0, 1.0))
    return 1.0 - remaining


def analyze(df: pd.DataFrame, has_timestamps: bool, settings: DetectionSettings,
            clean_report: dict | None = None, truth: list | None = None) -> AnalysisResult:
    stages, warnings = [], list((clean_report or {}).get("warnings", []))

    def stage(name, note, fn):
        t0 = time.perf_counter()
        out = fn()
        stages.append({"name": name, "seconds": round(time.perf_counter() - t0, 2), "note": note(out)})
        return out

    anomaly = stage("Anomaly detection", lambda a: "Isolation Forest scored each transaction on its own" if a.used_model else "Skipped: too few rows",
                    lambda: detect_anomalies(df, has_timestamps, settings))
    warnings += anomaly.warnings
    graph = stage("Network analysis",
                  lambda g: f"{g.stats['nodes']:,} accounts, {g.stats['edges']:,} links, {g.stats['round_trip_loops']} coherent loops, {g.stats['communities']} communities",
                  lambda: analyse_graph(df, has_timestamps, settings))
    warnings += graph.warnings
    rings = stage("Ring detection", lambda r: f"{len(r)} rings scored above {settings.ring_report_min_score:.0f}",
                  lambda: detect_rings(df, graph, has_timestamps, settings))

    # Transaction risk: individual oddness combined with network context.
    tx_ring, tx_ring_score = {}, {}
    for ring in rings:
        for i in ring.tx_index:
            if ring.score > tx_ring_score.get(i, -1):
                tx_ring[i], tx_ring_score[i] = ring, ring.score
    graph_component = pd.Series(0.0, index=df.index)
    for i, sc in tx_ring_score.items():
        graph_component.at[i] = sc / 100.0
    anomaly_component = sharpen(anomaly.scores)
    tx_risk = 100.0 * (1 - (1 - ANOMALY_WEIGHT * anomaly_component) * (1 - RING_WEIGHT * graph_component))
    tx_risk = tx_risk.round(1)

    flagged_idx = tx_risk[tx_risk >= settings.tx_flag_threshold].sort_values(ascending=False)
    transactions = []
    for i in flagged_idx.index[: settings.max_stored_transactions]:
        row = df.loc[i]
        reasons = []
        if i in tx_ring:
            r = tx_ring[i]
            reasons.append(f"Part of {r.code} ({TYPE_LABELS[r.ring_type].lower()}, ring risk {r.score:.0f}/100)")
        if anomaly_component.at[i] >= 0.5:
            reasons += explain_row(anomaly.zscores.loc[i]) or ["Unusual compared with the rest of the dataset"]
        transactions.append({
            "tx_id": row["transaction_id"], "sender": row["sender"], "receiver": row["receiver"],
            "amount": float(row["amount"]),
            "timestamp": row["timestamp"].isoformat() if has_timestamps else None,
            "risk_score": float(tx_risk.at[i]), "anomaly_score": round(float(anomaly.scores.at[i]), 3),
            "ring_code": tx_ring[i].code if i in tx_ring else None, "reasons": reasons,
        })

    accounts = _score_accounts(df, rings, anomaly_component, graph, settings)

    fraud_rings_amount = float(sum(r.metrics["total_amount"] for r in rings))
    summary = {
        "total_transactions": int(len(df)),
        "total_accounts": int(graph.stats["nodes"]),
        "total_amount": round(float(df["amount"].sum()), 2),
        "flagged_transactions": int((tx_risk >= settings.tx_flag_threshold).sum()),
        "high_risk_accounts": sum(1 for a in accounts if a["level"] == "high"),
        "medium_risk_accounts": sum(1 for a in accounts if a["level"] == "medium"),
        "rings_total": len(rings),
        "rings_high": sum(1 for r in rings if r.level == "high"),
        "rings_medium": sum(1 for r in rings if r.level == "medium"),
        "amount_in_rings": round(fraud_rings_amount, 2),
        "ring_types": {t: sum(1 for r in rings if r.ring_type == t) for t in TYPE_LABELS},
        "graph": graph.stats,
        "stages": stages,
        "warnings": warnings,
        "settings": settings.to_dict(),
        "has_timestamps": has_timestamps,
        "clean_report": clean_report or {},
    }

    evaluation = {}
    if "is_fraud" in df.columns:
        evaluation["transactions"] = evaluate_transactions(tx_risk, df["is_fraud"], settings.tx_flag_threshold)
        evaluation["anomaly_only"] = evaluate_transactions(anomaly_component * 60.0, df["is_fraud"], settings.tx_flag_threshold)
    if truth:
        evaluation["rings"] = evaluate_rings(
            [{"code": r.code, "nodes": r.nodes} for r in rings], truth)
    if evaluation:
        summary["evaluation"] = evaluation

    return AnalysisResult(summary=summary, rings=rings, accounts=accounts, transactions=transactions, tx_risk=tx_risk)


def _score_accounts(df, rings, anomaly_scores, graph, settings):
    ring_by_account = {}
    for ring in rings:
        for n in ring.nodes:
            ring_by_account.setdefault(n, []).append(ring)

    sent = pd.DataFrame({"account": df["sender"], "a": anomaly_scores})
    recv = pd.DataFrame({"account": df["receiver"], "a": anomaly_scores})
    p90 = pd.concat([sent, recv]).groupby("account")["a"].quantile(0.9)
    pr = pd.Series(graph.pagerank)
    pr_pct = pr.rank(pct=True) if len(pr) else pr
    G = graph.graph

    accounts = []
    for account in G.nodes:
        rs = ring_by_account.get(account, [])
        ring_component = max((r.score for r in rs), default=0.0) / 100.0
        anomaly_component = float(p90.get(account, 0.0))
        central = float(pr_pct.get(account, 0.0))
        score = 100.0 * _noisy_or(RING_WEIGHT * ring_component, 0.45 * anomaly_component, 0.15 * central)
        if score < 40 and not rs:
            continue
        reasons = [f"Member of {r.code}: {TYPE_LABELS[r.ring_type].lower()} (ring risk {r.score:.0f}/100, role: {r.roles.get(account, 'member')})"
                   for r in sorted(rs, key=lambda r: -r.score)]
        if anomaly_component >= 0.95:
            reasons.append("Some of its transactions are highly unusual on their own")
        if central >= 0.98 and G.degree(account) >= 5:
            reasons.append("Sits at the centre of many transfer links")
        accounts.append({
            "account": account, "risk_score": round(score, 1), "level": settings.level(score),
            "sent": int(G.out_degree(account, weight="count")), "received": int(G.in_degree(account, weight="count")),
            "counterparties": int(len(set(G.successors(account)) | set(G.predecessors(account)))),
            "ring_codes": [r.code for r in rs], "reasons": reasons,
        })
    accounts.sort(key=lambda a: -a["risk_score"])
    return accounts[: settings.max_stored_accounts]
