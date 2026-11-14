# Data Model: 004-decision-routing

Không đổi schema CSDL, không đổi API mà app dùng.

## DecisionResult (trong bộ nhớ, `pipeline/decision.py`)

| Trường | Kiểu | Ghi chú |
|---|---|---|
| relevant | float 0–1 | xác suất "cần chú ý" |
| relevant_conf | float 0–1 | |
| category | Category | + `category_conf` |
| has_date, multi_task, is_update | float 0–1 | |
| urgency | float 0–2 \| None | điểm liên tục |
| match_task_id | int \| None | chỉ id nằm trong tập ứng viên đã gửi; + `match_conf` |
| mandatory | float \| None | + `mandatory_conf`; None nếu không hỏi |
| major_fit | float 0–2 \| None | None nếu chưa khai ngành |
| input_tokens, ms | int | ghi vào `llm_usage` (agent `Decision`) |

## Route

`stop | direct | review | fallback` + `reason` (chuỗi ngắn tiếng Việt, vd. "bỏ qua (8%, tin cậy 92%)").

## Trace step (JSON trong bảng `traces`, không đổi cột)

```json
{"agent": "Decision", "kind": "gemini", "ms": 180,
 "output": {"route": "direct", "reason": "cần chú ý (97%)", "relevant": 0.97, "category": "deadline",
            "category_conf": 0.9, "urgency": 1.2, "match_task": "t42", "major_fit": null}}
```

## Settings (bảng `settings`, qua `agent_config`)

| Khoá | Mặc định | Ràng buộc |
|---|---|---|
| decision_low | 0.15 | [0, 1], ≤ decision_high |
| decision_high | 0.60 | [0, 1] |
| decision_min_conf | 0.80 | [0, 1] |
