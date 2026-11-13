"""Gmail chỉ-đọc: kết nối, quét thư mới qua pipeline agent, ngắt kết nối."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import google_api, repo, security
from ..deps import ai_limit, client_ip, current_user, enforce
from ..models import GmailSyncRequest, GoogleConnectRequest
from ..pipeline import orchestrator

router = APIRouter(prefix="/api/google", tags=["google"])


@router.get("/status")
def status(user: dict = Depends(current_user)):
    acct = repo.google_account(user["id"])
    if not acct:
        return {"connected": False}
    return {"connected": True, "email": acct["email"], "last_sync_at": acct["last_sync_at"]}


@router.post("/connect")
async def connect(body: GoogleConnectRequest, request: Request, user: dict = Depends(current_user)):
    enforce(f"gconnect:{user['id']}", 10, 600)
    try:
        tok = await google_api.exchange_code(body.server_auth_code)
    except google_api.GoogleError as e:
        raise HTTPException(400, str(e)) from e
    repo.save_google_account(
        user["id"], tok["email"] or user["email"], security.encrypt(tok["refresh_token"]), tok["scope"]
    )
    repo.audit("gmail_connected", user["id"], client_ip(request))
    # 002: từ giờ máy chủ tự đồng bộ (lượt đầu chạy ngay); người dùng không phải bấm gì nữa.
    repo.create_connection(user["id"], "gmail", "", tok["email"] or user["email"])
    return {"connected": True, "email": tok["email"] or user["email"]}


@router.post("/gmail/sync")
async def gmail_sync(body: GmailSyncRequest, user: dict = Depends(ai_limit)):
    """Đọc thư mới trong hộp thư đến và đưa từng thư qua Triage → Extractor → Planner."""
    enforce(f"gsync:{user['id']}", 12, 600)
    acct = repo.google_account(user["id"])
    if not acct:
        raise HTTPException(409, "Chưa kết nối Gmail")
    refresh = security.decrypt(acct["refresh_token_enc"])
    if not refresh:
        repo.delete_google_account(user["id"])
        raise HTTPException(409, "Không giải mã được quyền Gmail (khoá server đã đổi) — hãy kết nối lại")
    try:
        token = await google_api.access_token(refresh)
        ids = await google_api.list_message_ids(token, body.days, body.max_messages)
        results = []
        for gid in ids:
            if repo.get_message(user["id"], f"gmail-{gid}"):
                continue  # đã xử lý ở lần quét trước → không tải, không gọi LLM
            msg = await google_api.get_message(token, gid)
            results.append(await orchestrator.ingest(user["id"], msg))
    except google_api.GoogleError as e:
        raise HTTPException(502, str(e)) from e
    repo.touch_google_sync(user["id"])
    return {
        "scanned": len(ids),
        "new": len(results),
        "tasks_created": sum(len(r.created) for r in results),
        "tasks_updated": sum(len(r.updated) for r in results),
        "noise_filtered": sum(1 for r in results if not r.relevant),
        "results": results,
    }


@router.delete("/disconnect")
async def disconnect(request: Request, user: dict = Depends(current_user)):
    acct = repo.google_account(user["id"])
    if acct:
        token = security.decrypt(acct["refresh_token_enc"])
        if token:
            await google_api.revoke(token)
        repo.delete_google_account(user["id"])
        repo.delete_connections_of_kind(user["id"], ("gmail", "classroom"))
        repo.audit("gmail_disconnected", user["id"], client_ip(request))
    return {"connected": False}
