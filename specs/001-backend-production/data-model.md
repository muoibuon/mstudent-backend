# Data Model: Backend production

Hai bảng mới trong SQLite (thêm vào `SCHEMA` trong `db.py` với `CREATE TABLE IF NOT EXISTS`). Production bắt
đầu từ kho trống, không cần chuyển đổi dữ liệu.

## llm_usage

Mỗi lượt gọi LLM thành công ghi một dòng.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER NULL | FK users(id) ON DELETE CASCADE; NULL cho lượt gọi hệ thống (eval, ai-check) — vẫn tính vào trần |
| day | TEXT NOT NULL | `YYYY-MM-DD` theo `config.now()` (+07:00) |
| agent | TEXT NOT NULL | `Triage` / `Extractor` / `Digest` / `Assistant` |
| input_tokens | INTEGER NOT NULL | |
| output_tokens | INTEGER NOT NULL | |
| cost_usd | REAL NOT NULL | tính lúc ghi theo đơn giá cấu hình |
| latency_ms | INTEGER NOT NULL | dùng cho số liệu thời gian xử lý |
| created_at | TEXT NOT NULL | `config.utcnow()` ISO |

Index: `(day)`, `(user_id, day)`.

Quy tắc: không lưu nội dung prompt hay câu trả lời. Xoá tài khoản thì xoá theo CASCADE.

## rate_counters

| Cột | Kiểu | Ghi chú |
|---|---|---|
| key | TEXT NOT NULL | ví dụ `ai:m:42`, `login:ip:1.2.3.4` |
| window_start | INTEGER NOT NULL | epoch giây (UTC) làm tròn theo `window_s` |
| count | INTEGER NOT NULL | |

PK `(key, window_start)`. Dọn các dòng có `window_start` cũ hơn 2 ngày, theo cơ hội (1/200 lần ghi).

Không có `user_id` riêng vì key đã chứa nó. Bảng không bao giờ trả ra API.

## budget_alerts

| Cột | Kiểu | Ghi chú |
|---|---|---|
| day | TEXT NOT NULL | `YYYY-MM-DD` (+07:00) |
| level | INTEGER NOT NULL | 80 hoặc 100 |

PK `(day, level)`. Đánh dấu đã gửi cảnh báo chi phí để mỗi mức chỉ báo một lần mỗi ngày. Dùng bảng riêng thay
vì `settings`, vì `settings` là cấu hình agent và bị xoá sạch khi admin bấm "khôi phục mặc định".

Bộ đếm `rate_counters` dùng cửa sổ trượt xấp xỉ (cửa sổ trước × phần chồng lấn + cửa sổ hiện tại), không phải
cửa sổ cố định thuần, để không lách được giới hạn ở ranh giới cửa sổ.

## Số liệu tổng hợp (không lưu, tính khi gọi)

| Trường | Nguồn |
|---|---|
| users_total | `COUNT(*) FROM users` |
| users_active_7d | người dùng có `messages` hoặc `llm_usage` trong 7 ngày |
| messages_total | `COUNT(*) FROM messages` |
| messages_by_mode | `traces.mode` gom theo `llm` / `offline` / `cache` |
| tasks_total | `COUNT(*) FROM tasks` |
| llm_cost_today_usd, llm_budget_usd | `SUM(cost_usd) WHERE day=today`, cấu hình |
| llm_cost_per_active_user_usd | chi phí 7 ngày / users_active_7d |
| median_latency_ms | trung vị `latency_ms` 7 ngày |
