"""Provider chính dùng Responses endpoint đã chọn; không gọi mạng trong test."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app import agent_config, config
from app.models import Category, Message
from app.pipeline import assistant, llm_agents


def _response(text, model):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


@pytest.fixture()
def gateway(monkeypatch):
    """Runner/Responses thật, HTTP giả; mọi host ngoài gateway làm test thất bại."""
    monkeypatch.setenv("OPENAI_API_KEY", "gateway-test-not-real")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.test/v1")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
    model = "cx/gpt-6-luna(xhigh)"
    monkeypatch.setattr(agent_config, "get", lambda: agent_config.DEFAULTS | {"model": model})
    calls = []
    reply = {"text": "OK"}

    def handler(request):
        assert str(request.url) == "https://gateway.test/v1/responses"
        assert request.headers["authorization"] == "Bearer gateway-test-not-real"
        body = json.loads(request.content)
        assert body["model"] == model
        assert body["reasoning"]["effort"] == "high"
        calls.append(body)
        return httpx.Response(200, json=_response(reply["text"], model))

    custom = AsyncOpenAI(
        base_url=config.openai_base_url(),
        api_key=config.openai_api_key(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    monkeypatch.setattr(llm_agents, "_client", lambda base_url, api_key: custom)
    monkeypatch.setattr(llm_agents.budget, "record", lambda *args: None)
    monkeypatch.setattr(llm_agents.budget, "record_failure", lambda *args: None)
    return calls, reply


def test_review_uses_gateway_once_with_strict_schema_and_guard(gateway):
    calls, reply = gateway
    reply["text"] = json.dumps(
        {"relevant": True, "category": "deadline", "reason": "Có việc cần làm", "tasks": []}
    )
    result = asyncio.run(llm_agents.llm_review(Message(body="Nhớ nộp báo cáo ngày mai"), 1))
    assert result.relevant and result.category == Category.deadline and result.tasks == []
    assert len(calls) == 1
    schema = calls[0]["text"]["format"]
    assert schema["strict"] is True
    assert set(schema["schema"]["required"]) == {"relevant", "category", "reason", "tasks"}
    assert agent_config.GUARD in calls[0]["instructions"]


def test_assistant_uses_same_gateway_and_preserves_tools(gateway):
    calls, _ = gateway
    result = asyncio.run(assistant._llm_chat(7, "Xin chào", []))
    assert result.reply == "OK" and result.mode == "llm"
    assert len(calls) == 1
    assert {t["name"] for t in calls[0]["tools"]} == {
        "list_tasks",
        "add_notice",
        "complete_task",
        "get_digest",
    }


def test_extractor_gets_hint_outside_untrusted_notice(gateway):
    calls, reply = gateway
    reply["text"] = '{"tasks": []}'
    asyncio.run(llm_agents.llm_extract(Message(body="Thông báo"), 1, "loại gợi ý: deadline"))
    payload = json.dumps(calls[0]["input"], ensure_ascii=False)
    assert payload.index("</thong_bao>") < payload.index("loại gợi ý: deadline")


def test_decision_config_requires_openrouter_and_respects_switch(monkeypatch):
    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.delenv("MSTUDENT_DECISION_ENABLED", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-test-not-real")
    assert not config.decision_enabled()
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-test-not-real")
    assert config.decision_enabled()
    monkeypatch.setenv("MSTUDENT_DECISION_ENABLED", "0")
    assert not config.decision_enabled()
    monkeypatch.setenv("MSTUDENT_DECISION_ENABLED", "1")
    monkeypatch.setenv("MSTUDENT_OFFLINE", "1")
    assert not config.decision_enabled()


def test_review_schema_requires_all_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        llm_agents.ReviewOut(relevant=True, category="other", reason="Hữu ích")


def test_official_openai_defaults_and_effort_validation(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    assert config.openai_base_url() == "https://api.openai.com/v1"
    assert config.openai_reasoning_effort() == "high"
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "xhigh")
    assert config.openai_reasoning_effort() == "xhigh"
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "invalid")
    with pytest.raises(ValueError):
        config.openai_reasoning_effort()
