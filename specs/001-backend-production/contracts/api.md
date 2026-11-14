# API Contracts: Backend production

API cũ giữ nguyên. Phần dưới chỉ liệt kê thứ mới hoặc thay đổi hành vi.

## GET /api/admin/stats (mới)

- Auth: `Depends(admin_user)`. Không đăng nhập thì 401; không phải admin thì 403.
- 200:

```json
{
  "generated_at": "2026-11-14T09:00:00+07:00",
  "users_total": 57,
  "users_active_7d": 41,
  "messages_total": 812,
  "messages_by_mode": {"llm": 640, "offline": 120, "cache": 52},
  "tasks_total": 433,
  "llm_cost_today_usd": 0.42,
  "llm_budget_usd": 5.0,
  "llm_budget_exhausted": false,
  "llm_cost_per_active_user_usd": 0.03,
  "median_latency_ms": 2100
}
```

- Không chứa email, tên, nội dung hay id người dùng.

## GET /privacy (mới, công khai)

- Trả về `static/privacy.html` (text/html, tiếng Việt). Không đọc CSDL.

## Thay đổi hành vi (không đổi schema)

| Endpoint | Thay đổi |
|---|---|
| `POST /api/ingest`, Gmail sync, digest, chat trợ lý | Khi chạm trần chi phí hoặc LLM quá thời hạn chờ thì trả kết quả của bộ luật với `mode="offline"` (trường đã có sẵn). |
| Mọi endpoint có giới hạn tần suất | Bộ đếm còn sau khi khởi động lại. Vẫn trả 429 và `Retry-After` như cũ. |
| `GET /api/health` | Giữ nguyên schema. `mode` vẫn phản ánh `llm_enabled()`. |
| Khởi động khi `MSTUDENT_ENV=prod` | Thiếu `MSTUDENT_SECRET_KEY` / `OPENAI_API_KEY` / `MSTUDENT_ADMIN_EMAILS` thì tiến trình thoát, log liệt kê tên biến. |
