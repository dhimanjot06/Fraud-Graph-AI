"""Application configuration.

Detection thresholds live in ``DETECTION`` so analysts can tune the system
without touching service code. Every key maps to a field of
``app.services.settings.DetectionSettings``.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

_INSECURE_DEFAULT_KEY = "dev-only-insecure-key"


class Config:
    ENV_NAME = "development"
    DEBUG = False
    TESTING = False

    SECRET_KEY = os.environ.get("SECRET_KEY", _INSECURE_DEFAULT_KEY)

    # Storage
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "fraudgraph.db"))
    RAW_FOLDER = str(BASE_DIR / "data" / "raw")
    UPLOAD_FOLDER = str(BASE_DIR / "data" / "uploads")
    PROCESSED_FOLDER = str(BASE_DIR / "data" / "processed")
    MAX_CONTENT_LENGTH = 40 * 1024 * 1024  # 40 MB per upload
    ALLOWED_EXTENSIONS = {"csv"}

    # Sessions & security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60
    CSRF_ENABLED = True
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 10 * 60
    MIN_PASSWORD_LENGTH = 8

    # Detection tuning (see app/services/settings.py for the meaning of each key)
    DETECTION = {
        "currency_symbol": "₹",
        "max_rows": 250_000,
        "max_cycle_length": 6,
        "cycle_amount_tolerance": 0.25,
        "cycle_window_hours": 168,
        "time_window_hours": 72,
        "min_ring_size": 3,
        "max_ring_size": 40,
        "hub_min_senders": 5,
        "ring_report_min_score": 50.0,
        "high_threshold": 75.0,
        "medium_threshold": 50.0,
    }


class DevelopmentConfig(Config):
    ENV_NAME = "development"
    DEBUG = True


class TestingConfig(Config):
    ENV_NAME = "testing"
    TESTING = True
    CSRF_ENABLED = False
    SECRET_KEY = "testing-key"
    DETECTION = {**Config.DETECTION, "max_rows": 50_000}


class ProductionConfig(Config):
    ENV_NAME = "production"
    SESSION_COOKIE_SECURE = True


_CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name=None):
    name = (name or os.environ.get("FRAUDGRAPH_ENV") or "development").lower()
    try:
        return _CONFIGS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown config '{name}'. Choose from: {', '.join(_CONFIGS)}") from exc
