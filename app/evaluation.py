"""Chấm điểm pipeline trên eval/cases.json — dùng chung cho CLI và nút "Chạy eval" trên UI."""

from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path

from . import budget
from .models import Message, Source
from .pipeline import orchestrator, rules

CASES_PATH = Path(__file__).resolve().parent.parent / "eval" / "cases.json"


async def _run_one(m: Message, use_llm: bool, trace: orchestrator.Tracer):
    if use_llm:
        tri, ext, _ = await orchestrator.classify(None, m, trace)
    else:
        tri = rules.triage(m)
        ext = rules.extract(m, tri.category) if tri.relevant else None
    return tri, (ext.tasks if ext else [])


async def evaluate(use_llm: bool | None = None) -> dict:
    use_llm = budget.llm_allowed() if use_llm is None else use_llm
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    ref = "2026-11-10T08:00:00+07:00"  # mốc cố định mà cases.json được viết theo
    score = {"relevant": [0, 0], "category": [0, 0], "due": [0, 0], "course": [0, 0]}
    rows = []
    timings, usage_rows, routes = [], [], {}
    for c in cases:
        m = Message(source=Source.manual, subject=c.get("subject", ""), body=c["body"], received_at=ref)
        trace = orchestrator.Tracer()
        started = time.perf_counter()
        exp = c["expect"]
        score["relevant"][1] += 1
        if exp["relevant"]:
            score["category"][1] += 1
            for key in ("due", "course"):
                if key in exp:
                    score[key][1] += 1
        try:
            with budget.capture_usage() as usage:
                tri, tasks = await _run_one(m, use_llm, trace)
        except Exception as e:
            rows.append({"body": c["body"], "ok": False, "fails": [f"lỗi: {type(e).__name__}"], "got": {}})
            continue
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            timings.append(elapsed)
            usage_rows.extend(usage)
            route = next(
                (s["output"]["route"] for s in trace.steps if s.get("output", {}).get("route")),
                "fallback" if use_llm else "offline",
            )
            routes[route] = routes.get(route, 0) + 1
        exp, fails = c["expect"], []
        score["relevant"][0] += tri.relevant == exp["relevant"]
        if tri.relevant != exp["relevant"]:
            fails.append(f"relevant={tri.relevant}")
        if exp["relevant"]:
            if tri.category.value == exp["category"]:
                score["category"][0] += 1
            else:
                fails.append(f"category={tri.category.value} (cần {exp['category']})")
            dues = [t.due_at or "" for t in tasks]
            if "due" in exp:
                if any(d.startswith(exp["due"]) for d in dues):
                    score["due"][0] += 1
                else:
                    fails.append(f"due={dues or '∅'} (cần {exp['due']})")
            if "course" in exp:
                if any((t.course or "") == exp["course"] for t in tasks):
                    score["course"][0] += 1
                else:
                    fails.append(f"course={[t.course for t in tasks]} (cần {exp['course']})")
        rows.append(
            {
                "body": c["body"],
                "ok": not fails,
                "fails": fails,
                "route": route,
                "ms": elapsed,
                "got": {
                    "relevant": tri.relevant,
                    "category": tri.category.value,
                    "due": [t.due_at for t in tasks],
                },
            }
        )
    return {
        "mode": "llm" if use_llm else "offline",
        "scores": {
            k: {"ok": ok, "n": n, "pct": round(100 * ok / n) if n else None} for k, (ok, n) in score.items()
        },
        "cases": rows,
        "metrics": {
            "routes": routes,
            "main_calls": sum(r["agent"] != "Decision" for r in usage_rows),
            "decision_calls": sum(r["agent"] == "Decision" for r in usage_rows),
            "input_tokens": sum(r["input_tokens"] for r in usage_rows),
            "output_tokens": sum(r["output_tokens"] for r in usage_rows),
            "estimated_cost_usd": sum(r["cost_usd"] for r in usage_rows),
            "cost_note": "Chi phí LLM chính là ước tính theo giá cấu hình, không phải hóa đơn gateway",
            "p50_ms": statistics.median(timings) if timings else None,
            "p95_ms": sorted(timings)[math.ceil(len(timings) * 0.95) - 1] if timings else None,
        },
    }
