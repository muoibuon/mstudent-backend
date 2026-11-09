"""Planner agent (thuần Python): ưu tiên, nhắc việc, gộp trùng."""

from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher

from .. import store
from ..config import TZ
from ..models import Category, Priority, Task, TaskOut


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def priority(task: TaskOut | Task, ref: datetime) -> Priority:
    due = _dt(task.due_at)
    if due is None:
        return Priority.low
    hours = (due - ref).total_seconds() / 3600
    if hours <= 48 or task.category == Category.exam:
        return Priority.high
    if hours <= 24 * 7:
        return Priority.medium
    return Priority.low


def reminders(task: TaskOut, ref: datetime) -> list[str]:
    due = _dt(task.due_at)
    if due is None:
        return []
    offsets = [timedelta(days=3), timedelta(days=1), timedelta(hours=2)]
    if task.category == Category.exam:
        offsets = [timedelta(days=7)] + offsets
    return [(due - o).isoformat() for o in offsets if due - o > ref]


def _similar(a: Task, b: TaskOut) -> bool:
    if a.course and b.course and a.course != b.course:
        return False
    da, db = _dt(a.due_at), _dt(b.due_at)
    same_day = da and db and da.date() == db.date()
    ratio = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
    return bool((same_day and ratio > 0.45) or ratio > 0.8)


def plan(
    drafts: list[TaskOut], *, source: str, message_id: str, ref: datetime
) -> tuple[list[Task], list[Task]]:
    """Trả về (task mới, task được cập nhật)."""
    created, updated = [], []
    existing = store.list_tasks("open")
    for d in drafts:
        match = next((t for t in existing if _similar(t, d)), None)
        fields = {
            "title": d.title,
            "course": d.course,
            "category": d.category.value,
            "due_at": d.due_at,
            "location": d.location,
            "action": d.action,
            "priority": priority(d, ref).value,
            "reminders": reminders(d, ref),
        }
        if match:
            # Tin mới hơn ghi đè giờ/địa điểm (vd. "dời hạn nộp"), giữ lại trường cũ nếu tin mới thiếu.
            merged = {k: v for k, v in fields.items() if v not in (None, [], "") and k != "title"}
            merged["updated_from"] = match.updated_from + [message_id]
            updated.append(store.update_task(match.id, merged))
        else:
            created.append(store.insert_task({**fields, "source": source, "message_id": message_id}))
    return created, updated


def live(tasks: list[Task], ref: datetime) -> list[Task]:
    """Tính lại ưu tiên theo thời điểm hiện tại (việc càng gần hạn càng gấp)."""
    return [t.model_copy(update={"priority": priority(t, ref)}) for t in tasks]
