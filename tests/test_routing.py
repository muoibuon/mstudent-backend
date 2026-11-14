"""Decision v1: chỉ lọc nhiễu/phân loại; không gọi mạng."""

from types import SimpleNamespace

import httpx
import pytest

from app import agent_config, budget
from app.models import Category, ExtractionOut, TaskOut, TriageOut
from app.pipeline import decision, llm_agents
from tests.conftest import auth, signup

NOTICE = {"body": "Nộp báo cáo Lab 5 trước 23h59 ngày 20/11.", "subject": "INT3306 Lab 5"}


def draft(category=Category.deadline, title="Nộp báo cáo Lab 5"):
    return TaskOut(
        title=title,
        course="INT3306",
        category=category,
        due_at="2026-11-20T23:59:00+07:00",
        location=None,
        action="Nộp báo cáo",
    )


@pytest.fixture()
def routing(monkeypatch):
    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setenv("MSTUDENT_DECISION_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-test-not-real")
    monkeypatch.setenv("OPENAI_API_KEY", "main-test-not-real")
    calls = []
    world = {
        "p": 0.98,
        "category": Category.deadline,
        "category_conf": 0.94,
        "decision_error": None,
        "main_error": None,
        "tasks": [draft()],
        "review_relevant": True,
    }

    async def decide(msg, user_id=None):
        calls.append(("Decision", user_id, msg.body))
        if world["decision_error"]:
            raise world["decision_error"]
        result = SimpleNamespace(
            relevant=world["p"],
            relevant_conf=max(world["p"], 1 - world["p"]),
            category=world["category"],
            category_conf=world["category_conf"],
            probabilities={world["category"].value: world["category_conf"]},
        )
        result.summary = lambda: {
            "relevant": result.relevant,
            "relevant_conf": result.relevant_conf,
            "category": result.category.value,
            "category_conf": result.category_conf,
        }
        result.hint = lambda min_conf: (
            f"Loại gợi ý: {result.category.value}" if result.category_conf >= min_conf else None
        )
        return result

    async def triage(msg, user_id=None):
        calls.append(("Triage", user_id, None))
        if world["main_error"]:
            raise world["main_error"]
        return TriageOut(relevant=True, category=Category.deadline, reason="Main đã xem lại")

    async def extract(msg, user_id=None, hint=None):
        calls.append(("Extractor", user_id, hint))
        if world["main_error"]:
            raise world["main_error"]
        return ExtractionOut(tasks=world["tasks"])

    async def review(msg, user_id=None):
        calls.append(("Review", user_id, None))
        if world["main_error"]:
            raise world["main_error"]
        result = SimpleNamespace(
            relevant=world["review_relevant"],
            category=Category.deadline,
            reason="Main đã xem lại",
            tasks=world["tasks"] if world["review_relevant"] else [],
        )
        result.model_dump = lambda **kwargs: {
            "relevant": result.relevant,
            "category": result.category.value,
            "reason": result.reason,
            "tasks": [task.model_dump(mode="json") for task in result.tasks],
        }
        return result

    monkeypatch.setattr(decision, "decide", decide, raising=False)
    monkeypatch.setattr(llm_agents, "llm_triage", triage)
    monkeypatch.setattr(llm_agents, "llm_extract", extract)
    monkeypatch.setattr(llm_agents, "llm_review", review, raising=False)
    return world, calls


def ingest(client, user, body=None):
    response = client.post("/api/ingest", json=body or NOTICE, headers=user[0])
    assert response.status_code == 200, response.text
    return response.json()


def route_of(out):
    return next(step["output"]["route"] for step in out["trace"] if step["agent"] == "Decision")


def test_confident_noise_stops_without_main_call(client, user, routing):
    world, calls = routing
    world.update(p=0.02, category=Category.other)
    out = ingest(client, user, {"body": "Flash sale trà sữa giảm 50% hôm nay"})
    assert out["mode"] == "llm" and not out["relevant"] and not out["created"]
    assert route_of(out) == "stop"
    assert [c[0] for c in calls] == ["Decision"]


def test_confident_notice_only_extracts_and_passes_hint(client, user, routing):
    _, calls = routing
    out = ingest(client, user)
    assert route_of(out) == "direct" and out["created"]
    assert [c[0] for c in calls] == ["Decision", "Extractor"]
    assert "deadline" in calls[-1][2]


def test_ambiguous_notice_uses_one_review_call(client, user, routing):
    world, calls = routing
    world["p"] = 0.5
    out = ingest(client, user)
    assert route_of(out) == "review" and out["created"]
    assert [c[0] for c in calls] == ["Decision", "Review"]


def test_review_can_reject_notice_without_extracting(client, user, routing):
    world, calls = routing
    world.update(p=0.5, review_relevant=False)
    out = ingest(client, user)
    assert not out["relevant"] and not out["created"]
    assert [c[0] for c in calls] == ["Decision", "Review"]


@pytest.mark.parametrize(
    "p,expected", [(0.1, "stop"), (0.1001, "review"), (0.7999, "review"), (0.8, "direct")]
)
def test_probability_route_boundaries(client, user, routing, p, expected):
    world, _ = routing
    world["p"] = p
    assert route_of(ingest(client, user)) == expected


def test_saved_threshold_changes_route_without_code_change(client, user, routing):
    world, calls = routing
    world["p"] = 0.7
    agent_config.save({"decision_high": "0.65"})
    out = ingest(client, user)
    assert route_of(out) == "direct"
    assert [c[0] for c in calls] == ["Decision", "Extractor"]


@pytest.mark.parametrize("confidence", [0.2, 0.74])
def test_uncertain_category_does_not_add_triage_call(client, user, routing, confidence):
    world, calls = routing
    world["category_conf"] = confidence
    out = ingest(client, user)
    assert route_of(out) == "direct" and out["created"]
    assert [c[0] for c in calls] == ["Decision", "Extractor"]


def test_other_is_not_a_noise_label(client, user, routing):
    world, calls = routing
    world.update(category=Category.other, tasks=[])
    out = ingest(client, user, {"body": "Tài liệu tham khảo môn OOP, đọc khi ôn tập."})
    assert out["relevant"] and out["category"] == "other" and not out["created"]
    assert [c[0] for c in calls] == ["Decision", "Extractor"]


def test_notice_label_does_not_override_each_task_category(client, user, routing):
    world, _ = routing
    world["tasks"] = [draft(), draft(Category.exam, "Thi vấn đáp OOP")]
    out = ingest(client, user)
    assert {task["category"] for task in out["created"]} == {"deadline", "exam"}


def test_direct_event_label_does_not_force_extracted_deadline_into_event(client, user, routing):
    world, calls = routing
    world.update(category=Category.event, category_conf=0.99)
    out = ingest(client, user)
    assert out["category"] == "event" and route_of(out) == "direct"
    assert [task["category"] for task in out["created"]] == ["deadline"]
    assert out["created"][0]["rsvp"] is None
    assert [call[0] for call in calls] == ["Decision", "Extractor"]


@pytest.mark.parametrize("error", [ValueError("invalid response"), httpx.ReadTimeout("timeout")])
def test_decision_error_uses_legacy_main_path(client, user, routing, error):
    world, calls = routing
    world["decision_error"] = error
    out = ingest(client, user)
    assert route_of(out) == "fallback" and out["mode"] == "llm" and out["created"]
    assert [c[0] for c in calls] == ["Decision", "Triage", "Extractor"]


def test_provider_error_details_are_not_exposed_in_trace(client, user, routing, caplog, monkeypatch):
    from app.pipeline import assistant

    world, _ = routing
    sentinel = "private-credential-and-provider-request-body"
    world["decision_error"] = RuntimeError(sentinel)
    out = ingest(client, user)

    async def provider_failure(*args, **kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(llm_agents, "llm_digest", provider_failure)
    monkeypatch.setattr(assistant, "_llm_chat", provider_failure)
    digest = client.get("/api/digest", headers=user[0])
    chat = client.post("/api/chat", headers=user[0], json={"message": "Xin chào", "history": []})
    assert digest.status_code == chat.status_code == 200
    assert digest.json()["mode"] == chat.json()["mode"] == "offline"
    traces = client.get("/api/traces", headers=user[0])
    assert sentinel not in str(out) + digest.text + chat.text + traces.text
    assert sentinel not in caplog.text


def test_disabled_decision_uses_legacy_main_path(client, user, routing, monkeypatch):
    monkeypatch.setenv("MSTUDENT_DECISION_ENABLED", "0")
    _, calls = routing
    out = ingest(client, user)
    assert out["created"]
    assert [c[0] for c in calls] == ["Triage", "Extractor"]


@pytest.mark.parametrize("disabled", ["offline", "budget"])
def test_offline_or_budget_calls_neither_provider(client, user, routing, monkeypatch, disabled):
    if disabled == "offline":
        monkeypatch.setenv("MSTUDENT_OFFLINE", "1")
    else:
        monkeypatch.setattr(budget, "llm_allowed", lambda user_id=None: False)
    _, calls = routing
    out = ingest(client, user)
    assert out["mode"] == "offline" and out["created"] and calls == []


@pytest.mark.parametrize("route", ["review", "fallback"])
def test_budget_exhausted_after_decision_blocks_further_main_calls(client, user, routing, monkeypatch, route):
    world, calls = routing
    if route == "review":
        world["p"] = 0.5
    else:
        world["decision_error"] = httpx.ReadTimeout("timeout")
    monkeypatch.setattr(budget, "llm_allowed", lambda user_id=None: not calls)
    out = ingest(client, user)
    assert route_of(out) == route
    assert out["mode"] == "offline" and out["created"]
    assert [call[0] for call in calls] == ["Decision"]


def test_main_failure_falls_back_to_rules(client, user, routing):
    world, calls = routing
    world["main_error"] = RuntimeError("provider unavailable")
    out = ingest(client, user)
    assert out["mode"] == "offline" and out["created"]
    assert [c[0] for c in calls] == ["Decision", "Extractor"]


def test_duplicate_message_uses_cache_before_both_models(client, user, routing):
    _, calls = routing
    first = ingest(client, user)
    before = len(calls)
    second = ingest(client, user)
    assert first["created"] and second["duplicate"] and second["mode"] == "cache"
    assert len(calls) == before


@pytest.mark.parametrize("p", [0.98, 0.5])
def test_direct_and_review_apply_agreed_class_time_without_another_model(client, user, routing, p):
    world, calls = routing
    world["p"] = p
    world["category"] = Category.class_change
    world["tasks"] = [
        draft(category=Category.class_change, title="Học OOP").model_copy(
            update={"course": "OOP", "due_at": "2026-11-23T09:00:00+07:00"}
        )
    ]
    out = ingest(
        client, user, {"body": "thứ 2 tuần sau sáng tôi học oop", "received_at": "2026-11-14T16:43:00+07:00"}
    )
    assert out["mode"] == "llm" and len(out["created"]) == 1
    assert out["created"][0]["due_at"] == "2026-11-16T08:00:00+07:00"
    assert "Giờ mặc định" in out["created"][0]["action"]
    assert any(s["agent"] == "TimeDefaults" and s["kind"] == "python" for s in out["trace"])
    assert [c[0] for c in calls] == ["Decision", "Extractor" if p == 0.98 else "Review"]


def test_message_cache_and_tasks_are_per_user(client, user, routing):
    _, calls = routing
    second_tokens = signup(client, email="second@example.test")
    first = ingest(client, user)
    second = ingest(client, (auth(second_tokens), second_tokens))
    assert first["created"] and second["created"] and not second["duplicate"]
    assert first["created"][0]["id"] != second["created"][0]["id"]
    assert len({c[1] for c in calls if c[0] == "Decision"}) == 2
