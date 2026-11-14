"""Planner agent (thuần Python): ưu tiên, nhắc việc, gộp trùng — theo từng người dùng."""

from __future__ import annotations

import re
import unicodedata
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
    if due is None:  # việc không có hạn: giữ mức đã lưu (004: có thể lấy từ AI quyết định), mặc định thấp
        return getattr(task, "priority", None) or Priority.low
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


# ---------------- Gộp việc giữa các nguồn (FR-009) ----------------

_CODE_RE = re.compile(r"\b([A-Z]{2,5})\s?(\d{3,4}[A-Z]?)\b")
# Nguồn có cấu trúc cho hạn chính xác hơn → khi gộp, hạn của nguồn hạng cao hơn được giữ.
SOURCE_RANK = {"classroom": 3, "lms": 3, "sheet": 2}


def fold(text: str | None) -> str:
    """Bỏ dấu, viết thường, gộp khoảng trắng: "Mạng  Máy tính" → "mang may tinh"."""
    t = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


def course_code(*texts: str | None) -> str | None:
    for t in texts:
        m = _CODE_RE.search((t or "").upper())
        if m:
            return m.group(1) + m.group(2)
    return None


def _course_conflict(a: Task, b: TaskOut) -> bool:
    """True nếu chắc chắn là hai môn khác nhau → không bao giờ gộp."""
    ca, cb = course_code(a.course), course_code(b.course)
    if ca and cb:
        return ca != cb
    if ca or cb:  # một bên là mã, một bên là tên → không so được, không coi là xung đột
        return False
    na, nb = fold(a.course), fold(b.course)
    return bool(na and nb and na not in nb and nb not in na)


def _score(a: Task, b: TaskOut) -> float:
    """Điểm giống nhau (0 = không gộp). Mã học phần trùng hạ ngưỡng tiêu đề."""
    if _course_conflict(a, b):
        return 0.0
    da, db = _dt(a.due_at), _dt(b.due_at)
    same_day = bool(da and db and da.date() == db.date())
    ratio = SequenceMatcher(None, fold(a.title), fold(b.title)).ratio()
    code_a, code_b = course_code(a.course, a.title), course_code(b.course, b.title)
    same_code = bool(code_a and code_a == code_b)
    threshold = 0.35 if same_code else 0.45
    if (same_day and ratio > threshold) or ratio > 0.8:
        return ratio + (0.5 if same_day else 0) + (0.3 if same_code else 0)
    return 0.0


def match_existing(existing: list[Task], d: TaskOut) -> Task | None:
    best, best_score = None, 0.0
    for t in existing:
        sc = _score(t, d)
        if sc > best_score:
            best, best_score = t, sc
    return best


def _rank(sources: list[str]) -> int:
    return max((SOURCE_RANK.get(s, 1) for s in sources), default=1)


def plan(
    user_id: int,
    drafts: list[TaskOut],
    *,
    source: str,
    message_id: str,
    ref: datetime,
    hint_task_id: int | None = None,
) -> tuple[list[Task], list[Task]]:
    """Trả về (task mới, task được cập nhật). Gộp với việc đã có (kể cả từ nguồn khác) theo FR-009."""
    created, updated = [], []
    # Việc đã xong vẫn dùng để so khớp: khớp → bỏ qua (không mở lại, không tạo trùng — FR-074).
    existing = [
        t for t in repo.list_tasks(user_id, None, include_invites=True) if t.status in ("open", "done")
    ]
    clean = sanitize(drafts)
    # 004: AI quyết định chỉ ra việc cũ bị ảnh hưởng. Chỉ dùng khi tin ra đúng MỘT việc, việc đó còn mở, thuộc chính
    # người dùng (có trong `existing`) và không khác môn; mọi trường hợp khác → so khớp như cũ.
    hinted = (
        next((t for t in existing if t.id == hint_task_id and t.status == "open"), None)
        if hint_task_id
        else None
    )
    for d in clean:
        match = None
        if hinted is not None and len(clean) == 1 and not _course_conflict(hinted, d):
            match = hinted
        match = match or match_existing(existing, d)
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
        if match and match.status == "done":
            continue
        if match:
            # Tin mới hơn ghi đè giờ/địa điểm (vd. "dời hạn nộp"), giữ lại trường cũ nếu tin mới thiếu.
            merged = {k: v for k, v in fields.items() if v not in (None, [], "") and k != "title"}
            old_sources = match.sources or [match.source.value]
            if SOURCE_RANK.get(source, 1) < _rank(old_sources):
                for k in ("due_at", "priority", "reminders"):  # hạn từ nguồn có cấu trúc chính xác hơn
                    merged.pop(k, None)
            if course_code(match.course) and not course_code(d.course):
                merged.pop("course", None)  # giữ mã học phần, đừng thay bằng tên môn
            merged["updated_from"] = match.updated_from + [message_id]
            merged["sources"] = old_sources + ([source] if source not in old_sources else [])
            task = repo.update_task(user_id, match.id, merged)
            if task:
                updated.append(task)
                existing = [task if t.id == task.id else t for t in existing]
        else:
            task = repo.insert_task(
                user_id, {**fields, "source": source, "message_id": message_id, "sources": [source]}
            )
            created.append(task)
            existing.append(task)
    return created, updated


def live(tasks: list[Task], ref: datetime) -> list[Task]:
    """Tính lại ưu tiên theo thời điểm hiện tại (việc càng gần hạn càng gấp)."""
    return [t.model_copy(update={"priority": priority(t, ref)}) for t in tasks]
