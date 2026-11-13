#!/usr/bin/env python3
"""Sao lưu CSDL SQLite của MStudent (an toàn khi server đang chạy, kể cả chế độ WAL).

    python backup.py <đường dẫn mstudent.db> <thư mục sao lưu> [số ngày giữ, mặc định 7]

Mỗi ngày một file mstudent-YYYYMMDD.db (chạy lại trong ngày thì ghi đè). Xoá bản cũ hơn số ngày giữ.
Thư mục sao lưu có quyền 700, file 600 — bản sao lưu chứa dữ liệu người dùng.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PREFIX = "mstudent-"


def backup(src: Path, dest_dir: Path, keep_days: int = 7, today: datetime | None = None) -> Path:
    if not src.is_file():
        raise SystemExit(f"Không tìm thấy CSDL: {src}")
    today = today or datetime.now()
    dest_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(dest_dir, 0o700)
    dest = dest_dir / f"{PREFIX}{today:%Y%m%d}.db"
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)

    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(tmp)
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")  # bản sao lưu là MỘT file, không kèm -wal/-shm
        ok = target.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        target.close()
        source.close()
    if ok != "ok":
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"Bản sao lưu hỏng (integrity_check: {ok})")
    os.chmod(tmp, 0o600)
    tmp.replace(dest)  # chỉ thay bản cũ khi bản mới đã kiểm tra xong

    cutoff = f"{PREFIX}{today - timedelta(days=keep_days):%Y%m%d}.db"
    for old in dest_dir.glob(f"{PREFIX}????????.db"):
        if old.name <= cutoff:
            old.unlink()
    return dest


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    out = backup(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 7)
    print(f"Đã sao lưu: {out} ({out.stat().st_size // 1024} KB)")
