"""Tích hợp Google (cấu hình tại console.cloud.google.com — xem docs/GOOGLE_CLOUD_SETUP.md).

1. Đăng nhập bằng Google: app gửi ID token → server kiểm chữ ký bằng khoá công khai của Google.
2. Gmail chỉ-đọc: app gửi server auth code → server đổi lấy refresh token (mã hoá khi lưu) → đọc thư mới.

Client secret và refresh token chỉ nằm trên server, không bao giờ nằm trong app.
"""

from __future__ import annotations

import base64
import html
import re
from datetime import UTC, datetime

import httpx
import jwt

from . import config
from .models import Message, Source

CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")

_jwks = jwt.PyJWKClient(CERTS_URL, cache_keys=True, lifespan=3600)
_transport: httpx.AsyncBaseTransport | None = None  # test gán MockTransport vào đây


class GoogleError(Exception):
    """Lỗi có thể hiển thị cho người dùng."""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20, transport=_transport)


# ---------------- Đăng nhập ----------------


def verify_id_token(id_token: str) -> dict:
    """Kiểm chữ ký, issuer, audience, hạn dùng. Trả về {sub, email, name}. Hàm đồng bộ (gọi trong thread)."""
    audiences = config.google_client_ids()
    if not audiences:
        raise GoogleError("Server chưa cấu hình GOOGLE_WEB_CLIENT_ID")
    try:
        key = _jwks.get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=audiences,
            issuer=ISSUERS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as e:
        raise GoogleError("Google ID token không hợp lệ") from e
    if not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise GoogleError("Tài khoản Google chưa xác minh email")
    return {"sub": claims["sub"], "email": claims["email"].lower(), "name": claims.get("name", "")}


# ---------------- OAuth cho Gmail ----------------


async def exchange_code(server_auth_code: str) -> dict:
    """Đổi server auth code (lấy từ Google Sign-In trên điện thoại) lấy refresh token."""
    if not (config.google_web_client_id() and config.google_client_secret()):
        raise GoogleError("Server chưa cấu hình GOOGLE_WEB_CLIENT_ID / GOOGLE_CLIENT_SECRET")
    async with _client() as c:
        r = await c.post(
            TOKEN_URL,
            data={
                "code": server_auth_code,
                "client_id": config.google_web_client_id(),
                "client_secret": config.google_client_secret(),
                "grant_type": "authorization_code",
                "redirect_uri": "",  # code từ SDK di động không dùng redirect
            },
        )
    if r.status_code != 200:
        raise GoogleError("Google từ chối mã uỷ quyền (hết hạn hoặc đã dùng)")
    data = r.json()
    if not data.get("refresh_token"):
        raise GoogleError("Google không trả refresh token — hãy ngắt kết nối rồi cấp quyền lại")
    if config.GMAIL_SCOPE not in data.get("scope", "").split():
        raise GoogleError("Chưa cấp quyền đọc Gmail")
    email = ""
    if data.get("id_token"):
        # Token nhận trực tiếp từ Google qua TLS nên không cần kiểm chữ ký lần nữa.
        email = jwt.decode(data["id_token"], options={"verify_signature": False}).get("email", "")
    return {"refresh_token": data["refresh_token"], "scope": data.get("scope", ""), "email": email.lower()}


async def access_token(refresh_token: str) -> str:
    async with _client() as c:
        r = await c.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": config.google_web_client_id(),
                "client_secret": config.google_client_secret(),
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        raise GoogleError("Quyền truy cập Gmail đã hết hạn hoặc bị thu hồi — hãy kết nối lại")
    return r.json()["access_token"]


async def revoke(refresh_token: str) -> None:
    try:
        async with _client() as c:
            await c.post(REVOKE_URL, data={"token": refresh_token})
    except httpx.HTTPError:
        pass  # thu hồi phía Google là best-effort; phía mình vẫn xoá token


# ---------------- Gmail ----------------


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _find_part(payload: dict, mime: str) -> str | None:
    if payload.get("mimeType") == mime and payload.get("body", {}).get("data"):
        return _b64(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime)
        if found:
            return found
    return None


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def parse_gmail(raw: dict) -> Message:
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    body = _find_part(payload, "text/plain")
    if not body:
        page = _find_part(payload, "text/html")
        body = _strip_html(page) if page else raw.get("snippet", "")
    body = (body or raw.get("snippet") or "(không có nội dung)").strip()[:6000]
    received = None
    if raw.get("internalDate"):
        ts = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=UTC)
        received = ts.astimezone(config.TZ).isoformat()
    return Message(
        id=f"gmail-{raw['id']}",
        source=Source.email,
        sender=headers.get("from", "")[:300],
        subject=headers.get("subject", "")[:500],
        body=body or "(không có nội dung)",
        received_at=received,
    )


async def list_message_ids(token: str, days: int, max_messages: int) -> list[str]:
    query = f"newer_than:{days}d in:inbox -category:promotions -category:social"
    async with _client() as c:
        r = await c.get(
            f"{GMAIL_URL}/messages",
            params={"q": query, "maxResults": max_messages},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise GoogleError(f"Gmail trả lỗi {r.status_code} khi liệt kê thư")
    return [m["id"] for m in r.json().get("messages", [])]


async def get_message(token: str, gmail_id: str) -> Message:
    async with _client() as c:
        r = await c.get(
            f"{GMAIL_URL}/messages/{gmail_id}",
            params={"format": "full"},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise GoogleError(f"Gmail trả lỗi {r.status_code} khi đọc thư")
    return parse_gmail(r.json())
