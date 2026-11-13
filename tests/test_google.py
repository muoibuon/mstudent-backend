"""Google Sign-In + Gmail (Google được giả lập; không gọi mạng thật)."""

import base64
import sqlite3

import httpx
import pytest

from app import config, google_api
from tests.conftest import auth, signup

GMAIL_SCOPE = config.GMAIL_SCOPE


@pytest.fixture()
def google(monkeypatch):
    """Giả lập Google: ID token 'tok:<sub>:<email>' luôn hợp lệ; token endpoint + Gmail API bằng MockTransport."""
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "web-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shh")

    def fake_verify(id_token: str) -> dict:
        if not id_token.startswith("tok:"):
            raise google_api.GoogleError("Google ID token không hợp lệ")
        _, sub, email = id_token.split(":")
        return {"sub": sub, "email": email, "name": "G User"}

    monkeypatch.setattr(google_api, "verify_id_token", fake_verify)

    def b64(s: str) -> str:
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

    mails = {
        "m1": (
            "Phòng Đào tạo <daotao@vju.ac.vn>",
            "[CSE3032] Nộp báo cáo Lab 3",
            "Các em nộp báo cáo Lab 3 trước 23h59 ngày 13/11.",
        ),
        "m2": ("Shop <sale@shop.vn>", "Flash sale", "Giảm giá 50%, săn voucher ngay"),
    }
    state = {"calls": [], "revoked": []}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        state["calls"].append(url.split("?")[0])
        if url.startswith(google_api.TOKEN_URL):
            form = dict(x.split("=") for x in req.content.decode().split("&"))
            if form["grant_type"] == "authorization_code":
                if form["code"] != "good-code":
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(
                    200,
                    json={
                        "access_token": "at",
                        "refresh_token": "rt-secret",
                        "scope": f"openid {GMAIL_SCOPE}",
                    },
                )
            return httpx.Response(200, json={"access_token": "at"})
        if url.startswith(google_api.REVOKE_URL):
            state["revoked"].append(req.content.decode())
            return httpx.Response(200)
        assert req.headers["authorization"] == "Bearer at"
        if url.split("?")[0].endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": k} for k in mails]})
        mid = url.split("?")[0].rsplit("/", 1)[1]
        sender, subject, body = mails[mid]
        return httpx.Response(
            200,
            json={
                "id": mid,
                "internalDate": "1794272400000",
                "snippet": body[:20],
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
                    "parts": [{"mimeType": "text/plain", "body": {"data": b64(body)}}],
                },
            },
        )

    monkeypatch.setattr(google_api, "_transport", httpx.MockTransport(handler))
    return state


def test_google_login_creates_then_reuses_account(client, google):
    t = client.post("/api/auth/google", json={"id_token": "tok:sub-1:sv@vju.ac.vn"}).json()
    assert t["user"]["google_linked"] and not t["user"]["has_password"]
    again = client.post("/api/auth/google", json={"id_token": "tok:sub-1:sv@vju.ac.vn"}).json()
    assert again["user"]["id"] == t["user"]["id"]
    assert client.post("/api/auth/google", json={"id_token": "x" * 30}).status_code == 401
    # tài khoản chỉ có Google không đăng nhập bằng mật khẩu được, nhưng tự đặt mật khẩu được
    assert (
        client.post(
            "/api/auth/login", json={"email": "sv@vju.ac.vn", "password": "anything at all"}
        ).status_code
        == 401
    )
    set_pw = client.post(
        "/api/auth/change-password", json={"new_password": "brand new pass 99"}, headers=auth(again)
    )
    assert set_pw.status_code == 200 and set_pw.json()["user"]["has_password"]


def test_google_link_disables_unverified_password(client, google):
    """Kẻ xấu đăng ký trước bằng email của nạn nhân; khi chủ thật đăng nhập Google, mật khẩu và phiên cũ bị vô hiệu."""
    attacker = signup(client, "victim@vju.ac.vn", "attacker pass 123")
    owner = client.post("/api/auth/google", json={"id_token": "tok:sub-9:victim@vju.ac.vn"}).json()
    assert owner["user"]["id"] == attacker["user"]["id"] and not owner["user"]["has_password"]
    assert (
        client.post("/api/auth/refresh", json={"refresh_token": attacker["refresh_token"]}).status_code == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": "victim@vju.ac.vn", "password": "attacker pass 123"}
        ).status_code
        == 401
    )


def test_gmail_connect_sync_disconnect(client, google):
    h = auth(signup(client))
    assert client.get("/api/google/status", headers=h).json() == {"connected": False}
    assert client.post("/api/google/gmail/sync", json={}, headers=h).status_code == 409
    assert (
        client.post("/api/google/connect", json={"server_auth_code": "bad-code"}, headers=h).status_code
        == 400
    )
    assert client.post("/api/google/connect", json={"server_auth_code": "good-code"}, headers=h).json()[
        "connected"
    ]
    # refresh token của Google được mã hoá khi lưu
    enc = (
        sqlite3.connect(config.DB_PATH).execute("SELECT refresh_token_enc FROM google_accounts").fetchone()[0]
    )
    assert "rt-secret" not in enc

    r = client.post("/api/google/gmail/sync", json={"days": 7}, headers=h).json()
    assert (r["scanned"], r["new"], r["tasks_created"], r["noise_filtered"]) == (2, 2, 1, 1)
    task = client.get("/api/tasks", headers=h).json()[0]
    assert (
        task["source"] == "email"
        and task["course"] == "CSE3032"
        and task["due_at"].startswith("2026-11-13T23:59")
    )
    # quét lại: không tải lại thư đã xử lý, không tạo việc trùng
    before = len(google["calls"])
    r2 = client.post("/api/google/gmail/sync", json={}, headers=h).json()
    assert r2["new"] == 0 and len(google["calls"]) - before == 2  # chỉ đổi token + liệt kê
    assert len(client.get("/api/tasks", headers=h).json()) == 1

    assert client.get("/api/auth/me", headers=h).json()["gmail_connected"] is True
    assert client.request("DELETE", "/api/google/disconnect", headers=h).json() == {"connected": False}
    assert google["revoked"] == ["token=rt-secret"]
    assert client.get("/api/google/status", headers=h).json() == {"connected": False}


def test_parse_gmail_html_fallback():
    html = base64.urlsafe_b64encode("<p>Nộp bài <b>trước 20/11</b></p><script>x()</script>".encode()).decode()
    m = google_api.parse_gmail(
        {"id": "z", "payload": {"mimeType": "text/html", "headers": [], "body": {"data": html}}}
    )
    assert m.id == "gmail-z" and m.body == "Nộp bài trước 20/11"


def test_public_config(client, google):
    c = client.get("/api/public-config").json()
    assert c["google"]["enabled"] and c["google"]["web_client_id"].endswith("googleusercontent.com")
    assert "secret" not in str(c).lower() and "shh" not in str(c)


def test_connect_creates_auto_gmail_source_and_disconnect_removes_it(client, google):
    h = auth(signup(client))
    client.post("/api/google/connect", json={"server_auth_code": "good-code"}, headers=h)
    sources = client.get("/api/sources", headers=h).json()
    assert [s["kind"] for s in sources] == ["gmail"] and sources[0]["enabled"] is True
    assert (
        client.delete(f"/api/sources/{sources[0]['id']}", headers=h).status_code == 400
    )  # dùng nút ngắt Google
    client.delete("/api/google/disconnect", headers=h)
    assert client.get("/api/sources", headers=h).json() == []


def test_connect_with_classroom_scopes_creates_classroom_source(client, google, monkeypatch):
    real_post = httpx.AsyncClient.post

    async def classroom_only(self, url, *a, **kw):
        r = await real_post(self, url, *a, **kw)
        if str(url).startswith(google_api.TOKEN_URL) and r.status_code == 200:
            data = r.json() | {"scope": "openid " + " ".join(config.CLASSROOM_SCOPES)}
            return httpx.Response(200, json=data)
        return r

    monkeypatch.setattr(httpx.AsyncClient, "post", classroom_only)
    h = auth(signup(client))
    assert (
        client.post("/api/google/connect", json={"server_auth_code": "good-code"}, headers=h).status_code
        == 200
    )
    assert [s["kind"] for s in client.get("/api/sources", headers=h).json()] == ["classroom"]
