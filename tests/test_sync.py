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
