"""Chấm điểm pipeline trên eval/cases.json.

    python -m eval.run_eval            # chế độ hiện tại (llm nếu có OPENAI_API_KEY)
    MSTUDENT_OFFLINE=1 python -m eval.run_eval   # baseline luật

Dùng số liệu này khi pitch: "LLM đạt X% so với baseline Y%".
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("MSTUDENT_NOW", "2026-11-10T08:00:00+07:00")

from app import config  # noqa: E402
from app.models import Message, Source  # noqa: E402
from app.pipeline import rules  # noqa: E402

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))


async def run_one(m: Message):
    if config.llm_enabled():
        from app.pipeline import llm_agents

        tri = await llm_agents.llm_triage(m)
        ext = await llm_agents.llm_extract(m) if tri.relevant else None
    else:
        tri = rules.triage(m)
        ext = rules.extract(m, tri.category) if tri.relevant else None
    return tri, (ext.tasks if ext else [])


async def main():
    mode = "llm" if config.llm_enabled() else "offline"
    score = {"relevant": [0, 0], "category": [0, 0], "due": [0, 0], "course": [0, 0]}
    for i, c in enumerate(CASES, 1):
        m = Message(
            source=Source.manual,
            subject=c.get("subject", ""),
            body=c["body"],
            received_at=config.now().isoformat(),
        )
        tri, tasks = await run_one(m)
        exp, fails = c["expect"], []
        score["relevant"][1] += 1
        if tri.relevant == exp["relevant"]:
            score["relevant"][0] += 1
        else:
            fails.append(f"relevant={tri.relevant}")
        if exp["relevant"]:
            score["category"][1] += 1
            if tri.category.value == exp["category"]:
                score["category"][0] += 1
            else:
                fails.append(f"category={tri.category.value}")
            dues = [t.due_at or "" for t in tasks]
            if "due" in exp:
                score["due"][1] += 1
                if any(d.startswith(exp["due"]) for d in dues):
                    score["due"][0] += 1
                else:
                    fails.append(f"due={dues}")
            if "course" in exp:
                score["course"][1] += 1
                if any((t.course or "") == exp["course"] for t in tasks):
                    score["course"][0] += 1
                else:
                    fails.append(f"course={[t.course for t in tasks]}")
        print(f"{'✓' if not fails else '✗'} #{i:02d} {c['body'][:55]:<55} {' '.join(fails)}")
    print(f"\nChế độ: {mode}")
    for k, (ok, n) in score.items():
        print(f"  {k:<9} {ok}/{n} = {ok / n:.0%}" if n else f"  {k:<9} -")


if __name__ == "__main__":
    asyncio.run(main())
