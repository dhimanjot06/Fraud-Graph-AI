import pandas as pd

from app.services.fraud_ring_service import detect_rings
from app.services.graph_service import analyse_graph
from app.services.settings import DetectionSettings


def test_detect_rings_finds_planted_cycle():
    rows = []
    base_time = pd.Timestamp("2026-01-01")
    for i in range(3):
        for j, (s, r) in enumerate([("A", "B"), ("B", "C"), ("C", "A")]):
            rows.append((s, r, 1000 * (1 + 0.01 * j), base_time + pd.Timedelta(hours=i * 5 + j)))
    df = pd.DataFrame(rows, columns=["sender", "receiver", "amount", "timestamp"])
    settings = DetectionSettings()
    analysis = analyse_graph(df, True, settings)
    rings = detect_rings(df, analysis, True, settings)
    assert any(r.ring_type == "cycle" and set(r.nodes) == {"A", "B", "C"} for r in rings)
    ring = next(r for r in rings if r.ring_type == "cycle")
    assert 0 <= ring.score <= 100
    assert ring.reasons


def test_detect_rings_empty_graph_returns_nothing():
    df = pd.DataFrame(columns=["sender", "receiver", "amount", "timestamp"])
    settings = DetectionSettings()
    analysis = analyse_graph(df, True, settings)
    assert detect_rings(df, analysis, True, settings) == []
