# Runbook demo — bám theo thang điểm

| Tiêu chí | Điểm | Hệ thống đáp ứng bằng gì | Việc đội phải tự làm |
|---|---|---|---|
| 1. Demo AI trên **điện thoại thật** | 40 | App native (không phải trình duyệt); đóng hẳn → mở lại vào thẳng app nhờ refresh token trong Keychain/Keystore; AI gọi thật qua server; nhãn "AI trực tiếp" + nút "Kiểm tra AI" | Build và cài app lên máy; có `OPENAI_API_KEY`; mạng ổn định |
| 2. Vấn đề thật của người dùng | 35 | Gmail thật → việc; chia sẻ từ Zalo; thẻ "MStudent đã giúp bạn" (số tin đã đọc, tin nhiễu đã lọc, lần đổi hạn bắt kịp) | **Bằng chứng**: khảo sát + số liệu dùng thật (xem `PITCH.md`) |
| 3. Khả năng mở rộng thị trường | 25 | Nhiều người dùng, mỗi người dữ liệu riêng; đăng ký mở; số người dùng ở `/api/admin/overview` | Có người dùng thật trước ngày thi; kế hoạch tiếp cận (xem `PITCH.md`) |

> **0 điểm tiêu chí 1** nếu: không mở lại được app, AI không chạy trực tiếp, hoặc chỉ demo bằng trình duyệt/giả lập/ảnh/video.
> Vì vậy: **không demo bằng Expo web, không bằng simulator, không để server ở chế độ luật.**

## Production (máy chủ thật)

- **Địa chỉ cho app**: `https://mstudent.tailec1929.ts.net` (Tailscale Funnel, HTTPS hợp lệ, dùng được từ 4G).
- Máy: Azure for Students, **Japan East**, B2ts_v2 (2 vCPU, 1 GiB + swap 2 GB), Ubuntu 24.04, user riêng.
  SSH: `ssh -i ~/.ssh/<khoá-ssh>.pem <user>@<IP-máy-chủ>`. Không dùng region East Asia: OpenAI chặn Hong Kong.
- Cấu hình: `/etc/mstudent.env` (600). Dịch vụ: `sudo systemctl status mstudent`, log `sudo journalctl -u mstudent -n 50`.
- Cập nhật code từ laptop: `rsync` thư mục `` lên `~/mstudent/` rồi `sudo bash deploy/install.sh`.
- Chế độ AI: `curl https://mstudent.tailec1929.ts.net/api/health` phải ra `"mode":"llm"` (đã bật 2026-11-13; eval LLM
  trên VM: relevant 12/12, category 9/9, due 8/8, course 2/2). Đường lui khi OpenAI lỗi: đặt `MSTUDENT_OFFLINE=1` trong
  `/etc/mstudent.env` rồi `sudo systemctl restart mstudent` (app sẽ hiện rõ là chế độ luật).
- Kiểm tra trước giờ demo: `/api/health` qua địa chỉ trên; `tailscale funnel status` trên VM phải ghi `Funnel on`.
- **Số liệu cho pitch**: đăng nhập web console bằng tài khoản admin → thẻ **📊 Số liệu** (người dùng, hoạt động 7 ngày,
  thông báo đã xử lý, việc đã tạo, chi phí AI, độ trễ). API: `GET /api/admin/stats`.
- Đường lui: laptop chạy `python run_local.py` (mục B).

## A. Trước ngày thi (làm một lần)

1. **Backend**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt && cp .env.example .env
   ```
   Điền `OPENAI_API_KEY`, `MSTUDENT_ADMIN_EMAILS`, và (nếu dùng Google) 3 biến `GOOGLE_*` theo `GOOGLE_CLOUD_SETUP.md`.
   **Bỏ trống `MSTUDENT_NOW`** khi demo bằng dữ liệu thật.
2. **Kiểm tra AI thật**: `python -m eval.run_eval` → phải in `Chế độ: llm`. Ghi lại điểm để đưa vào slide.
3. **Build app và cài lên CẢ HAI máy** (Share từ Zalo và Google Sign-In cần bản build, Expo Go không đủ):
   ```bash
   cd mobile && npm install
   # Android: ra file APK cài thẳng
   npx eas-cli@latest build --profile preview --platform android
   # iOS: cắm cáp, cần Mac + Xcode (bản miễn phí hết hạn sau 7 ngày → build lại sát ngày thi)
   GOOGLE_IOS_URL_SCHEME=com.googleusercontent.apps.<...> npx expo prebuild --clean
   npx expo run:ios --device --configuration Release
   ```
   Bản **Release/preview** chạy độc lập, không cần Metro. Bản development cần máy tính chạy `expo start` — đừng dùng để demo.
4. **Tạo tài khoản demo** trên từng máy, kết nối Gmail (trong vòng 7 ngày trước demo), chia sẻ thử một tin từ Zalo.
5. **Cho 5–10 bạn dùng thật vài ngày** → có số liệu cho tiêu chí 2 và 3.

## B. Mạng trong phòng thi (rủi ro lớn nhất khi backend chạy localhost)

Điện thoại phải gọi được máy tính. Thứ tự ưu tiên:

| Cách | Làm thế nào | Khi nào dùng |
|---|---|---|
| **Hotspot của điện thoại demo** | Bật hotspot, máy tính vào hotspot đó, `python run_local.py`, nhập địa chỉ nó in ra | Mặc định — không phụ thuộc Wi-Fi hội trường (Wi-Fi công cộng thường chặn thiết bị gọi nhau) |
| **Tunnel HTTPS** | `cloudflared tunnel --url http://localhost:8000` → nhập link `https://….trycloudflare.com` | Cần HTTPS, hoặc 2 máy khác mạng. Phụ thuộc Internet |
| Wi-Fi chung | Cùng Wi-Fi, nhập IP LAN | Chỉ khi đã thử được trước |

iPhone lần đầu sẽ hỏi quyền "Tìm thiết bị trong mạng cục bộ" → **Cho phép** (làm trước, đừng để lên sân khấu mới bấm).
Máy tính: tắt chế độ ngủ, cho phép Python qua tường lửa.

## C. 30 phút trước giờ lên

- [ ] Production: `curl https://mstudent.tailec1929.ts.net/api/health` → `"mode":"llm"`. Nếu `offline` → xem mục Production.
  (Chỉ khi lùi về laptop: `python run_local.py` → dòng `AI: LLM trực tiếp (…)`.)
- [ ] Trên điện thoại: Cài đặt → **Kiểm tra AI ngay** → `✓ AI trả lời sau … ms`.
- [ ] Góc phải tab Trợ lý hiện chấm xanh **AI trực tiếp**.
- [ ] Đóng hẳn app (vuốt khỏi đa nhiệm) → mở lại → vào thẳng, không hỏi đăng nhập. Làm 2 lần.
- [ ] Chia sẻ một tin từ Zalo → MStudent → ra việc đúng ngày.
- [ ] Cài đặt → Gửi thông báo thử → thấy thông báo.
- [ ] Sạc pin, tắt Không làm phiền, tăng độ sáng, bật chiếu màn hình (AirPlay / scrcpy) nếu ban tổ chức cho.
- [ ] Mở sẵn web console `http://localhost:8000` trên máy tính ở tab **Agent trace** (để chiếu "bên trong AI").

## D. Kịch bản 3 phút trên điện thoại thật

| Giây | Làm gì | Nói gì | Chứng minh |
|---|---|---|---|
| 0–25 | Giơ điện thoại, mở Zalo nhóm lớp thật | "Tuần trước lớp mình có N tin trong nhóm, chỉ M tin là việc phải làm. X/Y bạn mình khảo sát từng lỡ hạn vì thế." | Tiêu chí 2: người dùng + bằng chứng |
| 25–45 | **Vuốt đóng hẳn MStudent → mở lại** | "Đây là app cài trên máy thật, mở lại vẫn nguyên phiên." | Tiêu chí 1 |
| 45–90 | Trong Zalo: giữ một tin thật → Chia sẻ → MStudent → *Phân tích bằng agent* | "AI đọc tin, hiểu 'thứ 6 tuần sau', tạo việc có hạn. Dòng dưới là 3 agent vừa chạy, chế độ AI trực tiếp." | Tiêu chí 1: AI chạy trực tiếp |
| 90–120 | Mời giám khảo đọc một thông báo bất kỳ → gõ vào Trợ lý | "Không phải kịch bản dựng sẵn." | Tiêu chí 1 |
| 120–145 | Cài đặt → **Quét Gmail** → thẻ "MStudent đã giúp bạn" | "Đọc N thư thật, lọc K thư nhiễu, bắt được 1 lần đổi hạn." | Tiêu chí 2: AI giúp trực tiếp |
| 145–180 | Slide cuối | Người dùng đầu tiên, số người đang dùng, đường mở rộng | Tiêu chí 3 |

### D2. Biến thể "tự động hoàn toàn" (002-auto-ingest) — thay đoạn 120–145 giây

Chuẩn bị trước giờ lên (đã kết nối Google trên tài khoản demo; bảng lớp thử đã thêm ở màn hình Nguồn tự động):

| Giây | Làm gì | Nói gì | Chứng minh |
|---|---|---|---|
| 120–130 | Đặt điện thoại **Android** lên bàn, app **đã đóng**. Trên laptop: thêm một dòng vào Google Sheet của lớp ("OOP · Nộp bài tập lớn · thứ 7 23h59") hoặc gửi một email thông báo tới Gmail demo | "Lớp trưởng vừa thêm deadline vào bảng chung / thầy vừa gửi mail. Không ai chạm vào MStudent." | Tiêu chí 2: dữ liệu thật, đa nguồn |
| 130–140 | Bấm **Đồng bộ ngay** trên web console hoặc chờ (Gmail ≤ 1–3 phút); Android hiện thông báo "MStudent: việc mới …" | "Máy chủ tự đọc nguồn, AI tạo việc, điện thoại nhận thông báo khi app đang đóng." | Tiêu chí 1 + 3 |
| 140–145 | Mở app → việc mới có nhãn nguồn "Bảng lớp" / "Email"; Classroom: hạn đúng tới từng phút, không qua AI | "Một bài xuất hiện ở nhiều nguồn vẫn chỉ là một việc." | Tiêu chí 3: mở rộng, không trùng |

Tài liệu trong email (US7): gửi email "Lịch thi học kỳ" kèm PDF lịch thi → việc thi lấy đúng giờ trong PDF, ghi chú
tóm tắt tài liệu; link Google Docs/Sheets công khai trong email cũng được đọc.

iPhone (bản ký miễn phí): mở app là thấy việc mới — không có thông báo đẩy khi app đóng (giới hạn của Apple).
Kiểm tra trước: màn hình Nguồn tự động không có dòng lỗi đỏ; Admin → Số liệu: chi phí AI hôm nay còn xa trần.

### D3. Biến thể "sự kiện của trường" (003-event-rsvp) — 20 giây, chèn sau D hoặc D2

Chuẩn bị: tài khoản demo đã khai trường + ngành (Cài đặt → Hồ sơ học tập), có MSSV và lớp; một Google Form công khai
có câu "Họ và tên", "MSSV", "Email", "Lớp".

| Làm gì | Nói gì | Chứng minh |
|---|---|---|
| Dán (hoặc gửi mail) thông báo: "Seminar AI và lập trình 14h thứ 6 tại phòng 501, hạn đăng ký thứ 4, đăng ký tại <link form>" | "Trường gửi rất nhiều sự kiện. MStudent không nhét hết vào lịch mà hỏi." | Tiêu chí 2 |
| Tab Việc → khối **SỰ KIỆN MỚI**: thẻ "Rất hợp ngành" + lý do nhắc tên ngành; bấm **Tham gia** | "AI xét theo ngành của tôi: sự kiện này có ích gì. Một chạm là vào lịch, có nhắc trước 1 ngày và 2 giờ." | Tiêu chí 1 |
| Bấm **Đăng ký (điền sẵn N câu)** → form mở với họ tên, MSSV, email, lớp đã điền | "Form đã điền sẵn từ hồ sơ trên máy; tôi tự xem lại và tự bấm Gửi — app không gửi thay." | Tiêu chí 2 |

Đổi ngành trong Hồ sơ học tập (vd. sang "Nhật Bản học") → cùng sự kiện đổi thành "Ít liên quan": mức phù hợp tính lại theo
ngành. AI tắt → thẻ ghi "Bộ luật (offline)". Bấm **Không** → sự kiện biến khỏi danh sách, xem lại ở "Xem sự kiện đã bỏ qua".

## E. Khi có sự cố

| Hiện tượng | Xử lý trong 20 giây |
|---|---|
| App báo "Không kết nối được" | Kiểm tra máy tính còn trong hotspot; Cài đặt hiện địa chỉ server — so với địa chỉ `run_local.py` in ra (IP đổi khi vào lại mạng). Đăng xuất → nhập địa chỉ mới |
| Chấm vàng "AI chưa bật" | Server thiếu key hoặc `MSTUDENT_OFFLINE=1` → sửa `.env`, chạy lại `run_local.py` |
| Kết quả ghi "bộ luật (AI chưa bật)" dù có key | LLM lỗi (hết credit/mạng) và hệ thống đã tự chuyển sang luật. Xem lỗi ở web console → Agent trace. **Nói thật với giám khảo**, đừng gọi kết quả đó là AI |
| Gmail báo hết hạn quyền | Quá 7 ngày ở Testing mode → Ngắt → Kết nối lại |
| Bị đẩy ra màn hình đăng nhập | Đăng nhập lại (mật khẩu demo ghi sẵn); kiểm tra đồng hồ máy tính và `.secret_key` không bị xoá |
| Mất hết mạng | Vẫn mở app được, thấy việc đã lưu và nhận nhắc việc; nói rõ phần AI cần mạng |
