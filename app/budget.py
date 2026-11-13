"""Trần chi phí LLM theo ngày cho toàn hệ thống.

- `llm_allowed()`: có được gọi LLM lúc này không (có khoá, không ép offline, chưa chạm trần hôm nay).
- `record()`: ghi token + chi phí ước tính của một lượt gọi, gửi cảnh báo khi chạm 80% và 100%.

Ngày tính theo giờ Việt Nam (`config.now()`). Chạm trần → pipeline chạy bộ luật và ghi rõ mode="offline".
Không bao giờ lưu hay gửi nội dung prompt/câu trả lời.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from . import config, repo

log = logging.getLogger("mstudent")


def today() -> str:
    return config.now().date().isoformat()


def spent_today() -> float:
    return repo.llm_cost_on(today())


def exhausted() -> bool:
    return spent_today() >= config.llm_daily_usd()


def llm_allowed() -> bool:
    """Dùng thay cho config.llm_enabled() ở mọi chỗ sắp gọi LLM."""
    return config.llm_enabled() and not exhausted()


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * config.price_in_per_m() + output_tokens * config.price_out_per_m()) / 1_000_000


def _tokens(result) -> tuple[int, int]:
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def record(user_id: int | None, agent: str, result, started: float) -> None:
    """Ghi nhận một lượt gọi LLM đã xong. Không được làm hỏng luồng chính nếu ghi lỗi."""
    try:
        tin, tout = _tokens(result)
        repo.record_llm_usage(
            user_id, agent, tin, tout, cost_usd(tin, tout), round((time.perf_counter() - started) * 1000)
        )
        _maybe_alert()
    except (
        Exception
    ) as e:  # CSDL bận, v.v. — chi phí lượt này không được ghi, nhưng người dùng vẫn có kết quả
        log.warning("Không ghi được chi phí LLM: %s", type(e).__name__)


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
