"""Persistence for analysis runs and their results."""
import json

from .database import get_db


def _load(row, key="data_json"):
    d = dict(row)
    d.update(json.loads(d.pop(key) or "{}"))
    return d


def create_run(user_id, dataset_id):
    db = get_db()
    cur = db.execute("INSERT INTO analysis_runs (user_id, dataset_id) VALUES (?, ?)", (user_id, dataset_id))
    db.commit()
    return cur.lastrowid


def fail_run(run_id, message):
    db = get_db()
    db.execute("UPDATE analysis_runs SET status = 'failed', error = ?, finished_at = datetime('now') WHERE id = ?",
               (message, run_id))
    db.commit()


def save_result(run_id, result):
    """Store a finished ``AnalysisResult`` in one transaction."""
    db = get_db()
    with db:
        db.execute(
            "UPDATE analysis_runs SET status = 'done', summary_json = ?, finished_at = datetime('now') WHERE id = ?",
            (json.dumps(result.summary, default=str), run_id))
        for ring in result.rings:
            data = {
                "components": ring.components, "reasons": ring.reasons, "metrics": ring.metrics,
                "roles": ring.roles, "edges": ring.edges, "nodes": ring.nodes, "loops": ring.loops[:10],
                "hub": ring.hub,
            }
            db.execute(
                """INSERT INTO fraud_rings (run_id, code, ring_type, risk_score, level, size, total_amount, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, ring.code, ring.ring_type, ring.score, ring.level, len(ring.nodes),
                 ring.metrics["total_amount"], json.dumps(data)))
        db.executemany(
            "INSERT INTO account_risks (run_id, account, risk_score, level, data_json) VALUES (?, ?, ?, ?, ?)",
            [(run_id, a["account"], a["risk_score"], a["level"],
              json.dumps({k: a[k] for k in ("sent", "received", "counterparties", "ring_codes", "reasons")}))
             for a in result.accounts])
        db.executemany(
            """INSERT INTO flagged_transactions (run_id, tx_id, sender, receiver, amount, timestamp, risk_score, ring_code, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(run_id, t["tx_id"], t["sender"], t["receiver"], t["amount"], t["timestamp"], t["risk_score"],
              t["ring_code"], json.dumps({"anomaly_score": t["anomaly_score"], "reasons": t["reasons"]}))
             for t in result.transactions])


def get_run(run_id, user_id):
    row = get_db().execute(
        """SELECT r.*, d.name AS dataset_name FROM analysis_runs r JOIN datasets d ON d.id = r.dataset_id
           WHERE r.id = ? AND r.user_id = ?""", (run_id, user_id)).fetchone()
    return _load(row, "summary_json") if row else None


def list_runs(user_id, limit=50):
    rows = get_db().execute(
        """SELECT r.id, r.status, r.created_at, r.finished_at, r.summary_json, r.error, d.name AS dataset_name, d.id AS dataset_id
           FROM analysis_runs r JOIN datasets d ON d.id = r.dataset_id
           WHERE r.user_id = ? ORDER BY r.id DESC LIMIT ?""", (user_id, limit)).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        summary = json.loads(d.pop("summary_json") or "{}")
        d["summary"] = {k: summary.get(k) for k in (
            "total_transactions", "total_accounts", "flagged_transactions", "high_risk_accounts",
            "rings_total", "rings_high")}
        out.append(d)
    return out


def latest_done_run(user_id):
    row = get_db().execute(
        "SELECT id FROM analysis_runs WHERE user_id = ? AND status = 'done' ORDER BY id DESC LIMIT 1",
        (user_id,)).fetchone()
    return get_run(row["id"], user_id) if row else None


def get_rings(run_id):
    rows = get_db().execute("SELECT * FROM fraud_rings WHERE run_id = ? ORDER BY risk_score DESC", (run_id,)).fetchall()
    return [_load(r) for r in rows]


def get_ring(run_id, code):
    row = get_db().execute("SELECT * FROM fraud_rings WHERE run_id = ? AND code = ?", (run_id, code)).fetchone()
    return _load(row) if row else None


def get_accounts(run_id, limit=500):
    rows = get_db().execute(
        "SELECT * FROM account_risks WHERE run_id = ? ORDER BY risk_score DESC LIMIT ?", (run_id, limit)).fetchall()
    return [_load(r) for r in rows]


def get_account_levels(run_id, accounts):
    """Return {account: (score, level)} for the given accounts."""
    if not accounts:
        return {}
    marks = ",".join("?" * len(accounts))
    rows = get_db().execute(
        f"SELECT account, risk_score, level FROM account_risks WHERE run_id = ? AND account IN ({marks})",
        [run_id, *accounts]).fetchall()
    return {r["account"]: (r["risk_score"], r["level"]) for r in rows}


def get_transactions(run_id, limit=500, ring_code=None):
    sql, params = "SELECT * FROM flagged_transactions WHERE run_id = ?", [run_id]
    if ring_code:
        sql += " AND ring_code = ?"
        params.append(ring_code)
    sql += " ORDER BY risk_score DESC LIMIT ?"
    params.append(limit)
    return [_load(r) for r in get_db().execute(sql, params).fetchall()]
