"""Các agent LLM dựng bằng OpenAI Agents SDK (`pip install openai-agents`).

Prompt và model đọc từ agent_config mỗi lần gọi, nên sửa trên UI là có hiệu lực ngay.
Chỉ được import khi config.llm_enabled() là True.
"""

from __future__ import annotations

import json

from agents import Agent, Runner

from .. import agent_config
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


async def llm_triage(msg: Message) -> TriageOut:
    res = await Runner.run(_agent("Triage", "triage_prompt", TriageOut), render(msg))
    return res.final_output


async def llm_extract(msg: Message) -> ExtractionOut:
    res = await Runner.run(_agent("Extractor", "extract_prompt", ExtractionOut), render(msg))
    return res.final_output


async def llm_digest(tasks: list[Task]) -> str:
    payload = json.dumps([t.model_dump(mode="json") for t in tasks], ensure_ascii=False)
    res = await Runner.run(
        _agent("Digest", "digest_prompt"), f"Bây giờ là {now().isoformat()}.\nTasks:\n{payload}"
    )
    return str(res.final_output)
