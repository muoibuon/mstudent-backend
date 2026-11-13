"""Thông báo đẩy khi đồng bộ tự động tạo / cập nhật việc — US4 (002-auto-ingest).

Gửi qua Expo Push (Android; iPhone khi bản cài có quyền thông báo đẩy). Gom tối đa 1 thông báo cho mỗi lượt đồng bộ
của một nguồn; lượt đầu tiên của nguồn không gửi (FR-076). Nội dung chỉ có tên việc + hạn, không có nội dung tin
gốc hay người gửi (quyền riêng tư: thông báo đi qua máy chủ Expo / Google FCM). Lỗi gửi không bao giờ làm hỏng đồng bộ.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .. import config, repo
from ..models import Task
from . import scheduler
from .scheduler import RunResult

log = logging.getLogger("mstudent")
EXPO_URL = "https://exp.host/--/api/v2/push/send"
_transport: httpx.AsyncBaseTransport | None = None  # test gán MockTransport
WEEKDAY = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
SOURCE_NAME = {"gmail": "Gmail", "classroom": "Classroom", "ics": "lịch LMS", "sheet": "bảng lớp"}


def fmt_due(due_at: str | None) -> str:
    if not due_at:
        return "không có hạn"
    d = datetime.fromisoformat(due_at).astimezone(config.TZ)
    return f"hạn {WEEKDAY[d.weekday()]} {d:%d/%m %H:%M}"


def build_message(conn: dict, created: list[Task], updated: list[Task]) -> tuple[str, str, list[int]] | None:
    tasks = created or updated
    if not tasks:
        return None
    soonest = min(tasks, key=lambda t: t.due_at or "9999")
    line = f"{soonest.title} · {fmt_due(soonest.due_at)}"
    ids = [t.id for t in tasks]
    if len(tasks) == 1:
        return ("MStudent: việc mới" if created else "MStudent: cập nhật hạn"), line, ids
    where = conn.get("label") or SOURCE_NAME.get(conn["kind"], "nguồn tự động")
    title = f"MStudent: {len(tasks)} việc mới" if created else f"MStudent: {len(tasks)} việc được cập nhật"
    return title, f"Từ {where} · sớm nhất: {line}", ids


async def after_run(conn: dict, res: RunResult, first_run: bool) -> None:
    if first_run:
        return  # kết quả lượt đầu đã hiện trong app (FR-071)
    created = [t for t in res.created if t and t.status == "open"]
    updated = [t for t in res.updated if t and t.status == "open" and t.id not in {c.id for c in created}]
    msg = build_message(conn, created, updated)
    tokens = repo.push_tokens_for(conn["user_id"])  # chỉ token đang bật nhắc việc (FR-042)
    if not msg or not tokens:
        return
    title, body, ids = msg
    payload = [
        {
            "to": tok,
            "title": title,
            "body": body,
            "data": {"type": "tasks", "task_ids": ids[:20]},
            "channelId": "default",
            "sound": "default",
        }
        for tok in tokens
    ]
    try:
        async with httpx.AsyncClient(timeout=5, transport=_transport) as c:
            r = await c.post(EXPO_URL, json=payload, headers={"Accept": "application/json"})
        tickets = r.json().get("data", []) if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Không gửi được thông báo đẩy: %s", type(e).__name__)
        return
    for tok, ticket in zip(tokens, tickets, strict=False):
        if (
            ticket.get("status") == "error"
            and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered"
        ):
            repo.drop_push_token(tok)


def register() -> None:
    if after_run not in scheduler.AFTER_RUN:
        scheduler.AFTER_RUN.append(after_run)
