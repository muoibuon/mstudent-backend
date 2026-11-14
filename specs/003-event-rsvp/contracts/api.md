# API: 003-event-rsvp (mọi endpoint cần `current_user`; lời gọi AI dùng `ai_limit`)

- `GET /api/catalog` → `{schools, majors, programs, version}`; header `ETag`, `If-None-Match` → 304.
- `GET /api/profile` → `{school_name, school_abbr, degree_level, major_code, major_name, student_id, class_name, phone,
  needs_profile}`; `needs_profile` = chưa có trường/ngành và không trong thời gian "Để sau".
- `PUT /api/profile` (giới hạn độ dài từng trường, `degree_level` ∈ 3 giá trị) → hồ sơ; đổi ngành → tính lại mức phù hợp
  các lời mời `pending` (nền).
- `POST /api/profile/snooze` → "Để sau" 7 ngày.
- `GET /api/tasks?status=open` (đổi): mặc định loại `pending`/`declined`; `GET /api/events?state=pending|going|declined`
  → lời mời (Task + các trường sự kiện).
- `POST /api/tasks/{id}/rsvp` body `{"going": bool}` → Task; không phải sự kiện → 400; của người khác → 404; sự kiện bắt
  buộc + `going=false` → 409.
- `Task` (đổi): thêm `rsvp, event_end, event_url, register_url, register_deadline, mandatory, fit_level, fit_reason,
  fit_mode, form_meta`.
- Thông báo đẩy lời mời: `{"categoryId": "event_invite", "data": {"type": "invite", "task_id": N}, "title": "Sự kiện mới:
  …", "body": "<mức phù hợp> · <giờ> · Tham gia không?"}`.
