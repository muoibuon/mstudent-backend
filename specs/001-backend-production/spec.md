# Feature Specification: Nâng backend MStudent lên bản production

**Feature Branch**: `001-backend-production`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "nâng backend MStudent lên bản production"

## Clarifications

### Session 2026-11-13

- Q: Phạm vi tài khoản? → A: Làm cả xác minh email và quên mật khẩu, nhưng chuyển sang Giai đoạn 2 (xem câu cuối).
- Q: Mã hoá dữ liệu khi lưu trữ? → A: Mã hoá ở mức hạ tầng (kho dữ liệu, bản sao lưu); token Google vẫn mã
  hoá ở mức ứng dụng.
- Q: Mục tiêu tải? → A: Một lớp, khoảng 100 người dùng (tối đa 30 người đồng thời).
- Q: Ai được tự đăng ký tài khoản ở production? → A: Mở cho mọi người; luôn bật giới hạn lượt AI mỗi người và trần chi phí LLM theo ngày.
- Q: Trần chi phí LLM mỗi ngày? → A: 5 USD/ngày toàn hệ thống, cảnh báo ở 80%, chỉnh được qua cấu hình.
- Q: Có chuyển dữ liệu `mstudent.db` local lên production không? → A: Không, production bắt đầu với dữ liệu trống; bản local giữ nguyên cho demo.
- Q: Tài khoản mật khẩu chưa xác minh email được làm gì? → A: (Giai đoạn 2) Dùng được mọi tính năng, chỉ bị chặn kết nối Gmail và nguồn dữ liệu ngoài cho đến khi xác minh; tài khoản Google coi như đã xác minh.
- Q: Hạn hoàn thành? → A: Demo hackathon ngày 2026-11-14. Phạm vi cắt còn MVP (Giai đoạn 1); xác minh email, quên mật khẩu, kiểm thử tải, uptime 99%, triển khai không gián đoạn và log có cấu trúc chuyển sang Giai đoạn 2.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dùng app ở bất cứ đâu, kết nối an toàn (Priority: P1)

Sinh viên và giám khảo cài app bản build, đăng ký và dùng mọi tính năng (chat trợ lý, việc, lịch) qua 4G hay
bất kỳ Wi-Fi nào. Họ không phải ngồi cùng mạng với máy chủ, không phải nhập địa chỉ IP. Mọi dữ liệu đi giữa app
và máy chủ đều được mã hoá.

**Why this priority**: Hiện backend chỉ chạy trên laptop trong mạng LAN, dữ liệu đi không mã hoá. Đây là điều
kiện để giám khảo tự thử trên máy họ (40đ) và để có người dùng thật (35đ).

**Independent Test**: Tắt Wi-Fi, dùng 4G, mở app bản build, đăng ký tài khoản mới, dán một thông báo và nhận
về việc do AI thật tạo ra.

**Acceptance Scenarios**:

1. **Given** điện thoại chỉ có 4G, **When** người dùng mở app và đăng ký, **Then** thành công mà không phải
   nhập địa chỉ máy chủ.
2. **Given** máy chủ chạy chế độ production, **When** có yêu cầu qua kết nối không mã hoá, **Then** không có
   token nào được nhận qua kênh đó.
3. **Given** máy chủ chạy chế độ production, **When** thiếu cấu hình bí mật bắt buộc, **Then** máy chủ không
   khởi động và báo tên cấu hình thiếu, không in giá trị bí mật.
4. **Given** mạng hội trường hỏng, **When** người demo đổi địa chỉ máy chủ trong app sang máy local, **Then**
   app chạy với backend local như runbook hiện tại.

---

### User Story 2 - Dữ liệu không mất, chi phí không vượt kiểm soát (Priority: P2)

Việc và thông báo của người dùng còn nguyên khi máy chủ khởi động lại. Có bản sao lưu hằng ngày. Chi phí LLM
không vượt trần dù đăng ký mở cho mọi người.

**Why this priority**: Mở đăng ký cho người lạ chỉ an toàn khi có trần chi phí. Người dùng thật chỉ quay lại
khi dữ liệu không biến mất.

**Independent Test**: Tạo dữ liệu, khởi động lại máy chủ, dữ liệu và phiên còn nguyên. Đặt trần chi phí rất
thấp, gửi thông báo, kết quả chuyển sang `offline`.

**Acceptance Scenarios**:

1. **Given** có dữ liệu của nhiều người dùng, **When** máy chủ khởi động lại, **Then** dữ liệu, phiên đăng
   nhập và bộ đếm giới hạn tần suất vẫn còn.
2. **Given** đã qua một ngày vận hành, **When** kiểm tra nơi lưu sao lưu, **Then** có bản sao lưu của ngày đó
   và khôi phục thử được.
3. **Given** chi phí LLM trong ngày chạm 80% trần, **When** có thêm lượt gọi, **Then** đội nhận cảnh báo.
4. **Given** chi phí LLM chạm 100% trần, **When** người dùng gửi thông báo, **Then** kết quả được xử lý bằng
   bộ luật, ghi rõ `offline`, cho tới đầu ngày hôm sau.

---

### User Story 3 - Số liệu thật cho buổi pitch (Priority: P3)

Đội trình bày với giám khảo bằng số liệu lấy từ production: bao nhiêu người dùng thật, bao nhiêu thông báo đã
xử lý, bao nhiêu phần trăm do AI và bao nhiêu do bộ luật, chi phí trung bình mỗi người, thời gian xử lý.

**Why this priority**: Tiêu chí "vấn đề thật" (35đ) và "mở rộng" (25đ) chấm bằng bằng chứng. Hiện chưa có chỗ
nào tổng hợp số liệu này.

**Independent Test**: Đăng nhập tài khoản admin, mở màn hình số liệu, các con số khớp với dữ liệu thật.
Tài khoản thường không xem được.

**Acceptance Scenarios**:

1. **Given** tài khoản admin, **When** mở màn hình số liệu, **Then** thấy số người dùng, số thông báo, tỉ lệ
   AI/offline, chi phí LLM hôm nay và trung bình mỗi người, thời gian xử lý trung vị.
2. **Given** tài khoản thường, **When** truy cập số liệu, **Then** bị từ chối.
3. **Given** màn hình số liệu, **When** hiển thị, **Then** không lộ email, nội dung thông báo hay dữ liệu của
   bất kỳ người dùng nào, chỉ có số tổng hợp.

---

### User Story 4 - Biết ngay khi dịch vụ sập (Priority: P4)

Đội nhận cảnh báo trong vòng vài phút nếu dịch vụ ngừng phản hồi, đặc biệt trong đêm trước và trong ngày demo.

**Why this priority**: Phát hiện sớm để kịp sửa hoặc chuyển sang bản local trước giờ demo.

**Independent Test**: Tắt dịch vụ, cảnh báo đến trong 5 phút.

**Acceptance Scenarios**:

1. **Given** dịch vụ ngừng phản hồi, **When** quá 5 phút, **Then** đội nhận cảnh báo.

---

### Edge Cases

- Nhà cung cấp LLM lỗi hoặc chậm: xử lý bằng bộ luật, ghi rõ `offline`, các yêu cầu khác không bị nghẽn.
- VPS khởi động lại hoặc kênh HTTPS bị ngắt: dịch vụ tự chạy lại, không cần thao tác tay.
- Người dùng không nằm trong danh sách test user của Google mà cố kết nối Gmail: được báo rõ là Gmail đang
  giới hạn trong giai đoạn thử nghiệm. Các tính năng khác vẫn dùng bình thường.
- Một người dùng gửi lượng lớn thông báo: bị giới hạn mà không ảnh hưởng người khác.
- Xoá tài khoản: xoá hết dữ liệu của người đó trên production.
- Đường demo local (`docs/DEMO_RUNBOOK.md`) MUST vẫn chạy được trên laptop, không cần VPS.

## Requirements *(mandatory)*

### Functional Requirements — Giai đoạn 1 (trước demo 2026-11-14)

**Truy cập & bảo mật kết nối**
- **FR-001**: Dịch vụ MUST truy cập được qua Internet bằng một địa chỉ cố định, có mã hoá. App bản build MUST
  dùng địa chỉ này làm mặc định.
- **FR-002**: Ở chế độ production, app MUST chỉ gửi token qua kết nối mã hoá.
- **FR-003**: Ở chế độ production, dịch vụ MUST không khởi động nếu thiếu cấu hình bí mật bắt buộc, và MUST
  báo tên cấu hình thiếu mà không in giá trị.
- **FR-004**: Ở production, tài liệu API tự sinh MUST tắt. Chức năng quản trị của web console MUST chỉ dùng
  được với tài khoản admin.
- **FR-005**: Đăng ký MUST mở cho mọi người (email/mật khẩu hoặc Google). Ở production, giới hạn lượt AI mỗi
  người (30/phút, 600/ngày) và trần chi phí LLM theo ngày MUST luôn bật và MUST NOT tắt được bằng cấu hình.
- **FR-006**: Mọi quy tắc bảo mật và cách ly dữ liệu hiện có (Constitution, nguyên tắc I) MUST được giữ nguyên
  và tiếp tục được kiểm thử.
- **FR-007**: App MUST cho phép đổi địa chỉ máy chủ sang máy local để dự phòng khi demo.

**Dữ liệu & chi phí**
- **FR-008**: Dữ liệu người dùng, phiên đăng nhập và bộ đếm giới hạn tần suất MUST còn nguyên sau khi khởi
  động lại.
- **FR-009**: Hệ thống MUST tự sao lưu dữ liệu mỗi ngày, giữ tối thiểu 7 bản, và MUST có hướng dẫn khôi phục
  đã chạy thử.
- **FR-010**: Dữ liệu lưu trữ và bản sao lưu MUST nằm trên ổ có mã hoá hoặc có quyền truy cập giới hạn ở mức
  hạ tầng. Token Google tiếp tục được mã hoá ở mức ứng dụng.
- **FR-011**: Trần chi phí LLM mặc định là 5 USD/ngày cho toàn hệ thống (chỉnh được qua cấu hình). Hệ thống
  MUST cảnh báo khi chạm 80%. Khi chạm 100%, hệ thống MUST tự chuyển sang bộ luật dự phòng (`offline`) cho
  tới đầu ngày hôm sau (giờ +07:00).
- **FR-012**: Việc gọi LLM MUST có thời hạn chờ. Khi LLM chậm hoặc lỗi, hệ thống MUST chuyển sang bộ luật dự
  phòng (`mode="offline"`).
- **FR-013**: Hệ thống MUST phục vụ 100 người dùng đăng ký, tối đa 30 người thao tác đồng thời.

**Số liệu & giám sát**
- **FR-014**: Admin MUST xem được số liệu tổng hợp: số người dùng, số thông báo đã xử lý, tỉ lệ AI/offline,
  chi phí LLM hôm nay và trung bình mỗi người, thời gian xử lý AI trung vị. Số liệu MUST NOT chứa dữ liệu nhận
  dạng cá nhân.
- **FR-015**: Một dịch vụ giám sát bên ngoài MUST kiểm tra dịch vụ còn sống ít nhất mỗi 5 phút và báo đội khi
  sập.
- **FR-016**: Log MUST NOT chứa mật khẩu, token, khoá hay nội dung thông báo.

**Google & quyền riêng tư**
- **FR-017**: Kết nối Gmail MUST chỉ dành cho tài khoản Google trong danh sách test user. Người khác MUST
  được báo rõ và vẫn dùng được các tính năng khác.
- **FR-018**: MUST có trang Chính sách quyền riêng tư công khai, nêu dữ liệu nào được đọc, gửi tới đâu (gồm
  nhà cung cấp LLM) và cách xoá tài khoản.

**Tương thích**
- **FR-019**: Chế độ chạy local cho demo (`docs/DEMO_RUNBOOK.md`) MUST tiếp tục hoạt động không cần VPS.
- **FR-020**: Hợp đồng API giữa app và backend MUST giữ nguyên. Nếu buộc phải đổi, MUST cập nhật đồng thời
  phía mobile.

### Giai đoạn 2 (sau hackathon, ngoài phạm vi lần triển khai này)

- Xác minh email khi đăng ký bằng mật khẩu (chỉ chặn kết nối Gmail và nguồn ngoài; tài khoản Google coi như đã
  xác minh) và quên mật khẩu bằng liên kết dùng một lần, có hạn, thu hồi mọi phiên cũ.
- Kiểm thử tải đầy đủ, mục tiêu sẵn sàng 99% mỗi tuần.
- Triển khai không gián đoạn và quay lại bản trước; chuyển đổi cấu trúc dữ liệu có phiên bản.
- Log có cấu trúc gắn mã yêu cầu; theo dõi tỉ lệ lỗi và độ trễ; cảnh báo khi tỉ lệ lỗi tăng vọt.
- Thẩm định ứng dụng Google để mở Gmail cho mọi người.
- Chạy nhiều bản song song.

### Key Entities

- **Người dùng / phiên đăng nhập**: tài khoản, refresh token xoay vòng; bền vững qua khởi động lại.
- **Dữ liệu nghiệp vụ**: thông báo, việc, trace agent, kết nối Gmail; luôn gắn với một người dùng và được sao lưu.
- **Bộ đếm giới hạn tần suất**: theo người dùng và địa chỉ; bền vững qua khởi động lại.
- **Mức chi tiêu LLM**: số lượt, chi phí ước tính theo ngày, trần và ngưỡng cảnh báo.
- **Số liệu tổng hợp**: các con số ở FR-014, không chứa dữ liệu cá nhân.
- **Bản sao lưu**: thời điểm, vị trí lưu, hạn lưu giữ.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Giám khảo dùng 4G, từ lúc mở app tới khi đăng ký xong và thấy việc đầu tiên do AI tạo hết dưới
  2 phút.
- **SC-002**: Dịch vụ production chạy liên tục từ khi triển khai tới hết buổi demo, có giám sát. Nếu có sự cố,
  cảnh báo đến trong vòng 5 phút.
- **SC-003**: Với 30 người dùng thao tác đồng thời, thao tác không gọi AI hoàn tất dưới 1 giây (kiểm tra nhanh).
- **SC-004**: 0 bản ghi bị mất qua khởi động lại máy chủ.
- **SC-005**: Chi phí LLM không vượt 5 USD trong bất kỳ ngày nào.
- **SC-006**: 0 trường hợp lộ bí mật hoặc nội dung thông báo trong log, phản hồi API và màn hình số liệu.
- **SC-007**: Khi LLM lỗi hoặc chạm trần, 100% thông báo vẫn được xử lý bằng bộ luật và đánh dấu `offline`.
- **SC-008**: Toàn bộ test hiện có và test mới đều qua. Đường demo trong `DEMO_RUNBOOK` chạy được từ đầu đến
  cuối trên cả production và local.

## Assumptions

- Đội có VPS miễn phí của trường, chạy được dịch vụ liên tục và ra được Internet. Không bắt buộc có IP công
  khai hay tên miền riêng, vì có thể dùng kênh HTTPS qua đường hầm miễn phí.
- Nhà cung cấp LLM và Google API giữ nguyên như hiện tại.
- App Google ở chế độ thử nghiệm (tối đa 100 test user cho Gmail). Thẩm định với Google nằm ngoài phạm vi.
- Phía mobile chỉ đổi địa chỉ máy chủ mặc định và bật chế độ chỉ kết nối mã hoá; không thêm tính năng mới.
- Production bắt đầu với kho dữ liệu trống; không chuyển dữ liệu từ bản local.
- Thanh toán / gói trả phí nằm ngoài phạm vi; mô hình freemium chỉ trình bày trong pitch.
- Máy chủ GPU chưa dùng trong Giai đoạn 1. Có thể cân nhắc làm LLM dự phòng ở Giai đoạn 2.
- Kiểm thử xâm nhập độc lập và thông báo đẩy từ máy chủ nằm ngoài phạm vi.
- Gửi nội dung thông báo tới nhà cung cấp LLM được chấp nhận và nêu rõ trong Chính sách quyền riêng tư.
