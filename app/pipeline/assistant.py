"""Trợ lý chat: agent có tool, điều khiển toàn bộ hệ thống bằng ngôn ngữ tự nhiên.

- Chế độ LLM: OpenAI Agents SDK, agent tự chọn tool (list_tasks, add_notice, complete_task, get_digest).
- Chế độ offline: bộ định tuyến ý định bằng luật gọi đúng các tool đó.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime

from .. import config, store
from ..models import Category, ChatResponse, ChatTurn, Message, Priority, Source, ToolCall
from . import orchestrator, planner, rules

log = logging.getLogger("mstudent")

# ---------------- Tool dùng chung cho cả 2 chế độ ----------------


def _fmt_task(t) -> str:
    when = datetime.fromisoformat(t.due_at).strftime("%H:%M %d/%m") if t.due_at else "không hạn"
    mark = "⚠️ " if t.priority == Priority.high else ""
    return f"{mark}#{t.id} · {when} — {t.title}"


def tool_list_tasks(days: int | None = 7, category: str | None = None) -> str:
    ref = config.now()
    tasks = planner.live(store.list_tasks("open"), ref)
    if category:
        tasks = [t for t in tasks if t.category.value == category]
    if days:
        tasks = [
            t
            for t in tasks
            if t.due_at and (datetime.fromisoformat(t.due_at) - ref).total_seconds() < days * 86400
        ]
    if not tasks:
        return "Không có việc nào phù hợp."
    return "\n".join(_fmt_task(t) for t in tasks)


async def tool_add_notice(text: str) -> str:
    r = await orchestrator.ingest(Message(source=Source.manual, body=text))
    if not r.relevant:
        return f"Không tạo việc: {r.reason}"
    parts = [f"Đã tạo {_fmt_task(t)}" for t in r.created] + [f"Đã cập nhật {_fmt_task(t)}" for t in r.updated]
    return "\n".join(parts) or "Thông báo hợp lệ nhưng không tách được việc nào."


def tool_complete_task(task_id: int) -> str:
    t = store.get_task(task_id)
    if t is None:
        return f"Không tìm thấy việc #{task_id}."
    store.set_status(task_id, "done")
    return f"Đã đánh dấu xong #{task_id} — {t.title}"


async def tool_get_digest() -> str:
    return (await orchestrator.digest())["text"]


# ---------------- Chế độ LLM ----------------


async def _llm_chat(message: str, history: list[ChatTurn]) -> ChatResponse:
    from agents import Agent, Runner, function_tool
    from agents.items import ToolCallItem, ToolCallOutputItem

    from .. import agent_config

    @function_tool
    def list_tasks(days: int | None, category: str | None) -> str:
        """Liệt kê việc đang mở.

        Args:
            days: chỉ lấy việc có hạn trong N ngày tới (null = tất cả).
            category: deadline | exam | class_change | event | admin | other (null = tất cả).
        """
        return tool_list_tasks(days, category)

    @function_tool
    async def add_notice(text: str) -> str:
        """Đưa một thông báo mới qua pipeline Triage → Extractor → Planner để tạo/cập nhật việc.

        Args:
            text: nguyên văn thông báo.
        """
        return await tool_add_notice(text)

    @function_tool
    def complete_task(task_id: int) -> str:
        """Đánh dấu một việc đã xong.

        Args:
            task_id: id của việc (số sau dấu #).
        """
        return tool_complete_task(task_id)

    @function_tool
    async def get_digest() -> str:
        """Lấy bản tin tóm tắt các việc trong 7 ngày tới."""
        return await tool_get_digest()

    cfg = agent_config.get()
    agent = Agent(
        name="MStudent Assistant",
        instructions=f"{cfg['assistant_prompt']}\nBây giờ là {config.now().isoformat()}.",
        tools=[list_tasks, add_notice, complete_task, get_digest],
        model=cfg["model"],
    )
    items = [{"role": h.role, "content": h.content} for h in history[-10:]]
    items.append({"role": "user", "content": message})
    res = await Runner.run(agent, items, max_turns=8)

    calls: list[ToolCall] = []
    for it in res.new_items:
        if isinstance(it, ToolCallItem):
            raw = it.raw_item
            try:
                args = json.loads(getattr(raw, "arguments", "") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tool=getattr(raw, "name", "tool"), args=args))
        elif isinstance(it, ToolCallOutputItem) and calls:
            calls[-1].result = str(it.output)[:1500]
    return ChatResponse(reply=str(res.final_output), mode="llm", tool_calls=calls)


# ---------------- Chế độ offline ----------------

HELP = (
    "Mình có thể:\n"
    "• Xem việc: “tuần này có gì?”, “hôm nay”, “lịch thi”\n"
    "• Thêm thông báo: “thêm: thứ 6 tuần sau nộp đồ án OOP”\n"
    "• Đánh dấu xong: “xong 3”\n"
    "• Tóm tắt: “bản tin”"
)
QUESTION = ("?", "có gì", "những", "nào", "bao nhiêu", "xem", "liệt kê", "còn")


def _n(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower().strip()


async def _offline_chat(message: str) -> ChatResponse:
    t = _n(message)
    calls: list[ToolCall] = []

    async def call(name: str, fn, **kw):
        out = await fn(**kw) if name in ("add_notice", "get_digest") else fn(**kw)
        calls.append(ToolCall(tool=name, args=kw, result=out))
        return out

    if m := re.search(r"(?:xong|hoàn thành|done|đã làm)\D{0,12}#?(\d+)", t):
        reply = await call("complete_task", tool_complete_task, task_id=int(m.group(1)))
    elif any(k in t for k in ("bản tin", "tóm tắt", "digest", "tổng quan")):
        reply = await call("get_digest", tool_get_digest)
    elif m := re.match(
        r"^(?:thêm|nhắc|ghi lại|lưu)\s*(?:giúp|mình|tôi|em)?\s*[:\-]?\s*(.+)", message.strip(), re.I | re.S
    ):
        reply = await call("add_notice", tool_add_notice, text=m.group(1))
    elif not any(q in t for q in QUESTION) and rules.triage(Message(body=message)).relevant:
        reply = await call("add_notice", tool_add_notice, text=message)
    elif any(
        k in t for k in ("hôm nay", "mai", "tuần", "tháng", "việc", "deadline", "hạn", "lịch", "thi", "sắp")
    ):
        days = 1 if "hôm nay" in t else 2 if "mai" in t else 30 if "tháng" in t else 7
        if "tất cả" in t:
            days = None
        cat = None
        if re.search(r"\bthi\b|kiểm tra", t):
            cat = Category.exam.value
        elif any(k in t for k in ("deadline", "nộp", "hạn nộp")):
            cat = Category.deadline.value
        out = await call("list_tasks", tool_list_tasks, days=days, category=cat)
        label = {1: "hôm nay", 2: "đến hết ngày mai", 7: "7 ngày tới", 30: "30 ngày tới"}.get(days, "tất cả")
        reply = f"Việc {label}:\n{out}"
    else:
        reply = HELP
    return ChatResponse(reply=reply, mode="offline", tool_calls=calls)


async def chat(message: str, history: list[ChatTurn]) -> ChatResponse:
    if config.llm_enabled():
        try:
            return await _llm_chat(message, history)
        except Exception as e:
            log.warning("Chat LLM lỗi, chuyển offline: %s", e)
    return await _offline_chat(message)
