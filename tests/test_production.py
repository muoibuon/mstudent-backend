"""Bản production: kiểm tra cấu hình khi khởi động, IP sau proxy, trang quyền riêng tư."""

from types import SimpleNamespace

import pytest

from app import config, deps

SECRET = "prod-secret-key-0123456789abcdef0123456789abcdef"


def _prod_env(monkeypatch, **override):
    env = {
        "MSTUDENT_ENV": "prod",
        "MSTUDENT_SECRET_KEY": SECRET,
        "OPENAI_API_KEY": "sk-test-value-should-never-be-printed",
        "MSTUDENT_ADMIN_EMAILS": "admin@vju.ac.vn",
        "MSTUDENT_NOW": None,
    }
    env.update(override)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


# ---------------- check_prod_config ----------------


def test_prod_config_ok(monkeypatch):
    _prod_env(monkeypatch)
    config.check_prod_config()


def test_prod_config_skipped_outside_prod(monkeypatch):
    _prod_env(monkeypatch, MSTUDENT_ENV="dev", OPENAI_API_KEY=None, MSTUDENT_ADMIN_EMAILS=None)
    config.check_prod_config()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MSTUDENT_SECRET_KEY", None),
        ("MSTUDENT_SECRET_KEY", "too-short"),
        ("OPENAI_API_KEY", None),
        ("MSTUDENT_ADMIN_EMAILS", None),
        ("MSTUDENT_NOW", "2026-11-10T08:00:00+07:00"),
    ],
)
def test_prod_config_names_missing_variable_without_leaking_values(monkeypatch, name, value):
    _prod_env(monkeypatch, **{name: value})
    with pytest.raises(RuntimeError) as e:
        config.check_prod_config()
    msg = str(e.value)
    assert name in msg
    assert SECRET not in msg
    assert "sk-test-value" not in msg
    assert "too-short" not in msg


# ---------------- client_ip ----------------


def _req(peer: str | None, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer) if peer else None, headers=headers)


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch):
    monkeypatch.delenv("MSTUDENT_TRUST_PROXY", raising=False)
    assert deps.client_ip(_req("127.0.0.1", "203.0.113.9")) == "127.0.0.1"


def test_client_ip_uses_first_forwarded_address_from_local_proxy(monkeypatch):
    monkeypatch.setenv("MSTUDENT_TRUST_PROXY", "1")
    assert deps.client_ip(_req("127.0.0.1", "203.0.113.9, 10.0.0.1")) == "203.0.113.9"
    assert deps.client_ip(_req("::1", " 2001:db8::7 ")) == "2001:db8::7"


def test_client_ip_does_not_trust_header_from_remote_peer(monkeypatch):
    monkeypatch.setenv("MSTUDENT_TRUST_PROXY", "1")
    assert deps.client_ip(_req("198.51.100.4", "203.0.113.9")) == "198.51.100.4"


def test_client_ip_falls_back_when_header_missing_or_garbage(monkeypatch):
    monkeypatch.setenv("MSTUDENT_TRUST_PROXY", "1")
    assert deps.client_ip(_req("127.0.0.1")) == "127.0.0.1"
    assert deps.client_ip(_req("127.0.0.1", "not an ip <script>")) == "127.0.0.1"
    assert deps.client_ip(_req(None)) == "unknown"


# ---------------- /privacy ----------------


def test_privacy_page_is_public(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "quyền riêng tư" in r.text.lower()
    assert "<script" not in r.text.lower()


# ---------------- Giới hạn tần suất bền vững ----------------


def test_rate_limit_survives_restart(client):
    from app import security

    a = security.RateLimiter()
    assert [a.hit("k", 3, 3600) for _ in range(3)] == [None, None, None]
    assert a.hit("k", 3, 3600) >= 1
    b = security.RateLimiter()  # tiến trình mới sau khi khởi động lại: không còn gì trong RAM
    assert b.hit("k", 3, 3600) >= 1
    assert b.hit("other", 3, 3600) is None  # khoá khác không bị ảnh hưởng
    b.reset("k")
    assert a.hit("k", 3, 3600) is None
    b.reset()
    assert a.hit("other", 1, 3600) is None


def test_rate_limit_counts_previous_window(client, monkeypatch):
    """Không lách được giới hạn bằng cách gọi dồn ở hai bên ranh giới cửa sổ."""
    from datetime import UTC, datetime

    from app import security

    clock = {"t": 1_000_000 * 60 + 59.0}  # giây thứ 59 của một cửa sổ 60 giây
    monkeypatch.setattr(config, "utcnow", lambda: datetime.fromtimestamp(clock["t"], UTC))
    lim = security.RateLimiter()
    assert all(lim.hit("k", 10, 60) is None for _ in range(10))
    clock["t"] += 2  # sang cửa sổ mới 1 giây: cửa sổ cố định sẽ cho thêm 10 lượt, ở đây gần như không
    assert sum(lim.hit("k", 10, 60) is None for _ in range(10)) <= 1
    clock["t"] += 120  # hai cửa sổ sau: sạch
    assert lim.hit("k", 10, 60) is None


# ---------------- Trần chi phí LLM, thời hạn chờ ----------------


class _FakeResult:
    def __init__(self, output, tin=1000, tout=500):
        self.final_output = output
        self.new_items = []
        self.context_wrapper = SimpleNamespace(usage=SimpleNamespace(input_tokens=tin, output_tokens=tout))


@pytest.fixture()
def llm_on(monkeypatch):
    """Bật đường LLM với Runner giả (không gọi mạng). Trả về danh sách các lượt gọi."""
    from app.models import Category, ExtractionOut, TriageOut
    from app.pipeline import llm_agents

    monkeypatch.delenv("MSTUDENT_OFFLINE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    calls: list[str] = []

    async def fake_run(agent, payload, **kwargs):
        calls.append(agent.name)
        if agent.name == "Triage":
            return _FakeResult(TriageOut(relevant=True, category=Category.deadline, reason="có hạn nộp"))
        if agent.name == "Extractor":
            return _FakeResult(ExtractionOut(tasks=[]))
        return _FakeResult("xong")

    monkeypatch.setattr(llm_agents.Runner, "run", fake_run)
    return calls


NOTICE = {"body": "Các em nộp bài tập tuần 9 trước 23h59 thứ 6 tuần này nhé."}


def _usage_rows():
    import sqlite3

    db = sqlite3.connect(config.DB_PATH)
    return db.execute(
        "SELECT user_id, agent, input_tokens, output_tokens, cost_usd FROM llm_usage"
    ).fetchall()


def test_llm_usage_recorded_per_call(client, user, llm_on, monkeypatch):
    monkeypatch.setenv("MSTUDENT_PRICE_IN_PER_M", "1")
    monkeypatch.setenv("MSTUDENT_PRICE_OUT_PER_M", "2")
    h, _ = user
    r = client.post("/api/ingest", json=NOTICE, headers=h)
    assert r.status_code == 200 and r.json()["mode"] == "llm"
    rows = _usage_rows()
    assert [row[1] for row in rows] == ["Triage", "Extractor"]
    assert all(row[0] is not None for row in rows)
    assert rows[0][2:] == (1000, 500, pytest.approx(0.002))


def test_daily_budget_switches_to_offline_and_resets_next_day(client, user, llm_on, monkeypatch):
    from app import budget

    monkeypatch.setenv("MSTUDENT_LLM_DAILY_USD", "0.004")
    monkeypatch.setenv("MSTUDENT_PRICE_IN_PER_M", "1")
    monkeypatch.setenv("MSTUDENT_PRICE_OUT_PER_M", "2")
    sent: list[str] = []
    monkeypatch.setattr(budget, "_send_alert", sent.append)
    h, _ = user

    assert budget.llm_allowed()
    assert client.post("/api/ingest", json=NOTICE, headers=h).json()["mode"] == "llm"  # tốn 0.004 → chạm trần
    assert budget.exhausted() and not budget.llm_allowed()

    before = len(llm_on)
    r = client.post(
        "/api/ingest", json={"body": "Thứ 5 kiểm tra giữa kỳ môn Giải tích lúc 9h nhé cả lớp"}, headers=h
    )
    assert r.json()["mode"] == "offline"  # kết quả của bộ luật được ghi rõ là offline
    assert client.post("/api/chat", json={"message": "hôm nay có gì"}, headers=h).json()["mode"] == "offline"
    assert len(llm_on) == before  # không gọi LLM thêm lượt nào

    assert len(sent) == 1 and "trần" in sent[0]  # báo đúng một lần, không báo 80% muộn
    assert "sk-test" not in sent[0]

    monkeypatch.setenv("MSTUDENT_NOW", "2026-11-11T00:05:00+07:00")  # sang ngày mới (+07:00)
    assert budget.llm_allowed()


def test_budget_alert_at_80_percent_once(client, user, llm_on, monkeypatch):
    from app import budget, repo

    monkeypatch.setenv("MSTUDENT_LLM_DAILY_USD", "1")
    sent: list[str] = []
    monkeypatch.setattr(budget, "_send_alert", sent.append)
    repo.record_llm_usage(None, "Eval", 0, 0, 0.85, 10)
    budget._maybe_alert()
    budget._maybe_alert()
    assert len(sent) == 1 and "80%" in sent[0]
    assert budget.llm_allowed()  # 85% vẫn còn dùng được


def test_llm_timeout_falls_back_to_rules(client, user, llm_on, monkeypatch):
    import asyncio

    from app.pipeline import llm_agents

    async def slow(agent, payload, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(llm_agents.Runner, "run", slow)
    monkeypatch.setenv("MSTUDENT_LLM_TIMEOUT_S", "0.05")
    h, _ = user
    r = client.post("/api/ingest", json=NOTICE, headers=h).json()
    assert r["mode"] == "offline"
    assert any("error" in step for step in r["trace"])
    assert _usage_rows() == []  # lượt hỏng không bị tính tiền
    assert client.post("/api/chat", json={"message": "hôm nay có gì"}, headers=h).json()["mode"] == "offline"


def test_ai_check_reports_budget_exhausted(client, user, llm_on, monkeypatch):
    from app import repo

    monkeypatch.setenv("MSTUDENT_LLM_DAILY_USD", "1")
    repo.record_llm_usage(None, "Eval", 0, 0, 2.0, 10)
    r = client.post("/api/ai/check", headers=user[0]).json()
    assert r["ok"] is False and "trần" in r["error"]
    assert llm_on == []


def test_delete_account_removes_llm_usage(client, user, llm_on):
    h, _ = user
    client.post("/api/ingest", json=NOTICE, headers=h)
    assert len(_usage_rows()) == 2
    assert (
        client.request("DELETE", "/api/auth/me", json={"confirm_email": "a@vju.ac.vn"}, headers=h).status_code
        == 200
    )
    assert _usage_rows() == []


# ---------------- Sao lưu ----------------


def test_backup_script_copies_restorable_db_and_prunes_old(client, user, tmp_path):
    import importlib.util
    import sqlite3
    from datetime import datetime
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "mstudent_backup", Path(__file__).resolve().parent.parent / "deploy" / "backup.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out_dir = tmp_path / "backups"
    out_dir.mkdir()
    for name in ("mstudent-20261101.db", "mstudent-20261103.db", "mstudent-20261109.db", "ghi-chu.txt"):
        (out_dir / name).write_text("x")

    dest = mod.backup(Path(config.DB_PATH), out_dir, keep_days=7, today=datetime(2026, 11, 10, 3, 0))

    assert dest.name == "mstudent-20261110.db"
    assert sqlite3.connect(dest).execute("SELECT email FROM users").fetchall() == [("a@vju.ac.vn",)]
    assert dest.stat().st_mode & 0o777 == 0o600 and out_dir.stat().st_mode & 0o777 == 0o700
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["ghi-chu.txt", "mstudent-20261109.db", "mstudent-20261110.db"]  # bản quá 7 ngày bị xoá
