"""Benchmark the hybrid pipeline against a transaction-only baseline.

Usage (from the project root):
    python -m ml.benchmark                # 10 seeds, default sizes
    python -m ml.benchmark --seeds 3 --accounts 1200 --normal 15000
"""
from __future__ import annotations

import argparse

import numpy as np
from sklearn.metrics import roc_auc_score

from app.services.data_service import clean_transactions
from app.services.risk_service import analyze
from app.services.settings import DetectionSettings
from ml.baseline import transaction_only_scores
from ml.synthetic import generate


def run(seeds=10, accounts=600, normal=6000):
    settings = DetectionSettings()
    rows = []
    for seed in range(1, seeds + 1):
        df, truth = generate(n_accounts=accounts, n_normal=normal, seed=seed)
        clean = clean_transactions(df.astype(str))
        result = analyze(clean.df, True, settings, clean.report, truth)
        y = clean.df["is_fraud"].astype(bool).to_numpy()
        base_scores = transaction_only_scores(clean.df, True, settings)
        k = int(y.sum())
        top = lambda s: float(y[np.argsort(-s.to_numpy(), kind="stable")[:k]].mean())
        ev = result.summary["evaluation"]
        rows.append({
            "seed": seed,
            "ring_recall": ev["rings"]["ring_recall"],
            "high_ring_precision": _high_precision(result, truth),
            "baseline_auc": roc_auc_score(y, base_scores),
            "hybrid_auc": roc_auc_score(y, result.tx_risk),
            "baseline_p@k": top(base_scores),
            "hybrid_p@k": top(result.tx_risk),
        })
    return rows


def _high_precision(result, truth):
    from ml.evaluation import _jaccard
    high = [r for r in result.rings if r.level == "high"]
    if not high:
        return None
    hits = sum(1 for r in high if any(_jaccard(t["accounts"], r.nodes) >= 0.5 for t in truth))
    return hits / len(high)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--accounts", type=int, default=600)
    ap.add_argument("--normal", type=int, default=6000)
    args = ap.parse_args()
    rows = run(args.seeds, args.accounts, args.normal)

    header = f"{'seed':>4} {'ring recall':>12} {'high-ring prec':>15} {'AUC base':>9} {'AUC hybrid':>11} {'P@K base':>9} {'P@K hybrid':>11}"
    print(header)
    print("-" * len(header))
    for r in rows:
        hp = "n/a" if r["high_ring_precision"] is None else f"{r['high_ring_precision']:.2f}"
        print(f"{r['seed']:>4} {r['ring_recall']:>12.2f} {hp:>15} {r['baseline_auc']:>9.3f} {r['hybrid_auc']:>11.3f} "
              f"{r['baseline_p@k']:>9.2f} {r['hybrid_p@k']:>11.2f}")
    mean = lambda k: np.nanmean([r[k] if r[k] is not None else np.nan for r in rows])
    print("-" * len(header))
    print(f"{'mean':>4} {mean('ring_recall'):>12.2f} {mean('high_ring_precision'):>15.2f} {mean('baseline_auc'):>9.3f} "
          f"{mean('hybrid_auc'):>11.3f} {mean('baseline_p@k'):>9.2f} {mean('hybrid_p@k'):>11.2f}")
    print("\nAUC = ROC-AUC on the labelled fraud transactions. P@K = precision among the K highest-risk "
          "transactions, where K is the number of labelled fraud transactions.")


if __name__ == "__main__":
    main()
