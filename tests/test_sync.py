"""002-auto-ingest: gộp nguồn, bộ lập lịch, các runner đồng bộ. Không gọi mạng."""

from __future__ import annotations

from datetime import datetime, timedelta

from app import config, repo
from app.models import Category, TaskOut
from app.pipeline import planner
from tests.conftest import auth, signup

REF = datetime(2026, 11, 10, 8, 0, tzinfo=config.TZ)


def _uid(client, headers) -> int:
    return client.get("/api/auth/me", headers=headers).json()["id"]


def _draft(title, course=None, due="2026-11-20T23:59:00+07:00", cat=Category.deadline):
    return TaskOut(title=title, course=course, category=cat, due_at=due, location=None, action=None)


# ---------------- Gộp việc giữa các nguồn (FR-009, FR-074) ----------------


def test_same_course_code_merges_across_sources(client, user):
    uid = _uid(client, user[0])
    created, _ = planner.plan(
        uid, [_draft("Nộp báo cáo Lab 5", "INT3306")], source="email", message_id="m1", ref=REF
    )
    created2, updated = planner.plan(
        uid, [_draft("Lab 5 - báo cáo", "INT 3306 Mạng máy tính")], source="sheet", message_id="m2", ref=REF
    )
    assert len(created) == 1 and created2 == [] and len(updated) == 1
    assert sorted(updated[0].sources) == ["email", "sheet"]


def test_different_course_never_merges(client, user):
    uid = _uid(client, user[0])
    planner.plan(uid, [_draft("Nộp bài tập tuần 9", "INT3306")], source="email", message_id="m1", ref=REF)
    created, updated = planner.plan(
        uid, [_draft("Nộp bài tập tuần 9", "MAT1101")], source="sheet", message_id="m2", ref=REF
    )
    assert len(created) == 1 and updated == []


def test_course_name_without_code_compares_folded_names(client, user):
    uid = _uid(client, user[0])
    planner.plan(uid, [_draft("Bài tập lớn", "Mạng máy tính")], source="email", message_id="m1", ref=REF)
    _, updated = planner.plan(
        uid, [_draft("Bài tập lớn", "mang may tinh")], source="sheet", message_id="m2", ref=REF
    )
    created, _ = planner.plan(
        uid, [_draft("Bài tập lớn", "Giải tích")], source="sheet", message_id="m3", ref=REF
    )
    assert len(updated) == 1 and len(created) == 1


def test_structured_source_due_wins_over_email(client, user):
    uid = _uid(client, user[0])
    planner.plan(
        uid,
        [_draft("Bài tập tuần 10", "OOP", "2026-11-21T17:00:00+07:00")],
        source="classroom",
        message_id="c1",
        ref=REF,
    )
    _, updated = planner.plan(
        uid,
        [_draft("Bài tập tuần 10", "OOP", "2026-11-21T23:59:00+07:00")],
        source="email",
        message_id="m1",
        ref=REF,
    )
    assert updated[0].due_at.startswith("2026-11-21T17:00")  # Classroom chính xác hơn → giữ
    _, updated = planner.plan(
        uid,
        [_draft("Bài tập tuần 10", "OOP", "2026-11-22T17:00:00+07:00")],
        source="classroom",
        message_id="c2",
        ref=REF,
    )
    assert updated[0].due_at.startswith("2026-11-22T17:00")  # cùng hạng → nguồn mới ghi đè


def test_done_task_is_not_reopened_or_duplicated(client, user):
    h, _ = user
    uid = _uid(client, h)
    created, _ = planner.plan(uid, [_draft("Nộp Lab 5", "INT3306")], source="email", message_id="m1", ref=REF)
    client.post(f"/api/tasks/{created[0].id}/done", headers=h)
    created2, updated = planner.plan(
        uid, [_draft("Nộp Lab 5", "INT3306")], source="sheet", message_id="m2", ref=REF
    )
    assert created2 == [] and updated == []
    assert repo.get_task(uid, created[0].id).status == "done"


# ---------------- Bộ lập lịch: lease, lùi dần, lỗi xác thực (T003) ----------------


def test_claim_is_exclusive(client, user):
    uid = _uid(client, user[0])
    repo.create_connection(uid, "sheet", "a", "A")
    now = config.utcnow()
    first = repo.claim_due_connections(now.isoformat(), (now + timedelta(seconds=90)).isoformat(), 10)
    second = repo.claim_due_connections(now.isoformat(), (now + timedelta(seconds=90)).isoformat(), 10)
    assert len(first) == 1 and second == []


def test_backoff_and_auth_failure(client, user):
    import asyncio

    from app.sync import scheduler

    uid = _uid(client, user[0])
    bad = repo.create_connection(uid, "sheet", "bad", "Lỗi")
    good = repo.create_connection(uid, "sheet", "good", "Tốt")
    calls: list[int] = []

    async def runner(conn):
        calls.append(conn["id"])
        if conn["id"] == bad["id"]:
            raise scheduler.TemporaryError("Mạng lỗi")
        return scheduler.RunResult()

    scheduler.RUNNERS["sheet"] = runner
    try:
        delays = []
        for _ in range(3):
            asyncio.run(scheduler.tick(force=True))
            b = repo.get_connection(uid, bad["id"])
            delays.append(
                round((datetime.fromisoformat(b["next_run_at"]) - config.utcnow()).total_seconds() / 60)
            )
        assert delays == [2, 4, 8]
        assert (
            repo.get_connection(uid, good["id"])["last_error"] is None
        )  # lỗi của nguồn này không chặn nguồn kia
        assert calls.count(good["id"]) >= 1

        async def revoked(conn):
            raise scheduler.AuthError("Cần kết nối lại Google")

        scheduler.RUNNERS["sheet"] = revoked
        repo.run_connection_now(uid, good["id"])
        asyncio.run(scheduler.tick(force=True))
        g = repo.get_connection(uid, good["id"])
        assert g["enabled"] is False and "kết nối lại" in g["last_error"]
    finally:
        scheduler.RUNNERS.pop("sheet", None)
        scheduler.register_default_runners()


def test_backoff_caps_at_one_hour():
    from app.sync import scheduler

    assert scheduler.backoff_minutes(1) == 2 and scheduler.backoff_minutes(3) == 8
    assert scheduler.backoff_minutes(20) == 60


def test_delete_account_removes_sync_data(client):
    h = auth(signup(client, "xoa@x.vn"))
    uid = _uid(client, h)
    conn = repo.create_connection(uid, "sheet", "x", "X")
    repo.upsert_source_item(uid, conn["id"], "k", "h", None)
    repo.upsert_push_token(uid, "ExponentPushToken[abc]", "android", True)
    client.request("DELETE", "/api/auth/me", json={"confirm_email": "xoa@x.vn"}, headers=h)
    import sqlite3

    db = sqlite3.connect(config.DB_PATH)
    for table in ("sync_connections", "source_items", "push_tokens"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


# ---------------- US3: Bảng deadline của lớp (T030, T031) ----------------

import asyncio  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

SHEET_URL = "https://docs.google.com/spreadsheets/d/1AbC-dEf_123/edit#gid=456"


def test_normalize_sheet_url_variants():
    from app.sync import sheets

    assert sheets.normalize_sheet_url(SHEET_URL) == ("1AbC-dEf_123", "456")
    assert sheets.normalize_sheet_url("https://docs.google.com/spreadsheets/d/1AbC/edit?usp=sharing") == (
        "1AbC",
        "0",
    )
    assert sheets.normalize_sheet_url("docs.google.com/spreadsheets/d/1AbC/htmlview?gid=7") == ("1AbC", "7")
    assert (
        sheets.export_url("1AbC", "7")
        == "https://docs.google.com/spreadsheets/d/1AbC/export?format=csv&gid=7"
    )
    for bad in (
        "https://evil.com/spreadsheets/d/1AbC",
        "https://docs.google.com/document/d/1AbC/edit",
        "ftp://x",
    ):
        with pytest.raises(sheets.SheetError):
            sheets.normalize_sheet_url(bad)


def _mock_http(monkeypatch, handler):
    from app.sync import sheets

    monkeypatch.setattr(sheets, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(sheets, "_ensure_public", lambda host: None)


def test_fetch_csv_follows_only_google_redirects(monkeypatch):
    from app.sync import sheets

    def handler(req):
        if req.url.host == "docs.google.com":
            return httpx.Response(307, headers={"location": "https://doc-0s.googleusercontent.com/x"})
        return httpx.Response(
            200, text="Môn,Nội dung,Hạn\nOOP,Lab 1,20/11", headers={"content-type": "text/csv"}
        )

    _mock_http(monkeypatch, handler)
    assert asyncio.run(sheets.fetch_csv("1AbC", "0")).startswith("Môn,")

    _mock_http(
        monkeypatch, lambda req: httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
    )
    with pytest.raises(sheets.SheetError):
        asyncio.run(sheets.fetch_csv("1AbC", "0"))

    login = "<!DOCTYPE html><html><body>Sign in</body></html>"
    _mock_http(
        monkeypatch, lambda req: httpx.Response(200, text=login, headers={"content-type": "text/html"})
    )
    with pytest.raises(sheets.SheetError, match="chia sẻ"):
        asyncio.run(sheets.fetch_csv("1AbC", "0"))

    big = "a,b\n" + "x,y\n" * 400_000
    _mock_http(monkeypatch, lambda req: httpx.Response(200, text=big, headers={"content-type": "text/csv"}))
    with pytest.raises(sheets.SheetError, match="lớn"):
        asyncio.run(sheets.fetch_csv("1AbC", "0"))


def test_parse_due_vietnamese_formats():
    from app.sync import sheets

    ref = REF  # 2026-11-10 08:00 +07:00
    assert sheets.parse_due("20/11", ref) == "2026-11-20T23:59:00+07:00"
    assert sheets.parse_due("20/11/2026 17:00", ref) == "2026-11-20T17:00:00+07:00"
    assert sheets.parse_due("23h59 20/11", ref) == "2026-11-20T23:59:00+07:00"
    assert sheets.parse_due("Thứ 6, 21/11 - 9h30", ref) == "2026-11-21T09:30:00+07:00"
    assert sheets.parse_due("2026-11-25", ref) == "2026-11-25T23:59:00+07:00"
    assert (
        sheets.parse_due("11/25/2026", ref) == "2026-11-25T23:59:00+07:00"
    )  # định dạng Mỹ: tháng > 12 là ngày
    assert sheets.parse_due("05/01", ref) == "2027-01-05T23:59:00+07:00"  # qua năm mới
    assert sheets.parse_due("sắp tới", ref) is None and sheets.parse_due("", ref) is None


def test_rule_mapping_guesses_columns():
    from app.sync import sheets

    m = sheets.rule_mapping(["STT", "Mã HP", "Nội dung bài tập", "Hạn nộp", "Giờ", "Ghi chú"])
    assert m == {"course": 1, "title": 2, "due": 3, "time": 4, "note": 5}
    m = sheets.rule_mapping(["Môn học", "Deadline", "Việc cần làm"])
    assert m["course"] == 0 and m["due"] == 1 and m["title"] == 2


CSV_V1 = "Môn,Nội dung,Hạn nộp\nINT3306,Nộp báo cáo Lab 5,20/11\nOOP,Bài tập lớn,25/11 17:00\nGiải tích,Ôn thi giữa kỳ,01/11\n"


def _sheet_conn(client, user, monkeypatch, csv_text: dict, mapper_calls: list):
    from app.models import ColumnRole, SheetMapping
    from app.pipeline import llm_agents
    from app.sync import sheets

    async def fake_fetch(sheet_id, gid):
        return csv_text["v"]

    async def fake_mapper(header, samples, user_id):
        mapper_calls.append(header)
        roles = {"Môn": "course", "Nội dung": "title", "Hạn nộp": "due"}
        return SheetMapping(
            columns=[ColumnRole(index=i, role=roles.get(h, "ignore")) for i, h in enumerate(header)]
        )

    monkeypatch.setattr(sheets, "fetch_csv", fake_fetch)
    monkeypatch.setattr(llm_agents, "llm_map_sheet", fake_mapper)
    monkeypatch.setattr(sheets.budget, "llm_allowed", lambda user_id=None: True)
    uid = _uid(client, user[0])
    return uid, repo.create_connection(uid, "sheet", "1AbC#0", "K70")


def _run(conn_id, uid):
    from app.sync import sheets

    return asyncio.run(sheets.run(repo.get_connection(uid, conn_id)))


def _tasks(uid):
    return {t.title: t for t in repo.list_tasks(uid, None)}


def test_sheet_runner_tracks_rows(client, user, monkeypatch):
    csv_text, calls = {"v": CSV_V1}, []
    uid, conn = _sheet_conn(client, user, monkeypatch, csv_text, calls)
    res = _run(conn["id"], uid)
    repo.finish_run(conn["id"], ok=True, next_run_at="2000", state=res.state)
    t = _tasks(uid)
    # Dòng quá hạn > 1 ngày ở lượt đầu bị bỏ qua (FR-075)
    assert set(t) == {"Nộp báo cáo Lab 5", "Bài tập lớn"} and len(calls) == 1
    assert t["Bài tập lớn"].due_at == "2026-11-25T17:00:00+07:00" and t["Bài tập lớn"].sources == ["sheet"]

    res = _run(conn["id"], uid)  # không đổi gì → không gọi lại AI, không tạo/cập nhật
    assert res.created == [] and res.updated == [] and len(calls) == 1
    repo.finish_run(conn["id"], ok=True, next_run_at="2000", state=res.state)

    csv_text["v"] = (
        "Môn,Nội dung,Hạn nộp\nINT3306,Nộp báo cáo Lab 5,22/11\nMAT1101,Bài tập chương 3,28/11\n"  # sửa hạn Lab 5, xoá dòng OOP, thêm dòng mới
    )
    res = _run(conn["id"], uid)
    t = _tasks(uid)
    assert t["Nộp báo cáo Lab 5"].due_at.startswith("2026-11-22") and len(res.updated) == 1
    assert "Bài tập chương 3" in t and len(res.created) == 1
    assert "Không còn trong bảng lớp" in (t["Bài tập lớn"].note or "") and t["Bài tập lớn"].status == "open"


def test_sheet_header_change_remaps_and_ai_off_uses_rules(client, user, monkeypatch):
    csv_text, calls = {"v": CSV_V1}, []
    uid, conn = _sheet_conn(client, user, monkeypatch, csv_text, calls)
    from app.sync import sheets

    monkeypatch.setattr(sheets.budget, "llm_allowed", lambda user_id=None: False)
    res = _run(conn["id"], uid)
    assert calls == [] and len(res.created) == 2 and res.mode == "offline"  # luật đoán cột
    repo.finish_run(conn["id"], ok=True, next_run_at="2000", state=res.state)
    monkeypatch.setattr(sheets.budget, "llm_allowed", lambda user_id=None: True)
    csv_text["v"] = CSV_V1.replace("Nội dung", "Nội dung bài")
    _run(conn["id"], uid)
    assert len(calls) == 1  # tiêu đề cột đổi → hỏi lại AI


def test_sheet_private_link_rejected_on_add(client, user, monkeypatch):
    from app.sync import sheets

    async def private(sheet_id, gid):
        raise sheets.SheetError(sheets.PRIVATE_MSG)

    monkeypatch.setattr(sheets, "fetch_csv", private)
    r = client.post("/api/sources", json={"kind": "sheet", "url": SHEET_URL}, headers=user[0])
    assert r.status_code == 400 and "chia sẻ" in r.json()["detail"]
    r = client.post("/api/sources", json={"kind": "sheet", "url": "https://evil.com/x"}, headers=user[0])
    assert r.status_code == 400


# ---------------- US1: Lịch LMS (.ics) tự động (T017) ----------------

ICS_V1 = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ev1@moodle
SUMMARY:Nộp báo cáo Lab 6
CATEGORIES:INT3306
DTSTART:20261120T165900Z
END:VEVENT
BEGIN:VEVENT
UID:ev2@moodle
SUMMARY:Quiz chương 4
CATEGORIES:MAT1101
DTSTART:20261118T020000Z
END:VEVENT
BEGIN:VEVENT
UID:old@moodle
SUMMARY:Bài cũ
DTSTART:20261101T020000Z
END:VEVENT
END:VCALENDAR
"""


def _ics_conn(client, user, monkeypatch, feed: dict):
    from app.sync import ics

    async def fake_fetch(url, etag):
        if etag and etag == feed.get("etag"):
            return 304, "", etag
        return 200, feed["v"], feed.get("etag")

    monkeypatch.setattr(ics, "fetch", fake_fetch)
    uid = _uid(client, user[0])
    return uid, repo.create_connection(uid, "ics", "https://lms.example.edu/export.ics", "Moodle")


def _run_ics(conn_id, uid, save=True):
    from app.sync import ics

    res = asyncio.run(ics.run(repo.get_connection(uid, conn_id)))
    if save:
        repo.finish_run(conn_id, ok=True, next_run_at="2000", cursor=res.cursor, state=res.state)
    return res


def test_ics_runner_structured_no_ai_and_updates(client, user, monkeypatch):
    feed = {"v": ICS_V1, "etag": '"v1"'}
    uid, conn = _ics_conn(client, user, monkeypatch, feed)
    res = _run_ics(conn["id"], uid)
    t = _tasks(uid)
    assert set(t) == {"Nộp báo cáo Lab 6", "Quiz chương 4"}  # sự kiện đã qua > 1 ngày bị bỏ (FR-075)
    assert (
        t["Nộp báo cáo Lab 6"].due_at == "2026-11-20T23:59:00+07:00"
        and t["Nộp báo cáo Lab 6"].course == "INT3306"
    )
    assert t["Quiz chương 4"].category.value == "exam" and t["Nộp báo cáo Lab 6"].sources == ["lms"]
    assert res.mode == "structured"

    res = _run_ics(conn["id"], uid)  # ETag không đổi → 304, không làm gì
    assert res.created == [] and res.updated == []

    feed.update(v=ICS_V1.replace("20261120T165900Z", "20261122T165900Z"), etag='"v2"')
    res = _run_ics(conn["id"], uid)
    t = _tasks(uid)
    assert len(res.updated) == 1 and res.created == []
    assert t["Nộp báo cáo Lab 6"].due_at.startswith("2026-11-22")
    assert len([x for x in repo.list_tasks(uid, None) if x.title == "Nộp báo cáo Lab 6"]) == 1


def test_ics_probe_rejects_bad_links(client, user, monkeypatch):
    from app.sync import ics

    async def not_calendar(url, etag):
        return 200, "<html>login</html>", None

    real_check = ics._ensure_public_url
    monkeypatch.setattr(ics, "fetch", not_calendar)
    monkeypatch.setattr(ics, "_ensure_public_url", lambda url: None)
    r = client.post("/api/sources", json={"kind": "ics", "url": "https://lms.example.edu/x"}, headers=user[0])
    assert r.status_code == 400 and "xuất lịch" in r.json()["detail"].lower()
    monkeypatch.setattr(ics, "_ensure_public_url", real_check)  # kiểm IP thật → chặn địa chỉ nội bộ
    r = client.post(
        "/api/sources", json={"kind": "ics", "url": "http://127.0.0.1:8000/x.ics"}, headers=user[0]
    )
    assert r.status_code == 400


# ---------------- US1: Gmail tự động + webhook báo ngay (T015, T016) ----------------


def _gmail_mail(mid, subject, body):
    import base64 as b64

    data = b64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "id": mid,
        "internalDate": "1794272400000",
        "snippet": body[:20],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Thầy A <a@vju.ac.vn>"},
                {"name": "Subject", "value": subject},
            ],
            "body": {"data": data},
        },
    }


@pytest.fixture()
def gmail_world(client, user, monkeypatch):
    """Hộp thư giả + đếm số thư đi qua pipeline. Trả (uid, conn_id, world)."""
    from app import google_api, security
    from app.pipeline import orchestrator

    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "web")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shh")
    world = {
        "list": ["m1"],
        "history": {"historyId": "105", "history": []},
        "token_error": None,
        "ingested": [],
    }
    mails = {
        "m1": _gmail_mail("m1", "[INT3306] Lab 5", "Nộp báo cáo Lab 5 trước 23h59 ngày 20/11."),
        "m4": _gmail_mail("m4", "[MAT1101] Bài tập", "Nộp bài tập chương 3 trước 17h ngày 21/11."),
    }

    def handler(req):
        url = str(req.url).split("?")[0]
        if url.startswith(google_api.TOKEN_URL):
            if world["token_error"]:
                return httpx.Response(400, json={"error": world["token_error"]})
            return httpx.Response(200, json={"access_token": "at"})
        if url.endswith("/profile"):
            return httpx.Response(200, json={"historyId": "100"})
        if url.endswith("/history"):
            h = world["history"]
            return httpx.Response(404, json={}) if h == 404 else httpx.Response(200, json=h)
        if url.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": i} for i in world["list"]]})
        return httpx.Response(200, json=mails[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(google_api, "_transport", httpx.MockTransport(handler))
    real_ingest = orchestrator.ingest

    async def counting_ingest(uid_, msg):
        world["ingested"].append((uid_, msg.id))
        return await real_ingest(uid_, msg)

    monkeypatch.setattr(orchestrator, "ingest", counting_ingest)
    uid = _uid(client, user[0])
    repo.save_google_account(uid, "sv@gmail.com", security.encrypt("rt"), config.GMAIL_SCOPE)
    conn = repo.create_connection(uid, "gmail", "", "sv@gmail.com")
    return uid, conn["id"], world


def _run_gmail(uid, conn_id):
    from app.sync import gmail

    res = asyncio.run(gmail.run(repo.get_connection(uid, conn_id)))
    repo.finish_run(conn_id, ok=True, next_run_at="2000", cursor=res.cursor, state=res.state)
    return res


def test_gmail_runner_incremental(gmail_world):
    uid, cid, world = gmail_world
    res = _run_gmail(uid, cid)  # lần đầu: liệt kê 7 ngày, lưu historyId
    assert world["ingested"] == [(uid, "gmail-m1")] and res.cursor == "100" and len(res.created) == 1

    res = _run_gmail(uid, cid)  # không có thư mới → 0 thư qua pipeline (0 lượt AI)
    assert len(world["ingested"]) == 1 and res.cursor == "105" and res.created == []

    world["history"] = {
        "historyId": "110",
        "history": [
            {"messagesAdded": [{"message": {"id": "m3", "labelIds": ["INBOX", "CATEGORY_PROMOTIONS"]}}]},
            {"messagesAdded": [{"message": {"id": "m4", "labelIds": ["INBOX", "UNREAD"]}}]},
            {"messagesAdded": [{"message": {"id": "m1", "labelIds": ["INBOX"]}}]},  # đã xử lý → bỏ
        ],
    }
    res = _run_gmail(uid, cid)
    assert world["ingested"][1:] == [(uid, "gmail-m4")] and res.cursor == "110" and res.skipped == 1

    world["history"], world["list"] = 404, ["m4"]  # historyId quá cũ → quét lại 1 ngày
    res = _run_gmail(uid, cid)
    assert len(world["ingested"]) == 2 and res.cursor == "100"


def test_gmail_runner_revoked_token_disables(gmail_world):
    from app.sync import gmail, scheduler

    uid, cid, world = gmail_world
    world["token_error"] = "invalid_grant"
    with pytest.raises(scheduler.AuthError, match="kết nối lại Gmail"):
        asyncio.run(gmail.run(repo.get_connection(uid, cid)))
    gmail.register()
    asyncio.run(scheduler.tick(force=True))
    c = repo.get_connection(uid, cid)
    assert c["enabled"] is False and "kết nối lại Gmail" in c["last_error"]


def _signed(claims: dict, key):
    import jwt

    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture()
def push_keys(monkeypatch):
    from types import SimpleNamespace

    from cryptography.hazmat.primitives.asymmetric import rsa

    from app import google_api

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("MSTUDENT_PUBLIC_URL", "https://mst.example.ts.net")
    monkeypatch.setenv("MSTUDENT_PUBSUB_PUSH_SA", "push@proj.iam.gserviceaccount.com")
    monkeypatch.setattr(
        google_api._jwks, "get_signing_key_from_jwt", lambda tok: SimpleNamespace(key=priv.public_key())
    )
    return priv


def _push(client, token, email="sv@gmail.com", raw=None):
    import base64 as b64
    import json

    data = b64.b64encode(json.dumps({"emailAddress": email, "historyId": "999"}).encode()).decode()
    body = raw if raw is not None else json.dumps({"message": {"data": data}, "subscription": "s"})
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/hooks/gmail", content=body, headers={**headers, "content-type": "application/json"}
    )


def test_gmail_webhook_requires_google_signature(client, user, push_keys):
    import time

    uid = _uid(client, user[0])
    from app import security

    repo.save_google_account(uid, "sv@gmail.com", security.encrypt("rt"), config.GMAIL_SCOPE)
    conn = repo.create_connection(uid, "gmail", "", "sv@gmail.com", next_run_at="2999-01-01T00:00:00+00:00")
    now = int(time.time())
    good = {
        "iss": "https://accounts.google.com", "aud": "https://mst.example.ts.net/api/hooks/gmail",
        "email": "push@proj.iam.gserviceaccount.com", "email_verified": True, "iat": now, "exp": now + 300,
    }  # fmt: skip

    assert _push(client, None).status_code == 403
    assert _push(client, "not-a-jwt").status_code == 403
    assert (
        _push(client, _signed({**good, "aud": "https://evil/api/hooks/gmail"}, push_keys)).status_code == 403
    )
    assert (
        _push(client, _signed({**good, "email": "attacker@x.iam.gserviceaccount.com"}, push_keys)).status_code
        == 403
    )
    assert repo.get_connection(uid, conn["id"])["next_run_at"].startswith("2999")

    assert _push(client, _signed(good, push_keys)).status_code == 204
    assert not repo.get_connection(uid, conn["id"])["next_run_at"].startswith("2999")  # chạy ngay
    assert (
        _push(client, _signed(good, push_keys), email="la@gmail.com").status_code == 204
    )  # email lạ: vẫn 204
    assert _push(client, _signed(good, push_keys), raw="x" * 9000).status_code == 413


# ---------------- US2: Google Classroom (T025) ----------------


def _cw(cid, title, due=None, time=None, updated="2026-11-09T01:00:00Z"):
    w = {"id": cid, "title": title, "updateTime": updated, "alternateLink": "https://classroom.google.com/x"}
    if due:
        w["dueDate"] = dict(zip(("year", "month", "day"), due, strict=True))
    if time:
        w["dueTime"] = dict(zip(("hours", "minutes"), time, strict=True))
    return w


@pytest.fixture()
def classroom_world(client, user, monkeypatch):
    from app import google_api, security
    from app.pipeline import orchestrator

    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "web")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shh")
    world = {
        "snapshot": [
            {  # lớp mới tạo → theo dõi
                "course": {
                    "id": "c1",
                    "name": "INT3306 Mạng máy tính",
                    "creationTime": "2026-10-20T00:00:00Z",
                },
                "coursework": [
                    _cw("w1", "Bài tập tuần 10", (2026, 11, 21), (10, 0)),  # 17:00 giờ VN
                    _cw("w2", "Quiz chương 4", (2026, 11, 19)),  # thiếu giờ → 23:59 VN
                    _cw("w3", "Bài đã quá hạn lâu", (2026, 11, 1), (10, 0)),
                    _cw("w4", "Đọc tài liệu"),  # không có hạn
                ],
                "submissions": [],
                "announcements": [
                    {
                        "id": "a1",
                        "text": "Thứ 6 tuần này nghỉ học, học bù thứ 7 tại P.301.",
                        "creationTime": "2026-11-09T02:00:00Z",
                        "updateTime": "2026-11-09T02:00:00Z",
                    },
                ],
            },
            {  # lớp cũ, không hoạt động → bỏ qua
                "course": {"id": "c2", "name": "Lớp năm ngoái", "creationTime": "2025-09-01T00:00:00Z"},
                "coursework": [_cw("w9", "Bài cũ", (2026, 11, 25), updated="2025-12-01T00:00:00Z")],
                "submissions": [],
                "announcements": [],
            },
        ],
        "error": None,
        "ingested": [],
    }

    async def fake_token(refresh):
        return "at"

    async def fake_snapshot(token):
        if world["error"]:
            raise world["error"]
        return world["snapshot"]

    monkeypatch.setattr(google_api, "access_token", fake_token)
    monkeypatch.setattr(google_api, "classroom_snapshot", fake_snapshot)
    real_ingest = orchestrator.ingest

    async def counting(uid_, msg):
        world["ingested"].append(msg.id)
        return await real_ingest(uid_, msg)

    monkeypatch.setattr(orchestrator, "ingest", counting)
    # "Bây giờ" của dữ liệu thử nghiệm: 10/11/2026 (conftest đặt MSTUDENT_NOW); datetime.now dùng cho lọc lớp.
    from app.sync import classroom

    monkeypatch.setattr(classroom, "datetime", _FrozenDatetime)
    uid = _uid(client, user[0])
    repo.save_google_account(uid, "sv@gmail.com", security.encrypt("rt"), " ".join(config.CLASSROOM_SCOPES))
    return uid, repo.create_connection(uid, "classroom", "", "sv@gmail.com")["id"], world


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 10, 1, 0, tzinfo=tz)


def _run_classroom(uid, cid):
    from app.sync import classroom

    res = asyncio.run(classroom.run(repo.get_connection(uid, cid)))
    repo.finish_run(cid, ok=True, next_run_at="2000", state=res.state)
    return res


def test_classroom_structured_tasks_without_ai(classroom_world):
    uid, cid, world = classroom_world
    res = _run_classroom(uid, cid)
    t = _tasks(uid)
    assert t["Bài tập tuần 10"].due_at == "2026-11-21T17:00:00+07:00"
    assert (
        t["Quiz chương 4"].due_at == "2026-11-19T23:59:00+07:00"
        and t["Quiz chương 4"].category.value == "exam"
    )
    assert t["Đọc tài liệu"].due_at is None
    assert "Bài đã quá hạn lâu" not in t and "Bài cũ" not in t  # FR-075, FR-024
    assert t["Bài tập tuần 10"].source.value == "classroom" and "INT3306" in t["Bài tập tuần 10"].course
    assert world["ingested"] == ["classroom-ann-a1"]  # chỉ thông báo lớp qua pipeline; bài tập không qua AI
    assert res.state["tracked_courses"] == 1

    world["snapshot"][0]["coursework"][0]["dueTime"] = {"hours": 13}  # dời sang 20:00 VN
    world["snapshot"][0]["submissions"] = [{"courseWorkId": "w2", "state": "TURNED_IN"}]
    res = _run_classroom(uid, cid)
    t = _tasks(uid)
    assert t["Bài tập tuần 10"].due_at == "2026-11-21T20:00:00+07:00"
    assert t["Quiz chương 4"].status == "done"  # đã nộp → xong (FR-021)
    assert len([x for x in repo.list_tasks(uid, None) if x.title == "Bài tập tuần 10"]) == 1
    assert world["ingested"] == ["classroom-ann-a1"]  # thông báo cũ không chạy lại


def test_classroom_blocked_by_school_disables_only_classroom(classroom_world):
    from app import google_api
    from app.sync import classroom, scheduler

    uid, cid, world = classroom_world
    gmail_conn = repo.create_connection(
        uid, "gmail", "", "sv@gmail.com", next_run_at="2999-01-01T00:00:00+00:00"
    )
    world["error"] = google_api.ClassroomBlocked(
        "Không đọc được Google Classroom: trường của bạn có thể chặn …"
    )
    classroom.register()
    asyncio.run(scheduler.tick(force=False))
    c = repo.get_connection(uid, cid)
    assert c["enabled"] is False and "trường" in c["last_error"]
    assert repo.get_connection(uid, gmail_conn["id"])["enabled"] is True
