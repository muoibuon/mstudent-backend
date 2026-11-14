# Tasks: Tự động thu thập thông báo học tập

**Input**: Design documents from `/specs/002-auto-ingest/` (plan.md, spec.md, research.md, data-model.md, contracts/api.md,
quickstart.md, checklists/ux.md)

**Tests**: Bắt buộc theo Constitution II. Viết test trước hoặc cùng lúc; sau mỗi phase chạy
`cd backend && python -m pytest -q && ruff check .` và (nếu sửa mobile) `cd mobile && npm test && npm run typecheck && npx expo lint`.
Mọi gọi ra ngoài (Gmail, Classroom, Sheets, Expo, Pub/Sub JWKS) trong test đều mock — không gọi mạng.

**Hạn chót**: demo 2026-11-14. Thứ tự làm thực tế: Phase 1 → 2 → **US3** → **US1** → US2 → US4 → Polish → US5 (xem cuối file).

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [X] T001 Thêm biến vào `backend/app/config.py` và `backend/deploy/mstudent.env.example` (chú thích tiếng Việt): `MSTUDENT_SYNC_ENABLED` (mặc định 1 ở prod, 0 khi chạy test), `MSTUDENT_GMAIL_POLL_S=120`, `MSTUDENT_PUBLIC_URL`, `MSTUDENT_PUBSUB_TOPIC`, `MSTUDENT_PUBSUB_PUSH_SA`, `MSTUDENT_SYNC_CONCURRENCY=4`; tắt sync trong `backend/tests/conftest.py`.
- [X] T002 [P] Thêm `classroom` và `sheet` vào enum `Source` (`backend/app/models.py`) và `mobile/lib/types.ts`; thêm `sources: list[str]`, `note: str | None` vào `Task` (backend + `types.ts`).

## Phase 2: Foundational (chặn mọi user story)

### Tests

- [X] T003 [P] `backend/tests/test_sync.py`: lease chống chạy trùng (2 lần `claim()` cùng lúc chỉ 1 thành công), lùi dần khi lỗi (`fail_count` 1→2→3 ⇒ 2/4/8 phút, tối đa 60), lỗi xác thực ⇒ `enabled=0` + `last_error` "Cần kết nối lại", một kết nối lỗi không chặn kết nối khác.
- [X] T004 [P] `backend/tests/test_api.py` (Constitution II: test cách ly endpoint mới nằm ở đây): `/api/sources`, `/api/push/register` — 401 khi chưa đăng nhập; người B không xem/sửa/xoá/đồng bộ được nguồn của A (404); giới hạn 10 bảng + 5 ics (422); trùng (409); xoá tài khoản ⇒ `sync_connections`, `source_items`, `push_tokens` = 0 dòng.
- [X] T005 [P] `backend/tests/test_sync.py`: `planner.match_existing` (FR-009) — cùng mã học phần + tiêu đề gần ⇒ gộp, `sources` có cả hai nguồn; khác mã môn ⇒ không gộp dù cùng tiêu đề; việc `done` không bị mở lại (FR-074); hạn từ nguồn có cấu trúc thắng hạn từ email.

### Implementation

- [X] T006 Thêm bảng `sync_connections`, `source_items`, `push_tokens` vào `SCHEMA` (`backend/app/db.py`) đúng `data-model.md`; thêm cột `tasks.sources`, `tasks.note` bằng hàm `_ensure_column()` (kiểm `PRAGMA table_info`, chỉ `ALTER TABLE ADD COLUMN` khi thiếu — DB production đang có dữ liệu).
- [X] T007 Repo trong `backend/app/repo.py` (mọi hàm nhận `user_id`, SQL tham số): `create_connection`, `list_connections`, `get_connection`, `set_connection_enabled`, `delete_connection`, `claim_due_connections(now, lease_s, limit)`, `finish_run(id, ok, error, cursor, state, next_run_at)`, `upsert_source_item`, `get_source_item`, `mark_items_gone`; cập nhật `insert_task`/`update_task`/`list_tasks` cho `sources`, `note`; `delete_user` xoá thêm 3 bảng (CASCADE đã có, thêm test).
- [X] T008 `backend/app/pipeline/planner.py`: viết `match_existing()` theo research R7 (chuẩn hoá mã học phần / tên môn bỏ dấu; khác môn ⇒ không gộp; ngưỡng tiêu đề 0,45 cùng ngày / 0,8 / 0,35 khi trùng mã), dùng trong `plan()`; thêm tham số `source_rank` để hạn từ Classroom/ics thắng; ghi thêm nguồn vào `sources`; bỏ qua việc `done`.
- [X] T009 `backend/app/sync/scheduler.py`: vòng lặp 15 s trong `lifespan` (`backend/app/main.py`), `claim_due_connections`, semaphore `MSTUDENT_SYNC_CONCURRENCY`, timeout 90 s/lượt, bảng `RUNNERS = {kind: async fn(conn) -> RunResult}`, lùi dần, phân loại lỗi xác thực vs tạm thời, jitter ±10 %; `run_now(conn_id)` đặt `next_run_at=now`. Log chỉ có id kết nối + loại lỗi (không token, không nội dung).
- [X] T010 `backend/app/routers/sources.py`: `GET/POST /api/sources`, `PATCH/DELETE /api/sources/{id}`, `POST /api/sources/{id}/sync` (ai_limit + 6 lần/10 phút) đúng `contracts/api.md`; model `SourceCreate` (`kind` ∈ {ics, sheet}, `url` ≤ 2000, `label` ≤ 100) trong `models.py`; gắn router vào `main.py`.
- [X] T011 [P] `mobile/lib/sources.ts` + test trong `mobile/lib/__tests__/logic.test.ts`: nhãn tiếng Việt theo `kind`, `relativeTime()` giờ VN ("vừa xong", "5 phút trước", "hôm qua 21:30") (FR-079), `statusOf(source)` (ok / lỗi / tắt).
- [X] T012 `mobile/lib/api.ts` + `types.ts`: `listSources`, `addSource`, `setSourceEnabled`, `deleteSource`, `syncSourceNow`, kiểu `SourceConnection`.
- [X] T013 `mobile/app/sources.tsx` (màn hình **Nguồn tự động**, FR-070/071/078) + lối vào trong `mobile/app/(tabs)/settings.tsx` + khai báo màn hình trong `mobile/app/_layout.tsx` (Protected khi đã đăng nhập): danh sách nguồn với trạng thái và lỗi, nút "Đồng bộ ngay", công tắc bật/tắt, xoá; form "Thêm bảng lớp" / "Thêm lịch LMS" (dán link); sau khi thêm hiện kết quả lượt đầu (poll `GET /api/sources` 1 phút).
- [X] T014 [P] `mobile/components/ui.tsx` (`TaskRow`): hiện nhãn nguồn và các nguồn đã gộp (FR-073) + `note` nếu có.

**Checkpoint**: test cũ + mới xanh; production vẫn chạy như trước khi `MSTUDENT_SYNC_ENABLED=0`.

## Phase 3: User Story 1 — Email và lịch LMS tự vào (P1) 🎯 MVP

**Goal**: Gmail tự đồng bộ (≤ 3 phút; ≈ 1 phút khi có Pub/Sub), `.ics` tự tải lại mỗi giờ.

**Independent Test**: quickstart mục 1 và 2.

### Tests (US1)

- [X] T015 [P] [US1] `backend/tests/test_sync.py`: runner Gmail — lần đầu dùng list 7 ngày và lưu `historyId`; lần sau `history.list` rỗng ⇒ 0 lời gọi AI, 0 việc; có thư mới ⇒ đi qua `orchestrator.ingest` với đúng `user_id`; `historyId` hết hạn (404) ⇒ quay lại list 1 ngày; `invalid_grant` ⇒ tắt kết nối + "Cần kết nối lại Gmail" (FR-014); chạm hạn mức ⇒ mode offline (FR-004).
- [X] T016 [P] [US1] `backend/tests/test_sync.py`: `/api/hooks/gmail` — không có / sai chữ ký, sai `aud`, sai `email` ⇒ 403; đúng ⇒ 204 và `next_run_at` của kết nối khớp email = now; email lạ ⇒ vẫn 204, không đổi gì; body > 8 KB ⇒ 413. (Ký JWT bằng khoá RSA sinh trong test, monkeypatch bộ lấy JWKS.)
- [X] T017 [P] [US1] `backend/tests/test_sync.py`: runner ics — tạo việc từ sự kiện; đổi `DTSTART` cùng `UID` ⇒ cập nhật hạn, không tạo bản thứ hai; lượt đầu bỏ sự kiện quá hạn > 1 ngày (FR-075); ETag không đổi (304) ⇒ không xử lý; URL nội bộ ⇒ 400 khi thêm; link không tải được / không phải lịch ⇒ 400 với thông điệp riêng gợi ý lấy lại link xuất lịch (FR-072).
- [X] T018 [P] [US1] `backend/tests/test_google.py`: `connect` với scope Gmail ⇒ tạo kết nối `gmail`; `disconnect` ⇒ xoá kết nối `gmail`/`classroom`.

### Implementation (US1)

- [X] T019 [US1] `backend/app/google_api.py`: `get_profile(token)`, `history_message_ids(token, start_history_id)` (lọc INBOX, messageAdded; ném `HistoryExpired` khi 404), `watch(token, topic)`, phân loại lỗi `AuthRevoked` (400 invalid_grant / 401) vs `GoogleError`.
- [X] T020 [US1] `backend/app/sync/gmail.py`: runner theo research R2 (dùng lại vòng `get_message` + bỏ qua `messages` đã có như `routers/google.py`); gia hạn `watch` khi `state.watch_expires_at` < 24 h nếu có `MSTUDENT_PUBSUB_TOPIC`; trả `RunResult` (mới / cập nhật / bỏ qua / mode).
- [X] T021 [US1] `backend/app/routers/google.py`: `connect` tạo/bật kết nối `gmail` (và lưu email), `disconnect` xoá kết nối Google; giữ nguyên `POST /api/google/gmail/sync` (đường demo cũ).
- [X] T022 [US1] `backend/app/routers/hooks.py`: `POST /api/hooks/gmail` theo contracts (OIDC: lấy JWKS `https://www.googleapis.com/oauth2/v3/certs`, cache 1 h, kiểm `iss`/`aud`/`email`/`email_verified`/`exp`), giới hạn 120/phút toàn hệ thống, body ≤ 8 KB, luôn 204; gắn vào `main.py`; cập nhật danh sách endpoint công khai trong `AGENTS.md` và `docs/SECURITY.md`.
- [X] T023 [US1] `backend/app/sync/ics.py`: runner theo research R6 (dùng `lms_ics.fetch` + `_assert_public_url`, ETag, `source_items` theo `UID`, FR-074/075); `POST /api/sources` kind `ics` kiểm URL và tải thử trước khi lưu; lỗi ⇒ thông điệp tiếng Việt riêng cho LMS (FR-072).
- [ ] T024 [P] [US1] `mobile/app/sources.tsx`: thẻ hướng dẫn "Chuyển tiếp email trường (Outlook/Teams) sang Gmail" (FR-012) — 4 bước ngắn, mở link cài đặt Outlook web.

**Checkpoint**: quickstart mục 1 (không Pub/Sub ⇒ ≤ 3 phút) và mục 2 đạt trên máy dev với Gmail thật.

## Phase 4: User Story 2 — Google Classroom (P2)

**Goal**: bài tập có hạn tự thành việc đúng hạn; nộp bài ⇒ xong; thông báo lớp qua AI.

**Independent Test**: quickstart mục 3.

### Tests (US2)

- [X] T025 [P] [US2] `backend/tests/test_sync.py`: runner Classroom với dữ liệu giả — lọc lớp theo FR-024 (tạo ≤ 60 ngày hoặc hoạt động ≤ 14 ngày); `dueDate`+`dueTime` UTC ⇒ `+07:00` đúng; thiếu `dueTime` ⇒ 23:59; đổi hạn ⇒ cập nhật; `TURNED_IN` ⇒ việc `done`; bài không hạn ⇒ việc không hạn; thông báo lớp ⇒ `ingest` 1 lần (id `classroom-ann-…`); lượt đầu bỏ bài quá hạn > 1 ngày; 0 lời gọi AI cho bài tập.
- [X] T026 [P] [US2] `backend/tests/test_google.py`: `connect` có đủ 3 scope Classroom ⇒ tạo kết nối `classroom`; thiếu scope ⇒ không tạo; lỗi 403 từ Classroom (trường chặn) ⇒ `last_error` giải thích, kết nối Gmail không bị ảnh hưởng.

### Implementation (US2)

- [X] T027 [US2] `backend/app/config.py` + `google_api.py`: hằng scope Classroom; `exchange_code` chấp nhận token có Classroom mà không có Gmail; hàm `classroom_courses`, `classroom_coursework`, `classroom_submissions`, `classroom_announcements` (phân trang, timeout, chỉ trường cần dùng).
- [X] T028 [US2] `backend/app/sync/classroom.py`: runner theo research R4 (tạo việc trực tiếp qua `planner.plan` với `source=classroom`, category theo `workType`/tiêu đề, course = tên lớp; `source_items` theo `courseWorkId`; FR-074/075).
- [X] T029 [US2] `mobile/lib/google.ts`: tham số `withClassroom` xin thêm 3 scope; `mobile/app/sources.tsx`: thẻ "Google Classroom" với nút "Cho phép đọc Classroom" (đăng nhập lại Google với scope bổ sung → `POST /api/google/connect`), giải thích chỉ đọc.

**Checkpoint**: quickstart mục 3 với lớp thử thật.

## Phase 5: User Story 3 — Bảng deadline của lớp (P3)

**Goal**: dán link bảng công khai một lần; dòng mới / sửa / xoá được phản ánh tự động.

**Independent Test**: quickstart mục 4.

### Tests (US3)

- [X] T030 [P] [US3] `backend/tests/test_sync.py`: chuẩn hoá link (`/edit#gid=123`, `/edit?usp=sharing`, `/htmlview`) ⇒ URL export CSV đúng; link không phải `docs.google.com/spreadsheets` ⇒ 400; chuyển hướng tới host ngoài allowlist ⇒ lỗi; HTML trả về (bảng riêng tư) ⇒ `last_error` hướng dẫn chia sẻ; > 1 MB hoặc > 2 000 dòng ⇒ lỗi rõ.
- [X] T031 [P] [US3] `backend/tests/test_sync.py`: SheetMapper (Runner giả) trả vai trò cột ⇒ tạo đúng việc; lượt sau không đổi ⇒ 0 lời gọi AI; thêm dòng ⇒ +1 việc; sửa hạn ⇒ cập nhật; xoá dòng ⇒ `note` "Không còn trong bảng lớp", không xoá việc; tiêu đề cột đổi ⇒ gọi lại mapper; AI tắt ⇒ đoán cột bằng luật ("môn", "mã hp", "nội dung", "hạn", "deadline", "ngày", "giờ"); ngày "20/11", "20/11/2026 23:59", "23h59 20/11" phân tích đúng `+07:00`.

### Implementation (US3)

- [X] T032 [US3] `backend/app/agent_config.py`: thêm `sheet_mapper_prompt` vào `DEFAULTS` (nối `GUARD`), model `SheetMapping` (mọi trường bắt buộc) trong `models.py`; `backend/app/pipeline/llm_agents.py`: `llm_map_sheet(header, samples, user_id)` qua `run_llm` (không tool).
- [X] T033 [US3] `backend/app/sync/sheets.py`: `normalize_sheet_url()`, `fetch_csv()` (httpx, theo chuyển hướng thủ công ≤ 3 lần chỉ tới `docs.google.com` / `*.googleusercontent.com`, kiểm IP công khai, 1 MB, 15 s), `map_columns()` (AI → luật dự phòng, lưu theo hash tiêu đề trong `state`), `parse_row_due()` (luật ngày giờ VN), runner theo research R5 (dòng không phân tích được ⇒ Extractor AI; `source_items` theo hash môn+nội dung; FR-032/074/075).
- [X] T034 [US3] `POST /api/sources` kind `sheet`: chuẩn hoá + tải thử ngay (trả 400 với thông điệp tiếng Việt nếu riêng tư / không phải bảng), `label` mặc định = tiêu đề trang tính nếu lấy được, ngược lại "Bảng lớp".

**Checkpoint**: quickstart mục 4 với bảng thật; `llm_usage` không tăng khi bảng không đổi.

## Phase 6: User Story 4 — Điện thoại tự nhận việc mới (P4)

**Goal**: Android có thông báo đẩy ≤ 1 phút; iPhone bản miễn phí tự làm mới nền.

**Independent Test**: quickstart mục 1 bước 3 (Android) và mục 6 (iPhone).

### Tests (US4)

- [X] T035 [P] [US4] `backend/tests/test_sync.py`: `/api/push/register` kiểm regex token, chuyển chủ khi người khác đăng ký cùng token, DELETE chỉ xoá token của mình; `notify.after_run` gộp 1 thông báo/lượt/nguồn (FR-076), lượt đầu của nguồn không gửi, tôn trọng người dùng tắt nhắc (FR-042 — trường `notify` của token; `notify=false` ⇒ không gửi), `DeviceNotRegistered` ⇒ xoá token, nội dung chỉ có tên việc + hạn.
- [X] T036 [P] [US4] `mobile/lib/__tests__/logic.test.ts`: logic thuần của làm mới nền — so danh sách việc cũ/mới ⇒ đúng tập việc mới cần đặt nhắc; không đặt trùng.

### Implementation (US4)

- [X] T037 [US4] `backend/app/sync/notify.py`: gom việc mới/dời hạn của một lượt, gửi Expo Push (httpx nền, timeout 5 s, nuốt lỗi, `channelId` default, `data.task_ids`); `routers/sources.py`: `POST/DELETE /api/push/register` (model `PushRegister`); gọi từ scheduler sau mỗi lượt có thay đổi.
- [X] T038 [US4] `mobile/lib/push.ts`: xin quyền thông báo, `getExpoPushTokenAsync({projectId})` (bỏ qua êm nếu lỗi — iPhone ký miễn phí), đăng ký khi đăng nhập / bật nhắc, huỷ khi đăng xuất; xử lý bấm thông báo ⇒ mở tab việc và đưa việc mới lên đầu (FR-077).
- [X] T039 [US4] `mobile/lib/background.ts`: `npx expo install expo-background-task expo-task-manager`; đăng ký task (khoảng tối thiểu 15 phút) tải `/api/tasks`, đặt nhắc cục bộ cho việc mới qua `lib/reminders.ts`; `settings.tsx` hiện dòng giới hạn iPhone (FR-041).

**Checkpoint**: Android (APK mới từ thành viên Android) nhận thông báo khi app đóng; iPhone mở app thấy việc mới.

## Phase 7: User Story 5 — Zalo trên Android (P5)

**Goal**: tin trong nhóm Zalo đã chọn tự thành việc, tin khác không rời máy.

**Independent Test**: quickstart mục 7.

- [X] T040 [P] [US5] `mobile/lib/zaloFilter.ts` + test: quyết định gửi / không gửi theo gói `com.zing.zalo`, tiêu đề nhóm nằm trong danh sách chọn, bỏ tin trùng trong 10 phút, cắt 8 000 ký tự.
- [ ] T041 [US5] `mobile/modules/zalo-listener/` (Expo Modules API, Kotlin): `NotificationListenerService` lọc gói Zalo, lưu hàng đợi, `WorkManager` gửi `POST /api/ingest` (source `zalo`) dùng refresh token trong Keystore; API JS: `isPermissionGranted`, `openPermissionSettings`, `setGroups`, `recentGroups` (tên nhóm thấy gần đây để chọn); config plugin thêm `<service>` vào manifest.
- [ ] T042 [US5] `mobile/app/sources.tsx` (chỉ Android): thẻ "Tự đọc tin Zalo" — giải thích (FR-052), mở cài đặt quyền, chọn nhóm từ `recentGroups`, tắt / thu hồi (FR-051).
- [ ] T043 [US5] Cập nhật `docs/HANDOFF_ANDROID.md`: build APK mới, kiểm thử quickstart mục 7.

## Phase 7b: User Story 7 — Tệp và tài liệu trong email (P1b, bổ sung 2026-11-14)

**Goal**: đọc PDF / Word / Excel / CSV đính kèm và link Google Docs/Sheets/Slides công khai, tóm gọn, tạo việc.

- [X] T051 [P] [US7] `backend/tests/test_docs.py`: rút chữ PDF/DOCX/XLSX/CSV; giới hạn kích thước, số trang, zip bomb, tệp hỏng/mật khẩu → bỏ qua có lý do; thu gọn giữ dòng có ngày/từ khoá; tìm link Google Docs/Sheets/Slides trong thân email.
- [X] T052 [P] [US7] `backend/tests/test_sync.py`: email liên quan có PDF → tạo việc từ nội dung PDF, ghi chú tóm tắt; email không liên quan → không tải tệp; cùng tệp lần hai → không chạy lại AI; link riêng tư → ghi chú, không lỗi.
- [X] T053 [US7] `backend/requirements.txt` thêm `pypdf`; `backend/app/connectors/docs.py`: `extract_text(name, mime, data)`, `focus(text)`, `find_doc_links(body)`, `fetch_public_doc(url)` (dùng bộ tải an toàn của `sync/sheets.py`).
- [X] T054 [US7] `backend/app/google_api.py`: `get_message_parts(token, id)` trả `Message` + danh sách tệp đính kèm (tên, mime, kích thước, attachmentId); `get_attachment(token, msg_id, att_id)`.
- [X] T055 [US7] `backend/app/agent_config.py` + `llm_agents.py`: prompt + `llm_summarize_doc()` (không tool, GUARD); `backend/app/sync/docs_ingest.py`: `ingest_documents(uid, token, gmail_id, msg, result)` — chỉ khi relevant, mỗi tài liệu thành thông báo `doc-<sha>` qua `orchestrator.ingest`, gắn tóm tắt vào `tasks.note`.
- [X] T056 [US7] Gọi `ingest_documents` từ `sync/gmail.py` và `routers/google.py` (đồng bộ tay).
- [X] T057 [US7] Cập nhật `docs/SECURITY.md` (tệp đính kèm là dữ liệu không tin cậy, giới hạn, không macro) và `docs/DEMO_RUNBOOK.md`.

## Phase 8: User Story 6 — Microsoft 365 (P6, sau demo)

- [X] T044 [US6] Ghi hướng dẫn chuyển tiếp Outlook → Gmail vào `docs/DEMO_RUNBOOK.md` và lộ trình Microsoft Graph (đăng ký ứng dụng, quyền `Mail.Read` / `EduAssignments.ReadBasic`, cần CNTT trường duyệt) vào `docs/ARCHITECTURE.md`. Không code trong đợt này.

## Phase 9: Polish & triển khai

- [ ] T045 Triển khai lên VM: rsync, `install.sh`, điền biến mới vào `/etc/mstudent.env`, kiểm `journalctl` không có lỗi scheduler; chạy quickstart mục 1–5, 8 trên production (Gmail thật, lớp Classroom thử, bảng thật).
- [X] T046 [P] Hướng dẫn cấu hình Google cho người dùng (OAuth Web + iOS client, Classroom API, Pub/Sub topic + push subscription OIDC trỏ tới `https://<máy>.ts.net/api/hooks/gmail`) trong `docs/GOOGLE_CLOUD_SETUP.md`.
- [ ] T047 [P] Cập nhật `docs/SECURITY.md` (webhook OIDC, token Google, SSRF bảng lớp, dữ liệu trong thông báo đẩy, Zalo chỉ nhóm đã chọn) và `docs/DEMO_RUNBOOK.md` (kịch bản demo tự động: gửi email → Android báo; bảng lớp → iPhone mở app thấy).
- [ ] T048 Build lại iOS (`MSTUDENT_IOS_FREE_SIGNING=1`, có `GOOGLE_IOS_URL_SCHEME`) và cài lên iPhone; kiểm nút Google + màn hình Nguồn.
- [X] T049 Soát bảo mật (vai trò `security-reviewer`) cho diff `002-auto-ingest`: webhook, token, SSRF, cách ly `user_id`, prompt SheetMapper.
- [X] T050 Chạy toàn bộ: `pytest`, `ruff`, `MSTUDENT_OFFLINE=1 python -m eval.run_eval`, `npm test`, `npm run typecheck`, `npx expo lint`; `deploy/smoke_load.py` trên production khi scheduler đang chạy (SC-003 của 001 vẫn đạt); theo dõi chi phí AI trong thẻ Số liệu 24 h đầu (SC-006).

## Dependencies & Execution Order

- Phase 1 → Phase 2 (chặn tất cả).
- US1, US2, US3 độc lập với nhau sau Phase 2; US2 dùng chung phần Google của US1 (T019, T021).
- US4 cần ít nhất một runner tạo việc (US1 hoặc US3). US5 độc lập backend, cần thành viên Android build.
- **Thứ tự thực tế cho demo**: Phase 2 → **US3** (không chờ cấu hình Google) → **US1** (khi có OAuth; Pub/Sub T022 khi có topic) → US2 → US4 → T045–T050 → US5.

## Parallel Opportunities

- Phase 2: T003, T004, T005 cùng lúc; T011, T014 song song với backend.
- US1: T015–T018 cùng lúc; T024 (mobile) song song với T019–T023.
- US3: T030, T031 cùng lúc.
- Polish: T046, T047 cùng lúc.

## Implementation Strategy

1. **Tối thiểu cho demo (~4 h)**: Phase 1–2 + US3 + US1 (poll 2 phút) + T045. Kịch bản: sửa bảng lớp / gửi email → việc tự
   xuất hiện, không ai chạm app. Đạt SC-007 phần iPhone (mở app thấy việc); phần **Android báo nền** cần thêm US4.
2. **Tăng điểm (~2,5 h)**: US2 Classroom, T022 Pub/Sub (≈ 1 phút).
3. **Điện thoại (~2 h)**: US4 (Android báo nền, iPhone làm mới nền).
4. **Sau demo**: US5 Zalo Android, US6 Microsoft 365. Nếu hết giờ, bỏ theo thứ tự US5 → US4 → US2; **không bỏ** T049, T050.
