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

# Mỗi lượt chỉ xử lý tối đa N mục mới/đổi (phần còn lại để lượt sau) và nhường event loop sau mỗi mục,
# để một nguồn rất lớn (cố ý hay vô tình) không làm treo máy chủ của mọi người.
MAX_ITEMS_PER_RUN = 300
MAX_ITEMS_SEEN = 5000


def short_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def guess_category(title: str) -> Category:
    t = planner.fold(title)
    return Category.exam if re.search(r"\b(thi|kiem tra|quiz|midterm|final|exam)\b", t) else Category.deadline


# is_global coi các địa chỉ này là công khai nhưng chúng trỏ vào hạ tầng nội bộ của nhà cung cấp đám mây.
_BLOCKED = {ipaddress.ip_address("168.63.129.16")}  # Azure WireServer
_BLOCKED_V6 = [ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("::/96")]


def ensure_public_host(host: str, port: int = 443) -> None:
    """Chống SSRF: mọi IP của tên miền phải là địa chỉ công khai."""
    try:
        infos = socket.getaddrinfo(host, port)
    except socket.gaierror as e:
        raise TemporaryError("Không phân giải được tên miền, sẽ thử lại") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        mapped = getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
        if not ip.is_global or ip in _BLOCKED or (mapped and (not mapped.is_global or mapped in _BLOCKED)):
            raise TemporaryError("Link trỏ tới địa chỉ nội bộ — không được phép")
        if ip.version == 6 and any(ip in n for n in _BLOCKED_V6):
            raise TemporaryError("Link trỏ tới địa chỉ nội bộ — không được phép")


def ensure_public_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise TemporaryError("Chỉ nhận đường dẫn http(s)")
    ensure_public_host(u.hostname, u.port or (443 if u.scheme == "https" else 80))
