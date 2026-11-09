"""Connector Zalo.

Nhóm Zalo cá nhân KHÔNG có API công khai, nên MVP dùng 2 cách hợp lệ:
1. Sinh viên dán/chia sẻ tin nhắn vào MStudent (POST /ingest với source="zalo").
2. Dán cả đoạn chat đã copy: tách theo dòng "Tên người gửi: nội dung" bằng split_chat().
Nếu trường có Zalo Official Account thì có thể nhận webhook OA (ngoài phạm vi MVP).
"""

from __future__ import annotations

import re

from ..models import Message, Source

LINE_RE = re.compile(r"^\s*(?:\[?\d{1,2}:\d{2}\]?\s*)?([^:\n]{2,40}):\s+(.+)$")


def split_chat(text: str, group: str = "Nhóm lớp") -> list[Message]:
    msgs: list[Message] = []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if m:
            msgs.append(
                Message(source=Source.zalo, sender=f"{m.group(1).strip()} ({group})", body=m.group(2).strip())
            )
        elif msgs and line.strip():
            msgs[-1].body += "\n" + line.strip()
    return msgs
