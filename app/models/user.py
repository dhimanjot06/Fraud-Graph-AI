from werkzeug.security import check_password_hash, generate_password_hash

from .database import get_db


def create_user(name, email, password):
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name.strip(), email.strip().lower(), generate_password_hash(password)),
    )
    db.commit()
    return cur.lastrowid


def get_user(user_id):
    return get_db().execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()


def verify_credentials(email, password):
    user = get_user_by_email(email)
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None
