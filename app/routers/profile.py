"""003-event-rsvp: danh mục trường/ngành, hồ sơ học tập, lời mời sự kiện (Tham gia / Không).

Mọi endpoint cần đăng nhập; mọi truy vấn lọc theo user_id. Hồ sơ chỉ dùng để đánh giá mức phù hợp của sự kiện (máy
chủ) và để app tự dựng link Google Form điền sẵn trên máy (máy chủ không dựng link chứa dữ liệu cá nhân).
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response

from .. import config, repo
from ..deps import current_user, enforce
from ..models import Profile, ProfileUpdate, RsvpRequest, Task
from ..pipeline import events, planner

router = APIRouter(prefix="/api", tags=["profile"])
DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def _catalog() -> tuple[bytes, str]:
    files = {
        name: json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("schools", "majors", "programs")
    }
    body = {
        "schools": files["schools"]["schools"],
        "majors": files["majors"]["levels"],  # {dai_hoc|thac_si|tien_si: [{code, name}]}
        "programs": files["programs"]["schools"],  # {<viết tắt trường>: {bậc: [{code, name}]}}
        "sources": {
            k: {x: v[x] for x in v if x in ("source", "fetched", "updated")} for k, v in files.items()
        },
    }
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    return raw, '"' + hashlib.sha256(raw).hexdigest()[:20] + '"'


@router.get("/catalog")
def catalog(request: Request, user: dict = Depends(current_user)) -> Response:
    """Danh sách trường (tên, viết tắt), danh mục ngành theo bậc, chương trình riêng của trường. ~130 KB, có ETag."""
    raw, etag = _catalog()
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=raw, media_type="application/json", headers=headers)


@router.get("/profile", response_model=Profile)
def get_profile(user: dict = Depends(current_user)):
    return repo.get_profile(user["id"])


@router.put("/profile", response_model=Profile)
def put_profile(body: ProfileUpdate, background: BackgroundTasks, user: dict = Depends(current_user)):
    enforce(f"profile:{user['id']}", 30, 3600)
    before = repo.get_profile(user["id"])
    saved = repo.save_profile(user["id"], body.model_dump())
    if before.get("major_name") != saved.get("major_name"):
        # đổi ngành → tính lại (nền) mức phù hợp của lời mời còn chờ (US3)
        background.add_task(events.reassess_pending, user["id"])
    return saved


@router.post("/profile/snooze")
def snooze(user: dict = Depends(current_user)):
    repo.snooze_profile(user["id"])
    return {"ok": True}


def _passed(t: Task, now) -> bool:
    """Sự kiện đã qua: lấy giờ kết thúc nếu có, không thì giờ bắt đầu. Không có giờ → chưa qua."""
    end = planner._dt(t.event_end) or planner._dt(t.due_at)
    return end is not None and end < now


@router.get("/events", response_model=list[Task])
def list_events(
    state: str = Query("pending", pattern="^(pending|going|declined)$"), user: dict = Depends(current_user)
):
    """Lời mời sự kiện theo trạng thái. `pending` đã qua giờ tự ẩn (FR-016); `declined` chỉ giữ sự kiện chưa qua."""
    now = config.now()
    items = repo.list_events(user["id"], state)
    if state != "going":
        items = [t for t in items if not _passed(t, now)]
    return planner.live(items, now)


@router.post("/tasks/{task_id}/rsvp", response_model=Task)
def rsvp(task_id: int, body: RsvpRequest, user: dict = Depends(current_user)):
    enforce(f"rsvp:{user['id']}", 120, 3600)
    task = repo.get_task(user["id"], task_id)
    if not task:
        raise HTTPException(404, "Không tìm thấy việc")
    if task.rsvp is None:
        raise HTTPException(400, "Việc này không phải lời mời sự kiện")
    if task.mandatory and not body.going:
        raise HTTPException(409, "Sự kiện bắt buộc, không thể bỏ qua")
    return events.set_rsvp(user["id"], task, body.going)
