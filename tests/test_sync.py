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
