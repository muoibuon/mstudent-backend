# Quickstart: kiểm tra 004-decision-routing

```bash
python -m pytest -q tests/test_routing.py tests/test_decision.py    # AI quyết định giả (MockTransport), không gọi mạng
python -m pytest -q && ruff check .
MSTUDENT_OFFLINE=1 python -m eval.run_eval                         # luồng luật không đổi
```

Có `GEMINI_API_KEY` + `OPENAI_API_KEY` (máy chủ):

1. `python -m eval.run_eval` → bảng điểm như cũ + `routes`, `gpt_calls`, `decision_calls`, `avg_ms`. So với lần chạy
   không có `GEMINI_API_KEY`: lọc/loại không giảm, `gpt_calls` giảm.
2. Web console → Agent trace: mỗi tin có bước "Decision" hiện tuyến (dừng / đi thẳng / xem lại / luồng cũ), xác suất.
3. Dán một tin quảng cáo → trace chỉ có bước Decision. Dán "Thầy cho lùi deadline bài thực hành số 5 sang thứ 2" khi đã
   có việc Lab 5 → việc cũ được cập nhật hạn.
4. Web console → Cấu hình agent: đổi `decision_low` → tin lưng chừng chuyển tuyến tương ứng.
