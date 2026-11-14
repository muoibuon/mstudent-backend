"""Luồng chính qua API (chế độ offline) + cách ly dữ liệu giữa người dùng."""

from tests.conftest import auth, signup


def test_requires_login(client):
    for method, path in [
        ("get", "/api/tasks"),
        ("post", "/api/demo/seed"),
        ("get", "/api/digest"),
        ("get", "/api/traces"),
        ("get", "/api/stats"),
        ("get", "/api/agents/config"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/api/ingest", json={"body": "x"}).status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/tasks", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_seed_dedupes_extension(client, user):
    h, _ = user
    results = client.post("/api/demo/seed", headers=h).json()
    assert sum(r["relevant"] for r in results) == 7
    tasks = client.get("/api/tasks", headers=h).json()
    lab = [t for t in tasks if "Lab 3" in t["title"]]
    assert len(lab) == 1, "tin gia hạn phải cập nhật task cũ, không tạo task mới"
    assert lab[0]["due_at"].startswith("2026-11-15T23:59")
    assert lab[0]["updated_from"] == ["demo-08"]


def test_trace_and_duplicate(client, user):
    h, _ = user
    body = {"source": "zalo", "body": "Nộp bài tập trước 23h59 ngày 20/11"}
    r = client.post("/api/ingest", json=body, headers=h).json()
    assert [s["agent"] for s in r["trace"]] == ["Triage", "Extractor", "Planner"]
    assert client.get("/api/traces", headers=h).json()[0]["message_id"] == r["message_id"]
    again = client.post("/api/ingest", json=body, headers=h).json()
    assert again["duplicate"] is True and again["created"] == []
    assert len(client.get("/api/tasks", headers=h).json()) == 1


def test_chat_offline_tools(client, user):
    h, _ = user
    client.post("/api/demo/seed", headers=h)
    r = client.post("/api/chat", json={"message": "Tuần này có gì?"}, headers=h).json()
    assert r["tool_calls"][0]["tool"] == "list_tasks" and "#" in r["reply"]
    r = client.post("/api/chat", json={"message": "thêm: thứ 6 tuần sau nộp đồ án OOP"}, headers=h).json()
    assert r["tool_calls"][0]["tool"] == "add_notice" and "Đã tạo" in r["reply"]
    tid = client.get("/api/tasks", headers=h).json()[0]["id"]
    r = client.post("/api/chat", json={"message": f"xong {tid}"}, headers=h).json()
    assert r["tool_calls"][0]["tool"] == "complete_task"
    assert all(t["id"] != tid for t in client.get("/api/tasks", headers=h).json())
    assert (
        client.post("/api/chat", json={"message": "bản tin"}, headers=h).json()["tool_calls"][0]["tool"]
        == "get_digest"
    )


def test_chat_file_requires_login_and_reads_document(client, user):
    h, _ = user
    document = ("Lịch thi học kỳ\nThi Toán lúc 09:00 ngày 20/11 tại phòng B201.\n").encode()
    files = {"file": ("lich-thi.txt", document, "text/plain")}
    assert client.post("/api/chat/file", files=files).status_code == 401
    response = client.post("/api/chat/file", files=files, headers=h)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "offline" and "lich-thi.txt" in body["reply"]
    assert "20/11" in body["reply"]
    assert "<thong_bao>" in body["document_context"]
    assert client.get("/api/tasks", headers=h).json() == [], "đính kèm không tự tạo việc"
    response = client.post(
        "/api/chat/file", files=files, data={"message": "Hãy tạo việc từ tài liệu này"}, headers=h
    )
    assert response.status_code == 200 and response.json()["tool_calls"][0]["tool"] == "add_notice"
    assert len(client.get("/api/tasks", headers=h).json()) == 1


def test_chat_file_rejects_unsupported_and_oversized(client, user):
    h, _ = user
    bad_type = client.post("/api/chat/file", files={"file": ("photo.png", b"x", "image/png")}, headers=h)
    assert bad_type.status_code == 400
    too_big = client.post(
        "/api/chat/file",
        files={"file": ("notes.txt", b"a" * (5 * 1024 * 1024 + 1), "text/plain")},
        headers=h,
    )
    assert too_big.status_code == 400 and "5 MB" in too_big.json()["detail"]


def test_chat_file_accepts_iphone_tab_separated_csv(client, user):
    h, _ = user
    data = 'Môn\tNgày\tViệc\rOOP\t20/11\t"Nộp bài"\r'.encode()
    response = client.post("/api/chat/file", files={"file": ("lich-tuan.csv", data, "text/csv")}, headers=h)
    assert response.status_code == 200, response.text
    assert "OOP | 20/11 | Nộp bài" in response.json()["document_context"]


def test_chat_file_imports_weekly_csv_without_duplicates_or_cross_user_data(client, user):
    h, _ = user
    data = (
        "Môn\tNgày\tBắt đầu\tKết thúc\tLặp lại\r"
        "Xác suất - Thống kê\t09/09/2026\t08:00\t11:00\tHàng tuần (Thứ Tư)\r"
        "Thí nghiệm khoa học\t11/09/2026\t08:00\t11:00\tHàng tuần (Thứ Sáu)\r"
    ).encode()
    files = {"file": ("lich-hoc.csv", data, "text/csv")}
    payload = {"message": "Thêm lịch này vào lịch app"}
    first = client.post("/api/chat/file", files=files, data=payload, headers=h)
    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "offline"
    assert first.json()["tool_calls"][0]["tool"] == "import_schedule"
    tasks = client.get("/api/tasks", headers=h).json()
    assert [t["due_at"][:16] for t in tasks] == ["2026-11-11T08:00", "2026-11-13T08:00"]
    assert all(t["title"].startswith("Học ") for t in tasks)

    repeat = client.post("/api/chat/file", files=files, data=payload, headers=h)
    assert repeat.status_code == 200 and "không tạo trùng" in repeat.json()["reply"]
    assert len(client.get("/api/tasks", headers=h).json()) == 2

    other = auth(signup(client, "student2@vju.ac.vn"))
    assert client.get("/api/tasks", headers=other).json() == []


def test_chat_imports_schedule_from_previous_file_context(client, user):
    h, _ = user
    data = b"Mon,Ngay,Bat dau,Ket thuc,Lap lai\nOOP,09/09/2026,08:00,10:00,Hang tuan (Thu Tu)\n"
    upload = client.post("/api/chat/file", files={"file": ("lich.csv", data, "text/csv")}, headers=h)
    assert upload.status_code == 200
    assert client.get("/api/tasks", headers=h).json() == []
    followup = client.post(
        "/api/chat",
        json={
            "message": "thêm lịch này vào lịch app",
            "history": [{"role": "user", "content": upload.json()["document_context"]}],
        },
        headers=h,
    )
    assert followup.status_code == 200, followup.text
    assert len(client.get("/api/tasks", headers=h).json()) == 1


def test_chat_schedule_does_not_reuse_past_one_off_dates(client, user):
    h, _ = user
    data = b"Mon,Ngay,Bat dau\nOOP,09/09/2026,08:00\n"
    response = client.post(
        "/api/chat/file",
        files={"file": ("old.csv", data, "text/csv")},
        data={"message": "Thêm lịch này vào lịch app"},
        headers=h,
    )
    assert response.status_code == 200
    assert "những ngày đã qua" in response.json()["reply"]
    assert client.get("/api/tasks", headers=h).json() == []


def test_patch_recomputes_reminders(client, user):
    h, _ = user
    client.post("/api/demo/seed", headers=h)
    t = client.get("/api/tasks", headers=h).json()[0]
    new = "2026-11-25" + t["due_at"][10:]
    r = client.patch(f"/api/tasks/{t['id']}", json={"due_at": new}, headers=h).json()
    assert r["due_at"] == new and all(x.startswith("2026-11-2") for x in r["reminders"])
    assert client.patch("/api/tasks/999999", json={"status": "done"}, headers=h).status_code == 404
    assert client.patch(f"/api/tasks/{t['id']}", json={"due_at": "hôm nào đó"}, headers=h).status_code == 422
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "deleted"}, headers=h).status_code == 422


def test_users_cannot_touch_each_other(client):
    """Cách ly dữ liệu: B không xem/sửa/hoàn thành được việc của A, kể cả qua trợ lý chat."""
    a, b = auth(signup(client, "a@x.vn")), auth(signup(client, "b@x.vn"))
    client.post("/api/demo/seed", headers=a)
    a_tasks = client.get("/api/tasks", headers=a).json()
    tid = a_tasks[0]["id"]
    assert client.get("/api/tasks", headers=b).json() == []
    assert client.get("/api/traces", headers=b).json() == []
    assert client.post(f"/api/tasks/{tid}/done", headers=b).status_code == 404
    assert client.patch(f"/api/tasks/{tid}", json={"title": "hacked"}, headers=b).status_code == 404
    r = client.post("/api/chat", json={"message": f"xong {tid}"}, headers=b).json()
    assert "Không tìm thấy" in r["reply"]
    # B nạp demo riêng không xoá dữ liệu của A
    client.post("/api/demo/seed", headers=b)
    assert [t["id"] for t in client.get("/api/tasks", headers=a).json()] == [t["id"] for t in a_tasks]
    assert client.get("/api/stats", headers=b).json()["messages_read"] == 9


def test_stats(client, user):
    h, _ = user
    client.post("/api/demo/seed", headers=h)
    s = client.get("/api/stats", headers=h).json()
    assert s["messages_read"] == 9 and s["noise_filtered"] == 2
    assert s["tasks_created"] == 6 and s["changes_caught"] == 1 and s["ai_runs"] == 0


def test_admin_only_config_and_eval(client, monkeypatch):
    normal = auth(signup(client, "sv@x.vn"))
    boss = auth(signup(client, "boss@x.vn"))
    monkeypatch.setenv("MSTUDENT_ADMIN_EMAILS", "boss@x.vn")
    assert client.put("/api/agents/config", json={"model": "x"}, headers=normal).status_code == 403
    assert client.post("/api/eval", headers=normal).status_code == 403
    assert client.get("/api/admin/audit", headers=normal).status_code == 403
    view = client.get("/api/agents/config", headers=normal).json()
    assert view["can_edit"] is False and "triage_prompt" not in view["config"]
    saved = client.put("/api/agents/config", json={"model": "gpt-test", "unknown": "x"}, headers=boss).json()
    assert saved["config"]["model"] == "gpt-test" and "unknown" not in saved["config"]
    assert client.post("/api/agents/config/reset", headers=boss).status_code == 200
    ev = client.post("/api/eval", headers=boss).json()
    assert ev["mode"] == "offline" and ev["scores"]["relevant"]["pct"] == 100
    assert any(
        a["event"] == "agent_config_changed" for a in client.get("/api/admin/audit", headers=boss).json()
    )


def test_ai_check_reports_offline(client, user):
    h, _ = user
    r = client.post("/api/ai/check", headers=h).json()
    assert r["ok"] is False and r["mode"] == "offline"


def test_hardening(client, user):
    h, _ = user
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert (
        "access-control-allow-origin"
        not in client.get("/api/health", headers={"Origin": "https://evil.example"}).headers
    )
    # body quá lớn / trường quá dài
    assert (
        client.post(
            "/api/ingest", content=b"x" * 300_000, headers={**h, "Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert client.post("/api/ingest", json={"body": "a" * 9000}, headers=h).status_code == 422
    assert client.post("/api/chat", json={"message": "a" * 5000}, headers=h).status_code == 422
    # SSRF: không cho đọc lịch từ địa chỉ nội bộ
    for url in ["http://127.0.0.1:8000/x.ics", "http://169.254.169.254/latest", "file:///etc/passwd"]:
        assert client.post("/api/ingest/lms-ics", json={"url": url}, headers=h).status_code == 400, url


def test_ai_rate_limit(client, user):
    h, _ = user
    codes = [client.post("/api/chat", json={"message": "chào"}, headers=h).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[-1] == 429


# ---------------- Nguồn tự động (002): cách ly người dùng ----------------


def _fake_probe(monkeypatch):
    from app.routers import sources

    async def probe(kind, url):
        return url, "Bảng thử"

    monkeypatch.setattr(sources, "_probe", probe)


def test_sources_require_login_and_are_isolated(client, monkeypatch):
    _fake_probe(monkeypatch)
    assert client.get("/api/sources").status_code == 401
    assert (
        client.post(
            "/api/push/register", json={"token": "ExponentPushToken[x]", "platform": "android"}
        ).status_code
        == 401
    )
    a, b = auth(signup(client, "a@x.vn")), auth(signup(client, "b@x.vn"))
    r = client.post(
        "/api/sources",
        json={"kind": "sheet", "url": "https://docs.google.com/spreadsheets/d/abc/edit"},
        headers=a,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert "target" not in r.json() and r.json()["label"] == "Bảng thử"
    assert client.get("/api/sources", headers=b).json() == []
    assert client.patch(f"/api/sources/{sid}", json={"enabled": False}, headers=b).status_code == 404
    assert client.post(f"/api/sources/{sid}/sync", headers=b).status_code == 404
    assert client.delete(f"/api/sources/{sid}", headers=b).status_code == 404
    assert client.patch(f"/api/sources/{sid}", json={"enabled": False}, headers=a).json()["enabled"] is False
    assert client.delete(f"/api/sources/{sid}", headers=a).status_code == 200
    assert client.get("/api/sources", headers=a).json() == []


def test_sources_limits_and_duplicates(client, user, monkeypatch):
    _fake_probe(monkeypatch)
    h, _ = user
    url = "https://docs.google.com/spreadsheets/d/{}/edit"
    assert (
        client.post("/api/sources", json={"kind": "sheet", "url": url.format(0)}, headers=h).status_code
        == 201
    )
    assert (
        client.post("/api/sources", json={"kind": "sheet", "url": url.format(0)}, headers=h).status_code
        == 409
    )
    for i in range(1, 10):
        assert (
            client.post("/api/sources", json={"kind": "sheet", "url": url.format(i)}, headers=h).status_code
            == 201
        )
    assert (
        client.post("/api/sources", json={"kind": "sheet", "url": url.format(99)}, headers=h).status_code
        == 422
    )
    assert client.post("/api/sources", json={"kind": "gmail", "url": "x"}, headers=h).status_code == 422


def test_push_tokens_are_owned_per_user(client):
    import sqlite3

    from app import config

    a, b = auth(signup(client, "a@x.vn")), auth(signup(client, "b@x.vn"))
    tok = {"token": "ExponentPushToken[abc123]", "platform": "android", "notify": True}
    assert (
        client.post("/api/push/register", json={**tok, "token": "not-a-token"}, headers=a).status_code == 422
    )
    assert client.post("/api/push/register", json=tok, headers=a).status_code == 200
    client.request("DELETE", "/api/push/register", json=tok, headers=b)  # B không xoá được token của A
    db = sqlite3.connect(config.DB_PATH)
    assert db.execute("SELECT COUNT(*) FROM push_tokens").fetchone()[0] == 1
    assert (
        client.post("/api/push/register", json=tok, headers=b).status_code == 200
    )  # máy đổi tài khoản → chuyển chủ
    owner = db.execute("SELECT u.email FROM push_tokens p JOIN users u ON u.id=p.user_id").fetchone()[0]
    assert owner == "b@x.vn"


# ---------------- 003: danh mục trường/ngành + hồ sơ ----------------


def test_catalog_requires_login_and_supports_etag(client, user):
    assert client.get("/api/catalog").status_code == 401
    r = client.get("/api/catalog", headers=user[0])
    assert r.status_code == 200 and r.headers.get("etag")
    data = r.json()
    abbrs = {s["abbr"] for s in data["schools"]}
    assert {"HUST", "VNU-VJU", "NEU"} <= abbrs and len(data["schools"]) > 250
    assert set(data["majors"]) == {"dai_hoc", "thac_si", "tien_si"}
    assert any(m["name"] == "Khoa học máy tính" for m in data["majors"]["dai_hoc"])
    assert (
        data["programs"]["VNU-VJU"]["dai_hoc"] and "Thông tư 09/2022" in data["sources"]["majors"]["source"]
    )
    again = client.get("/api/catalog", headers={**user[0], "If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_profile_is_per_user_and_validated(client):
    a, b = auth(signup(client, "a@x.vn")), auth(signup(client, "b@x.vn"))
    assert client.get("/api/profile").status_code == 401
    assert client.get("/api/profile", headers=a).json()["needs_profile"] is True
    body = {"school_name": "Trường Đại học Việt Nhật, ĐHQGHN", "school_abbr": "VNU-VJU", "degree_level": "dai_hoc",
            "major_code": "BCSE", "major_name": "Khoa học và Kỹ thuật máy tính", "student_id": "21020001", "class_name": "K5"}  # fmt: skip
    r = client.put("/api/profile", json=body, headers=a)
    assert (
        r.status_code == 200
        and r.json()["needs_profile"] is False
        and r.json()["major_name"].startswith("Khoa học")
    )
    assert client.get("/api/profile", headers=b).json()["major_name"] == ""  # B không thấy hồ sơ của A
    assert client.put("/api/profile", json={**body, "degree_level": "lop_12"}, headers=a).status_code == 422
    assert client.put("/api/profile", json={**body, "major_name": "x" * 201}, headers=a).status_code == 422
    assert client.put("/api/profile", json={**body, "phone": "<script>"}, headers=a).status_code == 422
    assert client.post("/api/profile/snooze", headers=b).status_code == 200
    assert client.get("/api/profile", headers=b).json()["needs_profile"] is False  # "Để sau" 7 ngày
    assert client.get("/api/auth/me", headers=a).status_code == 200
