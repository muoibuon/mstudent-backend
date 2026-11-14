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


class AuthRevoked(GoogleError):
    """Refresh token hết hạn / bị thu hồi / thiếu quyền → người dùng phải kết nối lại."""


class HistoryExpired(GoogleError):
    """startHistoryId quá cũ (Gmail chỉ giữ lịch sử khoảng 1 tuần) → quét lại theo ngày."""


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
    granted = set(data.get("scope", "").split())
    if config.GMAIL_SCOPE not in granted and not set(config.CLASSROOM_SCOPES) <= granted:
        raise GoogleError("Chưa cấp quyền đọc Gmail hoặc Google Classroom")
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
        try:
            err = r.json().get("error", "")
        except ValueError:
            err = ""
        if r.status_code in (400, 401) and err in ("invalid_grant", "unauthorized_client"):
            raise AuthRevoked("Quyền truy cập Google đã hết hạn hoặc bị thu hồi — hãy kết nối lại")
        raise GoogleError("Google tạm thời không cấp quyền truy cập, sẽ thử lại")
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
    # Phần có tên tệp là tệp đính kèm (vd. ghi-chu.txt), không phải thân email.
    if (
        payload.get("mimeType") == mime
        and payload.get("body", {}).get("data")
        and not payload.get("filename")
    ):
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


# ---------------- Đồng bộ tự động (002) ----------------

SKIP_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM", "TRASH", "DRAFT", "SENT"}


def _check(r: httpx.Response, what: str) -> None:
    if r.status_code in (401, 403):
        raise AuthRevoked("Google từ chối quyền đọc — hãy kết nối lại")
    if r.status_code != 200:
        raise GoogleError(f"Gmail trả lỗi {r.status_code} khi {what}")


async def get_history_id(token: str) -> str:
    async with _client() as c:
        r = await c.get(f"{GMAIL_URL}/profile", headers={"Authorization": f"Bearer {token}"})
    _check(r, "đọc hồ sơ")
    return str(r.json()["historyId"])


async def history_message_ids(token: str, start_history_id: str) -> tuple[list[str], str]:
    """Thư mới vào INBOX kể từ start_history_id (bỏ Quảng cáo/Mạng xã hội/Spam). Trả (ids, historyId mới)."""
    ids: list[str] = []
    latest = start_history_id
    page = None
    async with _client() as c:
        for _ in range(5):  # tối đa 5 trang × 100
            params = {"startHistoryId": start_history_id, "historyTypes": "messageAdded", "labelId": "INBOX",
                      "maxResults": 100}  # fmt: skip
            if page:
                params["pageToken"] = page
            r = await c.get(
                f"{GMAIL_URL}/history", params=params, headers={"Authorization": f"Bearer {token}"}
            )
            if r.status_code == 404:
                raise HistoryExpired("Lịch sử Gmail đã quá cũ")
            _check(r, "đọc lịch sử")
            data = r.json()
            latest = str(data.get("historyId", latest))
            for h in data.get("history", []):
                for added in h.get("messagesAdded", []):
                    m = added.get("message", {})
                    labels = set(m.get("labelIds", []))
                    if "INBOX" in labels and not labels & SKIP_LABELS and m.get("id") not in ids:
                        ids.append(m["id"])
            page = data.get("nextPageToken")
            if not page:
                break
    return ids, latest


async def watch(token: str, topic: str) -> int:
    """Đăng ký Gmail báo vào Pub/Sub khi INBOX thay đổi. Trả thời điểm hết hạn (ms epoch, khoảng 7 ngày)."""
    async with _client() as c:
        r = await c.post(
            f"{GMAIL_URL}/watch",
            json={"topicName": topic, "labelIds": ["INBOX"], "labelFilterBehavior": "include"},
            headers={"Authorization": f"Bearer {token}"},
        )
    _check(r, "đăng ký báo ngay")
    return int(r.json().get("expiration", 0))


def verify_push_jwt(token: str) -> dict:
    """Kiểm JWT do Google ký khi Pub/Sub gọi webhook: chữ ký, iss, aud = URL webhook, email = service account."""
    aud, sa = config.public_url() + "/api/hooks/gmail", config.pubsub_push_sa()
    if not (config.public_url() and sa):
        raise GoogleError("Webhook chưa được cấu hình")
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=aud, issuer=ISSUERS,
            options={"require": ["exp", "iat", "aud", "iss", "email"]},
        )  # fmt: skip
    except jwt.PyJWTError as e:
        raise GoogleError("Chữ ký webhook không hợp lệ") from e
    if str(claims.get("email", "")).lower() != sa or claims.get("email_verified") not in (True, "true"):
        raise GoogleError("Webhook không đến từ service account đã cấu hình")
    return claims


# ---------------- Google Classroom (002 US2) ----------------

CLASSROOM_URL = "https://classroom.googleapis.com/v1"


class ClassroomBlocked(GoogleError):
    """Trường / tổ chức chặn ứng dụng bên ngoài truy cập Classroom (403 không phải do token)."""


async def _classroom_get(
    c: httpx.AsyncClient, token: str, path: str, params: dict, key: str, max_pages: int = 5
) -> list[dict]:
    out: list[dict] = []
    page = None
    for _ in range(max_pages):
        q = {**params, **({"pageToken": page} if page else {})}
        r = await c.get(f"{CLASSROOM_URL}{path}", params=q, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 401:
            raise AuthRevoked("Google từ chối quyền đọc Classroom — hãy kết nối lại")
        if r.status_code == 403:
            raise ClassroomBlocked(
                "Không đọc được Google Classroom: trường của bạn có thể chặn ứng dụng bên ngoài, "
                "hoặc chưa cấp quyền Classroom. Gmail và các nguồn khác vẫn hoạt động."
            )
        if r.status_code != 200:
            raise GoogleError(f"Classroom trả lỗi {r.status_code}, sẽ thử lại")
        data = r.json()
        out += data.get(key, [])
        page = data.get("nextPageToken")
        if not page:
            break
    return out


async def classroom_snapshot(token: str, max_courses: int = 30) -> list[dict]:
    """Mỗi lớp đang học: {course, coursework, submissions, announcements} (chỉ các trường cần dùng)."""
    async with _client() as c:
        courses = await _classroom_get(
            c, token, "/courses", {"studentId": "me", "courseStates": "ACTIVE", "pageSize": 100}, "courses"
        )
        out = []
        for co in courses[:max_courses]:
            cid = co["id"]
            work = await _classroom_get(
                c, token, f"/courses/{cid}/courseWork",
                {"courseWorkStates": "PUBLISHED", "orderBy": "updateTime desc", "pageSize": 50}, "courseWork", 2,
            )  # fmt: skip
            subs = await _classroom_get(
                c, token, f"/courses/{cid}/courseWork/-/studentSubmissions",
                {"userId": "me", "pageSize": 100}, "studentSubmissions",
            )  # fmt: skip
            anns = await _classroom_get(
                c, token, f"/courses/{cid}/announcements",
                {"orderBy": "updateTime desc", "pageSize": 20}, "announcements", 1,
            )  # fmt: skip
            out.append({"course": co, "coursework": work, "submissions": subs, "announcements": anns})
        return out


# ---------------- Tệp đính kèm (002 US7) ----------------


def attachments_of(raw: dict) -> list[dict]:
    """Tệp đính kèm của một thư (tên, mime, kích thước, attachmentId hoặc dữ liệu nhỏ nằm sẵn trong thư)."""
    out: list[dict] = []

    def walk(part: dict) -> None:
        body = part.get("body", {}) or {}
        if part.get("filename") and (body.get("attachmentId") or body.get("data")):
            out.append(
                {
                    "name": str(part["filename"])[:200],
                    "mime": str(part.get("mimeType", ""))[:100],
                    "size": int(body.get("size") or 0),
                    "att_id": body.get("attachmentId"),
                    "data": body.get("data"),
                }
            )
        for child in part.get("parts", []) or []:
            walk(child)

    walk(raw.get("payload", {}) or {})
    return out


async def get_message_parts(token: str, gmail_id: str) -> tuple[Message, list[dict]]:
    async with _client() as c:
        r = await c.get(
            f"{GMAIL_URL}/messages/{gmail_id}",
            params={"format": "full"},
            headers={"Authorization": f"Bearer {token}"},
        )
    _check(r, "đọc thư")
    raw = r.json()
    return parse_gmail(raw), attachments_of(raw)


async def get_attachment(token: str, gmail_id: str, att: dict, max_bytes: int) -> bytes:
    """Nội dung tệp đính kèm (giải mã base64url). Quá `max_bytes` → GoogleError, không tải."""
    if att.get("size", 0) > max_bytes:
        raise GoogleError("Tệp quá lớn")
    data = att.get("data")
    if not data:
        async with _client() as c:
            r = await c.get(
                f"{GMAIL_URL}/messages/{gmail_id}/attachments/{att['att_id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
        _check(r, "tải tệp đính kèm")
        data = r.json().get("data", "")
    blob = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    if len(blob) > max_bytes:
        raise GoogleError("Tệp quá lớn")
    return blob
