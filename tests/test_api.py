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
