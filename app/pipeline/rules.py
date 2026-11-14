"""Triage + Extractor chạy offline bằng luật (không cần API key).

Dùng làm fallback khi mất mạng/hết credit lúc demo, và làm baseline để so với LLM trong eval.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from ..config import TZ
from ..models import Category, ExtractionOut, Message, TaskOut, TriageOut

SPAM = ["khuyến mãi", "giảm giá", "quảng cáo", "flash sale", "voucher", "mã giảm"]

# Thứ tự quan trọng: kiểm tra từ trên xuống.
CATEGORY_PATTERNS: list[tuple[Category, list[str]]] = [
    (
        Category.class_change,
        [
            r"nghỉ học",
            r"học bù",
            r"đổi phòng",
            r"chuyển phòng",
            r"dời lịch",
            r"đổi lịch",
            r"hoãn buổi",
            r"lịch học mới",
        ],
    ),
    (
        Category.event,
        [
            r"cuộc thi",
            r"hội thảo",
            r"workshop",
            r"seminar",
            r"sự kiện",
            r"hackathon",
            r"talkshow",
            r"ngày hội",
        ],
    ),
    (
        Category.exam,
        [
            r"\bthi\b",
            r"kiểm tra",
            r"giữa kỳ",
            r"cuối kỳ",
            r"midterm",
            r"final exam",
            r"\bquiz\b",
            r"\bexam\b",
        ],
    ),
    (
        Category.deadline,
        [
            r"hạn nộp",
            r"deadline",
            r"\bnộp\b",
            r"hạn chót",
            r"\bsubmit",
            r"\bdue\b",
            r"assignment",
            r"bài tập",
            r"báo cáo",
        ],
    ),
    (
        Category.admin,
        [
            r"học phí",
            r"đăng ký học phần",
            r"đăng ký môn",
            r"biểu mẫu",
            r"khảo sát",
            r"giấy xác nhận",
            r"bảo hiểm",
            r"học bổng",
        ],
    ),
]

COURSE_RE = re.compile(r"\b([A-Z]{2,4}\s?\d{3,4})\b")
DATE_RE = re.compile(r"(?<![\d/])(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?![\d/])")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:h|giờ|:)\s*(\d{2})?(?!\d)", re.IGNORECASE)
LOCATION_RE = re.compile(
    r"((?:phòng|P\.)\s*[A-Z]?\d{2,4}[A-Z]?|hội trường\s*\w*|giảng đường\s*\w*|online|zoom|"
    r"google meet|microsoft teams|ms teams)",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(r"(thứ\s*(?:hai|ba|tư|năm|sáu|bảy|[2-7])|chủ nhật)(\s*tuần\s*(?:này|sau|tới))?")
WEEKDAY_IDX = {
    "hai": 0,
    "2": 0,
    "ba": 1,
    "3": 1,
    "tư": 2,
    "4": 2,
    "năm": 3,
    "5": 3,
    "sáu": 4,
    "6": 4,
    "bảy": 5,
    "7": 5,
}


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def _received(msg: Message) -> datetime:
    from ..config import now

    if not msg.received_at:
        return now()
    dt = datetime.fromisoformat(msg.received_at)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def classify(text: str) -> Category:
    t = _norm(text)
    for cat, pats in CATEGORY_PATTERNS:
        if any(re.search(p, t) for p in pats):
            return cat
    if re.search(r"\b(?:tôi|mình|em)\s+học\b|\b(?:tiết|buổi|lịch)\s+học\b", t):
        return Category.class_change
    return Category.other


def find_date(text: str, ref: datetime) -> datetime | None:
    t = _norm(text)
    m = DATE_RE.search(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= d <= 31 and 1 <= mo <= 12:
            year = int(y) + (2000 if y and len(y) == 2 else 0) if y else ref.year
            try:
                dt = datetime(year, mo, d, tzinfo=TZ)
            except ValueError:
                return None
            if not y and dt < ref - timedelta(days=60):
                dt = dt.replace(year=year + 1)
            return dt
    if "hôm nay" in t or "tối nay" in t or "chiều nay" in t or "sáng nay" in t:
        return ref.replace(hour=0, minute=0, second=0, microsecond=0)
    if any(phrase in t for phrase in ("ngày mai", "sáng mai", "chiều mai", "tối mai")):
        return (ref + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    matches = list(WEEKDAY_RE.finditer(t))
    if matches:
        m = matches[-1]  # mốc nhắc sau cùng thường là mốc cần làm (vd. "nghỉ thứ 5, học bù thứ 7")
        name, qual = m.group(1), (m.group(2) or "")
        wd = 6 if name == "chủ nhật" else WEEKDAY_IDX[name.replace("thứ", "").strip()]
        monday = ref - timedelta(days=ref.weekday())
        if "sau" in qual or "tới" in qual:
            base = monday + timedelta(days=7 + wd)
        elif "này" in qual:
            base = monday + timedelta(days=wd)
        else:
            base = ref + timedelta(days=(wd - ref.weekday()) % 7)
        return base.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def default_daypart(text: str) -> tuple[str, int] | None:
    text = _norm(text)
    found = set()
    for match in re.finditer(r"\b(sáng|chiều|tối)\b", text):
        part = match.group(1)
        after = text[match.end() :].lstrip()
        if (
            (
                part == "sáng"
                and (re.search(r"\bánh\s*$", text[: match.start()]) or re.match(r"(?:tạo|kiến)\b", after))
            )
            or (part == "tối" and re.match(r"ưu\b", after))
            or (part == "chiều" and re.match(r"(?:dài|cao)\b", after))
        ):
            continue
        found.add(part)
    if len(found) == 1:
        part = found.pop()
        return part, {"sáng": 8, "chiều": 13, "tối": 19}[part]
    return None


def find_time(text: str) -> tuple[int, int] | None:
    for m in TIME_RE.finditer(_norm(text)):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    default = default_daypart(text)
    return (default[1], 0) if default else None


def apply_class_time_defaults(msg: Message, tasks: list[TaskOut]) -> list[TaskOut]:
    """Apply the agreed clock only to one unambiguous class; never invent a task."""
    text = f"{msg.subject}\n{msg.body}"
    part = default_daypart(text)
    if len(tasks) != 1 or tasks[0].category != Category.class_change or not part or TIME_RE.search(text):
        return tasks
    normalized = _norm(text)
    references = len(list(DATE_RE.finditer(text))) + len(list(WEEKDAY_RE.finditer(normalized)))
    references += len(
        re.findall(
            r"\b(?:ngày mai|sáng mai|chiều mai|tối mai|hôm nay|sáng nay|chiều nay|tối nay)\b", normalized
        )
    )
    if references > 1:
        return tasks
    day = find_date(text, _received(msg))
    if day is None:
        return tasks
    label, hour = part
    note = f"Giờ mặc định buổi {label}: {hour:02}:00"
    action = tasks[0].action or "Tham gia buổi học"
    if note not in action:
        action = action[: max(0, 198 - len(note))] + "; " + note
    return [tasks[0].model_copy(update={"due_at": day.replace(hour=hour).isoformat(), "action": action})]


def triage(msg: Message) -> TriageOut:
    text = f"{msg.subject}\n{msg.body}"
    t = _norm(text)
    if any(s in t for s in SPAM):
        return TriageOut(relevant=False, category=Category.other, reason="Quảng cáo / khuyến mãi")
    cat = classify(text)
    has_date = find_date(text, _received(msg)) is not None
    if cat == Category.other and not has_date:
        return TriageOut(relevant=False, category=cat, reason="Không có việc cần làm hay mốc thời gian")
    return TriageOut(
        relevant=True, category=cat, reason="Có từ khoá học vụ" + (" và mốc thời gian" if has_date else "")
    )


def _title(msg: Message, cat: Category, course: str | None) -> str:
    if msg.subject.strip():
        base = msg.subject.strip()
    else:
        first = re.split(r"(?<=[.!?\n])\s", msg.body.strip(), maxsplit=1)[0]
        base = first.strip()
    base = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", base)  # bỏ tiền tố [CSE3032]...
    if course and course not in base:
        base = f"{course}: {base}"
    base = re.split(r"(?<=[.!?])\s", base, maxsplit=1)[0].strip()
    if len(base) > 70:
        base = base[:70].rsplit(" ", 1)[0] + "…"
    return base


def extract(msg: Message, category: Category | None = None) -> ExtractionOut:
    text = f"{msg.subject}\n{msg.body}"
    ref = _received(msg)
    cat = category or classify(text)
    cm = COURSE_RE.search(text)
    course = cm.group(1).replace(" ", "") if cm else None

    due = None
    d = find_date(text, ref)
    if d is not None:
        tm = find_time(text)
        if tm:
            due = d.replace(hour=tm[0], minute=tm[1])
        else:
            due = d.replace(hour=23, minute=59) if cat == Category.deadline else d.replace(hour=8)

    loc = LOCATION_RE.search(text)
    action = {
        Category.deadline: "Hoàn thành và nộp bài",
        Category.exam: "Ôn tập và đi thi đúng giờ",
        Category.class_change: "Cập nhật lịch học",
        Category.event: "Đăng ký / tham gia nếu quan tâm",
        Category.admin: "Hoàn tất thủ tục",
    }.get(cat)
    return ExtractionOut(
        tasks=[
            TaskOut(
                title=_title(msg, cat, course),
                course=course,
                category=cat,
                due_at=due.isoformat() if due else None,
                location=loc.group(1) if loc else None,
                action=action,
            )
        ]
    )
