"""SQLite access for the app.

The schema is plain SQL so it ports directly to PostgreSQL (swap the driver and
the ``?`` placeholders for ``%s``). Connections are per request and use
foreign keys with cascading deletes.
"""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS datasets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'upload',
    original_name  TEXT,
    upload_path    TEXT NOT NULL,
    processed_path TEXT NOT NULL,
    rows           INTEGER NOT NULL,
    accounts       INTEGER NOT NULL,
    has_timestamps INTEGER NOT NULL DEFAULT 1,
    has_labels     INTEGER NOT NULL DEFAULT 0,
    meta_json      TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_datasets_user ON datasets(user_id);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dataset_id   INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'running',
    error        TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_user ON analysis_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_dataset ON analysis_runs(dataset_id);

CREATE TABLE IF NOT EXISTS fraud_rings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    code         TEXT NOT NULL,
    ring_type    TEXT NOT NULL,
    risk_score   REAL NOT NULL,
    level        TEXT NOT NULL,
    size         INTEGER NOT NULL,
    total_amount REAL NOT NULL,
    data_json    TEXT NOT NULL,
    UNIQUE (run_id, code)
);

CREATE TABLE IF NOT EXISTS account_risks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    account    TEXT NOT NULL,
    risk_score REAL NOT NULL,
    level      TEXT NOT NULL,
    data_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_run ON account_risks(run_id, risk_score DESC);

CREATE TABLE IF NOT EXISTS flagged_transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    tx_id      TEXT NOT NULL,
    sender     TEXT NOT NULL,
    receiver   TEXT NOT NULL,
    amount     REAL NOT NULL,
    timestamp  TEXT,
    risk_score REAL NOT NULL,
    ring_code  TEXT,
    data_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_run ON flagged_transactions(run_id, risk_score DESC);
"""


def get_db():
    if "db" not in g:
        path = current_app.config["DATABASE_PATH"]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    get_db().executescript(SCHEMA)
    get_db().commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
