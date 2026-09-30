import pandas as pd

from app.services.graph_service import analyse_graph, build_graph, find_round_trips
from app.services.settings import DetectionSettings


def _tx(rows):
    return pd.DataFrame(rows, columns=["sender", "receiver", "amount", "timestamp"]).assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"]))


def test_build_graph_aggregates_parallel_edges():
    df = _tx([("A", "B", 100, "2026-01-01"), ("A", "B", 200, "2026-01-02")])
    G = build_graph(df, True)
    assert G["A"]["B"]["count"] == 2
    assert G["A"]["B"]["total"] == 300


def test_find_round_trips_detects_a_simple_cycle():
    df = _tx([
        ("A", "B", 1000, "2026-01-01 09:00"),
        ("B", "C", 990, "2026-01-01 10:00"),
        ("C", "A", 985, "2026-01-01 11:00"),
    ])
    G = build_graph(df, True)
    cycles, warnings = find_round_trips(G, DetectionSettings(), True)
    assert any(set(c) == {"A", "B", "C"} for c in cycles)


def test_find_round_trips_ignores_mismatched_amounts():
    df = _tx([
        ("A", "B", 1000, "2026-01-01 09:00"),
        ("B", "C", 50, "2026-01-01 10:00"),   # far smaller: not a coherent loop leg
        ("C", "A", 980, "2026-01-01 11:00"),
    ])
    G = build_graph(df, True)
    cycles, _ = find_round_trips(G, DetectionSettings(), True)
    assert not any(set(c) == {"A", "B", "C"} for c in cycles)


def test_analyse_graph_runs_on_empty_frame():
    df = _tx([])
    analysis = analyse_graph(df, True, DetectionSettings())
    assert analysis.stats["nodes"] == 0
    assert analysis.cycles == []
