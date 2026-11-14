"""Controlled classifier comparison on synthetic data; writes usage, never tasks.

python -m eval.run_decision_eval --mode decision --split acceptance
python -m eval.run_decision_eval --mode gate --limit 10 --output report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

from app import budget, config
from app.models import Category, Message, Source
from app.pipeline import decision, llm_agents, orchestrator

CASES = Path(__file__).with_name("decision_cases.json")


async def evaluate_cases(mode: str, split: str, limit: int | None = None) -> dict:
    if mode not in ("decision", "gate", "main-only", "threshold"):
        raise ValueError("Chế độ eval không hợp lệ")
    if split not in ("calibration", "acceptance", "all") or (limit is not None and limit < 1):
        raise ValueError("Tập hoặc giới hạn eval không hợp lệ")
    dataset = json.loads(CASES.read_text(encoding="utf-8"))
    seen = set()
    for case in dataset:
        if case["id"] in seen or case["split"] not in ("calibration", "acceptance"):
            raise ValueError("ID hoặc tập dữ liệu eval không hợp lệ")
        seen.add(case["id"])
        Source(case["source"])
        expected = case["expected"]
        if type(expected["relevant"]) is not bool:
            raise ValueError("Nhãn relevant phải là boolean")
        if expected["relevant"]:
            Category(expected["category"])
    if not budget.llm_allowed():
        raise RuntimeError("Cần bật model chính và còn ngân sách; không chạy benchmark bằng bộ luật")
    if mode != "main-only" and not config.decision_enabled():
        raise RuntimeError("Cần OPENROUTER_API_KEY và MSTUDENT_DECISION_ENABLED=1")
    cases = [c for c in dataset if split == "all" or c["split"] == split]
    if limit is not None:
        cases = cases[:limit]
    rows, all_usage = [], []
    for case in cases:
        # Stop the run rather than count budget-induced offline responses as model quality.
        if not budget.llm_allowed():
            break
        msg = Message(
            source=Source(case["source"]),
            subject=case["subject"],
            body=case["body"],
            received_at="2026-11-14T08:00:00+07:00",
        )
        started = time.perf_counter()
        row = {"id": case["id"], "source": case["source"], "expected": case["expected"]}
        with budget.capture_usage() as usage:
            try:
                if mode == "gate":
                    trace = orchestrator.Tracer()
                    tri, _, runtime_mode = await orchestrator.classify(None, msg, trace)
                    row["route"] = next(
                        (s["output"]["route"] for s in trace.steps if s.get("output", {}).get("route")),
                        "offline",
                    )
                    row["mode"] = runtime_mode
                    row["got"] = {"relevant": tri.relevant, "category": tri.category.value}
                elif mode in ("decision", "threshold"):
                    d = await decision.decide(msg)
                    relevant = d.relevant >= 0.5
                    row.update(route="direct" if relevant else "stop", decision=d.summary())
                    row["got"] = {"relevant": relevant, "category": d.category.value}
                    if mode == "threshold" and relevant:
                        if not budget.llm_allowed():
                            raise RuntimeError("Đã hết ngân sách sau Decision")
                        await llm_agents.llm_extract(msg, hint=d.hint(0.75))
                else:
                    tri = await llm_agents.llm_triage(msg)
                    row.update(
                        route="fallback", got={"relevant": tri.relevant, "category": tri.category.value}
                    )
                    if tri.relevant:
                        if not budget.llm_allowed():
                            raise RuntimeError("Đã hết ngân sách sau Triage")
                        await llm_agents.llm_extract(msg)
                exp, got = row["expected"], row["got"]
                row["ok"] = got["relevant"] == exp["relevant"] and (
                    not exp["relevant"] or got["category"] == exp["category"]
                )
                if row.get("mode") == "offline":
                    row["ok"] = False
            except Exception as error:
                row.update(ok=False, error=type(error).__name__, route="error")
        row["ms"] = round((time.perf_counter() - started) * 1000, 1)
        row["usage"] = usage
        all_usage.extend(usage)
        rows.append(row)
    relevant_cases = [r for r in rows if r["expected"]["relevant"]]

    def measured(row):
        return "error" not in row and row.get("mode") != "offline"

    tp = sum(measured(r) and bool(r.get("got", {}).get("relevant")) for r in relevant_cases)
    fp = sum(
        measured(r) and bool(r.get("got", {}).get("relevant")) for r in rows if not r["expected"]["relevant"]
    )
    category_ok = sum(
        measured(r) and r.get("got", {}).get("category") == r["expected"]["category"] for r in relevant_cases
    )
    confusion = {}
    for row in relevant_cases:
        prediction = row.get("got", {}).get("category", "error") if measured(row) else "error"
        key = row["expected"]["category"] + " → " + prediction
        confusion[key] = confusion.get(key, 0) + 1
    latency = sorted(r["ms"] for r in rows)
    return {
        "summary": {
            "mode": mode,
            "split": split,
            "planned": len(cases),
            "completed": len(rows),
            "matched": sum(r["ok"] for r in rows),
            "errors": sum("error" in r for r in rows),
            "offline_fallbacks": sum(r.get("mode") == "offline" for r in rows),
            "routes": dict(Counter(r["route"] for r in rows)),
            "useful_recall": tp / len(relevant_cases) if relevant_cases else None,
            "useful_precision": tp / (tp + fp) if tp + fp else None,
            "category_correct": category_ok,
            "category_total": len(relevant_cases),
            "important_stopped": sum(r["route"] == "stop" for r in relevant_cases),
            "confusion": confusion,
            "main_runs": sum(u["agent"] != "Decision" for u in all_usage),
            "decision_calls": sum(u["agent"] == "Decision" for u in all_usage),
            "input_tokens": sum(u["input_tokens"] for u in all_usage),
            "output_tokens": sum(u["output_tokens"] for u in all_usage),
            "reported_decision_usd": sum(u["cost_usd"] for u in all_usage if not u["estimated"]),
            "estimated_usd": sum(u["cost_usd"] for u in all_usage if u["estimated"]),
            "p50_ms": statistics.median(latency) if latency else None,
            "p95_ms": latency[math.ceil(0.95 * len(latency)) - 1] if latency else None,
        },
        "method": "Sequential synthetic cases; split fixed before tuning. Main runs count SDK runs, not HTTP tool turns. "
        "threshold replays a 0.5 gate using the current prompt/provider, not historical dev. "
        "decision mode diagnoses p>=0.5 labels only, not deployed routing quality. "
        "No source fetch, event enrichment or task correctness measured; main gateway dollars are estimates.",
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("decision", "gate", "main-only", "threshold"), default="decision")
    parser.add_argument("--split", choices=("calibration", "acceptance", "all"), default="acceptance")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit phải >= 1")
    result = asyncio.run(evaluate_cases(args.mode, args.split, args.limit))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
