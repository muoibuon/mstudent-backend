"""Đọc chữ từ tài liệu trong email (002 US7): PDF, Word (.docx), Excel (.xlsx), CSV/TXT và link Google Docs/Sheets/
Slides chia sẻ công khai.

Tài liệu là DỮ LIỆU KHÔNG TIN CẬY: có giới hạn kích thước, số trang, dung lượng giải nén (chống zip bomb), không chạy
macro, lỗi đọc → bỏ qua tệp đó kèm lý do (không làm hỏng email). Chữ rút ra được thu gọn (`focus`) trước khi tới AI.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_UNZIPPED = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_FILES_PER_EMAIL = 5
MAX_LINKS_PER_EMAIL = 3
FOCUS_CHARS = 6000
HEAD_CHARS = 1500

SUPPORTED = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
    "text/plain": "txt",
}
EXT = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv", ".txt": "txt"}


class DocError(Exception):
    """Không đọc được tài liệu; thông điệp ngắn tiếng Việt để ghi chú lên việc."""


@dataclass
class DocText:
    name: str
    kind: str
    text: str


def kind_of(name: str, mime: str) -> str | None:
    """Loại tài liệu hỗ trợ (theo phần mở rộng, rồi theo MIME) hoặc None."""
    lower = (name or "").lower()
    for ext, k in EXT.items():
        if lower.endswith(ext):
            return k
    return SUPPORTED.get((mime or "").split(";")[0].strip().lower())


def extract_text(name: str, mime: str, data: bytes) -> DocText:
    kind = kind_of(name, mime)
    if not kind:
        raise DocError("Loại tệp chưa hỗ trợ")
    if len(data) > MAX_FILE_BYTES:
        raise DocError("Tệp quá lớn (tối đa 5 MB)")
    try:
        if kind == "pdf":
            text = _pdf(data)
        elif kind == "docx":
            text = _docx(data)
        elif kind == "xlsx":
            text = _xlsx(data)
        else:
            text = _plain(data, csv_mode=kind == "csv")
    except DocError:
        raise
    except Exception as e:  # tệp hỏng / định dạng lạ: không để lộ chi tiết nội bộ
        raise DocError("Tệp hỏng hoặc không đọc được") from e
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        raise DocError("Tệp không có chữ (có thể là ảnh scan)")
    return DocText(name=(name or "tài liệu")[:120], kind=kind, text=text)


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocError("PDF có mật khẩu")
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n".join((p.extract_text() or "") for p in pages)
    except (FileNotDecryptedError, PdfReadError) as e:
        raise DocError("PDF hỏng hoặc có mật khẩu") from e


def _open_zip(data: bytes) -> zipfile.ZipFile:
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise DocError("Tệp nén bất thường (quá lớn khi giải nén)")
    return z


def _read_member(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.file_size > MAX_UNZIPPED:
        raise DocError("Tệp nén bất thường (quá lớn khi giải nén)")
    with z.open(info) as f:
        out = f.read(MAX_UNZIPPED + 1)
    if len(out) > MAX_UNZIPPED:
        raise DocError("Tệp nén bất thường (quá lớn khi giải nén)")
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx(data: bytes) -> str:
    z = _open_zip(data)
    root = ElementTree.fromstring(_read_member(z, "word/document.xml"))
    lines: list[str] = []
    for para in root.iter():
        if _local(para.tag) != "p":
            continue
        line = "".join(t.text or "" for t in para.iter() if _local(t.tag) == "t")
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    z = _open_zip(data)
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ElementTree.fromstring(_read_member(z, "xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))[:3]
    lines: list[str] = []
    for sheet in sheets:
        for row in ElementTree.fromstring(_read_member(z, sheet)).iter():
            if _local(row.tag) != "row":
                continue
            cells = []
            for c in row:
                if _local(c.tag) != "c":
                    continue
                v = next((x.text for x in c.iter() if _local(x.tag) in ("v", "t") and x.text), "") or ""
                if c.get("t") == "s" and v.isdigit() and int(v) < len(shared):
                    v = shared[int(v)]
                cells.append(v.strip())
            if any(cells):
                lines.append(" | ".join(cells))
            if len(lines) >= 2000:
                break
    return "\n".join(lines)


def _plain(data: bytes, csv_mode: bool) -> str:
    text = data.decode("utf-8-sig", "replace")
    if not csv_mode:
        return text
    csv.field_size_limit(MAX_FILE_BYTES)
    rows = list(csv.reader(io.StringIO(text)))[:2000]
    return "\n".join(" | ".join(c.strip() for c in r) for r in rows if any(r))


# ---------------- Thu gọn trước khi gửi AI ----------------

_DATEISH = re.compile(
    r"\d{1,2}[/.\-]\d{1,2}|\d{1,2}\s*(?:h|giờ|:)\s*\d{0,2}|\b(?:thứ|t[2-7]|cn|chủ nhật)\b"
    r"|\b(?:hạn|nộp|thi|kiểm tra|deadline|lịch|due|exam|quiz|đăng ký|phòng)\b",
    re.IGNORECASE,
)


def focus(text: str, limit: int = FOCUS_CHARS) -> str:
    """Giữ phần đầu tài liệu + các dòng có ngày/giờ/từ khoá hạn, nộp, thi…; cắt ≤ `limit` ký tự."""
    if len(text) <= limit:
        return text
    head = text[:HEAD_CHARS]
    picked = [ln.strip() for ln in text[HEAD_CHARS:].splitlines() if ln.strip() and _DATEISH.search(ln)]
    out = head + "\n…\n" + "\n".join(picked)
    return out[:limit]


# ---------------- Link Google Docs / Sheets / Slides ----------------

_LINK = re.compile(
    r"https?://docs\.google\.com/(document|spreadsheets|presentation)/d/([A-Za-z0-9_-]{10,100})[^\s<>\"')]*",
    re.IGNORECASE,
)


def find_doc_links(body: str) -> list[tuple[str, str, str]]:
    """(loại, id, link xuất bản chữ) của tối đa MAX_LINKS_PER_EMAIL tài liệu Google trong thân email, không trùng."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for m in _LINK.finditer(body or ""):
        kind, doc_id = m.group(1).lower(), m.group(2)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        if kind == "document":
            url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        elif kind == "presentation":
            url = f"https://docs.google.com/presentation/d/{doc_id}/export/txt"
        else:
            gid = re.search(r"gid=(\d{1,12})", m.group(0))
            url = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv&gid={gid.group(1) if gid else '0'}"
        out.append((kind, doc_id, url))
        if len(out) >= MAX_LINKS_PER_EMAIL:
            break
    return out
