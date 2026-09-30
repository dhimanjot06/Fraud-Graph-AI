from app.services.data_service import clean_transactions
from app.services.risk_service import analyze
from app.services.settings import DetectionSettings
from ml.synthetic import generate


def test_pipeline_recovers_planted_rings():
    df, truth = generate(n_accounts=300, n_normal=2000, n_cycle_rings=2, n_collector_rings=1, seed=42)
    clean = clean_transactions(df.astype(str))
    result = analyze(clean.df, True, DetectionSettings(), clean.report, truth)

    assert result.summary["rings_total"] > 0
    assert "evaluation" in result.summary
    assert result.summary["evaluation"]["rings"]["ring_recall"] >= 0.6


def test_pipeline_handles_no_labels_or_rings():
    import pandas as pd
    df = pd.DataFrame({
        "sender": [f"A{i}" for i in range(20)], "receiver": [f"A{(i + 1) % 20}" for i in range(20)],
        "amount": [100 + i for i in range(20)],
        "timestamp": pd.date_range("2026-01-01", periods=20, freq="h"),
    })
    clean = clean_transactions(df.astype(str))
    result = analyze(clean.df, True, DetectionSettings(), clean.report, truth=None)
    assert "evaluation" not in result.summary
    assert result.summary["total_transactions"] == 20


def test_pipeline_is_deterministic():
    df, truth = generate(n_accounts=200, n_normal=1200, seed=3)
    clean = clean_transactions(df.astype(str))
    settings = DetectionSettings()
    r1 = analyze(clean.df, True, settings, clean.report, truth)
    r2 = analyze(clean.df, True, settings, clean.report, truth)
    assert [r.code for r in r1.rings] == [r.code for r in r2.rings]
    assert [round(r.score, 3) for r in r1.rings] == [round(r.score, 3) for r in r2.rings]
