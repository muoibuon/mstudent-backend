"""Connector email qua IMAP (Gmail/Outlook trường dùng App Password).

Biến môi trường: IMAP_HOST, IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER (mặc định INBOX).
"""

from __future__ import annotations

import email
import imaplib
import os
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from ..models import Message, Source


def _text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def fetch_unseen(limit: int = 20) -> list[Message]:
    box = imaplib.IMAP4_SSL(os.environ["IMAP_HOST"])
    box.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    box.select(os.getenv("IMAP_FOLDER", "INBOX"), readonly=True)
    _, data = box.search(None, "UNSEEN")
    out = []
    for num in data[0].split()[-limit:]:
        _, raw = box.fetch(num, "(BODY.PEEK[])")
        m = email.message_from_bytes(raw[0][1])
        received = parsedate_to_datetime(m["Date"]).isoformat() if m["Date"] else None
        out.append(
            Message(
                id=f"mail-{m.get('Message-ID', num.decode())}",
                source=Source.email,
                sender=str(make_header(decode_header(m.get("From", "")))),
                subject=str(make_header(decode_header(m.get("Subject", "")))),
                body=_text(m)[:5000],
                received_at=received,
            )
        )
    box.logout()
    return out
