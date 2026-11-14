# API Contracts: Tự động thu thập thông báo học tập

API cũ giữ nguyên. Chỉ liệt kê thứ mới hoặc đổi hành vi. Mọi endpoint (trừ `/api/hooks/gmail`) cần `current_user`.
Kiểu trả về đồng bộ vào `mobile/lib/types.ts` và `mobile/lib/api.ts` (constitution, mục Ràng buộc kỹ thuật).

## GET /api/sources

Danh sách nguồn của người gọi (không bao giờ có token / URL nội bộ).

```json
[
  {"id": 3, "kind": "gmail", "label": "sv@gmail.com", "enabled": true,
   "last_ok_at": "2026-11-13T09:02:11+00:00", "last_error": null},
  {"id": 7, "kind": "sheet", "label": "Deadline lớp K70", "enabled": true,
   "last_ok_at": "…", "last_error": "Bảng chưa chia sẻ công khai — chọn 'Bất kỳ ai có đường liên kết'"}
]
```

## POST /api/sources

Thêm nguồn dạng link. `Depends(current_user)`, giới hạn 20 lần / giờ.

- Body: `{"kind": "ics" | "sheet", "url": "<≤ 2000 ký tự>", "label": "<≤ 100, tuỳ chọn>"}`
- 201: một phần tử như trên. Lượt đồng bộ đầu chạy ngay (`next_run_at = now`).
- 400: URL không hợp lệ / không phải bảng tính / trỏ tới địa chỉ nội bộ. 409: đã có. 422: quá số nguồn cho phép.

## PATCH /api/sources/{id}

- Body: `{"enabled": bool}` → 200 phần tử. Nguồn của người khác / không có → 404.

## DELETE /api/sources/{id}

- 200 `{"ok": true}`; xoá kết nối và `source_items` (việc đã tạo giữ nguyên). Nguồn `gmail`/`classroom`: dùng
  `DELETE /api/google/disconnect` (đã có) → thu hồi token và xoá các kết nối Google.

## POST /api/sources/{id}/sync

"Đồng bộ ngay" (cho demo / khi người dùng muốn). `ai_limit` + 6 lần / 10 phút / nguồn → 202 `{"queued": true}`.

## POST /api/google/connect (đổi hành vi)

- Nhận scope Classroom nếu có trong `server_auth_code`. Lưu token như cũ, rồi tạo/bật kết nối `gmail` (nếu có
  `gmail.readonly`) và `classroom` (nếu có đủ 3 scope Classroom). Phản hồi thêm `"sources": [...]`.

## POST /api/push/register · DELETE /api/push/register

- Body: `{"token": "ExponentPushToken[…]", "platform": "android" | "ios", "notify": true}` (token ≤ 200, kiểm regex;
  `notify=false` khi người dùng tắt nhắc việc — app gọi lại khi đổi cài đặt).
- 400 khi URL lịch LMS không tải được / không phải lịch (FR-072) áp dụng cho `POST /api/sources` kind `ics`.
- 200 `{"ok": true}`. DELETE xoá token của chính người gọi (gọi khi đăng xuất).

## POST /api/hooks/gmail (công khai, xác thực bằng chữ ký Google)

- Gọi bởi Google Pub/Sub push. Header `Authorization: Bearer <OIDC JWT>`; server kiểm chữ ký bằng khoá công khai của
  Google, `iss` ∈ {`accounts.google.com`, `https://accounts.google.com`}, `aud` = `MSTUDENT_PUBLIC_URL + "/api/hooks/gmail"`,
  `email` = `MSTUDENT_PUBSUB_PUSH_SA`, `email_verified` = true. Sai → 403, không ghi log nội dung.
- Body Pub/Sub: `{"message": {"data": base64(JSON{"emailAddress","historyId"})}}` (≤ 8 KB).
- Hành vi: tìm kết nối `gmail` theo email → `next_run_at = now`. **Không** đọc thư hay gọi AI trong request; luôn 204
  (kể cả không tìm thấy email, để không lộ ai đang dùng). Giới hạn 120 lần / phút toàn hệ thống.

## Thông báo đẩy (server → Expo Push → Android)

```json
{"to": "ExponentPushToken[…]", "title": "MStudent: việc mới", "body": "Nộp báo cáo Lab 5 · hạn T6 21/11 23:59",
 "data": {"type": "tasks", "task_ids": [42]}, "channelId": "default"}
```

Chỉ gồm tên việc + hạn; không có nội dung tin gốc, không có email người gửi.

## Thay đổi dữ liệu trả về

- `Task.source` thêm `classroom`, `sheet`; `Task` thêm `sources: string[]`, `note: string | null`.
