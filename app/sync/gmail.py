"""Gmail tự động — US1 (002-auto-ingest).

Lần đầu: thư 7 ngày gần nhất. Các lần sau: chỉ thư mới qua Gmail history (không có thư mới → 1 lời gọi rẻ, 0 lượt
AI). Thư mới đi qua pipeline sẵn có (Triage → Extractor → Planner) với user_id của chủ hộp thư → tính vào hạn mức AI
riêng và trần chung. Có MSTUDENT_PUBSUB_TOPIC → đăng ký/gia hạn "báo ngay" (watch) mỗi ngày.
"""

from __future__ import annotations

import logging
import time

from .. import config, google_api, repo, security
from ..pipeline import orchestrator
from . import scheduler
from .scheduler import AuthError, RunResult, TemporaryError

log = logging.getLogger("mstudent")
RECONNECT = "Cần kết nối lại Gmail (quyền đã hết hạn hoặc bị thu hồi)"
FIRST_DAYS, MAX_PER_RUN = 7, 50


async def run(conn: dict) -> RunResult:
    uid = conn["user_id"]
    acct = repo.google_account(uid)
    refresh = security.decrypt(acct["refresh_token_enc"]) if acct else None
    if not refresh:
        raise AuthError(RECONNECT)
    state = dict(conn.get("state") or {})
    try:
        token = await google_api.access_token(refresh)
        if conn.get("cursor"):
            try:
                ids, history_id = await google_api.history_message_ids(token, conn["cursor"])
            except google_api.HistoryExpired:
                ids = await google_api.list_message_ids(token, 1, MAX_PER_RUN)
                history_id = await google_api.get_history_id(token)
        else:
            history_id = await google_api.get_history_id(token)
            ids = await google_api.list_message_ids(token, FIRST_DAYS, MAX_PER_RUN)
        res = RunResult(cursor=history_id, state=state, mode="")
        for gid in ids[:MAX_PER_RUN]:
            if repo.get_message(uid, f"gmail-{gid}"):
                res.skipped += 1  # đã xử lý → không tải, không gọi AI
                continue
            out = await orchestrator.ingest(uid, await google_api.get_message(token, gid))
            res.created += out.created
            res.updated += out.updated
            res.mode = "llm" if out.mode == "llm" or res.mode == "llm" else (res.mode or out.mode)
        await _renew_watch(token, state)
    except google_api.AuthRevoked as e:
        raise AuthError(RECONNECT) from e
    except google_api.GoogleError as e:
        raise TemporaryError(str(e)) from e
    repo.touch_google_sync(uid)
    res.mode = res.mode or "structured"
    return res


async def _renew_watch(token: str, state: dict) -> None:
    topic = config.pubsub_topic()
    if not topic or state.get("watch_expires_ms", 0) > (time.time() + 86400) * 1000:
        return
    try:
        state["watch_expires_ms"] = await google_api.watch(token, topic)
    except google_api.GoogleError as e:  # thiếu cấu hình Pub/Sub → vẫn chạy bằng kiểm tra định kỳ
        log.warning("Không đăng ký được Gmail watch: %s", type(e).__name__)


def register() -> None:
    scheduler.RUNNERS["gmail"] = run
