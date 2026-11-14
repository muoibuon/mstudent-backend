"""Chấm điểm pipeline trên eval/cases.json — dùng chung cho CLI và nút "Chạy eval" trên UI.

Đi qua đúng hàm điều phối của orchestrator (004): báo thêm tuyến của AI quyết định, số lượt GPT / AI quyết định, thời
gian trung vị mỗi ca. Ca có `existing` (việc có sẵn) chạy trong một tài khoản tạm (xoá ngay sau đó) để chấm "cập nhật
đúng việc cũ" (`expect.updates` = tên việc phải được cập nhật).
"""

from __future__ import annotations

import json
import secrets
import statistics
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from . import budget, config, repo
from .models import Message, Source
from .pipeline import orchestrator, rules

CASES_PATH = Path(__file__).resolve().parent.parent / "eval" / "cases.json"
REF = "2026-11-10T08:00:00+07:00"  # mốc cố định mà cases.json được viết theo
ROUTES = ("stop", "direct", "review", "fallback", "none")


async def _classify(m: Message, use_llm: bool) -> tuple[bool, str, list, str]:
    if use_llm:
        tr = orchestrator.Tracer()
        tri, ext, _mode, _ = await orchestrator.classify(None, m, tr)
        route = next((s["output"].get("route", "none") for s in tr.steps if s["agent"] == "Decision"), "none")
        return tri.relevant, tri.category.value, (ext.tasks if ext else []), route
    tri = rules.triage(m)
    ext = rules.extract(m, tri.category) if tri.relevant else None
    return tri.relevant, tri.category.value, (ext.tasks if ext else []), "none"


async def _with_existing(c: dict, m: Message, use_llm: bool, temp_ids: list[int]):
    """Ca "thay đổi thông báo cũ": tài khoản tạm + việc có sẵn → ingest thật → xem việc nào được cập nhật."""
    user = repo.create_user(f"eval-{secrets.token_hex(6)}@eval.invalid", "eval", None)
    uid = user["id"]
    temp_ids.append(uid)
    for t in c["existing"][:30]:
        repo.insert_task(uid, {"priority": "medium", "source": "manual", "message_id": "eval-existing", **t})
    if use_llm:
        out = await orchestrator.ingest(uid, m)
    else:  # bộ luật + planner, không đụng cấu hình toàn cục (máy chủ đang phục vụ người khác)
        from .pipeline import planner

        tri = rules.triage(m)
        ext = rules.extract(m, tri.category) if tri.relevant else None
        created, updated = (
            planner.plan(uid, ext.tasks, source="manual", message_id="eval", ref=datetime.fromisoformat(REF))
            if ext and ext.tasks
            else ([], [])
        )
        out = SimpleNamespace(
            relevant=tri.relevant, category=tri.category, created=created, updated=updated, trace=[]
        )
    tasks = [*out.created, *out.updated]
    route = next((s["output"].get("route", "none") for s in out.trace if s["agent"] == "Decision"), "none")
    return out.relevant, out.category.value, tasks, route, [t.title for t in out.updated], len(out.created)


async def evaluate(use_llm: bool | None = None) -> dict:
    use_llm = budget.llm_allowed() if use_llm is None else use_llm
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    score = {k: [0, 0] for k in ("relevant", "category", "due", "course", "update")}
    rows, temp_ids, times = [], [], []
    routes = dict.fromkeys(ROUTES, 0)
    gpt_by_kind = {"relevant": [], "noise": []}
    started_at = config.utcnow().isoformat()
    try:
        for c in cases:
            m = Message(source=Source.manual, subject=c.get("subject", ""), body=c["body"], received_at=REF)
            since = config.utcnow().isoformat()
            t0 = time.perf_counter()
            updated_titles, n_created = None, 0
            try:
                if c.get("existing"):
                    relevant, category, tasks, route, updated_titles, n_created = await _with_existing(
                        c, m, use_llm, temp_ids
                    )
                else:
                    relevant, category, tasks, route = await _classify(m, use_llm)
            except Exception as e:
                rows.append({"body": c["body"], "ok": False, "fails": [f"lỗi: {e}"], "got": {}})
                continue
            times.append((time.perf_counter() - t0) * 1000)
            routes[route] += 1
            calls = repo.llm_calls_since(since, tuple(temp_ids))
            gpt = sum(n for a, n in calls.items() if a != "Decision")
            exp, fails = c["expect"], []
            gpt_by_kind["relevant" if exp["relevant"] else "noise"].append(gpt)
            score["relevant"][1] += 1
            score["relevant"][0] += relevant == exp["relevant"]
            if relevant != exp["relevant"]:
                fails.append(f"relevant={relevant}")
            if exp["relevant"]:
                if "category" in exp:
                    score["category"][1] += 1
                    if category == exp["category"]:
                        score["category"][0] += 1
                    else:
                        fails.append(f"category={category} (cần {exp['category']})")
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
            if "updates" in exp:
                score["update"][1] += 1
                if exp["updates"] in (updated_titles or []) and n_created == 0:
                    score["update"][0] += 1
                else:
                    fails.append(
                        f"cập nhật={updated_titles or '∅'}, tạo mới={n_created} (cần cập nhật {exp['updates']})"
                    )
            rows.append(
                {
                    "body": c["body"],
                    "ok": not fails,
                    "fails": fails,
                    "route": route,
                    "gpt_calls": gpt,
                    "ms": round(times[-1]),
                    "got": {"relevant": relevant, "category": category, "due": [t.due_at for t in tasks]},
                }
            )
        calls = repo.llm_calls_since(started_at, tuple(temp_ids))
    finally:
        for uid in temp_ids:
            repo.delete_user(uid)

    def avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    per_rel, per_noise = avg(gpt_by_kind["relevant"]), avg(gpt_by_kind["noise"])
    return {
        "mode": "llm" if use_llm else "offline",
        "decision": bool(use_llm and config.decision_enabled()),
        "scores": {
            k: {"ok": ok, "n": n, "pct": round(100 * ok / n) if n else None} for k, (ok, n) in score.items()
        },
        "routes": {k: v for k, v in routes.items() if v},
        "gpt_calls": sum(n for a, n in calls.items() if a != "Decision"),
        "decision_calls": calls.get("Decision", 0),
        "p50_ms": round(statistics.median(times)) if times else None,
        "gpt_per_relevant": per_rel,
        "gpt_per_noise": per_noise,
        # SC-003: số lượt GPT mỗi tin ước tính cho hộp thư 30% tin học vụ / 70% tin nhiễu
        "gpt_per_msg_mix30": round(0.3 * per_rel + 0.7 * per_noise, 2)
        if None not in (per_rel, per_noise)
        else None,
        "ran_at": datetime.now(config.TZ).isoformat(timespec="seconds"),
        "cases": rows,
    }
