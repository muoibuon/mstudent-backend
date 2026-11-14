"""Chấm điểm pipeline trên eval/cases.json.

    python -m eval.run_eval                       # chế độ hiện tại (llm nếu có OPENAI_API_KEY)
    MSTUDENT_OFFLINE=1 python -m eval.run_eval    # baseline luật

Cũng chạy được từ tab "Cấu hình agent" trên UI.
"""

from __future__ import annotations

import asyncio

from app.evaluation import evaluate


async def main() -> None:
    r = await evaluate()
    for i, c in enumerate(r["cases"], 1):
        print(f"{'✓' if c['ok'] else '✗'} #{i:02d} {c['body'][:55]:<55} {' '.join(c['fails'])}")
    print(f"\nChế độ: {r['mode']}" + (" + AI quyết định" if r.get("decision") else ""))
    for k, s in r["scores"].items():
        print(f"  {k:<9} {s['ok']}/{s['n']} = {s['pct']}%" if s["n"] else f"  {k:<9} -")
    print(f"  tuyến     {r['routes']}")
    print(
        f"  lượt GPT  {r['gpt_calls']} · lượt AI quyết định {r['decision_calls']} · trung vị {r['p50_ms']} ms/ca"
    )
    print(
        f"  GPT/ca    học vụ {r['gpt_per_relevant']} · nhiễu {r['gpt_per_noise']}"
        f" · hỗn hợp 30/70 ≈ {r['gpt_per_msg_mix30']} lượt/tin"
    )


if __name__ == "__main__":
    asyncio.run(main())
