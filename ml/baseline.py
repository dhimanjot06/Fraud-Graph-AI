"""Baselines to compare the graph pipeline against."""
from __future__ import annotations

import pandas as pd

from app.services.anomaly_service import detect_anomalies
from app.services.settings import DetectionSettings


def transaction_only_scores(df: pd.DataFrame, has_timestamps: bool, settings: DetectionSettings) -> pd.Series:
    """Isolation Forest on per-transaction features only (no ring detection). Scores 0..1."""
    return detect_anomalies(df, has_timestamps, settings).scores
