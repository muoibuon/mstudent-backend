"""SQLite: kết nối, schema và nâng cấp phiên bản.

Mọi bảng dữ liệu người dùng đều có `user_id` và xoá theo người dùng (ON DELETE CASCADE).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager

from . import config

log = logging.getLogger("mstudent")

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT,              -- NULL nếu chỉ đăng nhập bằng Google
    google_sub TEXT UNIQUE,          -- mã định danh ổn định của tài khoản Google
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE, -- SHA-256 của token; không lưu token gốc
    family TEXT NOT NULL,            -- chuỗi xoay vòng của một lần đăng nhập
    device TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_refresh_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS ix_refresh_family ON refresh_tokens(family);
CREATE TABLE IF NOT EXISTS google_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    refresh_token_enc TEXT NOT NULL, -- mã hoá Fernet
    scopes TEXT NOT NULL DEFAULT '',
    connected_at TEXT NOT NULL,
    last_sync_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    source TEXT, sender TEXT, subject TEXT, body TEXT, received_at TEXT,
    relevant INTEGER, category TEXT, reason TEXT,
    PRIMARY KEY (user_id, id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT, course TEXT, category TEXT, due_at TEXT, location TEXT, action TEXT,
    priority TEXT, source TEXT, message_id TEXT, status TEXT DEFAULT 'open',
    reminders TEXT DEFAULT '[]', updated_from TEXT DEFAULT '[]',
    created_at TEXT, done_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(user_id, status);
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id TEXT, created_at TEXT, mode TEXT, summary TEXT, steps TEXT
);
CREATE INDEX IF NOT EXISTS ix_traces_user ON traces(user_id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);  -- cấu hình agent (toàn hệ thống)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, user_id INTEGER, event TEXT NOT NULL, ip TEXT, detail TEXT
);
-- Mỗi lượt gọi LLM thành công. user_id NULL = lượt gọi hệ thống (eval, ai-check). Không lưu nội dung.
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL, agent TEXT NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL, latency_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_llm_usage_day ON llm_usage(day);
CREATE INDEX IF NOT EXISTS ix_llm_usage_user ON llm_usage(user_id, day);
-- Bộ đếm giới hạn tần suất (cửa sổ cố định), bền vững qua khởi động lại.
CREATE TABLE IF NOT EXISTS rate_counters (
    key TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL,
    PRIMARY KEY (key, window_start)
);
-- Đã gửi cảnh báo chi phí mức nào (80, 100) trong ngày nào — để mỗi mức chỉ báo một lần mỗi ngày.
CREATE TABLE IF NOT EXISTS budget_alerts (day TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (day, level));
-- Đồng bộ tự động (002): mỗi nguồn của một người dùng; token Google vẫn ở google_accounts (mã hoá).
CREATE TABLE IF NOT EXISTS sync_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                  -- gmail | classroom | ics | sheet
    target TEXT NOT NULL DEFAULT '',     -- URL .ics / URL bảng đã chuẩn hoá; rỗng với gmail/classroom
    label TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    cursor TEXT,                         -- historyId Gmail, ETag .ics…
    state TEXT NOT NULL DEFAULT '{}',    -- JSON nhỏ (ánh xạ cột bảng, hạn watch, thống kê lượt gần nhất)
    next_run_at TEXT NOT NULL,
    lease_until TEXT,
    last_run_at TEXT, last_ok_at TEXT, last_error TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, kind, target)
);
CREATE INDEX IF NOT EXISTS ix_sync_due ON sync_connections(enabled, next_run_at);
-- Mục đã thấy ở nguồn: chống trùng và phát hiện thay đổi. task_id không FK cứng (việc có thể bị xoá).
CREATE TABLE IF NOT EXISTS source_items (
    connection_id INTEGER NOT NULL REFERENCES sync_connections(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    task_id INTEGER,
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    gone INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (connection_id, item_key)
);
CREATE TABLE IF NOT EXISTS push_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    notify INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, last_ok_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_push_user ON push_tokens(user_id);
"""

_initialized: set[str] = set()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    # table/column/decl là hằng số trong code, không bao giờ từ người dùng.
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _init(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        # Bản cũ (trước khi có tài khoản) không có cột user_id → bỏ dữ liệu demo cũ.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        if cols and "user_id" not in cols:
            log.warning("Phát hiện CSDL bản cũ (chưa có người dùng) — tạo lại các bảng dữ liệu.")
            conn.executescript(
                "DROP TABLE IF EXISTS tasks; DROP TABLE IF EXISTS messages; DROP TABLE IF EXISTS traces;"
            )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # Cột thêm sau (CSDL production đã có dữ liệu → chỉ ALTER khi thiếu, không tạo lại bảng).
    _ensure_column(conn, "tasks", "sources", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "tasks", "note", "TEXT")
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


@contextmanager
def connect():
    path = config.DB_PATH
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if path not in _initialized:
            _init(conn)
            _initialized.add(path)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
