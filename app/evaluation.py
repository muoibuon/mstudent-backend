"""Chấm điểm pipeline trên eval/cases.json — dùng chung cho CLI và nút "Chạy eval" trên UI."""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .models import Message, Source
from .pipeline import rules

CASES_PATH = Path(__file__).resolve().parent.parent / "eval" / "cases.json"


async def _run_one(m: Message, use_llm: bool):
    if use_llm:
        from .pipeline import llm_agents

        tri = await llm_agents.llm_triage(m)
        ext = await llm_agents.llm_extract(m) if tri.relevant else None
    else:
        tri = rules.triage(m)
        ext = rules.extract(m, tri.category) if tri.relevant else None
    return tri, (ext.tasks if ext else [])


async def evaluate(use_llm: bool | None = None) -> dict:
    use_llm = config.llm_enabled() if use_llm is None else use_llm
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    ref = "2026-11-10T08:00:00+07:00"  # mốc cố định mà cases.json được viết theo
    score = {"relevant": [0, 0], "category": [0, 0], "due": [0, 0], "course": [0, 0]}
    rows = []
    for c in cases:
        m = Message(source=Source.manual, subject=c.get("subject", ""), body=c["body"], received_at=ref)
        try:
            tri, tasks = await _run_one(m, use_llm)
        except Exception as e:
            rows.append({"body": c["body"], "ok": False, "fails": [f"lỗi: {e}"], "got": {}})
            continue
        exp, fails = c["expect"], []
        score["relevant"][1] += 1
        score["relevant"][0] += tri.relevant == exp["relevant"]
        if tri.relevant != exp["relevant"]:
            fails.append(f"relevant={tri.relevant}")
        if exp["relevant"]:
            score["category"][1] += 1
            if tri.category.value == exp["category"]:
                score["category"][0] += 1
            else:
                fails.append(f"category={tri.category.value} (cần {exp['category']})")
            dues = [t.due_at or "" for t in tasks]
            if "due" in exp:
                score["due"][1] += 1
                if any(d.startswith(exp["due"]) for d in dues):
                    score["due"][0] += 1
                else:
                    fails.append(f"due={dues or '∅'} (cần {exp['due']})")
            if "course" in exp:
                score["course"][1] += 1
                if any((t.course or "") == exp["course"] for t in tasks):
                    score["course"][0] += 1
                else:
                    fails.append(f"course={[t.course for t in tasks]} (cần {exp['course']})")
        rows.append(
            {
                "body": c["body"],
                "ok": not fails,
                "fails": fails,
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
    }
