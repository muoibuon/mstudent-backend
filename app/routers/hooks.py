"""Webhook công khai duy nhất (002): Google Pub/Sub báo có thư mới trong Gmail.

Ngoại lệ có biện minh với Constitution I (xem specs/002-auto-ingest/plan.md, Complexity Tracking):
- Xác thực bằng JWT do Google ký (OIDC của push subscription): chữ ký, iss, aud = URL này, email = service account.
- Không đọc thư, không gọi AI trong request: chỉ đặt lượt đồng bộ Gmail của người dùng đó chạy ngay.
- Luôn 204 khi chữ ký hợp lệ (kể cả email lạ) → không lộ ai đang dùng MStudent. Giới hạn 120 lần/phút toàn hệ thống.
"""

from __future__ import annotations

import base64
import binascii
import json

import anyio
from fastapi import APIRouter, HTTPException, Request, Response

from .. import google_api, repo
from ..deps import enforce

router = APIRouter(prefix="/api/hooks", tags=["hooks"])
MAX_BODY = 8 * 1024


@router.post("/gmail", status_code=204)
async def gmail_push(request: Request) -> Response:
    enforce("hook:gmail", 120, 60)
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "Quá lớn")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(403, "Thiếu chữ ký")
    try:
        await anyio.to_thread.run_sync(google_api.verify_push_jwt, auth[7:].strip())
    except google_api.GoogleError as e:
        raise HTTPException(403, "Chữ ký không hợp lệ") from e
    try:
        data = json.loads(base64.b64decode(json.loads(body)["message"]["data"]))
        email = str(data.get("emailAddress", ""))[:320]
    except (ValueError, KeyError, TypeError, binascii.Error):
        return Response(status_code=204)  # Pub/Sub sẽ không gửi lại thông báo hỏng
    uid = repo.google_user_by_email(email) if email else None
    conn = repo.find_connection(uid, "gmail", "") if uid else None
    if conn:
        repo.run_connection_now(uid, conn["id"])
    return Response(status_code=204)
