"""Cấu hình qua biến môi trường."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_dotenv() -> None:
    """Đọc backend/.env (nếu có) mà không cần python-dotenv. Biến đã có trong môi trường được giữ nguyên."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

TZ = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")

DB_PATH = os.getenv("MSTUDENT_DB", "mstudent.db")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


def llm_enabled() -> bool:
    """Dùng LLM khi có OPENAI_API_KEY và không ép chế độ offline."""
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("MSTUDENT_OFFLINE") != "1"


def now() -> datetime:
    """Giờ hiện tại (+07:00). Đặt MSTUDENT_NOW=2026-11-10T08:00 để demo ổn định."""
    fixed = os.getenv("MSTUDENT_NOW")
    if fixed:
        dt = datetime.fromisoformat(fixed)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    return datetime.now(TZ)
