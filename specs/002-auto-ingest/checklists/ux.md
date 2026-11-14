# UX Requirements Quality Checklist: Tự động thu thập thông báo học tập

**Purpose**: Kiểm tra spec đã mô tả đủ, rõ, nhất quán những gì người dùng nhìn thấy và làm (không kiểm tra code)
**Created**: 2026-11-13
**Feature**: [spec.md](../spec.md)

Đánh dấu `[x]` = spec đã đạt; `[ ]` = thiếu → đã bổ sung vào spec ở mục "Trải nghiệm người dùng" (FR-070…FR-079).

## Kết nối lần đầu

- [x] CHK001 Có nói rõ người dùng chỉ cần thao tác **một lần** cho mỗi nguồn và sau đó không cần làm gì? [Spec §FR-001, SC-001]
- [x] CHK002 Có quy định người dùng tìm và quản lý các nguồn ở đâu trong app (một chỗ duy nhất)? [Gap → FR-070]
- [x] CHK003 Có mô tả người dùng thấy gì ngay sau khi kết nối (lần đồng bộ đầu chạy ngay, bao nhiêu việc được tạo)? [Gap → FR-071]
- [x] CHK004 Có yêu cầu giải thích quyền được xin (chỉ đọc) trước khi người dùng đồng ý? [Spec §FR-008, FR-052]

## Trạng thái và lỗi

- [x] CHK005 Có yêu cầu hiển thị lần đồng bộ gần nhất và lỗi gần nhất cho từng nguồn? [Spec §FR-005]
- [x] CHK006 Lỗi quyền Gmail hết hạn có thông điệp và hành động cụ thể ("Cần kết nối lại Gmail")? [Spec §FR-014]
- [x] CHK007 Bảng không công khai có thông điệp hướng dẫn đổi quyền chia sẻ? [Spec §US3-3, FR-033]
- [x] CHK008 Link lịch LMS sai / không tải được có thông điệp riêng? [Gap → FR-072]
- [x] CHK009 Trường chặn Classroom có giải thích và khẳng định nguồn khác vẫn chạy? [Spec §US2-5]
- [x] CHK010 Hết hạn mức AI có được hiển thị rõ là "offline" chứ không im lặng? [Spec §FR-004, Constitution III]

## Việc được tạo tự động

- [x] CHK011 Người dùng có thấy việc đến từ nguồn nào (và nhiều nguồn khi đã gộp)? [Gap → FR-073]
- [x] CHK012 Việc người dùng đã xoá hoặc tự đánh dấu xong có bị đồng bộ tạo/mở lại không? [Gap → FR-074]
- [x] CHK013 Lần đồng bộ đầu với nhiều bài cũ (Classroom, bảng lớp) có làm ngập danh sách bằng việc đã quá hạn? [Gap → FR-075]
- [x] CHK014 Dòng bị xoá khỏi bảng lớp được xử lý không mất dữ liệu và có ghi chú? [Spec §FR-032]
- [x] CHK015 Gộp nhầm hai môn khác nhau có bị cấm rõ ràng? [Spec §FR-009]

## Thông báo trên điện thoại

- [x] CHK016 Nội dung thông báo có được quy định (tên việc + hạn)? [Spec §FR-040]
- [x] CHK017 Nhiều việc mới cùng lúc có được gộp thành một thông báo thay vì spam? [Gap → FR-076]
- [x] CHK018 Lần đồng bộ đầu (tạo hàng loạt việc) có gửi hàng loạt thông báo không? [Gap → FR-076]
- [x] CHK019 Bấm vào thông báo thì mở tới đâu? [Gap → FR-077]
- [x] CHK020 Tôn trọng cài đặt tắt nhắc việc? [Spec §FR-042]
- [x] CHK021 Giới hạn iPhone được giải thích bằng lời trong app? [Spec §FR-041]

## Điều khiển của người dùng

- [x] CHK022 Có yêu cầu nút "Đồng bộ ngay" cho từng nguồn (cần cho demo và khi người dùng sốt ruột)? [Gap → FR-078]
- [x] CHK023 Bật/tắt và ngắt kết nối từng nguồn? [Spec §FR-005]
- [x] CHK024 Zalo Android: chọn nhóm, thu hồi quyền, giải thích chỉ bắt tin hiện thông báo? [Spec §FR-050–FR-052]
- [x] CHK025 Thời gian chữ hiển thị ("đồng bộ lúc…") có dùng giờ Việt Nam và dạng tương đối dễ đọc? [Gap → FR-079]

## Nhất quán

- [x] CHK026 Độ trễ trong kịch bản chấp nhận khớp với FR và SC (1 phút / 3 phút / 30 phút / 1 giờ)? [Consistency, Spec §FR-010, SC-002]
- [x] CHK027 Giới hạn iPhone trong SC-007 khớp với clarify Q4? [Consistency, Spec §Clarifications]

## Notes

- 11/27 mục thiếu ở lần soát đầu; tất cả đã được bổ sung vào spec (FR-070…FR-079) cùng ngày → checklist đạt 27/27.
