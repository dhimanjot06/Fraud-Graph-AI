from flask import Blueprint, abort, g, jsonify, render_template

from app.models import analysis as analysis_model
from app.models import dataset as dataset_model
from app.utils.security import login_required

bp = Blueprint("dashboard", __name__)
api = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/dashboard")
@login_required
def index():
    uid = g.user["id"]
    latest = analysis_model.latest_done_run(uid)
    rings = analysis_model.get_rings(latest["id"])[:6] if latest else []
    return render_template("dashboard.html", latest=latest, rings=rings,
                           datasets=dataset_model.list_datasets(uid), runs=analysis_model.list_runs(uid, 6))


def _own_run_or_404(run_id):
    run = analysis_model.get_run(run_id, g.user["id"])
    if run is None or run["status"] != "done":
        abort(404)
    return run


@api.route("/runs/<int:run_id>/graph")
@login_required
def run_graph(run_id):
    """Overview network: the highest-risk rings side by side (capped for readability)."""
    _own_run_or_404(run_id)
    rings = analysis_model.get_rings(run_id)[:12]
    nodes, edges = {}, []
    for ring in rings:
        for n in ring["nodes"]:
            nodes.setdefault(n, {"id": n, "ring": ring["code"], "role": ring["roles"].get(n, "member"),
                                 "level": ring["level"]})
        edges += [{**e, "ring": ring["code"]} for e in ring["edges"]]
    return jsonify(nodes=list(nodes.values()), edges=edges, truncated=len(analysis_model.get_rings(run_id)) > 12)


@api.route("/runs/<int:run_id>/rings/<code>/graph")
@login_required
def ring_graph(run_id, code):
    _own_run_or_404(run_id)
    ring = analysis_model.get_ring(run_id, code)
    if ring is None:
        abort(404)
    levels = analysis_model.get_account_levels(run_id, ring["nodes"])
    nodes = [{"id": n, "role": ring["roles"].get(n, "member"),
              "risk": levels.get(n, (None, None))[0], "level": levels.get(n, (None, ring["level"]))[1]}
             for n in ring["nodes"]]
    return jsonify(nodes=nodes, edges=ring["edges"], type=ring["ring_type"], loop=(ring["loops"] or [None])[0])
