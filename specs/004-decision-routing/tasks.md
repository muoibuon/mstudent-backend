# Tasks: AI quyết định điều phối toàn bộ luồng xử lý thông báo

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/decision-request.md (`specs/004-decision-routing/`)

**Tests**: bắt buộc (Constitution II). Sau mỗi phase: `python -m pytest -q && ruff check .` và
`MSTUDENT_OFFLINE=1 python -m eval.run_eval`. Không gọi mạng trong test (Decisions API giả bằng `httpx.MockTransport`,
GPT bằng Runner giả).

## Phase 1: Foundational

- [x] T001 `app/agent_config.py`: khoá `decision_low` (0.15), `decision_high` (0.60), `decision_min_conf` (0.80) trong
  `DEFAULTS`; `thresholds()` đọc, kẹp [0, 1], buộc `low ≤ high`; `save()` từ chối giá trị không phải số. `app/config.py`:
  bỏ `decision_min_relevant`.
- [x] T002 `tests/test_routing.py`: fixture `decisions` (MockTransport trả lời theo câu hỏi nhận được, ghi lại request) +
  Runner giả đếm lượt GPT; test `thresholds()` (kẹp, `low ≤ high`, giá trị rác).
- [x] T003 `app/pipeline/decision.py`: `DecisionResult`, `DecisionError`; `build_questions(context)` (câu cơ bản R1);
  `parse(answers, sent)` hợp lệ hoá chặt (R7); `decide(msg, user_id, context)` — chỉ gọi khi `GEMINI_API_KEY` có và
  `budget.llm_allowed(user_id)`; một request, người gửi bỏ email, nội dung `render()`, câu `relevant` nối câu nhắc kiểu
  GUARD; ghi `llm_usage` (agent `Decision`, cả lượt lỗi); `route(result, thresholds)` → `(route, reason)`.

## Phase 2: User Story 1 + 2 — Một lượt quyết định, tuyến xem lại (P1)

- [x] T004 [P] [US1] `tests/test_routing.py`: tin nhiễu → tuyến dừng, 0 lượt GPT, trace "Decision"; tin rõ ràng → đi
  thẳng, chỉ Extractor (không GPT Triage), Extractor nhận dòng ngữ cảnh ngoài `<thong_bao>`; việc không có hạn lấy ưu
  tiên từ `urgency`; request không chứa email người gửi, MSSV, SĐT; tin đã xử lý không
  gọi lại lượt quyết định; nguồn có cấu trúc (lịch LMS, bài tập Classroom) không gọi lượt quyết định; hết hạn mức → luật.
- [x] T005 [P] [US2] `tests/test_routing.py`: xác suất lưng chừng / độ tin cậy thấp → xem lại (GPT Triage quyết định
  cuối); HTTP lỗi, `error.code=safety`, lựa chọn ngoài tập, xác suất ngoài [0,1], thiếu câu → luồng cũ, không mất tin;
  chưa có khoá → luồng cũ; offline → bộ luật; đổi ngưỡng qua `agent_config.save` đổi tuyến.
- [x] T006 [US1] `app/pipeline/llm_agents.py`: `llm_triage` chỉ còn GPT (bỏ gọi Gemini bên trong);
  `llm_extract(msg, user_id, hint=None)` nối dòng ngữ cảnh hệ thống sau `render()`.
- [x] T007 [US1] `app/pipeline/orchestrator.py`: `classify(user_id, msg)` → `(tri, ext, mode, steps, decision)` theo 4
  tuyến (dùng chung cho ingest và eval); `ingest()` dùng nó; ưu tiên từ `urgency` cho việc không có hạn; trace bước
  "Decision" theo data-model; cập nhật `ai_selfcheck` báo tuyến.
- [x] T008 [US1] Cập nhật `tests/test_decision.py` theo API mới (giữ các ca: khoá không lọt log/phản hồi, chi phí 0 đầu ra,
  cắt độ dài đầu vào, `/api/health.filter_model`).

## Phase 3: User Story 3 — Cập nhật đúng việc cũ (P2)

- [x] T009 [P] [US3] `tests/test_routing.py`: "lùi deadline bài thực hành số 5" chọn `t<id>` của "Lab 5" → cập nhật hạn,
  không việc mới; `none` → việc mới; id không thuộc ứng viên (của người khác) → bỏ qua gợi ý; khác môn → không gộp; nhiều
  việc trích ra → không dùng gợi ý; > 30 việc mở → chỉ 30 ứng viên, cùng môn trước.
- [x] T010 [US3] `app/pipeline/decision.py`: `candidates(user_id, msg)` (R4) + câu `match_task`;
  `app/pipeline/planner.py`: `plan(..., hint_task_id=None)` áp dụng khi an toàn; orchestrator truyền gợi ý.

## Phase 4: User Story 4 — Sự kiện trong cùng lượt (P2)

- [x] T011 [P] [US4] `tests/test_routing.py`: câu `mandatory`/`major_fit` chỉ gửi khi đã khai ngành; mức cao → GPT viết
  lý do (nhắc ngành), mức vừa/thấp → câu mẫu nhắc ngành, không gọi GPT MajorFit; "bắt buộc" tin cậy cao → tự vào lịch;
  cùng sự kiện, ngành CNTT vs Nhật Bản học ra mức khác nhau; đổi ngành → reassess bằng lượt quyết định chỉ có câu
  `major_fit`.
- [x] T012 [US4] `app/pipeline/events.py`: `enrich_event(..., decision=None)`, `fit_from_decision()`, `fit_template()`;
  `assess_fit` / `reassess_pending` dùng lượt quyết định khi bật, giữ GPT → luật làm đường lùi.

## Phase 5: User Story 5 — Vai trò cột bảng lớp (P3)

- [x] T013 [P] [US5] `tests/test_sync.py`: bảng "STT | Môn | Nội dung | Deadline | Ghi chú" nhận đúng vai trò bằng lượt
  quyết định (0 lượt GPT); cột tên việc không chắc → SheetMapper GPT; lỗi → luật.
- [x] T014 [US5] `app/pipeline/decision.py`: `map_sheet_columns(header, samples, user_id)`; `app/sync/sheets.py`:
  `map_columns` thử quyết định trước.

## Phase 6: Polish

- [x] T015 `app/evaluation.py`: đi qua `orchestrator.classify`; báo `routes`, `gpt_calls`, `decision_calls`, `p50_ms`
  (trung vị, SC-004), và số lượt GPT trung bình riêng cho ca học vụ / ca nhiễu (để tính SC-003 cho hỗn hợp 30/70);
  `eval/cases.json`: thêm ca mơ hồ và ca "thay đổi thông báo cũ" có trường `existing` (việc có sẵn, eval tạo trước
  trong tài khoản tạm) và `expect.updates` (SC-005) — không sửa ca cũ; CLI in thêm.
- [x] T016 `app/static/app.js` + `app.css`: trace hiện nhãn tuyến + xác suất cho bước Decision; trang Cấu hình có 3 ô
  ngưỡng (chỉ admin).
- [x] T017 `docs/ARCHITECTURE.md` (sơ đồ 4 tuyến), `docs/SECURITY.md` (dữ liệu gửi AI quyết định, hợp lệ hoá đầu ra),
  `AGENTS.md`.
- [x] T018 Soát bảo mật diff 004 (vai trò `security-reviewer`); sửa mức Cao/Trung bình.
- [ ] T019 (đã: test/lint/eval, triển khai, số đo gốc trong quickstart; còn: eval khi có khoá) Chạy toàn bộ test/lint/eval; triển khai backend (Gemini vẫn tắt tới khi có khoá → luồng cũ); khi có khoá: eval
  so sánh có / không AI quyết định, ghi số vào quickstart.

## Dependencies

Phase 1 → US1/US2 (Phase 2) → US3, US4, US5 (độc lập nhau, có thể song song) → Polish. T019 phần "khi có khoá" chờ
người dùng điền `GEMINI_API_KEY`.
