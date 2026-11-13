"""Tiện ích dùng chung cho các runner đồng bộ."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from urllib.parse import urlparse

from ..models import Category
from ..pipeline import planner
from .scheduler import TemporaryError


def short_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def guess_category(title: str) -> Category:
    t = planner.fold(title)
    return Category.exam if re.search(r"\b(thi|kiem tra|quiz|midterm|final|exam)\b", t) else Category.deadline


def ensure_public_host(host: str, port: int = 443) -> None:
    """Chống SSRF: mọi IP của tên miền phải là địa chỉ công khai."""
    try:
        infos = socket.getaddrinfo(host, port)
    except socket.gaierror as e:
        raise TemporaryError("Không phân giải được tên miền, sẽ thử lại") from e
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise TemporaryError("Link trỏ tới địa chỉ nội bộ — không được phép")


def ensure_public_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise TemporaryError("Chỉ nhận đường dẫn http(s)")
    ensure_public_host(u.hostname, u.port or (443 if u.scheme == "https" else 80))
