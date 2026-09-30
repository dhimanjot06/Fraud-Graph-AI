import os
import shutil
import tempfile

import pytest

from app import create_app


@pytest.fixture
def app():
    tmp = tempfile.mkdtemp()
    application = create_app("testing", {
        "DATABASE_PATH": os.path.join(tmp, "test.db"),
        "UPLOAD_FOLDER": os.path.join(tmp, "uploads"),
        "PROCESSED_FOLDER": os.path.join(tmp, "processed"),
        "RAW_FOLDER": os.path.join(tmp, "raw"),
    })
    yield application
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    client.post("/register", data={"name": "Test User", "email": "test@example.com",
                                    "password": "password1", "confirm": "password1"})
    return client
