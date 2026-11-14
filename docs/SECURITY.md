# Bảo mật MStudent

Phần nào có test tự động thì ghi tên test (`tests/`).

## Đã làm

| Lớp | Biện pháp | Ở đâu | Test |
|---|---|---|---|
| **Mật khẩu** | Băm **Argon2id**; tối thiểu 8 ký tự, chặn mật khẩu phổ biến/trùng email; tự băm lại khi tham số cũ | `security.py` | `test_register_login_me`, `test_register_validation` |
| **Đăng nhập** | Thông báo lỗi giống nhau cho sai mật khẩu và email không tồn tại; so khớp thời gian ổn định; khoá tạm sau 5 lần sai / 5 phút theo (IP, email) | `routers/auth.py` | `test_login_failures_same_error_and_lockout` |
| **Access token** | JWT HS256, sống 15 phút, bắt buộc `exp/sub/typ`, chỉ chấp nhận đúng thuật toán (chặn `alg=none`, khoá giả) | `security.py` | `test_access_token_rejects_tampering_and_expiry` |
| **Refresh token** | Chuỗi ngẫu nhiên 384 bit, **chỉ lưu SHA-256** trong CSDL, **xoay vòng** mỗi lần dùng; dùng lại token cũ → thu hồi cả chuỗi đăng nhập (ân hạn 30 giây cho trường hợp app bị tắt giữa chừng) | `routers/auth.py` | `test_refresh_rotation_and_reuse_detection`, `test_refresh_grace_when_app_killed_mid_rotation` |
| **Trên điện thoại** | Refresh token trong **Keychain/Keystore** (expo-secure-store, `AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY`); access token chỉ trong RAM | `mstudent-app/lib/api.ts` | — |
| **Cách ly dữ liệu** | Mọi truy vấn đều lọc `user_id`; việc của người khác trả 404 như không tồn tại; tool của trợ lý chat gắn sẵn `user_id` ở server | `repo.py`, `pipeline/assistant.py` | `test_users_cannot_touch_each_other` |
| **Phân quyền** | Sửa prompt/model, chạy eval, xem audit log chỉ dành cho email trong `MSTUDENT_ADMIN_EMAILS` | `deps.py` | `test_admin_only_config_and_eval` |
| **Google** | Kiểm chữ ký/`aud`/`iss`/`exp` của ID token; client secret chỉ ở server; refresh token Google **mã hoá Fernet** khi lưu; ngắt kết nối/xoá tài khoản → thu hồi ở Google | `google_api.py` | `test_gmail_connect_sync_disconnect` |
| **Chiếm tài khoản trước** | Email đã có tài khoản mật khẩu (chưa xác minh) mà chủ thật đăng nhập Google → vô hiệu mật khẩu và mọi phiên cũ | `routers/auth.py` | `test_google_link_disables_unverified_password` |
| **Prompt injection** | Thông báo được bọc trong `<thong_bao>` và không tự đóng thẻ được; quy tắc an toàn luôn nối vào prompt (admin không sửa được); Triage/Extractor **không có tool**; đầu ra LLM được kiểm tra (ngày, độ dài, tối đa 5 việc) trước khi ghi | `agent_config.py`, `llm_agents.py`, `planner.sanitize` | `test_prompt_wraps_untrusted_content`, `test_sanitize_llm_output` |
| **Chi phí LLM** | 30 lượt agent/phút và 600/ngày mỗi người; không chạy lại agent cho tin đã xử lý | `deps.ai_limit`, `orchestrator.ingest` | `test_ai_rate_limit`, `test_trace_and_duplicate` |
| **Trần chi phí theo ngày** | Ghi token/chi phí mỗi lượt gọi (không lưu nội dung) vào `llm_usage`, **kể cả lượt lỗi/quá hạn** (ước tính bi quan); vượt `MSTUDENT_LLM_DAILY_USD` (mặc định 5 USD) → cả hệ thống chạy bộ luật tới hết ngày; vượt `MSTUDENT_LLM_USER_DAILY_USD` (mặc định 0,5 USD) → **chỉ người đó** chạy bộ luật, nên một người không đốt hết AI của mọi người; `/api/ai/check` tính vào hạn mức AI của người gọi; eval cũng tôn trọng trần; cảnh báo webhook ở 80% và 100% | `budget.py` | `test_llm_usage_recorded_per_call`, `test_daily_budget_switches_to_offline_and_resets_next_day`, `test_budget_alert_at_80_percent_once`, `test_ai_check_reports_budget_exhausted`, `test_failed_llm_call_still_counts_toward_budget`, `test_per_user_daily_cap_only_affects_that_user`, `test_ai_check_counts_against_user_and_ai_limit`, `test_eval_respects_budget` |
| **Thời hạn gọi LLM** | Mỗi lượt gọi tối đa `MSTUDENT_LLM_TIMEOUT_S` (25 giây); quá hạn → đường luật, trace ghi lỗi | `llm_agents.run_llm` | `test_llm_timeout_falls_back_to_rules` |
| **Giới hạn tần suất bền vững** | Bộ đếm lưu SQLite (`rate_counters`), giữ nguyên sau khởi động lại | `security.RateLimiter` | `test_rate_limit_survives_restart`, `test_rate_limit_counts_previous_window` |
| **HTTPS production** | Tailscale Funnel (chứng chỉ Let's Encrypt), backend chỉ nghe `127.0.0.1:8000`; app chỉ cho `http://` với địa chỉ mạng nội bộ, bỏ `user:pass@` trước khi xét host (chặn lách kiểu `http://localhost:x@evil.com`) | `deploy/mstudent.service`, `mstudent-app/lib/url.ts` | `mstudent-app/lib/__tests__` (normalizeUrl) |
| **IP thật sau proxy** | Chỉ tin `X-Forwarded-For` khi `MSTUDENT_TRUST_PROXY=1` **và** kết nối đến từ 127.0.0.1/::1 → khoá đăng nhập và giới hạn tần suất theo IP người dùng thật; đã kiểm trên production (audit ghi IP công khai) | `deps.client_ip` | `test_client_ip_*` |
| **Kiểm cấu hình khi khởi động** | `MSTUDENT_ENV=prod` thiếu khoá ký/khóa provider chính (`OPENAI_API_KEY`)/admin, hoặc đặt `MSTUDENT_NOW` → từ chối chạy; lỗi chỉ nêu tên biến, không in giá trị. `MSTUDENT_OFFLINE=1` cho phép chạy không có khóa provider chính (đường lui) | `config.check_prod_config` | `test_prod_config_*` |
| **Máy chủ** | Dịch vụ systemd chạy user hệ thống `mstudent` (không shell), `NoNewPrivileges`, `ProtectSystem=strict`, chỉ ghi được `/opt/mstudent/data`; `/etc/mstudent.env` quyền 600; SSH chỉ bằng khoá; ổ đĩa Azure **được mã hoá khi lưu** (khoá do nền tảng quản lý) | `deploy/` | — |
| **Sao lưu** | Bản sao SQLite nhất quán (`sqlite3.backup`) lúc 03:00 hằng ngày, giữ 7 bản, thư mục 700/file 600; đã khôi phục thử trên production | `deploy/backup.py`, `mstudent-backup.timer` | `test_backup_script_copies_restorable_db_and_prunes_old` |
| **Webhook Gmail (Pub/Sub)** | `/api/hooks/gmail` công khai nhưng chỉ nhận JWT do Google ký: kiểm chữ ký, `iss`, `aud` = URL webhook, `email` = service account cấu hình; body ≤ 8 KB; 120 lần/phút; không đọc thư hay gọi AI trong request, chỉ hẹn lượt đồng bộ; luôn 204 khi chữ ký đúng (không lộ ai đang dùng) | `routers/hooks.py`, `google_api.verify_push_jwt` | `test_gmail_webhook_requires_google_signature` |
| **Đồng bộ tự động** | Chỉ scope đọc; token Google vẫn mã hoá Fernet; quyền bị thu hồi → tắt nguồn + "Cần kết nối lại"; lỗi một nguồn không ảnh hưởng nguồn khác; bảng lớp chỉ tải từ `docs.google.com` / `*.googleusercontent.com` + kiểm IP công khai, lịch LMS kiểm IP công khai, không theo chuyển hướng; mọi lượt AI tính vào hạn mức của chủ nguồn | `sync/` | `test_sync.py` |
| **Tài liệu trong email** | Mỗi tài liệu có gate riêng dù body email bị loại; PDF/Word/Excel/CSV ≤ 5 MB, ≤ 30 trang, giải nén ≤ 20 MB (chống zip bomb), ≤ 5 tệp/email, không chạy macro; link Google chỉ đọc bản công khai qua bộ tải có allowlist; nội dung tài liệu đi qua `render()` + GUARD + `sanitize()` như email, tóm tắt bằng agent không có tool; hash tránh xử lý lại tài liệu của cùng user; lỗi đọc ghi trace riêng | `connectors/docs.py`, `sync/docs_ingest.py` | `tests/test_docs.py` |
| **Hồ sơ học tập + lời mời sự kiện (003)** | Hồ sơ (trường, bậc, ngành, MSSV, lớp, SĐT) chỉ thuộc chủ tài khoản, có giới hạn độ dài, 30 lần sửa/giờ, xoá cùng tài khoản; gửi cho AI **chỉ trường/bậc/ngành** (không MSSV, lớp, SĐT). Form đăng ký: máy chủ chỉ đọc *cấu trúc* Google Form công khai (allowlist `docs.google.com`/`forms.gle`, kiểm IP công khai từng chặng, ≤ 1 MB, form bắt đăng nhập → bỏ qua); **link điền sẵn dựng trên điện thoại**, máy chủ không ghép dữ liệu cá nhân vào URL; **MStudent không bao giờ tự gửi form** — người dùng tự xem và bấm Gửi. Link sự kiện từ tin/AI chỉ nhận `http(s)`; `/rsvp` lọc theo `user_id` (của người khác → 404), 120 lần/giờ; agent EventDetails/MajorFit không có tool, đi qua GUARD; đánh giá bằng luật ghi rõ "Bộ luật (offline)" | `pipeline/events.py`, `routers/profile.py`, `mstudent-app/lib/prefill.ts` | `tests/test_events.py`, `mstudent-app/lib/__tests__` |
| **Hai model AI** | Decision gọi OpenRouter `google/gemini-decision-1`, chỉ hỏi `relevant`/`category`; kiểm type, xác suất hữu hạn, confidence và tập nhãn. Bốn tuyến stop/direct/review/fallback; Review xem lại + trích một lượt; lỗi Decision không được coi là nhiễu. `other` không đồng nghĩa nhiễu, nhãn thông báo không ép mọi task. Mô hình tập đóng vẫn có thể chọn sai dưới nội dung độc hại; validation và quyền dữ liệu vẫn bắt buộc | `pipeline/decision.py`, `orchestrator.classify` | `tests/test_decision.py`, `tests/test_routing.py` |
| **Provider chính và tracing** | Main agents/Assistant dùng chung custom Responses client theo `OPENAI_BASE_URL`/model cấu hình, không âm thầm chuyển về OpenAI; SDK tracing bên ngoài bị tắt ở module và mỗi run. Khóa OpenRouter/main chỉ ở môi trường, không đưa vào payload học vụ. API key model độc lập với Google OAuth nguồn dữ liệu | `llm_agents.build_agent`, `run_llm`, `config.py` | `tests/test_main_provider.py` |
| **Đo lường** | Usage request-local tránh lẫn eval chạy đồng thời; OpenRouter cung cấp cost khi có, LLM chính dùng giá cấu hình để ước tính (không phải hóa đơn gateway). Lượt lỗi vẫn tính ước tính; không suy ra tiết kiệm USD nếu giá gateway chưa được xác nhận | `budget.capture_usage`, `evaluation.py` | `tests/test_evaluation.py` |
| **Trang quyền riêng tư** | `/privacy` công khai, nêu OpenRouter, Google Decision, gateway chính do người vận hành cấu hình, nơi lưu và cách xoá | `static/privacy.html` | `test_privacy_page_is_public` |
| **Đầu vào** | Giới hạn độ dài mọi trường (Pydantic); body tối đa 256 KB; truy vấn SQL luôn dùng tham số | `models.py`, `main.py` | `test_hardening` |
| **SSRF** | Nhập lịch .ics chỉ nhận http(s) tới địa chỉ công khai, không theo chuyển hướng, tối đa 2 MB | `routers/core.py`, `connectors/lms_ics.py` | `test_hardening` |
| **Web console** | CSP `script-src 'self'` (không script nội tuyến), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `Cache-Control: no-store` cho API; không dùng cookie → không có CSRF | `main.py` | `test_hardening` |
| **CORS** | Mặc định tắt hoàn toàn; chỉ bật cho origin khai báo trong `MSTUDENT_CORS_ORIGINS` | `main.py` | `test_hardening` |
| **Bí mật** | `OPENAI_API_KEY`, client secret, khoá ký chỉ ở server (`.env`, `.secret_key` quyền 600, đều trong `.gitignore`); `MSTUDENT_ENV=prod` bắt buộc đặt khoá và tắt `/docs` | `config.py` | — |
| **Quyền riêng tư** | Xoá tài khoản xoá toàn bộ việc, thông báo, trace, token (CASCADE); Gmail chỉ-đọc | `routers/auth.py` | `test_delete_account_removes_everything` |
| **Nhật ký** | Ghi đăng nhập/thất bại, phát hiện dùng lại token, đổi cấu hình agent, kết nối Gmail | `repo.audit` | `test_admin_only_config_and_eval` |

## Chưa làm — nói thẳng khi giám khảo hỏi

| Thiếu | Rủi ro | Hướng xử lý |
|---|---|---|
| **HTTPS khi lùi về chạy localhost** | Production đã có HTTPS; chỉ khi lùi về laptop trong Wi-Fi chung thì người cùng mạng có thể nghe lén | Lùi về qua hotspot riêng của điện thoại; bản phát hành build với `MSTUDENT_HTTPS_ONLY=1` |
| **Quyền admin theo email chưa xác minh** | Admin xác định bằng `MSTUDENT_ADMIN_EMAILS`, mà đăng ký mật khẩu không xác minh email → ai đăng ký email admin trước sẽ thành admin (giảm thiểu: đội đã đăng ký sẵn email admin trên production; nếu chủ thật đăng nhập Google, mật khẩu cũ bị vô hiệu) | Chỉ cấp quyền admin cho phiên đăng nhập Google (email đã xác minh), hoặc `MSTUDENT_REGISTRATION=closed` |
| Xác minh email khi đăng ký bằng mật khẩu | Ai cũng đăng ký được bằng email của người khác (đã giảm thiểu bằng cơ chế "chiếm tài khoản trước" ở trên) | Gửi mã xác minh qua email; hoặc chỉ cho đăng nhập Google |
| Quên mật khẩu | Người dùng mật khẩu bị khoá ngoài nếu quên | Cần dịch vụ gửi email |
| Mã hoá nội dung thông báo trong SQLite | Ổ đĩa Azure đã mã hoá khi lưu, nhưng ai có quyền root trên VM (hoặc lấy được bản sao lưu) vẫn đọc được thông báo | SQLCipher; mã hoá bản sao lưu bằng khoá ngoài máy |
| Một máy chủ, một tiến trình | VM sập là dịch vụ ngừng; SQLite + 1 worker giới hạn vài chục yêu cầu đồng thời | Theo dõi bằng UptimeRobot; khi lớn: Postgres + nhiều worker sau load balancer |
| Nội dung được gửi tới OpenRouter/Google Decision và gateway LLM chính | Dữ liệu rời máy chủ; gateway có thể chuyển tiếp tới provider khác, model alias không xác minh danh tính upstream | Công bố nơi xử lý thực tế và điều khoản trước khi mở dịch vụ; không gửi credential nguồn; cho người dùng chọn nguồn nào được đọc |
| Giá gateway và model upstream chưa có xác nhận độc lập | Phí tính theo token/giá cấu hình là ước tính; model alias có thể được gateway ánh xạ | Xác nhận với người vận hành gateway, đối chiếu hóa đơn; báo số lượt/token và độ trễ riêng |
| Trần chi phí kiểm trước, ghi sau | Nhiều yêu cầu đồng thời có thể vượt trần một khoảng nhỏ | Dừng ở 95% trần, hoặc giữ chỗ chi phí trước khi gọi |
| Khoá giới hạn tần suất chứa email | `rate_counters` lưu `login:{ip}:{email}` tới khi được dọn (≤ 2 ngày), có trong bản sao lưu | Băm email trong khoá |
| Quyền file trên VM | `/etc/mstudent.env`, mã nguồn, venv thuộc user `mstudent` (dịch vụ chỉ đọc nhờ `ProtectSystem=strict`, nhưng tiến trình khác cùng user sửa được) | Chuyển sang `root:root`, chỉ `data/` và thư mục sao lưu thuộc `mstudent` |
| Hardening systemd chưa tối đa | Thiếu `CapabilityBoundingSet=`, `PrivateDevices`, `RestrictAddressFamilies`, `SystemCallFilter`… | Bổ sung, kiểm bằng `systemd-analyze security mstudent` |
| Đồng bộ tự động: mục mức thấp (soát T049) | URL lịch LMS (có thể chứa authtoken) lưu dạng rõ trong CSDL/sao lưu; đăng ký lại push token của người khác (phải biết token) chuyển chủ token; DNS rebinding giữa lúc kiểm IP và lúc tải (nay lặp mỗi giờ) | Mã hoá `target` bằng Fernet; gắn token với phiên; ghim IP đã kiểm khi kết nối |
| DNS rebinding với nhập .ics | Tên miền đổi IP giữa lúc kiểm tra và lúc tải | Ghim IP đã kiểm tra khi tải |
| Kiểm thử xâm nhập độc lập | Chưa ai ngoài đội soát | Cần trước khi có người dùng thật |

## Checklist trước khi cho người ngoài dùng

- [x] `MSTUDENT_ENV=prod`, `MSTUDENT_SECRET_KEY` ngẫu nhiên ≥ 32 ký tự (`install.sh` tự sinh; đổi khoá = mọi người đăng nhập lại và kết nối lại Gmail)
- [x] HTTPS (Tailscale Funnel) — còn: build app với `MSTUDENT_HTTPS_ONLY=1` cho bản phát hành
- [x] `MSTUDENT_ADMIN_EMAILS` chỉ gồm người trong đội; đã đăng ký sẵn tài khoản admin
- [x] Trần chi phí LLM theo ngày ở server — còn: xác nhận giá gateway và đặt hạn mức ở cả OpenRouter/provider chính
- [x] Sao lưu `mstudent.db` hằng ngày, đã khôi phục thử
- [ ] Thu hồi và tạo lại khóa model nếu từng lộ ra ngoài server (chat, ảnh chụp, log); giữ `OPENAI_API_KEY` và `OPENROUTER_API_KEY` riêng

Ngưỡng Decision và cách rollback: [DECISION_ROUTING.md](DECISION_ROUTING.md). Thông báo/tài liệu là dữ liệu không tin
cậy dù tới từ một nguồn đã OAuth thành công. OAuth chứng minh quyền lấy dữ liệu, không chứng minh nội dung là chỉ dẫn
hợp lệ cho agent. Lỗi auth/network phải xử lý ở connector; không đưa token hoặc thông báo lỗi quyền vào gate để phân loại.
