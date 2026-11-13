"""Bộ lập lịch đồng bộ nền: chạy trong tiến trình web (1 worker), trạng thái lưu trong CSDL.

Mỗi 15 giây: lấy các nguồn tới hạn (có lease chống chạy trùng), chạy tối đa N nguồn song song, mỗi lượt tối đa
90 giây. Thành công → hẹn lượt sau theo chu kỳ của loại nguồn (± 10 % để dàn tải). Lỗi tạm thời → lùi dần
2, 4, 8… phút (tối đa 60). Lỗi quyền (token bị thu hồi/hết hạn) → tắt nguồn và ghi "Cần kết nối lại …".
Log chỉ có id nguồn + loại lỗi: không token, không nội dung thông báo.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from .. import config, repo
from ..models import Task

log = logging.getLogger("mstudent")

TICK_S = 15
RUN_TIMEOUT_S = 90
LEASE_S = RUN_TIMEOUT_S + 30


class TemporaryError(Exception):
    """Lỗi tạm thời (mạng, nguồn trả 5xx…): thử lại sau, lùi dần. Thông điệp hiển thị cho người dùng."""


class AuthError(Exception):
    """Quyền truy cập không còn hiệu lực: tắt nguồn, người dùng phải kết nối lại."""


@dataclass
class RunResult:
    created: list[Task] = field(default_factory=list)
    updated: list[Task] = field(default_factory=list)
    skipped: int = 0
    mode: str = ""  # llm | offline | structured
    cursor: str | None = None
    state: dict | None = None


Runner = Callable[[dict], Awaitable[RunResult]]
RUNNERS: dict[str, Runner] = {}
# Gọi sau mỗi lượt thành công có thay đổi (vd. gửi thông báo đẩy): fn(conn, result, first_run)
AFTER_RUN: list[Callable[[dict, RunResult, bool], Awaitable[None]]] = []


def interval_s(kind: str) -> int:
    return {"gmail": config.gmail_poll_s(), "classroom": 600, "sheet": 1800, "ics": 3600}.get(kind, 1800)


def backoff_minutes(fail_count: int) -> int:
    return min(2 ** max(1, fail_count), 60)


def _next_ok(kind: str) -> str:
    s = interval_s(kind) * random.uniform(0.9, 1.1)
    return (config.utcnow() + timedelta(seconds=s)).isoformat()


async def run_one(conn: dict) -> None:
    runner = RUNNERS.get(conn["kind"])
    if runner is None:
        repo.finish_run(conn["id"], ok=False, error="Loại nguồn chưa được hỗ trợ", next_run_at=_later(60))
        return
    first_run = conn.get("last_ok_at") is None
    try:
        res = await asyncio.wait_for(runner(conn), RUN_TIMEOUT_S)
    except AuthError as e:
        log.warning("Đồng bộ nguồn %s: mất quyền truy cập", conn["id"])
        repo.finish_run(conn["id"], ok=False, error=str(e), next_run_at=_later(60), disable=True)
        return
    except Exception as e:  # TemporaryError, timeout, lỗi bất ngờ: không làm hỏng nguồn khác
        msg = str(e) if isinstance(e, TemporaryError) else "Lỗi tạm thời khi đồng bộ, sẽ thử lại"
        if isinstance(e, TimeoutError):
            msg = "Nguồn phản hồi quá chậm, sẽ thử lại"
        log.warning("Đồng bộ nguồn %s lỗi: %s", conn["id"], type(e).__name__)
        repo.finish_run(
            conn["id"], ok=False, error=msg, next_run_at=_later(backoff_minutes(conn["fail_count"] + 1))
        )
        return
    state = dict(res.state if res.state is not None else conn.get("state") or {})
    state["last"] = {
        "created": len(res.created),
        "updated": len(res.updated),
        "skipped": res.skipped,
        "mode": res.mode,
    }
    repo.finish_run(conn["id"], ok=True, next_run_at=_next_ok(conn["kind"]), cursor=res.cursor, state=state)
    if res.created or res.updated:
        for hook in AFTER_RUN:
            try:
                await hook(conn, res, first_run)
            except Exception as e:
                log.warning("Hook sau đồng bộ lỗi: %s", type(e).__name__)


def _later(minutes: float) -> str:
    return (config.utcnow() + timedelta(minutes=minutes)).isoformat()


async def tick(*, force: bool = False) -> int:
    """Chạy một vòng. `force=True` (test) lấy mọi nguồn đang bật bất kể giờ hẹn."""
    now = config.utcnow()
    limit = config.sync_concurrency() * 2
    conns = repo.claim_due_connections(
        now.isoformat(),
        (now + timedelta(seconds=LEASE_S)).isoformat(),
        limit,
        due_before="9999" if force else None,
    )
    if not conns:
        return 0
    sem = asyncio.Semaphore(config.sync_concurrency())

    async def guarded(c: dict) -> None:
        async with sem:
            await run_one(c)

    await asyncio.gather(*(guarded(c) for c in conns))
    return len(conns)


async def loop() -> None:
    log.info("Bộ đồng bộ nền đã chạy (mỗi %ss, %s nguồn song song)", TICK_S, config.sync_concurrency())
    while True:
        try:
            await tick()
        except Exception as e:  # không bao giờ để vòng lặp chết
            log.warning("Vòng đồng bộ lỗi: %s", type(e).__name__)
        await asyncio.sleep(TICK_S)


def register_default_runners() -> None:
    """Gắn runner/hook của các loại nguồn đã có: mỗi module có hàm `register()`."""
    import importlib

    for name in ("gmail", "classroom", "ics", "sheets", "notify"):
        try:
            mod = importlib.import_module(f"{__package__}.{name}")
        except ModuleNotFoundError:
            continue
        mod.register()


@contextlib.asynccontextmanager
async def lifespan(app):
    task = None
    if config.sync_enabled():
        register_default_runners()
        task = asyncio.create_task(loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
