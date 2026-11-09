import os

import pytest

os.environ["MSTUDENT_OFFLINE"] = "1"
os.environ["MSTUDENT_NOW"] = "2026-11-10T08:00:00+07:00"

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.connectors import lms_ics, zalo  # noqa: E402
from app.models import Category, Message, Source  # noqa: E402
from app.pipeline import rules  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    from app.main import app

    return TestClient(app)


def msg(body, subject="", received="2026-11-10T08:00:00+07:00", source=Source.zalo):
    return Message(source=source, subject=subject, body=body, received_at=received)


def test_deadline_with_time():
    m = msg("Các em nộp báo cáo Lab 3 trước 23h59 ngày 13/11.", "[CSE3032] Lab 3")
    t = rules.extract(m).tasks[0]
    assert t.category == Category.deadline
    assert t.course == "CSE3032"
    assert t.due_at.startswith("2026-11-13T23:59")


def test_exam_location():
    m = msg("Thi cuối kỳ MAT1042 vào 8h00 ngày 28/11/2026 tại phòng 301.")
    t = rules.extract(m).tasks[0]
    assert t.category == Category.exam
    assert t.due_at.startswith("2026-11-28T08:00")
    assert t.location.lower() == "phòng 301"


def test_relative_weekday_next_week():
    # 10/11/2026 là thứ 3 → "thứ 7 tuần sau" = 21/11
    m = msg("Nghỉ học thứ 5 tuần này, học bù 13h30 thứ 7 tuần sau phòng 205.")
    t = rules.extract(m).tasks[0]
    assert t.category == Category.class_change
    assert t.due_at.startswith("2026-11-21T13:30")


def test_this_week_deadline_defaults_to_2359():
    t = rules.extract(msg("Bài tập tuần 9 nộp trước thứ 6 tuần này nhé")).tasks[0]
    assert t.due_at.startswith("2026-11-13T23:59")


def test_spam_and_chitchat_are_ignored():
    assert not rules.triage(msg("Flash sale giảm giá 50%, săn voucher ngay")).relevant
    assert not rules.triage(msg("Có ai đi ăn trưa không")).relevant


def test_year_rollover():
    m = msg("Hạn nộp đồ án 10/01", received="2026-12-20T08:00:00+07:00")
    assert rules.extract(m).tasks[0].due_at.startswith("2027-01-10")


def test_zalo_split():
    msgs = zalo.split_chat(
        "Lớp trưởng: Mai nghỉ học nha\nNam: ok\n[09:15] Cô Lan: Nộp bài trước 20/11\ncả lớp nhé"
    )
    assert [m.sender.split(" (")[0] for m in msgs] == ["Lớp trưởng", "Nam", "Cô Lan"]
    assert msgs[2].body.endswith("cả lớp nhé")


def test_ics_parse():
    ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:42\nSUMMARY:Quiz 2 is due\nDTSTART:20261118T165900Z\nEND:VEVENT\nEND:VCALENDAR"
    m = lms_ics.parse_ics(ics)[0]
    assert m.source == Source.lms and "23:59 ngày 18/11/2026" in m.body


def test_seed_dedupes_extension(client):
    results = client.post("/api/demo/seed").json()
    assert sum(r["relevant"] for r in results) == 7
    tasks = client.get("/api/tasks").json()
    lab = [t for t in tasks if "Lab 3" in t["title"]]
    assert len(lab) == 1, "tin gia hạn phải cập nhật task cũ, không tạo task mới"
    assert lab[0]["due_at"].startswith("2026-11-15T23:59")
    assert lab[0]["updated_from"] == ["demo-08"]


def test_digest_and_done(client):
    client.post("/api/demo/seed")
    d = client.get("/api/digest").json()
    assert d["mode"] == "offline" and "việc trong 7 ngày tới" in d["text"]
    tid = client.get("/api/tasks").json()[0]["id"]
    assert client.post(f"/api/tasks/{tid}/done").json()["status"] == "done"
    assert all(t["id"] != tid for t in client.get("/api/tasks").json())


def test_trace_recorded(client):
    r = client.post(
        "/api/ingest", json={"source": "zalo", "body": "Nộp bài tập trước 23h59 ngày 20/11"}
    ).json()
    assert [s["agent"] for s in r["trace"]] == ["Triage", "Extractor", "Planner"]
    traces = client.get("/api/traces").json()
    assert traces[0]["message_id"] == r["message_id"] and traces[0]["mode"] == "offline"


def test_chat_offline_tools(client):
    client.post("/api/demo/seed")
    r = client.post("/api/chat", json={"message": "Tuần này có gì?"}).json()
    assert r["tool_calls"][0]["tool"] == "list_tasks" and "#" in r["reply"]
    r = client.post("/api/chat", json={"message": "thêm: thứ 6 tuần sau nộp đồ án OOP"}).json()
    assert r["tool_calls"][0]["tool"] == "add_notice" and "Đã tạo" in r["reply"]
    tid = client.get("/api/tasks").json()[0]["id"]
    r = client.post("/api/chat", json={"message": f"xong {tid}"}).json()
    assert r["tool_calls"][0]["tool"] == "complete_task"
    assert all(t["id"] != tid for t in client.get("/api/tasks").json())
    assert (
        client.post("/api/chat", json={"message": "bản tin"}).json()["tool_calls"][0]["tool"] == "get_digest"
    )
    assert "Mình có thể" in client.post("/api/chat", json={"message": "chào"}).json()["reply"]


def test_patch_task_moves_due(client):
    client.post("/api/demo/seed")
    t = client.get("/api/tasks").json()[0]
    new = "2026-11-25" + t["due_at"][10:]
    assert client.patch(f"/api/tasks/{t['id']}", json={"due_at": new}).json()["due_at"] == new
    assert client.patch("/api/tasks/9999", json={"status": "done"}).status_code == 404


def test_agent_config_and_eval(client, monkeypatch):
    cfg = client.get("/api/agents/config").json()
    assert cfg["llm"] is False and "triage_prompt" in cfg["config"]
    saved = client.put("/api/agents/config", json={"model": "gpt-test", "unknown": "x"}).json()["config"]
    assert saved["model"] == "gpt-test" and "unknown" not in saved
    assert client.post("/api/agents/config/reset").json()["config"]["model"] == cfg["defaults"]["model"]
    monkeypatch.setenv("MSTUDENT_ADMIN_TOKEN", "s3cret")
    assert client.put("/api/agents/config", json={"model": "x"}).status_code == 403
    ok = client.put("/api/agents/config", json={"model": "x"}, headers={"X-Admin-Token": "s3cret"})
    assert ok.status_code == 200
    ev = client.post("/api/eval").json()
    assert ev["mode"] == "offline" and ev["scores"]["relevant"]["pct"] == 100
