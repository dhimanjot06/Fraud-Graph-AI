"""Typed detection settings shared by every analysis service."""
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class DetectionSettings:
    # Presentation
    currency_symbol: str = "₹"

    # Input limits
    max_rows: int = 250_000

    # Transaction-level anomaly detection (Isolation Forest)
    if_n_estimators: int = 200
    random_state: int = 42
    min_rows_for_model: int = 30

    # Round-trip (cycle) search
    max_cycle_length: int = 6
    cycle_amount_tolerance: float = 0.25   # neighbouring legs may differ by at most this ratio
    cycle_window_hours: int = 168          # all legs must first appear within this span
    max_cycles: int = 5000
    max_dfs_expansions: int = 3_000_000

    # Ring candidates
    min_ring_size: int = 3
    max_ring_size: int = 40
    louvain_resolution: float = 1.0
    cluster_min_density: float = 0.45
    hub_min_senders: int = 5
    hub_amount_cv_max: float = 0.30
    hub_min_forward_ratio: float = 0.5
    time_window_hours: int = 72

    # Scoring and levels
    ring_report_min_score: float = 50.0
    high_threshold: float = 75.0
    medium_threshold: float = 50.0
    tx_flag_threshold: float = 50.0

    # Storage caps
    max_stored_transactions: int = 2000
    max_stored_accounts: int = 1000

    @classmethod
    def from_mapping(cls, mapping):
        names = {f.name for f in fields(cls)}
        return cls(**{k.lower(): v for k, v in (mapping or {}).items() if k.lower() in names})

    def to_dict(self):
        return asdict(self)

    def level(self, score):
        if score >= self.high_threshold:
            return "high"
        if score >= self.medium_threshold:
            return "medium"
        return "low"


def get_settings():
    """Build settings from the active Flask app config."""
    from flask import current_app

    return DetectionSettings.from_mapping(current_app.config.get("DETECTION", {}))
