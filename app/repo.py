"""Truy vấn CSDL. Mọi hàm dữ liệu người dùng đều nhận `user_id` và lọc theo nó — không có ngoại lệ."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from . import config
from .db import connect
from .models import Category, Message, Priority, Source, Task

# ---------------- Người dùng ----------------


def _iso() -> str:
    return config.utcnow().isoformat()


def create_user(email: str, name: str, password_hash: str | None, google_sub: str | None = None) -> dict:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO users (email, name, password_hash, google_sub, created_at) VALUES (?,?,?,?,?)",
            (email, name, password_hash, google_sub, _iso()),
        )
        return dict(c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())


def _one(sql: str, args: tuple) -> dict | None:
    with connect() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def user_by_id(user_id: int) -> dict | None:
    return _one("SELECT * FROM users WHERE id=?", (user_id,))


def user_by_email(email: str) -> dict | None:
    return _one("SELECT * FROM users WHERE email=?", (email,))


def user_by_google_sub(sub: str) -> dict | None:
    return _one("SELECT * FROM users WHERE google_sub=?", (sub,))


def update_user(user_id: int, **fields) -> None:
    allowed = {"name", "password_hash", "google_sub", "last_login_at"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), user_id))


def delete_user(user_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM users WHERE id=?", (user_id,))  # CASCADE xoá toàn bộ dữ liệu liên quan


def count_users() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ---------------- Refresh token ----------------


def add_refresh_token(user_id: int, token_hash: str, family: str, device: str) -> None:
    now = config.utcnow()
    with connect() as c:
        c.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, family, device, created_at, expires_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                user_id,
                token_hash,
                family,
                device[:100],
                now.isoformat(),
                (now + timedelta(days=config.REFRESH_TTL_DAYS)).isoformat(),
            ),
        )
        # Dọn token đã hết hạn của người này để bảng không phình.
        c.execute("DELETE FROM refresh_tokens WHERE user_id=? AND expires_at < ?", (user_id, now.isoformat()))


def get_refresh_token(token_hash: str) -> dict | None:
    return _one("SELECT * FROM refresh_tokens WHERE token_hash=?", (token_hash,))


def revoke_refresh_token(token_id: int) -> bool:
    """Thu hồi một token. Trả về False nếu token đã bị thu hồi từ trước (dấu hiệu dùng lại)."""
    with connect() as c:
        cur = c.execute(
            "UPDATE refresh_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (_iso(), token_id)
        )
        return cur.rowcount == 1


def revoke_family(family: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE refresh_tokens SET revoked_at=? WHERE family=? AND revoked_at IS NULL", (_iso(), family)
        )


def family_alive(family: str) -> bool:
    """Chuỗi đăng nhập còn ít nhất một token chưa bị thu hồi (chưa đăng xuất, chưa bị đánh dấu lộ)."""
    with connect() as c:
        r = c.execute("SELECT 1 FROM refresh_tokens WHERE family=? AND revoked_at IS NULL LIMIT 1", (family,))
        return r.fetchone() is not None


def revoke_all_tokens(user_id: int) -> None:
    with connect() as c:
        c.execute(
            "UPDATE refresh_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (_iso(), user_id)
        )


# ---------------- Nhật ký bảo mật ----------------


def audit(event: str, user_id: int | None = None, ip: str = "", detail: str = "") -> None:
    try:
        with connect() as c:
            c.execute(
                "INSERT INTO audit_log (at, user_id, event, ip, detail) VALUES (?,?,?,?,?)",
                (_iso(), user_id, event, ip, detail[:300]),
            )
    except sqlite3.Error:  # nhật ký không được làm hỏng request
        pass


def list_audit(limit: int = 100) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


# ---------------- Tài khoản Google (Gmail) ----------------


def save_google_account(user_id: int, email: str, refresh_token_enc: str, scopes: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO google_accounts (user_id, email, refresh_token_enc, scopes, connected_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,"
            " refresh_token_enc=excluded.refresh_token_enc, scopes=excluded.scopes,"
            " connected_at=excluded.connected_at",
            (user_id, email, refresh_token_enc, scopes, _iso()),
        )


def google_account(user_id: int) -> dict | None:
    return _one("SELECT * FROM google_accounts WHERE user_id=?", (user_id,))


def touch_google_sync(user_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE google_accounts SET last_sync_at=? WHERE user_id=?", (_iso(), user_id))


def delete_google_account(user_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM google_accounts WHERE user_id=?", (user_id,))


# ---------------- Thông báo ----------------


def save_message(user_id: int, msg: Message, relevant: bool, category: Category, reason: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                msg.id,
                msg.source.value,
                msg.sender,
                msg.subject,
                msg.body,
                msg.received_at,
                int(relevant),
                category.value,
                reason,
            ),
        )


def get_message(user_id: int, msg_id: str) -> dict | None:
    return _one("SELECT * FROM messages WHERE user_id=? AND id=?", (user_id, msg_id))


# ---------------- Việc ----------------


def _row_to_task(r: sqlite3.Row) -> Task:
    return Task(
        id=r["id"],
        title=r["title"],
        course=r["course"],
        category=Category(r["category"]),
        due_at=r["due_at"],
        location=r["location"],
        action=r["action"],
        priority=Priority(r["priority"]),
        source=Source(r["source"]),
        message_id=r["message_id"],
        status=r["status"],
        reminders=json.loads(r["reminders"] or "[]"),
        updated_from=json.loads(r["updated_from"] or "[]"),
    )


def insert_task(user_id: int, t: dict) -> Task:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO tasks (user_id, title, course, category, due_at, location, action, priority, source,"
            " message_id, reminders, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                t["title"],
                t.get("course"),
                t["category"],
                t.get("due_at"),
                t.get("location"),
                t.get("action"),
                t["priority"],
                t["source"],
                t["message_id"],
                json.dumps(t.get("reminders", [])),
                _iso(),
            ),
        )
        return _row_to_task(c.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone())


TASK_FIELDS = {
    "title", "course", "category", "due_at", "location", "action", "priority", "status",
    "reminders", "updated_from", "done_at",
}  # fmt: skip


def update_task(user_id: int, task_id: int, fields: dict) -> Task | None:
    fields = {k: v for k, v in fields.items() if k in TASK_FIELDS}
    for k in ("reminders", "updated_from"):
        if k in fields:
            fields[k] = json.dumps(fields[k])
    with connect() as c:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(
                f"UPDATE tasks SET {sets} WHERE id=? AND user_id=?", (*fields.values(), task_id, user_id)
            )
        r = c.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
        return _row_to_task(r) if r else None


def get_task(user_id: int, task_id: int) -> Task | None:
    with connect() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
        return _row_to_task(r) if r else None


def list_tasks(user_id: int, status: str | None = "open") -> list[Task]:
    q, args = "SELECT * FROM tasks WHERE user_id=?", [user_id]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY due_at IS NULL, due_at"
    with connect() as c:
        return [_row_to_task(r) for r in c.execute(q, args).fetchall()]


def tasks_from_message(user_id: int, msg_id: str) -> list[Task]:
    with connect() as c:
        rows = c.execute("SELECT * FROM tasks WHERE user_id=? AND message_id=?", (user_id, msg_id)).fetchall()
        return [_row_to_task(r) for r in rows]


def set_status(user_id: int, task_id: int, status: str) -> Task | None:
    return update_task(user_id, task_id, {"status": status, "done_at": _iso() if status == "done" else None})


def reset_user_data(user_id: int) -> None:
    """Xoá việc, thông báo, trace của MỘT người dùng (dùng cho nạp demo)."""
    with connect() as c:
        for table in ("tasks", "messages", "traces"):
            c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))


# ---------------- Trace ----------------


def save_trace(user_id: int, message_id: str, mode: str, summary: str, steps: list[dict]) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO traces (user_id, message_id, created_at, mode, summary, steps) VALUES (?,?,?,?,?,?)",
            (
                user_id,
                message_id,
                config.now().isoformat(),
                mode,
                summary,
                json.dumps(steps, ensure_ascii=False),
            ),
        )
        # Giữ 200 trace gần nhất mỗi người.
        c.execute(
            "DELETE FROM traces WHERE user_id=? AND id NOT IN"
            " (SELECT id FROM traces WHERE user_id=? ORDER BY id DESC LIMIT 200)",
            (user_id, user_id),
        )
        return cur.lastrowid


def list_traces(user_id: int, limit: int = 30) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM traces WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "message_id": r["message_id"],
            "created_at": r["created_at"],
            "mode": r["mode"],
            "summary": r["summary"],
            "steps": json.loads(r["steps"]),
        }
        for r in rows
    ]


# ---------------- Thống kê (bằng chứng giá trị cho người dùng) ----------------


def stats(user_id: int) -> dict:
    with connect() as c:

        def n(sql: str) -> int:
            return c.execute(sql, (user_id,)).fetchone()[0]

        by_source = {
            r[0]: r[1]
            for r in c.execute(
                "SELECT source, COUNT(*) FROM messages WHERE user_id=? GROUP BY source", (user_id,)
            )
        }
        return {
            "messages_read": n("SELECT COUNT(*) FROM messages WHERE user_id=?"),
            "noise_filtered": n("SELECT COUNT(*) FROM messages WHERE user_id=? AND relevant=0"),
            "tasks_created": n("SELECT COUNT(*) FROM tasks WHERE user_id=?"),
            "tasks_done": n("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='done'"),
            "tasks_open": n("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='open'"),
            "changes_caught": n("SELECT COUNT(*) FROM tasks WHERE user_id=? AND updated_from != '[]'"),
            "ai_runs": n("SELECT COUNT(*) FROM traces WHERE user_id=? AND mode='llm'"),
            "by_source": by_source,
        }


# ---------------- Cấu hình agent (toàn hệ thống) ----------------


def get_settings() -> dict[str, str]:
    with connect() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}


def save_settings(values: dict[str, str]) -> None:
    with connect() as c:
        c.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", list(values.items()))


def clear_settings() -> None:
    with connect() as c:
        c.execute("DELETE FROM settings")
