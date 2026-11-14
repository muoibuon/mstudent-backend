# Data Model: 003-event-rsvp

## users (thêm cột, ALTER khi thiếu)

| Cột | Kiểu | Ghi chú |
|---|---|---|
| school_name | TEXT NOT NULL DEFAULT '' | ≤ 200 |
| school_abbr | TEXT NOT NULL DEFAULT '' | ≤ 40 |
| degree_level | TEXT NOT NULL DEFAULT '' | `dai_hoc` · `thac_si` · `tien_si` |
| major_code | TEXT NOT NULL DEFAULT '' | mã ngành (7 chữ số) hoặc mã chương trình của trường |
| major_name | TEXT NOT NULL DEFAULT '' | ≤ 200 |
| student_id, class_name, phone | TEXT NOT NULL DEFAULT '' | tuỳ chọn, ≤ 40 / 60 / 20; chỉ dùng điền sẵn form trên máy |
| profile_snooze_until | TEXT NULL | "Để sau" 7 ngày |

## tasks (thêm cột)

| Cột | Kiểu | Ghi chú |
|---|---|---|
| rsvp | TEXT NULL | NULL (việc thường) · `pending` · `going` · `declined` |
| event_end | TEXT NULL | ISO +07:00 |
| event_url, register_url | TEXT NULL | chỉ http(s), ≤ 500 |
| register_deadline | TEXT NULL | ISO +07:00 |
| mandatory | INTEGER NOT NULL DEFAULT 0 | |
| fit_level | TEXT NULL | `high` · `medium` · `low` |
| fit_reason | TEXT NULL | ≤ 200 |
| fit_mode | TEXT NULL | `llm` · `offline` |
| form_meta | TEXT NULL | JSON `{form_id, fields:[{entry, role}]}` |
| reg_task_id | INTEGER NULL | việc "Đăng ký …" tạo khi Tham gia |

Trạng thái: pipeline tạo việc `event` → `pending` (bắt buộc → `going`); `POST rsvp` going/declined đổi qua lại; khi
`going` và có `register_deadline` → tạo việc "Đăng ký …" (`reg_task_id`), khi `declined` → việc đó chuyển `done`.

## Dữ liệu tĩnh (`backend/app/data/`)

- `schools.json`: `{source, fetched, schools:[{name, abbr, en, group, place}]}`
- `majors.json`: `{source, updated, levels:{dai_hoc|thac_si|tien_si:[{code, name}]}}`
- `programs.json`: `{source, fetched, schools:{<abbr>:{dai_hoc:[{code,name}], thac_si:[…], tien_si:[…]}}}`
