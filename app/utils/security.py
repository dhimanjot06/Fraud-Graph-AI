"""Authentication guard, CSRF protection, login throttling and response headers."""
import hmac
import secrets
import time
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from app.models import user as user_model

_failed_logins = {}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            flash("Sign in to continue.", "info")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target, fallback):
    """Only follow same-site relative redirects."""
    if target:
        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return fallback


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def throttle_key(email):
    return f"{(email or '').strip().lower()}|{request.remote_addr}"


def login_blocked(email):
    key = throttle_key(email)
    cfg = current_app.config
    now = time.time()
    attempts = [t for t in _failed_logins.get(key, []) if now - t < cfg["LOGIN_WINDOW_SECONDS"]]
    _failed_logins[key] = attempts
    return len(attempts) >= cfg["LOGIN_MAX_ATTEMPTS"]


def record_failed_login(email):
    _failed_logins.setdefault(throttle_key(email), []).append(time.time())


def clear_failed_logins(email):
    _failed_logins.pop(throttle_key(email), None)


def init_app(app):
    @app.before_request
    def load_user():
        uid = session.get("user_id")
        g.user = user_model.get_user(uid) if uid else None
        if uid and g.user is None:
            session.clear()

    @app.before_request
    def protect_from_csrf():
        if not app.config["CSRF_ENABLED"] or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        expected = session.get("_csrf")
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not sent or not hmac.compare_digest(expected, sent):
            abort(400, description="Your session expired or the form was tampered with. Reload the page and try again.")

    @app.context_processor
    def inject_globals():
        return {"csrf_token": csrf_token, "current_user": g.get("user"),
                "currency": app.config["DETECTION"].get("currency_symbol", "₹")}

    @app.after_request
    def set_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'",
        )
        if request.endpoint and request.endpoint != "static" and g.get("user") is not None:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp
