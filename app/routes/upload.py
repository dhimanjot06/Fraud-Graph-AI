import io
import json
import logging
import os
import uuid

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template,
                   request, url_for)
from werkzeug.utils import secure_filename

from app.models import dataset as dataset_model
from app.services import data_service
from app.services.settings import get_settings
from app.utils.security import login_required

bp = Blueprint("upload", __name__, url_prefix="/data")
log = logging.getLogger(__name__)

TEMPLATE_CSV = """transaction_id,sender,receiver,amount,timestamp
TX001,A101,B202,5000,2026-09-01 10:05
TX002,B202,C303,4800,2026-09-01 11:40
TX003,C303,A101,4900,2026-09-01 13:15
"""


@bp.route("/")
@login_required
def index():
    return render_template("upload.html", datasets=dataset_model.list_datasets(g.user["id"]),
                           max_mb=current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024))


@bp.route("/template.csv")
def template_csv():
    return Response(TEMPLATE_CSV, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=transactions_template.csv"})


def _register_dataset(user_id, name, source, original_name, raw_path, clean, extra_meta=None):
    processed_path = os.path.join(current_app.config["PROCESSED_FOLDER"], f"{uuid.uuid4().hex}.csv")
    data_service.save_processed(clean.df, processed_path)
    meta = {"report": clean.report, **(extra_meta or {})}
    return dataset_model.create_dataset(
        user_id, name, source, original_name, raw_path, processed_path, clean.report["rows_out"],
        clean.report["accounts"], clean.has_timestamps, clean.has_labels, meta)


@bp.route("/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV file to upload.", "error")
        return redirect(url_for("upload.index"))
    original = secure_filename(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in current_app.config["ALLOWED_EXTENSIONS"]:
        flash("Only .csv files are supported.", "error")
        return redirect(url_for("upload.index"))

    settings = get_settings()
    raw_path = os.path.join(current_app.config["UPLOAD_FOLDER"], f"{uuid.uuid4().hex}.csv")
    file.save(raw_path)
    try:
        clean = data_service.load_and_clean(raw_path, settings.max_rows)
    except data_service.DataValidationError as exc:
        os.remove(raw_path)
        flash(str(exc), "error")
        return redirect(url_for("upload.index"))
    except Exception:
        log.exception("Unexpected failure while reading an upload")
        os.remove(raw_path)
        flash("The file could not be processed. Check that it is a valid CSV and try again.", "error")
        return redirect(url_for("upload.index"))

    name = request.form.get("name", "").strip() or original.rsplit(".", 1)[0] or "Untitled dataset"
    dataset_id = _register_dataset(g.user["id"], name[:120], "upload", original, raw_path, clean)
    report = clean.report
    dropped = sum(report["dropped"].values())
    msg = f"Loaded {report['rows_out']:,} transactions across {report['accounts']:,} accounts."
    if dropped:
        msg += f" {dropped:,} rows were skipped (see the dataset details)."
    flash(msg, "success")
    return redirect(url_for("upload.index"))


@bp.route("/demo", methods=["POST"])
@login_required
def demo():
    from ml.synthetic import generate

    df, truth = generate(seed=7)
    token = uuid.uuid4().hex
    raw_path = os.path.join(current_app.config["UPLOAD_FOLDER"], f"{token}.csv")
    truth_path = os.path.join(current_app.config["PROCESSED_FOLDER"], f"{token}_truth.json")
    df.to_csv(raw_path, index=False)
    with open(truth_path, "w") as fh:
        json.dump(truth, fh)
    clean = data_service.load_and_clean(raw_path, get_settings().max_rows)
    _register_dataset(g.user["id"], "Demo: synthetic network with planted rings", "demo", "demo.csv",
                      raw_path, clean, {"truth_path": truth_path, "planted_rings": len(truth)})
    flash("Demo data loaded. It contains 5 hidden rings, so you can check the results against the truth.", "success")
    return redirect(url_for("upload.index"))


@bp.route("/<int:dataset_id>/delete", methods=["POST"])
@login_required
def delete(dataset_id):
    if not dataset_model.delete_dataset(dataset_id, g.user["id"]):
        abort(404)
    flash("Dataset and its analyses were deleted.", "success")
    return redirect(url_for("upload.index"))
