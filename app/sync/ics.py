"""Lịch LMS (.ics) tự động — phần lịch của US1 (002-auto-ingest).

Tải lại link xuất lịch mỗi giờ (ETag → 304 thì không làm gì). Sự kiện là dữ liệu có cấu trúc: tạo/cập nhật việc trực
tiếp qua planner, KHÔNG gọi AI. Khoá mỗi sự kiện = UID; hạn hoặc tiêu đề đổi → cập nhật việc cũ (FR-013).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import anyio
import httpx
from fastapi import HTTPException

from .. import config, repo
from ..connectors import lms_ics
from ..models import TaskOut
from ..pipeline import planner
from . import scheduler
from .common import MAX_ITEMS_PER_RUN, MAX_ITEMS_SEEN, ensure_public_url, guess_category, short_hash
from .scheduler import RunResult, TemporaryError

MAX_BYTES = 2 * 1024 * 1024
BAD_LINK = "Không đọc được lịch từ link này — vào LMS → Lịch → Xuất lịch (Export calendar) → lấy lại URL rồi dán vào đây"


def _ensure_public_url(url: str) -> None:
    ensure_public_url(url)


async def fetch(url: str, etag: str | None) -> tuple[int, str, str | None]:
    """(status, nội dung, etag mới). Không theo chuyển hướng (tránh bị dẫn sang địa chỉ nội bộ)."""
    await anyio.to_thread.run_sync(_ensure_public_url, url)
    headers = {"User-Agent": "MStudent/1.0"}
    if etag:
        headers["If-None-Match"] = etag
    async with (
        httpx.AsyncClient(timeout=15, follow_redirects=False) as client,
        client.stream("GET", url, headers=headers) as r,
    ):
        if r.status_code == 304:
            return 304, "", etag
        if r.status_code >= 400 or r.status_code in (301, 302, 303, 307, 308):
            raise TemporaryError(BAD_LINK if r.status_code < 500 else "Máy chủ LMS đang lỗi, sẽ thử lại")
        buf = bytearray()
        async for chunk in r.aiter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise TemporaryError("File lịch quá lớn (tối đa 2 MB)")
        return r.status_code, buf.decode("utf-8", "replace"), r.headers.get("etag")


async def probe(url: str) -> tuple[str, str]:
    url = url.strip()
    try:
        await anyio.to_thread.run_sync(_ensure_public_url, url)
        _, text, _ = await fetch(url, None)
    except TemporaryError as e:
        raise HTTPException(400, str(e)) from e
    if "BEGIN:VCALENDAR" not in text:
        raise HTTPException(400, BAD_LINK)
    return url, "Lịch LMS"


async def run(conn: dict) -> RunResult:
    uid = conn["user_id"]
    first = conn.get("last_ok_at") is None
    status, text, etag = await fetch(conn["target"], None if first else conn.get("cursor"))
    res = RunResult(mode="structured", cursor=etag, state=dict(conn.get("state") or {}))
    if status == 304:
        return res
    if "BEGIN:VCALENDAR" not in text:
        raise TemporaryError(BAD_LINK)
    ref = config.now()
    seen: set[str] = set()
    processed = 0
    for ev in lms_ics.parse_events(text)[:MAX_ITEMS_SEEN]:
        await asyncio.sleep(0)  # nhường event loop: không treo máy chủ với lịch rất lớn
        title = ev["summary"].strip()
        if not title:
            continue
        key = ev["uid"] or short_hash(title, ev["due"] or "")
        chash = short_hash(title, ev["due"] or "", ev["course"])
        seen.add(key)
        prev = repo.get_source_item(conn["id"], key)
        if prev and prev["content_hash"] == chash:
            res.skipped += 1
            continue
        if processed >= MAX_ITEMS_PER_RUN:
            res.state["more"] = True  # còn mục chưa xử lý → lượt sau
            continue
        processed += 1
        if prev and prev["task_id"]:
            task = repo.get_task(uid, prev["task_id"])
            if task is None or task.status == "done":
                repo.upsert_source_item(uid, conn["id"], key, chash, None)
                res.skipped += 1
                continue
        if first and ev["due"] and datetime.fromisoformat(ev["due"]) < ref - timedelta(days=1):
            repo.upsert_source_item(uid, conn["id"], key, chash, None)
            res.skipped += 1
            continue
        course = ev["course"] or planner.course_code(title) or None
        draft = TaskOut(
            title=title[:80],
            course=course,
            category=guess_category(title),
            due_at=ev["due"],
            location=None,
            action=None,
        )
        created, updated = planner.plan(uid, [draft], source="lms", message_id=f"lms-{key}"[:200], ref=ref)
        res.created += created
        res.updated += updated
        touched = (created + updated)[:1]
        repo.upsert_source_item(uid, conn["id"], key, chash, touched[0].id if touched else None)
    stamp = ref.strftime("%d/%m")
    for g in repo.mark_items_gone(conn["id"], seen):
        task = repo.get_task(uid, g["task_id"]) if g["task_id"] else None
        if task and task.status == "open":
            repo.update_task(uid, task.id, {"note": f"Không còn trong lịch LMS ({stamp})"})
    return res


def register() -> None:
    scheduler.RUNNERS["ics"] = run
