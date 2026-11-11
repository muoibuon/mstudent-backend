"""Tài khoản: đăng ký, đăng nhập (mật khẩu / Google), làm mới token, đăng xuất, đổi mật khẩu, xoá tài khoản."""

from __future__ import annotations

from datetime import datetime

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, google_api, repo, security
from ..deps import client_ip, current_user, enforce, is_admin
from ..models import (
    ChangePasswordRequest,
    Credentials,
    DeleteAccountRequest,
    GoogleLoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

BAD_LOGIN = "Email hoặc mật khẩu không đúng"


def user_out(user: dict) -> UserOut:
    return UserOut(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        is_admin=is_admin(user),
        has_password=bool(user["password_hash"]),
        google_linked=bool(user["google_sub"]),
        gmail_connected=repo.google_account(user["id"]) is not None,
    )


def issue_tokens(user: dict, device: str, family: str | None = None) -> TokenResponse:
    access, ttl = security.create_access_token(user["id"])
    refresh = security.new_refresh_token()
    repo.add_refresh_token(user["id"], security.token_hash(refresh), family or security.new_family(), device)
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=ttl, user=user_out(user))


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, request: Request):
    ip = client_ip(request)
    enforce(f"register:{ip}", 10, 3600)
    if not config.registration_open():
        raise HTTPException(403, "Hệ thống đang tạm đóng đăng ký")
    problem = security.password_problem(body.password, body.email)
    if problem:
        raise HTTPException(422, problem)
    if repo.user_by_email(body.email):
        raise HTTPException(409, "Email này đã có tài khoản — hãy đăng nhập")
    user = repo.create_user(body.email, body.name.strip(), security.hash_password(body.password))
    repo.audit("register", user["id"], ip)
    return issue_tokens(user, body.device)


@router.post("/login", response_model=TokenResponse)
def login(body: Credentials, request: Request):
    ip = client_ip(request)
    # Chống dò mật khẩu: theo cặp (ip, email) và theo ip.
    enforce(f"login:{ip}:{body.email}", 5, 300)
    enforce(f"login-ip:{ip}", 30, 300)
    user = repo.user_by_email(body.email)
    ok = security.verify_password(body.password, user["password_hash"] if user else None)
    if not user or not ok:
        repo.audit("login_failed", user["id"] if user else None, ip, body.email)
        raise HTTPException(401, BAD_LOGIN)
    security.limiter.reset(f"login:{ip}:{body.email}")
    updates = {"last_login_at": config.utcnow().isoformat()}
    if security.needs_rehash(user["password_hash"]):
        updates["password_hash"] = security.hash_password(body.password)
    repo.update_user(user["id"], **updates)
    repo.audit("login", user["id"], ip)
    return issue_tokens(user, body.device)


@router.post("/google", response_model=TokenResponse)
async def google_login(body: GoogleLoginRequest, request: Request):
    ip = client_ip(request)
    enforce(f"login-ip:{ip}", 30, 300)
    try:
        info = await anyio.to_thread.run_sync(google_api.verify_id_token, body.id_token)
    except google_api.GoogleError as e:
        repo.audit("google_login_failed", None, ip, str(e))
        raise HTTPException(401, str(e)) from e

    user = repo.user_by_google_sub(info["sub"])
    if user is None:
        user = repo.user_by_email(info["email"])
        if user is None:
            if not config.registration_open():
                raise HTTPException(403, "Hệ thống đang tạm đóng đăng ký")
            user = repo.create_user(info["email"], info["name"], None, google_sub=info["sub"])
            repo.audit("register_google", user["id"], ip)
        else:
            # Email trùng với tài khoản mật khẩu chưa từng xác minh email: Google đã xác minh chủ email,
            # nên vô hiệu mật khẩu cũ và mọi phiên cũ (chống kẻ đăng ký trước bằng email của người khác).
            repo.update_user(user["id"], google_sub=info["sub"], password_hash=None)
            repo.revoke_all_tokens(user["id"])
            repo.audit("google_linked", user["id"], ip)
            user = repo.user_by_id(user["id"])
    repo.update_user(user["id"], last_login_at=config.utcnow().isoformat())

    if body.server_auth_code:  # cấp quyền Gmail ngay khi đăng nhập
        try:
            tok = await google_api.exchange_code(body.server_auth_code)
            repo.save_google_account(
                user["id"],
                tok["email"] or info["email"],
                security.encrypt(tok["refresh_token"]),
                tok["scope"],
            )
            repo.audit("gmail_connected", user["id"], ip)
        except google_api.GoogleError:
            pass  # đăng nhập vẫn thành công; người dùng có thể kết nối Gmail lại trong Cài đặt
    repo.audit("login_google", user["id"], ip)
    return issue_tokens(user, body.device)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request):
    ip = client_ip(request)
    enforce(f"refresh:{ip}", 120, 300)
    invalid = HTTPException(401, "Phiên đã hết hạn, hãy đăng nhập lại")
    row = repo.get_refresh_token(security.token_hash(body.refresh_token))
    if row is None:
        raise invalid
    if row["revoked_at"] is not None or not repo.revoke_refresh_token(row["id"]):
        # Token đã xoay vòng mà còn bị dùng lại. Nếu vừa mới xoay (app bị tắt/mất mạng trước khi kịp lưu
        # token mới) thì cho qua trong khoảng ân hạn ngắn; ngoài khoảng đó coi như token bị lộ → thu hồi cả chuỗi.
        revoked = row["revoked_at"] or repo.get_refresh_token(row["token_hash"])["revoked_at"]
        age = (config.utcnow() - datetime.fromisoformat(revoked)).total_seconds()
        if age > config.REFRESH_REUSE_GRACE_S or not repo.family_alive(row["family"]):
            repo.revoke_family(row["family"])
            repo.audit("refresh_reuse_detected", row["user_id"], ip)
            raise invalid
    if row["expires_at"] < config.utcnow().isoformat():
        raise invalid
    user = repo.user_by_id(row["user_id"])
    if user is None:
        raise invalid
    return issue_tokens(user, row["device"], family=row["family"])


@router.post("/logout")
def logout(body: RefreshRequest):
    row = repo.get_refresh_token(security.token_hash(body.refresh_token))
    if row:
        repo.revoke_family(row["family"])
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, user: dict = Depends(current_user)):
    repo.revoke_all_tokens(user["id"])
    repo.audit("logout_all", user["id"], client_ip(request))
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(current_user)):
    return user_out(user)


@router.post("/change-password", response_model=TokenResponse)
def change_password(body: ChangePasswordRequest, request: Request, user: dict = Depends(current_user)):
    ip = client_ip(request)
    enforce(f"chpw:{user['id']}", 5, 900)
    # Tài khoản chỉ có Google (chưa có mật khẩu) được đặt mật khẩu mới mà không cần mật khẩu cũ.
    if user["password_hash"] and not security.verify_password(body.old_password, user["password_hash"]):
        repo.audit("change_password_failed", user["id"], ip)
        raise HTTPException(401, "Mật khẩu hiện tại không đúng")
    problem = security.password_problem(body.new_password, user["email"])
    if problem:
        raise HTTPException(422, problem)
    repo.update_user(user["id"], password_hash=security.hash_password(body.new_password))
    repo.revoke_all_tokens(user["id"])  # đăng xuất mọi thiết bị khác
    repo.audit("change_password", user["id"], ip)
    return issue_tokens(repo.user_by_id(user["id"]), "")


@router.delete("/me")
async def delete_account(body: DeleteAccountRequest, request: Request, user: dict = Depends(current_user)):
    if body.confirm_email.strip().lower() != user["email"].lower():
        raise HTTPException(400, "Email xác nhận không khớp")
    acct = repo.google_account(user["id"])
    if acct:
        token = security.decrypt(acct["refresh_token_enc"])
        if token:
            await google_api.revoke(token)
    repo.delete_user(user["id"])  # xoá toàn bộ việc, thông báo, trace, token (CASCADE)
    repo.audit("account_deleted", None, client_ip(request), f"user {user['id']}")
    return {"ok": True}
