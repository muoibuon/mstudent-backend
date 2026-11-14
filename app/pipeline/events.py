"""003-event-rsvp: chi tiết sự kiện, lời mời Tham gia / Không, mức phù hợp với ngành.

- Việc category `event` do pipeline tạo → `enrich_event()` gắn chi tiết + `rsvp` (`pending`; bắt buộc → `going`).
- Chi tiết: agent EventDetails (không tool, GUARD) hoặc `details_rules()` khi AI tắt. Link chỉ nhận http(s).
- Form đăng ký: `fetch_form_meta()` đọc cấu trúc Google Form CÔNG KHAI (allowlist host, ≤ 1 MB) → vai trò từng câu.
  Máy chủ không dựng link điền sẵn (không ghép dữ liệu cá nhân vào URL) — app tự dựng trên máy; không ai tự gửi form.
- Phù hợp với ngành: agent MajorFit hoặc `fit_rules()` (ghi `fit_mode='offline'`, UI phải hiện rõ).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import anyio
import httpx

from .. import budget, config, repo
from ..models import Category, EventDetails, MajorFitOut, Message, Task
from . import rules

log = logging.getLogger("mstudent")

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
MAX_URL = 500
MAX_FORM_BYTES = 1_000_000
FORM_HOSTS = {"docs.google.com", "forms.gle"}
_transport: httpx.AsyncBaseTransport | None = None  # test gán MockTransport
MAX_REASSESS = 20


def fold(text: str | None) -> str:
    """Chữ thường, bỏ dấu tiếng Việt (để so từ khoá)."""
    t = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return re.sub(r"\s+", " ", "".join(ch for ch in t if unicodedata.category(ch) != "Mn")).strip()


def safe_url(u: str | None) -> str | None:
    """Chỉ nhận http(s) có host; cắt 500 ký tự. Mọi thứ khác (javascript:, file:, intent:…) → None."""
    u = (u or "").strip().rstrip(".,;")
    if not u or len(u) > MAX_URL:
        return None
    p = urlparse(u)
    return u if p.scheme in ("http", "https") and p.hostname else None


def is_form_url(u: str | None) -> bool:
    p = urlparse(u or "")
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (
        host == "forms.gle" or (host == "docs.google.com" and "/forms/" in p.path)
    )


def _iso(s: str | None) -> str | None:
    try:
        d = datetime.fromisoformat(s) if s else None
    except ValueError:
        return None
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=config.TZ)).isoformat()


# ---------------- Chi tiết sự kiện ----------------

_MANDATORY = re.compile(r"bat buoc|diem danh|tinh chuyen can|tinh diem ren luyen|yeu cau .{0,20}co mat")
_NOT_MANDATORY = re.compile(r"khong bat buoc|tu nguyen")
_REG_DEADLINE = re.compile(r"(?:han|han chot|truoc|den het|den)\s*(?:dang ky|dk)|dang ky\s*(?:truoc|den|han)")


def details_rules(msg: Message) -> EventDetails:
    """Luật offline: link trong tin, từ khoá bắt buộc, hạn đăng ký ở câu có chữ 'đăng ký trước/hạn đăng ký'."""
    text = f"{msg.subject}\n{msg.body}"
    urls = [u for u in (safe_url(m) for m in URL_RE.findall(text)) if u]
    register = next((u for u in urls if is_form_url(u)), None)
    event_url = next((u for u in urls if u != register), None)
    folded = fold(text)
    deadline = None
    for line in re.split(r"[\n.;]", text):
        if _REG_DEADLINE.search(fold(line)):
            d = rules.find_date(line, rules._received(msg))
            if d is not None:
                hm = rules.find_time(line)
                deadline = d.replace(hour=hm[0], minute=hm[1]) if hm else d.replace(hour=23, minute=59)
                break
    return EventDetails(
        start_at=None,
        end_at=None,
        location=None,
        event_url=event_url,
        register_url=register,
        register_deadline=deadline.isoformat() if deadline else None,
        organizer=None,
        mandatory=bool(_MANDATORY.search(folded)) and not _NOT_MANDATORY.search(folded),
    )


# ---------------- Cấu trúc Google Form công khai ----------------

# Thứ tự quan trọng: "mã sinh viên" phải khớp trước "tên", "email trường" trước "trường".
ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("student_id", ("mssv", "ma sinh vien", "ma so sinh vien", "ma sv", "msv", "student id", "ma hoc vien")),
    ("email", ("email", "e-mail", "thu dien tu")),
    ("phone", ("dien thoai", "sdt", "phone", "so dt", "zalo")),
    ("name", ("ho va ten", "ho ten", "ten day du", "full name", "your name", "ten cua ban", "ho & ten")),
    ("class_name", ("lop", "class")),
    ("major", ("nganh", "chuyen nganh", "major", "chuong trinh dao tao")),
    ("school", ("truong", "university", "school", "don vi")),
]
_FB_RE = re.compile(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\])\s*;\s*</script>", re.DOTALL)
_FORM_ID_RE = re.compile(r"/forms/d/e/([A-Za-z0-9_-]{20,100})/")


def role_of(title: str) -> str | None:
    t = fold(title)
    for role, kws in ROLE_KEYWORDS:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", t) for k in kws):
            return role
    return None


def parse_form(html: str, final_url: str) -> dict | None:
    """Lấy `{form_id, fields:[{entry, role}]}` từ trang viewform. Chỉ câu trả lời ngắn / đoạn văn (kiểu 0, 1)."""
    fid = _FORM_ID_RE.search(urlparse(final_url).path)
    m = _FB_RE.search(html)
    if not fid or not m:
        return None
    try:
        items = json.loads(m.group(1))[1][1]
    except (ValueError, IndexError, TypeError):
        return None
    fields, seen = [], set()
    for it in items if isinstance(items, list) else []:
        try:
            title, kind, entry = it[1], it[3], it[4][0][0]
        except (IndexError, TypeError):
            continue
        if kind not in (0, 1) or not isinstance(entry, int) or not isinstance(title, str):
            continue
        role = role_of(title)
        if role and role not in seen:
            seen.add(role)
            fields.append({"entry": str(entry), "role": role})
    return {"form_id": fid.group(1), "fields": fields[:10]} if fields else None


def _check_host(host: str) -> None:
    """Chặn SSRF: host phải trong allowlist và phân giải ra IP công khai."""
    if host.lower() not in FORM_HOSTS:
        raise ValueError("host không được phép")
    for info in socket.getaddrinfo(host, 443):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("địa chỉ không công khai")


async def fetch_form_meta(url: str | None) -> dict | None:
    """Đọc cấu trúc form công khai. Form bắt đăng nhập (chuyển hướng sang accounts.google.com) / lỗi bất kỳ → None."""
    if not is_form_url(url):
        return None
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, transport=_transport, headers={"User-Agent": "MStudent/1.0"}
        ) as client:
            for _ in range(4):  # tối đa 3 lần chuyển hướng, mỗi chặng kiểm lại host
                p = urlparse(url)
                if p.scheme != "https":
                    return None
                await anyio.to_thread.run_sync(_check_host, p.hostname or "")
                async with client.stream("GET", url) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, r.headers.get("location", ""))
                        continue
                    if r.status_code != 200:
                        return None
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf += chunk
                        if len(buf) > MAX_FORM_BYTES:
                            return None
                return parse_form(buf.decode("utf-8", "replace"), url)
    except (httpx.HTTPError, ValueError, OSError) as e:
        log.info("Không đọc được form đăng ký: %s", type(e).__name__)
    return None


# ---------------- Phù hợp với ngành ----------------

# lĩnh vực → (từ khoá trong TÊN NGÀNH, từ khoá trong NỘI DUNG SỰ KIỆN); tất cả đã bỏ dấu.
FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "công nghệ thông tin": (
        (
            "cong nghe thong tin",
            "khoa hoc may tinh",
            "phan mem",
            "may tinh",
            "tri tue nhan tao",
            "du lieu",
            "an toan thong tin",
            "he thong thong tin",
            "computer",
            "software",
            "data",
        ),
        (
            "lap trinh",
            "phan mem",
            "hackathon",
            " ai ",
            "tri tue nhan tao",
            "machine learning",
            "du lieu",
            "data",
            "cong nghe thong tin",
            "an ninh mang",
            "cloud",
            "blockchain",
            "coding",
            "developer",
            "web",
            "app",
            "thuat toan",
            "robot",
            "iot",
            "chuyen doi so",
        ),
    ),
    "kinh tế – quản trị": (
        (
            "kinh te",
            "quan tri",
            "kinh doanh",
            "tai chinh",
            "ke toan",
            "marketing",
            "ngan hang",
            "thuong mai",
            "logistics",
            "business",
            "kiem toan",
        ),
        (
            "khoi nghiep",
            "startup",
            "kinh doanh",
            "tai chinh",
            "dau tu",
            "marketing",
            "chung khoan",
            "ngan hang",
            "ke toan",
            "thuong mai",
            "logistics",
            "ban hang",
            "thuong hieu",
            "kinh te",
        ),
    ),
    "kỹ thuật – công nghệ": (
        (
            "ky thuat",
            "co khi",
            "dien",
            "dien tu",
            "tu dong hoa",
            "co dien tu",
            "xay dung",
            "o to",
            "vat lieu",
            "che tao",
            "engineering",
        ),
        (
            "robot",
            "tu dong hoa",
            "co khi",
            "vi mach",
            "ban dan",
            "dien tu",
            "che tao",
            "iot",
            "nhung",
            "xay dung",
            "nang luong",
            "o to",
            "ky thuat",
        ),
    ),
    "ngôn ngữ – văn hoá": (
        (
            "ngon ngu",
            "tieng",
            "nhat ban hoc",
            "han quoc hoc",
            "dong phuong hoc",
            "van hoc",
            "bien dich",
            "phien dich",
            "quoc te hoc",
            "khu vuc hoc",
            "van hoa",
        ),
        (
            "tieng nhat",
            "tieng anh",
            "tieng han",
            "tieng trung",
            "jlpt",
            "ielts",
            "toeic",
            "bien dich",
            "phien dich",
            "giao luu van hoa",
            "van hoa",
            "ngon ngu",
            "hung bien",
            "du hoc",
        ),
    ),
    "y – sinh – nông nghiệp": (
        (
            "y khoa",
            "y hoc",
            "duoc",
            "dieu duong",
            "sinh hoc",
            "cong nghe sinh hoc",
            "nong nghiep",
            "thuc pham",
            "thu y",
            "y te",
        ),
        (
            "y te",
            "suc khoe",
            "benh",
            "duoc",
            "sinh hoc",
            "thuc pham",
            "nong nghiep",
            "dinh duong",
            "hien mau",
        ),
    ),
    "môi trường – phát triển bền vững": (
        ("moi truong", "bien doi khi hau", "phat trien ben vung", "tai nguyen", "nang luong"),
        ("moi truong", "khi hau", "ben vung", "nang luong tai tao", "xanh", "rac thai", "net zero"),
    ),
    "luật – chính sách – xã hội": (
        (
            "luat",
            "chinh sach cong",
            "chinh tri",
            "xa hoi hoc",
            "cong tac xa hoi",
            "tam ly",
            "bao chi",
            "truyen thong",
            "quan he quoc te",
        ),
        ("phap luat", "luat", "chinh sach", "xa hoi", "tam ly", "truyen thong", "bao chi", "ngoai giao"),
    ),
    "giáo dục": (("giao duc", "su pham"), ("giang day", "su pham", "giao duc", "day hoc")),
    "nghệ thuật – thiết kế": (
        ("thiet ke", "my thuat", "kien truc", "am nhac", "nghe thuat", "dien anh"),
        ("thiet ke", "design", "nghe thuat", "am nhac", "trien lam", "kien truc", "nhiep anh", "van nghe"),
    ),
}
GENERAL = ("ky nang mem", "hoc bong", "viec lam", "tuyen dung", "huong nghiep", "thuc tap", "tinh nguyen",
           "cau lac bo", "ngay hoi", "career", "job fair", "cv", "phong van", "trao doi sinh vien")  # fmt: skip
_STOP = {
    "hoc",
    "nganh",
    "khoa",
    "cong",
    "nghe",
    "quan",
    "va",
    "cac",
    "ky",
    "thuat",
    "chuyen",
    "chuong",
    "trinh",
}


def _has(text: str, kw: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(kw.strip())}(?![a-z0-9])", text) is not None


def fit_rules(major_name: str, event_text: str) -> MajorFitOut:
    """Luật offline: so lĩnh vực của ngành với lĩnh vực sự kiện. Lý do luôn nhắc tên ngành (SC-005)."""
    major, text = fold(major_name), fold(event_text)
    name = major_name.strip()[:80]
    mine = {f for f, (mk, _) in FIELDS.items() if any(_has(major, k) for k in mk)}
    theirs = {f for f, (_, ek) in FIELDS.items() if any(_has(text, k) for k in ek)}
    words = [w for w in re.findall(r"[a-z]{4,}", major) if w not in _STOP]
    direct = len(major) >= 6 and major in text
    common = sorted(mine & theirs)
    if direct or common:
        why = (
            f"nhắc trực tiếp tới ngành {name}"
            if direct
            else f"thuộc lĩnh vực {common[0]}, sát với ngành {name}"
        )
        return MajorFitOut(level="high", reason=f"Sự kiện {why}."[:200])
    if any(_has(text, k) for k in GENERAL) or (words and sum(_has(text, w) for w in words) >= 2):
        return MajorFitOut(
            level="medium",
            reason=f"Nội dung chung (kỹ năng, nghề nghiệp, hoạt động sinh viên), có ích cho ngành {name}."[
                :200
            ],
        )
    if theirs:
        return MajorFitOut(
            level="low",
            reason=f"Sự kiện thuộc lĩnh vực {sorted(theirs)[0]}, ít liên quan ngành {name}."[:200],
        )
    return MajorFitOut(
        level="medium", reason=f"Chưa thấy liên hệ rõ với ngành {name}; xem nội dung để quyết định."[:200]
    )


def _event_text(task: Task, msg: Message | None) -> str:
    parts = [task.title, task.course, task.action, task.location, task.note]
    if msg is not None:
        parts += [msg.subject, msg.body]
    return "\n".join(p for p in parts if p)[:4000]


async def assess_fit(user_id: int, task: Task, msg: Message | None = None) -> dict:
    """Trả về các cột fit_* để ghi vào việc. Chưa khai báo ngành → xoá đánh giá (không đoán)."""
    profile = repo.get_profile(user_id)
    if not profile.get("major_name"):
        return {"fit_level": None, "fit_reason": None, "fit_mode": None}
    text = _event_text(task, msg)
    if budget.llm_allowed(user_id):
        from . import llm_agents

        try:
            out = await llm_agents.llm_major_fit(profile, text, user_id)
            reason = llm_agents.clean_text(out.reason)[:200]
            if reason:
                return {"fit_level": out.level, "fit_reason": reason, "fit_mode": "llm"}
        except Exception as e:  # lỗi mạng/credit → luật
            log.warning("MajorFit LLM lỗi, dùng luật: %s", type(e).__name__)
    out = fit_rules(profile["major_name"], text)
    return {"fit_level": out.level, "fit_reason": out.reason, "fit_mode": "offline"}


def event_field(text: str) -> str | None:
    """Lĩnh vực đầu tiên mà nội dung sự kiện thuộc về (bảng FIELDS), để dựng câu mẫu."""
    t = fold(text)
    return next((f for f, (_, ek) in FIELDS.items() if any(_has(t, k) for k in ek)), None)


def fit_template(level: str, major_name: str, event_text: str) -> str:
    """Lý do dạng câu mẫu cho mức vừa / thấp (004 US4) — luôn nhắc tên ngành."""
    name, field_ = major_name.strip()[:80], event_field(event_text)
    if level == "low":
        why = f": sự kiện thuộc lĩnh vực {field_}." if field_ else "."
        return f"Ít liên quan ngành {name}{why}"[:200]
    if level == "medium":
        why = f"sự kiện thuộc lĩnh vực {field_}, " if field_ else ""
        return f"Có ích chung cho ngành {name}: {why}mở rộng kỹ năng và hiểu biết ngoài chuyên môn."[:200]
    why = f": sự kiện thuộc lĩnh vực {field_}." if field_ else "."
    return f"Sát với chuyên môn ngành {name}{why}"[:200]


async def fit_from_score(user_id: int, profile: dict, score_: float, text: str) -> dict:
    """Mức do AI quyết định chấm. Mức cao: GPT viết lý do (giữ nguyên mức); vừa / thấp: câu mẫu, không gọi GPT."""
    from . import decision

    level = decision.fit_level(score_)
    reason = None
    if level == "high" and budget.llm_allowed(user_id):
        from . import llm_agents

        try:
            reason = llm_agents.clean_text((await llm_agents.llm_major_fit(profile, text, user_id)).reason)[
                :200
            ]
        except Exception as e:
            log.warning("MajorFit LLM lỗi, dùng câu mẫu: %s", type(e).__name__)
    return {
        "fit_level": level,
        "fit_reason": reason or fit_template(level, profile["major_name"], text),
        "fit_mode": "llm",
    }


def _stored_message(user_id: int, task: Task) -> Message | None:
    row = repo.get_message(user_id, task.message_id)
    if not row:
        return None
    try:
        return Message(source=task.source, subject=row.get("subject") or "", body=row.get("body") or "")
    except ValueError:
        return None


async def reassess_pending(user_id: int) -> None:
    """Đổi ngành → tính lại mức phù hợp của các lời mời còn chờ (AI quyết định nếu bật, không thì như cũ)."""
    from . import decision

    profile = repo.get_profile(user_id)
    for task in repo.list_events(user_id, "pending")[:MAX_REASSESS]:
        msg = _stored_message(user_id, task)
        fields = None
        if profile.get("major_name") and decision.enabled(user_id):
            text = _event_text(task, msg)
            try:
                s = await decision.decide_fit(Message(source=task.source, body=text[:8000]), user_id, profile)
                fields = await fit_from_score(user_id, profile, s, text)
            except Exception as e:
                log.warning("Tính lại hợp ngành bằng AI quyết định lỗi: %s", type(e).__name__)
        repo.update_task(user_id, task.id, fields or await assess_fit(user_id, task, msg))


# ---------------- Lời mời ----------------


def event_reminders(due_at: str | None) -> list[str]:
    """Nhắc 1 ngày và 2 giờ trước giờ sự kiện (FR-012)."""
    due = datetime.fromisoformat(due_at) if due_at else None
    if due is None:
        return []
    ref = config.now()
    return [(due - o).isoformat() for o in (timedelta(days=1), timedelta(hours=2)) if due - o > ref]


def set_rsvp(user_id: int, task: Task, going: bool) -> Task:
    """Tham gia → vào lịch + nhắc, có hạn đăng ký thì tạo/mở lại việc "Đăng ký …". Không → ẩn, đóng việc đăng ký."""
    reg_id = repo.task_reg_id(user_id, task.id)
    fields: dict = {"rsvp": "going" if going else "declined"}
    if going:
        fields["reminders"] = event_reminders(task.due_at)
        deadline = _iso(task.register_deadline)
        if reg_id:
            repo.set_status(user_id, reg_id, "open")
        elif deadline and datetime.fromisoformat(deadline) > config.now():
            reg = repo.insert_task(
                user_id,
                {
                    "title": f"Đăng ký: {task.title}"[:200],
                    "course": task.course,
                    "category": Category.deadline.value,
                    "due_at": deadline,
                    "location": None,
                    "action": "Mở form và gửi đăng ký",
                    "priority": "high"
                    if datetime.fromisoformat(deadline) - config.now() <= timedelta(hours=48)
                    else "medium",
                    "source": task.source.value,
                    "message_id": task.message_id,
                    "reminders": [
                        (datetime.fromisoformat(deadline) - o).isoformat()
                        for o in (timedelta(days=1), timedelta(hours=2))
                        if datetime.fromisoformat(deadline) - o > config.now()
                    ],
                },
            )
            fields["reg_task_id"] = reg.id
    else:
        fields["reminders"] = []
        if reg_id:
            repo.set_status(user_id, reg_id, "done")
    return repo.update_task(user_id, task.id, fields) or task


async def enrich_event(user_id: int, task: Task, msg: Message, dres=None) -> tuple[Task, str]:
    """Việc `event` vừa tạo → gắn chi tiết, form, mức phù hợp, trạng thái lời mời. Trả về (việc, 'llm'|'rules').

    `dres` (004): kết quả AI quyết định cho tin này — dùng "bắt buộc" khi đủ tin cậy và điểm hợp ngành khi có."""
    from ..agent_config import thresholds

    det, kind = None, "rules"
    if budget.llm_allowed(user_id):
        from . import llm_agents

        try:
            det, kind = await llm_agents.llm_event_details(msg, user_id), "llm"
        except Exception as e:
            log.warning("EventDetails LLM lỗi, dùng luật: %s", type(e).__name__)
    base = details_rules(msg)
    if det is None:
        det = base
    register = safe_url(det.register_url) or base.register_url
    event_url = safe_url(det.event_url) or base.event_url
    if event_url and not register and is_form_url(event_url):
        register, event_url = event_url, None
    mandatory = det.mandatory
    if dres is not None and dres.mandatory is not None and dres.mandatory_conf >= thresholds()["min_conf"]:
        mandatory = dres.mandatory >= 0.5
    fields: dict = {
        "event_end": _iso(det.end_at),
        "event_url": event_url,
        "register_url": register,
        "register_deadline": _iso(det.register_deadline) or base.register_deadline,
        "mandatory": 1 if mandatory else 0,
        "form_meta": await fetch_form_meta(register),
        "rsvp": "pending",
    }
    start = _iso(det.start_at)
    if start and start != task.due_at:
        # Giờ bắt đầu do EventDetails đọc là mốc của sự kiện. Mốc cũ sớm hơn (Extractor lấy nhầm hạn đăng ký) → giữ
        # làm hạn đăng ký nếu chưa có.
        old = _iso(task.due_at)
        if old and old < start and not fields["register_deadline"]:
            fields["register_deadline"] = old
        fields["due_at"] = start
    if det.location and not task.location:
        fields["location"] = det.location.strip()[:200]
    if det.organizer and not task.note:
        fields["note"] = f"Tổ chức: {det.organizer.strip()[:150]}"
    profile = repo.get_profile(user_id)
    if dres is not None and dres.major_fit is not None and profile.get("major_name"):
        fields.update(await fit_from_score(user_id, profile, dres.major_fit, _event_text(task, msg)))
    else:
        fields.update(await assess_fit(user_id, task, msg))
    task = repo.update_task(user_id, task.id, fields) or task
    if mandatory:  # sự kiện bắt buộc tự vào lịch (không hỏi)
        task = set_rsvp(user_id, task, True)
    return task, kind
