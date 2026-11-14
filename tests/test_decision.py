"""OpenRouter Decisions: hợp đồng thật, kiểm tra đầu ra và ghi usage; không gọi mạng."""

import asyncio
import copy
import json
import logging
import sqlite3

import httpx
import pytest

from app import budget, config
from app.models import Category, Message
from app.pipeline import decision

KEY = "sk-or-test-not-real"


def response_data():
    return {
        "model": "google/gemini-decision-1-20261111",
        "provider": "Google AI Studio",
        "answers": {
            "relevant": {"type": "noul", "noul": 0.97, "confidence": 0.97},
            "category": {
                "type": "choice",
                "choice": "deadline",
                "probabilities": {
                    "deadline": 0.9,
                    "exam": 0.02,
                    "class_change": 0.02,
                    "event": 0.02,
                    "admin": 0.02,
                    "other": 0.02,
                },
                "confidence": 0.9,
            },
        },
        "usage": {"input_tokens": 400, "output_tokens": 0, "cost": 0.000041},
    }


@pytest.fixture()
def api(monkeypatch, user):
    requests = []
    reply = {"status": 200, "data": response_data()}
    monkeypatch.setattr(config, "openrouter_api_key", lambda: KEY, raising=False)
    monkeypatch.setattr(config, "decision_model", lambda: "google/gemini-decision-1")

    def handler(request):
        requests.append(request)
        return httpx.Response(reply["status"], json=reply["data"])

    monkeypatch.setattr(decision, "_transport", httpx.MockTransport(handler))
    return requests, reply, user[1]["user"]["id"]


def call(uid, **values):
    return asyncio.run(decision.decide(Message(body="Nộp báo cáo Lab 5 trước thứ 6", **values), uid))


def usage():
    with sqlite3.connect(config.DB_PATH) as db:
        return db.execute(
            "SELECT agent,input_tokens,output_tokens,cost_usd FROM llm_usage ORDER BY id"
        ).fetchall()


def test_openrouter_contract_and_actual_usage(api, caplog):
    requests, _, uid = api
    with caplog.at_level(logging.DEBUG):
        result = call(uid, sender="Thầy Nam <teacher@example.edu>", subject="Lab 5")
    assert result.category == Category.deadline and result.relevant == 0.97
    (request,) = requests
    payload = json.loads(request.content)
    assert str(request.url) == decision.URL
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert "x-goog-api-key" not in request.headers
    assert payload["model"] == "google/gemini-decision-1"
    assert set(payload) == {"model", "state", "questions"}
    assert set(payload["questions"]) == {"relevant", "category"}
    assert "<thong_bao>" in payload["state"] and "teacher@example.edu" not in payload["state"]
    assert usage() == [("Decision", 400, 0, 0.000041)]
    assert result.input_tokens == 400 and result.cost_usd == 0.000041
    assert result.summary()["model"] == "google/gemini-decision-1-20261111"
    assert KEY not in caplog.text and KEY not in json.dumps(result.summary())


@pytest.mark.parametrize(
    "probability,route",
    [(0, "stop"), (0.1, "stop"), (0.1001, "review"), (0.7999, "review"), (0.8, "direct"), (1, "direct")],
)
def test_route_boundaries_and_category_uncertainty(probability, route):
    result = decision.parse(response_data()["answers"])
    result.relevant = probability
    result.category_conf = 0.2
    assert decision.route(result, {"low": 0.1, "high": 0.8, "category_conf": 0.75}) == route
    assert result.hint(0.75) is None


def test_other_is_not_noise():
    data = response_data()["answers"]
    data["category"]["choice"] = "other"
    data["category"]["probabilities"]["other"], data["category"]["probabilities"]["deadline"] = 0.9, 0.02
    result = decision.parse(data)
    assert decision.route(result, {"low": 0.1, "high": 0.8}) == "direct"
    assert "từng việc" in result.hint(0.75)


@pytest.mark.parametrize(
    "target,key,value",
    [
        ("relevant", "type", "choice"),
        ("relevant", "noul", True),
        ("relevant", "noul", "0.9"),
        ("relevant", "noul", float("nan")),
        ("relevant", "noul", float("inf")),
        ("relevant", "noul", -0.1),
        ("relevant", "confidence", None),
        ("category", "type", "noul"),
        ("category", "confidence", 1.1),
        ("category", "confidence", None),
        ("category", "choice", "delete_all"),
        ("category", "choice", "exam"),
        ("category", "probabilities", {"deadline": 1}),
        ("category", "probabilities", {k: 0.5 for k in decision.CATEGORY_CRITERIA}),
    ],
)
def test_invalid_answers_are_rejected(target, key, value):
    answers = copy.deepcopy(response_data()["answers"])
    answers[target][key] = value
    with pytest.raises(decision.DecisionError):
        decision.parse(answers)


@pytest.mark.parametrize("answers", [None, [], {}, {"relevant": {"type": "noul"}}])
def test_missing_answers_fail(answers):
    with pytest.raises(decision.DecisionError):
        decision.parse(answers)


def test_malformed_response_still_records_provider_usage_once(api):
    _, reply, uid = api
    reply["data"]["answers"] = {}
    with pytest.raises(decision.DecisionError):
        call(uid)
    assert usage() == [("Decision", 400, 0, 0.000041)]


@pytest.mark.parametrize("status", [400, 401, 429, 503])
def test_http_failure_records_estimate_without_raw_error(api, status):
    _, reply, uid = api
    reply.update(status=status, data={"error": {"message": KEY}})
    with pytest.raises(decision.DecisionError, match=f"Decisions API trả {status}") as error:
        call(uid)
    assert KEY not in str(error.value)
    (row,) = usage()
    assert row[0] == "Decision" and row[1] > 0 and row[2] == 0 and row[3] > 0


def test_timeout_is_counted_once(api, monkeypatch):
    _, _, uid = api

    def fail(request):
        raise httpx.ReadTimeout("temporary", request=request)

    monkeypatch.setattr(decision, "_transport", httpx.MockTransport(fail))
    with pytest.raises(httpx.ReadTimeout):
        call(uid)
    assert len(usage()) == 1


def test_zero_usage_is_not_replaced_by_estimate(api):
    _, reply, uid = api
    reply["data"]["usage"] = {"input_tokens": 0, "output_tokens": 0, "cost": 0}
    call(uid)
    assert usage() == [("Decision", 0, 0, 0)]


def test_request_local_counters_mark_actual_and_estimated_usage(api):
    _, reply, uid = api
    with budget.capture_usage() as rows:
        call(uid)
        reply.update(status=503, data={"error": {"message": "unavailable"}})
        with pytest.raises(decision.DecisionError):
            call(uid)
    assert len(rows) == 2
    assert rows[0]["estimated"] is False and rows[0]["cost_usd"] == 0.000041
    assert rows[1]["estimated"] is True


def test_error_response_preserves_reported_cost(api):
    _, reply, uid = api
    reply["status"] = 503
    with pytest.raises(decision.DecisionError):
        call(uid)
    assert usage() == [("Decision", 400, 0, 0.000041)]


def test_non_json_provider_response_is_safe(api, monkeypatch):
    _, _, uid = api
    monkeypatch.setattr(
        decision, "_transport", httpx.MockTransport(lambda request: httpx.Response(200, text=KEY))
    )
    with pytest.raises(decision.DecisionError, match="Phản hồi không hợp lệ") as error:
        call(uid)
    assert KEY not in str(error.value) and len(usage()) == 1


def test_input_cap_preserves_wrapper(api):
    requests, _, uid = api
    asyncio.run(decision.decide(Message(body="x" * 8000, sender="s" * 300, subject="t" * 500), uid))
    state = json.loads(requests[0].content)["state"]
    assert len(state) <= decision.MAX_INPUT_CHARS and state.endswith("</thong_bao>")
