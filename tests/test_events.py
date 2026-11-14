"""003-event-rsvp: lời mời sự kiện (Tham gia / Không), chi tiết, form đăng ký, mức phù hợp với ngành.

Không gọi mạng: LLM dùng Runner giả, Google Forms / Expo dùng httpx.MockTransport.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import repo
from app.models import Category, EventDetails, ExtractionOut, MajorFitOut, Message, TaskOut, TriageOut
from app.pipeline import events

from .conftest import auth, signup

FORM_ID = "1FAIpQLSc" + "a" * 47
FORM_URL = f"https://docs.google.com/forms/d/e/{FORM_ID}/viewform"
SEMINAR = {
    "subject": "Seminar Trí tuệ nhân tạo và lập trình ứng dụng",
    "body": (
        "Khoa tổ chức seminar về AI và lập trình lúc 14h00 ngày 20/11/2026 tại phòng 501.\n"
        f"Hạn đăng ký 18/11/2026. Đăng ký tại {FORM_URL}\n"
        "Chi tiết: https://vju.ac.vn/seminar-ai"
    ),
}
MANDATORY = {
    "body": "Hội thảo định hướng nghề nghiệp ngày 21/11/2026 lúc 9h00, bắt buộc tham dự, có điểm danh."
}
IT = {"school_name": "Trường ĐH Việt Nhật", "school_abbr": "VNU-VJU", "degree_level": "dai_hoc",
      "major_code": "7480201", "major_name": "Khoa học và Kỹ thuật máy tính"}  # fmt: skip
LANG = {**IT, "major_code": "7310613", "major_name": "Nhật Bản học"}


def _form_html(items) -> str:
    data = [None, [None, items], None]
    return f"<html><script>var FB_PUBLIC_LOAD_DATA_ = {json.dumps(data)};</script></html>"


FORM_ITEMS = [
    [1, "Họ và tên", None, 0, [[111, None, 1]]],
    [2, "Mã sinh viên (MSSV)", None, 0, [[222, None, 1]]],
    [3, "Email", None, 0, [[333, None, 0]]],
    [4, "Lớp", None, 0, [[444, None, 0]]],
    [5, "Bạn muốn hỏi diễn giả điều gì?", None, 1, [[555, None, 0]]],
    [6, "Bạn biết sự kiện qua đâu?", None, 2, [[666, [["Facebook"], ["Bạn bè"]], 0]]],
]


@pytest.fixture()
def forms(monkeypatch):
    """Google Forms giả. state['mode']: 'public' | 'private' (chuyển hướng sang trang đăng nhập)."""
    state = {"mode": "public", "hits": []}

    def handler(req: httpx.Request):
        state["hits"].append(str(req.url))
        if state["mode"] == "private":
            return httpx.Response(302, headers={"location": "https://accounts.google.com/ServiceLogin"})
        return httpx.Response(200, text=_form_html(FORM_ITEMS))

    monkeypatch.setattr(events, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(events, "_check_host", lambda host: _allow(host))
    return state


def _allow(host: str) -> None:
    if host.lower() not in events.FORM_HOSTS:
        raise ValueError("host không được phép")


def _ingest(client, h, msg):
    r = client.post("/api/ingest", json=msg, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _events(client, h, state="pending"):
    r = client.get(f"/api/events?state={state}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _rsvp(client, h, tid, going):
    return client.post(f"/api/tasks/{tid}/rsvp", json={"going": going}, headers=h)


# ---------------- US2: lời mời ----------------


def test_event_notice_becomes_pending_invite_with_details(client, user, forms):
    h, _ = user
    out = _ingest(client, h, SEMINAR)
    assert out["category"] == "event" and out["mode"] == "offline"
    (t,) = out["created"]
    assert t["rsvp"] == "pending" and not t["mandatory"]
    assert t["register_url"] == FORM_URL and t["event_url"] == "https://vju.ac.vn/seminar-ai"
    assert t["register_deadline"].startswith("2026-11-18T23:59")
    assert t["due_at"].startswith("2026-11-20T14:00")
    assert t["form_meta"] == {
        "form_id": FORM_ID,
        "fields": [
            {"entry": "111", "role": "name"},
            {"entry": "222", "role": "student_id"},
            {"entry": "333", "role": "email"},
            {"entry": "444", "role": "class_name"},
        ],
    }
    # Lời mời chưa trả lời không nằm trong danh sách việc, chỉ ở /api/events.
    assert client.get("/api/tasks", headers=h).json() == []
    assert [e["id"] for e in _events(client, h)] == [t["id"]]
    assert any(s["agent"] == "EventDetails" and s["kind"] == "rules" for s in out["trace"])


def test_going_schedules_event_and_creates_registration_task(client, user, forms):
    h, _ = user
    (t,) = _ingest(client, h, SEMINAR)["created"]
    r = _rsvp(client, h, t["id"], True)
    assert r.status_code == 200 and r.json()["rsvp"] == "going"
    assert r.json()["reminders"] == ["2026-11-19T14:00:00+07:00", "2026-11-20T12:00:00+07:00"]
    tasks = client.get("/api/tasks", headers=h).json()
    reg = next(x for x in tasks if x["id"] != t["id"])
    assert {x["id"] for x in tasks} == {t["id"], reg["id"]}
    assert reg["title"].startswith("Đăng ký: ") and reg["due_at"].startswith("2026-11-18T23:59")
    assert reg["rsvp"] is None and reg["category"] == "deadline"

    # Đổi ý: Không → ẩn khỏi danh sách việc, việc đăng ký đóng lại; vẫn xem được ở "Đã bỏ qua".
    assert _rsvp(client, h, t["id"], False).json()["rsvp"] == "declined"
    assert client.get("/api/tasks", headers=h).json() == []
    assert [e["id"] for e in _events(client, h, "declined")] == [t["id"]]

    # Đổi ý lần nữa: Tham gia → mở lại đúng việc đăng ký cũ, không tạo trùng.
    assert _rsvp(client, h, t["id"], True).json()["rsvp"] == "going"
    again = client.get("/api/tasks", headers=h).json()
    assert {x["id"] for x in again} == {t["id"], reg["id"]}


def test_mandatory_event_goes_straight_to_calendar_and_cannot_decline(client, user):
    h, _ = user
    (t,) = _ingest(client, h, MANDATORY)["created"]
    assert t["mandatory"] is True and t["rsvp"] == "going"
    assert [x["id"] for x in client.get("/api/tasks", headers=h).json()] == [t["id"]]
    assert _events(client, h) == []
    r = _rsvp(client, h, t["id"], False)
    assert r.status_code == 409


def test_rsvp_rejects_plain_task_and_other_users(client, user):
    h, _ = user
    (plain,) = _ingest(client, h, {"body": "Các em nộp bài tập tuần 9 trước 23h59 thứ 6 tuần này nhé."})[
        "created"
    ]
    assert plain["rsvp"] is None
    assert _rsvp(client, h, plain["id"], True).status_code == 400

    (invite,) = _ingest(client, h, {"body": "Workshop kỹ năng viết CV ngày 25/11/2026 lúc 15h00."})["created"]
    other = auth(signup(client, "b@vju.ac.vn"))
    assert _rsvp(client, other, invite["id"], True).status_code == 404
    assert _events(client, other) == []
    assert _rsvp(client, h, 99999, True).status_code == 404
    assert client.get("/api/events").status_code == 401
    assert client.post(f"/api/tasks/{invite['id']}/rsvp", json={"going": True}).status_code == 401
    assert client.get("/api/events?state=all", headers=h).status_code == 422
    assert _events(client, h)[0]["rsvp"] == "pending"  # người khác không đổi được


def test_pending_invite_hidden_after_event_passed(client, user, monkeypatch):
    h, _ = user
    (t,) = _ingest(client, h, {"body": "Talkshow khởi nghiệp ngày 12/11/2026 lúc 18h00 tại hội trường."})[
        "created"
    ]
    assert len(_events(client, h)) == 1
    monkeypatch.setenv("MSTUDENT_NOW", "2026-11-13T08:00:00+07:00")
    assert _events(client, h) == []
    # Không xoá dữ liệu: quay lại trước giờ sự kiện thì vẫn còn.
    monkeypatch.setenv("MSTUDENT_NOW", "2026-11-10T08:00:00+07:00")
    assert [e["id"] for e in _events(client, h)] == [t["id"]]


def test_unsafe_links_dropped():
    assert events.safe_url("javascript:alert(1)") is None
    assert events.safe_url("file:///etc/passwd") is None
    assert events.safe_url("intent://x#Intent;end") is None
    assert events.safe_url("https://") is None
    assert events.safe_url("https://a.vn/" + "x" * 600) is None
    assert events.safe_url(" https://vju.ac.vn/su-kien. ") == "https://vju.ac.vn/su-kien"
    assert events.is_form_url("https://forms.gle/abc") and events.is_form_url(FORM_URL)
    assert not events.is_form_url("http://docs.google.com/forms/d/e/x/viewform")  # không phải https
    assert not events.is_form_url("https://docs.google.com.evil.vn/forms/d/e/x/viewform")
    assert not events.is_form_url("https://docs.google.com/spreadsheets/d/x")


def test_private_form_gives_no_form_meta(client, user, forms):
    h, _ = user
    forms["mode"] = "private"
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["register_url"] == FORM_URL and t["form_meta"] is None
    assert forms["hits"] == [FORM_URL]  # không đi theo chuyển hướng ra ngoài allowlist


def test_form_fetch_never_leaves_allowlist(forms):
    assert asyncio.run(events.fetch_form_meta("https://evil.example/forms/d/e/x/viewform")) is None
    assert asyncio.run(events.fetch_form_meta("http://169.254.169.254/latest/meta-data")) is None
    assert forms["hits"] == []


def test_form_parser_ignores_malformed_and_non_text_questions():
    assert events.parse_form("<html>không có dữ liệu</html>", FORM_URL) is None
    assert events.parse_form(_form_html("không phải danh sách"), FORM_URL) is None
    assert events.parse_form(_form_html(FORM_ITEMS), "https://docs.google.com/forms/d/abc/edit") is None
    only_choice = [[6, "Lớp", None, 2, [[666, [["A"]], 0]]], [7, "Họ tên", None, 0, None], "rác"]
    assert events.parse_form(_form_html(only_choice), FORM_URL) is None
    assert events.role_of("Email trường cấp") == "email"
    assert events.role_of("Số điện thoại / Zalo") == "phone"
    assert events.role_of("Ngành học") == "major"
    assert events.role_of("Trường") == "school"
    assert events.role_of("Bạn mong chờ gì?") is None


def test_invite_push_has_action_category(client, user, forms, monkeypatch):
    from app.sync import notify, scheduler

    sent: list[list[dict]] = []

    def handler(req):
        msgs = json.loads(req.content)
        sent.append(msgs)
        return httpx.Response(200, json={"data": [{"status": "ok"} for _ in msgs]})

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(handler))
    h, _ = user
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    client.put("/api/profile", json=IT, headers=h)
    repo.upsert_push_token(uid, "ExponentPushToken[on]", "android", True)
    conn = repo.create_connection(uid, "gmail", "", "sv@gmail.com")
    out = asyncio.run(_orch(uid, Message(**SEMINAR)))
    asyncio.run(notify.after_run(conn, scheduler.RunResult(created=out.created), False))
    (msg,) = sent[0]
    assert msg["categoryId"] == "event_invite"
    assert msg["data"] == {"type": "invite", "task_id": out.created[0].id}
    assert msg["title"].startswith("Sự kiện mới: ")
    assert msg["body"] == "Rất hợp ngành · T6 20/11 14:00 · Tham gia không?"
    assert SEMINAR["body"][:30] not in json.dumps(msg, ensure_ascii=False)  # không gửi nội dung tin gốc


async def _orch(uid, msg):
    from app.pipeline import orchestrator

    return await orchestrator.ingest(uid, msg)


# ---------------- Đường LLM (Runner giả) ----------------


class _FakeResult:
    def __init__(self, output):
        self.final_output = output
        self.new_items = []
        self.context_wrapper = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=20))


@pytest.fixture()
def llm_on(monkeypatch):
    from app.pipeline import llm_agents

    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    calls: list[tuple[str, str]] = []
    out = {
        "details": EventDetails(
            start_at="2026-11-20T14:00:00+07:00",
            end_at="2026-11-20T16:30:00+07:00",
            location="Phòng 501",
            event_url="javascript:alert(1)",  # model bị lừa chép link độc → phải bị bỏ
            register_url=FORM_URL,
            register_deadline="không phải ngày",
            organizer="Khoa CNTT",
            mandatory=False,
        ),
        "fit": MajorFitOut(level="high", reason="Sát ngành Khoa học và Kỹ thuật máy tính: thực hành AI."),
    }

    async def fake_run(agent, payload, **kwargs):
        calls.append((agent.name, payload if isinstance(payload, str) else ""))
        if agent.name == "Triage":
            return _FakeResult(TriageOut(relevant=True, category=Category.event, reason="sự kiện"))
        if agent.name == "Extractor":
            return _FakeResult(
                ExtractionOut(
                    tasks=[
                        TaskOut(
                            title="Seminar AI",
                            course=None,
                            category=Category.event,
                            due_at=None,
                            location=None,
                            action="Tham dự",
                        )  # fmt: skip
                    ]
                )
            )
        if agent.name == "EventDetails":
            return _FakeResult(out["details"])
        if agent.name == "MajorFit":
            if isinstance(out["fit"], Exception):
                raise out["fit"]
            return _FakeResult(out["fit"])
        return _FakeResult("xong")

    monkeypatch.setattr(llm_agents.Runner, "run", fake_run)
    return calls, out


def test_llm_details_are_sanitized_and_fit_uses_profile_only(client, user, forms, llm_on):
    calls, _ = llm_on
    h, _ = user
    client.put("/api/profile", json={**IT, "student_id": "21020001", "phone": "0912345678"}, headers=h)
    out = _ingest(client, h, SEMINAR)
    (t,) = out["created"]
    assert out["mode"] == "llm" and t["rsvp"] == "pending"
    assert t["due_at"] == "2026-11-20T14:00:00+07:00" and t["event_end"] == "2026-11-20T16:30:00+07:00"
    assert t["location"] == "Phòng 501" and t["note"] == "Tổ chức: Khoa CNTT"
    assert t["event_url"] == "https://vju.ac.vn/seminar-ai"  # link độc bị bỏ, lấy link thật trong tin
    assert t["register_deadline"].startswith("2026-11-18")  # ngày sai định dạng của model → luật
    assert t["fit_level"] == "high" and t["fit_mode"] == "llm" and "máy tính" in t["fit_reason"]
    assert [c[0] for c in calls] == ["Triage", "Extractor", "EventDetails", "MajorFit"]
    fit_payload = calls[-1][1]
    assert "Khoa học và Kỹ thuật máy tính" in fit_payload and "<thong_bao>" in fit_payload
    assert "21020001" not in fit_payload and "0912345678" not in fit_payload  # không gửi MSSV / SĐT cho LLM


def test_fit_llm_failure_falls_back_to_rules(client, user, forms, llm_on):
    _, out = llm_on
    out["fit"] = RuntimeError("hết credit")
    h, _ = user
    client.put("/api/profile", json=IT, headers=h)
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["fit_mode"] == "offline" and t["fit_level"] == "high"


# ---------------- US3: phù hợp với ngành ----------------


def test_fit_rules_differ_by_major_and_mention_major():
    text = "Workshop lập trình AI và machine learning cho sinh viên"
    it = events.fit_rules("Khoa học và Kỹ thuật máy tính", text)
    lang = events.fit_rules("Nhật Bản học", text)
    assert it.level == "high" and "Khoa học và Kỹ thuật máy tính" in it.reason
    assert lang.level == "low" and "Nhật Bản học" in lang.reason
    jp = "Giao lưu văn hoá và thi thử JLPT cùng sinh viên Nhật"
    assert events.fit_rules("Nhật Bản học", jp).level == "high"
    assert events.fit_rules("Khoa học và Kỹ thuật máy tính", jp).level == "low"
    general = events.fit_rules("Nhật Bản học", "Ngày hội việc làm và hướng nghiệp 2026")
    assert general.level == "medium" and "Nhật Bản học" in general.reason
    assert events.fit_rules("Kỹ thuật xây dựng", "Lễ kỷ niệm ngày nhà giáo").level == "medium"
    assert all(len(x.reason) <= 200 for x in (it, lang, general))


def test_no_major_means_no_fit_then_profile_change_reassesses(client, user, forms):
    h, _ = user
    (t,) = _ingest(client, h, SEMINAR)["created"]
    assert t["fit_level"] is None and t["fit_reason"] is None and t["fit_mode"] is None

    assert client.put("/api/profile", json=IT, headers=h).status_code == 200
    (e,) = _events(client, h)
    assert e["fit_level"] == "high" and e["fit_mode"] == "offline"

    assert client.put("/api/profile", json=LANG, headers=h).status_code == 200
    (e,) = _events(client, h)
    assert e["fit_level"] == "low" and "Nhật Bản học" in e["fit_reason"] and e["fit_mode"] == "offline"


def test_reassess_only_touches_own_pending_invites(client, user, forms):
    h, _ = user
    other = auth(signup(client, "b@vju.ac.vn"))
    client.put("/api/profile", json=LANG, headers=other)
    (theirs,) = _ingest(client, other, SEMINAR)["created"]
    (mine,) = _ingest(client, h, SEMINAR)["created"]
    _rsvp(client, h, mine["id"], True)  # đã trả lời → không tính lại
    client.put("/api/profile", json=IT, headers=h)
    assert _events(client, h, "going")[0]["fit_level"] is None
    assert _events(client, other)[0]["fit_level"] == theirs["fit_level"] == "low"


def test_event_triage_with_registration_only_task_still_becomes_invite(
    client, user, forms, llm_on, monkeypatch
):
    """Lỗi thật trên máy chủ: Triage = event nhưng Extractor trả việc "Đăng ký …" (deadline, hạn = hạn đăng ký)."""
    from app.pipeline import llm_agents

    _, out = llm_on
    out["details"] = out["details"].model_copy(update={"register_deadline": None, "register_url": None})
    inner = llm_agents.Runner.run

    async def run(agent, payload, **kwargs):
        if agent.name == "Extractor":
            return _FakeResult(
                ExtractionOut(
                    tasks=[
                        TaskOut(
                            title="Đăng ký Seminar AI",
                            course=None,
                            category=Category.deadline,
                            due_at="2026-11-18T23:59:00+07:00",
                            location=None,
                            action="Đăng ký",
                        )  # fmt: skip
                    ]
                )
            )
        return await inner(agent, payload, **kwargs)

    monkeypatch.setattr(llm_agents.Runner, "run", run)
    h, _ = user
    (t,) = _ingest(client, h, {**SEMINAR, "body": SEMINAR["body"].replace("Hạn đăng ký 18/11/2026. ", "")})[
        "created"
    ]
    assert t["category"] == "event" and t["rsvp"] == "pending"
    assert t["due_at"] == "2026-11-20T14:00:00+07:00"  # giờ sự kiện, không phải hạn đăng ký
    assert t["register_deadline"] == "2026-11-18T23:59:00+07:00"
    assert client.get("/api/tasks", headers=h).json() == []
