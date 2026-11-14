"""Eval measures the runtime classifier and request-local provider usage."""

import asyncio
import json

import pytest

from app import budget, config, evaluation
from app.models import Category, ExtractionOut, TaskOut, TriageOut


@pytest.fixture()
def measured_cases(tmp_path, monkeypatch):
    cases = [
        {"body": "Nộp báo cáo", "expect": {"relevant": True, "category": "deadline"}},
        {"body": "Đi ăn trưa không?", "expect": {"relevant": False}},
    ]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(evaluation, "CASES_PATH", path)
    monkeypatch.setattr(budget, "llm_allowed", lambda user_id=None: True)
    monkeypatch.setattr(budget.repo, "record_llm_usage", lambda *args: None)
    monkeypatch.setattr(budget, "_maybe_alert", lambda: None)
    return cases


def test_eval_uses_classifier_and_measures_decision_vs_main_only(measured_cases, monkeypatch):
    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-test-not-real")
    seen = []

    async def classify(user_id, msg, trace):
        assert user_id is None
        seen.append(msg.body)
        relevant = msg.body == "Nộp báo cáo"
        if config.decision_enabled():
            route = "direct" if relevant else "stop"
            budget.record_usage(None, "Decision", 100, 0, 0.00001, 3, estimated=False)
        else:
            route = "fallback"
            budget.record_usage(None, "Triage", 200, 20, 0.00003, 5)
        trace.steps.append({"output": {"route": route}})
        tri = TriageOut(relevant=relevant, category=Category.deadline, reason="Kết quả thử")
        ext = None
        if relevant:
            budget.record_usage(None, "Extractor", 300, 30, 0.00004, 7)
            ext = ExtractionOut(
                tasks=[
                    TaskOut(
                        title="Nộp báo cáo",
                        course=None,
                        category=Category.deadline,
                        due_at=None,
                        location=None,
                        action=None,
                    )
                ]
            )
        return tri, ext, "llm"

    monkeypatch.setattr(evaluation.orchestrator, "classify", classify)
    gated = asyncio.run(evaluation.evaluate(use_llm=True))
    assert seen == [c["body"] for c in measured_cases]
    assert gated["metrics"]["routes"] == {"direct": 1, "stop": 1}
    assert gated["metrics"]["decision_calls"] == 2
    assert gated["metrics"]["main_calls"] == 1
    assert gated["metrics"]["input_tokens"] == 500
    assert gated["metrics"]["output_tokens"] == 30
    assert gated["metrics"]["estimated_cost_usd"] == pytest.approx(0.00006)
    assert gated["scores"]["relevant"]["pct"] == 100
    assert gated["metrics"]["p50_ms"] is not None and gated["metrics"]["p95_ms"] is not None
    assert "ước tính" in gated["metrics"]["cost_note"]

    monkeypatch.setenv("MSTUDENT_DECISION_ENABLED", "0")
    baseline = asyncio.run(evaluation.evaluate(use_llm=True))
    assert baseline["metrics"]["routes"] == {"fallback": 2}
    assert baseline["metrics"]["decision_calls"] == 0
    assert baseline["metrics"]["main_calls"] == 3
    assert baseline["metrics"]["estimated_cost_usd"] == pytest.approx(0.0001)


def test_capture_usage_isolates_concurrent_tasks_and_nested_scope(monkeypatch):
    monkeypatch.setattr(budget.repo, "record_llm_usage", lambda *args: None)
    monkeypatch.setattr(budget, "_maybe_alert", lambda: None)

    async def measured(name):
        with budget.capture_usage() as rows:
            budget.record_usage(None, name, 10, 0, 0.1, 1, estimated=False)
            await asyncio.sleep(0)
            with budget.capture_usage() as nested:
                budget.record_usage(None, name + " nested", 20, 0, 0.2, 2)
            budget.record_usage(None, name, 30, 0, 0.3, 3)
            return rows, nested

    async def concurrent():
        return await asyncio.gather(measured("A"), measured("B"))

    a, b = asyncio.run(concurrent())
    assert [r["agent"] for r in a[0]] == ["A", "A"]
    assert [r["agent"] for r in b[0]] == ["B", "B"]
    assert [r["agent"] for r in a[1]] == ["A nested"]
    assert [r["agent"] for r in b[1]] == ["B nested"]
    assert [r["estimated"] for r in a[0]] == [False, True]
    with budget.capture_usage() as fresh:
        assert fresh == []


def test_eval_keeps_usage_of_failed_provider_call(measured_cases, monkeypatch):
    async def broken(user_id, msg, trace):
        budget.record_usage(None, "Review", 50, 50, 0.001, 10)
        raise TimeoutError("provider timeout")

    monkeypatch.setattr(evaluation.orchestrator, "classify", broken)
    result = asyncio.run(evaluation.evaluate(use_llm=True))
    assert all(not c["ok"] for c in result["cases"])
    assert result["metrics"]["main_calls"] == len(measured_cases)
    assert result["metrics"]["estimated_cost_usd"] == pytest.approx(0.002)
