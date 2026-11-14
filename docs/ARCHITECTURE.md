# Kiến trúc MStudent v1.0

> AI inbox cho sinh viên: gom thông báo rải rác (email trường, LMS, nhóm Zalo lớp) và biến chúng thành việc cần làm có
> hạn, ưu tiên và nhắc việc. Thiết kế theo thang điểm: **AI chạy trực tiếp trên điện thoại thật**, **vấn đề thật có bằng
> chứng**, **mở rộng được**.

## 1. Tổng quan

```mermaid
flowchart LR
  subgraph Phone["Điện thoại thật (iOS / Android)"]
    APP["App Expo<br/>Trợ lý · Việc · Lịch · Cài đặt"]
    SS["Share sheet<br/>(Zalo → MStudent)"]
    KS[("Keychain / Keystore<br/>refresh token")]
    LN["Nhắc việc trên máy"]
  end
  subgraph Laptop["Máy tính (localhost:8000)"]
    API["FastAPI<br/>auth · tasks · chat · google"]
    AG["Pipeline agent<br/>Decision → Extractor / Review → Planner<br/>Digest · Assistant"]
    DB[("SQLite<br/>users · tokens · tasks · …")]
    WEB["Web console<br/>trace · cấu hình · eval"]
  end
  APP -- "HTTP(S) + Bearer JWT" --> API
  SS --> APP
  APP --- KS
  APP --> LN
  API --> AG --> DB
  API --> DB
  WEB --> API
  AG -- "OPENAI_API_KEY" --> LLM["OpenAI Responses API<br/>gpt-6-luna · reasoning high"]
  AG -- "OPENROUTER_API_KEY" --> DEC["OpenRouter<br/>Google Gemini Decision"]
  API -- "client secret" --> G["Google Cloud<br/>Sign-In · Gmail API"]
```

Nguyên tắc: **mọi bí mật ở server** (khoá LLM, client secret Google, khoá ký). App chỉ giữ refresh token của chính MStudent.

## 2. Thành phần

| Thư mục | Vai trò |
|---|---|
| `app/routers/auth.py` | Đăng ký, đăng nhập (mật khẩu / Google), làm mới token, đăng xuất, đổi mật khẩu, xoá tài khoản |
| `app/routers/core.py` | Thông báo → việc, việc, trợ lý chat, bản tin, thống kê, trace, kiểm tra AI, quản trị |
| `app/routers/google.py` | Kết nối Gmail, quét thư, ngắt kết nối |
| `app/pipeline/` | Các agent (xem mục 3) |
| `app/security.py` | Argon2id, JWT, refresh token, Fernet, giới hạn tần suất |
| `app/db.py`, `repo.py` | Schema SQLite và truy vấn (luôn lọc theo `user_id`) |
| `app/google_api.py` | Kiểm ID token, đổi mã uỷ quyền, Gmail REST |
| `app/static/` | Web console cho nhà phát triển (không phải kênh demo) |
| Repo `mstudent-ios` / `mstudent-android` | App Expo, tách khỏi backend |

## 3. Pipeline agent

```mermaid
flowchart LR
  M["Văn bản<br/>(Gmail · tài liệu · thông báo lớp · Zalo · dán tay)"] --> D{Đã xử lý?}
  D -- rồi --> C["Trả kết quả cũ<br/>(không gọi LLM)"]
  D -- chưa --> T{"Decision: relevant + category<br/>một request OpenRouter"}
  T -- stop --> X[(Lưu là tin nhiễu)]
  T -- direct --> E["Extractor<br/>0..n việc, nhãn là gợi ý"]
  T -- review --> V["Review<br/>xem lại + trích trong một lượt"]
  T -- "fallback: lỗi hoặc tắt" --> F["Triage → Extractor<br/>LLM chính, đường cũ"]
  V --> S
  F --> S
  E --> S["Kiểm tra đầu ra<br/>(ngày, độ dài, ≤ 5 việc)"]
  S --> P["Planner<br/>ưu tiên · mốc nhắc · gộp tin gia hạn"]
  P --> DB[(SQLite theo user)]
  V -. LLM lỗi .-> R["Bộ luật<br/>ghi rõ mode=offline"]
  F -. LLM lỗi .-> R
  E -. LLM lỗi .-> R
```

| Agent | Kiểu | Ghi chú |
|---|---|---|
| **Decision** | Gemini Decision qua OpenRouter | Hai câu `relevant`/`category`; xác suất và confidence được kiểm tra trước chọn tuyến |
| **Triage** | LLM chính qua Responses gateway, output có schema | Không có tool. Dùng khi gate tắt/lỗi |
| **Review** | LLM chính, output có schema | Không có tool. Xem lại độ liên quan, phân loại và trích việc trong một lượt |
| **Extractor** | LLM, output có schema | Không có tool. Suy ra ngày tương đối từ thời điểm nhận tin |
| **Planner** | Python | Ưu tiên theo hạn, mốc nhắc 7d/3d/1d/2h, gộp tin gia hạn vào việc cũ |
| **Digest** | LLM / template | Bản tin 7 ngày |
| **Assistant** | LLM + 4 tool | `list_tasks`, `add_notice`, `complete_task`, `get_digest` — `user_id` gắn ở server |

Mọi lượt chạy ghi **trace** (agent, loại `llm`/`rules`, thời gian, đầu ra). App và web console hiện `mode` để không bao giờ
gọi nhầm kết quả của bộ luật là AI. `POST /api/ai/check` gọi thật một lượt LLM để xác nhận trước khi demo.

Ngưỡng mặc định: `decision_low=0.10`, `decision_high=0.80`, `decision_category_conf=0.75`, lưu qua cấu hình admin.
Nhãn loại không chắc không làm phát sinh thêm Triage; Extractor tự phân loại từng việc. Một thông báo nhiều loại
không bị ép thành một loại Task. `other` vẫn có thể hữu ích. Chi tiết vận hành: [DECISION_ROUTING.md](DECISION_ROUTING.md).

LLM chính mặc định dùng `cx/gpt-6-luna(xhigh)` tại `OPENAI_BASE_URL`; mọi agent, kể cả Assistant có tool, dùng chung
Responses client. SDK tracing bên ngoài bị tắt. Phí Decision lấy từ OpenRouter usage; phí main tính theo giá cấu hình
chỉ là ước tính. Không dùng thời gian hoặc phí một request để suy ra lợi ích toàn workflow.

Attachment/link tài liệu có bước xử lý riêng dù body email bị phân loại nhiễu; mỗi tài liệu có hash/cache và giới hạn
parse. Lỗi tài liệu được ghi trace, không coi là kết luận nhiễu. Nguồn ICS/Classroom có cấu trúc đi thẳng planner;
OAuth, token và lỗi fetch không được gửi vào gate như nội dung học vụ.

## 4. Dữ liệu (SQLite)

```
users(id, email UNIQUE, name, password_hash?, google_sub?, created_at, last_login_at)
refresh_tokens(id, user_id→users, token_hash UNIQUE, family, device, created_at, expires_at, revoked_at)
google_accounts(user_id→users, email, refresh_token_enc, scopes, connected_at, last_sync_at)
messages(user_id→users, id, source, sender, subject, body, received_at, relevant, category, reason)
tasks(id, user_id→users, title, course, category, due_at, location, action, priority, source,
      message_id, status, reminders[], updated_from[], created_at, done_at)
traces(id, user_id→users, message_id, created_at, mode, summary, steps[])
settings(key, value)            -- model + prompt, toàn hệ thống, chỉ admin sửa
llm_usage(user_id?, day, agent, input_tokens, output_tokens, cost_usd, latency_ms, created_at)
audit_log(id, at, user_id, event, ip, detail)
```

Khoá ngoại `ON DELETE CASCADE`: xoá tài khoản là xoá hết dữ liệu của người đó. WAL bật sẵn. Phiên bản schema ở `PRAGMA user_version`.

## 5. API

Tất cả cần `Authorization: Bearer <access token>` trừ nhóm Công khai và `/api/auth/{register,login,google,refresh,logout}`.

| Nhóm | Endpoint |
|---|---|
| Công khai | `GET /api/health` · `GET /api/public-config` |
| Tài khoản | `POST /api/auth/register` · `login` · `google` · `refresh` · `logout` · `logout-all` · `change-password` · `GET/DELETE /api/auth/me` |
| Thông báo | `POST /api/ingest` · `/api/ingest/zalo` · `/api/ingest/lms-ics` · `/api/demo/seed` |
| Việc | `GET /api/tasks` · `POST /api/tasks/{id}/done` · `PATCH /api/tasks/{id}` |
| AI | `POST /api/chat` · `GET /api/digest` · `POST /api/ai/check` · `GET /api/traces` · `GET /api/stats` |
| Gmail | `GET /api/google/status` · `POST /api/google/connect` · `POST /api/google/gmail/sync` · `DELETE /api/google/disconnect` |
| Quản trị | `GET/PUT /api/agents/config` · `POST /api/agents/config/reset` · `POST /api/eval` · `GET /api/admin/audit` · `GET /api/admin/overview` |

Tài liệu tự sinh: `http://localhost:8000/docs` (tắt khi `MSTUDENT_ENV=prod`).

## 6. Phiên đăng nhập trên điện thoại (cốt lõi của tiêu chí "đóng hẳn rồi mở lại")

```mermaid
sequenceDiagram
  participant A as App
  participant K as Keychain/Keystore
  participant S as Server
  Note over A: Mở app (kể cả sau khi vuốt đóng)
  A->>K: đọc refresh token
  A->>S: POST /api/auth/refresh
  S-->>A: access token mới (15') + refresh token mới (xoay vòng)
  A->>K: lưu refresh token mới
  Note over A: Hiện ngay việc đã lưu trên máy, rồi tải mới
  A->>S: GET /api/tasks (Bearer)
```

- Server không gọi được → vẫn vào app với dữ liệu đã lưu, **không** bắt đăng nhập lại.
- App bị tắt giữa lúc đổi token → server chấp nhận token cũ trong 30 giây ân hạn, không khoá phiên.
- Access token hết hạn giữa chừng → tự làm mới và gọi lại, người dùng không thấy gì.

## 7. Kết nối nguồn

Từ 002-auto-ingest: **kết nối một lần, máy chủ tự đồng bộ** (`app/sync/`, bộ lập lịch chạy trong tiến trình
web, trạng thái trong bảng `sync_connections`). Chi tiết: `specs/002-auto-ingest/`.

| Nguồn | Cách lấy | Tự động | Trạng thái |
|---|---|---|---|
| **Gmail** | Gmail API chỉ đọc; `history` tăng dần; tuỳ chọn Pub/Sub báo ngay → `/api/hooks/gmail` | 2 phút (≈ 1 phút khi có Pub/Sub) | Có, cần cấu hình Console |
| **Google Classroom** | Classroom API chỉ đọc: bài tập có hạn (không qua AI), bài đã nộp → xong, thông báo lớp qua AI | 10 phút | Có, cần bật API + scope |
| **Bảng lớp (Google Sheets)** | Link chia sẻ công khai → CSV; AI hiểu cột một lần | 30 phút | Có |
| **LMS** | URL lịch `.ics` (Moodle…), ETag | 60 phút | Có |
| **Zalo** | Share sheet (Android), Phím tắt iOS + deep link `mstudent://share`, dán đoạn chat | Thủ công | Có; tự động trên Android qua đọc thông báo: kế hoạch (002 US5) |
| Email trường (Outlook), Teams, Udemy | Chuyển tiếp email sang Gmail đã kết nối | Như Gmail | Có (không cần code) |
| Microsoft 365 trực tiếp | Microsoft Graph | — | Lộ trình bên dưới |
| Email khác | IMAP (`connectors/email_imap.py`) | — | Có mã, chưa nối API |

Google OAuth chỉ phục vụ đăng nhập/Gmail/Classroom. Google Sheets, Docs/Slides và metadata form hiện đọc đường công
khai; không có Drive OAuth để đọc tài liệu riêng tư. OpenRouter và gateway LLM chính dùng API key riêng, không nhận
refresh token Google. Lịch LMS tự đồng bộ không qua AI; endpoint nhập `.ics` thủ công vẫn chuyển về pipeline thông báo.

### Lộ trình Microsoft 365 (002 US6, sau cuộc thi)

1. Đăng ký ứng dụng đa tenant trên Microsoft Entra; quyền uỷ quyền chỉ đọc `Mail.Read`, `EduAssignments.ReadBasic`,
   `offline_access`. Tenant trường (vd `vnu.edu.vn`) thường chặn sinh viên tự đồng ý → cần CNTT trường **duyệt quyền
   cho cả tenant** (admin consent).
2. Thêm nguồn `msgraph` vào bộ lập lịch: thư mới qua delta query `/me/mailFolders/inbox/messages/delta`, bài tập qua
   `/education/me/assignments` (có `dueDateTime`, không cần AI); có thể nhận báo ngay bằng Graph change notifications.
3. Trong lúc chờ: hướng dẫn quy tắc chuyển tiếp Outlook → Gmail (màn hình Nguồn tự động).

## 8. Chạy và triển khai

Production chạy Docker/Compose, Uvicorn chỉ bind `127.0.0.1:8000` trong host network Linux và phục vụ ra ngoài qua
Tailscale Funnel. DB bind mount `/opt/mstudent/data` vào `/data`; UID/GID container khớp user dịch vụ. Root filesystem
chỉ đọc; cấu hình/khóa từ env file trên host. Backup timer gọi container riêng, không cần khóa API hoặc network.
Quy trình build, chuyển từ systemd và rollback: `docs/DOCKER_DEPLOY.md`.

Local demo vẫn có thể dùng `python run_local.py`, mở cổng 8000 trên mạng LAN. Chi tiết demo: `docs/DEMO_RUNBOOK.md`.

## 9. Chưa làm

- Zalo tự động trên Android (đọc thông báo trên máy, 002 US5); Microsoft 365 trực tiếp (lộ trình ở mục 7).
- Thông báo đẩy cho iPhone cần tài khoản Apple Developer (bản ký miễn phí chỉ làm mới nền).
- Múi giờ theo người dùng (đang cố định +07:00) và giao diện đa ngôn ngữ — cần cho thị trường ngoài Việt Nam.
- Xác minh email, quên mật khẩu, HTTPS mặc định (xem `SECURITY.md`).
