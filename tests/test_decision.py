"""Hai model: Gemini Decision lọc thông báo (Triage), model trả lời (OpenAI) làm phần còn lại. Không gọi mạng."""

import json
import logging
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from app import config
from app.models import Category, ExtractionOut, TaskOut, TriageOut
from app.pipeline import decision

NOTICE = {
    "sender": "Thầy Nam",
    "subject": "Lab 5",
    "body": "Các em nộp báo cáo Lab 5 trước 23h59 thứ 6 tuần này nhé.",
}
KEY = "AIza-test-not-real"


class _FakeResult:
    def __init__(self, output):
        self.final_output = output
        self.new_items = []
        self.context_wrapper = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=20))


@pytest.fixture()
def two_models(monkeypatch):
    """Bật cả hai model với Decisions API giả + Runner giả. Trả về (lượt gọi Gemini, lượt gọi OpenAI, trả lời giả)."""
    from app.pipeline import llm_agents

    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    gemini: list[httpx.Request] = []
    openai: list[str] = []
    reply = {
        "status": 200,
        "json": {
            "answers": {
                "relevant": {"type": "noul", "noul": 0.97, "confidence": 0.97},
                "category": {
                    "type": "choice",
                    "choice": "deadline",
                    "probabilities": {"deadline": 0.9},
                    "confidence": 0.9,
                },
            },
            "usage": {"total_input_tokens": 400, "total_output_tokens": 0, "total_tokens": 400},
        },
    }

    def handler(req: httpx.Request):
        gemini.append(req)
        return httpx.Response(reply["status"], json=reply["json"])

    async def fake_run(agent, payload, **kwargs):
        openai.append(agent.name)
        if agent.name == "Triage":
            return _FakeResult(TriageOut(relevant=True, category=Category.exam, reason="GPT lọc"))
        if agent.name == "Extractor":
            return _FakeResult(
                ExtractionOut(
                    tasks=[
                        TaskOut(
                            title="Nộp báo cáo Lab 5",
                            course=None,
                            category=Category.deadline,
                            due_at="2026-11-13T23:59:00+07:00",
                            location=None,
                            action="Nộp",
                        )  # fmt: skip
                    ]
                )
            )
        return _FakeResult("xong")

    monkeypatch.setattr(decision, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(llm_agents.Runner, "run", fake_run)
    return gemini, openai, reply


def _usage():
    db = sqlite3.connect(config.DB_PATH)
    return db.execute(
        "SELECT agent, input_tokens, output_tokens, cost_usd FROM llm_usage ORDER BY id"
    ).fetchall()


def test_gemini_filters_then_answer_model_extracts(client, user, two_models, caplog):
    gemini, openai, _ = two_models
    h, _ = user
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/ingest", json=NOTICE, headers=h)
    out = r.json()
    assert r.status_code == 200 and out["mode"] == "llm" and out["relevant"] and out["category"] == "deadline"
    assert out["reason"] == "Gemini Decision: cần chú ý (97%, tin cậy 97%), loại hạn nộp"
    assert openai == ["Extractor"]  # bước lọc không gọi model trả lời
    (req,) = gemini
    body = json.loads(req.content)
    assert str(req.url) == decision.URL and req.headers["x-goog-api-key"] == KEY
    assert body["model"] == "gemini-decision-1" and "Lab 5" in body["input"]
    assert body["questions"]["relevant"]["type"] == "noul"
    assert set(body["questions"]["category"]["criteria"]) == {c.value for c in Category}
    # Chi phí: model lọc tính riêng 0.10 USD / 1M token đầu vào, không có đầu ra.
    agent, tin, tout, cost = _usage()[0]
    assert (agent, tin, tout) == ("Decision", 400, 0) and cost == pytest.approx(0.00004)
    # Khoá không lọt ra phản hồi hay log.
    assert KEY not in r.text and KEY not in caplog.text
    assert client.get("/api/health").json()["filter_model"] == "gemini-decision-1"
    assert KEY not in client.get("/api/health").text


def test_low_probability_notice_is_filtered_out_without_answer_model(client, user, two_models):
    gemini, openai, reply = two_models
    reply["json"]["answers"]["relevant"]["noul"] = 0.08
    reply["json"]["answers"]["category"]["choice"] = "other"
    h, _ = user
    out = client.post("/api/ingest", json={"body": "Sale 50% trà sữa hôm nay cả nhà ơi"}, headers=h).json()
    assert out["relevant"] is False and out["created"] == [] and out["mode"] == "llm"
    assert out["reason"].startswith("Gemini Decision: bỏ qua (8%, tin cậy")
    assert len(gemini) == 1 and openai == []  # tin nhiễu không tốn lượt model trả lời


@pytest.mark.parametrize(
    "broken",
    [
        {"status": 400, "json": {"error": {"code": "safety", "message": "blocked"}}},
        {"status": 429, "json": {"error": {"message": "quota"}}},
        {
            "status": 200,
            "json": {"answers": {"relevant": {"noul": 0.9}, "category": {"choice": "xoá hết việc"}}},
        },
        {"status": 200, "json": {"answers": {"relevant": {"noul": 7}, "category": {"choice": "exam"}}}},
        {"status": 200, "json": {"answers": {}}},
    ],
)
def test_gemini_failure_falls_back_to_answer_model(client, user, two_models, broken):
    _, openai, reply = two_models
    reply.update(broken)
    h, _ = user
    out = client.post("/api/ingest", json=NOTICE, headers=h).json()
    assert out["mode"] == "llm" and out["reason"] == "GPT lọc" and out["category"] == "exam"
    assert openai == ["Triage", "Extractor"]
    assert _usage()[0][0] == "Decision"  # lượt lỗi vẫn được ước tính vào chi phí


def test_without_gemini_key_answer_model_does_triage(client, user, two_models, monkeypatch):
    gemini, openai, _ = two_models
    monkeypatch.delenv("GEMINI_API_KEY")
    h, _ = user
    client.post("/api/ingest", json=NOTICE, headers=h)
    assert gemini == [] and openai == ["Triage", "Extractor"]
    health = client.get("/api/health").json()
    assert health["filter_model"] == health["model"]


def test_offline_mode_calls_neither_model(client, user, two_models, monkeypatch):
    gemini, openai, _ = two_models
    monkeypatch.setenv("MSTUDENT_OFFLINE", "1")
    h, _ = user
    out = client.post("/api/ingest", json=NOTICE, headers=h).json()
    assert out["mode"] == "offline" and gemini == [] and openai == []


def test_input_is_capped(two_models):
    import asyncio

    from app.models import Message

    gemini, _, _ = two_models
    asyncio.run(decision.decide(Message(body="x" * 8000, subject="s" * 500, sender="n" * 300), None))
    assert len(json.loads(gemini[0].content)["input"]) <= decision.MAX_INPUT_CHARS
