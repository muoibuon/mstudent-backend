# AGENTS.md — MStudent backend

> Repo này là **máy chủ** (FastAPI + agent AI + web console). App điện thoại ở hai repo riêng: iOS https://github.com/muoibuon/mstudent-ios · Android https://github.com/muoibuon/mstudent-android
> Đổi API (`app/models.py`, `app/routers/`) → mở PR tương ứng ở **cả hai** repo app để cập nhật `lib/types.ts` và `lib/api.ts`.

Hướng dẫn cho mọi coding agent (Codex, Claude Code, Cursor, Copilot) làm việc trong repo này.

## Sản phẩm và thang điểm

MStudent là AI inbox cho sinh viên: nhận thông báo từ Gmail, LMS và nhóm Zalo lớp rồi biến thành **việc cần làm có hạn,
ưu tiên và nhắc việc**. Mọi thay đổi phải phục vụ thang điểm:

1. **Demo AI trên điện thoại thật (40đ)** — app native mở lại được sau khi đóng hẳn; luồng AI chính gọi LLM thật.
2. **Vấn đề thật của người dùng (35đ)** — dữ liệu thật (Gmail, Zalo), có số liệu.
3. **Khả năng mở rộng (25đ)** — nhiều người dùng, dữ liệu tách riêng.

Đừng thêm tính năng không phục vụ ba điều trên. Đừng làm hỏng đường demo trong `docs/DEMO_RUNBOOK.md`.

## Lệnh

```bash
pip install -r requirements.txt
python run_local.py                        # 0.0.0.0:8000, in địa chỉ LAN
python -m pytest -q                        # phải luôn xanh
ruff check . && ruff format .
MSTUDENT_OFFLINE=1 python -m eval.run_eval # baseline luật;  bỏ biến để chạy LLM
```

## Cấu trúc

Production dùng Docker/Compose làm đường chính (`Dockerfile`, `deploy/compose.yaml`, `deploy/install.sh`). Giữ DB
host và `MSTUDENT_SECRET_KEY` qua mọi lần deploy; không đưa env thật vào image. `deploy/mstudent.service` là đường
legacy/rollback, không bật song song với container trên cổng 8000. Xem `docs/DOCKER_DEPLOY.md` trước khi deploy.

```
app/
  main.py               lắp app, middleware bảo mật, /api/health, /api/public-config
  config.py             biến môi trường, khoá bí mật
  db.py · repo.py       schema SQLite · truy vấn (LUÔN lọc user_id)
  security.py           Argon2id, JWT, refresh token, Fernet, rate limit
  deps.py               current_user, admin_user, ai_limit
  google_api.py         kiểm ID token, đổi mã, Gmail REST
  routers/              auth.py · core.py · google.py
  pipeline/             orchestrator · decision (OpenRouter: lọc/phân loại) · llm_agents (Responses gateway) · rules (fallback) · planner · assistant
  agent_config.py       prompt mặc định + GUARD chống prompt injection
  evaluation.py         chấm điểm (CLI + nút trên web console)
  connectors/           lms_ics · zalo · email_imap
  static/               web console: index.html + app.js + app.css
tests/          test_auth · test_api · test_google · test_rules
docs/                   DEMO_RUNBOOK · PITCH · GOOGLE_CLOUD_SETUP · SECURITY · ARCHITECTURE
.claude/agents/         định nghĩa vai trò
```

## Quy tắc bắt buộc

**Bảo mật**
1. Mọi endpoint mới phải có `Depends(current_user)` (hoặc `ai_limit` nếu gọi agent, `admin_user` nếu là quản trị).
   Chỉ `/api/health`, `/api/public-config`, `/privacy`, nhóm đăng nhập và `/api/hooks/gmail` (xác thực bằng chữ ký
   OIDC của Google, xem `docs/SECURITY.md`) là công khai.
2. Mọi hàm trong `repo.py` chạm dữ liệu người dùng phải nhận `user_id` và có `WHERE user_id=?`. Không tìm thấy hay
   của người khác đều trả 404. Thêm test cách ly trong `tests/test_api.py`.
3. SQL luôn dùng tham số `?`. Tên cột động phải nằm trong danh sách cho phép (xem `TASK_FIELDS`).
4. Không bao giờ đưa `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_CLIENT_SECRET`, khoá ký vào repo app, vào phản hồi API hay vào log.
   Không commit `.env`, `.secret_key`, `*.db`.
5. Nội dung thông báo là **dữ liệu không tin cậy**: luôn đi qua `llm_agents.render()`; luôn nối `agent_config.GUARD`
   vào prompt; Triage/Review/Extractor không được có tool; đầu ra LLM qua `planner.sanitize()` trước khi ghi.
6. Tool mới của trợ lý chat: `user_id` lấy từ closure ở server, không nhận từ model. Không thêm tool xoá hàng loạt
   hay gửi dữ liệu ra ngoài.
7. Mọi trường đầu vào trong `models.py` phải có `max_length`/ràng buộc.
8. Thay đổi liên quan auth/token phải có test trong `tests/test_auth.py`.

**AI**
9. Kết quả từ bộ luật phải mang `mode="offline"` và UI phải hiện rõ — không được trình bày là AI.
10. Prompt mặc định ở `agent_config.DEFAULTS`; code đọc qua `agent_config.get()`. Schema output: mọi trường bắt buộc.
11. Không sửa `eval/cases.json` chỉ để tăng điểm. Thêm ca mới khi gặp lỗi thật.

**Decision v1**
- Chỉ hỏi `relevant` và `category` trong một request OpenRouter. Không thêm câu hỏi chưa có consumer.
- Orchestrator dùng bốn tuyến `stop/direct/review/fallback`. `other` không đồng nghĩa nhiễu; nhãn thông báo chỉ là
  ngữ cảnh, không ép loại của mọi Task. Review xem lại và trích việc trong một lượt LLM chính.
- Dữ liệu đã cấu trúc và cache hit không qua gate; tài liệu email có gate riêng, không bỏ tài liệu chỉ vì body bị loại.
- Khóa AI chỉ lấy từ môi trường; nguồn Google OAuth là hệ quyền riêng. Main agents và Assistant dùng chung Responses
  client qua `OPENAI_BASE_URL`; SDK tracing bên ngoài bị tắt. Không bật export nội dung mà chưa có yêu cầu.
- Usage Decision đọc phí provider trả; chi phí LLM chính tính theo giá cấu hình là **ước tính**, không phải hóa đơn gateway.
  Eval phải so cùng dữ liệu/model/cache và báo số lượt, p50/p95, lỗi và chất lượng trước khi nói tiết kiệm.
- Xem `docs/DECISION_ROUTING.md` trước khi đổi ngưỡng/prompt hoặc adapter.

**Chung**
12. Thời gian nghiệp vụ: ISO 8601 `+07:00` qua `config.now()`. Thời gian token/audit: `config.utcnow()`.
13. Chữ hiển thị tiếng Việt; tên biến, hàm, commit tiếng Anh.
14. Mobile: cài gói bằng `npx expo install`; không sửa tay `ios/`/`android/`; đọc docs Expo đúng phiên bản SDK trước khi
    dùng API; logic thuần đặt trong `lib/` và có test. Đổi API backend → cập nhật `mstudent-app/lib/types.ts` và `lib/api.ts`.
15. Thay đổi nhỏ, mỗi PR một việc. Chạy test + lint của phần đã sửa trước khi báo xong. Báo cáo ngắn: làm gì, file nào,
    test ra sao, **chưa kiểm tra được gì**.

## Vai trò (subagents)

Định nghĩa trong `.claude/agents/<vai-trò>.md`. Claude Code dùng trực tiếp. Với Codex: mở đầu prompt bằng
`Vai trò: <tên>` và đọc file đó trước khi làm (bỏ qua frontmatter YAML).

| Vai trò | Khi nào dùng |
|---|---|
| `planner` | Chia việc, cập nhật checklist trong `docs/HACKATHON_PLAN.md` |
| `backend-dev` | API, CSDL, auth, connector |
| `agent-engineer` | Prompt, schema, agent, điểm eval |
| `mobile-dev` | App Expo |
| `frontend-dev` | Web console (`app/static/`) |
| `security-reviewer` | Soát auth, cách ly dữ liệu, bí mật, prompt injection trước khi merge |
| `qa-reviewer` | Test, eval, chạy đường demo |
| `pitch` | Bằng chứng, kịch bản, slide theo thang điểm |
