"""Layer 1: transaction-level anomaly detection with an Isolation Forest."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .data_service import to_epoch_seconds
from .settings import DetectionSettings

FEATURE_PHRASES = {
    "amount_vs_sender_median": "The amount is unusually large compared with this sender's normal payments",
    "amount_z_sender": "The amount is far outside this sender's usual range",
    "log_amount": "The amount is unusually large for this dataset",
    "sender_tx_count": "The sender is unusually active",
    "receiver_tx_count": "The receiver handles an unusual number of transactions",
    "sender_unique_receivers": "The sender pays an unusually wide set of accounts",
    "receiver_unique_senders": "The receiver collects from an unusually wide set of accounts",
    "pair_count": "These two accounts transact with each other unusually often",
    "reverse_exists": "Money also flows back the other way between these accounts",
    "hour_sin": "The payment happened at an unusual time of day",
    "hour_cos": "The payment happened at an unusual time of day",
    "sender_gap": "The sender made this payment unusually soon after the previous one",
}


@dataclass
class AnomalyResult:
    scores: pd.Series            # 0..1, higher = more unusual (percentile rank)
    zscores: pd.DataFrame        # robust z-scores per feature, for explanations
    used_model: bool
    warnings: list


def build_features(df: pd.DataFrame, has_timestamps: bool) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    amount = df["amount"]
    by_sender = df.groupby("sender")["amount"]
    f["log_amount"] = np.log1p(amount)
    f["amount_vs_sender_median"] = np.log1p(amount) - np.log1p(by_sender.transform("median"))
    std = by_sender.transform("std").fillna(0.0)
    f["amount_z_sender"] = ((amount - by_sender.transform("mean")) / (std + 1e-9)).clip(-5, 5)
    f["sender_tx_count"] = np.log1p(by_sender.transform("count"))
    f["receiver_tx_count"] = np.log1p(df.groupby("receiver")["amount"].transform("count"))
    f["sender_unique_receivers"] = np.log1p(df.groupby("sender")["receiver"].transform("nunique"))
    f["receiver_unique_senders"] = np.log1p(df.groupby("receiver")["sender"].transform("nunique"))
    f["pair_count"] = np.log1p(df.groupby(["sender", "receiver"])["amount"].transform("count"))
    pairs = pd.MultiIndex.from_arrays([df["sender"], df["receiver"]])
    reverse = pd.MultiIndex.from_arrays([df["receiver"], df["sender"]])
    f["reverse_exists"] = reverse.isin(pairs).astype(float)

    if has_timestamps:
        hours = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
        f["hour_sin"] = np.sin(2 * np.pi * hours / 24)
        f["hour_cos"] = np.cos(2 * np.pi * hours / 24)
        gap = to_epoch_seconds(df["timestamp"]).groupby(df["sender"]).diff().clip(lower=0)
        f["sender_gap"] = np.log1p(gap).fillna(np.log1p(gap.median() if gap.notna().any() else 0.0))
    return f.replace([np.inf, -np.inf], 0.0).fillna(0.0)


def _robust_z(features: pd.DataFrame) -> pd.DataFrame:
    med = features.median()
    mad = (features - med).abs().median() * 1.4826
    scale = mad.where(mad > 1e-9, features.std().replace(0, 1.0)).fillna(1.0) + 1e-9
    return (features - med) / scale


def detect_anomalies(df: pd.DataFrame, has_timestamps: bool, settings: DetectionSettings) -> AnomalyResult:
    features = build_features(df, has_timestamps)
    zscores = _robust_z(features)
    if len(df) < settings.min_rows_for_model:
        return AnomalyResult(
            scores=pd.Series(0.0, index=df.index),
            zscores=zscores,
            used_model=False,
            warnings=[f"Only {len(df)} transactions: too few to train the anomaly model, so anomaly scores are set to zero."],
        )
    model = IsolationForest(n_estimators=settings.if_n_estimators, contamination="auto",
                            random_state=settings.random_state, n_jobs=-1)
    model.fit(features)
    raw = -model.score_samples(features)
    scores = pd.Series(raw, index=df.index).rank(pct=True)
    return AnomalyResult(scores=scores, zscores=zscores, used_model=True, warnings=[])


def explain_row(zrow: pd.Series, top: int = 2) -> list:
    """Plain-language drivers of an anomaly score for one transaction."""
    drivers, seen = [], set()
    for name, value in zrow.abs().sort_values(ascending=False).items():
        if value < 2.5 or name not in FEATURE_PHRASES:
            continue
        phrase = FEATURE_PHRASES[name]
        if phrase in seen:
            continue
        seen.add(phrase)
        drivers.append(phrase)
        if len(drivers) >= top:
            break
    return drivers
