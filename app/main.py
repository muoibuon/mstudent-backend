"""MStudent API.

Chạy local cho điện thoại trong cùng mạng:  python run_local.py   (trong thư mục backend/)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agent_config, config
from .routers import auth, core, google, hooks, sources
from .sync import scheduler

ROOT = Path(__file__).resolve().parent

# Production: thiếu cấu hình bắt buộc thì dừng ngay lúc khởi động (chỉ nêu tên biến).
config.check_prod_config()

app = FastAPI(
    lifespan=scheduler.lifespan,  # bộ đồng bộ nền (tắt bằng MSTUDENT_SYNC_ENABLED=0)
    title="MStudent",
    version="1.0.0",
    description="AI inbox biến thông báo email/LMS/Zalo thành việc cần làm",
    # Tài liệu API tự sinh chỉ bật khi phát triển.
    docs_url=None if config.is_prod() else "/docs",
    redoc_url=None,
    openapi_url=None if config.is_prod() else "/openapi.json",
)

if config.cors_origins():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,  # dùng Bearer token, không dùng cookie → không có CSRF
    )

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def hardening(request: Request, call_next):
    # Chặn body quá lớn trước khi đọc.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > config.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Nội dung gửi lên quá lớn"}, status_code=413)
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith(("/docs", "/openapi")):
        h["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    elif request.url.path == "/" or request.url.path.startswith("/static/"):
        h["Cache-Control"] = "no-cache"  # trình duyệt hỏi lại (ETag) nên luôn lấy bản mới sau khi deploy
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(auth.router)
app.include_router(core.router)
app.include_router(google.router)
app.include_router(sources.router)
app.include_router(hooks.router)


@app.get("/api/health", tags=["public"])
def health():
    """Công khai: app dùng để kiểm tra kết nối và biết AI có đang chạy trực tiếp không."""
    return {
        "ok": True,
        "mode": "llm" if config.llm_enabled() else "offline",
        "model": agent_config.get()["model"],
        "now": config.now().isoformat(),
    }


@app.get("/api/public-config", tags=["public"])
def public_config():
    """Cấu hình công khai cho app (client ID không phải bí mật)."""
    return {
        "registration_open": config.registration_open(),
        "google": {
            "enabled": bool(config.google_web_client_id()),
            "web_client_id": config.google_web_client_id(),
            "ios_client_id": config.google_ios_client_id(),
            "gmail": bool(config.google_web_client_id() and config.google_client_secret()),
        },
    }


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/privacy", include_in_schema=False)
def privacy():
    """Công khai: trang tĩnh Chính sách quyền riêng tư (không đọc CSDL)."""
    return FileResponse(ROOT / "static" / "privacy.html", media_type="text/html; charset=utf-8")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")
