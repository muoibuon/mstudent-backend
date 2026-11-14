# Research: Tự động thu thập thông báo học tập

Mỗi mục: **Quyết định** · Lý do · Phương án đã cân nhắc. Ngày: 2026-11-13.

## R1. Bộ lập lịch đồng bộ

- **Quyết định**: Vòng lặp asyncio chạy trong chính tiến trình FastAPI (khởi động trong `lifespan`), mỗi 15 giây quét bảng
  `sync_connections` tìm kết nối có `next_run_at <= now`, chạy tối đa 4 kết nối song song (semaphore), mỗi lượt có thời
  hạn 90 giây. Lịch kế tiếp = chu kỳ của loại nguồn + độ lệch ngẫu nhiên ±10% (dàn đều tải). Lỗi liên tiếp → lùi dần
  (2, 4, 8… phút, tối đa 1 giờ). Tắt được bằng `MSTUDENT_SYNC_ENABLED=0` (test, máy dev).
- **Lý do**: Dịch vụ chạy `--workers 1` nên không lo chạy trùng; không thêm hạ tầng (Celery/Redis); dùng chung DB, budget,
  pipeline. Trạng thái lịch nằm trong DB nên khởi động lại không mất.
- **Đã cân nhắc**: systemd timer gọi CLI mỗi phút (thô, không phản ứng nhanh với Gmail push); APScheduler (thêm phụ thuộc,
  không lợi gì hơn vòng lặp 40 dòng); Celery + Redis (quá nặng cho 1 GiB RAM).
- **Phòng chạy trùng**: cột `lease_until` — lấy kết nối bằng `UPDATE … SET lease_until=? WHERE id=? AND (lease_until IS NULL
  OR lease_until < now)`; chỉ chạy khi `rowcount == 1`.

## R2. Gmail: đồng bộ tăng dần

- **Quyết định**: Lần đầu dùng `messages.list` (`newer_than:7d in:inbox -category:promotions -category:social`, đã có) và lưu
  `historyId` từ `users.getProfile`. Các lần sau dùng `users.history.list(startHistoryId, historyTypes=messageAdded,
  labelId=INBOX)`: không có thư mới → 1 lời gọi rẻ, **0 lượt AI**. `historyId` hết hạn (404) → quay lại `messages.list`
  1 ngày gần nhất. Chu kỳ dự phòng: 120 giây (`MSTUDENT_GMAIL_POLL_S`).
- **Lý do**: `history.list` tốn 2 đơn vị quota, rẻ hơn list + get; chống trùng vẫn giữ bằng `messages(user_id, id)`.
- **Quota**: 100 người × 30 lượt/giờ = 3 000 lời gọi/giờ, rất xa giới hạn dự án Gmail API.

## R3. Gmail: báo ngay (push)

- **Quyết định**: `users.watch` gửi thông báo vào topic Google Cloud Pub/Sub; subscription kiểu **push** tới
  `https://<máy>.ts.net/api/hooks/gmail` có **xác thực OIDC** (Google ký JWT). Endpoint kiểm chữ ký JWT (khoá công khai của
  Google, đã có `verify` cho ID token), `aud` = URL endpoint, `email` = service account cấu hình trong
  `MSTUDENT_PUBSUB_PUSH_SA`. Payload chỉ có `emailAddress` + `historyId` → tìm kết nối Gmail theo email → đặt
  `next_run_at = now`; scheduler chạy trong ≤ 15 giây. `watch` hết hạn sau 7 ngày → gia hạn mỗi 24 giờ trong lượt đồng bộ.
- **Lý do**: Độ trễ ~10–30 giây cho demo; endpoint không bao giờ tin nội dung payload (chỉ dùng làm "chuông báo"), dữ liệu
  thật vẫn lấy qua `history.list` bằng token của người dùng.
- **Cần cấu hình (người dùng)**: bật Pub/Sub API, tạo topic, cấp quyền `Pub/Sub Publisher` cho
  `gmail-api-push@system.gserviceaccount.com`, tạo push subscription có OIDC (service account riêng). Thiếu cấu hình →
  bỏ qua `watch`, chạy bằng chu kỳ 2 phút (FR-010 vẫn đạt ≤ 3 phút).
- **Đã cân nhắc**: chỉ poll 30 giây (lãng phí, vẫn chậm hơn push); IMAP IDLE (cần mật khẩu ứng dụng, giữ kết nối dài).

## R4. Google Classroom

- **Quyết định**: Thêm scope chỉ đọc `classroom.courses.readonly`, `classroom.coursework.me.readonly`,
  `classroom.announcements.readonly` vào lần đăng nhập Google (xin thêm quyền tăng dần; người đã nối Gmail được hỏi thêm khi
  bật Classroom). Mỗi 10 phút:
  1. `courses.list(studentId=me, courseStates=ACTIVE)`.
  2. Lọc theo FR-024: giữ lớp có `creationTime` trong 60 ngày **hoặc** có bài tập / thông báo `updateTime` trong 14 ngày.
     API không trả "ngày tham gia" của học sinh → dùng lần đầu MStudent thấy lớp (`source_items.first_seen_at`) làm xấp xỉ.
  3. `courseWork.list` → mỗi bài có hạn thành việc **không qua AI** (`dueDate` + `dueTime` là UTC → đổi sang +07:00; thiếu
     `dueTime` → 23:59 giờ VN). Category = `deadline` (hoặc `exam` nếu `workType`/tiêu đề chứa "kiểm tra", "thi", "quiz").
  4. `courseWork.studentSubmissions.list(courseWorkId="-", userId=me)` → `TURNED_IN`/`RETURNED` → đánh dấu việc xong.
  5. `announcements.list` (mục mới) → `orchestrator.ingest` như tin nhắn (qua AI, có budget).
- **Lý do**: dữ liệu có cấu trúc → đúng 100% hạn, 0 chi phí AI; dùng lại OAuth sẵn có.
- **Rủi ro**: tài khoản Workspace của trường có thể chặn ứng dụng bên ngoài → báo lỗi rõ (spec Story 2 kịch bản 5).

## R5. Bảng deadline của lớp (Google Sheets công khai)

- **Quyết định**: Nhận link `https://docs.google.com/spreadsheets/d/<id>/…(#gid=<gid>)`, tải
  `https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>`. Chỉ theo chuyển hướng tới
  `docs.google.com` và `*.googleusercontent.com` (tối đa 3 lần), giới hạn 1 MB và 2 000 dòng, timeout 15 giây; kiểm IP công
  khai như `.ics` (chống SSRF). Bảng không công khai → Google trả trang đăng nhập (HTML) → báo "đổi quyền chia sẻ".
- **Hiểu cột**: lần đầu (và khi dòng tiêu đề đổi) gửi **dòng tiêu đề + 3 dòng mẫu** cho một agent "SheetMapper" (không có
  tool, schema bắt buộc, nối GUARD) → trả vai trò từng cột: `course | title | due_date | due_time | note | ignore`. Lưu ánh
  xạ cùng hash tiêu đề. Nếu AI bị tắt/hết hạn mức → đoán theo từ khoá tiêu đề cột ("môn", "mã hp", "nội dung", "hạn",
  "deadline", "ngày", "giờ") bằng luật.
- **Mỗi dòng**: khoá dòng = hash(chuẩn hoá(môn + nội dung)); hash nội dung = hash(cả dòng). Dòng mới → tạo việc; hash đổi
  → cập nhật việc (qua planner, giữ `updated_from`); dòng biến mất → thêm ghi chú "không còn trong bảng", không xoá.
  Ngày/giờ phân tích bằng luật (dd/mm/yyyy, dd/mm, d/m, hh:mm, hhhmm). Không phân tích được → gửi dòng cho Extractor AI.
  Chu kỳ 30 phút (FR-034 ≤ 1 giờ).
- **Đã cân nhắc**: Sheets API với `spreadsheets.readonly` (đọc mọi bảng của người dùng, quá rộng); Google Picker + `drive.file`
  (đúng hướng lâu dài, làm sau demo).

## R6. Lịch LMS (.ics) tự động

- **Quyết định**: Lưu URL thành kết nối loại `ics`; tải lại mỗi 60 phút bằng `lms_ics.fetch` hiện có (có kiểm SSRF). Mỗi
  sự kiện có `UID` → khoá trong `source_items`; hash(`DTSTART`/`DUE` + `SUMMARY`) đổi → cập nhật hạn. Sự kiện `.ics` là dữ
  liệu có cấu trúc: tạo việc trực tiếp, chỉ gọi AI khi tiêu đề cần tách môn/loại (giữ hành vi hiện tại của
  `/api/ingest/lms-ics`). Hỗ trợ ETag/`If-Modified-Since` để không tải lại khi không đổi.

## R7. Gộp việc giữa các nguồn (FR-009)

- **Quyết định**: Thay `planner._similar` bằng `planner.match_existing()`:
  1. Chuẩn hoá môn: mã học phần (regex `[A-Z]{2,5}\s?\d{3,4}[A-Z]?`) hoặc tên môn bỏ dấu, viết thường. Hai việc đều có môn
     mà khác nhau → **không bao giờ gộp**.
  2. Cùng môn (hoặc một bên thiếu môn) → điểm = độ giống tiêu đề (bỏ dấu) + thưởng nếu cùng ngày hạn; ngưỡng như hiện tại
     (cùng ngày & ≥ 0,45, hoặc ≥ 0,8). Có mã học phần trùng khớp → hạ ngưỡng tiêu đề xuống 0,35.
  3. Gộp → ghi thêm nguồn vào `tasks.sources`; hạn lấy theo nguồn có cấu trúc (Classroom, .ics > bảng lớp > email/Zalo).
- **Lý do**: xác định được, không tốn AI, có test; câu trả lời clarify "so mã/tên môn trước rồi xét" khớp trực tiếp.
- **Đã cân nhắc**: hỏi AI để quyết định gộp (tốn chi phí, khó test; để dành cho ca "không chắc" sau demo).

## R8. Thông báo khi có việc mới (FR-040, FR-041)

- **Quyết định**:
  - **Android**: Expo Push. App lấy `ExpoPushToken` (`expo-notifications`, cần `projectId` của EAS và khoá FCM v1 tải lên
    EAS), gửi về `POST /api/push/register`. Server sau mỗi lượt đồng bộ có việc mới / dời hạn → gửi
    `https://exp.host/--/api/v2/push/send` (httpx, nền, nuốt lỗi), gom tối đa 1 thông báo / người / lượt đồng bộ
    ("Việc mới: … · hạn …", nhiều việc thì "3 việc mới, sớm nhất: …"). Phản hồi `DeviceNotRegistered` → xoá token.
  - **iPhone bản ký miễn phí**: không có APNs → `getExpoPushTokenAsync` lỗi → app bỏ qua đăng ký. Dùng `expo-background-task`
    (iOS BGTaskScheduler; hệ điều hành quyết định thời điểm, thường ≥ 15 phút, có thể vài giờ): tải `/api/tasks`, so với
    bản lưu, đặt nhắc việc cục bộ cho việc mới. Cài đặt hiện dòng giải thích giới hạn.
- **Quyền riêng tư**: nội dung thông báo đi qua Expo/FCM → chỉ gửi tên việc + hạn, không gửi nội dung tin gốc.

## R9. Zalo trên Android (Story 5)

- **Quyết định**: Expo module cục bộ `mobile/modules/zalo-listener` (Kotlin, Expo Modules API) chứa
  `NotificationListenerService`: chỉ nhận thông báo của gói `com.zing.zalo`; tiêu đề thông báo = tên nhóm; chỉ giữ nhóm nằm
  trong danh sách người dùng chọn (lưu `SharedPreferences`). Tin hợp lệ được xếp hàng trong bộ nhớ máy và gửi lên
  `POST /api/ingest` (source `zalo`) bằng `WorkManager` (chạy cả khi app đóng; access token làm mới qua refresh token đã lưu
  trong Keystore). Config plugin thêm `<service>` + quyền `BIND_NOTIFICATION_LISTENER_SERVICE` vào manifest.
- **Giới hạn**: chỉ bắt tin khi Zalo hiện thông báo (nhóm bị tắt thông báo → không có); nội dung có thể bị Zalo rút gọn; chỉ
  cài ngoài cửa hàng (chính sách Google Play hạn chế quyền này); không có trên iPhone.
- **Rủi ro**: cao (native code, build qua EAS/Android Studio do thành viên khác làm) → làm sau P1–P4.

## R10. Microsoft 365 (Story 6, sau demo)

- Microsoft Graph: `Mail.Read`, `EduAssignments.ReadBasic` (ủy quyền); tenant trường thường chặn người dùng tự đồng ý ứng
  dụng bên ngoài → cần CNTT trường duyệt. Trước mắt: hướng dẫn quy tắc chuyển tiếp Outlook → Gmail (FR-012). Không thiết
  kế chi tiết trong đợt này.

## R11. Tải và chi phí

- 100 người đã nối Gmail: ~50 lời gọi Gmail/phút (phần lớn `history.list` rỗng), 0 AI khi không có thư mới. Classroom: 100 ×
  (1 + số lớp × 3) lời gọi / 10 phút. Bảng lớp: 1 tải CSV / 30 phút / bảng, 0 AI khi không đổi. Bộ nhớ: vòng lặp + 4 tác vụ
  song song, < 50 MB thêm. Trần chi phí riêng 0,5 USD/người/ngày và chung 5 USD/ngày áp dụng cho mọi lượt AI tự động
  (`user_id` của chủ kết nối).

## R12. Tệp đính kèm và tài liệu trong email (US7)

- **Quyết định**: Dùng quyền `gmail.readonly` sẵn có (`messages.attachments.get`). Email được xử lý trước như cũ;
  chỉ khi Triage kết luận liên quan mới tải tệp (FR-080). PDF: `pypdf` (thuần Python); DOCX/XLSX: đọc XML trong zip
  bằng thư viện chuẩn (giới hạn số mục và dung lượng giải nén chống zip bomb); CSV/TXT: giải mã trực tiếp. Link Google
  Docs/Sheets/Slides công khai: tải bản xuất `txt`/`csv` qua cùng bộ tải an toàn của nguồn Bảng lớp (allowlist host).
- **Thu gọn**: giữ 1 500 ký tự đầu + các dòng có ngày/giờ/từ khoá (hạn, nộp, thi, kiểm tra, deadline, lịch), cắt
  6 000 ký tự. Tài liệu thành một "thông báo" mới (`doc-<sha256 nội dung>`) đi qua `orchestrator.ingest` → chống trùng
  theo nội dung (FR-084) và dùng sẵn GUARD/sanitize/budget. Tóm tắt 2–3 câu: agent "DocSummarizer" (không tool) chỉ
  chạy khi tài liệu tạo/cập nhật việc; offline → câu đầu của tài liệu.
- **Đã cân nhắc**: quyền `drive.readonly` để đọc tài liệu riêng tư (scope bị hạn chế, cần xác minh) — để sau; OCR cho
  PDF scan (AI đọc ảnh, tốn chi phí) — để sau.
