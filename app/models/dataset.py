import json
import os

from .database import get_db


def create_dataset(user_id, name, source, original_name, upload_path, processed_path,
                   rows, accounts, has_timestamps, has_labels, meta):
    db = get_db()
    cur = db.execute(
        """INSERT INTO datasets (user_id, name, source, original_name, upload_path, processed_path,
                                 rows, accounts, has_timestamps, has_labels, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, name, source, original_name, upload_path, processed_path, rows, accounts,
         int(has_timestamps), int(has_labels), json.dumps(meta)),
    )
    db.commit()
    return cur.lastrowid


def _decorate(row):
    if row is None:
        return None
    d = dict(row)
    d["meta"] = json.loads(d.pop("meta_json") or "{}")
    return d


def list_datasets(user_id):
    rows = get_db().execute(
        """SELECT d.*, (SELECT COUNT(*) FROM analysis_runs r WHERE r.dataset_id = d.id AND r.status = 'done') AS runs,
                  (SELECT MAX(id) FROM analysis_runs r WHERE r.dataset_id = d.id AND r.status = 'done') AS last_run_id
           FROM datasets d WHERE d.user_id = ? ORDER BY d.id DESC""", (user_id,)).fetchall()
    return [_decorate(r) for r in rows]


def get_dataset(dataset_id, user_id):
    row = get_db().execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user_id)).fetchone()
    return _decorate(row)


def delete_dataset(dataset_id, user_id):
    ds = get_dataset(dataset_id, user_id)
    if not ds:
        return False
    db = get_db()
    db.execute("DELETE FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user_id))
    db.commit()
    paths = [ds["upload_path"], ds["processed_path"], ds["meta"].get("truth_path")]
    for path in paths:
        if path and os.path.isfile(path):
            os.remove(path)
    return True
