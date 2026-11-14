"""Cấu hình qua biến môi trường (đọc từ .env nếu có)."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Đọc .env mà không cần python-dotenv. Biến đã có trong môi trường được giữ nguyên."""
    env = BACKEND_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

TZ = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")

DB_PATH = os.getenv("MSTUDENT_DB", str(BACKEND_DIR / "mstudent.db"))
# Hai model: model TRẢ LỜI (trích việc, chi tiết sự kiện, bản tin, trợ lý chat…) và model LỌC (Triage, xem decision.py).
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "cx/gpt-6-luna(xhigh)")

ACCESS_TTL_MIN = int(os.getenv("MSTUDENT_ACCESS_TTL_MIN", "15"))
REFRESH_TTL_DAYS = int(os.getenv("MSTUDENT_REFRESH_TTL_DAYS", "30"))
# App bị đóng giữa lúc đổi token → lần mở lại vẫn gửi token cũ; chấp nhận trong khoảng ngắn này.
REFRESH_REUSE_GRACE_S = int(os.getenv("MSTUDENT_REFRESH_GRACE_S", "30"))
MAX_BODY_BYTES = 256 * 1024

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
# Google Classroom chỉ đọc (002 US2): danh sách lớp, bài tập + bài nộp của chính mình, thông báo lớp.
CLASSROOM_SCOPES = (
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
)


def is_prod() -> bool:
    return os.getenv("MSTUDENT_ENV", "dev").lower() == "prod"


def is_offline_forced() -> bool:
    return os.getenv("MSTUDENT_OFFLINE") == "1"


def openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://rs6esw8.abc-tunnel.us/v1").rstrip("/")


def openrouter_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "")


def decision_model() -> str:
    return os.getenv("MSTUDENT_DECISION_MODEL", "google/gemini-decision-1")


def decision_enabled() -> bool:
    """Decision qua OpenRouter; tắt gate thì model chính lọc thông báo."""
    return (
        bool(openrouter_api_key())
        and os.getenv("MSTUDENT_DECISION_ENABLED", "1") != "0"
        and not is_offline_forced()
    )


def decision_timeout_s() -> float:
    return _float_env("MSTUDENT_DECISION_TIMEOUT_S", 8.0)


def decision_price_in_per_m() -> float:
    """USD cho 1 triệu token đầu vào của model lọc (gemini-decision-1: 0.10, không tính đầu ra)."""
    return _float_env("MSTUDENT_DECISION_PRICE_IN_PER_M", 0.10)


def llm_enabled() -> bool:
    """Dùng LLM khi có OPENAI_API_KEY và không ép chế độ offline."""
    return bool(openai_api_key()) and not is_offline_forced()


def now() -> datetime:
    """Giờ hiện tại (+07:00). Đặt MSTUDENT_NOW=2026-11-10T08:00 để demo/test ổn định."""
    fixed = os.getenv("MSTUDENT_NOW")
    if fixed:
        dt = datetime.fromisoformat(fixed)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    return datetime.now(TZ)


def utcnow() -> datetime:
    """Giờ thật (UTC) cho token, audit, rate limit — không bị MSTUDENT_NOW ảnh hưởng."""
    return datetime.now(UTC)


# ---------------- Bí mật ----------------

_secret_cache: str | None = None


def secret_key() -> str:
    """Khoá ký JWT và mã hoá token Google.

    Ưu tiên MSTUDENT_SECRET_KEY. Nếu chưa đặt (chạy local), tự sinh một khoá ngẫu nhiên và lưu
    vào .secret_key (quyền 600, đã có trong .gitignore) để token không mất hiệu lực sau khi khởi động lại.
    """
    global _secret_cache
    env = os.getenv("MSTUDENT_SECRET_KEY")
    if env:
        if len(env) < 32:
            raise RuntimeError("MSTUDENT_SECRET_KEY phải dài ít nhất 32 ký tự")
        return env
    if _secret_cache:
        return _secret_cache
    if is_prod():
        raise RuntimeError("MSTUDENT_ENV=prod bắt buộc đặt MSTUDENT_SECRET_KEY")
    path = BACKEND_DIR / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        path.chmod(0o600)
    _secret_cache = path.read_text(encoding="utf-8").strip()
    return _secret_cache


def fernet_key() -> bytes:
    """Khoá Fernet (32 byte, base64) dẫn xuất từ secret_key, tách miền với khoá ký JWT."""
    digest = hashlib.sha256(b"mstudent/fernet/v1:" + secret_key().encode()).digest()
    return base64.urlsafe_b64encode(digest)


# ---------------- Phân quyền, CORS, Google ----------------


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


def admin_emails() -> set[str]:
    return {e.lower() for e in _csv("MSTUDENT_ADMIN_EMAILS")}


def cors_origins() -> list[str]:
    """App native không cần CORS. Chỉ đặt khi có web khác origin gọi API (vd. Expo web khi dev)."""
    return _csv("MSTUDENT_CORS_ORIGINS")


def registration_open() -> bool:
    return os.getenv("MSTUDENT_REGISTRATION", "open").lower() != "closed"


def google_web_client_id() -> str:
    return os.getenv("GOOGLE_WEB_CLIENT_ID", "")


def google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "")


def google_ios_client_id() -> str:
    return os.getenv("GOOGLE_IOS_CLIENT_ID", "")


def google_client_ids() -> list[str]:
    """Mọi client ID được chấp nhận làm `aud` của Google ID token (web, iOS, Android)."""
    ids = [google_web_client_id(), google_ios_client_id(), *_csv("GOOGLE_EXTRA_CLIENT_IDS")]
    return [i for i in ids if i]


# ---------------- Production: chi phí LLM, proxy, cảnh báo ----------------


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def llm_daily_usd() -> float:
    """Trần chi phí LLM mỗi ngày (USD) cho toàn hệ thống. Chạm trần → chạy bộ luật (offline)."""
    return _float_env("MSTUDENT_LLM_DAILY_USD", 5.0)


def llm_user_daily_usd() -> float:
    """Trần chi phí LLM mỗi ngày cho MỖI người dùng (USD). Chạm trần → riêng người đó chạy bộ luật. 0 = tắt."""
    return _float_env("MSTUDENT_LLM_USER_DAILY_USD", 0.5)


def llm_timeout_s() -> float:
    """Thời hạn chờ một lượt gọi LLM. Quá hạn → chuyển sang bộ luật."""
    return _float_env("MSTUDENT_LLM_TIMEOUT_S", 25.0)


def price_in_per_m() -> float:
    """Ước tính USD/1M token cho ngân sách; xác nhận giá gateway trước khi đối chiếu hóa đơn."""
    return _float_env("MSTUDENT_PRICE_IN_PER_M", 0.10)


def price_out_per_m() -> float:
    return _float_env("MSTUDENT_PRICE_OUT_PER_M", 0.50)


def trust_proxy() -> bool:
    """Bật khi chạy sau đường hầm/reverse proxy trên chính máy này (chỉ tin header từ 127.0.0.1)."""
    return os.getenv("MSTUDENT_TRUST_PROXY") == "1"


# ---------------- Đồng bộ tự động (002-auto-ingest) ----------------


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def sync_enabled() -> bool:
    """Bộ đồng bộ nền (Gmail, Classroom, bảng lớp, lịch LMS). Mặc định bật; test đặt 0."""
    return os.getenv("MSTUDENT_SYNC_ENABLED", "1") == "1"


def gmail_poll_s() -> int:
    """Chu kỳ kiểm tra Gmail dự phòng (giây) khi không có / lỗi kênh báo ngay Pub/Sub."""
    return max(30, _int_env("MSTUDENT_GMAIL_POLL_S", 120))


def sync_concurrency() -> int:
    return max(1, min(_int_env("MSTUDENT_SYNC_CONCURRENCY", 4), 16))


def public_url() -> str:
    """Địa chỉ HTTPS công khai của backend (vd https://mstudent.x.ts.net), dùng cho aud của webhook."""
    return os.getenv("MSTUDENT_PUBLIC_URL", "").rstrip("/")


def pubsub_topic() -> str:
    """projects/<id>/topics/<tên>: topic nhận thông báo Gmail. Trống = chỉ kiểm tra định kỳ."""
    return os.getenv("MSTUDENT_PUBSUB_TOPIC", "")


def pubsub_push_sa() -> str:
    """Email service account mà Pub/Sub dùng để ký JWT khi gọi /api/hooks/gmail."""
    return os.getenv("MSTUDENT_PUBSUB_PUSH_SA", "").lower()


def alert_webhook() -> str:
    """URL webhook (Discord/Slack/Telegram bot) nhận cảnh báo chi phí. Trống = không gửi."""
    return os.getenv("MSTUDENT_ALERT_WEBHOOK", "")


def check_prod_config() -> None:
    """Ở chế độ prod: thiếu cấu hình bắt buộc thì không cho khởi động. Chỉ nêu TÊN biến, không in giá trị."""
    if not is_prod():
        return
    problems: list[str] = []
    if len(os.getenv("MSTUDENT_SECRET_KEY", "")) < 32:
        problems.append("MSTUDENT_SECRET_KEY (cần >= 32 ký tự)")
    if not os.getenv("OPENAI_API_KEY") and not is_offline_forced():
        problems.append("OPENAI_API_KEY (hoặc đặt MSTUDENT_OFFLINE=1 để chạy bộ luật, không dùng AI)")
    if not admin_emails():
        problems.append("MSTUDENT_ADMIN_EMAILS")
    if os.getenv("MSTUDENT_NOW"):
        problems.append("MSTUDENT_NOW (phải bỏ trống ở prod, nếu không trần chi phí không sang ngày mới)")
    if problems:
        raise RuntimeError("MSTUDENT_ENV=prod thiếu hoặc sai cấu hình: " + "; ".join(problems))
