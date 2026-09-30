import csv
import io
import json
import logging
import os

from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for)

from app.models import analysis as analysis_model
from app.models import dataset as dataset_model
from app.services import data_service, risk_service
from app.services.settings import get_settings
from app.utils.security import login_required

bp = Blueprint("analysis", __name__, url_prefix="/analysis")
log = logging.getLogger(__name__)


def _own_run(run_id):
    run = analysis_model.get_run(run_id, g.user["id"])
    if run is None:
        abort(404)
    return run


@bp.route("/")
@login_required
def index():
    return render_template("analysis/index.html", runs=analysis_model.list_runs(g.user["id"]))


@bp.route("/run/<int:dataset_id>", methods=["POST"])
@login_required
def run(dataset_id):
    ds = dataset_model.get_dataset(dataset_id, g.user["id"])
    if ds is None:
        abort(404)
    run_id = analysis_model.create_run(g.user["id"], dataset_id)
    try:
        df = data_service.load_processed(ds["processed_path"], bool(ds["has_labels"]))
        truth = None
        truth_path = ds["meta"].get("truth_path")
        if truth_path and os.path.isfile(truth_path):
            with open(truth_path) as fh:
                truth = json.load(fh)
        result = risk_service.analyze(df, bool(ds["has_timestamps"]), get_settings(),
                                      ds["meta"].get("report"), truth)
        analysis_model.save_result(run_id, result)
    except Exception:
        log.exception("Analysis %s failed", run_id)
        analysis_model.fail_run(run_id, "The analysis stopped unexpectedly. Check the server log for details.")
        flash("The analysis could not finish. The dataset is unchanged; try again or check the server log.", "error")
        return redirect(url_for("upload.index"))
    return redirect(url_for("analysis.results", run_id=run_id))


@bp.route("/<int:run_id>")
@login_required
def results(run_id):
    run = _own_run(run_id)
    if run["status"] != "done":
        flash(run.get("error") or "This analysis did not finish.", "error")
        return redirect(url_for("analysis.index"))
    return render_template(
        "analysis/results.html", run=run, summary=run,
        rings=analysis_model.get_rings(run_id),
        accounts=analysis_model.get_accounts(run_id, 40),
        transactions=analysis_model.get_transactions(run_id, 60),
    )


@bp.route("/<int:run_id>/rings/<code>")
@login_required
def ring(run_id, code):
    run = _own_run(run_id)
    ring = analysis_model.get_ring(run_id, code)
    if ring is None:
        abort(404)
    levels = analysis_model.get_account_levels(run_id, ring["nodes"])
    members = sorted(
        ({"account": n, "role": ring["roles"].get(n, "member"),
          "risk": levels.get(n, (None, None))[0], "level": levels.get(n, (None, "low"))[1]} for n in ring["nodes"]),
        key=lambda m: -(m["risk"] or 0))
    return render_template("analysis/ring.html", run=run, ring=ring, members=members,
                           transactions=analysis_model.get_transactions(run_id, 200, ring_code=code))


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in exported cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@bp.route("/<int:run_id>/export/<kind>.csv")
@login_required
def export(run_id, kind):
    _own_run(run_id)
    if kind == "rings":
        header = ["ring", "type", "risk_score", "level", "accounts", "total_amount", "reasons"]
        rows = [[r["code"], r["ring_type"], r["risk_score"], r["level"], r["size"], r["total_amount"],
                 " | ".join(r["reasons"])] for r in analysis_model.get_rings(run_id)]
    elif kind == "accounts":
        header = ["account", "risk_score", "level", "sent", "received", "counterparties", "rings", "reasons"]
        rows = [[a["account"], a["risk_score"], a["level"], a["sent"], a["received"], a["counterparties"],
                 " ".join(a["ring_codes"]), " | ".join(a["reasons"])]
                for a in analysis_model.get_accounts(run_id, 100000)]
    elif kind == "transactions":
        header = ["transaction_id", "sender", "receiver", "amount", "timestamp", "risk_score", "ring", "reasons"]
        rows = [[t["tx_id"], t["sender"], t["receiver"], t["amount"], t["timestamp"], t["risk_score"],
                 t["ring_code"] or "", " | ".join(t["reasons"])]
                for t in analysis_model.get_transactions(run_id, 100000)]
    else:
        abort(404)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows([[_csv_safe(c) for c in row] for row in rows])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=fraudgraph_run{run_id}_{kind}.csv"})
