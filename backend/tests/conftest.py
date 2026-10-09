import os
import tempfile

os.environ["DATABASE_URL"] = "postgresql+psycopg://localhost/dooh_test"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="dooh-media-")
os.environ["ADMIN_PASSWORD"] = "test-pass"
os.environ["SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin(client):
    token = client.post("/api/admin/login", json={"password": "test-pass"}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def pair_device(admin_client, uid="android-123", **extra):
    """Register + pair a tablet; returns its device token and id."""
    from fastapi.testclient import TestClient as _TC

    tablet = _TC(app)
    reg = tablet.post("/api/player/register", json={"device_uid": uid, "app_version": "1.0.0"}).json()
    body = {"pairing_code": reg["pairing_code"], "name": "Lobby", "venue_name": "Cafe", "venue_address": "1 Main St", **extra}
    device = admin_client.post("/api/admin/screens/pair", json=body).json()
    status = tablet.post("/api/player/pairing-status", json={"device_uid": uid, "claim_secret": reg["claim_secret"]}).json()
    return status["token"], device["id"]
