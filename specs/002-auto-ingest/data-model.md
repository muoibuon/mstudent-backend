# Data Model: Tự động thu thập thông báo học tập

SQLite, thêm vào `SCHEMA` trong `backend/app/db.py` (`CREATE TABLE IF NOT EXISTS`, không migration phá huỷ). Mọi bảng
có `user_id … REFERENCES users(id) ON DELETE CASCADE` để xoá tài khoản là xoá hết (FR-007).

## sync_connections — một nguồn của một sinh viên

| Cột | Kiểu | Ghi chú |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER NOT NULL FK users | |
| kind | TEXT NOT NULL | `gmail` · `classroom` · `ics` · `sheet` (sau: `msgraph`) |
| target | TEXT NOT NULL DEFAULT '' | URL `.ics` / URL bảng đã chuẩn hoá (`<id>#gid`); rỗng với gmail/classroom |
| label | TEXT NOT NULL DEFAULT '' | tên hiển thị (≤ 100 ký tự) |
| enabled | INTEGER NOT NULL DEFAULT 1 | |
| cursor | TEXT | Gmail `historyId`; `.ics` ETag; Classroom mốc thời gian |
| state | TEXT NOT NULL DEFAULT '{}' | JSON nhỏ: ánh xạ cột bảng + hash tiêu đề, hạn `watch` Gmail, thống kê lượt gần nhất |
| next_run_at | TEXT NOT NULL | UTC ISO |
| lease_until | TEXT | UTC ISO, chống chạy trùng |
| last_run_at, last_ok_at | TEXT | UTC ISO |
| last_error | TEXT | ≤ 300 ký tự, tiếng Việt, **không chứa token** |
| fail_count | INTEGER NOT NULL DEFAULT 0 | lùi dần khi lỗi |
| created_at | TEXT NOT NULL | |

- `UNIQUE(user_id, kind, target)`; index `(enabled, next_run_at)`.
- Giới hạn: tối đa 10 kết nối `sheet` + 5 `ics` mỗi người.
- Chu kỳ: gmail 120 s (push đặt `next_run_at=now`), classroom 600 s, sheet 1 800 s, ics 3 600 s.
- Trạng thái: `enabled=1` → chạy theo lịch; lỗi xác thực (Google 400 `invalid_grant`, 401) → `enabled=0`,
  `last_error="Cần kết nối lại …"` (FR-014); lỗi tạm thời → `fail_count+1`, lùi `min(2^n phút, 60 phút)`.
- Token Google vẫn ở `google_accounts` (mã hoá Fernet). Kết nối `gmail`/`classroom` tự tạo khi người dùng nối Google với
  scope tương ứng; ngắt Google → xoá các kết nối này.

## source_items — mục đã thấy ở nguồn (chống trùng, phát hiện thay đổi)

| Cột | Kiểu | Ghi chú |
|---|---|---|
| user_id | INTEGER NOT NULL FK users | |
| connection_id | INTEGER NOT NULL FK sync_connections ON DELETE CASCADE | |
| item_key | TEXT NOT NULL | Classroom `courseWorkId`; `.ics` `UID`; bảng: hash(môn+nội dung); `course:<id>` cho lớp |
| content_hash | TEXT NOT NULL | hash nội dung liên quan (hạn, tiêu đề, trạng thái nộp) |
| task_id | INTEGER NULL | việc đã tạo/gộp (không FK cứng: việc có thể bị người dùng xoá) |
| first_seen_at, last_seen_at | TEXT NOT NULL | |
| gone | INTEGER NOT NULL DEFAULT 0 | dòng bảng biến mất (FR-032) |

- FR-074: `task_id` trỏ tới việc không còn tồn tại → người dùng đã xoá → **không tạo lại** từ mục này; việc có
  `status='done'` → không mở lại, không đổi hạn.
- FR-075: lần đầu (`connection.last_ok_at IS NULL`) bỏ qua mục có hạn < now − 1 ngày (vẫn ghi `source_items` để lần sau
  không xét lại).
- PK `(connection_id, item_key)`. Email không cần bảng này: đã chống trùng bằng `messages(user_id, id='gmail-<id>')`.
- Mọi truy vấn lọc `user_id` (nguyên tắc I).

## push_tokens — thiết bị nhận thông báo (Android)

| Cột | Kiểu | Ghi chú |
|---|---|---|
| token | TEXT PK | `ExponentPushToken[…]`, ≤ 200 ký tự, regex kiểm định dạng |
| user_id | INTEGER NOT NULL FK users | |
| platform | TEXT NOT NULL | `android` · `ios` |
| notify | INTEGER NOT NULL DEFAULT 1 | 0 khi người dùng tắt nhắc việc trong app (FR-042) |
| created_at, last_ok_at | TEXT | |

- Một token chỉ thuộc một người: đăng ký lại bởi người khác → chuyển chủ (máy đổi tài khoản). Đăng xuất → xoá.

## tasks (đã có) — thay đổi

- `source`: thêm giá trị `classroom`, `sheet` (enum `Source` ở `models.py` và `mobile/lib/types.ts`).
- Cột mới `sources TEXT NOT NULL DEFAULT '[]'`: danh sách nguồn đã góp vào việc (gộp FR-009), ví dụ
  `["email","classroom"]`. Thêm bằng `ALTER TABLE … ADD COLUMN` có kiểm tra cột tồn tại (DB production đang có dữ liệu).
- Cột mới `note TEXT NULL` (≤ 200): ví dụ "Không còn trong bảng lớp (13/11)".

## messages (đã có)

- Thêm id dạng `classroom-ann-<id>` cho thông báo lớp Classroom (chống trùng như Gmail).

## Quan hệ

```
users 1─* sync_connections 1─* source_items *─0..1 tasks
users 1─1 google_accounts (token)        users 1─* push_tokens
```
