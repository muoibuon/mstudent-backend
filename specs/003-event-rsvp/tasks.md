# Tasks: Sự kiện của trường — Tham gia / Không, phù hợp với ngành

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/api.md (`/specs/003-event-rsvp/`)

**Tests**: bắt buộc (Constitution II). Sau mỗi phase: `cd backend && python -m pytest -q && ruff check .`;
`cd mobile && npm test && npm run typecheck && npx expo lint`. Không gọi mạng trong test.

## Phase 1: Foundational

- [x] T001 `backend/app/db.py`: `_ensure_column` cho users (school_name, school_abbr, degree_level, major_code, major_name, student_id, class_name, phone, profile_snooze_until) và tasks (rsvp, event_end, event_url, register_url, register_deadline, mandatory, fit_level, fit_reason, fit_mode, form_meta, reg_task_id).
- [x] T002 `backend/app/models.py`: `Profile`, `ProfileUpdate` (giới hạn độ dài, `degree_level` Literal), `RsvpRequest`, `EventDetails`, `MajorFitOut` (mọi trường bắt buộc); `Task` thêm trường sự kiện; `mobile/lib/types.ts` tương ứng.
- [x] T003 `backend/app/repo.py`: `get_profile`, `save_profile`, `snooze_profile`; `list_tasks` mặc định loại `rsvp IN ('pending','declined')`; `list_events(user_id, state)`; `set_event_fields`; `set_rsvp`.

## Phase 2: User Story 1 — Hồ sơ trường/ngành (P1)

- [x] T004 [P] [US1] `backend/tests/test_api.py`: `/api/catalog` (401, ETag/304, có HUST/VNU-VJU, 3 bậc), `/api/profile` GET/PUT/snooze cách ly người dùng, giới hạn độ dài, `needs_profile`.
- [x] T005 [US1] `backend/app/routers/profile.py`: `GET /api/catalog` (nạp `app/data/*.json` một lần, ETag = hash), `GET/PUT /api/profile`, `POST /api/profile/snooze`; gắn vào `main.py`.
- [x] T006 [P] [US1] `mobile/lib/catalog.ts` + test: `searchSchools(q)` (bỏ dấu, viết tắt không phân biệt "-"/khoảng trắng, xếp khớp viết tắt trước), `majorsFor(catalog, schoolAbbr, level, q)` (chương trình của trường trước, rồi danh mục quốc gia; tìm theo tên/mã).
- [x] T007 [US1] `mobile/app/profile.tsx`: màn "Bạn học ở đâu?" theo UI Kit — ô tìm trường + danh sách, 3 nút bậc (Đại học / Thạc sĩ / Tiến sĩ), ô tìm ngành + danh sách, MSSV/lớp/SĐT tuỳ chọn, nút Lưu (vàng chanh) / Để sau (viền); `_layout.tsx` chuyển tới màn này khi `needs_profile`; Cài đặt có mục "Hồ sơ học tập" mở màn này.

## Phase 3: User Story 2 — Lời mời Tham gia / Không (P1)

- [x] T008 [P] [US2] `backend/tests/test_events.py`: tin sự kiện → task `rsvp=pending` + chi tiết (Runner giả và luật offline); bắt buộc → `going`; `/rsvp` going tạo việc "Đăng ký …" khi có hạn đăng ký, declined ẩn khỏi `/api/tasks` và đóng việc đăng ký; đổi ý; bắt buộc + không → 409; `/api/events` lọc trạng thái + ẩn pending đã qua giờ; link không phải http(s) bị bỏ; đọc cấu trúc Google Form (HTML giả có `FB_PUBLIC_LOAD_DATA_`), form riêng tư → không có form_meta.
- [x] T009 [P] [US2] `backend/tests/test_api.py`: `/api/events`, `/api/tasks/{id}/rsvp` 401/404 chéo người dùng.
- [x] T010 [US2] `backend/app/agent_config.py` + `pipeline/llm_agents.py`: `event_prompt` + `llm_event_details()`; `backend/app/pipeline/events.py`: `details_rules()`, `enrich_event(uid, task, msg)`, `fetch_form_meta(url)` (allowlist docs.google.com/forms.gle, ≤ 1 MB, parse `FB_PUBLIC_LOAD_DATA_`, ghép vai trò bằng từ khoá).
- [x] T011 [US2] `backend/app/pipeline/orchestrator.py`: sau planner, việc category `event` mới → `enrich_event` (pending/going); `backend/app/routers/profile.py`: `GET /api/events`, `POST /api/tasks/{id}/rsvp`.
- [x] T012 [US2] `backend/app/sync/notify.py`: lời mời mới → thông báo `categoryId=event_invite`, `data.type=invite`.
- [x] T013 [P] [US2] `mobile/lib/prefill.ts` + test: `prefillUrl(form_meta, profile, email, name)` (chỉ vai trò có dữ liệu, mã hoá URL, chỉ docs.google.com); `mobile/lib/events.ts` + test: sắp lời mời (mức phù hợp rồi thời gian), ẩn đã qua.
- [x] T014 [US2] `mobile/components/InviteCard.tsx` (thẻ màu, giờ/địa điểm, nhãn Bắt buộc, mức phù hợp + lý do, nút Tham gia vàng chanh / Không viền); `tasks.tsx`: khối "SỰ KIỆN MỚI" + "Đã bỏ qua"; `TaskCard`: nút "Mở link" / "Đăng ký (đã điền sẵn)" cho sự kiện đã tham gia; `api.ts` + `store.tsx` (events, rsvp).
- [x] T015 [US2] `mobile/lib/notifications.ts` + `_layout.tsx`: category `event_invite` (Tham gia / Không), xử lý bấm hành động → rsvp.

## Phase 4: User Story 3 — Phù hợp với ngành (P2)

- [x] T016 [P] [US3] `backend/tests/test_events.py`: MajorFit (Runner giả) nhắc tên ngành; offline luật CNTT vs Ngôn ngữ cho cùng sự kiện ra mức khác nhau, `fit_mode=offline`; chưa có ngành → không tính; đổi ngành → tính lại pending.
- [x] T017 [US3] `pipeline/events.py`: `fit_rules()` (từ khoá ngành + nhóm lĩnh vực), `assess_fit(uid, task)` (LLM nếu được phép, không thì luật); gọi trong `enrich_event`; `PUT /api/profile` đổi ngành → tính lại nền.

## Phase 5: Polish

- [x] T018 `docs/SECURITY.md` (hồ sơ, link điền sẵn dựng trên máy, form không tự gửi), `docs/DEMO_RUNBOOK.md` (kịch bản lời mời + ngành).
- [x] T019 Soát bảo mật diff 003 (vai trò `security-reviewer`); sửa mức Cao/Trung bình.
- [x] T020 Chạy toàn bộ test/lint/eval; triển khai backend; build lại iOS và cài.

## Dependencies

Phase 1 → US1 → US2 → US3 → Polish. US3 cần hồ sơ (US1) và lời mời (US2). T013 song song với backend US2.
