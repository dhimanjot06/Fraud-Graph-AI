"""Loading, validating and cleaning transaction files.

Accepts our own column names as well as common public-dataset layouts
(e.g. PaySim: ``nameOrig``/``nameDest``/``step``/``isFraud``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

BASE_EPOCH = pd.Timestamp("2026-01-01")

ALIASES = {
    "transaction_id": ["transaction_id", "transactionid", "tx_id", "txn_id", "trans_num", "id"],
    "sender": ["sender", "source", "nameorig", "from", "from_account", "sender_id",
               "originator", "orig", "account_from", "payer"],
    "receiver": ["receiver", "target", "namedest", "to", "to_account", "receiver_id",
                 "beneficiary", "dest", "account_to", "payee"],
    "amount": ["amount", "amt", "value", "transaction_amount"],
    "timestamp": ["timestamp", "time", "date", "datetime", "step", "transaction_date",
                  "trans_date_trans_time"],
    "is_fraud": ["is_fraud", "isfraud", "fraud", "label", "class"],
}
REQUIRED = ("sender", "receiver", "amount")
TRUTHY = {"1", "1.0", "true", "t", "yes", "y", "fraud"}


class DataValidationError(ValueError):
    """Raised with a user-readable message when a file cannot be analysed."""


@dataclass
class CleanResult:
    df: pd.DataFrame
    has_timestamps: bool
    has_labels: bool
    report: dict = field(default_factory=dict)


def normalise_name(name) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_")


def map_columns(columns) -> dict:
    """Return {canonical_name: original_column} for every recognised column."""
    norm = {normalise_name(c): c for c in columns}
    mapping, used = {}, set()
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            key = normalise_name(alias)
            if key in norm and norm[key] not in used:
                mapping[canonical] = norm[key]
                used.add(norm[key])
                break
    return mapping


def to_epoch_seconds(series: pd.Series) -> pd.Series:
    series = pd.to_datetime(series) if not pd.api.types.is_datetime64_any_dtype(series) else series
    return (series - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)


def read_csv(source, max_rows: int) -> pd.DataFrame:
    try:
        raw = pd.read_csv(source, dtype=str, skipinitialspace=True, nrows=max_rows + 1)
    except pd.errors.EmptyDataError as exc:
        raise DataValidationError("The file is empty.") from exc
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise DataValidationError("The file could not be read as a CSV. Check the delimiter and encoding (UTF-8).") from exc
    if raw.empty:
        raise DataValidationError("The file has a header but no transactions.")
    if len(raw) > max_rows:
        raise DataValidationError(
            f"The file has more than {max_rows:,} rows. Sample or filter it to {max_rows:,} rows or fewer and upload again."
        )
    return raw


def _parse_timestamps(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() > 0.95:
        if numeric.dropna().abs().median() > 1e9:      # unix seconds
            return pd.to_datetime(numeric, unit="s", errors="coerce")
        return BASE_EPOCH + pd.to_timedelta(numeric, unit="h")  # simulation "steps" = hours
    parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
    return parsed.dt.tz_convert(None)


def clean_transactions(raw: pd.DataFrame) -> CleanResult:
    mapping = map_columns(raw.columns)
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        found = ", ".join(map(str, raw.columns[:12]))
        raise DataValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Columns found: {found}. Rename them to sender, receiver and amount."
        )

    df = pd.DataFrame({name: raw[col] for name, col in mapping.items()})
    rows_in = len(df)
    dropped, warnings = {}, []

    def drop(mask, reason):
        nonlocal df
        n = int(mask.sum())
        if n:
            dropped[reason] = n
            df = df.loc[~mask]

    for col in ("sender", "receiver"):
        df[col] = df[col].astype("string").str.strip()
    drop(df["sender"].isna() | df["receiver"].isna() | (df["sender"] == "") | (df["receiver"] == ""),
         "missing sender or receiver")

    cleaned_amount = df["amount"].astype("string").str.replace(r"[^0-9.\-]", "", regex=True)
    df["amount"] = pd.to_numeric(cleaned_amount, errors="coerce")
    drop(df["amount"].isna(), "amount is not a number")
    drop(df["amount"] <= 0, "amount is zero or negative")
    drop(df["sender"] == df["receiver"], "sender and receiver are the same account")

    has_timestamps = "timestamp" in df.columns
    if has_timestamps:
        df["timestamp"] = _parse_timestamps(df["timestamp"])
        drop(df["timestamp"].isna(), "timestamp could not be read")
    else:
        warnings.append("No timestamp column found. Timing signals are switched off and ring scores use the remaining signals.")
        df["timestamp"] = BASE_EPOCH + pd.to_timedelta(range(len(df)), unit="s")

    if "transaction_id" in df.columns:
        df["transaction_id"] = df["transaction_id"].astype("string").str.strip()
        drop(df["transaction_id"].duplicated(keep="first"), "duplicate transaction id")
        blank = df["transaction_id"].isna() | (df["transaction_id"] == "")
        if blank.any():
            df.loc[blank, "transaction_id"] = [f"AUTO{i:07d}" for i in range(int(blank.sum()))]
    else:
        df["transaction_id"] = [f"TX{i:07d}" for i in range(1, len(df) + 1)]

    has_labels = "is_fraud" in df.columns
    if has_labels:
        df["is_fraud"] = df["is_fraud"].astype("string").str.strip().str.lower().isin(TRUTHY)

    if df.empty:
        raise DataValidationError("No usable transactions remain after cleaning. " +
                                  "; ".join(f"{v} rows: {k}" for k, v in dropped.items()))

    cols = ["transaction_id", "sender", "receiver", "amount", "timestamp"] + (["is_fraud"] if has_labels else [])
    df = df[cols].astype({"transaction_id": str, "sender": str, "receiver": str})
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)

    accounts = pd.unique(pd.concat([df["sender"], df["receiver"]]))
    report = {
        "rows_in": rows_in,
        "rows_out": len(df),
        "dropped": dropped,
        "warnings": warnings,
        "column_map": mapping,
        "accounts": int(len(accounts)),
        "has_timestamps": has_timestamps,
        "has_labels": has_labels,
        "date_start": df["timestamp"].min().isoformat() if has_timestamps else None,
        "date_end": df["timestamp"].max().isoformat() if has_timestamps else None,
    }
    return CleanResult(df=df, has_timestamps=has_timestamps, has_labels=has_labels, report=report)


def load_and_clean(source, max_rows: int) -> CleanResult:
    return clean_transactions(read_csv(source, max_rows))


def save_processed(df: pd.DataFrame, path) -> None:
    df.to_csv(path, index=False)


def load_processed(path, has_labels: bool = False) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"transaction_id": str, "sender": str, "receiver": str},
                     parse_dates=["timestamp"])
    if has_labels and "is_fraud" in df.columns:
        df["is_fraud"] = df["is_fraud"].astype(bool)
    return df
