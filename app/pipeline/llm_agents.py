"""Các agent LLM dựng bằng OpenAI Agents SDK (`pip install openai-agents`).

Chỉ được import khi config.llm_enabled() là True.
"""

from __future__ import annotations

import json

from agents import Agent, Runner

from ..config import OPENAI_MODEL, now
from ..models import ExtractionOut, Message, Task, TriageOut

TRIAGE_PROMPT = """Bạn là trợ lý học vụ cho sinh viên đại học Việt Nam.
Đọc một thông báo (email, LMS hoặc tin nhắn nhóm Zalo lớp) và quyết định:
- relevant: true nếu sinh viên cần LÀM gì đó hoặc GHI NHỚ một mốc thời gian
  (nộp bài, thi, đổi lịch học, đăng ký, đóng học phí, sự kiện có hạn đăng ký).
  false với quảng cáo, chuyện phiếm, lời chào, thông báo không liên quan.
- category: deadline | exam | class_change | event | admin | other
- reason: một câu ngắn tiếng Việt.
"""

EXTRACT_PROMPT = """Bạn trích xuất VIỆC CẦN LÀM từ thông báo học vụ.
Quy tắc:
- Một thông báo có thể chứa 0..n việc; mỗi mốc thời gian riêng là một việc riêng.
- due_at: ISO 8601 có múi giờ +07:00. Suy ra ngày tương đối ("thứ 6 tuần này", "ngày mai")
  từ thời điểm nhận tin. Hạn nộp không ghi giờ → 23:59. Không có mốc thời gian → null.
- course: mã môn (vd. CSE3032) nếu có, nếu không thì tên môn, nếu không có thì null.
- title ngắn gọn, bắt đầu bằng động từ khi có thể ("Nộp báo cáo Lab 3").
- Không bịa thông tin không có trong tin nhắn.
"""

DIGEST_PROMPT = """Bạn viết bản tin buổi sáng cho sinh viên, tiếng Việt, thân thiện, ngắn gọn.
Đầu vào là danh sách task JSON. Viết:
1. Một câu tổng quan (bao nhiêu việc gấp hôm nay/tuần này).
2. Danh sách theo ngày, việc gấp đánh dấu ⚠️, mỗi dòng: giờ — việc — môn — địa điểm.
3. Một gợi ý ưu tiên cho hôm nay.
Tối đa 150 từ. Không bịa task.
"""

triage_agent = Agent(name="Triage", instructions=TRIAGE_PROMPT, output_type=TriageOut, model=OPENAI_MODEL)
extractor_agent = Agent(
    name="Extractor", instructions=EXTRACT_PROMPT, output_type=ExtractionOut, model=OPENAI_MODEL
)
digest_agent = Agent(name="Digest", instructions=DIGEST_PROMPT, model=OPENAI_MODEL)


def _render(msg: Message) -> str:
    return (
        f"Thời điểm nhận: {msg.received_at or now().isoformat()}\n"
        f"Nguồn: {msg.source.value}\nNgười gửi: {msg.sender}\n"
        f"Tiêu đề: {msg.subject}\n---\n{msg.body}"
    )


async def llm_triage(msg: Message) -> TriageOut:
    res = await Runner.run(triage_agent, _render(msg))
    return res.final_output


async def llm_extract(msg: Message) -> ExtractionOut:
    res = await Runner.run(extractor_agent, _render(msg))
    return res.final_output


async def llm_digest(tasks: list[Task]) -> str:
    payload = json.dumps([t.model_dump(mode="json") for t in tasks], ensure_ascii=False)
    res = await Runner.run(digest_agent, f"Bây giờ là {now().isoformat()}.\nTasks:\n{payload}")
    return str(res.final_output)
