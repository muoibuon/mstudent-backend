# Tasks: Nâng backend MStudent lên bản production

**Input**: Design documents from `/specs/001-backend-production/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: Bắt buộc theo Constitution (nguyên tắc II). Viết test trước hoặc cùng lúc với code; chạy
`cd backend && python -m pytest -q && ruff check .` sau mỗi phase.

**Hạn chót**: demo 2026-11-14. Ưu tiên: Phase 1 → 2 → US1 → US2 → triển khai → US3 → US4.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [X] T001 Trên VPS, kiểm tra truy cập HTTPS tới pypi.org, api.openai.com, controlplane.tailscale.com (mỗi lệnh `curl` một dòng); ghi kết quả vào `specs/001-backend-production/research.md` mục R11. Nếu OpenAI bị chặn thì DỪNG và báo người dùng.
- [X] T002 Tạo nhánh git `001-backend-production` từ `master`; xác nhận `cd backend && python -m pytest -q && ruff check .` xanh trước khi sửa.
- [X] T003 [P] Tạo `backend/deploy/mstudent.env.example` liệt kê mọi biến (MSTUDENT_ENV, MSTUDENT_SECRET_KEY, OPENAI_API_KEY, MSTUDENT_ADMIN_EMAILS, MSTUDENT_DB, MSTUDENT_TRUST_PROXY, MSTUDENT_LLM_DAILY_USD=5, MSTUDENT_PRICE_IN_PER_M, MSTUDENT_PRICE_OUT_PER_M, MSTUDENT_LLM_TIMEOUT_S=25, MSTUDENT_ALERT_WEBHOOK, GOOGLE_*), giá trị để trống, có chú thích tiếng Việt.

## Phase 2: Foundational (chặn mọi user story)

- [X] T004 Thêm vào `backend/app/config.py`: `llm_daily_usd()` (mặc định 5.0), `llm_timeout_s()` (mặc định 25), `price_in_per_m()` / `price_out_per_m()` (mặc định theo giá `gpt-5-mini`, đọc từ env), `trust_proxy()`, `alert_webhook()`.
- [X] T005 Thêm hai bảng `llm_usage` và `rate_counters` vào `SCHEMA` trong `backend/app/db.py` đúng như `data-model.md` (llm_usage: user_id NULL REFERENCES users(id) ON DELETE CASCADE — NULL cho lượt gọi hệ thống như eval/ai-check, day TEXT NOT NULL `YYYY-MM-DD` +07:00, agent, input_tokens, output_tokens, cost_usd REAL, latency_ms, created_at; index `(day)`, `(user_id, day)`; rate_counters: PK `(key, window_start)`).

**Checkpoint**: test cũ vẫn xanh.

## Phase 3: User Story 1 — Dùng app ở bất cứ đâu, kết nối an toàn (P1) 🎯 MVP

**Goal**: Backend chạy được an toàn sau đường hầm HTTPS; app trỏ sẵn tới production và vẫn lùi về local được.

**Independent Test**: Điện thoại dùng 4G, mở app bản build, đăng ký, dán thông báo, nhận việc do AI tạo.

### Tests (US1)

- [X] T006 [P] [US1] Test `check_prod_config()` trong `backend/tests/test_production.py`: thiếu từng biến (MSTUDENT_SECRET_KEY, OPENAI_API_KEY, MSTUDENT_ADMIN_EMAILS) thì `RuntimeError` có tên biến và không chứa giá trị của các biến khác; đủ thì không lỗi; ngoài prod thì không kiểm tra.
- [X] T007 [P] [US1] Test `client_ip()` trong `backend/tests/test_production.py`: không bật cờ → bỏ qua `X-Forwarded-For`; bật cờ và peer 127.0.0.1 → lấy IP đầu tiên của header; bật cờ nhưng peer khác → bỏ qua header.
- [X] T008 [P] [US1] Test `GET /privacy` trả 200 text/html không cần đăng nhập, trong `backend/tests/test_production.py`.
- [X] T009 [P] [US1] Test `normalizeUrl`/chính sách HTTP trong `mobile/lib/__tests__/url.test.ts`: `http://192.168.1.5:8000`, `http://10.0.0.2`, `http://localhost:8000` được chấp nhận; `http://example.com` bị từ chối hoặc nâng lên `https://`; chuỗi trống trả về rỗng.

### Implementation (US1)

- [X] T010 [US1] Viết `check_prod_config()` trong `backend/app/config.py` và gọi nó khi khởi động app trong `backend/app/main.py` nếu `is_prod()`. Thông báo lỗi chỉ liệt kê tên biến thiếu. Ở prod, `MSTUDENT_NOW` MUST không được đặt (nếu có thì báo lỗi), vì trần chi phí theo ngày sẽ không bao giờ sang ngày mới.
- [X] T011 [US1] Sửa `client_ip()` trong `backend/app/deps.py`: khi `config.trust_proxy()` và `request.client.host` ∈ {127.0.0.1, ::1} thì dùng phần tử đầu của `X-Forwarded-For` (strip, giới hạn 45 ký tự); ngược lại giữ như cũ.
- [X] T012 [P] [US1] Tạo `backend/app/static/privacy.html` (tiếng Việt, không có script nội tuyến): dữ liệu đọc từ Gmail chỉ-đọc, LMS, Zalo; nội dung được gửi tới OpenAI để phân tích; lưu trên máy chủ của đội; xoá tài khoản thì xoá hết; liên hệ. Thêm route công khai `GET /privacy` trong `backend/app/main.py`.
- [X] T013 [US1] Sửa `mobile/lib/url.ts`: thêm `isPrivateHost()` và `normalizeUrl()` chỉ giữ `http://` cho localhost/10.x/172.16–31.x/192.168.x; host khác thì đổi thành `https://`; không có scheme và là host công khai thì mặc định `https://`.
- [X] T014 [US1] Trong `mobile/app.config.js` đọc `EXPO_PUBLIC_API_URL` và đưa vào `extra`; ở màn hình đăng nhập (file gọi `setBaseUrl` trong `mobile/app/`), điền sẵn giá trị này nếu người dùng chưa lưu địa chỉ nào, vẫn cho sửa. (Đã có sẵn: `DEFAULT_URL` trong `mobile/lib/store.tsx` đọc `EXPO_PUBLIC_API_URL`; không cần sửa code.)
- [X] T015 [US1] Trong `mobile/lib/google.ts`, khi kết nối Gmail bị Google từ chối (`access_denied` hoặc người dùng không phải test user) thì hiện: "Gmail đang trong giai đoạn thử nghiệm, chỉ mở cho người dùng được mời. Bạn vẫn dùng được các tính năng khác."
- [X] T016 [P] [US1] Tạo `backend/deploy/mstudent.service`: User=mstudent, EnvironmentFile=/etc/mstudent.env, WorkingDirectory=/opt/mstudent/app/backend, `ExecStart=/opt/mstudent/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers` (để `client_ip()` tự xử lý `X-Forwarded-For`, tránh xử lý hai lần), Restart=always, NoNewPrivileges, ProtectSystem=strict, ReadWritePaths=/opt/mstudent/data.

**Checkpoint**: `pytest`, `ruff`, `npm test`, `npm run typecheck` đều xanh.

## Phase 4: User Story 2 — Dữ liệu không mất, chi phí không vượt kiểm soát (P2)

**Goal**: Giới hạn tần suất bền vững; trần LLM 5 USD/ngày; LLM có thời hạn chờ; sao lưu hằng ngày.

**Independent Test**: Khởi động lại thì bộ đếm và dữ liệu còn; đặt trần 0.0001 USD thì kết quả `offline`.

### Tests (US2)

- [X] T017 [P] [US2] Test `RateLimiter` lưu SQLite trong `backend/tests/test_production.py`: chạm giới hạn → trả số giây chờ; tạo instance mới (giả lập khởi động lại) → vẫn bị chặn; `reset()` hoạt động; test cũ `test_ai_rate_limit` vẫn xanh.
- [X] T018 [P] [US2] Test trần chi phí trong `backend/tests/test_production.py`: ghi usage vượt `MSTUDENT_LLM_DAILY_USD` → `budget.llm_allowed()` False và `ingest` trả `mode="offline"`; ngày mới (đổi `MSTUDENT_NOW`) → True; cảnh báo 80%/100% chỉ gửi một lần mỗi ngày (mock webhook).
- [X] T019 [P] [US2] Test timeout LLM trong `backend/tests/test_production.py`: mock `Runner.run` ngủ lâu hơn `MSTUDENT_LLM_TIMEOUT_S=0.1` → `ingest` trả `mode="offline"` và trace có lỗi timeout.
- [X] T020 [P] [US2] Test xoá tài khoản xoá luôn `llm_usage` của người đó trong `backend/tests/test_api.py`.

### Implementation (US2)

- [X] T021 [US2] Viết lại `RateLimiter` trong `backend/app/security.py` dùng bảng `rate_counters` (cửa sổ cố định theo `config.utcnow()`, `INSERT … ON CONFLICT(key, window_start) DO UPDATE SET count=count+1`, dọn bản ghi cũ hơn 2 ngày theo xác suất 1/200). Giữ nguyên chữ ký `hit()`/`reset()`.
- [X] T022 [US2] Thêm vào `backend/app/repo.py`: `record_llm_usage(user_id, agent, input_tokens, output_tokens, cost_usd, latency_ms)`, `llm_cost_on(day)`; mọi câu SQL dùng tham số `?`.
- [X] T023 [US2] Tạo `backend/app/budget.py`: `llm_allowed()` = `config.llm_enabled()` và `repo.llm_cost_on(today) < config.llm_daily_usd()`; `record(user_id, agent, result, started)` đọc `result.context_wrapper.usage` (dự phòng ước lượng ≈4 ký tự/token), tính chi phí, ghi DB, gửi cảnh báo 80%/100% một lần mỗi ngày qua `MSTUDENT_ALERT_WEBHOOK` (httpx, chạy nền, timeout 5 giây, nuốt lỗi), cờ lưu trong `settings` khoá `budget_alert:<day>:80|100`.
- [X] T024 [US2] Trong `backend/app/pipeline/llm_agents.py`, bọc mỗi `Runner.run` bằng `asyncio.wait_for(..., config.llm_timeout_s())` và gọi `budget.record(...)` sau khi thành công. Thêm tham số `user_id: int | None = None` cho `llm_triage`/`llm_extract`/`llm_digest`; cập nhật nơi gọi trong `backend/app/evaluation.py` và `ai_selfcheck()` (truyền None).
- [X] T025 [US2] Trong `backend/app/pipeline/orchestrator.py`, đổi `config.llm_enabled()` thành `budget.llm_allowed()` ở `ingest()` và `digest()`; truyền `user_id` vào các hàm LLM.
- [X] T026 [US2] Trong `backend/app/pipeline/assistant.py`, đổi sang `budget.llm_allowed()`, bọc `Runner.run` bằng `asyncio.wait_for`, gọi `budget.record(...)`. Khi timeout thì đi đường offline sẵn có.
- [X] T027 [P] [US2] Tạo `backend/deploy/backup.py`: dùng `sqlite3.connect(src).backup(dst)` ghi `/var/backups/mstudent/mstudent-YYYYMMDD.db` (thư mục 700, file 600), xoá bản cũ hơn 7 ngày; nhận đường dẫn qua tham số dòng lệnh.
- [X] T028 [P] [US2] Tạo `backend/deploy/mstudent-backup.service` (oneshot, User=mstudent) và `backend/deploy/mstudent-backup.timer` (`OnCalendar=*-*-* 03:00:00 Asia/Ho_Chi_Minh`, `Persistent=true`).

**Checkpoint**: test xanh; chạy thử `python deploy/backup.py` trên laptop rồi mở được bản sao lưu.

## Phase 5: Triển khai lên VPS (chặn US3/US4 trên production)

- [X] T029 Trên VPS làm theo `specs/001-backend-production/quickstart.md` mục 1–3: tạo user `mstudent`, venv, `/etc/mstudent.env` (quyền 600), `/opt/mstudent/data` (700), bật `mstudent` và `mstudent-backup.timer`; `curl localhost:8000/api/health` trả `ok`. Chạy `backup.py` một lần rồi **khôi phục thử** theo mục "Khôi phục từ sao lưu" của quickstart (FR-009, US2 kịch bản 2).
- [X] T030 Cài Tailscale và bật `tailscale funnel --bg 8000` theo `quickstart.md` mục 4; ghi địa chỉ `https://<máy>.ts.net` vào `docs/DEMO_RUNBOOK.md`. Kiểm tra từ 4G. Nếu Funnel không chạy thì lùi về `cloudflared tunnel --url http://localhost:8000` và ghi chú.
- [X] T031 Kiểm tra `X-Forwarded-For` qua Funnel: đăng nhập sai từ 2 máy khác nhau, xem audit log ghi 2 IP khác nhau. Nếu không có header thì ghi vào `docs/SECURITY.md`.
- [ ] T032 Build app Android với `EXPO_PUBLIC_API_URL=https://<máy>.ts.net`; cài lên điện thoại thật; chạy Independent Test của US1 và US2.

## Phase 6: User Story 3 — Số liệu thật cho buổi pitch (P3)

**Goal**: Admin xem số liệu tổng hợp không lộ dữ liệu cá nhân.

**Independent Test**: Admin mở thẻ "Số liệu" thấy con số đúng; tài khoản thường gọi `/api/admin/stats` bị 403.

- [X] T033 [P] [US3] Test trong `backend/tests/test_production.py`: không đăng nhập → 401; người thường → 403; admin → 200 đủ các khoá trong `contracts/api.md`; phản hồi không chứa email hay nội dung thông báo của dữ liệu mẫu.
- [X] T034 [US3] Thêm `repo.stats_summary(today)` trong `backend/app/repo.py` tính các trường ở `data-model.md` (users_total, users_active_7d, messages_total, messages_by_mode từ `traces.mode`, tasks_total, llm_cost_today_usd, llm_cost_per_active_user_usd, median_latency_ms).
- [X] T035 [US3] Thêm `GET /api/admin/stats` với `Depends(admin_user)` trong `backend/app/routers/core.py`, kèm `llm_budget_usd` và `llm_budget_exhausted`.
- [X] T036 [US3] Thêm thẻ "Số liệu" (chỉ hiện với admin) trong `backend/app/static/index.html` và `backend/app/static/app.js`: các ô số lớn, nút làm mới; không dùng script nội tuyến (CSP).

## Phase 7: User Story 4 — Biết ngay khi dịch vụ sập (P4)

**Independent Test**: `sudo systemctl stop mstudent` → cảnh báo đến trong 5 phút.

- [ ] T037 [US4] Tạo monitor UptimeRobot (HTTP(s), 5 phút) cho `https://<máy>.ts.net/api/health`, thêm kênh nhận cảnh báo; thử tắt dịch vụ để xác nhận; ghi lại vào `docs/DEMO_RUNBOOK.md`.
- [ ] T038 [US4] Đặt `MSTUDENT_ALERT_WEBHOOK` trên VPS (Discord hoặc Telegram) và thử gửi một cảnh báo chi phí bằng cách tạm đặt `MSTUDENT_LLM_DAILY_USD` rất thấp.

## Phase 8: Polish

- [X] T039 [P] Cập nhật `docs/SECURITY.md`: chuyển "Giới hạn tần suất lưu trong RAM" và "HTTPS" sang mục đã làm (kèm tên test); ghi rõ ổ VPS không mã hoá và biện pháp thay thế; thêm trần chi phí LLM.
- [X] T040 [P] Cập nhật `docs/DEMO_RUNBOOK.md`: mục Production (địa chỉ, kiểm tra trước giờ demo, xem số liệu) và đường lui về local; cập nhật `docs/GOOGLE_CLOUD_SETUP.md` cách thêm test user và URL `/privacy`.
- [X] T041 Tạo `backend/deploy/smoke_load.py` (httpx async, 30 yêu cầu đồng thời `GET /api/tasks` với 30 token thử, in p95 và số lỗi) và chạy với production để kiểm SC-003. Chạy toàn bộ: `cd backend && python -m pytest -q && ruff check .`, `MSTUDENT_OFFLINE=1 python -m eval.run_eval`, `cd mobile && npm test && npm run typecheck && npx expo lint`; chạy đường demo trong `DEMO_RUNBOOK` trên cả production và local.
- [X] T042 Nhờ vai trò `security-reviewer` (`.claude/agents/security-reviewer.md`) soát diff: client_ip, `/privacy`, stats, budget, rate limiter.

## Dependencies & Execution Order

- Phase 1 → Phase 2 → US1 (Phase 3) → US2 (Phase 4) → Triển khai (Phase 5) → US3, US4 → Polish.
- US3 chỉ cần Phase 2 (bảng `llm_usage`), có thể code song song với US2 nhưng nên làm sau triển khai để giữ trọng tâm.
- US4 cần dịch vụ đã chạy trên VPS (Phase 5).
- Trong mỗi story: test → code → checkpoint.

## Parallel Opportunities

- US1: T006, T007, T008, T009 cùng lúc; T012 và T016 song song với T010/T011.
- US2: T017–T020 cùng lúc; T027, T028 (deploy) song song với T021–T026 (code).
- Polish: T039, T040 cùng lúc.

## Implementation Strategy

1. **Tối thiểu để demo (khoảng 2–3 giờ)**: T001–T016 + T029–T032. App chạy qua 4G với HTTPS.
2. **An toàn chi phí (khoảng 1–2 giờ)**: T017–T028, triển khai lại.
3. **Điểm pitch (khoảng 1 giờ)**: T033–T036, T037–T038.
4. **Trước khi ngủ**: T039–T042. Nếu hết giờ thì bỏ US3/US4 trước, **không bao giờ** bỏ T041.
