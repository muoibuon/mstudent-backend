"""Nhập các buổi học của tuần sắp tới từ bảng lịch trong tệp đính kèm."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import config, repo
from ..models import Category, Priority, Source, Task
from . import planner

MAX_SESSIONS = 40
DATE = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?(?!\d)")
TIME = re.compile(r"(?<!\d)(\d{1,2})\s*[:h]\s*(\d{1,2})(?!\d)", re.I)
WEEKDAY = {
    "thu hai": 0,
    "thu 2": 0,
    "t2": 0,
    "thu ba": 1,
    "thu 3": 1,
    "t3": 1,
    "thu tu": 2,
    "thu 4": 2,
    "t4": 2,
    "thu nam": 3,
    "thu 5": 3,
    "t5": 3,
    "thu sau": 4,
    "thu 6": 4,
    "t6": 4,
    "thu bay": 5,
    "thu 7": 5,
    "t7": 5,
    "chu nhat": 6,
    "cn": 6,
}
WEEKDAY_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in WEEKDAY) + r")(?!\w)")
INTENT = re.compile(r"(?:thêm|xếp|tạo|đưa|lưu|sắp).{0,70}(?:lịch|thời khóa biểu)", re.I | re.S)


@dataclass(frozen=True)
class Session:
    course: str
    start: datetime
    end_time: str


def wants_schedule(message: str) -> bool:
    return bool(INTENT.search(message))


def _fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(ch) != "Mn"
    ).replace("đ", "d")


def parse(text: str, now: datetime) -> list[Session]:
    """Chỉ nhận dòng bảng có môn, ngày/thứ và giờ bắt đầu; không đoán dữ liệu thiếu."""
    found: dict[tuple[str, str], Session] = {}
    for line in text.splitlines()[:2000]:
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 2 or not cells[0]:
            continue
        course = cells[0][:60]
        date_match = DATE.search(line)
        weekday_match = WEEKDAY_RE.search(_fold(line))
        time_matches = list(TIME.finditer(line))
        if not time_matches or not (date_match or weekday_match):
            continue
        try:
            hour, minute = (int(x) for x in time_matches[0].groups())
            if hour > 23 or minute > 59:
                continue
            end_hour, end_minute = (
                (int(x) for x in time_matches[1].groups()) if len(time_matches) > 1 else (hour, minute)
            )
            if end_hour > 23 or end_minute > 59:
                continue
            day = None
            if date_match:
                d, m, y = date_match.groups()
                day = datetime(int(y or now.year), int(m), int(d), tzinfo=config.TZ)
            weekly = bool(re.search(r"hang tuan|weekly", _fold(line))) or (
                day is None and weekday_match is not None
            )
            if weekly:
                weekday = WEEKDAY[weekday_match.group(1).lower()] if weekday_match else day.weekday()
                day = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                start = day.replace(hour=hour, minute=minute)
                if start <= now:
                    start += timedelta(days=7)
            elif day is not None:
                start = day.replace(hour=hour, minute=minute)
                if not now < start <= now + timedelta(days=7):
                    continue
            else:
                continue
        except (ValueError, AttributeError):
            continue
        key = (course.casefold(), start.isoformat())
        found[key] = Session(course=course, start=start, end_time=f"{end_hour:02d}:{end_minute:02d}")
        if len(found) >= MAX_SESSIONS:
            break
    return sorted(found.values(), key=lambda s: s.start)


def add(user_id: int, text: str, filename: str) -> tuple[list[Task], int]:
    """Ghi lịch của đúng người dùng; gửi lại cùng bảng không tạo bản sao."""
    now = config.now()
    sessions = parse(text, now)
    existing = {(t.title.casefold(), t.due_at) for t in repo.list_tasks(user_id, None)}
    created: list[Task] = []
    skipped = 0
    for session in sessions:
        title = f"Học {session.course}"[:120]
        due = session.start.isoformat()
        key = (title.casefold(), due)
        if key in existing:
            skipped += 1
            continue
        task_id = hashlib.sha256(f"schedule|{filename}|{title}|{due}".encode()).hexdigest()[:32]
        task = repo.insert_task(
            user_id,
            {
                "title": title,
                "course": session.course,
                "category": Category.other.value,
                "due_at": due,
                "action": f"Buổi học, kết thúc {session.end_time}",
                "priority": Priority.low.value,
                "source": Source.manual.value,
                "message_id": task_id,
                "reminders": planner.reminders(task_like(session), now),
                "note": f"Nhập từ {filename[:80]} · kết thúc {session.end_time}",
            },
        )
        created.append(task)
        existing.add(key)
    return created, skipped


def task_like(session: Session):
    """Đầu vào tối thiểu cho planner.reminders; không cần một bản ghi DB tạm."""
    from ..models import TaskOut

    return TaskOut(
        title=session.course,
        course=session.course,
        category=Category.other,
        due_at=session.start.isoformat(),
        location=None,
        action=None,
    )
