"""API chính: thông báo → việc, trợ lý chat, bản tin, thống kê, cấu hình agent. Tất cả đều cần đăng nhập."""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlparse

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import agent_config, budget, config, evaluation, repo
from ..connectors import lms_ics, zalo
from ..deps import admin_user, ai_limit, client_ip, current_user, enforce
from ..models import ChatRequest, ChatResponse, IcsUrl, IngestResult, Message, Task, TaskPatch, ZaloPaste
from ..pipeline import assistant, orchestrator, planner

router = APIRouter(prefix="/api", tags=["core"])

SAMPLE = Path(__file__).resolve().parent.parent.parent / "sample_data" / "messages.json"
MAX_BATCH = 30


# ---------------- Thông báo → việc ----------------


@router.post("/ingest", response_model=IngestResult)
async def ingest(msg: Message, user: dict = Depends(ai_limit)):
    return await orchestrator.ingest(user["id"], msg)


@router.post("/ingest/zalo", response_model=list[IngestResult])
async def ingest_zalo(p: ZaloPaste, user: dict = Depends(ai_limit)):
    msgs = zalo.split_chat(p.text, p.group)[:MAX_BATCH]
    return [await orchestrator.ingest(user["id"], m) for m in msgs]


def _assert_public_url(url: str) -> None:
    """Chống SSRF: chỉ cho http(s) tới địa chỉ công khai (không localhost, mạng nội bộ, metadata cloud)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise HTTPException(400, "Chỉ nhận đường dẫn http(s)")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror as e:
        raise HTTPException(400, "Không phân giải được tên miền") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise HTTPException(400, "Không được trỏ tới địa chỉ nội bộ")


@router.post("/ingest/lms-ics", response_model=list[IngestResult])
async def ingest_ics(p: IcsUrl, user: dict = Depends(ai_limit)):
    await anyio.to_thread.run_sync(_assert_public_url, p.url)
    try:
        msgs = await anyio.to_thread.run_sync(lms_ics.fetch, p.url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, "Không đọc được lịch từ đường dẫn này") from e
    return [await orchestrator.ingest(user["id"], m) for m in msgs[:MAX_BATCH]]


@router.post("/demo/seed", response_model=list[IngestResult])
async def seed(user: dict = Depends(current_user)):
    """Xoá dữ liệu CỦA NGƯỜI ĐANG ĐĂNG NHẬP và nạp bộ tin nhắn mẫu để demo."""
    enforce(f"seed:{user['id']}", 6, 3600)
    repo.reset_user_data(user["id"])
    msgs = [Message(**m) for m in json.loads(SAMPLE.read_text(encoding="utf-8"))]
    return [await orchestrator.ingest(user["id"], m) for m in msgs]


# ---------------- Việc ----------------


@router.get("/tasks", response_model=list[Task])
def tasks(status: str | None = "open", user: dict = Depends(current_user)):
    if status not in (None, "", "open", "done"):
        raise HTTPException(400, "status phải là open hoặc done")
    return planner.live(repo.list_tasks(user["id"], status or None), config.now())


@router.post("/tasks/{task_id}/done", response_model=Task)
def done(task_id: int, user: dict = Depends(current_user)):
    task = repo.set_status(user["id"], task_id, "done")
    if task is None:  # không tồn tại HOẶC của người khác — trả cùng một lỗi
        raise HTTPException(404, "Không có việc này")
    return task


@router.patch("/tasks/{task_id}", response_model=Task)
def patch_task(task_id: int, p: TaskPatch, user: dict = Depends(current_user)):
    fields = p.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "Không có gì để cập nhật")
    if "due_at" in fields:
        due = planner._dt(fields["due_at"])
        if due is None:
            raise HTTPException(422, "due_at phải là ISO 8601")
        fields["due_at"] = due.isoformat()
    task = repo.update_task(user["id"], task_id, fields)
    if task is None:
        raise HTTPException(404, "Không có việc này")
    if "due_at" in fields:  # dời hạn → tính lại mốc nhắc
        task = repo.update_task(user["id"], task_id, {"reminders": planner.reminders(task, config.now())})
    return planner.live([task], config.now())[0]


# ---------------- Trợ lý, bản tin, thống kê ----------------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(ai_limit)):
    return await assistant.chat(user["id"], req.message, req.history)


@router.get("/digest")
async def digest(user: dict = Depends(ai_limit)):
    return await orchestrator.digest(user["id"])


@router.get("/stats")
def stats(user: dict = Depends(current_user)):
    return repo.stats(user["id"])


@router.get("/traces")
def traces(limit: int = 30, user: dict = Depends(current_user)):
    return repo.list_traces(user["id"], max(1, min(limit, 100)))


@router.post("/ai/check")
async def ai_check(user: dict = Depends(ai_limit)):
    """Gọi thật LLM một lượt: dùng để chắc chắn AI chạy trực tiếp trước khi demo. Tính vào hạn mức AI của người gọi."""
    enforce(f"aicheck:{user['id']}", 10, 300)
    return await orchestrator.ai_selfcheck(user["id"])


# ---------------- Quản trị ----------------


@router.get("/agents/config")
def get_agent_config(user: dict = Depends(current_user)):
    cfg = agent_config.get()
    if user["email"].lower() not in config.admin_emails():
        return {"config": {"model": cfg["model"]}, "llm": config.llm_enabled(), "can_edit": False}
    return {"config": cfg, "defaults": agent_config.DEFAULTS, "llm": config.llm_enabled(), "can_edit": True}


@router.put("/agents/config")
def put_agent_config(values: dict[str, str], request: Request, admin: dict = Depends(admin_user)):
    repo.audit("agent_config_changed", admin["id"], client_ip(request), ",".join(sorted(values)[:10]))
    try:
        return {"config": agent_config.save(values)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.post("/agents/config/reset")
def reset_agent_config(request: Request, admin: dict = Depends(admin_user)):
    repo.audit("agent_config_reset", admin["id"], client_ip(request))
    return {"config": agent_config.reset()}


@router.post("/eval")
async def run_eval(admin: dict = Depends(admin_user)):
    enforce(f"eval:{admin['id']}", 6, 600)
    return await evaluation.evaluate()


@router.get("/admin/audit")
def audit_log(limit: int = 100, admin: dict = Depends(admin_user)):
    return repo.list_audit(max(1, min(limit, 500)))


@router.get("/admin/stats")
def admin_stats(admin: dict = Depends(admin_user)):
    now = config.now()
    return {
        "generated_at": now.isoformat(),
        **repo.stats_summary(now),
        "llm_budget_usd": config.llm_daily_usd(),
        "llm_budget_exhausted": budget.exhausted(),
    }


@router.get("/admin/overview")
def overview(admin: dict = Depends(admin_user)):
    return {"users": repo.count_users()}
