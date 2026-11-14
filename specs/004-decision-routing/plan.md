# Implementation Plan: AI quyết định điều phối toàn bộ luồng xử lý thông báo

**Branch**: `004-decision-routing` | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Summary

Mỗi thông báo được Gemini Decision 1 trả lời một lần tối đa 9 câu dạng chọn đáp án (liên quan, loại, có hạn, nhiều việc,
cập nhật, mức gấp, trùng việc cũ nào, bắt buộc, hợp ngành). Orchestrator dùng kết quả để chọn tuyến **dừng / đi thẳng /
xem lại / luồng cũ**; đi thẳng thì bỏ GPT Triage, Extractor nhận ngữ cảnh sẵn; planner cập nhật đúng việc cũ được chọn;
sự kiện lấy "bắt buộc" và mức hợp ngành từ cùng lượt (GPT chỉ viết lý do cho mức cao); bảng lớp nhận vai trò cột bằng
lượt quyết định. Mọi lỗi rơi về luồng hiện tại. Chi tiết quyết định: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12, FastAPI, httpx, openai-agents · **Storage**: SQLite — không đổi schema; ngưỡng trong
bảng `settings` · **Testing**: pytest, Decisions API giả bằng `httpx.MockTransport`, Runner giả cho GPT ·
**Target**: máy chủ Azure B2ls_v2 (2 vCPU, 4 GB) · **Performance**: tin nhiễu < 1 s; tin rõ ràng nhanh hơn ≥ 30% ·
**Constraints**: chạy và test được khi chưa có `GEMINI_API_KEY`; không đổi API của app; không gửi MSSV/SĐT/email cho AI
quyết định · **Scale**: ≤ 30 ứng viên trùng việc, ≤ 30 cột bảng lớp mỗi lượt

## Constitution Check (v1.1.0)

| Nguyên tắc | Đánh giá |
|---|---|
| I. Bảo mật & cách ly | ✅ Không endpoint mới. Nội dung gửi đi qua `render()` + câu nhắc kiểu GUARD; đầu ra (không phải chữ) hợp lệ hoá chặt thay cho `sanitize()`; id việc từ AI chỉ nhận nếu thuộc tập ứng viên của chính người dùng; khoá chỉ ở máy chủ; dữ liệu cá nhân tối thiểu (R7) |
| II. Test | ✅ `tests/test_routing.py` mới: 4 tuyến, ngưỡng, ứng viên chéo người dùng, sự kiện, lỗi → luồng cũ; bảng lớp trong `tests/test_sync.py`; test cũ giữ xanh |
| III. AI minh bạch | ✅ Kết quả AI quyết định ghi `mode="llm"` + bước trace "Decision"; luật vẫn `offline`; prompt mới (nếu có) trong `DEFAULTS`; eval chỉ thêm ca, không sửa ca cũ |
| Ràng buộc kỹ thuật | ✅ Không đổi API → không phải sửa `types.ts`/`api.ts` ở hai repo app |

**PASS**, không ngoại lệ.

## Project Structure

```text
app/pipeline/decision.py      # VIẾT LẠI: dựng câu hỏi theo ngữ cảnh, decide(), validate, route(), map_sheet_columns()
app/pipeline/orchestrator.py  # điều phối theo tuyến; truyền DecisionResult cho Extractor / planner / events
app/pipeline/llm_agents.py    # llm_triage chỉ còn GPT; llm_extract nhận dòng ngữ cảnh hệ thống
app/pipeline/planner.py       # plan(..., hint_task_id) cập nhật việc được chọn khi an toàn
app/pipeline/events.py        # enrich_event / assess_fit / reassess_pending dùng câu trả lời quyết định; câu mẫu lý do
app/sync/sheets.py            # map_columns: quyết định → GPT → luật
app/agent_config.py           # khoá ngưỡng decision_* (kẹp giá trị)
app/evaluation.py             # đi qua hàm điều phối; routes / gpt_calls / decision_calls / avg_ms
app/config.py                 # bỏ decision_min_relevant
app/static/app.js · app.css   # trace: nhãn tuyến + xác suất cho bước Decision; ô sửa ngưỡng trong Cấu hình
tests/test_routing.py         # MỚI
tests/test_decision.py        # cập nhật theo API mới
tests/test_sync.py            # thêm ca vai trò cột bằng lượt quyết định
eval/cases.json               # thêm ca mơ hồ + cập nhật việc cũ
docs/ARCHITECTURE.md · docs/SECURITY.md · AGENTS.md
```

## Phân pha

1. **Nền (US1 + US2)**: `decision.py` (câu hỏi cơ bản, validate, route), orchestrator 4 tuyến, Extractor nhận ngữ cảnh,
   ngưỡng trong `agent_config`, trace. ~1,5 h
2. **Trùng việc (US3)**: ứng viên, `match_task`, `planner.plan(hint_task_id)`. ~1 h
3. **Sự kiện (US4)**: `mandatory`, `major_fit`, câu mẫu lý do, reassess. ~1 h
4. **Bảng lớp (US5)**: `col_<i>`. ~0,5 h
5. **Đo + hoàn thiện**: eval mới, web console, tài liệu, soát bảo mật, triển khai (Gemini vẫn tắt tới khi có khoá). ~1 h

## Rủi ro

- Chưa có khoá Gemini → không đo được chất lượng thật; mọi thứ kiểm bằng AI giả, triển khai an toàn vì không có khoá thì
  chạy luồng cũ. Khi có khoá: chạy eval so sánh trước khi coi là xong (SC-001…SC-004).
- Ngưỡng mặc định có thể chưa tối ưu → chỉnh trên web console, không cần triển khai lại.
