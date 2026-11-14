# Implementation Plan: Tự động thu thập thông báo học tập

**Branch**: `002-auto-ingest` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-auto-ingest/spec.md`

## Summary

Kết nối nguồn một lần, sau đó máy chủ tự đồng bộ định kỳ: Gmail (báo ngay qua Pub/Sub + kiểm tra 2 phút), lịch LMS `.ics`
(60 phút), Google Classroom (10 phút, hạn nộp có cấu trúc, không tốn AI), bảng deadline của lớp qua link Google Sheets công
khai (30 phút, AI chỉ hiểu cột một lần). Mọi mục mới đi qua pipeline sẵn có (triage → extract → planner), gộp việc giữa các
nguồn theo mã/tên môn, tính vào trần chi phí riêng/chung. Việc mới → thông báo đẩy Android (Expo Push); iPhone bản miễn
phí dùng làm mới nền. Zalo Android qua đọc thông báo trên máy làm sau cùng. Chi tiết quyết định: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript / React Native 0.88 + Expo SDK 58 (mobile), Kotlin (module Zalo
Android, P5)

**Primary Dependencies**: FastAPI, httpx, openai-agents, PyJWT[crypto] (đã có); mobile thêm `expo-background-task`,
`expo-device` (đã có `expo-notifications`). Không thêm phụ thuộc backend mới.

**Storage**: SQLite (WAL) hiện có; 3 bảng mới + 2 cột mới ở `tasks` ([data-model.md](data-model.md))

**Testing**: pytest (mock Gmail/Classroom/CSV/Expo bằng `httpx.MockTransport` hoặc monkeypatch), node:test cho `mobile/lib`

**Target Platform**: Ubuntu 24.04 VM (Azure Japan East, 1 GiB + swap), Android 10+, iOS 16.4+

**Project Type**: mobile + API (`backend/`, `mobile/`)

**Performance Goals**: email → việc ≤ 1 phút (push) / ≤ 3 phút (poll); Classroom ≤ 30 phút; bảng/`.ics` ≤ 1 giờ;
vòng đồng bộ không làm p95 API người dùng vượt 1 s

**Constraints**: 1 tiến trình uvicorn; < 50 MB RAM thêm; 0 lượt AI khi nguồn không đổi; trần 0,5 USD/người/ngày và
5 USD/ngày; chỉ scope đọc; demo 2026-11-14 (P1–P3 trên production)

**Scale/Scope**: ≤ 100 người dùng thử (giới hạn Google Testing), mỗi người ≤ 10 bảng + 5 `.ics`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Nguyên tắc | Đánh giá | Ghi chú |
|---|---|---|
| I. Bảo mật & cách ly | ⚠️ Có ngoại lệ có lý do | Endpoint mới đều `current_user`/`ai_limit`, repo lọc `user_id`, SQL tham số, giới hạn độ dài. **Ngoại lệ**: `POST /api/hooks/gmail` công khai nhưng xác thực bằng chữ ký OIDC của Google và không đọc dữ liệu (xem Complexity Tracking). Token Google vẫn mã hoá Fernet; push chỉ chứa tên việc + hạn. Nội dung email/thông báo lớp/dòng bảng đi qua `render()` + GUARD + `sanitize()`. Agent SheetMapper không có tool. SSRF: allowlist host cho bảng, kiểm IP công khai cho `.ics`. |
| II. Test luôn xanh | ✅ | Test cho mỗi nguồn (mock HTTP), lịch/lease, gộp nguồn, cách ly người dùng ở `/api/sources`, chữ ký webhook, xoá tài khoản xoá dữ liệu mới. |
| III. AI minh bạch | ✅ | Hết hạn mức → luật, `mode="offline"`. Prompt SheetMapper ở `agent_config.DEFAULTS`, schema bắt buộc mọi trường. Classroom/`.ics` có cấu trúc không qua AI (ghi rõ nguồn). |
| Ràng buộc kỹ thuật | ✅ | Python/FastAPI/Pydantic v2/openai-agents; gói mobile cài bằng `npx expo install`; thời gian nghiệp vụ `+07:00` qua `config.now()` (hạn Classroom UTC được đổi), lịch/lease dùng `config.utcnow()`; `types.ts`/`api.ts` cập nhật cho `sources`, `push`, `Task.sources/note`; đường demo cũ trong `DEMO_RUNBOOK` không đổi (đồng bộ tay vẫn chạy). |
| Quy trình | ✅ | Sửa nhiều file → đã qua `/speckit-plan`; thay đổi chạm token Google, webhook công khai, prompt mới → `security-reviewer` soát trước khi merge. |

Kết quả: **PASS** với một ngoại lệ có biện minh.

## Project Structure

### Documentation (this feature)

```text
specs/002-auto-ingest/
├── plan.md · research.md · data-model.md · quickstart.md
├── contracts/api.md
├── checklists/requirements.md
└── tasks.md            # bước tasks
```

### Source Code (repository root)

```text
backend/app/
├── sync/                    # MỚI
│   ├── scheduler.py         # vòng lặp lifespan, lease, lùi dần, chạy runner theo kind
│   ├── gmail.py             # history.list tăng dần, watch/gia hạn, gọi orchestrator.ingest
│   ├── ics.py               # tải lại .ics, so UID/hash, tạo/cập nhật việc
│   ├── classroom.py         # lọc lớp FR-024, courseWork → việc, submissions → xong, announcements → ingest
│   ├── sheets.py            # tải CSV an toàn, SheetMapper/luật, so dòng
│   └── notify.py            # gom việc mới/dời hạn → Expo Push
├── routers/sources.py       # MỚI: /api/sources, /api/push/register
├── routers/hooks.py         # MỚI: /api/hooks/gmail (OIDC)
├── google_api.py            # + history.list, getProfile, watch, Classroom calls
├── pipeline/planner.py      # match_existing (FR-009), sources[]
├── db.py · repo.py · models.py · config.py · main.py   # bảng/cột mới, CRUD lọc user_id, env mới, lifespan
└── agent_config.py          # + sheet_mapper_prompt
backend/tests/test_sync.py   # MỚI

mobile/
├── lib/push.ts              # MỚI: đăng ký Expo push (bỏ qua khi không hỗ trợ)
├── lib/background.ts        # MỚI: expo-background-task kéo việc mới + đặt nhắc
├── lib/sources.ts           # MỚI: logic thuần (nhãn, trạng thái) + test
├── lib/google.ts            # + scope Classroom tuỳ chọn
├── app/sources.tsx          # MỚI: màn hình Nguồn (danh sách, thêm link, bật/tắt, đồng bộ ngay)
├── app/(tabs)/settings.tsx  # lối vào "Nguồn tự động", giải thích giới hạn iPhone
└── modules/zalo-listener/   # P5: Expo module Kotlin + config plugin
```

**Structure Decision**: Giữ cấu trúc mobile + API hiện có; gom toàn bộ logic đồng bộ vào gói `backend/app/sync/` để tách
khỏi request path và test độc lập.

## Phân pha & thứ tự (theo ưu tiên spec)

| Pha | Nội dung | Ước lượng | Cần từ người dùng |
|---|---|---|---|
| 1 | Nền: bảng, repo, scheduler, `/api/sources`, planner gộp nguồn | 1,5 h | — |
| 2 (US1) | Gmail tự động (poll 2 phút) + `.ics` tự động | 1,5 h | Google OAuth (Web + iOS client, secret) |
| 3 (US1) | Gmail báo ngay: `watch` + `/api/hooks/gmail` | 1 h | Pub/Sub topic + push subscription OIDC |
| 4 (US3) | Bảng lớp | 1,5 h | — (làm được trước khi có OAuth) |
| 5 (US2) | Classroom | 1,5 h | bật Classroom API + 3 scope |
| 6 (US4) | Push Android + làm mới nền iPhone + màn hình Nguồn | 2 h | Thành viên Android: EAS project + khoá FCM |
| 7 (US5) | Zalo Android | 3–4 h | Thành viên Android build/test |
| 8 | Triển khai, quickstart trên production, tài liệu, soát bảo mật | 1 h | — |

Thứ tự thực hiện thực tế: 1 → 4 → 2 → 3 → 5 → 6 → 8 → 7 (bảng lớp lên trước vì không chờ cấu hình Google).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Endpoint công khai `POST /api/hooks/gmail` (nguyên tắc I chỉ cho health/public-config/auth/privacy) | Google Pub/Sub cần gọi vào máy chủ để email thành việc trong ~1 phút (clarify Q3) | Chỉ poll 2 phút: đạt ≤ 3 phút nhưng người dùng chọn cả báo ngay; xác thực bằng chữ ký OIDC của Google + không đọc dữ liệu trong request + luôn 204 nên rủi ro thấp. Cập nhật danh sách endpoint công khai trong `AGENTS.md`/`SECURITY.md`. |
| Vòng lặp nền trong tiến trình web | Không có hàng đợi riêng trên VM 1 GiB | Celery/Redis tốn RAM và vận hành; systemd timer không phản ứng kịp với push |
