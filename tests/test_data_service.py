import io

import pandas as pd
import pytest

from app.services.data_service import DataValidationError, clean_transactions, map_columns, read_csv


def test_map_columns_recognises_paysim_layout():
    cols = ["step", "type", "amount", "nameOrig", "nameDest", "isFraud"]
    mapping = map_columns(cols)
    assert mapping["sender"] == "nameOrig"
    assert mapping["receiver"] == "nameDest"
    assert mapping["is_fraud"] == "isFraud"


def test_clean_transactions_drops_bad_rows():
    df = pd.DataFrame({
        "sender": ["A", "B", "A", ""], "receiver": ["B", "A", "A", "C"],
        "amount": ["100", "-5", "50", "20"], "timestamp": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
    })
    result = clean_transactions(df)
    assert len(result.df) == 1  # row0 kept; row1 negative, row2 self-loop, row3 missing sender
    assert result.report["rows_out"] == 1


def test_clean_transactions_requires_columns():
    with pytest.raises(DataValidationError):
        clean_transactions(pd.DataFrame({"foo": [1], "bar": [2]}))


def test_read_csv_rejects_too_many_rows():
    csv_bytes = b"sender,receiver,amount\n" + b"A,B,10\n" * 20
    with pytest.raises(DataValidationError):
        read_csv(io.BytesIO(csv_bytes), max_rows=5)


def test_read_csv_rejects_empty_file():
    with pytest.raises(DataValidationError):
        read_csv(io.BytesIO(b""), max_rows=100)
