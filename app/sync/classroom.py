"""Google Classroom tự động — US2 (002-auto-ingest).

Bài tập có hạn → việc cần làm trực tiếp (dữ liệu có cấu trúc, KHÔNG gọi AI, hạn đúng 100%). Bài đã nộp → việc xong.
Thông báo lớp → pipeline AI như một tin nhắn. Chỉ theo dõi lớp tạo trong 60 ngày hoặc có hoạt động trong 14 ngày
(FR-024). Trường chặn ứng dụng bên ngoài → tắt nguồn Classroom kèm giải thích; Gmail không bị ảnh hưởng.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .. import config, google_api, repo, security
from ..models import Message, Source, TaskOut
from ..pipeline import orchestrator, planner
from . import scheduler
from .common import guess_category, short_hash
from .scheduler import AuthError, RunResult, TemporaryError

RECONNECT = "Cần kết nối lại Google để đọc Classroom"
ACTIVE_DAYS, NEW_COURSE_DAYS = 14, 60


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def due_of(work: dict) -> str | None:
    """dueDate/dueTime của Classroom là giờ UTC → đổi sang +07:00. Thiếu giờ → 23:59 giờ VN của ngày đó."""
    d = work.get("dueDate")
    if not d or not d.get("year"):
        return None
    t = work.get("dueTime")
    try:
        if t:
            utc = datetime(
                d["year"], d["month"], d["day"], t.get("hours", 0), t.get("minutes", 0), tzinfo=UTC
            )
            return utc.astimezone(config.TZ).isoformat()
        return datetime(d["year"], d["month"], d["day"], 23, 59, tzinfo=config.TZ).isoformat()
    except (KeyError, ValueError):
        return None


def course_is_tracked(snap: dict, now: datetime) -> bool:
    co = snap["course"]
    created = _ts(co.get("creationTime"))
    if created and created >= now - timedelta(days=NEW_COURSE_DAYS):
        return True
    recent = now - timedelta(days=ACTIVE_DAYS)
    stamps = [_ts(x.get("updateTime")) for x in snap["coursework"] + snap["announcements"]]
    return any(s and s >= recent for s in stamps)


async def run(conn: dict) -> RunResult:
    uid = conn["user_id"]
    acct = repo.google_account(uid)
    refresh = security.decrypt(acct["refresh_token_enc"]) if acct else None
    if not refresh:
        raise AuthError(RECONNECT)
    try:
        token = await google_api.access_token(refresh)
        snapshot = await google_api.classroom_snapshot(token)
    except google_api.ClassroomBlocked as e:
        raise AuthError(str(e)) from e
    except google_api.AuthRevoked as e:
        raise AuthError(RECONNECT) from e
    except google_api.GoogleError as e:
        raise TemporaryError(str(e)) from e

    first = conn.get("last_ok_at") is None
    now_utc, ref = datetime.now(UTC), config.now()
    res = RunResult(mode="structured", state=dict(conn.get("state") or {}))
    tracked = 0
    for snap in snapshot:
        if not course_is_tracked(snap, now_utc):
            continue
        tracked += 1
        course_name = (snap["course"].get("name") or "")[:60]
        turned_in = {
            s["courseWorkId"] for s in snap["submissions"] if s.get("state") in ("TURNED_IN", "RETURNED")
        }
        for work in snap["coursework"]:
            await _work(conn, uid, course_name, work, work["id"] in turned_in, first, ref, res)
        for ann in snap["announcements"]:
            created = _ts(ann.get("creationTime"))
            if not ann.get("text") or not created or created < now_utc - timedelta(days=3 if first else 7):
                continue
            if repo.get_message(uid, f"classroom-ann-{ann['id']}"[:200]):
                res.skipped += 1  # đã xử lý → không chạy lại pipeline
                continue
            out = await orchestrator.ingest(
                uid,
                Message(
                    id=f"classroom-ann-{ann['id']}"[:200],
                    source=Source.classroom,
                    sender=course_name,
                    subject=f"Thông báo lớp {course_name}"[:500],
                    body=ann["text"][:8000],
                    received_at=created.astimezone(config.TZ).isoformat(),
                ),
            )
            if not out.duplicate:
                res.created += out.created
                res.updated += out.updated
                res.mode = out.mode if out.mode in ("llm", "offline") else res.mode
    res.state["tracked_courses"] = tracked
    return res


async def _work(conn, uid, course_name, work, done, first, ref, res) -> None:
    key = f"cw:{work['id']}"
    title = (work.get("title") or "").strip()[:80]
    if not title:
        return
    due = due_of(work)
    chash = short_hash(title, due or "", "done" if done else "open")
    prev = repo.get_source_item(conn["id"], key)
    if prev and prev["content_hash"] == chash:
        res.skipped += 1
        return
    task = repo.get_task(uid, prev["task_id"]) if prev and prev["task_id"] else None
    if prev and prev["task_id"] and (task is None or task.status == "done"):
        repo.upsert_source_item(uid, conn["id"], key, chash, None)  # người dùng đã xoá / đã xong
        res.skipped += 1
        return
    if done:
        if task and task.status == "open":  # đã nộp trên Classroom → việc xong (FR-021)
            repo.update_task(uid, task.id, {"status": "done", "done_at": config.utcnow().isoformat()})
            res.updated.append(repo.get_task(uid, task.id))
        repo.upsert_source_item(uid, conn["id"], key, chash, task.id if task else None)
        return
    if first and due and datetime.fromisoformat(due) < ref - timedelta(days=1):
        repo.upsert_source_item(uid, conn["id"], key, chash, None)
        res.skipped += 1
        return
    draft = TaskOut(
        title=title,
        course=course_name or None,
        category=guess_category(title),
        due_at=due,
        location=None,
        action=(work.get("alternateLink") or None) and "Nộp trên Google Classroom",
    )
    created, updated = planner.plan(uid, [draft], source="classroom", message_id=f"classroom-{key}", ref=ref)
    res.created += created
    res.updated += updated
    touched = (created + updated)[:1]
    repo.upsert_source_item(uid, conn["id"], key, chash, touched[0].id if touched else None)


def register() -> None:
    scheduler.RUNNERS["classroom"] = run
