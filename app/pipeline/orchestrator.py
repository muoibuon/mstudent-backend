"""Orchestrator: Message → Triage → Extractor → Planner → Store.

Chế độ 'llm' dùng OpenAI Agents SDK; nếu lỗi hoặc không có key thì tự rơi về 'offline' (luật).
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime

from .. import config, store
from ..models import IngestResult, Message, Priority, Task
from . import planner, rules

log = logging.getLogger("mstudent")
WEEKDAY_VI = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def _msg_id(msg: Message) -> str:
    raw = f"{msg.source.value}|{msg.sender}|{msg.subject}|{msg.body}"
    return msg.id or hashlib.sha1(raw.encode()).hexdigest()[:12]


async def ingest(msg: Message) -> IngestResult:
    msg = msg.model_copy(
        update={"id": _msg_id(msg), "received_at": msg.received_at or config.now().isoformat()}
    )
    mode = "offline"
    tri = ext = None
    if config.llm_enabled():
        try:
            from . import llm_agents

            tri = await llm_agents.llm_triage(msg)
            if tri.relevant:
                ext = await llm_agents.llm_extract(msg)
            mode = "llm"
        except Exception as e:  # mạng/credit/model lỗi → không làm hỏng demo
            log.warning("LLM lỗi, chuyển sang offline: %s", e)
            tri = ext = None
    if tri is None:
        tri = rules.triage(msg)
        ext = rules.extract(msg, tri.category) if tri.relevant else None

    store.save_message(msg, tri.relevant, tri.category, tri.reason)
    created: list[Task] = []
    updated: list[Task] = []
    if tri.relevant and ext and ext.tasks:
        ref = datetime.fromisoformat(msg.received_at)
        created, updated = planner.plan(ext.tasks, source=msg.source.value, message_id=msg.id, ref=ref)
    return IngestResult(
        message_id=msg.id,
        relevant=tri.relevant,
        category=tri.category,
        reason=tri.reason,
        created=created,
        updated=updated,
        mode=mode,
    )


def digest_text(tasks: list[Task], ref: datetime) -> str:
    """Bản tin không cần LLM: nhóm theo ngày trong 7 ngày tới."""
    upcoming = [
        t
        for t in tasks
        if t.due_at and 0 <= (datetime.fromisoformat(t.due_at) - ref).total_seconds() < 7 * 86400
    ]
    if not upcoming:
        return "Tuần này chưa có việc nào có hạn. 🎉"
    urgent = sum(1 for t in upcoming if t.priority == Priority.high)
    lines = [f"Bạn có {len(upcoming)} việc trong 7 ngày tới, {urgent} việc gấp."]
    by_day: dict[str, list[Task]] = defaultdict(list)
    for t in upcoming:
        d = datetime.fromisoformat(t.due_at)
        by_day[f"{WEEKDAY_VI[d.weekday()]} {d:%d/%m}"].append(t)
    for day, items in by_day.items():
        lines.append(f"\n{day}")
        for t in items:
            mark = "⚠️ " if t.priority == Priority.high else "• "
            hhmm = datetime.fromisoformat(t.due_at).strftime("%H:%M")
            extra = " — ".join(x for x in [t.course, t.location] if x and x not in t.title)
            lines.append(f"{mark}{hhmm} — {t.title}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines)


async def digest() -> dict:
    ref = config.now()
    tasks = planner.live(store.list_tasks("open"), ref)
    if config.llm_enabled():
        try:
            from . import llm_agents

            return {"mode": "llm", "text": await llm_agents.llm_digest(tasks)}
        except Exception as e:
            log.warning("Digest LLM lỗi: %s", e)
    return {"mode": "offline", "text": digest_text(tasks, ref)}
