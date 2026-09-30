"""FraudGraph AI: application factory."""
import logging
import os

from flask import Flask, render_template

from config import _INSECURE_DEFAULT_KEY, get_config


def create_app(config_name=None, overrides=None):
    app = Flask(__name__)
    cfg = get_config(config_name)
    app.config.from_object(cfg)
    if overrides:
        app.config.update(overrides)

    if app.config["ENV_NAME"] == "production" and app.config["SECRET_KEY"] == _INSECURE_DEFAULT_KEY:
        raise RuntimeError("Set a strong SECRET_KEY in the environment before running in production.")

    for key in ("UPLOAD_FOLDER", "PROCESSED_FOLDER", "RAW_FOLDER"):
        os.makedirs(app.config[key], exist_ok=True)

    logging.basicConfig(level=logging.DEBUG if app.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from app.models import init_app as init_database
    from app.utils import formatting, security

    init_database(app)
    security.init_app(app)
    formatting.init_app(app)

    from app.routes import analysis, auth, dashboard, main, upload

    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(dashboard.api)
    app.register_blueprint(upload.bp)
    app.register_blueprint(analysis.bp)

    _register_error_handlers(app)

    from app.cli import register_commands
    register_commands(app)
    return app


def _register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(err):
        return render_template("errors/error.html", code=400, title="That request didn't go through",
                               message=getattr(err, "description", "")), 400

    @app.errorhandler(403)
    def forbidden(_err):
        return render_template("errors/error.html", code=403, title="You don't have access to this",
                               message="Sign in with the account that owns it."), 403

    @app.errorhandler(404)
    def not_found(_err):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="The page may have moved, or the analysis may have been deleted."), 404

    @app.errorhandler(413)
    def too_large(_err):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_template("errors/error.html", code=413, title="That file is too large",
                               message=f"Uploads are limited to {limit} MB. Filter or sample the file and try again."), 413

    @app.errorhandler(500)
    def server_error(_err):
        return render_template("errors/error.html", code=500, title="Something went wrong on our side",
                               message="The error has been logged. Try again, and if it keeps happening check the server log."), 500
