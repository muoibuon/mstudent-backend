"""Trần chi phí LLM theo ngày: toàn hệ thống và từng người dùng.

- `llm_allowed(user_id)`: có được gọi LLM lúc này không (có khoá, không ép offline, chưa chạm trần chung hôm nay,
  và người này chưa chạm trần riêng). Trần riêng ngăn một người đốt hết trần chung của mọi người.
- `record()`: ghi token + chi phí của một lượt gọi xong; `record_failure()`: lượt lỗi/quá hạn vẫn có thể đã bị tính
  tiền nên ghi chi phí ước tính. Cả hai gửi cảnh báo khi chạm 80% và 100% trần chung.

Ngày tính theo giờ Việt Nam (`config.now()`). Chạm trần → pipeline chạy bộ luật và ghi rõ mode="offline".
Không bao giờ lưu hay gửi nội dung prompt/câu trả lời.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from . import config, repo

log = logging.getLogger("mstudent")
_usage: ContextVar[list | None] = ContextVar("llm_usage", default=None)


@contextmanager
def capture_usage():
    """Request-local counters for eval; concurrent users cannot contaminate them."""
    rows = []
    token = _usage.set(rows)
    try:
        yield rows
    finally:
        _usage.reset(token)


def record_usage(user_id, agent, tin, tout, cost, latency_ms, *, estimated=True):
    repo.record_llm_usage(user_id, agent, tin, tout, cost, latency_ms)
    rows = _usage.get()
    if rows is not None:
        rows.append(
            {
                "agent": agent,
                "input_tokens": tin,
                "output_tokens": tout,
                "cost_usd": cost,
                "estimated": estimated,
                "latency_ms": latency_ms,
            }
        )
    _maybe_alert()


def today() -> str:
    return config.now().date().isoformat()


def spent_today() -> float:
    return repo.llm_cost_on(today())


def exhausted() -> bool:
    return spent_today() >= config.llm_daily_usd()


def user_exhausted(user_id: int | None) -> bool:
    cap = config.llm_user_daily_usd()
    return user_id is not None and cap > 0 and repo.llm_cost_user_on(user_id, today()) >= cap


def llm_allowed(user_id: int | None = None) -> bool:
    """Dùng thay cho config.llm_enabled() ở mọi chỗ sắp gọi LLM."""
    return config.llm_enabled() and not exhausted() and not user_exhausted(user_id)


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * config.price_in_per_m() + output_tokens * config.price_out_per_m()) / 1_000_000


def _tokens(result) -> tuple[int, int]:
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def record(user_id: int | None, agent: str, result, started: float) -> None:
    """Ghi nhận một lượt gọi LLM đã xong. Không được làm hỏng luồng chính nếu ghi lỗi."""
    try:
        tin, tout = _tokens(result)
        record_usage(
            user_id, agent, tin, tout, cost_usd(tin, tout), round((time.perf_counter() - started) * 1000)
        )
    except (
        Exception
    ) as e:  # CSDL bận, v.v. — chi phí lượt này không được ghi, nhưng người dùng vẫn có kết quả
        log.warning("Không ghi được chi phí LLM: %s", type(e).__name__)


def estimate_tokens(*parts) -> int:
    """≈ 4 ký tự / token. Dùng khi không có số liệu usage thật (lượt gọi lỗi hoặc quá hạn)."""
    return (
        sum(len(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, default=str)) for p in parts)
        // 4
        + 1
    )


# Lượt lỗi: không biết model đã sinh bao nhiêu → giả định bằng số token đầu vào, tối thiểu 500 (ước tính bi quan).
def record_failure(user_id: int | None, agent: str, est_input_tokens: int, started: float) -> None:
    try:
        tin, tout = est_input_tokens, max(500, est_input_tokens)
        record_usage(
            user_id, agent, tin, tout, cost_usd(tin, tout), round((time.perf_counter() - started) * 1000)
        )
    except Exception as e:
        log.warning("Không ghi được chi phí LLM (lượt lỗi): %s", type(e).__name__)


def _maybe_alert() -> None:
    limit = config.llm_daily_usd()
    if limit <= 0:
        return
    day, spent = today(), spent_today()
    if spent >= limit:
        repo.mark_budget_alert(day, 80)  # không báo 80% muộn sau khi đã báo 100%
        if repo.mark_budget_alert(day, 100):
            _notify(
                f"⛔ MStudent: đã chạm trần chi phí LLM hôm nay ({spent:.2f}/{limit:.2f} USD). "
                f"AI chuyển sang bộ luật (offline) tới hết ngày {day}."
            )
    elif spent >= limit * 0.8 and repo.mark_budget_alert(day, 80):
        _notify(f"⚠️ MStudent: chi phí LLM hôm nay đã đạt 80% trần ({spent:.2f}/{limit:.2f} USD).")


def _notify(text: str) -> None:
    log.warning(text)
    _send_alert(text)


def _send_alert(text: str) -> None:
    url = config.alert_webhook()
    if not url:
        return

    def post() -> None:
        try:
            # "content" cho Discord, "text" cho Slack và các webhook tương thích.
            httpx.post(url, json={"content": text, "text": text}, timeout=5)
        except Exception as e:
            log.warning("Không gửi được cảnh báo chi phí: %s", type(e).__name__)

    threading.Thread(target=post, daemon=True).start()
