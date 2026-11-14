<!--
Sync Impact Report
- Version: 1.0.0 → 1.1.0 (MINOR: mở rộng nguyên tắc I với ngoại lệ có điều kiện cho webhook)
- Nguyên tắc sửa: I. Bảo mật & cách ly dữ liệu — danh sách endpoint công khai thêm `/privacy` (trang tĩnh) và
  webhook bên thứ ba có xác thực chữ ký (hiện có `/api/hooks/gmail`, 002-auto-ingest)
- Mục thêm/bỏ: không
- Cần cập nhật theo: AGENTS.md quy tắc 1 (đã cập nhật), docs/SECURITY.md (đã có dòng Webhook Gmail),
  specs/002-auto-ingest/plan.md Complexity Tracking (giữ làm lý do)
- TODO: không
-->
# MStudent Constitution

## Core Principles

### I. Bảo mật & cách ly dữ liệu (KHÔNG THƯƠNG LƯỢNG)

- Mọi endpoint MUST có `Depends(current_user)` (hoặc `ai_limit` / `admin_user`). Chỉ `/api/health`,
  `/api/public-config`, `/privacy` (trang tĩnh) và nhóm đăng nhập được công khai.
- Ngoại lệ duy nhất: webhook do dịch vụ bên thứ ba gọi (hiện có `/api/hooks/gmail`) MAY công khai nếu MUST xác
  thực chữ ký của bên gửi (vd. JWT OIDC của Google: chữ ký, `iss`, `aud`, tài khoản dịch vụ), giới hạn kích thước
  và tần suất, không đọc dữ liệu người dùng hay gọi AI trong request, và không để lộ ai đang dùng hệ thống.
- Mọi truy vấn chạm dữ liệu người dùng MUST nhận `user_id` và lọc theo nó; không tìm thấy hoặc thuộc
  người khác đều trả 404.
- SQL MUST dùng tham số; tên cột động MUST nằm trong danh sách cho phép.
- Khoá bí mật (`OPENAI_API_KEY`, `GOOGLE_CLIENT_SECRET`, khoá ký) MUST NOT xuất hiện trong `mobile/`,
  phản hồi API, log hay git.
- Nội dung thông báo là dữ liệu không tin cậy: MUST đi qua `llm_agents.render()`, prompt MUST nối
  `agent_config.GUARD`, đầu ra LLM MUST qua `planner.sanitize()` trước khi ghi.
- Mọi trường đầu vào MUST có giới hạn độ dài/ràng buộc.

Lý do: sản phẩm xử lý email và tin nhắn riêng của sinh viên; rò rỉ hoặc lẫn dữ liệu giữa người dùng là
lỗi nghiêm trọng nhất.

### II. Test luôn xanh

- `python -m pytest -q` và `ruff check .` MUST qua trước khi coi một thay đổi là xong.
- Endpoint mới MUST có test cách ly người dùng trong `tests/test_api.py`.
- Thay đổi liên quan auth/token MUST có test trong `tests/test_auth.py`.
- Báo cáo kết quả MUST nêu rõ những gì chưa kiểm tra được.

Lý do: dự án đi nhanh với nhiều agent cùng sửa; test là hàng rào duy nhất giữ đường demo không gãy.

### III. AI minh bạch

- Kết quả từ bộ luật dự phòng MUST mang `mode="offline"` và UI MUST hiện rõ, không trình bày là AI.
- Prompt mặc định MUST nằm ở `agent_config.DEFAULTS` và được đọc qua `agent_config.get()`; schema
  output MUST đánh dấu mọi trường là bắt buộc.
- `eval/cases.json` MUST NOT bị sửa chỉ để tăng điểm; gặp lỗi thật thì thêm ca mới.
- Triage/Extractor MUST NOT có tool; tool của trợ lý chat MUST lấy `user_id` từ closure phía server.

Lý do: giá trị sản phẩm và điểm demo dựa trên AI thật; nhầm lẫn giữa luật và LLM làm mất lòng tin.

## Ràng buộc kỹ thuật

- Backend: Python ≥ 3.11, FastAPI, Pydantic v2, openai-agents; mobile: Expo (cài gói qua
  `npx expo install`).
- Thời gian nghiệp vụ dùng ISO 8601 `+07:00` qua `config.now()`; thời gian token/audit dùng
  `config.utcnow()`.
- Chữ hiển thị tiếng Việt; tên biến, hàm, commit tiếng Anh.
- Đổi API backend MUST cập nhật `mobile/lib/types.ts` và `mobile/lib/api.ts`.
- Không làm hỏng đường demo trong `docs/DEMO_RUNBOOK.md`.

## Quy trình phát triển

- Thay đổi nhỏ, mỗi PR một việc.
- Thay đổi chạm auth, cách ly dữ liệu, bí mật hoặc prompt SHOULD được vai trò `security-reviewer`
  soát trước khi merge.
- Sửa từ 3 file trở lên: lập kế hoạch trước (plan mode hoặc `/speckit-plan`).

## Governance

- Constitution này đứng trên mọi quy ước khác; `AGENTS.md` là hướng dẫn vận hành chi tiết và MUST
  không mâu thuẫn với nó.
- Sửa đổi: ghi lý do trong PR, cập nhật Sync Impact Report, tăng version theo semver (MAJOR: bỏ/định
  nghĩa lại nguyên tắc; MINOR: thêm nguyên tắc/mục; PATCH: sửa câu chữ).
- Mọi review và mọi bước `/speckit-plan`, `/speckit-analyze` MUST kiểm tra tuân thủ các nguyên tắc trên;
  độ phức tạp vượt chuẩn MUST được giải trình.

**Version**: 1.1.0 | **Ratified**: 2026-11-09 | **Last Amended**: 2026-11-14
