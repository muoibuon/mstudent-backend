"""Lưu trữ SQLite tối giản (đủ cho hackathon, thay bằng Postgres sau)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from . import config
from .models import Category, Message, Priority, Source, Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    source TEXT, sender TEXT, subject TEXT, body TEXT, received_at TEXT,
    relevant INTEGER, category TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, course TEXT, category TEXT, due_at TEXT, location TEXT, action TEXT,
    priority TEXT, source TEXT, message_id TEXT, status TEXT DEFAULT 'open',
    reminders TEXT DEFAULT '[]', updated_from TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT, created_at TEXT, mode TEXT, summary TEXT, steps TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def reset() -> None:
    with connect() as c:
        c.execute("DELETE FROM tasks")
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM traces")
        c.execute("DELETE FROM sqlite_sequence WHERE name IN ('tasks', 'traces')")  # id đếm lại từ 1


def save_message(msg: Message, relevant: bool, category: Category, reason: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
            (
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


def message_seen(msg_id: str) -> bool:
    with connect() as c:
        return c.execute("SELECT 1 FROM messages WHERE id=?", (msg_id,)).fetchone() is not None


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


def insert_task(t: dict) -> Task:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO tasks (title, course, category, due_at, location, action, priority, source,"
            " message_id, reminders) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
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
            ),
        )
        row = c.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone()
        return _row_to_task(row)


def update_task(task_id: int, fields: dict) -> Task:
    fields = dict(fields)
    for k in ("reminders", "updated_from"):
        if k in fields:
            fields[k] = json.dumps(fields[k])
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), task_id))
        return _row_to_task(c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def list_tasks(status: str | None = "open") -> list[Task]:
    q, args = "SELECT * FROM tasks", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    q += " ORDER BY due_at IS NULL, due_at"
    with connect() as c:
        return [_row_to_task(r) for r in c.execute(q, args).fetchall()]


def set_status(task_id: int, status: str) -> Task:
    return update_task(task_id, {"status": status})


def get_task(task_id: int) -> Task | None:
    with connect() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(r) if r else None


# ---- Trace từng bước agent ----


def save_trace(message_id: str, created_at: str, mode: str, summary: str, steps: list[dict]) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO traces (message_id, created_at, mode, summary, steps) VALUES (?,?,?,?,?)",
            (message_id, created_at, mode, summary, json.dumps(steps, ensure_ascii=False)),
        )
        return cur.lastrowid


def list_traces(limit: int = 30) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM traces ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
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


# ---- Cấu hình agent ----


def get_settings() -> dict[str, str]:
    with connect() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}


def save_settings(values: dict[str, str]) -> None:
    with connect() as c:
        c.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", list(values.items()))


def clear_settings() -> None:
    with connect() as c:
        c.execute("DELETE FROM settings")
