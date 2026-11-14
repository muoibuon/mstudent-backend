"""Classifier benchmark dispatch and honest accounting; providers are mocked."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import budget, config, repo
from app.models import Category, ExtractionOut, Source, TriageOut
from eval import run_decision_eval as benchmark


@pytest.fixture()
def evaluation(monkeypatch, tmp_path):
    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setattr(budget, "llm_allowed", lambda user_id=None: not config.is_offline_forced())
    monkeypatch.setattr(config, "decision_enabled", lambda: True)
    monkeypatch.setattr(repo, "record_llm_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(budget, "_maybe_alert", lambda: None)
    cases = [
        {
            "id": "cal-noise",
            "split": "calibration",
            "source": "zalo",
            "subject": "",
            "body": "Xin chào.",
            "expected": {"relevant": False},
        },
        {
            "id": "accept-exam",
            "split": "acceptance",
            "source": "email",
            "subject": "Lịch thi",
            "body": "Thi OOP ngày mai.",
            "expected": {"relevant": True, "category": "exam"},
        },
        {
            "id": "accept-noise",
            "split": "acceptance",
            "source": "manual",
            "subject": "",
            "body": "Trà sữa giảm giá.",
            "expected": {"relevant": False},
        },
    ]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(benchmark, "CASES", path)
    world = {"calls": [], "decision_error": None, "main_error": None, "offline_gate": False}

    def record(agent):
        budget.record_usage(
            None, agent, 100, 0 if agent == "Decision" else 20, 0.00001, 5, estimated=agent != "Decision"
        )

    async def decide(msg, user_id=None):
        world["calls"].append(("Decision", msg.body))
        record("Decision")
        if world["decision_error"]:
            raise world["decision_error"]
        relevant = msg.body.startswith("Thi")
        out = SimpleNamespace(
            relevant=0.95 if relevant else 0.02, category=Category.exam if relevant else Category.other
        )
        out.summary = lambda: {"relevant": out.relevant, "category": out.category.value}
        out.hint = lambda threshold: "exam" if relevant else None
        return out

    async def triage(msg, user_id=None):
        world["calls"].append(("Triage", msg.body))
        record("Triage")
        if world["main_error"]:
            raise world["main_error"]
        relevant = msg.body.startswith("Thi")
        return TriageOut(
            relevant=relevant, category=Category.exam if relevant else Category.other, reason="mock"
        )

    async def extract(msg, user_id=None, hint=None):
        world["calls"].append(("Extractor", msg.body))
        record("Extractor")
        if world["main_error"]:
            raise world["main_error"]
        return ExtractionOut(tasks=[])

    async def classify(user_id, msg, trace):
        world["calls"].append(("Gate", msg.body))
        out = await decide(msg)
        relevant = out.relevant >= 0.8
        if relevant:
            await extract(msg)
        trace.add("Decision", "llm", 0, {"route": "direct" if relevant else "stop"})
        tri = TriageOut(relevant=relevant, category=out.category, reason="mock")
        return tri, None, "offline" if world["offline_gate"] else "llm"

    monkeypatch.setattr(benchmark.decision, "decide", decide)
    monkeypatch.setattr(benchmark.llm_agents, "llm_triage", triage)
    monkeypatch.setattr(benchmark.llm_agents, "llm_extract", extract)
    monkeypatch.setattr(benchmark.orchestrator, "classify", classify)
    return world, path, cases


@pytest.mark.parametrize(
    "mode,expected,main_runs,decision_calls",
    [
        ("decision", ["Decision", "Decision"], 0, 2),
        ("threshold", ["Decision", "Extractor", "Decision"], 1, 2),
        ("main-only", ["Triage", "Extractor", "Triage"], 3, 0),
        ("gate", ["Gate", "Decision", "Extractor", "Gate", "Decision"], 1, 2),
    ],
)
def test_modes_dispatch_and_capture_request_local_usage(
    evaluation, mode, expected, main_runs, decision_calls
):
    world, _, _ = evaluation
    result = asyncio.run(benchmark.evaluate_cases(mode, "acceptance"))
    summary = result["summary"]
    assert [call[0] for call in world["calls"]] == expected
    assert summary["main_runs"] == main_runs and summary["decision_calls"] == decision_calls
    assert summary["completed"] == summary["matched"] == summary["planned"] == 2
    assert summary["input_tokens"] == 100 * (main_runs + decision_calls)
    assert summary["output_tokens"] == 20 * main_runs
    assert summary["reported_decision_usd"] == pytest.approx(0.00001 * decision_calls)
    assert summary["estimated_usd"] == pytest.approx(0.00001 * main_runs)


def test_acceptance_split_and_limit_do_not_use_calibration_cases(evaluation):
    world, _, _ = evaluation
    result = asyncio.run(benchmark.evaluate_cases("decision", "acceptance", limit=1))
    assert [case["id"] for case in result["cases"]] == ["accept-exam"]
    assert world["calls"] == [("Decision", "Thi OOP ngày mai.")]
    assert result["summary"]["planned"] == result["summary"]["completed"] == 1


def test_offline_refuses_to_benchmark_rules_as_models(evaluation, monkeypatch):
    world, _, _ = evaluation
    monkeypatch.setenv("MSTUDENT_OFFLINE", "1")
    with pytest.raises(RuntimeError, match="bộ luật"):
        asyncio.run(benchmark.evaluate_cases("decision", "acceptance"))
    assert world["calls"] == []


@pytest.mark.parametrize("mode", ["decision", "gate", "threshold"])
def test_decision_modes_require_decision_provider(evaluation, monkeypatch, mode):
    world, _, _ = evaluation
    monkeypatch.setattr(config, "decision_enabled", lambda: False)
    with pytest.raises(RuntimeError, match="OPENROUTER"):
        asyncio.run(benchmark.evaluate_cases(mode, "acceptance"))
    assert world["calls"] == []


def test_invalid_provider_response_is_error_not_fake_successful_fallback(evaluation):
    world, _, _ = evaluation
    world["decision_error"] = benchmark.decision.DecisionError("invalid choice distribution")
    result = asyncio.run(benchmark.evaluate_cases("decision", "acceptance"))
    summary = result["summary"]
    assert summary["errors"] == 2 and summary["matched"] == 0
    assert summary["category_correct"] == 0 and summary["useful_recall"] == 0
    assert summary["main_runs"] == 0 and summary["routes"] == {"error": 2}
    assert all("got" not in row for row in result["cases"])
    assert [call[0] for call in world["calls"]] == ["Decision", "Decision"]


def test_main_failure_after_decision_does_not_inflate_quality(evaluation):
    world, _, _ = evaluation
    world["main_error"] = RuntimeError("main provider failed")
    result = asyncio.run(benchmark.evaluate_cases("threshold", "acceptance"))
    summary = result["summary"]
    assert summary["errors"] == 1 and summary["matched"] == 1  # only the noise case completed successfully
    assert summary["category_correct"] == 0 and summary["useful_recall"] == 0


def test_offline_gate_result_is_not_counted_as_model_correctness(evaluation):
    world, _, _ = evaluation
    world["offline_gate"] = True
    summary = asyncio.run(benchmark.evaluate_cases("gate", "acceptance"))["summary"]
    assert summary["offline_fallbacks"] == 2 and summary["matched"] == 0
    assert summary["category_correct"] == 0 and summary["useful_recall"] == 0


def test_budget_break_reports_partial_run_and_does_not_score_unprocessed_case(evaluation, monkeypatch):
    world, _, _ = evaluation
    monkeypatch.setattr(budget, "llm_allowed", lambda user_id=None: not world["calls"])
    result = asyncio.run(benchmark.evaluate_cases("decision", "acceptance"))
    summary = result["summary"]
    assert summary["planned"] == 2 and summary["completed"] == 1
    assert [case["id"] for case in result["cases"]] == ["accept-exam"]
    assert summary["matched"] == 1 and summary["decision_calls"] == 1


@pytest.mark.parametrize(
    "mode,split,limit",
    [("unknown", "acceptance", None), ("decision", "unknown", None), ("decision", "all", 0)],
)
def test_invalid_programmatic_options_fail_before_provider(evaluation, mode, split, limit):
    world, _, _ = evaluation
    with pytest.raises(ValueError):
        asyncio.run(benchmark.evaluate_cases(mode, split, limit))
    assert world["calls"] == []


@pytest.mark.parametrize(
    "field,value", [("source", "invalid"), ("expected", {"relevant": True, "category": "invalid"})]
)
def test_invalid_dataset_is_rejected_before_any_provider_call(evaluation, field, value):
    world, path, cases = evaluation
    cases[-1][field] = value
    path.write_text(json.dumps(cases), encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(benchmark.evaluate_cases("decision", "acceptance"))
    assert world["calls"] == []


def test_dataset_integrity_and_disjoint_holdout():
    cases = json.loads(
        (Path(__file__).resolve().parents[1] / "eval/decision_cases.json").read_text(encoding="utf-8")
    )
    assert len(cases) == len({case["id"] for case in cases}) == 100
    bodies = {"calibration": set(), "acceptance": set()}
    for case in cases:
        Source(case["source"])
        assert type(case["expected"]["relevant"]) is bool
        if case["expected"]["relevant"]:
            Category(case["expected"]["category"])
        assert case["body"].strip() and isinstance(case["subject"], str)
        bodies[case["split"]].add(" ".join(case["body"].casefold().split()))
    assert len(bodies["calibration"]) == 40 and len(bodies["acceptance"]) == 60
    assert bodies["calibration"].isdisjoint(bodies["acceptance"])
