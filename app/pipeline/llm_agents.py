"""Các agent LLM dựng bằng OpenAI Agents SDK (`pip install openai-agents`).

Prompt và model đọc từ agent_config mỗi lần gọi, nên sửa trên UI là có hiệu lực ngay.
Chỉ được import khi config.llm_enabled() là True.
Mọi lượt gọi đi qua run_llm(): có thời hạn chờ (timeout) và được tính vào trần chi phí theo ngày.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

from agents import Agent, Runner

from .. import agent_config, budget, config
from ..config import now
from ..models import ExtractionOut, Message, Task, TriageOut


def _agent(name: str, prompt_key: str, output_type=None) -> Agent:
    cfg = agent_config.get()
    return Agent(
        name=name,
        instructions=cfg[prompt_key] + agent_config.GUARD,
        output_type=output_type,
        model=cfg["model"],
    )


def _clean(text: str) -> str:
    """Không cho nội dung thông báo tự đóng thẻ dữ liệu."""
    return text.replace("</thong_bao>", "</thong_bao_>").replace("<thong_bao>", "<thong_bao_>")


_WRAPPER_TAG = re.compile(r"<\s*/?\s*thong_bao_?\s*>", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Đầu ra chữ của LLM (bản tin, trả lời chat): bỏ thẻ bọc dữ liệu nếu model chép lại."""
    return _WRAPPER_TAG.sub("", text).strip()


def render(msg: Message) -> str:
    return (
        f"Thời điểm nhận: {msg.received_at or now().isoformat()}\n"
        f"Nguồn: {msg.source.value}\n"
        "<thong_bao>\n"
        f"Người gửi: {_clean(msg.sender)}\n"
        f"Tiêu đề: {_clean(msg.subject)}\n"
        f"---\n{_clean(msg.body)}\n"
        "</thong_bao>"
    )


async def run_llm(agent: Agent, payload, *, user_id: int | None, **kwargs):
    """Mọi lượt gọi LLM đi qua đây: có thời hạn chờ và được ghi vào chi phí trong ngày."""
    started = time.perf_counter()
    try:
        res = await asyncio.wait_for(Runner.run(agent, payload, **kwargs), timeout=config.llm_timeout_s())
    except Exception:
        # Quá hạn/lỗi giữa chừng: OpenAI có thể đã tính tiền → vẫn tính vào trần (ước tính), rồi để bên gọi lùi về luật.
        budget.record_failure(
            user_id, agent.name, budget.estimate_tokens(agent.instructions or "", payload), started
        )
        raise
    budget.record(user_id, agent.name, res, started)
    return res


async def llm_triage(msg: Message, user_id: int | None = None) -> TriageOut:
    res = await run_llm(_agent("Triage", "triage_prompt", TriageOut), render(msg), user_id=user_id)
    return res.final_output


async def llm_extract(msg: Message, user_id: int | None = None) -> ExtractionOut:
    res = await run_llm(_agent("Extractor", "extract_prompt", ExtractionOut), render(msg), user_id=user_id)
    return res.final_output


async def llm_digest(tasks: list[Task], user_id: int | None = None) -> str:
    payload = json.dumps([t.model_dump(mode="json") for t in tasks], ensure_ascii=False)
    res = await run_llm(
        _agent("Digest", "digest_prompt"),
        f"Bây giờ là {now().isoformat()}.\nTasks:\n{payload}",
        user_id=user_id,
    )
    return clean_text(str(res.final_output))
