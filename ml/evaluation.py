"""Metrics for labelled data and known ring structures. Pure NumPy/pandas/sklearn."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def evaluate_transactions(risk: pd.Series, labels: pd.Series, threshold: float) -> dict:
    """Precision, recall and F1 at ``threshold`` plus ranking quality."""
    y = labels.astype(bool).to_numpy()
    flagged = (risk >= threshold).to_numpy()
    tp = int((flagged & y).sum())
    fp = int((flagged & ~y).sum())
    fn = int((~flagged & y).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    k = int(y.sum())
    top_k = np.argsort(-risk.to_numpy(), kind="stable")[:k] if k else np.array([], dtype=int)
    precision_at_k = float(y[top_k].mean()) if k else 0.0
    auc = float(roc_auc_score(y, risk)) if 0 < y.sum() < len(y) else None
    return {
        "threshold": threshold,
        "labelled_fraud": int(y.sum()),
        "flagged": int(flagged.sum()),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "precision_at_k": round(precision_at_k, 3),
        "roc_auc": None if auc is None else round(auc, 3),
    }


def _jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def evaluate_rings(detected: list, truth: list, min_overlap: float = 0.5) -> dict:
    """Match detected rings to planted rings by account-set overlap (Jaccard)."""
    matched_truth, matched_detected, details = set(), set(), []
    for t in truth:
        best, best_j = None, 0.0
        for i, d in enumerate(detected):
            j = _jaccard(t["accounts"], d["nodes"])
            if j > best_j:
                best, best_j = i, j
        hit = best is not None and best_j >= min_overlap
        if hit:
            matched_truth.add(t["ring_id"])
            matched_detected.add(best)
        details.append({
            "truth_id": t["ring_id"], "type": t["type"], "accounts": len(t["accounts"]),
            "found": hit, "overlap": round(best_j, 2),
            "detected_as": detected[best]["code"] if hit else None,
        })
    n_truth, n_det = len(truth), len(detected)
    return {
        "planted_rings": n_truth,
        "detected_rings": n_det,
        "rings_found": len(matched_truth),
        "ring_recall": round(len(matched_truth) / n_truth, 3) if n_truth else None,
        "ring_precision": round(len(matched_detected) / n_det, 3) if n_det else None,
        "details": details,
    }
