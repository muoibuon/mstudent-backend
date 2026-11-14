"""Orchestrator: Message → Triage → Extractor → Planner → Store, theo từng người dùng.

Chế độ 'llm' dùng OpenAI Agents SDK; nếu lỗi hoặc không có key thì tự rơi về 'offline' (luật).
Mỗi lần chạy ghi lại trace từng bước để UI hiển thị.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime

from .. import budget, config, repo
from ..models import Category, IngestResult, Message, Priority, Source, Task
from . import planner, rules

log = logging.getLogger("mstudent")
WEEKDAY_VI = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def _msg_id(msg: Message) -> str:
    if msg.id:
        return msg.id
    # Cùng nội dung nhưng khác ngày nhận là tin khác ("mai kiểm tra" hôm nay ≠ tuần sau).
    raw = f"{msg.source.value}|{msg.sender}|{msg.subject}|{msg.body}|{(msg.received_at or '')[:10]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Tracer:
    """Ghi lại output/thời gian của từng agent."""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def add(self, agent: str, kind: str, started: float, output=None, error: str | None = None) -> None:
        step = {"agent": agent, "kind": kind, "ms": round((time.perf_counter() - started) * 1000, 1)}
        if output is not None:
            step["output"] = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        if error:
            step["error"] = error
        self.steps.append(step)


def _short_error(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:160]}"


async def ingest(user_id: int, msg: Message) -> IngestResult:
    received = msg.received_at or config.now().isoformat()
    msg = msg.model_copy(update={"received_at": received})
    msg = msg.model_copy(update={"id": _msg_id(msg)})

    seen = repo.get_message(user_id, msg.id)
    if seen:  # đã xử lý → không gọi lại LLM (tiết kiệm chi phí khi quét hộp thư nhiều lần)
        return IngestResult(
            message_id=msg.id,
            relevant=bool(seen["relevant"]),
            category=Category(seen["category"]),
            reason="Tin này đã được xử lý trước đó",
            mode="cache",
            duplicate=True,
        )

    tr = Tracer()
    mode = "offline"
    tri = ext = None
    if budget.llm_allowed(user_id):
        from . import llm_agents

        t0 = time.perf_counter()
        try:
            tri = await llm_agents.llm_triage(msg, user_id)
            tr.add("Triage", "llm", t0, tri)
            if tri.relevant:
                t0 = time.perf_counter()
                ext = await llm_agents.llm_extract(msg, user_id)
                tr.add("Extractor", "llm", t0, ext)
            mode = "llm"
        except Exception as e:  # mạng/credit/model lỗi → không làm hỏng luồng
            log.warning("LLM lỗi, chuyển sang offline: %s", e)
            tr.add("LLM", "llm", t0, error=f"{_short_error(e)} → chuyển sang luật")
            tri = ext = None
    if tri is None:
        t0 = time.perf_counter()
        tri = rules.triage(msg)
        tr.add("Triage", "rules", t0, tri)
        if tri.relevant:
            t0 = time.perf_counter()
            ext = rules.extract(msg, tri.category)
            tr.add("Extractor", "rules", t0, ext)

    repo.save_message(user_id, msg, tri.relevant, tri.category, tri.reason[:300])
    created: list[Task] = []
    updated: list[Task] = []
    # 003: tin được phân loại là sự kiện nhưng Extractor chỉ trả việc "đăng ký …" (deadline) → vẫn phải thành lời mời.
    is_event = tri.relevant and tri.category == Category.event and ext and ext.tasks
    if is_event and not any(d.category == Category.event for d in ext.tasks):
        ext.tasks[0] = ext.tasks[0].model_copy(update={"category": Category.event})
    if tri.relevant and ext and ext.tasks:
        t0 = time.perf_counter()
        try:
            ref = datetime.fromisoformat(received)
        except ValueError:
            ref = config.now()
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=config.TZ)
        created, updated = planner.plan(
            user_id, ext.tasks, source=msg.source.value, message_id=msg.id, ref=ref
        )
        tr.add(
            "Planner",
            "python",
            t0,
            {
                "created": [{"id": t.id, "title": t.title, "priority": t.priority.value} for t in created],
                "updated": [{"id": t.id, "title": t.title, "due_at": t.due_at} for t in updated],
            },
        )
    # 003: việc sự kiện mới → lời mời Tham gia / Không (chi tiết, form đăng ký, mức phù hợp với ngành).
    for i, t in enumerate(created):
        if t.category == Category.event and t.rsvp is None:
            from . import events

            t0 = time.perf_counter()
            try:
                created[i], kind = await events.enrich_event(user_id, t, msg)
                tr.add(
                    "EventDetails",
                    kind,
                    t0,
                    {
                        "id": t.id,
                        "rsvp": created[i].rsvp,
                        "fit": created[i].fit_level,
                        "fit_mode": created[i].fit_mode,
                    },
                )
            except Exception as e:  # lỗi làm giàu không được làm mất việc
                log.warning("Không gắn được chi tiết sự kiện: %s", type(e).__name__)
                tr.add("EventDetails", "python", t0, error=_short_error(e))
    summary = (msg.subject or msg.body).strip().replace("\n", " ")[:90]
    repo.save_trace(user_id, msg.id, mode, f"[{msg.source.value}] {summary}", tr.steps)
    return IngestResult(
        message_id=msg.id,
        relevant=tri.relevant,
        category=tri.category,
        reason=tri.reason,
        created=created,
        updated=updated,
        mode=mode,
        trace=tr.steps,
    )


def digest_text(tasks: list[Task], ref: datetime) -> str:
    """Bản tin không cần LLM: nhóm theo ngày trong 7 ngày tới."""
    upcoming = [
        t
        for t in tasks
        if t.due_at and 0 <= (datetime.fromisoformat(t.due_at) - ref).total_seconds() < 7 * 86400
    ]
    if not upcoming:
        return "Tuần này chưa có việc nào có hạn. 🎉"
    urgent = sum(1 for t in upcoming if t.priority == Priority.high)
    lines = [f"Bạn có {len(upcoming)} việc trong 7 ngày tới, {urgent} việc gấp."]
    by_day: dict[str, list[Task]] = defaultdict(list)
    for t in upcoming:
        d = datetime.fromisoformat(t.due_at)
        by_day[f"{WEEKDAY_VI[d.weekday()]} {d:%d/%m}"].append(t)
    for day, items in by_day.items():
        lines.append(f"\n{day}")
        for t in items:
            mark = "⚠️ " if t.priority == Priority.high else "• "
            hhmm = datetime.fromisoformat(t.due_at).strftime("%H:%M")
            extra = " — ".join(x for x in [t.course, t.location] if x and x not in t.title)
            lines.append(f"{mark}{hhmm} — {t.title}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines)


async def digest(user_id: int) -> dict:
    ref = config.now()
    tasks = planner.live(repo.list_tasks(user_id, "open"), ref)
    if budget.llm_allowed(user_id):
        try:
            from . import llm_agents

            return {"mode": "llm", "text": await llm_agents.llm_digest(tasks, user_id)}
        except Exception as e:
            log.warning("Digest LLM lỗi: %s", e)
    return {"mode": "offline", "text": digest_text(tasks, ref)}


async def ai_selfcheck(user_id: int | None = None) -> dict:
    """Gọi thật một lượt Triage để biết AI có chạy trực tiếp được không (dùng trước giờ demo)."""
    from .. import agent_config

    model = agent_config.get()["model"]
    if not config.llm_enabled():
        why = "MSTUDENT_OFFLINE=1" if config.is_offline_forced() else "chưa có OPENAI_API_KEY trên server"
        return {"ok": False, "mode": "offline", "model": model, "error": f"AI đang tắt: {why}"}
    if budget.exhausted():
        return {
            "ok": False,
            "mode": "offline",
            "model": model,
            "error": "AI tạm dừng: đã chạm trần chi phí LLM hôm nay, đang chạy bằng bộ luật",
        }
    if budget.user_exhausted(user_id):
        return {
            "ok": False,
            "mode": "offline",
            "model": model,
            "error": "Bạn đã dùng hết hạn mức AI hôm nay, đang chạy bằng bộ luật tới hết ngày",
        }
    from . import llm_agents

    sample = Message(
        source=Source.manual,
        body="Các em nộp bài tập tuần 9 trước 23h59 thứ 6 tuần này nhé.",
        received_at=config.now().isoformat(),
    )
    t0 = time.perf_counter()
    try:
        tri = await llm_agents.llm_triage(sample, user_id)
    except Exception as e:
        return {"ok": False, "mode": "llm", "model": model, "error": _short_error(e)}
    return {
        "ok": bool(tri.relevant),
        "mode": "llm",
        "model": model,
        "filter_model": config.decision_model() if config.decision_enabled() else model,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
        "sample": tri.model_dump(mode="json"),
    }
