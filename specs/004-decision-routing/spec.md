# Feature Specification: AI quyết định điều phối toàn bộ luồng xử lý thông báo

**Feature Branch**: `004-decision-routing`

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Tiến hành tạo workflow cho decision AI" — chọn phương án "Decision AI điều phối cả luồng":
mở rộng AI quyết định từ chỉ lọc thành bộ điều phối; một lượt hỏi trả lời nhiều câu (liên quan? loại gì? có hạn không?
bắt buộc? hợp ngành mức nào? trùng việc cũ?) rồi quyết định bước nào mới cần gọi AI trả lời.

## Bối cảnh

MStudent có hai AI (từ thay đổi "hai model" trước đó):

- **AI quyết định**: chỉ chọn câu trả lời trong tập cho trước (có/không, một lựa chọn trong danh sách, một mức điểm),
  kèm xác suất. Rất nhanh (dưới 1 giây), rẻ, không sinh chữ — nên nội dung thông báo không thể "ra lệnh" cho nó.
- **AI trả lời**: đọc và viết chữ — trích tên việc, ngày giờ, địa điểm, viết lý do, trả lời chat. Chậm hơn (2–4 giây
  mỗi lượt) và đắt hơn.

Hiện AI quyết định mới chỉ thay bước lọc. Mọi thông báo liên quan vẫn đi qua 2–4 lượt AI trả lời nối tiếp (trích việc,
chi tiết sự kiện, mức phù hợp với ngành…), kể cả những câu hỏi thực chất chỉ là chọn đáp án. Số đo thật trên máy chủ:
lọc 2,6 giây, trích việc 3,9 giây mỗi tin; với hộp thư nhiều tin, một lượt đồng bộ mất hàng phút.

Mục tiêu: **AI quyết định trả lời một lần mọi câu hỏi dạng chọn đáp án cho mỗi thông báo, rồi điều phối**: tin nhiễu
dừng ngay; tin rõ ràng chỉ gọi AI trả lời cho đúng phần cần viết chữ; tin mơ hồ mới được AI trả lời xem lại.

Phục vụ thang điểm: tiêu chí 1 (AI chạy nhanh, thấy được từng quyết định và độ tin cậy trên điện thoại), tiêu chí 2
(xử lý được hộp thư thật nhiều tin), tiêu chí 3 (chi phí và thời gian mỗi người dùng giảm → phục vụ được nhiều người
hơn trên cùng máy chủ).

## Clarifications

### Session 2026-11-14

- Q: Lý do hợp ngành lấy từ đâu khi AI quyết định không viết chữ? → A: Sự kiện mức cao: AI trả lời viết lý do cụ thể
  nhắc tên ngành; mức vừa và thấp: câu mẫu dựng từ mức + lĩnh vực + tên ngành.
- Q: Có nhận thông báo dạng ảnh chụp màn hình trong tính năng này không? → A: Không; để spec riêng sau.
- Q: Tuyến xử lý và độ tin cậy hiện ở đâu? → A: Chỉ web console (trace); app không đổi.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Một lượt quyết định, tin nhiễu không tốn thêm gì (Priority: P1)

Mỗi thông báo mới (email, bảng lớp, tin dán, Zalo) được AI quyết định đánh giá trong **một** lượt: có cần chú ý không,
thuộc loại nào, có mốc thời gian không, có nhiều việc riêng không, mức gấp. Tin nhiễu dừng tại đây. Tin cần chú ý đi
tiếp với các câu trả lời đó đính kèm, để các bước sau không phải hỏi lại.

**Why this priority**: Đây là nền của cả luồng; riêng nó đã giảm thời gian và số lượt AI trả lời cho phần lớn thông báo
(hộp thư sinh viên phần nhiều là tin nhiễu).

**Independent Test**: Gửi 10 thông báo (6 nhiễu, 4 học vụ) khi AI quyết định bật: 6 tin nhiễu không phát sinh lượt AI
trả lời nào; 4 tin học vụ ra đúng việc như hiện nay; trace của mỗi tin hiện các câu trả lời và độ tin cậy.

**Acceptance Scenarios**:

1. **Given** AI quyết định đang bật, **When** một email quảng cáo tới, **Then** nó bị bỏ qua trong một lượt quyết định,
   không có lượt AI trả lời nào, trace ghi "bỏ qua" kèm xác suất.
2. **Given** một thông báo nộp bài có hạn, **When** được xử lý, **Then** việc được tạo đúng tên, hạn, môn như hiện nay,
   loại lấy từ lượt quyết định (không hỏi lại); mức gấp vẫn tính theo hạn, việc không có hạn lấy mức gấp từ lượt
   quyết định.
3. **Given** AI quyết định lỗi hoặc chưa cấu hình, **When** thông báo tới, **Then** luồng chạy như hiện nay (AI trả lời
   lọc rồi trích; AI trả lời cũng lỗi thì bộ luật), không mất thông báo.

---

### User Story 2 - Tin mơ hồ được xem lại, tin rõ ràng đi thẳng (Priority: P1)

Khi AI quyết định không chắc (xác suất "cần chú ý" lưng chừng hoặc độ tin cậy thấp), thông báo được chuyển cho AI trả
lời đánh giá lại thay vì bị bỏ hoặc nhận bừa. Khi chắc chắn, không có bước xem lại.

**Why this priority**: Bỏ sót một hạn nộp tệ hơn nhiều so với tốn thêm một lượt AI; đây là điều kiện để tin tưởng giao
cả luồng cho AI quyết định.

**Independent Test**: Với bộ thông báo mẫu có cả ca mơ hồ ("mai nhớ nha", "thầy bảo tuần sau tính"), ca mơ hồ được
chuyển xem lại và trace ghi lý do chuyển; ca rõ ràng không bị chuyển.

**Acceptance Scenarios**:

1. **Given** xác suất "cần chú ý" nằm trong vùng không chắc, **When** xử lý, **Then** AI trả lời đánh giá lại và quyết
   định cuối cùng là của AI trả lời; trace ghi "chuyển xem lại" kèm xác suất ban đầu.
2. **Given** xác suất rất cao hoặc rất thấp với độ tin cậy cao, **When** xử lý, **Then** không có bước xem lại.
3. **Given** loại thông báo được chọn với độ tin cậy thấp nhưng chắc chắn là cần chú ý, **When** xử lý, **Then** loại do
   AI trả lời xác định lại trong bước trích việc.

---

### User Story 3 - Cập nhật đúng việc cũ thay vì tạo trùng (Priority: P2)

Khi thông báo là thay đổi của một thông báo trước (dời hạn, đổi phòng, huỷ buổi), AI quyết định chọn trực tiếp việc cũ
nào bị ảnh hưởng trong danh sách việc đang mở của sinh viên (hoặc "không có"), thay vì chỉ dựa vào so khớp tên.

**Why this priority**: Trùng việc và bỏ lỡ cập nhật hạn là phàn nàn thường gặp khi một bài được nhắc ở nhiều nguồn với
cách viết khác nhau; nhưng luồng hiện tại đã gộp được phần lớn ca nên xếp sau P1.

**Independent Test**: Có sẵn việc "Nộp báo cáo Lab 5 — INT3306 — thứ 6"; gửi "Thầy cho lùi deadline bài thực hành số 5
sang thứ 2": việc cũ được cập nhật hạn, không có việc mới.

**Acceptance Scenarios**:

1. **Given** sinh viên có việc đang mở trùng nội dung, **When** thông báo thay đổi tới, **Then** việc đó được cập nhật và
   ghi nguồn cập nhật; không tạo việc mới.
2. **Given** thông báo nói về một việc chưa có, **When** xử lý, **Then** tạo việc mới như bình thường.
3. **Given** thông báo nhắc tới một môn khác với việc cũ, **When** xử lý, **Then** không bao giờ gộp hai môn khác nhau
   (giữ quy tắc gộp hiện có).

---

### User Story 4 - Sự kiện: bắt buộc và mức hợp ngành trong cùng lượt (Priority: P2)

Với thông báo sự kiện, cùng lượt quyết định còn trả lời: có bắt buộc không, và mức hữu ích với ngành của sinh viên (cao /
vừa / thấp). Không cần gọi riêng một lượt AI trả lời để chấm mức hợp ngành.

**Why this priority**: Giảm một lượt AI trả lời cho mỗi lời mời và làm mức hợp ngành nhất quán (có xác suất), nhưng phụ
thuộc tính năng lời mời (003) đã có.

**Independent Test**: Cùng một thông báo seminar AI, với hồ sơ ngành Khoa học máy tính ra mức cao, với ngành Nhật Bản học
ra mức thấp; lời mời hiện mức và lý do như hiện nay.

**Acceptance Scenarios**:

1. **Given** sinh viên đã khai ngành, **When** có thông báo sự kiện, **Then** mức hợp ngành đến từ lượt quyết định và
   lời mời hiển thị lý do nhắc tên ngành: mức cao do AI trả lời viết, mức vừa / thấp là câu mẫu.
2. **Given** thông báo nói "bắt buộc, có điểm danh", **When** xử lý, **Then** sự kiện tự vào lịch như hiện nay.
3. **Given** sinh viên đổi ngành, **When** còn lời mời chờ trả lời, **Then** mức hợp ngành được tính lại bằng lượt
   quyết định.

---

### User Story 5 - Bảng lớp: nhận vai trò cột bằng lượt quyết định (Priority: P3)

Khi thêm bảng deadline của lớp, AI quyết định chọn vai trò từng cột (môn, tên việc, hạn, giờ, ghi chú, bỏ qua) thay cho
lượt AI trả lời hiện nay.

**Why this priority**: Chỉ chạy một lần mỗi bảng (hoặc khi tiêu đề cột đổi) nên tiết kiệm ít; làm sau cùng.

**Independent Test**: Bảng mẫu có cột "STT | Môn | Nội dung | Deadline | Ghi chú": nhận đúng vai trò và tạo đúng việc như
hiện nay.

**Acceptance Scenarios**:

1. **Given** một bảng lớp mới, **When** đồng bộ lần đầu, **Then** vai trò cột do lượt quyết định chọn, mỗi vai trò tối
   đa một cột, đúng một cột tên việc.
2. **Given** lượt quyết định không chắc về cột tên việc, **When** đồng bộ, **Then** chuyển cho AI trả lời như hiện nay.

---

### Edge Cases

- AI quyết định trả về câu trả lời ngoài tập cho phép, thiếu câu, hoặc xác suất không hợp lệ → coi như lỗi, dùng luồng
  hiện tại cho tin đó.
- AI quyết định chặn nội dung (an toàn nội dung) → luồng hiện tại; không coi là "tin nhiễu".
- Sinh viên có rất nhiều việc đang mở → chỉ đưa vào câu "trùng việc cũ" những việc gần nhất về thời gian và cùng môn (giới
  hạn số lựa chọn); việc ngoài danh sách vẫn được so khớp như hiện nay.
- Thông báo cực ngắn hoặc chỉ có link → thường rơi vào vùng không chắc → xem lại.
- Hết hạn mức chi phí AI trong ngày → bộ luật, như hiện nay.
- Nguồn có cấu trúc (lịch LMS, Classroom) → không qua lượt quyết định (đã lấy hạn chính xác, không dùng AI).
- Cùng một nội dung đã xử lý → không hỏi lại (giữ bộ nhớ đệm theo tin).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Mỗi thông báo mới (trừ nguồn có cấu trúc và tin đã xử lý) MUST được AI quyết định đánh giá trong đúng một
  lượt, trả lời cùng lúc: cần chú ý (xác suất), loại (6 loại hiện có), có mốc thời gian, có nhiều việc riêng, mức gấp
  (3 mức), là cập nhật của thông báo trước, và — khi có ngữ cảnh — trùng việc cũ nào, sự kiện bắt buộc, mức hợp ngành.
- **FR-002**: Tin có xác suất "cần chú ý" dưới ngưỡng thấp và độ tin cậy cao MUST dừng, không gọi AI trả lời.
- **FR-003**: Tin trong vùng không chắc (giữa ngưỡng thấp và cao, hoặc độ tin cậy thấp) MUST được AI trả lời đánh giá lại;
  quyết định của AI trả lời là quyết định cuối.
- **FR-004**: Tin cần chú ý MUST chỉ gọi AI trả lời cho các phần cần viết chữ (tên việc, ngày giờ, địa điểm, link, ghi
  chú); các câu trả lời dạng chọn đáp án từ lượt quyết định MUST được dùng lại, không hỏi lại.
- **FR-005**: Khi lượt quyết định chọn một việc cũ với độ tin cậy cao, việc đó MUST được cập nhật thay vì tạo việc mới;
  quy tắc không gộp khác môn và ưu tiên hạn từ nguồn có cấu trúc MUST giữ nguyên.
- **FR-006**: Với sự kiện, mức hợp ngành và "bắt buộc" MUST lấy từ lượt quyết định khi có; lý do hợp ngành MUST nhắc tên
  ngành (giữ FR-020/SC-005 của 003): mức cao MUST do AI trả lời viết; mức vừa / thấp MUST dùng câu mẫu dựng từ mức,
  lĩnh vực của sự kiện và tên ngành, không gọi AI trả lời.
- **FR-007**: Vai trò cột của bảng lớp MUST được chọn bằng lượt quyết định, chuyển cho AI trả lời khi không chắc.
- **FR-008**: Mọi lỗi của AI quyết định (mạng, hạn mức, chặn nội dung, câu trả lời không hợp lệ) MUST rơi về luồng hiện
  tại cho đúng tin đó; không thông báo nào bị mất hay bị coi là nhiễu vì lỗi.
- **FR-009**: Trace của mỗi tin MUST ghi các câu trả lời của lượt quyết định, xác suất / độ tin cậy, và tuyến đã đi
  (dừng / đi thẳng / chuyển xem lại / rơi về luồng cũ), và web console MUST hiển thị các thông tin này. App không đổi.
- **FR-010**: Ngưỡng thấp / cao và độ tin cậy tối thiểu MUST chỉnh được bởi quản trị viên mà không cần sửa code; mặc định
  thiên về không bỏ sót (thà xem lại còn hơn bỏ).
- **FR-011**: Dữ liệu gửi cho AI quyết định MUST chỉ gồm nội dung thông báo, tên ngành / trường / bậc (cho câu hợp ngành)
  và tiêu đề + môn + hạn của các việc đưa vào câu "trùng việc cũ"; không gửi mã sinh viên, số điện thoại, email.
- **FR-012**: Mọi lượt quyết định MUST được tính vào hạn mức chi phí hằng ngày (người dùng và toàn hệ thống), kể cả lượt
  lỗi.
- **FR-013**: Kết quả của lượt quyết định MUST được gắn nhãn là AI (không phải bộ luật); kết quả bộ luật vẫn ghi rõ
  "Bộ luật (offline)".
- **FR-014**: Bộ đánh giá chất lượng (eval) MUST báo được kết quả riêng cho luồng có AI quyết định: độ chính xác lọc,
  loại, hạn, số lượt AI trả lời và thời gian trung bình mỗi tin.

### Key Entities

- **Lượt quyết định**: một lần hỏi AI quyết định cho một thông báo; gồm danh sách câu hỏi, câu trả lời, xác suất, độ tin
  cậy, số token, thời gian.
- **Tuyến xử lý**: kết luận điều phối của một tin — dừng, đi thẳng, chuyển xem lại, hoặc rơi về luồng cũ — kèm lý do.
- **Ngưỡng điều phối**: ngưỡng thấp, ngưỡng cao, độ tin cậy tối thiểu cho từng câu; do quản trị viên đặt.
- **Ứng viên trùng việc**: tập việc đang mở (giới hạn số lượng) được đưa làm lựa chọn cho câu "trùng việc cũ".

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Trên bộ eval, độ chính xác lọc và phân loại không thấp hơn luồng hiện tại (hiện 12/12 lọc, 9/9 loại); độ
  chính xác hạn không giảm.
- **SC-002**: Không có thông báo học vụ nào trong bộ eval bị bỏ ở tuyến "dừng" (0 bỏ sót).
- **SC-003**: Với hỗn hợp 30% tin học vụ / 70% tin nhiễu, số lượt AI trả lời giảm ít nhất 50% so với luồng hiện tại.
- **SC-004**: Tin nhiễu được kết luận trong dưới 1 giây (trung vị); tin học vụ rõ ràng nhanh hơn luồng hiện tại ít nhất
  30% (trung vị thời gian từ lúc nhận đến lúc có việc).
- **SC-005**: Với bộ ca "thay đổi thông báo cũ" (dời hạn, đổi phòng) viết khác cách viết ban đầu, ít nhất 90% cập nhật
  đúng việc cũ, 0 ca gộp nhầm khác môn.
- **SC-006**: Khi AI quyết định tắt hoặc lỗi, kết quả eval bằng đúng luồng hiện tại (không có hồi quy).

## Assumptions

- AI quyết định là Google Gemini Decision 1 (đã tích hợp ở bước lọc, khoá `GEMINI_API_KEY` sẽ điền sau). Mọi phần của
  tính năng phải chạy và test được khi chưa có khoá (AI giả trong test, luồng cũ trong thực tế).
- AI trả lời giữ nguyên (GPT-6 Luna) cho các phần cần viết chữ và cho trợ lý chat, bản tin sáng.
- Ngưỡng mặc định ban đầu: dừng khi xác suất < 0,15 và độ tin cậy ≥ 0,8; đi thẳng khi ≥ 0,6; còn lại xem lại. Chỉnh lại
  sau khi đo trên dữ liệu thật.
- Câu "trùng việc cũ" đưa tối đa 30 việc đang mở gần nhất (theo hạn, ưu tiên cùng môn) cộng lựa chọn "không có việc nào".
- Thông báo dạng ảnh / PDF scan nằm ngoài phạm vi; sẽ là spec riêng.
- Không đổi app iOS / Android và không đổi API mà app dùng; tuyến / độ tin cậy chỉ hiện trên web console.
