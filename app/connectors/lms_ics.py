"""Connector LMS: đọc lịch iCal (.ics) xuất từ Moodle/Canvas.

Moodle: Calendar → Export calendar → copy URL. Không cần thư viện ngoài.
"""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime

from ..config import TZ
from ..models import Message, Source


def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parse_dt(value: str) -> str:
    v = value.split(":")[-1]
    fmt = "%Y%m%dT%H%M%S" if "T" in v else "%Y%m%d"
    dt = datetime.strptime(v.rstrip("Z"), fmt)
    dt = dt.replace(tzinfo=UTC) if v.endswith("Z") else dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).isoformat()


def parse_ics(text: str) -> list[Message]:
    msgs, ev = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            ev = {}
        elif line == "END:VEVENT" and ev is not None:
            due = ev.get("DTEND") or ev.get("DTSTART")
            body = ev.get("DESCRIPTION", "").replace("\\n", "\n")
            if due:
                d = datetime.fromisoformat(due)
                body += f"\nHạn: {d:%H:%M} ngày {d:%d/%m/%Y}"
            msgs.append(
                Message(
                    id=f"lms-{ev.get('UID', len(msgs))}",
                    source=Source.lms,
                    sender=ev.get("CATEGORIES", "LMS"),
                    subject=ev.get("SUMMARY", ""),
                    body=body,
                )
            )
            ev = None
        elif ev is not None and ":" in line:
            key, _, val = line.partition(":")
            name = key.split(";")[0]
            ev[name] = _parse_dt(line) if name in ("DTSTART", "DTEND") else val
    return msgs


def fetch(url: str) -> list[Message]:
    with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310 (URL do người dùng cung cấp)
        return parse_ics(r.read().decode("utf-8", "replace"))
