"""002 US7: đọc tài liệu trong email (PDF/DOCX/XLSX/CSV, link Google) và đưa vào pipeline. Không gọi mạng."""

from __future__ import annotations

import asyncio
import base64
import io
import zipfile

import httpx
import pytest

from app import config, repo, security
from app.connectors import docs

# ---------------- Tệp mẫu tạo trong test ----------------


def make_pdf(lines: list[str]) -> bytes:
    """PDF tối thiểu hợp lệ (font Helvetica, chữ ASCII) — đủ để pypdf rút chữ."""
    content = "BT /F1 12 Tf 50 750 Td 16 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def make_docx(paragraphs: list[str]) -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>{body}</w:body></w:document>',
        )
    return buf.getvalue()


def make_xlsx(rows: list[list[str]]) -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    strings = sorted({c for r in rows for c in r})
    idx = {s: i for i, s in enumerate(strings)}
    sst = "".join(f"<si><t>{s}</t></si>" for s in strings)
    sheet = "".join("<row>" + "".join(f'<c t="s"><v>{idx[c]}</v></c>' for c in r) + "</row>" for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{sst}</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{sheet}</sheetData></worksheet>")
    return buf.getvalue()


PDF_LINES = [
    "Lich thi hoc ky 1",
    "Giai tich 2 - 08:00 16/12/2026 - A2-301",
    "Mang may tinh - 13:30 18/12/2026",
]

# ---------------- T051: rút chữ, giới hạn, thu gọn, link ----------------


def test_extract_pdf_docx_xlsx_csv():
    pdf = docs.extract_text("lich-thi.pdf", "application/pdf", make_pdf(PDF_LINES))
    assert pdf.kind == "pdf" and "Giai tich 2" in pdf.text and "16/12/2026" in pdf.text
    word = docs.extract_text(
        "de-cuong.docx",
        "application/octet-stream",
        make_docx(["Đề cương OOP", "Nộp đồ án trước 23h59 ngày 20/12"]),
    )
    assert word.kind == "docx" and "Nộp đồ án trước 23h59" in word.text
    xlsx = docs.extract_text("ds.xlsx", "", make_xlsx([["Môn", "Hạn"], ["Giải tích", "16/12"]]))
    assert "Giải tích | 16/12" in xlsx.text
    csv_ = docs.extract_text("a.csv", "text/csv", "Môn,Hạn\nOOP,20/12\n".encode())
    assert "OOP | 20/12" in csv_.text


def test_extract_tab_separated_csv_with_cr_only_lines():
    # Một ứng dụng iPhone xuất .csv dạng TSV với CR đơn; vẫn phải đọc được đủ cột.
    data = 'Môn\tNgày\tGhi chú\rOOP\t20/12\t"Nộp bài"\rToán\t21/12\t"Kiểm tra"\r'.encode()
    document = docs.extract_text("lich-tuan.csv", "text/csv", data)
    assert document.kind == "csv"
    assert "OOP | 20/12 | Nộp bài" in document.text
    assert "Toán | 21/12 | Kiểm tra" in document.text


def test_extract_rejects_bad_files():
    with pytest.raises(docs.DocError, match="chưa hỗ trợ"):
        docs.extract_text("anh.png", "image/png", b"x")
    with pytest.raises(docs.DocError, match="quá lớn"):
        docs.extract_text("to.pdf", "application/pdf", b"0" * (docs.MAX_FILE_BYTES + 1))
    with pytest.raises(docs.DocError, match="hỏng"):
        docs.extract_text("hong.pdf", "application/pdf", b"%PDF-1.4 rac")
    with pytest.raises(docs.DocError):
        docs.extract_text("hong.docx", "", b"PK\x03\x04 khong phai zip")

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("mat-khau")
    enc = io.BytesIO()
    w.write(enc)
    with pytest.raises(docs.DocError, match="mật khẩu"):
        docs.extract_text("khoa.pdf", "application/pdf", enc.getvalue())

    blank = PdfWriter()
    blank.add_blank_page(100, 100)
    out = io.BytesIO()
    blank.write(out)
    with pytest.raises(docs.DocError, match="không có chữ"):
        docs.extract_text("scan.pdf", "application/pdf", out.getvalue())


def test_zip_bomb_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * (docs.MAX_UNZIPPED + 10))
    assert len(buf.getvalue()) < 200_000  # nén rất nhỏ nhưng giải nén > 20 MB
    with pytest.raises(docs.DocError, match="nén bất thường"):
        docs.extract_text("bom.docx", "", buf.getvalue())


def test_focus_keeps_head_and_dated_lines():
    filler = "\n".join(f"Dòng giới thiệu số {i} không có gì quan trọng." for i in range(400))
    text = "Đầu tài liệu\n" + filler + "\nNộp báo cáo cuối kỳ trước 23h59 ngày 20/12\n" + filler
    out = docs.focus(text)
    assert len(out) <= docs.FOCUS_CHARS and out.startswith("Đầu tài liệu") and "20/12" in out


def test_find_doc_links():
    body = (
        "Xem lịch: https://docs.google.com/document/d/1AbCdEfGhIjK/edit?usp=sharing và bảng "
        "https://docs.google.com/spreadsheets/d/1ZyXwVuTsRqP/edit#gid=42 , lặp lại "
        "https://docs.google.com/document/d/1AbCdEfGhIjK/view, slide https://docs.google.com/presentation/d/1SlIdEsIdAbC/edit"
        " https://docs.google.com/document/d/1ThirdOneXyZ/edit https://evil.com/document/d/1AbCdEfGhIjK"
    )
    links = docs.find_doc_links(body)
    assert [k for k, _, _ in links] == ["document", "spreadsheets", "presentation"]  # tối đa 3, không trùng
    assert links[0][2].endswith("/document/d/1AbCdEfGhIjK/export?format=txt")
    assert links[1][2].endswith("/spreadsheets/d/1ZyXwVuTsRqP/export?format=csv&gid=42")
    assert links[2][2].endswith("/presentation/d/1SlIdEsIdAbC/export/txt")


# ---------------- T052: luồng Gmail có tệp đính kèm ----------------


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _mail(mid, subject, body, attachments=()):
    parts = [{"mimeType": "text/plain", "body": {"data": _b64(body.encode())}}]
    for i, (name, mime, data) in enumerate(attachments):
        parts.append(
            {
                "mimeType": mime,
                "filename": name,
                "body": {"attachmentId": f"att-{mid}-{i}", "size": len(data)},
            }
        )
    return {
        "id": mid,
        "internalDate": "1794272400000",
        "snippet": body[:20],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Phòng Đào tạo <daotao@vju.ac.vn>"},
                {"name": "Subject", "value": subject},
            ],
            "parts": parts,
        },
    }


@pytest.fixture()
def mailbox(client, user, monkeypatch):
    from app import google_api

    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "web")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shh")
    pdf = make_pdf(PDF_LINES)
    world = {"mails": {}, "list": [], "downloads": 0}

    def handler(req):
        url = str(req.url).split("?")[0]
        if url.startswith(google_api.TOKEN_URL):
            return httpx.Response(200, json={"access_token": "at"})
        if url.endswith("/profile"):
            return httpx.Response(200, json={"historyId": "100"})
        if url.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": i} for i in world["list"]]})
        if "/attachments/" in url:
            world["downloads"] += 1
            return httpx.Response(200, json={"data": _b64(pdf)})
        return httpx.Response(200, json=world["mails"][url.rsplit("/", 1)[1]])

    monkeypatch.setattr(google_api, "_transport", httpx.MockTransport(handler))
    uid = client.get("/api/auth/me", headers=user[0]).json()["id"]
    repo.save_google_account(uid, "sv@gmail.com", security.encrypt("rt"), config.GMAIL_SCOPE)
    conn = repo.create_connection(uid, "gmail", "", "sv@gmail.com")
    return uid, conn["id"], world, pdf


def _run(uid, cid):
    from app.sync import gmail

    res = asyncio.run(gmail.run(repo.get_connection(uid, cid)))
    repo.finish_run(cid, ok=True, next_run_at="2000", cursor=None, state=res.state)
    return res


def _doc_messages(uid):
    import sqlite3

    db = sqlite3.connect(config.DB_PATH)
    return [r[0] for r in db.execute("SELECT id FROM messages WHERE user_id=? AND id LIKE 'doc-%'", (uid,))]


def test_relevant_email_reads_pdf_and_adds_summary(mailbox):
    uid, cid, world, pdf = mailbox
    world["mails"]["m1"] = _mail(
        "m1",
        "[Đào tạo] Lịch thi học kỳ 1",
        "Các em xem lịch thi học kỳ 1 trong file đính kèm, thi từ 16/12.",
        [("lich-thi.pdf", "application/pdf", pdf)],
    )
    world["list"] = ["m1"]
    _run(uid, cid)
    assert world["downloads"] == 1 and len(_doc_messages(uid)) == 1  # PDF đã qua pipeline đúng một lần
    noted = [t for t in repo.list_tasks(uid, None) if t.note and "lich-thi.pdf" in t.note]
    assert noted, "việc tạo/cập nhật từ tài liệu phải có ghi chú tóm tắt"
    assert any(t.due_at and t.due_at.startswith("2026-12-16T08:00") for t in noted)  # giờ thi lấy từ PDF

    # Cùng tệp đến lần hai qua email khác → KHÔNG chạy lại pipeline cho tài liệu (FR-084)
    world["mails"]["m2"] = _mail(
        "m2",
        "Fwd: Lịch thi học kỳ 1",
        "Chuyển tiếp lịch thi học kỳ 1, hạn đăng ký 16/12.",
        [("lich-thi.pdf", "application/pdf", pdf)],
    )
    world["list"] = ["m2"]
    with __import__("app.db", fromlist=["connect"]).connect() as c:
        c.execute("UPDATE sync_connections SET cursor=NULL WHERE id=?", (cid,))  # quét lại theo danh sách
    _run(uid, cid)
    assert world["downloads"] == 2  # email m2 thật sự được xử lý (tệp được tải để so nội dung)
    assert len(_doc_messages(uid)) == 1  # nhưng tài liệu trùng nội dung không chạy lại pipeline


def test_noise_body_does_not_discard_valid_academic_attachment(mailbox):
    uid, cid, world, pdf = mailbox
    world["mails"]["s1"] = _mail(
        "s1", "Flash sale 11.11", "Giảm giá 50%, săn voucher ngay!", [("catalog.pdf", "application/pdf", pdf)]
    )
    world["list"] = ["s1"]
    _run(uid, cid)
    assert world["downloads"] == 1
    assert len(_doc_messages(uid)) == 1
    assert any(t.due_at and t.due_at.startswith("2026-12-16T08:00") for t in repo.list_tasks(uid, None))


def test_noise_body_still_checks_public_document_link(mailbox, monkeypatch):
    from app.sync import sheets

    fetched = []

    async def public(url):
        fetched.append(url)
        return "Nộp báo cáo OOP trước 23h59 ngày 20/12/2026."

    monkeypatch.setattr(sheets, "fetch_google_export", public)
    uid, cid, world, _ = mailbox
    world["mails"]["link"] = _mail(
        "link",
        "Xem thêm",
        "Xin chào. https://docs.google.com/document/d/1AcademicDocAbc/edit",
    )
    world["list"] = ["link"]
    _run(uid, cid)
    assert len(fetched) == 1 and len(_doc_messages(uid)) == 1
    assert any(t.due_at and t.due_at.startswith("2026-12-20T23:59") for t in repo.list_tasks(uid, None))


def test_private_doc_on_noise_body_does_not_crash_or_become_noise_document(mailbox, monkeypatch):
    from app.sync import sheets

    fetched = []

    async def private(url):
        fetched.append(url)
        raise sheets.SheetError(sheets.PRIVATE_MSG)

    monkeypatch.setattr(sheets, "fetch_google_export", private)
    uid, cid, world, _ = mailbox
    world["mails"]["private"] = _mail(
        "private", "Xem thêm", "Xin chào. https://docs.google.com/document/d/1PrivateDocAbc/edit"
    )
    world["list"] = ["private"]
    _run(uid, cid)
    assert len(fetched) == 1 and _doc_messages(uid) == []
    assert repo.list_tasks(uid, None) == []
    document_steps = [
        step for trace in repo.list_traces(uid) for step in trace["steps"] if step["agent"] == "Documents"
    ]
    assert document_steps and any("riêng tư" in error for error in document_steps[0]["output"]["errors"])


def test_private_google_doc_link_is_noted(mailbox, monkeypatch):
    from app.sync import sheets

    async def private(url):
        raise sheets.SheetError(sheets.PRIVATE_MSG)

    monkeypatch.setattr(sheets, "fetch_google_export", private)
    uid, cid, world, _ = mailbox
    world["mails"]["p1"] = _mail(
        "p1",
        "[OOP] Đề bài đồ án",
        "Nộp đồ án OOP trước 23h59 ngày 20/12. Đề bài: https://docs.google.com/document/d/1PrivateDocAbc/edit",
    )
    world["list"] = ["p1"]
    _run(uid, cid)
    notes = [t.note or "" for t in repo.list_tasks(uid, None)]
    assert any("riêng tư" in n for n in notes)
