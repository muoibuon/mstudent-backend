# Feature Specification: Tự động thu thập thông báo học tập

**Feature Branch**: `002-auto-ingest`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Tự động thu thập thông báo học tập không cần sinh viên thao tác thủ công. Sau khi kết nối nguồn
một lần, hệ thống tự định kỳ lấy dữ liệu mới và biến thành việc cần làm có hạn, ưu tiên, nhắc việc; không tạo trùng; cập
nhật việc cũ khi hạn thay đổi; tôn trọng trần chi phí AI. Ưu tiên: P1 Gmail (kèm email trường/Teams/Udemy chuyển tiếp vào
Gmail) và lịch LMS; P2 Google Classroom; P3 Google Sheets tổng hợp deadline qua link chia sẻ; P4 điện thoại tự nhận việc
mới khi app đóng; P5 Zalo trên Android qua thông báo trên máy; P6 Microsoft 365 để sau demo. Ngoài phạm vi: tự động hoá
tài khoản Zalo cá nhân bằng công cụ không chính thức, Facebook Group, Udemy API. Demo 2026-11-14, P1–P3 phải kịp."

## Bối cảnh

Hiện tại sinh viên phải tự bấm "Đồng bộ Gmail", tự nhập lịch LMS, tự dán hoặc chia sẻ tin Zalo. Nếu quên thao tác thì
MStudent không biết có deadline mới, đúng lúc sinh viên cần nhất. Mục tiêu của tính năng: **kết nối một lần, sau đó
không phải làm gì nữa**. Việc mới tự xuất hiện, hạn đổi thì việc tự cập nhật, điện thoại tự nhắc.

Phục vụ thang điểm: tiêu chí 2 (vấn đề thật, dữ liệu thật từ nhiều nguồn sinh viên đang dùng) và tiêu chí 3 (mở rộng:
nhiều nguồn, nhiều người, chi phí kiểm soát được).

## Clarifications

### Session 2026-11-13

- Q: Cùng một bài xuất hiện ở nhiều nguồn (email, Classroom, bảng lớp) thì xử lý thế nào? → A: So khớp theo tên môn /
  mã học phần trước, rồi xét nội dung và hạn để kết luận có phải cùng một bài; nếu cùng thì gộp vào một việc (ghi đủ các
  nguồn), nếu không chắc thì giữ riêng.
- Q: Theo dõi những lớp Google Classroom nào? → A: Lớp có hoạt động trong 14 ngày gần nhất, hoặc được tạo / tham gia trong
  2 tháng gần nhất; lớp cũ hơn và không hoạt động thì bỏ qua.
- Q: Email mới phải thành việc nhanh tới mức nào (demo không thể chờ 15 phút)? → A: Kết hợp hai cách: Gmail báo ngay khi
  có email mới (vài chục giây) và kiểm tra định kỳ mỗi 2 phút làm lưới an toàn khi kênh báo ngay lỗi; khi có việc / lịch
  mới thì điện thoại hiện thông báo chạy nền, không cần mở app.
- Q: iPhone hiện cài bằng tài khoản Apple miễn phí (không nhận được thông báo đẩy) — xử lý thế nào? → A: Chấp nhận giới
  hạn cho demo: thông báo chạy nền demo trên Android; iPhone tự kéo việc mới khi hệ điều hành cho chạy ngầm hoặc khi mở
  app. Có tài khoản Apple Developer sau này thì bật thông báo đẩy cho iPhone như Android.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Email và lịch LMS tự vào MStudent (Priority: P1)

Sinh viên kết nối Gmail và dán link lịch LMS **một lần**. Từ đó, khi trường, giảng viên, Teams hay Udemy gửi email (trực
tiếp vào Gmail hoặc chuyển tiếp từ email trường), và khi lịch LMS có hạn nộp mới, việc cần làm tự xuất hiện trong
MStudent mà sinh viên không phải mở app hay bấm gì.

**Why this priority**: Email là kênh chính thức của trường và là nơi các nền tảng khác (Teams, Udemy, Coursera…) gửi
thông báo; lịch LMS chứa hạn nộp chính xác. Hai nguồn này đã kết nối được, chỉ thiếu phần tự động, nên làm nhanh nhất
và giá trị cao nhất.

**Independent Test**: Kết nối Gmail, gửi một email "Nộp báo cáo Lab 5 trước 23h59 thứ 6 tuần sau" vào hộp thư, không
mở app; trong thời gian đồng bộ quy định, việc "Nộp báo cáo Lab 5" xuất hiện với đúng hạn.

**Acceptance Scenarios**:

1. **Given** sinh viên đã kết nối Gmail, **When** có email thông báo học tập mới đến, **Then** trong khoảng 1 phút (tối đa
   3 phút) có việc
   cần làm tương ứng với đúng hạn, nguồn ghi "Email", mà sinh viên không thao tác gì.
2. **Given** email quảng cáo hoặc không liên quan đến học tập, **When** hệ thống đồng bộ, **Then** không tạo việc.
3. **Given** cùng một email được đồng bộ nhiều lần, **When** hệ thống đồng bộ lại, **Then** không tạo việc trùng và không
   tốn thêm lượt AI.
4. **Given** sinh viên đã lưu link lịch LMS, **When** giảng viên thêm hoặc dời hạn một bài trên LMS, **Then** trong tối đa
   1 giờ việc mới được tạo hoặc việc cũ được cập nhật hạn (không tạo bản thứ hai).
5. **Given** sinh viên đã chạm hạn mức AI trong ngày, **When** có email mới, **Then** email vẫn được xử lý bằng bộ luật
   (ghi rõ "offline") thay vì bị bỏ qua.
6. **Given** quyền Gmail hết hạn hoặc bị thu hồi, **When** hệ thống đồng bộ, **Then** dừng đồng bộ nguồn đó và app báo
   "Cần kết nối lại Gmail" thay vì lỗi im lặng.

---

### User Story 2 - Bài tập Google Classroom tự vào MStudent (Priority: P2)

Sinh viên cho phép MStudent đọc Google Classroom **một lần**. Bài tập có hạn nộp trong mọi lớp sinh viên đang học tự
thành việc cần làm với đúng hạn; thông báo của lớp được AI lọc như tin nhắn.

**Why this priority**: Nhiều môn giao bài qua Classroom; hạn nộp ở đó là dữ liệu chính xác, không cần AI đoán ngày nên
đúng tuyệt đối và không tốn chi phí AI. Dùng chung lần đăng nhập Google với Gmail.

**Independent Test**: Trong một lớp Classroom thử, giảng viên giao bài có hạn; không mở app, trong thời gian đồng bộ quy
định việc tương ứng xuất hiện với đúng hạn và tên lớp.

**Acceptance Scenarios**:

1. **Given** sinh viên đã cho phép đọc Classroom, **When** giảng viên giao bài có hạn nộp, **Then** có việc cần làm đúng
   tên bài, đúng hạn, ghi tên lớp, nguồn "Classroom".
2. **Given** giảng viên đổi hạn bài tập, **When** hệ thống đồng bộ, **Then** việc cũ được cập nhật hạn.
3. **Given** sinh viên đã nộp bài trên Classroom, **When** hệ thống đồng bộ, **Then** việc tương ứng được đánh dấu xong.
4. **Given** bài tập không có hạn nộp, **When** hệ thống đồng bộ, **Then** vẫn tạo việc nhưng ghi "không có hạn".
5. **Given** trường chặn quyền truy cập Classroom cho ứng dụng bên ngoài, **When** sinh viên bấm cho phép, **Then** app giải
   thích lý do và các nguồn khác vẫn hoạt động.

---

### User Story 3 - Bảng deadline chung của lớp tự vào MStudent (Priority: P3)

Lớp trưởng thường tổng hợp deadline vào một bảng tính chia sẻ cho cả lớp. Sinh viên dán link bảng **một lần**; từ đó
dòng mới thành việc mới, dòng bị sửa hạn thì việc cũ được cập nhật.

**Why this priority**: Đây là cách nhiều lớp đang làm thật; không cần đăng nhập hay xin quyền, nên làm được ngay cả khi
chưa cấu hình tài khoản Google.

**Independent Test**: Tạo bảng tính có cột Môn / Nội dung / Hạn, chia sẻ "ai có link đều xem được", dán link vào app;
thêm một dòng và sửa hạn một dòng; trong thời gian đồng bộ quy định app phản ánh đúng cả hai thay đổi.

**Acceptance Scenarios**:

1. **Given** bảng tính chia sẻ công khai theo link, **When** sinh viên dán link, **Then** mỗi dòng có nội dung thành một
   việc cần làm, hệ thống tự hiểu cột nào là môn, nội dung, hạn mà không bắt sinh viên khai báo.
2. **Given** bảng đã được theo dõi, **When** có dòng mới, **Then** có việc mới; **When** một dòng đổi hạn, **Then** việc cũ
   được cập nhật; **When** không có dòng nào đổi, **Then** không tốn lượt AI nào.
3. **Given** link không phải bảng tính hoặc bảng không chia sẻ công khai, **When** sinh viên dán, **Then** app báo rõ cách
   đổi quyền chia sẻ.
4. **Given** một dòng bị xoá khỏi bảng, **When** hệ thống đồng bộ, **Then** việc tương ứng không bị xoá tự động (tránh mất
   dữ liệu) nhưng được ghi chú "không còn trong bảng".

---

### User Story 4 - Điện thoại tự nhận việc mới khi app đang đóng (Priority: P4)

Việc do hệ thống tự tạo (Story 1–3) phải đến được điện thoại và có nhắc việc kể cả khi sinh viên không mở app.

**Why this priority**: Tự động ở máy chủ mà điện thoại không biết thì sinh viên vẫn bỏ lỡ. Xếp sau P1–P3 vì cần có việc
tự tạo trước.

**Independent Test**: Đóng hẳn app; tạo một email thông báo mới; trong khoảng thời gian quy định điện thoại hiện thông
báo về việc mới (Android) hoặc nhắc việc được đặt đúng hạn (iPhone).

**Acceptance Scenarios**:

1. **Given** app đã đóng, **When** có việc mới tự tạo hoặc hạn bị dời, **Then** điện thoại hiện thông báo "Việc mới: … ·
   hạn …" trong vòng 1 phút.
2. **Given** iPhone cài bản không hỗ trợ thông báo đẩy, **When** có việc mới, **Then** lần làm mới nền kế tiếp do hệ điều
   hành cho phép sẽ tải việc mới và đặt nhắc việc; app ghi rõ giới hạn này trong phần Cài đặt.
3. **Given** sinh viên tắt nhắc việc trong app, **When** có việc mới, **Then** không gửi thông báo.

---

### User Story 5 - Tin nhóm Zalo tự vào MStudent trên Android (Priority: P5)

Sinh viên dùng Android cho phép MStudent đọc thông báo của Zalo **một lần** và chọn nhóm lớp cần theo dõi. Tin mới trong
các nhóm đó (khi điện thoại hiện thông báo) tự được gửi đi phân tích thành việc.

**Why this priority**: Zalo là kênh thông báo chính của nhiều lớp nhưng không có cách đọc chính thức. Đọc thông báo trên
chính máy của sinh viên là cách hợp lệ duy nhất trên Android. Xếp P5 vì rủi ro kỹ thuật cao và không làm được trên iPhone.

**Independent Test**: Trên Android, bật quyền, chọn một nhóm thử; gửi tin "Mai kiểm tra 15 phút chương 3" vào nhóm; trong
vài phút có việc tương ứng mà không mở MStudent hay Zalo.

**Acceptance Scenarios**:

1. **Given** sinh viên đã cấp quyền và chọn nhóm A, **When** nhóm A có tin mới hiện thông báo, **Then** nội dung tin được
   phân tích và tạo việc nếu liên quan học tập.
2. **Given** tin đến từ nhóm không được chọn hoặc từ chat riêng, **When** thông báo hiện, **Then** nội dung **không** rời
   khỏi điện thoại.
3. **Given** nhóm bị tắt thông báo trong Zalo, **When** có tin mới, **Then** không thu được; app nói rõ giới hạn này.
4. **Given** sinh viên thu hồi quyền, **When** có tin mới, **Then** không còn tin nào được gửi đi.

---

### User Story 6 - Email và bài tập Microsoft 365 (Priority: P6, sau demo)

Trường dùng Microsoft 365 (Outlook, Teams) thì sinh viên kết nối tài khoản trường một lần để email trường và bài tập
Teams tự vào MStudent mà không cần chuyển tiếp email.

**Why this priority**: Cần bộ phận CNTT của trường duyệt quyền; không thể kịp trước demo. Trong lúc chờ, quy tắc chuyển
tiếp email sang Gmail (Story 1) đã thay thế được phần lớn.

**Independent Test**: Sau khi trường duyệt, kết nối tài khoản trường; giao một bài tập Teams thử; việc tương ứng xuất
hiện đúng hạn.

**Acceptance Scenarios**:

1. **Given** trường đã duyệt quyền, **When** có bài tập Teams mới, **Then** có việc đúng hạn, nguồn "Teams".
2. **Given** trường chưa duyệt, **When** sinh viên thử kết nối, **Then** app hướng dẫn dùng quy tắc chuyển tiếp email.

---

### User Story 7 - Tệp và tài liệu trong email (Priority: P1b, bổ sung 2026-11-14)

Email của trường hay kèm lịch thi (PDF), đề cương (Word), danh sách (Excel) hoặc link Google Docs/Sheets. MStudent đọc
cả các tài liệu đó, tóm gọn 2–3 câu và tạo việc có hạn từ nội dung bên trong.

**Why this priority**: Nhiều hạn quan trọng (lịch thi, lịch nộp đồ án) chỉ nằm trong tệp đính kèm, không có trong
thân email.

**Independent Test**: Gửi email "Lịch thi học kỳ" kèm PDF có dòng "Giải tích 2 – 08:00 16/12/2026 – A2-301"; trong
thời gian đồng bộ Gmail có việc "Thi Giải tích 2" đúng giờ, ghi chú tóm tắt tài liệu.

**Acceptance Scenarios**:

1. **Given** email liên quan học tập kèm PDF / Word / Excel / CSV, **When** đồng bộ, **Then** nội dung tệp được đọc,
   việc có hạn trong tệp được tạo, việc có ghi chú tóm tắt 2–3 câu của tài liệu.
2. **Given** email chứa link Google Docs / Sheets / Slides chia sẻ công khai, **When** đồng bộ, **Then** tài liệu được
   đọc như tệp đính kèm.
3. **Given** link tài liệu riêng tư, **When** đồng bộ, **Then** không đọc được và việc ghi chú "Tài liệu riêng tư — mở
   để xem", không lỗi.
4. **Given** email quảng cáo / không liên quan có tệp, **When** đồng bộ, **Then** tệp KHÔNG được tải.
5. **Given** cùng một tệp đến lần hai (email chuyển tiếp), **When** đồng bộ, **Then** không tốn thêm lượt AI.
6. **Given** tệp quá lớn, hỏng, có mật khẩu, PDF scan (không có chữ) hoặc nén bất thường, **When** đồng bộ, **Then**
   bỏ qua tệp đó với ghi chú, email và các tệp khác vẫn xử lý.

---

### Edge Cases

- Một bài đến từ nhiều nguồn (email + Classroom + bảng lớp): so khớp tên môn / mã học phần, rồi xét nội dung và hạn;
  cùng bài thì gộp vào một việc và ghi đủ nguồn; không chắc thì giữ riêng (xem FR-009).
- Lần đồng bộ đầu tiên của hộp thư lâu năm: chỉ lấy thông báo trong một khoảng gần đây, không xử lý toàn bộ lịch sử.
- Nguồn trả lỗi tạm thời hoặc chậm: thử lại lần sau, không làm hỏng các nguồn khác hay làm chậm người dùng khác.
- Hàng trăm người dùng cùng đồng bộ: dàn đều theo thời gian, không dồn một lúc.
- Chạm trần chi phí AI chung hoặc riêng: vẫn xử lý bằng bộ luật với nhãn "offline"; dữ liệu có cấu trúc (Classroom, bảng
  lớp đã hiểu cột, lịch LMS) không cần AI nên không bị ảnh hưởng.
- Sinh viên ngắt kết nối nguồn hoặc xoá tài khoản: dừng đồng bộ ngay, xoá dữ liệu kết nối của nguồn đó.
- Bảng tính rất lớn hoặc link trỏ tới nơi không phải bảng tính: từ chối, báo rõ, không làm treo hệ thống.
- Nội dung thông báo cố tình chèn lệnh cho AI (prompt injection): xử lý như mọi thông báo khác, là dữ liệu không tin cậy.

## Requirements *(mandatory)*

### Functional Requirements

**Chung**

- **FR-001**: Sau khi kết nối một nguồn, hệ thống MUST tự lấy dữ liệu mới định kỳ mà không cần sinh viên mở app hay thao
  tác.
- **FR-002**: Mọi dữ liệu tự lấy MUST đi qua cùng quy trình phân tích như dữ liệu dán tay: lọc liên quan, tách việc, chống
  trùng, cập nhật việc cũ khi hạn đổi.
- **FR-003**: Hệ thống MUST NOT tạo việc trùng hoặc gọi AI lại cho dữ liệu đã xử lý.
- **FR-004**: Mỗi lượt gọi AI do đồng bộ tự động MUST tính vào hạn mức AI của đúng sinh viên đó và trần chung; khi chạm
  trần MUST xử lý bằng bộ luật và ghi rõ "offline".
- **FR-005**: Sinh viên MUST xem được trong app: nguồn nào đang kết nối, lần đồng bộ gần nhất, lỗi gần nhất (nếu có), và
  bật/tắt hoặc ngắt kết nối từng nguồn.
- **FR-006**: Lỗi của một nguồn hoặc một sinh viên MUST NOT ảnh hưởng nguồn khác hay sinh viên khác.
- **FR-007**: Dữ liệu của mỗi sinh viên MUST tách biệt hoàn toàn; ngắt kết nối hoặc xoá tài khoản MUST dừng đồng bộ và xoá
  thông tin kết nối của nguồn đó.
- **FR-008**: Chỉ xin quyền **đọc** và ở mức hẹp nhất đủ dùng; không bao giờ gửi, sửa hay xoá dữ liệu ở nguồn.
- **FR-009**: Khi một mục mới có thể trùng với việc đã có từ nguồn khác, hệ thống MUST so khớp tên môn / mã học phần trước,
  sau đó xét nội dung và hạn để kết luận. Cùng một bài → gộp vào việc đã có (cập nhật hạn nếu nguồn mới chính xác hơn,
  ghi thêm nguồn); không chắc → tạo việc riêng. Không bao giờ gộp hai việc khác môn.

**Story 1 – Email và lịch LMS**

- **FR-010**: Email mới MUST thành việc trong khoảng 1 phút khi kênh báo ngay của Gmail hoạt động, và tối đa 3 phút nhờ
  kiểm tra định kỳ mỗi 2 phút khi kênh báo ngay lỗi hoặc chưa cấu hình. Kiểm tra định kỳ khi không có email mới MUST
  không tốn lượt AI.
- **FR-011**: Lần đồng bộ đầu tiên MUST chỉ lấy email trong 7 ngày gần nhất.
- **FR-012**: App MUST hướng dẫn cách tự chuyển tiếp email từ hộp thư trường (Outlook) sang Gmail để email trường, Teams,
  Udemy cũng được xử lý tự động.
- **FR-013**: Sinh viên MUST lưu được link lịch LMS; hệ thống MUST tự tải lại tối đa mỗi giờ và cập nhật hạn bị dời.
- **FR-014**: Khi quyền đọc email không còn hiệu lực, hệ thống MUST dừng đồng bộ nguồn đó và hiển thị yêu cầu kết nối lại.

**Story 2 – Google Classroom**

- **FR-020**: Bài tập có hạn nộp MUST thành việc với đúng hạn và tên lớp mà không cần AI đoán ngày.
- **FR-021**: Hạn bài tập thay đổi MUST cập nhật việc cũ; bài đã nộp MUST đánh dấu việc là xong.
- **FR-022**: Thông báo của lớp MUST được lọc và tách việc như một tin nhắn thông thường.
- **FR-023**: Độ trễ đồng bộ tối đa 30 phút.
- **FR-024**: Chỉ theo dõi lớp có hoạt động (bài tập hoặc thông báo mới) trong 14 ngày gần nhất, hoặc được tạo / tham gia
  trong 2 tháng gần nhất; lớp không thoả cả hai điều kiện thì bỏ qua cho tới khi có hoạt động mới.

**Story 3 – Bảng deadline của lớp**

- **FR-030**: Sinh viên MUST theo dõi được bảng tính chia sẻ công khai theo link bằng cách dán link.
- **FR-031**: Hệ thống MUST tự hiểu vai trò các cột (môn, nội dung, hạn, ghi chú) mà không bắt sinh viên khai báo; dòng
  không đổi MUST NOT tốn lượt AI.
- **FR-032**: Dòng mới tạo việc mới; dòng đổi hạn cập nhật việc cũ; dòng bị xoá MUST NOT xoá việc mà chỉ ghi chú.
- **FR-033**: Chỉ chấp nhận link bảng tính hợp lệ, giới hạn kích thước; từ chối link khác với thông báo rõ ràng.
- **FR-034**: Độ trễ đồng bộ tối đa 1 giờ.

**Story 4 – Điện thoại**

- **FR-040**: Khi hệ thống tự tạo việc mới hoặc dời hạn một việc, điện thoại MUST hiện thông báo chạy nền (app đang đóng)
  với tên việc và hạn, trong vòng 1 phút sau khi việc được tạo (Android, và iPhone khi bản cài cho phép thông báo đẩy).
- **FR-041**: iPhone (bản không có thông báo đẩy) MUST tự làm mới nền khi hệ điều hành cho phép và đặt nhắc việc cho việc
  mới; app MUST nói rõ giới hạn thời gian không đảm bảo.
- **FR-042**: Tôn trọng cài đặt tắt nhắc việc của sinh viên.

**Story 5 – Zalo trên Android**

- **FR-050**: Chỉ hoạt động khi sinh viên cấp quyền đọc thông báo và chọn nhóm; MUST chỉ gửi đi nội dung của các nhóm đã
  chọn, mọi thông báo khác MUST NOT rời khỏi máy.
- **FR-051**: Thu hồi quyền hoặc bỏ chọn nhóm MUST dừng gửi ngay.
- **FR-052**: App MUST giải thích rõ: chỉ thu được tin hiện thành thông báo; không hoạt động trên iPhone.

**Story 7 – Tệp và tài liệu trong email**

- **FR-080**: Chỉ tải tệp đính kèm của email đã được phân loại là liên quan học tập.
- **FR-081**: Đọc chữ từ PDF, Word (.docx), Excel (.xlsx), CSV/TXT; mỗi tệp ≤ 5 MB, ≤ 30 trang, dung lượng giải nén
  ≤ 20 MB, tối đa 5 tệp mỗi email; không chạy macro.
- **FR-082**: Đọc link Google Docs / Sheets / Slides chia sẻ công khai trong thân email (tối đa 3 link mỗi email);
  link riêng tư → ghi chú, không lỗi.
- **FR-083**: Tài liệu dài được thu gọn trước khi gửi AI (ưu tiên đoạn có ngày, giờ, từ khoá hạn/thi/nộp; ≤ 6 000 ký
  tự); AI trả việc có hạn + tóm tắt 2–3 câu gắn vào ghi chú của việc.
- **FR-084**: Mỗi tài liệu (theo nội dung) chỉ xử lý một lần; nội dung tài liệu là dữ liệu không tin cậy, đi qua cùng
  lớp bảo vệ như email và tính vào hạn mức AI của người dùng.

**Story 6 – Microsoft 365 (sau demo)**

- **FR-060**: Kết nối tài khoản trường để đọc email và bài tập; nếu trường chưa duyệt MUST hướng dẫn chuyển tiếp email.

**Trải nghiệm người dùng (bổ sung sau checklist UX)**

- **FR-070**: App MUST có một màn hình **Nguồn tự động** (vào từ Cài đặt) liệt kê mọi nguồn có thể kết nối và đang kết
  nối, kèm trạng thái; mọi thao tác kết nối / thêm link / bật tắt / ngắt nằm ở đây.
- **FR-071**: Ngay sau khi kết nối hoặc thêm link, hệ thống MUST chạy lượt đồng bộ đầu ngay và app MUST hiện kết quả
  ("Đã thêm 5 việc từ Bảng lớp K70") trong vòng 1 phút, hoặc lỗi cụ thể.
- **FR-072**: Link lịch LMS không hợp lệ / không tải được MUST có thông báo riêng, gợi ý lấy lại link xuất lịch từ LMS.
- **FR-073**: Mỗi việc MUST hiện nguồn của nó (Email, Classroom, Bảng lớp, LMS, Zalo); việc gộp từ nhiều nguồn MUST hiện
  đủ các nguồn.
- **FR-074**: Việc người dùng đã **xoá** MUST NOT bị đồng bộ tạo lại từ cùng mục nguồn; việc người dùng đã **tự đánh dấu
  xong** MUST NOT bị mở lại, kể cả khi nguồn đổi hạn (chỉ cập nhật hạn nếu việc còn mở).
- **FR-075**: Lần đồng bộ đầu MUST bỏ qua mục đã quá hạn hơn 1 ngày (bài cũ trong Classroom, dòng cũ trong bảng, sự kiện
  lịch đã qua).
- **FR-076**: Thông báo MUST gộp: tối đa 1 thông báo cho mỗi lượt đồng bộ của một nguồn ("3 việc mới từ Classroom, sớm nhất:
  …"); lượt đồng bộ **đầu tiên** của một nguồn MUST NOT gửi thông báo (đã có kết quả ở FR-071).
- **FR-077**: Bấm vào thông báo MUST mở app tới danh sách việc, đưa việc mới lên đầu (một việc → mở thẳng việc đó).
- **FR-078**: Mỗi nguồn MUST có nút **Đồng bộ ngay**, có giới hạn tần suất để tránh lạm dụng.
- **FR-079**: Thời điểm hiển thị MUST theo giờ Việt Nam và ở dạng dễ đọc ("vừa xong", "5 phút trước", "hôm qua 21:30").

### Key Entities

- **Nguồn kết nối (Source connection)**: một nguồn của một sinh viên: loại (Gmail, lịch LMS, Classroom, bảng lớp, Zalo
  Android, Microsoft 365), trạng thái bật/tắt, lần đồng bộ gần nhất, lỗi gần nhất, dấu mốc "đã đọc tới đâu", thông tin
  truy cập (được bảo vệ, không bao giờ trả về app).
- **Bản ghi đã xử lý**: dấu vân tay của từng mục đã lấy (email, bài tập, dòng bảng, sự kiện lịch) để chống trùng và phát
  hiện thay đổi; liên kết tới việc cần làm đã tạo.
- **Lượt đồng bộ**: lần chạy của một nguồn: thời điểm, số mục mới / cập nhật / bỏ qua, chế độ (AI hay luật), lỗi.
- **Việc cần làm** (đã có): thêm nguồn gốc ("Email", "Classroom", "Bảng lớp", "Zalo", "LMS") và liên kết tới mục nguồn.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Sau khi kết nối, sinh viên **không cần thao tác nào** để thông báo mới thành việc cần làm (0 thao tác).
- **SC-002**: 95% thông báo email học tập mới thành việc trong vòng 1 phút (tối đa 3 phút khi kênh báo ngay lỗi); bài tập Classroom trong 30 phút; thay đổi
  bảng lớp và lịch LMS trong 1 giờ.
- **SC-003**: 0 việc trùng khi cùng một mục nguồn được đồng bộ nhiều lần; cùng một bài nhận từ hai nguồn có cùng mã học
  phần và cùng hạn thì chỉ còn một việc.
- **SC-004**: Hạn nộp lấy từ Classroom và lịch LMS đúng 100% so với nguồn.
- **SC-005**: Đồng bộ lại khi không có gì mới không tốn lượt AI nào.
- **SC-006**: Chi phí AI vẫn trong trần ngày (chung và riêng) với 100 sinh viên đã kết nối Gmail.
- **SC-007**: Trong buổi demo, giám khảo thấy được một thông báo mới đi từ nguồn tới điện thoại **Android** (hiện thông
  báo chạy nền) mà không ai chạm vào app; trên iPhone việc mới có mặt ngay khi mở app.

## Assumptions

- Sinh viên dùng Gmail (cá nhân hoặc trường); email trường trên Outlook được chuyển tiếp sang Gmail bằng quy tắc của
  hộp thư. Kết nối Microsoft 365 trực tiếp để sau demo (Story 6).
- Ứng dụng Google của đội ở chế độ thử nghiệm: tối đa 100 người dùng được mời, quyền đọc email cần cấp lại sau 7 ngày.
  Đưa lên chế độ công khai cần Google xác minh và đánh giá bảo mật, ngoài phạm vi cuộc thi.
- Classroom dùng chung lần đăng nhập Google với Gmail; nếu Classroom thuộc tài khoản trường bị chặn ứng dụng bên ngoài thì
  Story 2 không dùng được với tài khoản đó.
- Bảng lớp được chia sẻ "ai có link đều xem được"; bảng riêng tư để sau (chọn file qua hộp chọn của Google).
- iPhone cài bằng tài khoản Apple miễn phí: không có thông báo đẩy, làm mới nền do hệ điều hành quyết định tần suất.
  Có tài khoản Apple Developer thì dùng thông báo đẩy như Android.
- Đọc thông báo Zalo chỉ có trên Android, cài ngoài cửa hàng (APK); không áp dụng cho iPhone.
- Ngoài phạm vi: tự động đăng nhập/điều khiển tài khoản Zalo cá nhân (vi phạm điều khoản, rủi ro bảo mật), nhóm Facebook
  (không còn cách đọc chính thức), Udemy (không có cách đọc cho học viên; thông báo của Udemy đi qua email).
- Máy chủ hiện tại (một máy, 1 GiB RAM) đủ cho vài trăm sinh viên đồng bộ dàn đều; mở rộng hơn để sau.
- Hạn chót: demo 2026-11-14; P1–P3 phải chạy trên production trước demo; P4–P5 làm nếu kịp; P6 sau demo.
