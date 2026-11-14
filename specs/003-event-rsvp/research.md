# Research: Sự kiện của trường — Tham gia / Không, phù hợp với ngành

Ngày: 2026-11-14. Mỗi mục: **Quyết định** · Lý do · Đã cân nhắc.

## R1. Dữ liệu trường đại học (FR-004)

- **Quyết định**: Lấy từ Wikipedia tiếng Việt "Danh sách trường đại học, học viện và cao đẳng tại Việt Nam" (wikitext,
  CC BY-SA 4.0): mọi bảng phần cơ sở giáo dục đại học, đại học quốc gia/vùng, trực thuộc bộ/ngành, tỉnh, tư thục, quân
  đội/công an (bỏ trường nước ngoài, cao đẳng). Trường mẹ trong bảng có ô gộp ("Đại học Bách khoa Hà Nội (HUST)") được
  lấy riêng; đơn vị trực thuộc ghép tên trường mẹ. Kết quả: **306 trường, 239 có tên viết tắt** (HUST, NEU, UEH, FTU,
  PTIT, VNU-UET, VNU-VJU, VNUHCM-UIT…). File `backend/app/data/schools.json` (nguồn + ngày lấy).
- **Đã cân nhắc**: bảng mã trường tuyển sinh (luatminhkhue, hoatieu) — bị Cloudflare chặn và không có tên viết tắt;
  bộ dữ liệu Hugging Face `dict-universities` — dữ liệu tư vấn tuyển sinh dạng văn bản, không có cột viết tắt.

## R2. Dữ liệu ngành theo bậc

- **Quyết định**: Danh mục thống kê ngành đào tạo, Thông tư 09/2022/TT-BGDĐT, Phụ lục I (PDF Công báo 485+486): mã
  7xxxxxx = Đại học (**364**), 8xxxxxx = Thạc sĩ (**310**), 9xxxxxx = Tiến sĩ (**290**). Chữ rút từ PDF bị chèn dấu
  cách giữa âm tiết ("Giáo d ục") → ghép lại bằng luật + soát tay 5 lỗi còn sót (Khuyến, Ngoại, Quyền, Truyền, hoạch).
  File `backend/app/data/majors.json`. Lưu ý: Thông tư 74/2026 thay thế cho khoá tuyển sinh từ 01/01/2027 — cập nhật
  file khi có bản chính thức.
- **Ngành riêng của trường**: `backend/app/data/programs.json`, bắt đầu với VJU (trang vju.ac.vn, 2026-11-14): 9
  chương trình đại học, 9 thạc sĩ, 1 tiến sĩ. Trường có dữ liệu riêng → hiện danh sách của trường trước, kèm "Ngành khác
  (danh mục quốc gia)"; trường chưa có → danh mục quốc gia theo bậc.
- **Không** điền ngành của trường từ trí nhớ (dễ sai).
- Dữ liệu đặt ở máy chủ (`GET /api/catalog`, có ETag) → cập nhật không cần phát hành lại app; app tìm kiếm cục bộ
  (bỏ dấu, theo tên viết tắt, theo mã ngành).

## R3. Lời mời sự kiện dựa trên bảng `tasks`

- **Quyết định**: Không tạo bảng riêng; thêm cột cho `tasks`: `rsvp` (NULL | pending | going | declined), `event_end`,
  `event_url`, `register_url`, `register_deadline`, `mandatory`, `fit_level`, `fit_reason`, `fit_mode`, `form_meta`
  (JSON). Việc category `event` do pipeline tạo → `rsvp='pending'` (bắt buộc → `going`). Nhờ vậy dùng lại toàn bộ gộp
  nguồn, chống trùng, đồng bộ, xoá tài khoản.
- Danh sách việc / lịch / nhắc chỉ lấy `rsvp IS NULL OR rsvp='going'`; lời mời `pending` hiện ở khối riêng; `declined`
  ở mục "Đã bỏ qua"; pending quá giờ sự kiện → tự ẩn (lọc theo thời gian, không xoá).

## R4. Trích chi tiết sự kiện

- **Quyết định**: Khi Triage/Extractor ra việc category `event`, gọi thêm agent **EventDetails** (không tool, GUARD,
  schema bắt buộc mọi trường): bắt đầu/kết thúc, địa điểm, link sự kiện, link đăng ký, hạn đăng ký, đơn vị tổ chức, bắt
  buộc. Offline: luật — link http(s) trong tin, "bắt buộc|điểm danh|tính chuyên cần" → bắt buộc, link Google Forms →
  link đăng ký. Link chỉ nhận http(s), cắt 500 ký tự.

## R5. Phù hợp với ngành (Story 3)

- **Quyết định**: Agent **MajorFit** (không tool, GUARD) nhận nội dung sự kiện + trường, bậc, ngành của người dùng → mức
  `high|medium|low` + lý do ≤ 200 ký tự, nhắc tên ngành. Kết quả lưu trên việc (tính một lần; đổi ngành → tính lại các
  lời mời còn pending). Offline: luật so từ khoá ngành (bỏ dấu) với nội dung sự kiện + bảng nhóm ngành → lĩnh vực
  (CNTT, kinh tế, kỹ thuật, ngôn ngữ…), ghi `fit_mode='offline'`.

## R6. Đăng ký bằng Google Form đã điền sẵn

- **Quyết định**: Máy chủ đọc cấu trúc form công khai (`docs.google.com/forms/d/e/<id>/viewform`, `forms.gle/…`
  chuyển hướng) qua bộ tải an toàn (allowlist `docs.google.com`, `forms.gle`, ≤ 1 MB), lấy `FB_PUBLIC_LOAD_DATA_`:
  tiêu đề câu hỏi + `entry.<id>` của câu trả lời ngắn. Ghép tiêu đề với vai trò hồ sơ (họ tên, MSSV, email, lớp, trường,
  ngành, số điện thoại) bằng từ khoá. Lưu `form_meta = {form_id, fields:[{entry, role}]}` trên việc.
  **App tự dựng link điền sẵn** (`viewform?usp=pp_url&entry.N=…`) từ hồ sơ trên máy → máy chủ không dựng link chứa dữ
  liệu cá nhân; sinh viên tự bấm Gửi. Form bắt đăng nhập / không đọc được → nút mở link gốc.

## R7. Thông báo có nút Tham gia / Không

- **Quyết định**: `expo-notifications` category `event_invite` với 2 hành động ("Tham gia", "Không" — destructive).
  Thông báo đẩy từ máy chủ gửi kèm `categoryId` (Expo Push hỗ trợ); làm mới nền / thông báo cục bộ dùng cùng category.
  Bấm hành động → app mở (`opensAppToForeground`) và gọi `POST /api/tasks/{id}/rsvp`.
