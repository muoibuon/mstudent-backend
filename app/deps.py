"""Dependency dùng chung: người dùng hiện tại, quyền admin, giới hạn tần suất."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from . import config, repo, security


def client_ip(request: Request) -> str:
    # Không tin X-Forwarded-For trừ khi tự đặt proxy tin cậy ở trước; mặc định dùng địa chỉ kết nối.
    return request.client.host if request.client else "unknown"


def is_admin(user: dict) -> bool:
    return user["email"].lower() in config.admin_emails()


def current_user(authorization: str | None = Header(None)) -> dict:
    """Xác thực `Authorization: Bearer <access token>` và nạp người dùng từ CSDL."""
    unauthorized = HTTPException(
        401, "Chưa đăng nhập hoặc phiên đã hết hạn", headers={"WWW-Authenticate": "Bearer"}
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized
    user_id = security.decode_access_token(authorization[7:].strip())
    if user_id is None:
        raise unauthorized
    user = repo.user_by_id(user_id)
    if user is None:  # tài khoản đã bị xoá
        raise unauthorized
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên (MSTUDENT_ADMIN_EMAILS) mới được làm việc này")
    return user


def enforce(key: str, limit: int, window_s: int) -> None:
    wait = security.limiter.hit(key, limit, window_s)
    if wait is not None:
        raise HTTPException(
            429, f"Quá nhiều yêu cầu, thử lại sau {wait} giây", headers={"Retry-After": str(wait)}
        )


def ai_limit(user: dict = Depends(current_user)) -> dict:
    """Giới hạn số lần gọi agent mỗi người (bảo vệ chi phí LLM): 30 lần/phút, 600 lần/ngày."""
    enforce(f"ai:m:{user['id']}", 30, 60)
    enforce(f"ai:d:{user['id']}", 600, 86400)
    return user
