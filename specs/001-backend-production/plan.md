# Implementation Plan: Nâng backend MStudent lên bản production

**Branch**: `001-backend-production` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-backend-production/spec.md`

## Summary

Đưa backend FastAPI hiện có lên VPS Ubuntu của trường trước buổi demo ngày 2026-11-14, với thay đổi code tối
thiểu:
- **HTTPS:** VPS không có IP công khai hay tên miền nên dùng **Tailscale Funnel**. Đường hầm ra ngoài cho địa
  chỉ HTTPS cố định `https://<máy>.<tailnet>.ts.net`, miễn phí. Backend chạy bằng `systemd`.
- **Code backend:** bộ đếm giới hạn tần suất chuyển từ RAM sang SQLite; theo dõi token LLM và áp trần
  5 USD/ngày; đặt thời hạn chờ cho mọi lượt gọi LLM; thêm endpoint số liệu cho admin; thêm trang Chính sách
  quyền riêng tư; kiểm tra cấu hình bắt buộc khi khởi động ở chế độ prod; lấy IP thật của client qua proxy tin
  cậy.
- **Mobile:** đặt sẵn địa chỉ production và chỉ cho HTTP với địa chỉ LAN.
- **Vận hành:** sao lưu SQLite hằng ngày bằng `systemd timer`; UptimeRobot ping `/api/health`; cảnh báo chi
  phí qua webhook (Discord/Telegram).

## Technical Context

**Language/Version**: Python 3.11+ (backend), TypeScript / Expo (mobile, chỉ chỉnh cấu hình và `lib/`)

**Primary Dependencies**: FastAPI, Pydantic v2, openai-agents, httpx, uvicorn. Không thêm thư viện Python mới.

**Storage**: SQLite (WAL) trên ổ VPS. Thêm 2 bảng: `llm_usage`, `rate_counters`.

**Testing**: pytest + ruff (backend); jest + typecheck (mobile, phần `lib/url.ts`)

**Target Platform**: VPS Ubuntu/Debian có sudo, 1 tiến trình uvicorn sau Tailscale Funnel

**Project Type**: Mobile app + web service (repo có sẵn `backend/` và `mobile/`)

**Performance Goals**: 30 người dùng đồng thời; thao tác không gọi AI dưới 1 giây

**Constraints**: Phải xong trong vài giờ; không phá đường demo local; giữ nguyên hợp đồng API hiện có; trần
LLM 5 USD/ngày

**Scale/Scope**: 100 người dùng đăng ký; 1 VPS; 1 tiến trình

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Nguyên tắc | Kiểm tra | Kết quả |
|---|---|---|
| I. Bảo mật & cách ly | Endpoint mới `/api/admin/stats` dùng `admin_user` và chỉ trả số tổng hợp. Bảng mới có `user_id` khi chạm dữ liệu người dùng. SQL dùng tham số. Bí mật nằm trong `/etc/mstudent.env` (quyền 600), không vào log. | ✅ |
| I. Endpoint công khai | `/privacy` là trang HTML tĩnh, không phải API, không đọc dữ liệu. Ngoại lệ được ghi lại ở Complexity Tracking. | ✅ (có giải trình) |
| I. IP client | Chỉ tin `X-Forwarded-For` khi `MSTUDENT_TRUST_PROXY=1` **và** kết nối đến từ `127.0.0.1`. | ✅ |
| II. Test xanh | Mỗi thay đổi có test: rate limit bền vững, trần chi phí, timeout, stats chỉ admin, kiểm tra cấu hình prod, client_ip. Chạy `pytest -q && ruff check .` | ✅ |
| III. AI minh bạch | Chạm trần hoặc timeout thì đi đường bộ luật sẵn có, `mode="offline"`. Không đổi prompt hay `eval/cases.json`. | ✅ |
| Ràng buộc: thời gian | Chi phí tính theo ngày `config.now()` (+07:00); bộ đếm rate dùng `config.utcnow()`. | ✅ |
| Ràng buộc: API ↔ mobile | Không đổi API cũ. `stats` chỉ dùng trên web console, không cần sửa `types.ts`. | ✅ |

**Sau Phase 1:** thiết kế không thêm vi phạm mới. ✅

## Project Structure

### Documentation (this feature)

```text
specs/001-backend-production/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md          # hướng dẫn triển khai lên VPS + khôi phục
├── contracts/
│   └── api.md             # /api/admin/stats, /privacy, hành vi health
└── tasks.md               # (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py              # + check_prod_config(), LLM_TIMEOUT_S, giá token, trần chi phí, TRUST_PROXY
│   ├── db.py                  # + bảng llm_usage, rate_counters
│   ├── repo.py                # + record_llm_usage(), cost_today(), stats_summary(), rate_hit()
│   ├── security.py            # RateLimiter → lưu SQLite
│   ├── deps.py                # client_ip() tin proxy cục bộ khi bật cờ
│   ├── budget.py              # MỚI: llm_allowed(), ghi usage, cảnh báo 80%/100% qua webhook
│   ├── main.py                # gọi check_prod_config() khi khởi động; route /privacy
│   ├── pipeline/
│   │   ├── llm_agents.py      # asyncio.wait_for + ghi usage
│   │   ├── orchestrator.py    # llm_enabled() → budget.llm_allowed()
│   │   └── assistant.py       # như trên + timeout
│   ├── routers/core.py        # + GET /api/admin/stats
│   └── static/
│       ├── privacy.html       # MỚI
│       ├── index.html, app.js # + thẻ "Số liệu" cho admin
├── deploy/                    # MỚI
│   ├── mstudent.service       # systemd unit (uvicorn 1 worker, 127.0.0.1:8000, --no-proxy-headers)
│   ├── smoke_load.py          # kiểm tra nhanh 30 yêu cầu đồng thời (SC-003)
│   ├── mstudent-backup.service + .timer   # sao lưu 03:00 hằng ngày
│   ├── backup.py              # sqlite3 backup API, giữ 7 bản
│   └── mstudent.env.example
└── tests/
    ├── test_production.py     # MỚI: rate bền vững, trần chi phí, timeout, stats, prod config, client_ip
mobile/
├── app.config.js              # + EXPO_PUBLIC_API_URL
└── lib/url.ts (+ test)        # chỉ cho http:// với địa chỉ LAN/localhost
docs/
├── DEMO_RUNBOOK.md            # + mục "Production" và đường lui về local
└── SECURITY.md                # cập nhật các mục đã làm
```

**Structure Decision**: Giữ cấu trúc `backend/` + `mobile/` sẵn có. Mọi thay đổi là bổ sung nhỏ. Hạ tầng gom
vào `backend/deploy/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `/privacy` công khai ngoài danh sách cho phép | FR-018: Google và người dùng phải đọc được khi chưa đăng nhập | Đưa vào sau đăng nhập thì không thoả yêu cầu. Trang tĩnh, không chạm dữ liệu. |
| Phụ thuộc hạ tầng ngoài (Tailscale, UptimeRobot, webhook) | VPS không có IP công khai/tên miền; cần cảnh báo | Cloudflare quick tunnel đổi địa chỉ mỗi lần khởi động lại; ngrok free giới hạn 20k request/tháng |
