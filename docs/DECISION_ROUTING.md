# Decision v1: lọc nhiễu và phân loại

Decision là tiền xử lý văn bản trước LLM chính. Một request hỏi hai câu: `relevant` (xác suất nội dung hữu ích) và
`category` (deadline/exam/class_change/event/admin/other). Không chọn tool, task trùng, urgency hoặc mức hợp ngành trong v1.
`other` không đồng nghĩa nhiễu. Tin hữu ích có thể không có task; mỗi task được LLM phân loại riêng.

## Cấu hình provider

Chép `.env.example` cho local hoặc `deploy/mstudent.env.example` cho dịch vụ. Điền khóa riêng trong môi trường server:

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=high
OPENROUTER_API_KEY=
MSTUDENT_DECISION_MODEL=google/gemini-decision-1
MSTUDENT_DECISION_ENABLED=1
MSTUDENT_OFFLINE=0
```

Không ghi giá trị khóa vào Git, lệnh chia sẻ, trace hay app. Google OAuth (`GOOGLE_*`) phục vụ lấy Gmail/Classroom,
không thay thế hai khóa model này. Sheets/Docs/Slides hiện đọc link công khai; không có Drive OAuth cho tài liệu riêng.

Decision dùng `POST https://openrouter.ai/api/alpha/decisions`, auth Bearer, payload `state`. Usage đọc
`input_tokens`, `output_tokens`, `cost`. Main agents và Assistant đều dùng custom Responses client; model lưu trong
settings admin có thể ghi đè `OPENAI_MODEL`. Mặc định dùng API OpenAI chính thức với model `gpt-6-luna` và truyền
`reasoning.effort=high` riêng, không gắn effort vào tên model. SDK tracing bên ngoài bị tắt. Khi tự cấu hình gateway
khác, phải kiểm tra lại model/effort và nhà cung cấp nhận dữ liệu.

## Bốn tuyến

| Tuyến | Điều kiện | LLM chính |
|---|---|---|
| `stop` | p(relevant) ≤ ngưỡng thấp | Không gọi |
| `direct` | p(relevant) ≥ ngưỡng cao | Extractor trích việc, nhận nhãn gợi ý khi đủ chắc |
| `review` | Nằm giữa hai ngưỡng | Review xét liên quan/phân loại và trích việc trong cùng một lượt |
| `fallback` | Decision tắt/thiếu khóa/lỗi/đáp án không hợp lệ | Triage → Extractor như đường cũ |

LLM chính lỗi hoặc hết ngân sách → bộ luật và ghi rõ `offline`. Tin đã xử lý trả cache, không gọi lại model.
Dữ liệu cấu trúc Classroom/ICS và dòng Sheets parser hiểu đi planner trực tiếp. Endpoint ICS thủ công vẫn đi pipeline
thông báo; không suy từ tên source để bỏ qua kiểm tra.

Ngưỡng trong cấu hình admin:

| Khóa | Mặc định |
|---|---:|
| `decision_low` | 0.10 |
| `decision_high` | 0.80 |
| `decision_category_conf` | 0.75 |

Giá trị phải hữu hạn, trong [0,1], low < high. Category confidence thấp không gọi thêm Triage: Extractor tự phân loại
trong lượt hiện có. Các số này là điểm khởi đầu, không phải bảo đảm recall; chỉnh trên tập phát triển và nghiệm thu
bằng tập riêng. Độ tin cậy của relevant không thay thế độ tin cậy category.

Thông báo, tài liệu, lịch sử chat và tool output là dữ liệu không tin cậy. Gate không có quyền cập nhật dữ liệu.
GUARD, sanitize, giới hạn đầu vào và kiểm tra `user_id` vẫn áp dụng. Nội dung hữu hạn không làm model miễn nhiễm với
prompt injection hoặc phân loại sai.

## Email và tài liệu

Body email và từng tài liệu có gate riêng. Không bỏ attachment hợp lệ chỉ vì body bị coi là nhiễu. Giữ giới hạn
định dạng/dung lượng và hash theo nội dung; lỗi đọc tệp/link được ghi vào trace `Documents`, không ghi là model kết luận
nhiễu. Đường này có thể tải thêm tài liệu của email bị loại; theo dõi chi phí fetch và gate riêng khi đo workload.

## Kiểm tra và đo hiệu quả

```bash
python -m pytest -q tests/test_decision.py tests/test_routing.py tests/test_main_provider.py tests/test_evaluation.py tests/test_docs.py
ruff check .
MSTUDENT_OFFLINE=1 python -m eval.run_eval
# Gọi API thật, cần khóa môi trường; không dùng dữ liệu riêng tư khi chưa được phép.
python -m eval.run_decision_eval --mode decision --split acceptance
```

Kiểm tra bốn tuyến, tin `other` hữu ích, nhiều loại task, ca mơ hồ, response lỗi, cache và attachment. Đo cùng dữ liệu,
model, trạng thái cache và hạ tầng. So riêng với đường không Decision và `dev` cũ đã có Decision; không dùng cải thiện
so với đường thứ nhất để khẳng định cải thiện so với đường thứ hai.

Báo số lượt Decision/main, token, tỷ lệ stop/review/fallback, p50/p95 và độ đúng deadline/task; không chỉ accuracy chung.
Phí Decision lấy từ provider khi có; phí main là ước tính theo `MSTUDENT_PRICE_IN_PER_M`/`MSTUDENT_PRICE_OUT_PER_M`,
không phải hóa đơn gateway. Giữ giá cấu hình để ngân sách hoạt động, nhưng xác nhận giá trước khi tuyên bố tiết kiệm USD.
Không hứa phần trăm tiết kiệm hoặc mọi request đều nhanh hơn: nhánh vẫn cần LLM chịu thêm thời gian Decision.

## Tắt gate và xử lý sự cố

- `MSTUDENT_DECISION_ENABLED=0`: quay về Triage → Extractor; vẫn dùng provider chính đã cấu hình.
- `MSTUDENT_OFFLINE=1`: không gọi cả hai provider; dùng bộ luật.
- Decision 401/429/5xx/timeout hoặc đáp án sai: trace `fallback`; kiểm tra credential/provider, không coi request là spam.
- LLM chính 401/schema/tool lỗi: giữ trace lỗi, xác nhận base URL/model/capability; không âm thầm gọi provider khác.
- Phát hiện bỏ sót deadline quan trọng: tắt gate, xem message/trace đã lưu, chỉnh prompt/ngưỡng trên tập phát triển rồi
  đánh giá lại. Tin đã cache không tự chạy lại khi đổi ngưỡng; replay phải có phạm vi rõ và giữ tránh tạo task trùng.

Không đổi OAuth hay reset nguồn dữ liệu khi chỉ tắt gate. Muốn đổi gateway phải kiểm tra provider riêng và cấu hình lại
khóa/base URL; không gộp thao tác đó vào rollback ngưỡng.
