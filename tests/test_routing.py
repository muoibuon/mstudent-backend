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
        answers = {k: v for k, v in state["answers"].items() if k in payload["questions"]}
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
    }

    async def fake_run(agent, payload, **kwargs):
        state["calls"].append(agent.name)
        state["payloads"].append(payload if isinstance(payload, str) else "")
        if agent.name == "Triage":
            return _FakeResult(state["triage"])
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
