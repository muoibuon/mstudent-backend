"""Tài khoản và token."""

import sqlite3

from app import config, security
from tests.conftest import auth, signup


def test_register_login_me(client):
    t = signup(client, "Muoi@VJU.ac.vn", "correct horse 42", "Muối")
    assert t["user"]["email"] == "muoi@vju.ac.vn" and t["user"]["has_password"] and not t["user"]["is_admin"]
    assert client.get("/api/auth/me", headers=auth(t)).json()["name"] == "Muối"
    ok = client.post("/api/auth/login", json={"email": "MUOI@vju.ac.vn", "password": "correct horse 42"})
    assert ok.status_code == 200
    # mật khẩu được băm Argon2id, không lưu dạng rõ; refresh token chỉ lưu dạng băm
    db = sqlite3.connect(config.DB_PATH)
    stored = db.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored.startswith("$argon2id$") and "correct horse" not in stored
    hashes = [r[0] for r in db.execute("SELECT token_hash FROM refresh_tokens")]
    assert t["refresh_token"] not in hashes and security.token_hash(t["refresh_token"]) in hashes


def test_register_validation(client):
    def reg(**kw):
        return client.post(
            "/api/auth/register", json={"email": "a@x.vn", "password": "correct horse 42", **kw}
        )

    assert reg(password="short").status_code == 422
    assert reg(password="password123").status_code == 422
    assert reg(password="a@x.vn").status_code == 422
    assert reg(email="not-an-email").status_code == 422
    assert reg().status_code == 201
    assert reg().status_code == 409


def test_login_failures_same_error_and_lockout(client):
    signup(client, "a@x.vn")
    wrong = client.post("/api/auth/login", json={"email": "a@x.vn", "password": "wrong password"})
    ghost = client.post("/api/auth/login", json={"email": "ghost@x.vn", "password": "wrong password"})
    assert (
        wrong.status_code == ghost.status_code == 401 and wrong.json() == ghost.json()
    )  # không lộ email nào tồn tại
    for _ in range(4):
        client.post("/api/auth/login", json={"email": "a@x.vn", "password": "wrong password"})
    locked = client.post("/api/auth/login", json={"email": "a@x.vn", "password": "correct horse 42"})
    assert locked.status_code == 429 and "retry-after" in locked.headers


def test_refresh_rotation_and_reuse_detection(client, monkeypatch):
    monkeypatch.setattr(config, "REFRESH_REUSE_GRACE_S", 0)
    t1 = signup(client)
    t2 = client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    assert t2["refresh_token"] != t1["refresh_token"]
    assert client.get("/api/auth/me", headers=auth(t2)).status_code == 200
    # token cũ bị dùng lại (dấu hiệu bị lộ) → thu hồi cả chuỗi, kể cả token mới nhất
    assert client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_refresh_grace_when_app_killed_mid_rotation(client):
    """App bị đóng ngay sau khi server xoay token (chưa kịp lưu token mới): mở lại vẫn vào được."""
    t1 = signup(client)
    client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]})  # phản hồi bị mất
    again = client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert again.status_code == 200
    # nhưng sau khi đăng xuất thì token cũ không dùng lại được dù còn trong ân hạn
    client.post("/api/auth/logout", json={"refresh_token": again.json()["refresh_token"]})
    assert client.post("/api/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh(client):
    t = signup(client)
    assert client.post("/api/auth/logout", json={"refresh_token": t["refresh_token"]}).json() == {"ok": True}
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_access_token_rejects_tampering_and_expiry(client, monkeypatch):
    t = signup(client)
    token = t["access_token"]
    head, payload, sig = token.split(".")
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {head}.{payload}.AAAA"}).status_code
        == 401
    )
    import jwt

    forged = jwt.encode(
        {"sub": "1", "typ": "access", "exp": 9999999999},
        "another-secret-another-secret-0000",
        algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"sub": "1", "typ": "access", "exp": 9999999999}, None, algorithm="none")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401
    monkeypatch.setattr(config, "ACCESS_TTL_MIN", -1)
    expired, _ = security.create_access_token(t["user"]["id"])
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_change_password_logs_out_other_devices(client):
    t = signup(client)
    other = client.post(
        "/api/auth/login", json={"email": "a@vju.ac.vn", "password": "correct horse 42"}
    ).json()
    bad = client.post(
        "/api/auth/change-password",
        json={"old_password": "nope", "new_password": "brand new pass 99"},
        headers=auth(t),
    )
    assert bad.status_code == 401
    new = client.post(
        "/api/auth/change-password",
        json={"old_password": "correct horse 42", "new_password": "brand new pass 99"},
        headers=auth(t),
    )
    assert new.status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"email": "a@vju.ac.vn", "password": "brand new pass 99"}
        ).status_code
        == 200
    )


def test_delete_account_removes_everything(client):
    t = signup(client)
    h = auth(t)
    client.post("/api/demo/seed", headers=h)
    assert (
        client.request("DELETE", "/api/auth/me", json={"confirm_email": "wrong@x.vn"}, headers=h).status_code
        == 400
    )
    assert (
        client.request("DELETE", "/api/auth/me", json={"confirm_email": "a@vju.ac.vn"}, headers=h).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers=h).status_code == 401  # token còn hạn nhưng tài khoản đã xoá
    db = sqlite3.connect(config.DB_PATH)
    for table in ("users", "tasks", "messages", "traces", "refresh_tokens"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_registration_can_be_closed(client, monkeypatch):
    monkeypatch.setenv("MSTUDENT_REGISTRATION", "closed")
    r = client.post("/api/auth/register", json={"email": "a@x.vn", "password": "correct horse 42"})
    assert r.status_code == 403
