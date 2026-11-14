# Research: Backend production

## R1. Đưa dịch vụ ra Internet có HTTPS (VPS không IP công khai, không tên miền)

- **Decision**: Tailscale Funnel → `https://<máy>.<tailnet>.ts.net`, chuyển tiếp tới `127.0.0.1:8000`.
- **Rationale**: Miễn phí, địa chỉ cố định (không phải build lại app), chứng chỉ TLS tự động, chỉ cần VPS ra
  được Internet. Chạy như dịch vụ hệ thống nên tự lên lại khi VPS khởi động lại.
- **Alternatives**: Cloudflare quick tunnel (miễn phí nhưng địa chỉ ngẫu nhiên, đổi mỗi lần khởi động lại);
  Cloudflare named tunnel (cần tên miền); ngrok free (có 1 tên miền tĩnh nhưng giới hạn ~20k request/tháng và
  trang cảnh báo trên trình duyệt); Caddy + Let's Encrypt (cần IP công khai và tên miền).
- **Cần kiểm tra khi triển khai**: mạng trường có chặn kết nối ra ngoài của Tailscale không. Nếu bị chặn thì
  lùi về Cloudflare quick tunnel, nhập địa chỉ tay trong app (FR-007 vẫn cho phép).

## R2. IP thật của client sau đường hầm

- **Decision**: Thêm cờ `MSTUDENT_TRUST_PROXY=1`. Khi bật **và** kết nối đến từ `127.0.0.1`/`::1`, `client_ip()`
  lấy địa chỉ đầu tiên trong `X-Forwarded-For`. Ngược lại giữ cách hiện tại. Uvicorn chạy với
  `--no-proxy-headers` (mặc định uvicorn tự tin proxy 127.0.0.1, sẽ trùng logic).
- **Rationale**: Sau đường hầm, mọi kết nối đều đến từ localhost, nên giới hạn đăng nhập theo IP sẽ gộp mọi
  người làm một và chặn nhầm cả lớp.
- **Cần kiểm tra**: Funnel có đặt `X-Forwarded-For` không. Nếu không có header thì vẫn rơi về IP kết nối:
  giới hạn theo IP yếu đi, nhưng giới hạn theo tài khoản vẫn còn.

## R3. Bộ đếm giới hạn tần suất bền vững

- **Decision**: Bảng SQLite `rate_counters(key, window_start, count)` với cửa sổ cố định. Dùng một câu
  `INSERT … ON CONFLICT DO UPDATE` trong transaction, theo `config.utcnow()`.
- **Rationale**: Không thêm Redis (theo Clarification Q3, 1 tiến trình là đủ), bộ đếm còn sau khi khởi động
  lại, và nhiều tiến trình sau này vẫn dùng chung được. Cửa sổ cố định đơn giản hơn cửa sổ trượt; sai số ở
  biên cửa sổ chấp nhận được.
- **Giữ nguyên**: giao diện `limiter.hit(key, limit, window_s)` và `reset()` để test cũ không đổi.

## R4. Đo chi phí LLM và trần theo ngày

- **Decision**: Sau mỗi `Runner.run`, đọc `result.context_wrapper.usage` (input/output tokens) và ghi vào
  `llm_usage`. Chi phí = tokens × đơn giá từ cấu hình (`MSTUDENT_PRICE_IN_PER_M`, `MSTUDENT_PRICE_OUT_PER_M`
  USD/1 triệu token). `budget.llm_allowed()` = `llm_enabled()` và chi phí hôm nay (+07:00) < trần
  (`MSTUDENT_LLM_DAILY_USD`, mặc định 5).
- **Rationale**: Không phụ thuộc API billing của OpenAI (có độ trễ, cần khoá admin). Thay mọi chỗ gọi
  `llm_enabled()` trong luồng xử lý (orchestrator, assistant, digest) bằng `llm_allowed()`. `/api/health`
  vẫn báo `llm_enabled()` để app hiện đúng trạng thái.
- **Cảnh báo**: lần đầu vượt 80% và 100% trong ngày thì POST tới `MSTUDENT_ALERT_WEBHOOK` (Discord/Telegram,
  tuỳ chọn). Cờ "đã báo" lưu trong bảng `settings` theo ngày, chạy nền và không chặn yêu cầu.
- **Cần kiểm tra**: tên thuộc tính usage trong phiên bản `openai-agents` đang cài. Nếu không đọc được thì ước
  lượng theo độ dài ký tự (≈ 4 ký tự/token) và ghi chú trong log.

## R5. Thời hạn chờ LLM

- **Decision**: Bọc mọi `Runner.run` bằng `asyncio.wait_for(..., timeout=MSTUDENT_LLM_TIMEOUT_S)`, mặc định
  25 giây. Hết hạn thì ném `TimeoutError`; nhánh `except Exception` có sẵn trong orchestrator sẽ chuyển sang
  bộ luật. Assistant cũng được bọc như vậy và trả lời rơi về chế độ offline sẵn có.

## R6. Kiểm tra cấu hình khi khởi động ở prod

- **Decision**: Hàm `config.check_prod_config()` được gọi khi app khởi động nếu `is_prod()`. Bắt buộc có:
  `MSTUDENT_SECRET_KEY` (≥ 32 ký tự), `OPENAI_API_KEY`, `MSTUDENT_ADMIN_EMAILS`. Thiếu thì `RuntimeError`
  liệt kê **tên** biến, không in giá trị. Google là tuỳ chọn (chỉ cảnh báo). `MSTUDENT_NOW` bị cấm ở prod.

## R7. Sao lưu

- **Decision**: `deploy/backup.py` dùng `sqlite3.Connection.backup()` (an toàn khi đang chạy WAL), ghi vào
  `/var/backups/mstudent/mstudent-YYYYMMDD.db` (thư mục quyền 700, file 600), xoá bản cũ hơn 7 ngày. Chạy bằng
  `systemd timer` lúc 03:00. Khôi phục: dừng dịch vụ, chép bản sao lưu đè lên, khởi động lại (`quickstart.md`).
- **Mã hoá (FR-010)**: chưa xác nhận ổ VPS có mã hoá hay không. Tối thiểu là quyền file 600 và người dùng hệ
  thống riêng `mstudent`. Ghi nhận vào SECURITY.md.

## R8. Giám sát

- **Decision**: UptimeRobot (gói miễn phí, kiểm tra mỗi 5 phút) gọi `GET https://<địa chỉ>/api/health`, cảnh
  báo qua email/app của UptimeRobot. Không cần code.

## R9. Mobile: địa chỉ mặc định và chính sách HTTP

- **Decision**: Bản build đặt `EXPO_PUBLIC_API_URL=https://<máy>.ts.net`, điền sẵn ở màn hình đăng
  nhập và vẫn sửa được. **Không** bật `MSTUDENT_HTTPS_ONLY` (để còn lùi về `http://192.168.x.x` khi demo).
  Thay vào đó, `lib/url.ts` chỉ chấp nhận `http://` khi host là localhost hoặc dải IP riêng (10/8,
  172.16/12, 192.168/16); các host khác buộc `https://`.
- **Rationale**: Thoả cùng lúc FR-002 (token không đi qua HTTP trên Internet) và FR-007 (lùi về local).

## R10. Gmail chỉ cho test user

- **Decision**: Không cần code phía server: Google tự từ chối người không có trong danh sách test user ở màn
  hình đồng ý. Phía app: bắt lỗi `access_denied` và hiện câu "Gmail đang trong giai đoạn thử nghiệm, chỉ mở
  cho người dùng được mời". Thêm test user trong Google Cloud Console (`docs/GOOGLE_CLOUD_SETUP.md`).

## R11. Thông tin VPS đã xác nhận (2026-11-13)

- Ubuntu 24.04.4 LTS x86_64, sudo không cần mật khẩu, Python 3.12.3, SQLite 3.45.1, Docker có sẵn.
- 2 vCPU, RAM 1,9 GB, ổ `/` ext4 19 GB (trống 5,2 GB). Ổ **không mã hoá** (không LUKS).
- IP nội bộ `192.168.2.216`, chỉ vào được qua máy trung gian `ssh-lab`; ra Internet qua NAT. Không có IP công
  khai, nên **bắt buộc dùng đường hầm**. UDP tới Tailscale DERP gửi được.
- Đã xác nhận ra Internet (T001): pypi.org 200, api.openai.com 421 (tới được), controlplane.tailscale.com 302.
- FR-010: vì ổ không mã hoá, dùng người dùng hệ thống `mstudent`, thư mục dữ liệu và sao lưu quyền 700, file
  600. Ghi rõ hạn chế này trong `docs/SECURITY.md`.
- Bản sao lưu: CSDL dự kiến < 50 MB, 7 bản < 350 MB, vừa với 5,2 GB còn trống.

## R12. VM Azure for Students thử nghiệm (2026-11-13)

- Azure East Asia (Hong Kong), Standard_B2ats_v2 (2 vCPU, 1 GiB + swap 2 GB), Ubuntu 24.04.5, StandardSSD
  (Azure tự mã hoá khi lưu). Gói Students không cho B1s ở East Asia.
- T001: pypi.org 200, controlplane.tailscale.com 302, **api.openai.com 403
  `unsupported_country_region_territory`**: OpenAI chặn Hong Kong ⇒ VM này chỉ chạy được `MSTUDENT_OFFLINE=1`.
- Gói Students chỉ cho 5 region: eastasia, indonesiacentral, indiasouthcentral, malaysiawest, japaneast.
  ⇒ **Chọn Japan East** (B2ts_v2; B2ats_v2/B1s không có), IP <IP-máy-chủ>, user riêng. VM Hong Kong bỏ.
- Japan East, T001: pypi 200, OpenAI tới được (trả lỗi khoá, không chặn vùng), Tailscale 302.
- `install.sh` chạy ở `MSTUDENT_OFFLINE=1` (chưa có khoá OpenAI): `/api/health` ok.
- T029: sao lưu bằng `mstudent-backup.service` rồi khôi phục theo quickstart: bản ghi tạo sau sao lưu biến mất, bản
  ghi trước còn; dữ liệu thử đã xoá. Timer chạy 20:00 UTC = 03:00 +07.
- T030: Tailscale 1.104.7 (cài từ kho apt chính thức), Funnel `https://mstudent.tailec1929.ts.net` → 127.0.0.1:8000.
  Lần đầu cấp chứng chỉ ACME mất ~1 phút. `/api/health` 200, `/privacy` 200 qua Internet.
- T031: Funnel gửi `X-Forwarded-For`; audit `login_failed` ghi đúng IPv6 công khai của laptop (không phải 127.0.0.1).
- T041 (2026-11-13, `deploy/smoke_load.py`, 30 đồng thời × 3 lượt `GET /api/tasks`): trên VM gọi 127.0.0.1 p95 86 ms;
  từ VM qua Funnel p95 103 ms; từ laptop qua 4G p95 6,7 s (nghẽn đường lên của một máy mở 30 kết nối, 1 yêu cầu đơn
  ≈ 0,45 s) ⇒ SC-003 đạt ở phía server. 0 lỗi; tài khoản thử tự xoá. pytest 65/65, ruff sạch, eval offline
  relevant 100% / category 100% / due 88% / course 100%; mobile test 9/9, typecheck, lint đều qua.
- T042: Funnel **ghi đè** `X-Forwarded-For` (gửi `1.2.3.4` giả → audit ghi IP thật) ⇒ không giả được IP qua Funnel.
