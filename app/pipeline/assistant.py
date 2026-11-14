"""Trợ lý chat: agent có tool, điều khiển dữ liệu CỦA CHÍNH người dùng bằng ngôn ngữ tự nhiên.

- Chế độ LLM: OpenAI Agents SDK, agent tự chọn tool (list_tasks, add_notice, complete_task, get_digest).
- Chế độ offline: bộ định tuyến ý định bằng luật gọi đúng các tool đó.

`user_id` được gắn sẵn vào tool ở phía server; model không thể truyền hay đổi nó.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from html import escape, unescape

from .. import budget, config, repo
from ..connectors import docs
from ..models import Category, ChatResponse, ChatTurn, Message, Priority, Source, ToolCall
from . import llm_agents, orchestrator, planner, rules, schedule_import

log = logging.getLogger("mstudent")

# ---------------- Tool dùng chung cho cả 2 chế độ ----------------


def _fmt_task(t) -> str:
    when = datetime.fromisoformat(t.due_at).strftime("%H:%M %d/%m") if t.due_at else "không hạn"
    mark = "⚠️ " if t.priority == Priority.high else ""
    return f"{mark}#{t.id} · {when} — {t.title}"


def tool_list_tasks(user_id: int, days: int | None = 7, category: str | None = None) -> str:
    ref = config.now()
    tasks = planner.live(repo.list_tasks(user_id, "open"), ref)
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
    return "\n".join(_fmt_task(t) for t in tasks[:40])


async def tool_add_notice(user_id: int, text: str) -> str:
    text = text.strip()[:8000]
    if not text:
        return "Thông báo trống."
    r = await orchestrator.ingest(user_id, Message(source=Source.manual, body=text))
    if r.duplicate:
        return "Thông báo này đã được ghi nhận trước đó."
    if not r.relevant:
        return f"Không tạo việc: {r.reason}"
    parts = [f"Đã tạo {_fmt_task(t)}" for t in r.created] + [f"Đã cập nhật {_fmt_task(t)}" for t in r.updated]
    return "\n".join(parts) or "Thông báo hợp lệ nhưng không tách được việc nào."


def tool_complete_task(user_id: int, task_id: int) -> str:
    t = repo.get_task(user_id, task_id)
    if t is None:
        return f"Không tìm thấy việc #{task_id}."
    repo.set_status(user_id, task_id, "done")
    return f"Đã đánh dấu xong #{task_id} — {t.title}"


async def tool_get_digest(user_id: int) -> str:
    return (await orchestrator.digest(user_id))["text"]


# ---------------- Chế độ LLM ----------------


async def _llm_chat(user_id: int, message: str, history: list[ChatTurn]) -> ChatResponse:
    from agents import function_tool
    from agents.items import ToolCallItem, ToolCallOutputItem

    @function_tool
    def list_tasks(days: int | None, category: str | None) -> str:
        """Liệt kê việc đang mở.

        Args:
            days: chỉ lấy việc có hạn trong N ngày tới (null = tất cả).
            category: deadline | exam | class_change | event | admin | other (null = tất cả).
        """
        return tool_list_tasks(user_id, days, category)

    @function_tool
    async def add_notice(text: str) -> str:
        """Đưa một thông báo mới qua pipeline Triage → Extractor → Planner để tạo/cập nhật việc.

        Args:
            text: nguyên văn thông báo.
        """
        return await tool_add_notice(user_id, text)

    @function_tool
    def complete_task(task_id: int) -> str:
        """Đánh dấu một việc đã xong.

        Args:
            task_id: id của việc (số sau dấu #).
        """
        return tool_complete_task(user_id, task_id)

    @function_tool
    async def get_digest() -> str:
        """Lấy bản tin tóm tắt các việc trong 7 ngày tới."""
        return await tool_get_digest(user_id)

    agent = llm_agents.build_agent(
        "MStudent Assistant",
        "assistant_prompt",
        tools=[list_tasks, add_notice, complete_task, get_digest],
        instruction_suffix=f"\nBây giờ là {config.now().isoformat()}.",
    )
    items = [{"role": h.role, "content": h.content} for h in history[-10:]]
    items.append({"role": "user", "content": message})
    res = await llm_agents.run_llm(agent, items, user_id=user_id, max_turns=8)

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
    return ChatResponse(reply=llm_agents.clean_text(str(res.final_output)), mode="llm", tool_calls=calls)


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


async def _offline_chat(user_id: int, message: str) -> ChatResponse:
    t = _n(message)
    calls: list[ToolCall] = []

    async def call(name: str, fn, **kw):
        out = fn(user_id, **kw)
        if hasattr(out, "__await__"):
            out = await out
        calls.append(ToolCall(tool=name, args=kw, result=out))
        return out

    if m := re.search(r"(?:xong|hoàn thành|done|đã làm)\D{0,12}#?(\d{1,9})", t):
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


async def chat(user_id: int, message: str, history: list[ChatTurn]) -> ChatResponse:
    if schedule_import.wants_schedule(message):
        for turn in reversed(history[-10:]):
            if turn.role != "user":
                continue
            match = re.search(r"<thong_bao>\s*Tệp: ([^\n]+)\n(.*?)\n</thong_bao>", turn.content, re.S)
            if match and match.group(1).lower().endswith((".csv", ".xlsx")):
                return _import_schedule(user_id, unescape(match.group(2)), unescape(match.group(1)))
    if budget.llm_allowed(user_id):
        try:
            return await _llm_chat(user_id, message, history)
        except Exception as e:
            log.warning("Chat LLM lỗi, chuyển offline: %s", type(e).__name__)
    return await _offline_chat(user_id, message)


def _import_schedule(user_id: int, text: str, filename: str) -> ChatResponse:
    created, skipped = schedule_import.add(user_id, text, filename)
    if created:
        first = min(t.due_at for t in created if t.due_at)
        last = max(t.due_at for t in created if t.due_at)
        reply = (
            f"Đã thêm {len(created)} buổi học vào Lịch, từ {datetime.fromisoformat(first):%d/%m} "
            f"đến {datetime.fromisoformat(last):%d/%m}."
        )
        if skipped:
            reply += f" Bỏ qua {skipped} buổi đã có."
    elif skipped:
        reply = f"Các buổi học trong 7 ngày tới đã có trong Lịch ({skipped} buổi); không tạo trùng."
    else:
        reply = (
            "Chưa tìm thấy buổi học sắp tới trong bảng. Tệp CSV cần có môn, ngày, giờ bắt đầu "
            "và 'Hàng tuần' nếu lịch lặp; những ngày đã qua mà không lặp sẽ được bỏ qua."
        )
    return ChatResponse(
        reply=reply,
        mode="offline",
        tool_calls=[ToolCall(tool="import_schedule", result=reply)],
    )


async def chat_with_file(
    user_id: int, question: str, document: docs.DocText, history: list[ChatTurn]
) -> ChatResponse:
    """Tài liệu là dữ liệu không tin cậy; chỉ câu hỏi ngoài thẻ là chỉ dẫn của người dùng."""
    prompt = (
        question.strip()
        or "Tóm tắt tệp này và các mốc thời gian quan trọng. Chưa tạo việc nếu mình chưa yêu cầu."
    )
    if document.kind in ("csv", "xlsx") and schedule_import.wants_schedule(prompt):
        response = _import_schedule(user_id, document.text, document.name)
        response.document_context = (
            f"{prompt}\n\n<thong_bao>\nTệp: {escape(document.name)[:120]}\n"
            f"{escape(docs.focus(document.text, limit=2700))[:2700]}\n</thong_bao>"
        )
        return response
    content = docs.focus(document.text, limit=2800)
    message = (
        f"{prompt}\n\n<thong_bao>\nTệp: {escape(document.name)[:120]}\n{escape(content)[:2700]}\n</thong_bao>"
    )
    if budget.llm_allowed(user_id):
        try:
            response = await _llm_chat(user_id, message, history)
            response.document_context = message
            return response
        except Exception as e:
            log.warning("Chat với tệp lỗi, chuyển offline: %s", e)
    if (
        question.strip()
        and not re.search(r"(?:đừng|không|chưa)\s+(?:tạo|thêm|ghi|lưu|nhắc)", prompt, re.I)
        and re.search(r"(?:tạo|thêm|ghi|lưu|nhắc).{0,20}(?:việc|hạn|deadline|thông báo)", prompt, re.I)
    ):
        result = await tool_add_notice(user_id, content)
        return ChatResponse(
            reply=f"Đã đọc {document.name}. {result}",
            mode="offline",
            tool_calls=[ToolCall(tool="add_notice", result=result)],
            document_context=message,
        )
    excerpt = docs.focus(document.text, limit=900)
    return ChatResponse(
        reply=f"Đã đọc {document.name}. AI đang không khả dụng; đây là phần nội dung trích được:\n{excerpt}",
        mode="offline",
        document_context=message,
    )
