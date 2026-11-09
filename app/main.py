"""MStudent API — chạy: uvicorn app.main:app --reload (trong thư mục backend/)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, store
from .connectors import lms_ics, zalo
from .models import IngestResult, Message, Task
from .pipeline import orchestrator, planner

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT.parent / "sample_data" / "messages.json"

app = FastAPI(
    title="MStudent", version="0.1.0", description="AI inbox biến thông báo email/LMS/Zalo thành việc cần làm"
)


class ZaloPaste(BaseModel):
    text: str
    group: str = "Nhóm lớp"


class IcsUrl(BaseModel):
    url: str


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "llm" if config.llm_enabled() else "offline", "model": config.OPENAI_MODEL}


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
    return store.set_status(task_id, "done")


@app.get("/api/digest")
async def digest():
    return await orchestrator.digest()


@app.post("/api/demo/seed", response_model=list[IngestResult])
async def seed():
    """Xoá dữ liệu và nạp bộ tin nhắn mẫu để demo."""
    store.reset()
    msgs = [Message(**m) for m in json.loads(SAMPLE.read_text(encoding="utf-8"))]
    return [await orchestrator.ingest(m) for m in msgs]
