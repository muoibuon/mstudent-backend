# Kế hoạch thi — Codex Community Hackathon

> Thang điểm và kịch bản demo chi tiết: `DEMO_RUNBOOK.md`. Bằng chứng và mở rộng thị trường: `PITCH.md`.

Giả định: thi **1 ngày, ~8 giờ code (09:00–17:00)**, đội **3 người**. Lịch thật khác thì giữ thứ tự,
co giãn thời lượng.

> ⚠️ **Đọc luật trước:** nhiều hackathon chỉ cho dùng code viết trong giờ thi. Nếu vậy, repo này là
> bản tham khảo/luyện tập: tạo repo mới lúc khai mạc và để Codex dựng lại theo `AGENTS.md` +
> `docs/ARCHITECTURE.md` (khoảng 1 giờ). Nếu được mang code có sẵn, ghi rõ phần nào làm trước.

## Phân vai

| Người | Vai chính | Agent hỗ trợ |
|---|---|---|
| A | Backend + agent LLM | `backend-dev`, `agent-engineer` |
| B | App mobile (Expo) + luồng demo | `mobile-dev`, `frontend-dev` |
| C | Dữ liệu thật, eval, pitch | `qa-reviewer`, `pitch`, `planner` |

Mỗi người chạy Codex/Claude Code trong nhánh riêng (`feat/<tên>`), merge vào `main` sau khi `qa-reviewer` xanh.

## Trước ngày thi

- [ ] Đọc luật, tiêu chí chấm, yêu cầu nộp bài (video? repo public? slide?)
- [ ] Có `OPENAI_API_KEY` + credit; thử `python -m eval.run_eval` ở chế độ LLM
- [ ] Gom **20–30 thông báo thật** (đã xoá tên/SĐT) từ email, Moodle, Zalo lớp → thêm vào `eval/cases.json`
- [ ] Mỗi người cài Codex CLI, đăng nhập, chạy thử repo
- [ ] **Build bản Release và cài lên cả iPhone lẫn Android demo** (xem `DEMO_RUNBOOK.md` mục A) — tiêu chí 40 điểm yêu cầu app thật trên máy thật
- [ ] Cấu hình Google Cloud theo `GOOGLE_CLOUD_SETUP.md`; kết nối Gmail trong vòng 7 ngày trước demo
- [ ] Khảo sát + cho 5–10 bạn dùng thật để có bằng chứng (xem `PITCH.md`)
- [ ] Thử mạng demo: máy tính vào hotspot của điện thoại + `python run_local.py`; chuẩn bị `cloudflared tunnel` dự phòng
- [ ] Chọn 1–2 tính năng mở rộng ở mục 8 `ARCHITECTURE.md`

## Trong ngày thi

| Giờ | Việc | Ai | Xong khi |
|---|---|---|---|
| 09:00–09:30 | Kick-off: chốt phạm vi, `planner` chia task | Cả đội | Checklist bên dưới đã chia người |
| 09:30–11:00 | **Lõi chạy end-to-end chế độ LLM** trên dữ liệu thật | A | Eval LLM ≥ baseline, seed chạy |
| 09:30–11:00 | UI: danh sách task theo ngày, bản tin, mobile | B | Luồng demo bấm được |
| 09:30–11:00 | Thêm case thật, đo baseline, viết slide khung | C | Có bảng điểm baseline |
| 11:00–11:15 | Merge #1 + `qa-reviewer` | Cả đội | `main` xanh |
| 11:15–13:30 | Tính năng mở rộng #1 (vd. xuất .ics / Telegram nhắc việc) | A | Có test |
| 11:15–13:30 | UI cho tính năng #1, dán đoạn chat Zalo | B | — |
| 11:15–13:30 | `agent-engineer`: sửa prompt theo case sai, chạy eval | C | Điểm due/category tăng |
| 13:30–14:00 | Ăn trưa + merge #2 | Cả đội | — |
| 14:00–15:30 | Tính năng #2 **hoặc** đánh bóng (chọn theo tiến độ) | A, B | — |
| 14:00–15:30 | `pitch`: kịch bản demo, slide, README, quay video dự phòng | C | Có video 2–3' |
| 15:30–16:00 | **Đóng băng tính năng.** Chỉ sửa bug | Cả đội | — |
| 16:00–16:30 | Tập demo 3 lần, bấm giờ | Cả đội | ≤ 3 phút |
| 16:30–17:00 | Nộp bài: repo, video, slide | C | Đã nộp |

## Checklist tính năng

- [ ] Pipeline LLM chạy với dữ liệu thật, có fallback offline
- [ ] Tin gia hạn cập nhật task cũ (không tạo trùng)
- [ ] Một tin → nhiều task (vd. "nghỉ thứ 5, học bù thứ 7")
- [ ] Bản tin sáng
- [ ] Dán cả đoạn chat Zalo
- [ ] Tính năng mở rộng #1: ______
- [ ] Tính năng mở rộng #2: ______
- [ ] Bảng điểm eval LLM vs luật cho slide

## Kịch bản demo

Xem `DEMO_RUNBOOK.md` mục D (bám theo thang điểm, làm trên điện thoại thật).
