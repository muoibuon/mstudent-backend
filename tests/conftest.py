import os

os.environ["MSTUDENT_OFFLINE"] = "1"
os.environ["MSTUDENT_SYNC_ENABLED"] = "0"  # không chạy vòng đồng bộ nền trong test
os.environ["MSTUDENT_NOW"] = "2026-11-10T08:00:00+07:00"
os.environ["MSTUDENT_SECRET_KEY"] = "test-secret-key-0123456789abcdef0123456789abcdef"
os.environ.pop("MSTUDENT_ADMIN_EMAILS", None)

import pytest
from fastapi.testclient import TestClient

from app import config, security


@pytest.fixture(autouse=True)
def isolated_provider_credentials(monkeypatch):
    """Local .env credentials must never turn mocked tests into paid requests."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    security.limiter.reset()
    from app.main import app

    return TestClient(app)


def signup(client, email="a@vju.ac.vn", password="correct horse 42", name="A"):
    r = client.post("/api/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def auth(tokens) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture()
def user(client):
    """(headers, tokens) của một người dùng đã đăng ký."""
    t = signup(client)
    return auth(t), t
