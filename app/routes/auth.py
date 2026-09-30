import re

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from app.models import user as user_model
from app.utils.security import (clear_failed_logins, login_blocked, record_failed_login, safe_next)

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        min_len = current_app.config["MIN_PASSWORD_LENGTH"]

        error = None
        if not name:
            error = "Enter your name."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif len(password) < min_len:
            error = f"Use a password of at least {min_len} characters."
        elif password.isdigit():
            error = "Add letters to your password; digits alone are too easy to guess."
        elif password != confirm:
            error = "The two passwords don't match."
        elif user_model.get_user_by_email(email):
            error = "An account with this email already exists. Sign in instead."

        if error:
            flash(error, "error")
            return render_template("auth/register.html", name=name, email=email), 400

        user_id = user_model.create_user(name, email, password)
        session.clear()
        session["user_id"] = user_id
        session.permanent = True
        flash("Your account is ready. Load the demo data or upload a transaction file to begin.", "success")
        return redirect(url_for("upload.index"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if login_blocked(email):
            flash("Too many failed attempts. Wait a few minutes and try again.", "error")
            return render_template("auth/login.html", email=email), 429
        user = user_model.verify_credentials(email, password)
        if user is None:
            record_failed_login(email)
            flash("Email or password is incorrect.", "error")
            return render_template("auth/login.html", email=email), 401
        clear_failed_logins(email)
        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True
        return redirect(safe_next(request.args.get("next"), url_for("dashboard.index")))
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You are signed out.", "info")
    return redirect(url_for("main.landing"))
