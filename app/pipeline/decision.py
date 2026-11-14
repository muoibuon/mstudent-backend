"""AI lọc dữ liệu: Google Gemini Decision 1 (Decisions API) quyết định một thông báo có đáng chú ý không và thuộc loại nào.

Đây là model quyết định tập đóng: chỉ trả xác suất cho câu hỏi có/không và lựa chọn trong danh sách cho trước, không sinh
chữ → nội dung thông báo (dữ liệu không tin cậy) không thể khiến nó "làm theo chỉ dẫn" hay trả ra thứ gì ngoài nhãn.
Các bước sau (trích việc, chi tiết sự kiện, trả lời người dùng) do model trả lời (OpenAI) đảm nhận.

Lỗi mạng / hết hạn mức / nội dung bị chặn → ném lỗi; bên gọi (llm_agents.llm_triage) lùi về model trả lời rồi về bộ luật.
Khoá GEMINI_API_KEY chỉ nằm ở máy chủ, gửi qua header, không bao giờ ghi vào log hay phản hồi.
"""

from __future__ import annotations

import logging
import time

import httpx

from .. import budget, config, repo
from ..models import Category, Message, TriageOut

log = logging.getLogger("mstudent")
URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
AGENT = "Triage (Gemini Decision)"
MAX_INPUT_CHARS = 9000
_transport: httpx.AsyncBaseTransport | None = None  # test gán MockTransport

CATEGORY_CRITERIA = {
    "deadline": "Có bài tập, báo cáo, đồ án, hồ sơ phải NỘP trước một thời hạn.",
    "exam": "Lịch thi, kiểm tra, bảo vệ, vấn đáp.",
    "class_change": "Nghỉ học, học bù, đổi phòng, đổi giờ, đổi lịch học.",
    "event": "Sự kiện, hội thảo, seminar, workshop, talkshow, cuộc thi, ngày hội do trường/khoa/CLB tổ chức.",
    "admin": "Thủ tục hành chính: học phí, đăng ký học phần, học bổng, giấy tờ, bảo hiểm.",
    "other": "Không thuộc các loại trên.",
}
CATEGORY_VI = {
    "deadline": "hạn nộp",
    "exam": "thi",
    "class_change": "đổi lịch",
    "event": "sự kiện",
    "admin": "thủ tục",
    "other": "khác",
}
QUESTIONS = {
    "relevant": {
        "type": "noul",
        "instructions": (
            "Đây là một thông báo gửi tới sinh viên đại học Việt Nam (email, LMS hoặc nhóm Zalo lớp). Sinh viên có cần "
            "LÀM một việc hoặc GHI NHỚ một mốc thời gian vì thông báo này không (nộp bài, thi, đổi lịch học, đăng ký, "
            "đóng học phí, sự kiện của trường)? Quảng cáo, chuyện phiếm, lời chào, tin không liên quan học tập → không."
        ),
    },
    "category": {
        "type": "choice",
        "instructions": "Thông báo này thuộc loại nào?",
        "criteria": CATEGORY_CRITERIA,
    },
}


def _input(msg: Message) -> str:
    text = f"Người gửi: {msg.sender}\nTiêu đề: {msg.subject}\n---\n{msg.body}"
    return text[:MAX_INPUT_CHARS]


async def decide_triage(msg: Message, user_id: int | None = None) -> TriageOut:
    """Một lượt gọi Decisions API cho cả hai câu hỏi. Ghi token vào chi phí trong ngày (giá riêng của model lọc)."""
    payload = {"model": config.decision_model(), "input": _input(msg), "questions": QUESTIONS}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.decision_timeout_s(), transport=_transport) as c:
            r = await c.post(URL, json=payload, headers={"x-goog-api-key": config.gemini_api_key()})
        if r.status_code != 200:
            raise RuntimeError(f"Decisions API trả {r.status_code}")
        data = r.json()
        answers = data["answers"]
        p = float(answers["relevant"]["noul"])
        choice = str(answers["category"]["choice"])
        if not 0.0 <= p <= 1.0 or choice not in CATEGORY_CRITERIA:
            raise ValueError("câu trả lời ngoài tập cho phép")
    except Exception:
        _record(user_id, budget.estimate_tokens(payload), started)  # ước tính: có thể đã bị tính tiền
        raise
    usage = data.get("usage") or {}
    _record(user_id, int(usage.get("total_input_tokens") or budget.estimate_tokens(payload)), started)
    relevant = p >= config.decision_min_relevant()
    verdict = "cần chú ý" if relevant else "bỏ qua"
    return TriageOut(
        relevant=relevant,
        category=Category(choice),
        reason=f"Gemini Decision: {verdict} ({p:.0%}), loại {CATEGORY_VI[choice]}",
    )


def _record(user_id: int | None, input_tokens: int, started: float) -> None:
    try:
        cost = (
            input_tokens * config.decision_price_in_per_m() / 1_000_000
        )  # model lọc không tính token đầu ra
        repo.record_llm_usage(
            user_id, AGENT, input_tokens, 0, cost, round((time.perf_counter() - started) * 1000)
        )
    except Exception as e:
        log.warning("Không ghi được chi phí model lọc: %s", type(e).__name__)
