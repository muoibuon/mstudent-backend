"""Mật khẩu (Argon2id), JWT, refresh token, mã hoá khi lưu, giới hạn tần suất."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from . import config

# ---------------- Mật khẩu ----------------

_hasher = PasswordHasher()  # Argon2id với tham số mặc định theo khuyến nghị của thư viện
_DUMMY_HASH = _hasher.hash("mstudent-dummy-password")

COMMON_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "password1", "password123", "qwertyuiop",
    "11111111", "00000000", "iloveyou", "matkhau123", "anhyeuem", "abc12345", "abcd1234", "qwerty123",
}  # fmt: skip


def password_problem(password: str, email: str = "") -> str | None:
    """Trả về lý do mật khẩu không đạt, hoặc None nếu đạt."""
    if len(password) < 8:
        return "Mật khẩu cần ít nhất 8 ký tự"
    if len(password) > 128:
        return "Mật khẩu tối đa 128 ký tự"
    low = password.lower()
    if low in COMMON_PASSWORDS:
        return "Mật khẩu quá phổ biến, hãy chọn mật khẩu khác"
    if email and low in (email.lower(), email.lower().split("@")[0]):
        return "Mật khẩu không được trùng với email"
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> bool:
    """So khớp trong thời gian gần như không đổi, kể cả khi tài khoản không tồn tại (chống dò email)."""
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


# ---------------- JWT (access token, sống ngắn) ----------------

ALGO = "HS256"


def create_access_token(user_id: int) -> tuple[str, int]:
    now = config.utcnow()
    ttl = config.ACCESS_TTL_MIN * 60
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, config.secret_key(), algorithm=ALGO), ttl


def decode_access_token(token: str) -> int | None:
    try:
        data = jwt.decode(
            token, config.secret_key(), algorithms=[ALGO], options={"require": ["exp", "sub", "typ"]}
        )
    except jwt.PyJWTError:
        return None
    if data.get("typ") != "access":
        return None
    try:
        return int(data["sub"])
    except (TypeError, ValueError):
        return None


# ---------------- Refresh token (ngẫu nhiên, lưu dạng băm) ----------------


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_family() -> str:
    return uuid.uuid4().hex


# ---------------- Mã hoá khi lưu (token Google) ----------------


def encrypt(plain: str) -> str:
    return Fernet(config.fernet_key()).encrypt(plain.encode()).decode()


def decrypt(cipher: str) -> str | None:
    try:
        return Fernet(config.fernet_key()).decrypt(cipher.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------------- Giới hạn tần suất ----------------


class RateLimiter:
    """Cửa sổ trượt trong bộ nhớ. Đủ cho một tiến trình (localhost); nhiều tiến trình thì chuyển sang Redis."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: int) -> int | None:
        """Ghi nhận một lần gọi. Trả về số giây phải chờ nếu vượt giới hạn, None nếu được phép."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(window_s - (now - q[0])) + 1)
            q.append(now)
            return None

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


limiter = RateLimiter()
