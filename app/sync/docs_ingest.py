"""Tài liệu trong email → việc cần làm + tóm tắt (002 US7).

Mỗi tài liệu được lọc riêng: nội dung email bị loại không có nghĩa tài liệu đính kèm cũng là nhiễu. Mỗi tài liệu (tệp
đính kèm hoặc link Google công khai) được rút chữ, thu gọn rồi đưa qua pipeline như một thông báo riêng có id
`doc-<sha256 nội dung>` → cùng tài liệu đến lần hai không tốn AI (FR-084), vẫn qua GUARD/sanitize/budget. Việc tạo
ra từ tài liệu được ghi chú tóm tắt 2–3 câu (FR-083). Lỗi một tệp không làm hỏng email hay tệp khác.
"""

from __future__ import annotations

import hashlib
import logging

import anyio

from .. import budget, google_api, repo
from ..connectors import docs
from ..models import IngestResult, Message, Source
from ..pipeline import llm_agents, orchestrator
from . import sheets

log = logging.getLogger("mstudent")
LINK_LABEL = {"document": "Google Docs", "spreadsheets": "Google Sheets", "presentation": "Google Slides"}


async def _summary(uid: int, d: docs.DocText) -> str:
    if budget.llm_allowed(uid):
        try:
            return await llm_agents.llm_summarize_doc(d.name, docs.focus(d.text), uid)
        except Exception as e:
            log.warning("Tóm tắt tài liệu lỗi: %s", type(e).__name__)
    first = docs.focus(d.text, 240).split("\n")[0]
    return f"{d.name}: {first}"[:240]


async def ingest_documents(
    uid: int, token: str | None, gmail_id: str, msg: Message, attachments: list[dict], result: IngestResult
) -> list[IngestResult]:
    if result.duplicate:
        return []
    found: list[docs.DocText] = []
    problems: list[str] = []

    candidates = [a for a in attachments if docs.kind_of(a["name"], a["mime"])][: docs.MAX_FILES_PER_EMAIL]
    for att in candidates:
        try:
            if not token:
                raise docs.DocError("Không có quyền tải tệp")
            data = await google_api.get_attachment(token, gmail_id, att, docs.MAX_FILE_BYTES)
            found.append(await anyio.to_thread.run_sync(docs.extract_text, att["name"], att["mime"], data))
        except (docs.DocError, google_api.GoogleError) as e:
            problems.append(f"{att['name'][:60]}: {e}")

    for kind, _doc_id, url in docs.find_doc_links(msg.body):
        label = LINK_LABEL.get(kind, "Tài liệu Google")
        try:
            text = await sheets.fetch_google_export(url)
            found.append(docs.DocText(name=label, kind=kind, text=text.strip()))
        except sheets.SheetError as e:
            problems.append(
                f"{label}: tài liệu riêng tư — mở để xem"
                if e.args and e.args[0] == sheets.PRIVATE_MSG
                else f"{label}: {e}"
            )

    results: list[IngestResult] = []
    for d in found:
        if not d.text:
            continue
        mid = "doc-" + hashlib.sha256(d.text.encode()).hexdigest()[:24]
        if repo.get_message(uid, mid):
            continue  # cùng tài liệu đã xử lý (email chuyển tiếp…) → không chạy lại AI
        # Parent marketing text must not contaminate the independent document gate.
        body = f"Tệp: {d.name}\n---\n{docs.focus(d.text)}"
        out = await orchestrator.ingest(
            uid,
            Message(
                id=mid,
                source=Source.email,
                sender=msg.sender,
                subject=f"[Tệp] {d.name}"[:500],
                body=body[:8000],
                received_at=msg.received_at,
            ),
        )
        touched = out.created + out.updated
        if touched:
            note = await _summary(uid, d)
            for t in touched:
                repo.update_task(uid, t.id, {"note": note})
        results.append(out)

    if problems:  # ghi lại tệp không đọc được lên việc của chính email đó (nếu có)
        note = "Không đọc được: " + "; ".join(problems)[:250]
        for t in result.created + result.updated:
            if not t.note:
                repo.update_task(uid, t.id, {"note": note})
        repo.save_trace(
            uid,
            msg.id or f"gmail-{gmail_id}",
            result.mode,
            "Không đọc được tài liệu kèm email",
            [{"agent": "Documents", "kind": "python", "ms": 0, "output": {"errors": problems}}],
        )
    return results
