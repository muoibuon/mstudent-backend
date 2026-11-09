"""MStudent API — chạy: uvicorn app.main:app --reload (trong thư mục backend/)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import agent_config, config, evaluation, store
from .connectors import lms_ics, zalo
from .models import ChatRequest, ChatResponse, IngestResult, Message, Task
from .pipeline import assistant, orchestrator, planner

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT.parent / "sample_data" / "messages.json"


async def require_api_token(request: Request, authorization: str | None = Header(None)) -> None:
    """Nếu đặt MSTUDENT_API_TOKEN thì mọi /api/* (trừ /api/health) cần `Authorization: Bearer <token>`.

    Dùng khi deploy backend công khai cho app mobile. Để trống khi chạy local/demo.
    """
    expected = os.getenv("MSTUDENT_API_TOKEN")
    if not expected or not request.url.path.startswith("/api/") or request.url.path == "/api/health":
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "Thiếu hoặc sai API token")


app = FastAPI(
    title="MStudent",
    version="0.2.0",
    description="AI inbox biến thông báo email/LMS/Zalo thành việc cần làm",
    dependencies=[Depends(require_api_token)],
)
# App mobile / web khác origin gọi API → cần CORS. Thu hẹp bằng MSTUDENT_CORS_ORIGINS="https://a.com,https://b.com".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("MSTUDENT_CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ZaloPaste(BaseModel):
    text: str
    group: str = "Nhóm lớp"


class IcsUrl(BaseModel):
    url: str


class TaskPatch(BaseModel):
    title: str | None = None
    due_at: str | None = None
    status: str | None = None


def _check_admin(token: str | None) -> None:
    """Nếu đặt MSTUDENT_ADMIN_TOKEN thì chỉ ai có token mới được sửa cấu hình agent."""
    expected = os.getenv("MSTUDENT_ADMIN_TOKEN")
    if expected and token != expected:
        raise HTTPException(403, "Sai admin token")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": "llm" if config.llm_enabled() else "offline",
        "model": agent_config.get()["model"],
        "now": config.now().isoformat(),
    }


@app.post("/api/ingest", response_model=IngestResult)
async def ingest(msg: Message):
    return await orchestrator.ingest(msg)


@app.post("/api/ingest/zalo", response_model=list[IngestResult])
async def ingest_zalo(p: ZaloPaste):
    return [await orchestrator.ingest(m) for m in zalo.split_chat(p.text, p.group)]


@app.post("/api/ingest/lms-ics", response_model=list[IngestResult])
async def ingest_ics(p: IcsUrl):
    try:
        msgs = lms_ics.fetch(p.url)
    except Exception as e:
        raise HTTPException(400, f"Không đọc được lịch: {e}") from e
    return [await orchestrator.ingest(m) for m in msgs]


@app.get("/api/tasks", response_model=list[Task])
def tasks(status: str | None = "open"):
    return planner.live(store.list_tasks(status or None), config.now())


@app.post("/api/tasks/{task_id}/done", response_model=Task)
def done(task_id: int):
    if store.get_task(task_id) is None:
        raise HTTPException(404, "Không có việc này")
    return store.set_status(task_id, "done")


@app.patch("/api/tasks/{task_id}", response_model=Task)
def patch_task(task_id: int, p: TaskPatch):
    if store.get_task(task_id) is None:
        raise HTTPException(404, "Không có việc này")
    fields = p.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "Không có gì để cập nhật")
    return planner.live([store.update_task(task_id, fields)], config.now())[0]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    return await assistant.chat(req.message, req.history)


@app.get("/api/traces")
def traces(limit: int = 30):
    return store.list_traces(limit)


@app.get("/api/agents/config")
def get_agent_config():
    return {"config": agent_config.get(), "defaults": agent_config.DEFAULTS, "llm": config.llm_enabled()}


@app.put("/api/agents/config")
def put_agent_config(values: dict[str, str], x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return {"config": agent_config.save(values)}


@app.post("/api/agents/config/reset")
def reset_agent_config(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return {"config": agent_config.reset()}


@app.post("/api/eval")
async def run_eval():
    return await evaluation.evaluate()


@app.get("/api/digest")
async def digest():
    return await orchestrator.digest()


@app.post("/api/demo/seed", response_model=list[IngestResult])
async def seed():
    """Xoá dữ liệu và nạp bộ tin nhắn mẫu để demo."""
    store.reset()
    msgs = [Message(**m) for m in json.loads(SAMPLE.read_text(encoding="utf-8"))]
    return [await orchestrator.ingest(m) for m in msgs]
