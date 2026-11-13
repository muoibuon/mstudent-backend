"""Nguồn tự động (002): quản lý nguồn của người dùng + đăng ký thiết bị nhận thông báo đẩy.

Mọi endpoint cần đăng nhập; mọi truy vấn lọc theo user_id; nguồn của người khác trả 404.
Không bao giờ trả về token hay URL đã chuẩn hoá (target) — chỉ nhãn và trạng thái.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import repo
from ..deps import ai_limit, current_user, enforce
from ..models import PushRegister, SourceCreate, SourceOut, SourcePatch

router = APIRouter(prefix="/api", tags=["sources"])

LIMITS = {"sheet": 10, "ics": 5}


def _out(c: dict) -> SourceOut:
    return SourceOut(
        id=c["id"],
        kind=c["kind"],
        label=c["label"],
        enabled=c["enabled"],
        last_run_at=c["last_run_at"],
        last_ok_at=c["last_ok_at"],
        last_error=c["last_error"],
        created_at=c["created_at"],
        last=(c.get("state") or {}).get("last"),
    )


async def _probe(kind: str, url: str) -> tuple[str, str]:
    """Kiểm tra link trước khi lưu: trả (target đã chuẩn hoá, nhãn gợi ý) hoặc ném HTTPException 400."""
    if kind == "sheet":
        from ..sync import sheets

        return await sheets.probe(url)
    try:
        from ..sync import ics
    except ModuleNotFoundError as e:  # US1 chưa triển khai
        raise HTTPException(400, "Lịch LMS tự động sắp có — tạm thời dùng mục Nhập lịch LMS") from e
    return await ics.probe(url)


@router.get("/sources", response_model=list[SourceOut])
def list_sources(user: dict = Depends(current_user)):
    return [_out(c) for c in repo.list_connections(user["id"])]


@router.post("/sources", response_model=SourceOut, status_code=201)
async def add_source(body: SourceCreate, user: dict = Depends(current_user)):
    enforce(f"srcadd:{user['id']}", 20, 3600)
    if repo.count_connections(user["id"], body.kind) >= LIMITS[body.kind]:
        raise HTTPException(422, f"Tối đa {LIMITS[body.kind]} nguồn loại này")
    target, label = await _probe(body.kind, body.url.strip())
    if repo.find_connection(user["id"], body.kind, target):
        raise HTTPException(409, "Nguồn này đã được thêm")
    conn = repo.create_connection(user["id"], body.kind, target, body.label.strip() or label)
    return _out(conn)


@router.patch("/sources/{conn_id}", response_model=SourceOut)
def patch_source(conn_id: int, body: SourcePatch, user: dict = Depends(current_user)):
    if not repo.get_connection(user["id"], conn_id):
        raise HTTPException(404, "Không tìm thấy nguồn")
    return _out(repo.set_connection_enabled(user["id"], conn_id, body.enabled))


@router.delete("/sources/{conn_id}")
def delete_source(conn_id: int, user: dict = Depends(current_user)):
    conn = repo.get_connection(user["id"], conn_id)
    if not conn:
        raise HTTPException(404, "Không tìm thấy nguồn")
    if conn["kind"] in ("gmail", "classroom"):
        raise HTTPException(400, "Nguồn Google: hãy dùng nút Ngắt kết nối Google")
    repo.delete_connection(user["id"], conn_id)
    return {"ok": True}


@router.post("/sources/{conn_id}/sync", status_code=202)
def sync_now(conn_id: int, user: dict = Depends(ai_limit)):
    if not repo.get_connection(user["id"], conn_id):
        raise HTTPException(404, "Không tìm thấy nguồn")
    enforce(f"srcsync:{user['id']}:{conn_id}", 6, 600)
    if not repo.run_connection_now(user["id"], conn_id):
        raise HTTPException(409, "Nguồn đang tắt — bật lại trước khi đồng bộ")
    return {"queued": True}


@router.post("/push/register")
def push_register(body: PushRegister, user: dict = Depends(current_user)):
    enforce(f"push:{user['id']}", 30, 3600)
    repo.upsert_push_token(user["id"], body.token, body.platform, body.notify)
    return {"ok": True}


@router.delete("/push/register")
def push_unregister(body: PushRegister, user: dict = Depends(current_user)):
    repo.delete_push_token(user["id"], body.token)
    return {"ok": True}
