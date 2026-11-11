"""Planner agent (thuần Python): ưu tiên, nhắc việc, gộp trùng — theo từng người dùng."""

from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher

from .. import repo
from ..config import TZ
from ..models import Category, Priority, Task, TaskOut


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def sanitize(drafts: list[TaskOut], max_tasks: int = 5) -> list[TaskOut]:
    """Kiểm tra đầu ra của LLM trước khi ghi CSDL: cắt độ dài, bỏ ngày sai định dạng, giới hạn số việc."""
    out: list[TaskOut] = []
    for d in drafts[:max_tasks]:
        title = " ".join((d.title or "").split())[:120]
        if not title:
            continue
        due = _dt(d.due_at)
        out.append(
            d.model_copy(
                update={
                    "title": title,
                    "due_at": due.isoformat() if due else None,
                    "course": (d.course or None) and d.course.strip()[:60],
                    "location": (d.location or None) and d.location.strip()[:120],
                    "action": (d.action or None) and d.action.strip()[:200],
                }
            )
        )
    return out


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
    user_id: int, drafts: list[TaskOut], *, source: str, message_id: str, ref: datetime
) -> tuple[list[Task], list[Task]]:
    """Trả về (task mới, task được cập nhật)."""
    created, updated = [], []
    existing = repo.list_tasks(user_id, "open")
    for d in sanitize(drafts):
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
            task = repo.update_task(user_id, match.id, merged)
            if task:
                updated.append(task)
        else:
            created.append(repo.insert_task(user_id, {**fields, "source": source, "message_id": message_id}))
    return created, updated


def live(tasks: list[Task], ref: datetime) -> list[Task]:
    """Tính lại ưu tiên theo thời điểm hiện tại (việc càng gần hạn càng gấp)."""
    return [t.model_copy(update={"priority": priority(t, ref)}) for t in tasks]
