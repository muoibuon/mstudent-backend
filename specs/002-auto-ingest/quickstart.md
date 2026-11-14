# Quickstart: kiểm chứng tự động thu thập

Chi tiết API ở [contracts/api.md](contracts/api.md); dữ liệu ở [data-model.md](data-model.md).

## 0. Điều kiện

- Production chạy bản mới (`sudo bash backend/deploy/install.sh`), `/api/health` → `"mode":"llm"`.
- `/etc/mstudent.env` có: `MSTUDENT_SYNC_ENABLED=1`, `MSTUDENT_PUBLIC_URL=https://<máy>.ts.net`, `GOOGLE_WEB_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GOOGLE_IOS_CLIENT_ID`; (tuỳ chọn, cho Gmail báo ngay) `MSTUDENT_PUBSUB_TOPIC`,
  `MSTUDENT_PUBSUB_PUSH_SA`.
- Google Cloud: Gmail API + Classroom API bật; scope Gmail + 3 scope Classroom; tài khoản thử nằm trong Test users.
- Test tự động: `cd backend && python -m pytest -q && ruff check .`; `cd mobile && npm test && npm run typecheck`.

## 1. Gmail tự động (Story 1, SC-002)

1. Trong app: Cài đặt → Kết nối Google (chọn Gmail). Cài đặt → Nguồn hiện "Gmail · đồng bộ lúc …".
2. **Đóng hẳn app.** Từ tài khoản khác gửi email: "Nộp báo cáo Lab 5 môn Mạng trước 23h59 thứ 6 tuần sau".
3. Kỳ vọng: ≤ 1 phút (có Pub/Sub) / ≤ 3 phút (không) → việc "Nộp báo cáo Lab 5" đúng hạn; Android hiện thông báo
   chạy nền "MStudent: việc mới". Web console → Agent trace có lượt `llm`.
4. Gửi lại đúng email đó (forward) → không có việc trùng (SC-003). Gửi email quảng cáo → không có việc.

## 2. Lịch LMS (Story 1)

`POST /api/sources {"kind":"ics","url":"<link xuất lịch Moodle>"}` → việc xuất hiện. Sửa hạn một bài trên Moodle → ≤ 1 giờ
(hoặc bấm "Đồng bộ ngay") việc cũ đổi hạn, không có bản thứ hai.

## 3. Google Classroom (Story 2, SC-004)

1. Tạo lớp thử trên classroom.google.com (tài khoản giáo viên khác), mời tài khoản sinh viên; giao bài "Bài tập tuần 10",
   hạn ngày mai 17:00.
2. Sinh viên bật Classroom trong app (cấp thêm quyền). ≤ 30 phút (hoặc "Đồng bộ ngay") → việc đúng tên, hạn 17:00 giờ VN,
   môn = tên lớp, nguồn Classroom.
3. Đổi hạn sang 20:00 → việc cập nhật. Nộp bài → việc thành "xong". Lớp không hoạt động > 14 ngày & tạo > 60 ngày → bỏ qua.

## 4. Bảng deadline của lớp (Story 3)

1. Google Sheets: cột "Môn | Nội dung | Hạn nộp", 3 dòng; Chia sẻ → "Bất kỳ ai có đường liên kết" → Người xem.
2. App: Nguồn → Thêm bảng lớp → dán link → 3 việc.
3. Thêm 1 dòng, sửa hạn 1 dòng, xoá 1 dòng → "Đồng bộ ngay" → +1 việc, 1 việc đổi hạn, 1 việc có ghi chú "không còn trong
   bảng". Đồng bộ lại không đổi gì → `llm_usage` không tăng (SC-005).
4. Dán link bảng riêng tư → thông báo hướng dẫn đổi quyền chia sẻ.

## 5. Gộp nguồn (FR-009)

Cùng bài "Lab 5 – INT3306" có trong email và bảng lớp → chỉ 1 việc, `sources = ["email","sheet"]`. Bài cùng tên khác mã môn
→ 2 việc.

## 6. iPhone (Story 4, bản ký miễn phí)

Cài đặt hiện "iPhone: việc mới được tải khi iOS cho chạy nền hoặc khi mở app". Mở app → việc mới có ngay; nhắc việc được đặt.

## 7. Zalo Android (Story 5, nếu làm)

Cài APK mới → Cài đặt → "Tự đọc tin Zalo" → cấp quyền → chọn nhóm thử. Gửi "Mai kiểm tra 15 phút chương 3" vào nhóm → việc
xuất hiện; tin ở nhóm không chọn → không có request nào tới server (xem log).

## 8. Chi phí và an toàn

- Admin → Số liệu: chi phí hôm nay tăng đúng theo số tin mới, không tăng khi đồng bộ rỗng.
- `curl -X POST https://<máy>.ts.net/api/hooks/gmail` không có chữ ký → 403.
- Xoá tài khoản → `sync_connections`, `source_items`, `push_tokens` của người đó = 0 dòng.
