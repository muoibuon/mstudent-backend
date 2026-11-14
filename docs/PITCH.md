# Pitch — tiêu chí 2 (35 điểm) và 3 (25 điểm)

> Mọi con số dưới đây là **chỗ trống cần đội tự đo**. Đừng điền số ước lượng: giám khảo chấm "có bằng chứng",
> và số bịa rất dễ bị hỏi ngược.

## Tiêu chí 2 — Vấn đề thật của người dùng (35đ)

Thang điểm cần 3 thứ: **người dùng rõ**, **khó khăn có bằng chứng**, **AI giúp trực tiếp**.

### Người dùng

Sinh viên đại học Việt Nam nhận thông báo học vụ từ nhiều kênh cùng lúc: email trường, LMS (Moodle), và nhóm Zalo của
lớp/môn/CLB. Người dùng đầu tiên: sinh viên VJU cùng khoá với đội.

### Khó khăn — cách thu bằng chứng trong 2–3 ngày

| Bằng chứng | Cách làm | Kết quả điền vào |
|---|---|---|
| **Khảo sát** (Google Form, 5 câu, gửi vào các nhóm lớp) | Mục tiêu ≥ 30 phản hồi | `__ / __` bạn từng lỡ hạn hoặc biết muộn vì thông báo bị trôi |
| **Đếm tin nhắn thật** | Xuất 1 tuần tin của 1–2 nhóm Zalo lớp, dán vào MStudent | `__` tin/tuần, trong đó `__` tin cần hành động (`__ %`) |
| **Câu chuyện cụ thể** | Xin 2–3 bạn kể lại một lần lỡ hạn (ảnh chụp tin gốc, đã che tên) | Trích nguyên văn 1 câu |
| **Dùng thật** | 5–10 bạn cài app vài ngày | Số từ thẻ "MStudent đã giúp bạn" |

Câu hỏi khảo sát gợi ý:
1. Bạn đang ở bao nhiêu nhóm Zalo/Messenger liên quan tới việc học?
2. Trong học kỳ này bạn đã từng lỡ hoặc suýt lỡ hạn nộp/lịch thi/đổi phòng vì không thấy thông báo chưa? (Chưa / 1 lần / 2–3 lần / nhiều hơn)
3. Thông báo đó nằm ở đâu? (Zalo / email / LMS / khác)
4. Hiện bạn ghi nhớ hạn bằng cách nào?
5. Bạn có sẵn sàng cho một app đọc thông báo và nhắc hạn không? Điều gì làm bạn e ngại?

### AI giúp trực tiếp — chỉ ra trên máy

| Việc người dùng phải tự làm | MStudent làm | Thấy ở đâu |
|---|---|---|
| Đọc hết tin để tìm tin quan trọng | Triage agent lọc tin nhiễu | "tin nhiễu đã lọc" |
| Tự tính "thứ 6 tuần sau" là ngày nào, tự ghi lịch | Extractor agent ra việc có ngày giờ, môn, phòng | Màn hình chia sẻ → kết quả |
| Không biết hạn đã bị dời | Planner gộp tin gia hạn vào việc cũ, đổi hạn | "lần đổi hạn bắt kịp" |
| Quên | Nhắc trên máy 3 ngày / 1 ngày / 2 giờ trước | Thông báo |

Số đo chất lượng (lấy từ `python -m eval.run_eval` ở chế độ LLM, và chạy lại với `MSTUDENT_OFFLINE=1` để so):

| | AI (LLM) | Bộ luật (không AI) |
|---|---|---|
| Lọc đúng tin | `__ %` | 100 % trên 12 ca mẫu |
| Đúng hạn/giờ | `__ %` | 88 % trên 12 ca mẫu |

> 12 ca mẫu do chính mình viết nên chưa nói lên nhiều. Thêm 20–30 tin thật vào `eval/cases.json` rồi mới dùng số này.

**Hạn chế nên tự nói trước**: AI có thể hiểu sai ngày → mỗi việc đều sửa/dời được và hiện nguồn; nhóm Zalo cá nhân không có
API nên phải chia sẻ tin bằng tay; nội dung thông báo được gửi tới nhà cung cấp LLM.

## Tiêu chí 3 — Khả năng mở rộng thị trường (25đ)

Thang điểm cần: **cách tiếp cận người dùng đầu tiên**, **đường ra toàn cầu**, và **có người dùng thật là lợi thế**.

### Người dùng đầu tiên (làm được ngay)

1. **Lớp của đội** → cài APK/TestFlight, mục tiêu `__` người dùng trước ngày thi. Số liệu: `/api/admin/overview`.
2. **Lớp trưởng / ban cán sự** là điểm vào: họ là người đăng thông báo và mệt vì bị hỏi lại. Một lớp trưởng dùng → cả nhóm biết.
3. **CLB (vd. Monozukuri Club)**: thông báo sự kiện, hạn đăng ký.
4. Vòng lặp lan truyền có sẵn trong sản phẩm: bản tin tuần của lớp do MStudent tổng hợp, gửi lại vào nhóm Zalo kèm link cài.

### Mở rộng

| Giai đoạn | Thị trường | Cần thay đổi gì |
|---|---|---|
| 1 | VJU → các trường thuộc ĐHQGHN | Không đổi sản phẩm; thêm mẫu thông báo từng trường vào eval |
| 2 | Sinh viên Việt Nam | Kênh phân phối qua lớp trưởng; Zalo Official Account cho trường/CLB (có API) |
| 3 | Đông Nam Á, rồi toàn cầu | Cùng vấn đề, khác ứng dụng nhắn tin (LINE, WhatsApp, Telegram, KakaoTalk). LLM đọc được đa ngôn ngữ; phần cần làm là **múi giờ theo người dùng** (hiện cố định +07:00), giao diện đa ngôn ngữ, và connector cho từng ứng dụng |
| 4 | Ngoài sinh viên | Phụ huynh (nhóm lớp của con), nhóm làm việc nhỏ |

Vì sao mở rộng được: lõi là pipeline "tin nhắn tự do → việc có hạn" không phụ thuộc trường hay ngôn ngữ; đưa tin vào bằng
Share sheet hoạt động với mọi ứng dụng nhắn tin trên iOS/Android mà không cần API của họ.

### Rào cản thật (nêu kèm phương án)

| Rào cản | Phương án |
|---|---|
| Quyền đọc Gmail là *restricted scope*: muốn mở công khai phải qua xác minh và đánh giá bảo mật của Google | Giai đoạn đầu: Share sheet + chuyển tiếp email + lịch .ics của LMS (không cần quyền nhạy cảm); xin xác minh khi có người dùng |
| Zalo nhóm cá nhân không có API | Share sheet; Zalo OA cho kênh chính thức |
| Chi phí LLM mỗi tin | Model nhỏ cho Triage, chỉ gọi Extractor cho tin liên quan; không xử lý lại tin đã đọc; giới hạn theo người dùng |
| Niềm tin (app đọc tin nhắn của tôi) | Chỉ-đọc, người dùng chọn tin để chia sẻ, xoá tài khoản xoá hết dữ liệu; xem `SECURITY.md` |

### Mô hình doanh thu (giả thuyết, chưa kiểm chứng)

Miễn phí cho sinh viên; thu phí từ trường/CLB cho kênh thông báo chính thức có xác nhận đã đọc. Cần phỏng vấn ít nhất một
phòng đào tạo hoặc ban chủ nhiệm CLB trước khi khẳng định.

## 5 câu giám khảo hay hỏi

| Câu hỏi | Trả lời ngắn |
|---|---|
| Khác gì Google Calendar / nhắc việc có sẵn? | Những app đó cần người dùng tự nhập. MStudent bắt đầu từ tin nhắn gốc và tự tạo việc |
| AI hiểu sai ngày thì sao? | Hiện tin gốc và các agent đã chạy; sửa/dời bằng một chạm; đo bằng bộ eval |
| Dữ liệu của tôi đi đâu? | Lưu trên server của đội, tách theo tài khoản; nội dung tin gửi tới LLM để phân tích; Gmail chỉ-đọc, token mã hoá; xoá tài khoản là xoá hết |
| Sao không đọc thẳng Zalo? | Zalo không mở API cho nhóm cá nhân; Share sheet là cách hợp lệ và hoạt động với mọi app |
| Backend chạy localhost thì người dùng thật dùng thế nào? | Bản thi chạy local theo yêu cầu; cùng mã nguồn deploy được lên máy chủ có HTTPS (SQLite → Postgres khi cần) |
