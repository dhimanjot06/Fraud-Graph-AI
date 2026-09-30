import io
import re


def test_landing_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"FraudGraph" in resp.data


def test_register_login_logout_flow(client):
    resp = client.post("/register", data={"name": "Ann", "email": "ann@example.com",
                                          "password": "password1", "confirm": "password1"}, follow_redirects=True)
    assert resp.status_code == 200
    resp = client.post("/logout", follow_redirects=True)
    assert resp.status_code == 200
    resp = client.post("/login", data={"email": "ann@example.com", "password": "password1"}, follow_redirects=True)
    assert resp.status_code == 200


def test_register_rejects_short_password(client):
    resp = client.post("/register", data={"name": "Ann", "email": "ann2@example.com",
                                          "password": "short", "confirm": "short"})
    assert resp.status_code == 400


def test_register_rejects_mismatched_passwords(client):
    resp = client.post("/register", data={"name": "Ann", "email": "ann3@example.com",
                                          "password": "password1", "confirm": "password2"})
    assert resp.status_code == 400


def test_dashboard_requires_login(client):
    resp = client.get("/dashboard", follow_redirects=True)
    assert b"Sign in" in resp.data or b"sign in" in resp.data.lower()


def test_demo_dataset_end_to_end(auth_client):
    resp = auth_client.post("/data/demo", follow_redirects=True)
    assert resp.status_code == 200
    resp = auth_client.get("/data/")
    match = re.search(rb"/analysis/run/(\d+)", resp.data)
    assert match, "expected a dataset with an Analyze button"
    dataset_id = match.group(1).decode()

    resp = auth_client.post(f"/analysis/run/{dataset_id}", follow_redirects=True)
    assert resp.status_code == 200
    run_id = resp.request.path.rsplit("/", 1)[-1]

    resp = auth_client.get(f"/analysis/{run_id}")
    assert resp.status_code == 200
    assert b"FR-" in resp.data

    ring_match = re.search(rb"/rings/(FR-\d+)", resp.data)
    assert ring_match
    ring_code = ring_match.group(1).decode()
    resp = auth_client.get(f"/analysis/{run_id}/rings/{ring_code}")
    assert resp.status_code == 200

    resp = auth_client.get(f"/analysis/{run_id}/export/rings.csv")
    assert resp.status_code == 200
    assert resp.data.startswith(b"ring,type,risk_score")


def test_upload_rejects_non_csv(auth_client):
    resp = auth_client.post("/data/upload", data={"name": "bad", "file": (io.BytesIO(b"data"), "bad.txt")},
                            content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Only .csv files" in resp.data


def test_analysis_run_requires_ownership(auth_client, client):
    client.post("/register", data={"name": "Bob", "email": "bob@example.com",
                                    "password": "password1", "confirm": "password1"})
    auth_client.post("/data/demo")
    resp = client.get("/analysis/1")
    assert resp.status_code in (302, 404)


def test_missing_csrf_token_is_rejected(app):
    app.config["CSRF_ENABLED"] = True
    with app.test_client() as c:
        resp = c.post("/register", data={"name": "Ann", "email": "csrf@example.com",
                                         "password": "password1", "confirm": "password1"})
        assert resp.status_code == 400
