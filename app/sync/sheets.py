"""Bảng deadline của lớp (Google Sheets chia sẻ công khai theo link) — US3 của 002-auto-ingest.

- Tải bảng dạng CSV qua link export; chỉ theo chuyển hướng tới docs.google.com / *.googleusercontent.com, kiểm IP
  công khai (chống SSRF), tối đa 1 MB / 2 000 dòng.
- Hiểu cột: AI (SheetMapper) một lần, lưu theo hash dòng tiêu đề; AI tắt/hết hạn mức → đoán bằng từ khoá.
- Mỗi dòng có khoá = hash(môn + nội dung) và hash nội dung: dòng không đổi → bỏ qua (0 lượt AI); dòng mới → tạo việc;
  dòng đổi → cập nhật việc; dòng biến mất → ghi chú lên việc, không xoá (FR-032).
"""

from __future__ import annotations

import csv
import io
import ipaddress
import re
import socket
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlparse

import anyio
import httpx
from fastapi import HTTPException

from .. import budget, config, repo
from ..models import Message, SheetMapping, Source, TaskOut
from ..pipeline import llm_agents, orchestrator, planner
from . import scheduler
from .common import guess_category, short_hash
from .scheduler import RunResult

MAX_BYTES = 1_000_000
MAX_ROWS = 2000
PRIVATE_MSG = (
    "Bảng chưa chia sẻ công khai — mở Google Sheets → Chia sẻ → 'Bất kỳ ai có đường liên kết' → Người xem"
)
_ID_RE = re.compile(r"^/spreadsheets/d/([A-Za-z0-9_-]{1,100})(?:/|$)")


class SheetError(scheduler.TemporaryError):
    """Lỗi hiển thị được cho người dùng (tiếng Việt)."""


# ---------------- Link & tải về ----------------


def normalize_sheet_url(url: str) -> tuple[str, str]:
    """Trả (sheet_id, gid). Chỉ nhận link docs.google.com/spreadsheets/d/<id>."""
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    u = urlparse(raw)
    m = _ID_RE.match(u.path or "")
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() != "docs.google.com" or not m:
        raise SheetError("Đây không phải link Google Sheets (docs.google.com/spreadsheets/d/…)")
    gid = parse_qs(u.query).get("gid", [None])[0] or parse_qs(u.fragment).get("gid", ["0"])[0]
    if not re.fullmatch(r"\d{1,12}", gid or ""):
        gid = "0"
    return m.group(1), gid


def export_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def _host_ok(host: str) -> bool:
    host = host.lower()
    return host == "docs.google.com" or host.endswith(".googleusercontent.com")


def _ensure_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443)
    except socket.gaierror as e:
        raise SheetError("Không kết nối được Google Sheets, sẽ thử lại") from e
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise SheetError("Link trỏ tới địa chỉ không được phép")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "MStudent/1.0"})


async def fetch_csv(sheet_id: str, gid: str) -> str:
    url = export_url(sheet_id, gid)
    async with _client() as client:
        for _ in range(4):  # tối đa 3 lần chuyển hướng
            host = urlparse(url).hostname or ""
            if urlparse(url).scheme != "https" or not _host_ok(host):
                raise SheetError("Link chuyển hướng tới địa chỉ không được phép")
            await anyio.to_thread.run_sync(_ensure_public, host)
            async with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                if r.status_code in (401, 403):
                    raise SheetError(PRIVATE_MSG)
                if r.status_code == 404:
                    raise SheetError("Không tìm thấy bảng — kiểm tra lại link")
                if r.status_code >= 400:
                    raise SheetError(f"Google Sheets trả lỗi {r.status_code}, sẽ thử lại")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        raise SheetError("Bảng quá lớn (tối đa 1 MB)")
                text = buf.decode("utf-8-sig", "replace")
                head = text.lstrip()[:20].lower()
                if "html" in r.headers.get("content-type", "") or head.startswith(("<!doctype", "<html")):
                    raise SheetError(PRIVATE_MSG)  # bảng riêng tư → Google trả trang đăng nhập
                return text
    raise SheetError("Quá nhiều lần chuyển hướng")


def parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any(r)]
    if len(rows) > MAX_ROWS + 1:
        raise SheetError(f"Bảng có quá nhiều dòng (tối đa {MAX_ROWS})")
    if not rows:
        return [], []
    return rows[0], rows[1:]


async def probe(url: str) -> tuple[str, str]:
    """Kiểm tra link khi người dùng thêm: trả (target, nhãn) hoặc 400 với thông điệp tiếng Việt."""
    try:
        sheet_id, gid = normalize_sheet_url(url)
        header, _ = parse_csv(await fetch_csv(sheet_id, gid))
    except SheetError as e:
        raise HTTPException(400, str(e)) from e
    if not header:
        raise HTTPException(400, "Bảng đang trống — thêm dòng tiêu đề (Môn, Nội dung, Hạn…) rồi thử lại")
    return f"{sheet_id}#{gid}", "Bảng lớp"


# ---------------- Hiểu cột ----------------

ROLES = ("course", "title", "due", "time", "note")
# Thứ tự quan trọng: "Hạn nộp" là due chứ không phải title; "Ghi chú" trước mọi thứ.
_KEYWORDS: list[tuple[str, list[str]]] = [
    ("note", ["ghi chu", "note", "luu y", "link"]),
    ("time", ["gio", "time"]),
    ("due", ["han", "han nop", "deadline", "ngay", "due", "date", "thoi han"]),
    ("course", ["ma hp", "ma mon", "hoc phan", "mon", "course", "subject"]),
    (
        "title",
        ["noi dung", "bai", "bai tap", "cong viec", "viec", "nhiem vu", "task", "ten", "tieu de", "yeu cau"],
    ),
]


def rule_mapping(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, h in enumerate(header):
        words = planner.fold(h)
        for role, kws in _KEYWORDS:
            if role not in mapping and any(re.search(rf"\b{kw}\b", words) for kw in kws):
                mapping[role] = i
                break
    if "title" not in mapping:  # cột chữ đầu tiên chưa dùng, bỏ STT
        used = set(mapping.values())
        for i, h in enumerate(header):
            if i not in used and planner.fold(h) not in ("stt", "#", "tt", "so thu tu"):
                mapping["title"] = i
                break
    return mapping


def _from_model(m: SheetMapping, ncols: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in m.columns:
        if c.role in ROLES and c.role not in out and 0 <= c.index < ncols:
            out[c.role] = c.index
    return out


async def map_columns(
    header: list[str], samples: list[list[str]], user_id: int
) -> tuple[dict[str, int], str]:
    if budget.llm_allowed(user_id):
        try:
            m = _from_model(await llm_agents.llm_map_sheet(header, samples, user_id), len(header))
            if "title" in m:
                return m, "llm"
        except Exception:
            pass  # AI lỗi/quá hạn → luật
    return rule_mapping(header), "offline"


# ---------------- Ngày giờ kiểu Việt Nam ----------------

_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DMY = re.compile(r"(?<![\d:])(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?(?![\d:])")
_TIME = re.compile(r"(?<!\d)(\d{1,2})\s*(?:h|:|giờ)\s*(\d{2})?(?!\d)", re.IGNORECASE)


def parse_due(text: str, ref: datetime) -> str | None:
    """'20/11', '20/11/2026 17:00', '23h59 20/11', 'Thứ 6, 21/11 - 9h30', '2026-11-25', '11/25/2026' → ISO +07:00.

    Thiếu giờ → 23:59. Thiếu năm → năm gần nhất không cũ hơn 30 ngày so với hôm nay."""
    text = (text or "").strip()
    if not text:
        return None
    hour, minute = 23, 59
    rest = text
    if m := _ISO.search(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rest = text.replace(m.group(0), " ")
    elif m := _DMY.search(text):
        a, b = int(m.group(1)), int(m.group(2))
        d, mo = (b, a) if b > 12 >= a else (a, b)  # định dạng Mỹ (11/25) → đảo
        y = int(m.group(3)) if m.group(3) else None
        if y is not None and y < 100:
            y += 2000
        rest = text.replace(m.group(0), " ")
    else:
        return None
    if t := _TIME.search(rest):
        hour, minute = int(t.group(1)), int(t.group(2) or 0)
        if hour > 23 or minute > 59:
            hour, minute = 23, 59
    try:
        if y is None:
            y = ref.year
            if datetime(y, mo, d, tzinfo=config.TZ) < ref - timedelta(days=30):
                y += 1
        return datetime(y, mo, d, hour, minute, tzinfo=config.TZ).isoformat()
    except ValueError:
        return None


# ---------------- Đồng bộ ----------------


def _cell(row: list[str], mapping: dict[str, int], role: str) -> str:
    i = mapping.get(role)
    return row[i].strip() if i is not None and i < len(row) else ""


async def run(conn: dict) -> RunResult:
    uid = conn["user_id"]
    state = dict(conn.get("state") or {})
    first = conn.get("last_ok_at") is None
    sheet_id, gid = (conn["target"].split("#", 1) + ["0"])[:2]
    header, rows = parse_csv(await fetch_csv(sheet_id, gid))
    res = RunResult(state=state, mode="structured")
    if not header:
        return res
    header_hash = short_hash(*header)
    if state.get("header_hash") != header_hash or not state.get("mapping"):
        mapping, used = await map_columns(header, rows[:3], uid)
        state.update(header_hash=header_hash, mapping=mapping)
        res.mode = used
    mapping = {k: int(v) for k, v in state["mapping"].items()}
    ref = config.now()
    seen: set[str] = set()

    for row in rows:
        title, course = _cell(row, mapping, "title"), _cell(row, mapping, "course")
        if not title:
            continue
        key = short_hash(planner.fold(course), planner.fold(title))
        chash = short_hash(*row)
        seen.add(key)
        prev = repo.get_source_item(conn["id"], key)
        if prev and prev["content_hash"] == chash:
            res.skipped += 1
            continue
        if prev and prev["task_id"]:
            task = repo.get_task(uid, prev["task_id"])
            if (
                task is None or task.status == "done"
            ):  # người dùng đã xoá / đã xong → không tạo lại, không mở lại
                repo.upsert_source_item(uid, conn["id"], key, chash, None)
                res.skipped += 1
                continue
        due_text = " ".join(x for x in (_cell(row, mapping, "due"), _cell(row, mapping, "time")) if x)
        due = parse_due(due_text, ref)
        if first and due and datetime.fromisoformat(due) < ref - timedelta(days=1):
            repo.upsert_source_item(uid, conn["id"], key, chash, None)  # bài cũ ở lượt đầu: bỏ qua (FR-075)
            res.skipped += 1
            continue
        note = _cell(row, mapping, "note")
        if due_text and not due:
            # Không đọc được ngày bằng luật → đưa cả dòng qua pipeline AI như một thông báo.
            msg = Message(
                id=f"sheet-{conn['id']}-{chash}",
                source=Source.sheet,
                subject=f"Bảng lớp: {conn['label']}"[:500],
                body=f"{course} — {title} — Hạn: {due_text}" + (f" — {note}" if note else ""),
                received_at=ref.isoformat(),
            )
            out = await orchestrator.ingest(uid, msg)
            created, updated = out.created, out.updated
            if out.mode in ("llm", "offline"):
                res.mode = out.mode if res.mode == "structured" else res.mode
        else:
            draft = TaskOut(
                title=title[:80],
                course=course[:60] or None,
                category=guess_category(title),
                due_at=due,
                location=None,
                action=note[:200] or None,
            )
            created, updated = planner.plan(
                uid, [draft], source="sheet", message_id=f"sheet-{conn['id']}-{key}", ref=ref
            )
        res.created += created
        res.updated += updated
        touched = (created + updated)[:1]
        repo.upsert_source_item(uid, conn["id"], key, chash, touched[0].id if touched else None)

    stamp = ref.strftime("%d/%m")
    for g in repo.mark_items_gone(conn["id"], seen):
        task = repo.get_task(uid, g["task_id"]) if g["task_id"] else None
        if task and task.status == "open":
            repo.update_task(uid, task.id, {"note": f"Không còn trong bảng lớp ({stamp})"})
    return res


def register() -> None:
    scheduler.RUNNERS["sheet"] = run
