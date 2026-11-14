# Feature Specification: Sự kiện của trường — phản hồi Tham gia / Không, phù hợp với ngành

**Feature Branch**: `003-event-rsvp`

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Sinh viên thường có lịch event/seminar do trường tổ chức → khi đọc được thông báo này hãy
hiện thông báo cho người dùng và cho họ 2 lựa chọn Tham gia / Không tham gia dạng nút được thiết kế → nếu tham gia thì
tạo nút truy cập link và nhúng link điền form rồi lên lịch cho người dùng, nếu không thì bỏ qua; tạo thêm tính năng
trường và ngành hiện sau khi người dùng đăng nhập → suy xét về ngành xem sự kiện đó có ích gì cho ngành học của người
dùng." (Gộp đề xuất trước đó: mở Google Form đã điền sẵn để sinh viên tự gửi.)

## Bối cảnh

Hiện MStudent coi sự kiện/seminar như một "việc" bình thường: tự xếp vào danh sách, không hỏi sinh viên có muốn đi
không, không biết sự kiện có đáng đi với ngành của họ không, và sinh viên vẫn phải tự tìm link đăng ký. Kết quả: danh
sách việc lẫn nhiều sự kiện không định đi, còn sự kiện đáng đi thì lỡ hạn đăng ký.

Mục tiêu: **sự kiện là lời mời, không phải việc bắt buộc**. MStudent hỏi một chạm (Tham gia / Không), giải thích sự
kiện có ích gì cho ngành của sinh viên, và khi tham gia thì lo luôn phần đăng ký + lịch + nhắc.

Phục vụ thang điểm: tiêu chí 1 (AI suy luận theo ngành, thấy trực tiếp trên điện thoại), tiêu chí 2 (vấn đề thật:
quá tải thông báo sự kiện), tiêu chí 3 (cá nhân hoá theo trường/ngành, mở rộng sang nhiều trường).

## Clarifications

### Session 2026-11-14

- Q: Lời mời sự kiện hiện ở đâu? → A: Khối "SỰ KIỆN MỚI" ở đầu tab Việc; sự kiện đã tham gia vào Lịch và danh sách việc;
  thanh tab giữ 4 mục.
- Q: Sự kiện bắt buộc (điểm danh, tính chuyên cần) xử lý thế nào? → A: Tự vào lịch + nhắc, gắn nhãn "Bắt buộc", không có
  nút Không; vẫn hiện nhận xét phù hợp ngành.
- Q: Khai báo trường bằng cách nào? → A: Dùng bộ dữ liệu các trường đại học Việt Nam, tìm nhanh theo tên hoặc tên viết
  tắt (HUST, VJU…); chọn bậc học (Đại học / Thạc sĩ / Tiến sĩ — 3 ô chọn riêng) rồi chọn ngành từ dữ liệu ngành theo
  bậc; vẫn cho nhập tay nếu không tìm thấy.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Khai báo trường và ngành sau khi đăng nhập (Priority: P1)

Lần đầu đăng nhập (hoặc khi chưa khai báo), sinh viên thấy một màn ngắn hỏi **trường** và **ngành** (kèm MSSV, lớp —
tuỳ chọn, dùng để điền sẵn form). Khai báo một lần, sửa được trong Cài đặt.

**Why this priority**: Không có ngành thì không đánh giá được mức phù hợp của sự kiện (Story 3) và không điền sẵn form
được (Story 2).

**Independent Test**: Tài khoản mới đăng nhập → thấy màn "Bạn học ở đâu?" → gõ "HUST" ra Đại học Bách khoa Hà Nội →
chọn bậc Đại học → chọn ngành → vào app; Cài đặt
hiện đúng trường/ngành; đăng xuất đăng nhập lại không bị hỏi lại.

**Acceptance Scenarios**:

1. **Given** tài khoản chưa có trường/ngành, **When** đăng nhập, **Then** hiện màn khai báo trước khi vào app; có nút
   "Để sau".
2. **Given** đã khai báo, **When** mở lại app, **Then** không hỏi lại; Cài đặt cho phép sửa.
3. **Given** sinh viên gõ tên viết tắt hoặc một phần tên trường (không dấu cũng được), **When** tìm, **Then** danh sách
   trường khớp hiện ngay (vd. "VJU" → Trường Đại học Việt Nhật).
4. **Given** đã chọn trường, **When** chọn bậc (Đại học / Thạc sĩ / Tiến sĩ), **Then** danh sách ngành theo bậc đó hiện
   để chọn (tìm được theo tên / mã ngành); không có trong danh sách thì nhập tay.

---

### User Story 2 - Sự kiện hiện thành lời mời với nút Tham gia / Không tham gia (Priority: P1)

Khi MStudent đọc được thông báo sự kiện/seminar/workshop (từ email, Zalo, LMS, bảng lớp, Classroom…), nó không tạo việc
ngay mà tạo một **lời mời**: thông báo trên điện thoại + thẻ lời mời trong app với hai nút được thiết kế theo UI Kit.

- **Tham gia** → sự kiện vào lịch (đúng giờ, địa điểm), đặt nhắc trước, thẻ có nút **"Mở link"** (trang sự kiện) và
  **"Đăng ký (đã điền sẵn)"** nếu có Google Form; nếu có hạn đăng ký riêng thì tạo thêm việc "Đăng ký … trước …".
- **Không tham gia** → ẩn lời mời, không vào lịch, không nhắc.

**Why this priority**: Đây là yêu cầu chính; giải quyết quá tải thông báo sự kiện.

**Independent Test**: Dán thông báo "Workshop AI cho sinh viên 18h thứ 4 tại hội trường A, đăng ký: forms.gle/…" →
thẻ lời mời hiện với 2 nút; bấm Tham gia → sự kiện có trong Lịch đúng ngày giờ, có nút Đăng ký mở form với họ tên/MSSV
/email điền sẵn; với một sự kiện khác bấm Không → biến mất khỏi danh sách.

**Acceptance Scenarios**:

1. **Given** thông báo sự kiện mới, **When** hệ thống xử lý, **Then** có lời mời trạng thái "chờ trả lời", điện thoại
   hiện thông báo "Sự kiện mới: … · Tham gia không?".
2. **Given** lời mời chờ trả lời, **When** bấm **Tham gia**, **Then** sự kiện vào lịch với giờ, địa điểm, nhắc trước
   1 ngày và 2 giờ; thẻ có nút mở link sự kiện và nút đăng ký.
3. **Given** sự kiện có Google Form đăng ký công khai, **When** bấm **Đăng ký (đã điền sẵn)**, **Then** form mở với các
   câu khớp hồ sơ (họ tên, MSSV, email, lớp, trường, ngành) đã điền; sinh viên tự xem lại và tự bấm Gửi. MStudent KHÔNG
   bao giờ tự gửi form.
4. **Given** lời mời, **When** bấm **Không tham gia**, **Then** lời mời ẩn khỏi danh sách và lịch, không nhắc; có thể
   xem lại trong mục "Sự kiện đã bỏ qua" và đổi ý.
5. **Given** cùng một sự kiện được báo từ nhiều nguồn, **When** xử lý, **Then** chỉ có một lời mời (gộp như việc).
6. **Given** lời mời không được trả lời và sự kiện đã qua, **When** tới giờ sự kiện, **Then** lời mời tự ẩn.
7. **Given** điện thoại hỗ trợ nút trên thông báo, **When** thông báo hiện, **Then** có thể bấm Tham gia / Không ngay
   trên thông báo mà không cần mở app.

---

### User Story 3 - Sự kiện này có ích gì cho ngành của bạn (Priority: P2)

Mỗi lời mời có nhận xét ngắn của AI: **mức phù hợp** (Rất phù hợp / Có thể hữu ích / Ít liên quan) và **1–2 câu lý do**
gắn với ngành của sinh viên (vd. "Workshop AI giúp ích cho ngành Khoa học máy tính: thực hành mô hình ngôn ngữ, cơ hội
gặp doanh nghiệp tuyển thực tập").

**Why this priority**: Giúp quyết định nhanh; là điểm AI cá nhân hoá rõ nhất khi demo.

**Independent Test**: Cùng một thông báo "Hội thảo khởi nghiệp fintech": tài khoản ngành Tài chính – Ngân hàng thấy "Rất
phù hợp" kèm lý do; tài khoản ngành Ngôn ngữ Anh thấy mức thấp hơn kèm lý do khác.

**Acceptance Scenarios**:

1. **Given** sinh viên đã khai báo ngành, **When** có lời mời, **Then** thẻ hiện mức phù hợp + lý do 1–2 câu, nhắc tên
   ngành.
2. **Given** chưa khai báo ngành, **When** có lời mời, **Then** thẻ gợi ý "Khai báo ngành để biết sự kiện có hợp với bạn"
   thay cho nhận xét.
3. **Given** AI đang tắt / hết hạn mức, **When** có lời mời, **Then** dùng đánh giá bằng luật (so từ khoá ngành), ghi rõ
   "Bộ luật (offline)", không gọi là AI.
4. **Given** danh sách lời mời, **When** hiển thị, **Then** lời mời "Rất phù hợp" lên trước.

### Edge Cases

- Thông báo vừa là sự kiện vừa có hạn bắt buộc (vd. "Seminar bắt buộc, điểm danh tính chuyên cần"): vẫn là lời mời nhưng
  gắn nhãn "Bắt buộc" và nhắc rõ; mặc định không cho "Không tham gia" ẩn hẳn mà chỉ hạ ưu tiên.
- Sự kiện không có giờ / không có link / link không phải Google Form: vẫn tạo lời mời; thiếu gì thì ẩn nút tương ứng.
- Form bắt đăng nhập tài khoản trường hoặc không đọc được cấu trúc: nút "Đăng ký" mở link gốc, không điền sẵn.
- Link độc hại trong thông báo: chỉ mở link http(s) trong trình duyệt hệ thống, không mở link nội bộ / scheme lạ.
- Hồ sơ sinh viên là dữ liệu cá nhân: chỉ dùng để điền sẵn trên chính máy, không gửi cho bên thứ ba ngoài việc tạo link
  điền sẵn mà chính sinh viên mở.
- Đổi ý: Tham gia → Không (gỡ khỏi lịch, huỷ nhắc) và ngược lại.

## Requirements *(mandatory)*

### Functional Requirements

**Hồ sơ (Story 1)**

- **FR-004**: Bộ dữ liệu trường đại học Việt Nam (tên đầy đủ, tên viết tắt, mã trường nếu có) và ngành theo bậc
  (Đại học / Thạc sĩ / Tiến sĩ, kèm mã ngành) MUST đi kèm app/máy chủ, tìm được không dấu, theo tên viết tắt; có ghi
  nguồn và ngày cập nhật; cập nhật được không cần phát hành lại app.
- **FR-001**: Sau khi đăng nhập, nếu chưa có trường/ngành, app MUST hiện màn khai báo (trường, bậc, ngành bắt buộc; MSSV,
  lớp, số điện thoại tuỳ chọn) có nút "Để sau"; không hỏi lại khi đã khai báo hoặc đã chọn "Để sau" trong 7 ngày.
- **FR-002**: Sinh viên MUST sửa được hồ sơ trong Cài đặt; xoá tài khoản xoá hồ sơ.
- **FR-003**: Mọi trường hồ sơ có giới hạn độ dài; hồ sơ chỉ thuộc chủ tài khoản.

**Lời mời sự kiện (Story 2)**

- **FR-010**: Thông báo được phân loại là sự kiện (category "event") MUST tạo lời mời trạng thái `chờ trả lời` thay vì
  việc thường; trích: tên, thời gian bắt đầu/kết thúc, địa điểm, link sự kiện, link đăng ký, hạn đăng ký, đơn vị tổ chức,
  bắt buộc hay không.
- **FR-011**: Lời mời mới MUST báo lên điện thoại (thông báo đẩy nếu có, nếu không thì khi mở app / làm mới nền) với nút
  Tham gia / Không ngay trên thông báo khi hệ điều hành hỗ trợ.
- **FR-012**: **Tham gia** MUST đưa sự kiện vào lịch và nhắc (1 ngày và 2 giờ trước); nếu có hạn đăng ký thì tạo việc
  "Đăng ký …" có hạn đó.
- **FR-013**: **Không tham gia** MUST ẩn lời mời khỏi danh sách và lịch, huỷ nhắc; xem lại / đổi ý được.
- **FR-014**: Có link Google Form công khai → nút "Đăng ký (đã điền sẵn)" mở form với câu khớp hồ sơ đã điền; MStudent
  MUST NOT tự gửi form.
- **FR-015**: Lời mời trùng nhau giữa các nguồn MUST gộp (như FR-009 của 002).
- **FR-016**: Lời mời chưa trả lời tự ẩn khi sự kiện đã qua.

**Phù hợp với ngành (Story 3)**

- **FR-020**: Mỗi lời mời MUST có mức phù hợp (3 mức) + lý do 1–2 câu theo ngành đã khai báo; AI không có tool, dữ liệu
  thông báo đi qua lớp bảo vệ như các agent khác; tính vào hạn mức AI của sinh viên.
- **FR-021**: AI tắt / hết hạn mức → đánh giá bằng luật, ghi rõ "Bộ luật (offline)".
- **FR-022**: Danh sách lời mời sắp theo mức phù hợp rồi theo thời gian.

### Key Entities

- **Hồ sơ sinh viên**: trường, ngành, MSSV, lớp, số điện thoại — thuộc tài khoản.
- **Lời mời sự kiện**: sự kiện đã trích + trạng thái (chờ / tham gia / không) + mức phù hợp + lý do + link sự kiện + link
  đăng ký + cấu trúc form (nếu đọc được) + việc liên quan (lịch, đăng ký).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Từ lúc thông báo sự kiện được xử lý tới khi sinh viên quyết định: 1 chạm (Tham gia hoặc Không).
- **SC-002**: Sau khi bấm Tham gia, sự kiện có trong lịch với đúng ngày giờ và nhắc, không cần nhập gì thêm (100% sự
  kiện có thời gian rõ ràng).
- **SC-003**: Với form đăng ký công khai, ≥ 80% câu thông tin cá nhân (họ tên, MSSV, email, lớp) được điền sẵn đúng.
- **SC-004**: Danh sách việc không còn sự kiện mà sinh viên đã chọn Không.
- **SC-005**: Nhận xét phù hợp luôn nhắc tới ngành của sinh viên và khác nhau giữa hai ngành khác nhau cho cùng sự kiện.

## Assumptions

- Phân loại "sự kiện" dùng category `event` sẵn có của Triage; Extractor được mở rộng để trích thêm trường của sự kiện.
- Hồ sơ nhập tay (chưa đồng bộ từ hệ thống đào tạo của trường).
- Điền sẵn chỉ áp dụng cho Google Forms công khai đọc được cấu trúc; form khác mở link gốc.
- Nút trên thông báo: Android và iOS hỗ trợ cho thông báo cục bộ; iPhone ký bằng Apple ID miễn phí không có thông báo
  đẩy → lời mời hiện khi mở app hoặc khi làm mới nền.
- Giao diện theo MStudent UI Kit v1 (thẻ màu, nút vàng chanh / nút viền, Meme).
- Hạn chót: càng sớm càng tốt cho demo; Story 1–2 trước, Story 3 ngay sau.
