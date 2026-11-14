"""004-decision-routing: AI quyết định điều phối luồng. Decisions API giả (MockTransport), GPT giả (Runner) — không mạng."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import agent_config, config
from app.models import Category, ExtractionOut, Message, TaskOut, TriageOut
from app.pipeline import decision

KEY = "AIza-test-not-real"


def _noul(p, conf=None):
    return {"type": "noul", "noul": p, "confidence": max(p, 1 - p) if conf is None else conf}


def _choice(c, conf=0.9):
    return {"type": "choice", "choice": c, "probabilities": {c: conf}, "confidence": conf}


def _score(s):
    return {"type": "score", "score": s, "confidence": 0.8}


class _FakeResult:
    def __init__(self, output):
        self.final_output = output
        self.new_items = []
        self.context_wrapper = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=20))


@pytest.fixture()
def decisions(monkeypatch):
    """Decisions API giả. `answers` = câu trả lời theo khoá câu hỏi (câu không có trong dict → không trả lời);
    `status`/`body` để giả lỗi; `requests` ghi lại payload đã gửi."""
    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    state = {
        "answers": {
            "relevant": _noul(0.97),
            "category": _choice("deadline"),
            "has_date": _noul(0.95),
            "multi_task": _noul(0.05),
            "is_update": _noul(0.1),
            "urgency": _score(1.0),
        },
        "status": 200,
        "body": None,
        "requests": [],
        "headers": [],
    }

    def handler(req: httpx.Request):
        payload = json.loads(req.content)
        state["requests"].append(payload)
        state["headers"].append(dict(req.headers))
        if state["body"] is not None or state["status"] != 200:
            return httpx.Response(state["status"], json=state["body"] or {})
        merged = {**state["answers"], **(state["fn"](payload) if state.get("fn") else {})}
        answers = {k: v for k, v in merged.items() if k in payload["questions"]}
        return httpx.Response(200, json={"answers": answers, "usage": {"total_input_tokens": 400}})

    monkeypatch.setattr(decision, "_transport", httpx.MockTransport(handler))
    return state


@pytest.fixture()
def gpt(monkeypatch):
    """GPT giả: đếm lượt theo agent; trả lời mặc định hợp lý cho Triage/Extractor."""
    from app.pipeline import llm_agents

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    state = {
        "calls": [],
        "payloads": [],
        "triage": TriageOut(relevant=True, category=Category.exam, reason="GPT lọc"),
        "tasks": None,  # danh sách TaskOut thay cho mặc định của Extractor
    }

    async def fake_run(agent, payload, **kwargs):
        state["calls"].append(agent.name)
        state["payloads"].append(payload if isinstance(payload, str) else "")
        if agent.name == "Triage":
            return _FakeResult(state["triage"])
        if agent.name == "EventDetails":
            from app.models import EventDetails

            return _FakeResult(EventDetails(start_at=None, end_at=None, location=None, event_url=None,
                                            register_url=None, register_deadline=None, organizer=None,
                                            mandatory=False))  # fmt: skip
        if agent.name == "MajorFit":
            from app.models import MajorFitOut

            return _FakeResult(
                MajorFitOut(level="low", reason="GPT: rất hữu ích cho ngành Khoa học máy tính.")
            )
        if agent.name == "Extractor" and state["tasks"] is not None:
            return _FakeResult(ExtractionOut(tasks=state["tasks"]))
        if agent.name == "Extractor":
            return _FakeResult(
                ExtractionOut(
                    tasks=[
                        TaskOut(
                            title="Nộp báo cáo Lab 5",
                            course="INT3306",
                            category=Category.deadline,
                            due_at="2026-11-13T23:59:00+07:00",
                            location=None,
                            action="Nộp",
                        )  # fmt: skip
                    ]
                )
            )
        return _FakeResult("xong")

    monkeypatch.setattr(llm_agents.Runner, "run", fake_run)
    return state


MSG = Message(
    sender="Thầy Nam <nam.thay@vju.ac.vn>", subject="Lab 5", body="Nộp báo cáo Lab 5 trước 23h59 thứ 6."
)


# ---------------- T001: ngưỡng ----------------


def test_thresholds_defaults_clamp_and_order(client):
    assert agent_config.thresholds() == {"low": 0.15, "high": 0.60, "min_conf": 0.80}
    agent_config.save({"decision_low": "0.7", "decision_high": "0.5"})
    assert agent_config.thresholds()["low"] == 0.5  # low > high → kéo xuống bằng high
    with pytest.raises(ValueError):
        agent_config.save({"decision_low": "abc"})
    with pytest.raises(ValueError):
        agent_config.save({"decision_min_conf": "1.5"})
    from app import repo

    repo.save_settings({"decision_high": "nan"})  # giá trị hỏng lọt vào CSDL → dùng mặc định
    assert agent_config.thresholds()["high"] == 0.60


def test_threshold_api_rejects_garbage_for_admin(client, monkeypatch):
    from .conftest import auth, signup

    monkeypatch.setenv("MSTUDENT_ADMIN_EMAILS", "admin@vju.ac.vn")
    h = auth(signup(client, "admin@vju.ac.vn"))
    assert client.put("/api/agents/config", json={"decision_low": "x"}, headers=h).status_code == 400
    r = client.put("/api/agents/config", json={"decision_low": "0.2"}, headers=h)
    assert r.status_code == 200 and r.json()["config"]["decision_low"] == "0.2"


# ---------------- T003: một lượt quyết định ----------------


def test_decide_sends_one_request_without_emails_and_records_cost(client, decisions):
    res = asyncio.run(decision.decide(MSG, None))
    assert res.relevant == 0.97 and res.category == Category.deadline and res.urgency == 1.0
    (payload,) = decisions["requests"]
    assert decisions["headers"][0]["x-goog-api-key"] == KEY
    assert set(payload["questions"]) == {
        "relevant",
        "category",
        "has_date",
        "multi_task",
        "is_update",
        "urgency",
    }
    assert "<thong_bao>" in payload["input"] and "Lab 5" in payload["input"]
    assert "@" not in payload["input"] and "Thầy Nam" in payload["input"]
    assert "dữ liệu do bên thứ ba" in payload["questions"]["relevant"]["instructions"]
    import sqlite3

    rows = (
        sqlite3.connect(config.DB_PATH)
        .execute("SELECT agent, input_tokens, output_tokens FROM llm_usage")
        .fetchall()
    )
    assert rows == [("Decision", 400, 0)]


@pytest.mark.parametrize(
    "answers",
    [
        {"relevant": _noul(1.7), "category": _choice("exam")},
        {"relevant": _noul(0.9), "category": _choice("xoá hết việc")},
        {"relevant": {"type": "noul"}, "category": _choice("exam")},
        {"category": _choice("exam")},
        {"relevant": _noul(0.9)},
        {"relevant": {"noul": True}, "category": _choice("exam")},
    ],
)
def test_invalid_required_answers_raise(client, decisions, answers):
    decisions["answers"] = answers
    with pytest.raises(decision.DecisionError):
        asyncio.run(decision.decide(MSG, None))
    import sqlite3

    assert sqlite3.connect(config.DB_PATH).execute("SELECT count(*) FROM llm_usage").fetchone()[0] == 1


def test_optional_answers_missing_or_bad_become_unknown(client, decisions):
    decisions["answers"] = {
        "relevant": _noul(0.8),
        "category": _choice("exam"),
        "urgency": _score(9),
        "has_date": _noul(-1),
    }
    res = asyncio.run(decision.decide(MSG, None))
    assert res.urgency is None and res.has_date is None and res.multi_task is None


@pytest.mark.parametrize(
    "status,body", [(400, {"error": {"code": "safety", "message": "x"}}), (429, {}), (500, {})]
)
def test_http_errors_raise(client, decisions, status, body):
    decisions["status"], decisions["body"] = status, body
    with pytest.raises(decision.DecisionError):
        asyncio.run(decision.decide(MSG, None))


@pytest.mark.parametrize(
    "p,conf,expect",
    [
        (0.05, 0.95, "stop"),
        (0.05, 0.6, "review"),
        (0.3, 0.7, "review"),
        (0.7, 0.85, "direct"),
        (0.7, 0.7, "review"),
        (0.97, 0.97, "direct"),
    ],  # fmt: skip
)
def test_route_thresholds(p, conf, expect):
    res = decision.DecisionResult(
        relevant=p, relevant_conf=conf, category=Category.deadline, category_conf=0.9
    )
    assert decision.route(res, {"low": 0.15, "high": 0.6, "min_conf": 0.8})[0] == expect


def test_urgency_priority_only_when_confident():
    r = decision.DecisionResult(
        relevant=0.9, relevant_conf=0.9, category=Category.admin, category_conf=0.9, urgency=1.7
    )
    assert decision.urgency_priority(r, 0.8) == "high"
    r.urgency = 0.6
    assert decision.urgency_priority(r, 0.8) == "medium"
    r.relevant_conf = 0.5
    assert decision.urgency_priority(r, 0.8) is None
    assert decision.urgency_priority(None, 0.8) is None


def test_strip_emails():
    assert decision.strip_emails("Thầy Nam <nam@vju.ac.vn>") == "Thầy Nam"
    assert decision.strip_emails("liên hệ a.b+c@gmail.com nhé") == "liên hệ  nhé"


# ---------------- Phase 2: 4 tuyến qua /api/ingest (T004, T005) ----------------

NOTICE = {
    "sender": "Thầy Nam <nam.thay@vju.ac.vn>",
    "subject": "Lab 5",
    "body": "Nộp báo cáo Lab 5 trước 23h59 thứ 6.",
}


def _ingest(client, h, body=NOTICE):
    r = client.post("/api/ingest", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _step(out, agent):
    return next(s for s in out["trace"] if s["agent"] == agent)


def test_noise_stops_without_any_gpt_call(client, user, decisions, gpt):
    decisions["answers"].update(relevant=_noul(0.04, 0.96), category=_choice("other"))
    out = _ingest(client, user[0], {"body": "Sale 50% trà sữa hôm nay cả nhà ơi"})
    assert out["relevant"] is False and out["created"] == [] and out["mode"] == "llm"
    assert gpt["calls"] == [] and len(decisions["requests"]) == 1
    step = _step(out, "Decision")
    assert (
        step["kind"] == "gemini" and step["output"]["route"] == "stop" and step["output"]["relevant"] == 0.04
    )
    assert [s["agent"] for s in out["trace"]] == ["Decision"]


def test_clear_notice_goes_direct_to_extractor_with_system_hint(client, user, decisions, gpt):
    out = _ingest(client, user[0])
    assert out["relevant"] and out["category"] == "deadline" and out["mode"] == "llm"
    assert gpt["calls"] == ["Extractor"]  # không gọi GPT Triage
    assert _step(out, "Decision")["output"]["route"] == "direct"
    payload = gpt["payloads"][0]
    hint_at = payload.index("Ngữ cảnh do hệ thống xác định")
    assert hint_at > payload.index("</thong_bao>")  # ngữ cảnh nằm ngoài dữ liệu không tin cậy
    assert "loại = hạn nộp" in payload and "có nhiều việc riêng: không" in payload
    assert [t["title"] for t in out["created"]] == ["Nộp báo cáo Lab 5"]
    sent = json.dumps(decisions["requests"][0], ensure_ascii=False)
    assert "nam.thay@vju.ac.vn" not in sent


def test_task_without_due_takes_priority_from_urgency(client, user, decisions, gpt, monkeypatch):
    from app.pipeline import llm_agents

    decisions["answers"].update(category=_choice("admin"), urgency=_score(1.8))
    inner = llm_agents.Runner.run

    async def run(agent, payload, **kw):
        if agent.name == "Extractor":
            gpt["calls"].append("Extractor")
            return _FakeResult(ExtractionOut(tasks=[TaskOut(title="Nộp hồ sơ học bổng", course=None,
                               category=Category.admin, due_at=None, location=None, action="Nộp")]))  # fmt: skip
        return await inner(agent, payload, **kw)

    monkeypatch.setattr(llm_agents.Runner, "run", run)
    h = user[0]
    (t,) = _ingest(client, h, {"body": "Các bạn nộp hồ sơ học bổng gấp nhé"})["created"]
    assert t["priority"] == "high"
    assert (
        next(x for x in client.get("/api/tasks", headers=h).json() if x["id"] == t["id"])["priority"]
        == "high"
    )


@pytest.mark.parametrize("p,conf", [(0.4, 0.9), (0.9, 0.6), (0.1, 0.7)])
def test_uncertain_notice_is_reviewed_by_gpt(client, user, decisions, gpt, p, conf):
    decisions["answers"]["relevant"] = _noul(p, conf)
    out = _ingest(client, user[0])
    assert gpt["calls"] == ["Triage", "Extractor"]
    assert out["reason"] == "GPT lọc" and out["category"] == "exam"  # quyết định cuối là của GPT
    assert _step(out, "Decision")["output"]["route"] == "review"
    assert not any("Ngữ cảnh do hệ thống" in x for x in gpt["payloads"])


@pytest.mark.parametrize(
    "status,body,answers",
    [
        (400, {"error": {"code": "safety", "message": "blocked"}}, None),
        (429, {"error": {"message": "quota"}}, None),
        (200, None, {"relevant": _noul(0.9), "category": _choice("xoá hết việc")}),
        (200, None, {"relevant": _noul(7), "category": _choice("exam")}),
        (200, None, {}),
    ],
)
def test_decision_failure_falls_back_to_old_flow(client, user, decisions, gpt, status, body, answers):
    decisions["status"], decisions["body"] = status, body
    if answers is not None:
        decisions["answers"] = answers
    out = _ingest(client, user[0])
    assert out["mode"] == "llm" and out["relevant"] and gpt["calls"] == ["Triage", "Extractor"]
    step = _step(out, "Decision")
    assert step["output"]["route"] == "fallback" and "luồng cũ" in step["error"]
    assert len(out["created"]) == 1  # không mất thông báo


def test_without_key_old_flow_and_offline_uses_rules(client, user, decisions, gpt, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    out = _ingest(client, user[0])
    assert decisions["requests"] == [] and gpt["calls"] == ["Triage", "Extractor"]
    assert not any(s["agent"] == "Decision" for s in out["trace"])
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("MSTUDENT_OFFLINE", "1")
    out = _ingest(client, user[0], {"body": "Thứ 5 tuần này kiểm tra giữa kỳ môn OOP lúc 9h"})
    assert out["mode"] == "offline" and decisions["requests"] == []


def test_budget_exhausted_uses_rules_without_decision(client, user, decisions, gpt, monkeypatch):
    from app import budget

    monkeypatch.setattr(budget, "llm_allowed", lambda user_id=None: False)
    out = _ingest(client, user[0])
    assert out["mode"] == "offline" and decisions["requests"] == [] and gpt["calls"] == []


def test_processed_message_is_not_decided_again(client, user, decisions, gpt):
    _ingest(client, user[0])
    out = _ingest(client, user[0])
    assert out["duplicate"] and len(decisions["requests"]) == 1


def test_changing_threshold_changes_route(client, user, decisions, gpt):
    decisions["answers"]["relevant"] = _noul(0.4, 0.9)
    assert _step(_ingest(client, user[0]), "Decision")["output"]["route"] == "review"
    agent_config.save({"decision_low": "0.5"})
    out = _ingest(client, user[0], {"body": "Tin thứ hai khác nội dung để không trùng"})
    assert _step(out, "Decision")["output"]["route"] == "stop" and out["relevant"] is False


def test_selfcheck_reports_decision_route(client, user, decisions, gpt):
    r = client.post("/api/ai/check", headers=user[0]).json()
    assert r["decision"]["route"] == "direct" and r["decision"]["ok"] is True
    decisions["status"], decisions["body"] = 500, {}
    r = client.post("/api/ai/check", headers=user[0]).json()
    assert r["decision"]["route"] == "fallback" and r["decision"]["ok"] is False


# ---------------- Phase 3: cập nhật đúng việc cũ (T009) ----------------

from app import repo  # noqa: E402

LAB5 = {"title": "Nộp báo cáo Lab 5", "course": "INT3306", "category": "deadline",
        "due_at": "2026-11-13T23:59:00+07:00", "priority": "high", "source": "email", "message_id": "m-lab5"}  # fmt: skip
DELAY = {"body": "Thầy cho lùi deadline bài thực hành số 5 sang thứ 2 tuần sau nhé"}


def _uid(client, h):
    return client.get("/api/auth/me", headers=h).json()["id"]


def _draft(title, course, due):
    return TaskOut(
        title=title, course=course, category=Category.deadline, due_at=due, location=None, action=None
    )


def test_decision_points_at_old_task_and_it_is_updated(client, user, decisions, gpt):
    h = user[0]
    old = repo.insert_task(_uid(client, h), LAB5)
    gpt["tasks"] = [_draft("Nộp bài thực hành 5", None, "2026-11-16T23:59:00+07:00")]
    decisions["answers"]["match_task"] = _choice(f"t{old.id}", 0.92)
    out = _ingest(client, h, DELAY)
    assert out["created"] == [] and [t["id"] for t in out["updated"]] == [old.id]
    assert (
        out["updated"][0]["due_at"] == "2026-11-16T23:59:00+07:00"
        and out["updated"][0]["course"] == "INT3306"
    )
    crit = decisions["requests"][0]["questions"]["match_task"]["criteria"]
    assert crit[f"t{old.id}"] == "Nộp báo cáo Lab 5 · INT3306 · 13/11 23:59" and "none" in crit
    assert _step(out, "Decision")["output"]["match_task"] == f"t{old.id}"


def test_without_hint_the_same_notice_creates_a_new_task(client, user, decisions, gpt):
    h = user[0]
    repo.insert_task(_uid(client, h), LAB5)
    gpt["tasks"] = [_draft("Nộp bài thực hành 5", None, "2026-11-16T23:59:00+07:00")]
    decisions["answers"]["match_task"] = _choice("none", 0.9)
    out = _ingest(client, h, DELAY)
    assert len(out["created"]) == 1 and out["updated"] == []  # so khớp chuỗi một mình không nhận ra


def test_low_confidence_hint_is_ignored(client, user, decisions, gpt):
    h = user[0]
    old = repo.insert_task(_uid(client, h), LAB5)
    gpt["tasks"] = [_draft("Nộp bài thực hành 5", None, "2026-11-16T23:59:00+07:00")]
    decisions["answers"]["match_task"] = _choice(f"t{old.id}", 0.5)
    assert len(_ingest(client, h, DELAY)["created"]) == 1


def test_other_users_task_id_is_never_used(client, user, decisions, gpt):
    from .conftest import auth, signup

    other = auth(signup(client, "b@vju.ac.vn"))
    theirs = repo.insert_task(_uid(client, other), LAB5)
    h = user[0]
    mine = repo.insert_task(_uid(client, h), {**LAB5, "title": "Đọc chương 3", "course": "MAT1093"})
    gpt["tasks"] = [_draft("Nộp bài thực hành 5", None, "2026-11-16T23:59:00+07:00")]
    decisions["answers"]["match_task"] = _choice(f"t{theirs.id}", 0.99)
    out = _ingest(client, h, DELAY)
    assert len(out["created"]) == 1 and out["updated"] == []
    crit = decisions["requests"][0]["questions"]["match_task"]["criteria"]
    assert set(crit) == {f"t{mine.id}", "none"}  # chỉ việc của chính người dùng được gửi đi
    assert repo.get_task(_uid(client, other), theirs.id).due_at == LAB5["due_at"]


def test_hint_never_merges_different_courses(client, user, decisions, gpt):
    h = user[0]
    old = repo.insert_task(_uid(client, h), LAB5)
    gpt["tasks"] = [_draft("Nộp bài tập 5", "MAT1093", "2026-11-16T23:59:00+07:00")]
    decisions["answers"]["match_task"] = _choice(f"t{old.id}", 0.95)
    out = _ingest(client, h, {"body": "MAT1093: nộp bài tập 5 trước thứ 2"})
    assert len(out["created"]) == 1 and repo.get_task(_uid(client, h), old.id).due_at == LAB5["due_at"]


def test_hint_ignored_when_notice_has_several_tasks(client, user, decisions, gpt):
    h = user[0]
    old = repo.insert_task(_uid(client, h), LAB5)
    gpt["tasks"] = [_draft("Nộp bài thực hành 5", None, "2026-11-16T23:59:00+07:00"),
                    _draft("Ôn tập giữa kỳ", None, "2026-11-20T09:00:00+07:00")]  # fmt: skip
    decisions["answers"]["match_task"] = _choice(f"t{old.id}", 0.95)
    out = _ingest(client, h, {"body": "Lùi bài thực hành 5 sang thứ 2; thứ 6 tuần sau kiểm tra giữa kỳ"})
    assert repo.get_task(_uid(client, h), old.id).due_at == LAB5["due_at"] and len(out["created"]) == 2


def test_candidates_capped_same_course_first_no_declined(client, user):
    from app.pipeline import decision as d

    h = user[0]
    uid = _uid(client, h)
    for i in range(35):
        repo.insert_task(
            uid,
            {
                **LAB5,
                "title": f"Việc {i}",
                "course": "MAT1093",
                "due_at": f"2026-12-{i % 28 + 1:02d}T09:00:00+07:00",
            },
        )
    same = repo.insert_task(uid, {**LAB5, "due_at": "2027-06-01T09:00:00+07:00"})
    declined = repo.insert_task(uid, {**LAB5, "title": "Seminar"})
    repo.update_task(uid, declined.id, {"rsvp": "declined"})
    done = repo.insert_task(uid, {**LAB5, "title": "Đã xong"})
    repo.set_status(uid, done.id, "done")
    cands = d.candidates(uid, Message(body="INT3306: lùi hạn Lab 5"))
    ids = [t.id for t in cands]
    assert len(cands) == d.MAX_CANDIDATES and ids[0] == same.id  # cùng môn lên đầu dù hạn xa
    assert declined.id not in ids and done.id not in ids
    assert len(d.match_question(cands)["match_task"]["criteria"]) == d.MAX_CANDIDATES + 1
    assert d.match_question([]) == {}


# ---------------- Phase 4: sự kiện trong cùng lượt (T011) ----------------

IT = {"school_name": "Trường ĐH Việt Nhật", "school_abbr": "VNU-VJU", "degree_level": "dai_hoc",
      "major_code": "7480101", "major_name": "Khoa học máy tính", "student_id": "21020001", "phone": "0912345678"}  # fmt: skip
JP = {**IT, "major_code": "7310613", "major_name": "Nhật Bản học"}
SEMINAR = {"body": "Seminar về AI và lập trình lúc 14h00 ngày 20/11/2026 tại phòng 501, mời các bạn tham dự."}


def _event_setup(decisions, gpt, fit=1.8, mandatory=0.05):
    decisions["answers"].update(category=_choice("event"), major_fit=_score(fit), mandatory=_noul(mandatory))
    gpt["tasks"] = [TaskOut(title="Seminar AI và lập trình", course=None, category=Category.event,
                            due_at="2026-11-20T14:00:00+07:00", location="Phòng 501", action="Tham dự")]  # fmt: skip


def test_event_questions_only_sent_after_major_declared(client, user, decisions, gpt):
    h = user[0]
    _event_setup(decisions, gpt)
    _ingest(client, h, SEMINAR)
    assert not {"mandatory", "major_fit"} & set(decisions["requests"][0]["questions"])
    client.put("/api/profile", json=IT, headers=h)
    _ingest(client, h, {"body": "Workshop kỹ năng viết CV ngày 25/11/2026 lúc 15h00."})
    q = decisions["requests"][-1]["questions"]
    assert (
        "Khoa học máy tính" in q["major_fit"]["instructions"]
        and "Việt Nhật" in q["major_fit"]["instructions"]
    )
    sent = json.dumps(decisions["requests"][-1], ensure_ascii=False)
    assert "21020001" not in sent and "0912345678" not in sent


def test_high_fit_reason_written_by_gpt_level_from_decision(client, user, decisions, gpt):
    h = user[0]
    client.put("/api/profile", json=IT, headers=h)
    _event_setup(decisions, gpt, fit=1.8)
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert (
        t["rsvp"] == "pending" and t["fit_level"] == "high" and t["fit_mode"] == "llm"
    )  # mức của AI quyết định
    assert t["fit_reason"] == "GPT: rất hữu ích cho ngành Khoa học máy tính."
    assert gpt["calls"] == ["Extractor", "EventDetails", "MajorFit"]


@pytest.mark.parametrize(
    "fit,level,start", [(0.2, "low", "Ít liên quan ngành"), (1.0, "medium", "Có ích chung cho ngành")]
)
def test_medium_low_fit_use_template_without_gpt(client, user, decisions, gpt, fit, level, start):
    h = user[0]
    client.put("/api/profile", json=JP, headers=h)
    _event_setup(decisions, gpt, fit=fit)
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["fit_level"] == level and t["fit_mode"] == "llm"
    assert t["fit_reason"].startswith(start) and "Nhật Bản học" in t["fit_reason"]
    assert "MajorFit" not in gpt["calls"]


def test_mandatory_from_decision_goes_to_calendar(client, user, decisions, gpt):
    h = user[0]
    client.put("/api/profile", json=IT, headers=h)
    _event_setup(decisions, gpt, mandatory=0.96)
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["mandatory"] is True and t["rsvp"] == "going"


def test_unsure_mandatory_falls_back_to_event_details(client, user, decisions, gpt):
    h = user[0]
    client.put("/api/profile", json=IT, headers=h)
    _event_setup(decisions, gpt)
    decisions["answers"]["mandatory"] = _noul(0.6, 0.6)
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["mandatory"] is False and t["rsvp"] == "pending"  # EventDetails giả nói không bắt buộc


def test_same_event_different_majors_and_reassess_on_major_change(client, user, decisions, gpt):
    def by_major(payload):
        q = payload["questions"].get("major_fit")
        return {"major_fit": _score(0.2 if q and "Nhật Bản học" in q["instructions"] else 1.8)} if q else {}

    decisions["fn"] = by_major
    h = user[0]
    client.put("/api/profile", json=IT, headers=h)
    _event_setup(decisions, gpt)
    decisions["answers"].pop("major_fit")
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["fit_level"] == "high"
    n = len(decisions["requests"])
    client.put("/api/profile", json=JP, headers=h)  # đổi ngành → tính lại nền
    assert set(decisions["requests"][n]["questions"]) == {"major_fit"}  # lượt chỉ có câu hợp ngành
    (e,) = client.get("/api/events?state=pending", headers=h).json()
    assert e["fit_level"] == "low" and "Nhật Bản học" in e["fit_reason"] and e["fit_mode"] == "llm"


def test_decision_off_events_work_as_before(client, user, decisions, gpt, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    h = user[0]
    client.put("/api/profile", json=IT, headers=h)
    _event_setup(decisions, gpt)
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["rsvp"] == "pending" and t["fit_mode"] == "llm" and "MajorFit" in gpt["calls"]
    assert decisions["requests"] == []


# ---------------- Phase 6: eval qua hàm điều phối (T015) ----------------


def test_eval_reports_routes_calls_and_cleans_temp_users(client, decisions, gpt):
    import sqlite3

    from app import evaluation

    r = asyncio.run(evaluation.evaluate(use_llm=True))
    assert r["decision"] is True and r["routes"].get("direct", 0) >= 1
    assert r["decision_calls"] == len(r["cases"]) and r["gpt_calls"] >= 1 and r["p50_ms"] is not None
    assert r["gpt_per_noise"] is not None and r["gpt_per_msg_mix30"] is not None
    assert all("route" in c for c in r["cases"])
    db = sqlite3.connect(config.DB_PATH)
    assert db.execute("SELECT count(*) FROM users WHERE email LIKE 'eval-%'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0  # tài khoản tạm xoá kèm việc
