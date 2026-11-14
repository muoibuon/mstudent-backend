# Cấu hình Google Cloud (console.cloud.google.com)

MStudent dùng Google Cloud cho **2 việc** — cả hai đều tuỳ chọn, app vẫn chạy với email/mật khẩu nếu chưa cấu hình:

| Việc | Giá trị cho bài thi | Cần gì |
|---|---|---|
| **Đăng nhập bằng Google** | Vào app bằng 1 chạm, không phải nhớ mật khẩu | OAuth client: Web + Android + iOS |
| **Gmail chỉ-đọc** | AI tự đọc email trường → tạo việc. Đây là bằng chứng "vấn đề thật" mạnh nhất | Bật Gmail API + scope `gmail.readonly` |

Không dùng: Gemini (AI chạy bằng OpenAI theo lựa chọn của đội), Google Calendar (để sau cuộc thi).

> Tên menu trong Console có thể thay đổi; các bước dưới đây theo giao diện "Google Auth Platform".

## 1. Tạo project và bật API

1. Vào https://console.cloud.google.com → tạo project `mstudent`.
2. **APIs & Services → Library** → bật lần lượt: **Gmail API**, **Google Classroom API**, và (nếu dùng Gmail báo ngay,
   mục 5) **Cloud Pub/Sub API**.

## 2. Màn hình xin quyền (Google Auth Platform)

1. **Branding**: tên app `MStudent`, email hỗ trợ. **Privacy policy link**: `https://mstudent.tailec1929.ts.net/privacy`
   (trang công khai của backend; đổi theo địa chỉ production nếu khác).
2. **Audience**: loại **External**, trạng thái **Testing**. Thêm email của các thành viên đội và giám khảo (nếu họ thử Gmail) vào **Test users** (tối đa 100).
   - Thêm test user: **Audience → Test users → + Add users** → nhập email Gmail → **Save**. Có hiệu lực ngay.
   - Người không có trong danh sách bấm "Kết nối Gmail" sẽ bị Google từ chối; app hiện thông báo "Gmail đang trong giai
     đoạn thử nghiệm, chỉ mở cho người dùng được mời" và vẫn dùng được các tính năng khác.
3. **Data Access** → Add scopes (đều **chỉ đọc**):
   - `https://www.googleapis.com/auth/gmail.readonly` — Gmail
   - `https://www.googleapis.com/auth/classroom.courses.readonly` — danh sách lớp
   - `https://www.googleapis.com/auth/classroom.coursework.me.readonly` — bài tập + bài nộp của chính mình
   - `https://www.googleapis.com/auth/classroom.announcements.readonly` — thông báo lớp

## 3. Tạo 3 OAuth client (mục Clients)

| Loại | Điền gì | Lấy được gì | Đặt ở đâu |
|---|---|---|---|
| **Web application** | Tên bất kỳ. Không cần redirect URI | Client ID + Client secret | `.env`: `GOOGLE_WEB_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| **Android** | Package `vn.muoibuon.mstudent` + **SHA-1** của khoá ký | (không cần chép gì) | Chỉ cần tồn tại trong cùng project |
| **iOS** | Bundle ID `vn.muoibuon.mstudent` | iOS Client ID | `.env`: `GOOGLE_IOS_CLIENT_ID`; khi build app: `GOOGLE_IOS_URL_SCHEME` |

**Lấy SHA-1 cho Android** (phải đúng khoá đã ký bản APK cài trên máy demo):

```bash
# Bản build local (expo run:android) — khoá debug
keytool -list -v -keystore mstudent-app/android/app/debug.keystore -alias androiddebugkey -storepass android | grep SHA1
# Bản build bằng EAS
npx eas-cli@latest credentials   # chọn Android → xem SHA-1
```

Sai SHA-1 là lỗi phổ biến nhất: nút Google báo `DEVELOPER_ERROR`.

**iOS URL scheme** = iOS Client ID đảo ngược. Ví dụ client ID `1234-abc.apps.googleusercontent.com` →

```bash
GOOGLE_IOS_URL_SCHEME=com.googleusercontent.apps.1234-abc npx expo prebuild --clean
```

## 4. Điền `.env`

```
GOOGLE_WEB_CLIENT_ID=1234-web.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_IOS_CLIENT_ID=1234-ios.apps.googleusercontent.com
```

Khởi động lại `python run_local.py` → dòng "Google Sign-In: bật". App tự lấy client ID từ `/api/public-config`,
không cần build lại app khi đổi client ID (trừ URL scheme của iOS).

Trên máy chủ production: ghi 3 dòng trên vào `/etc/mstudent.env` rồi `sudo systemctl restart mstudent`. Sau khi người
dùng bấm kết nối Google trong app, nguồn **Gmail** (và **Classroom** nếu đã cấp quyền) tự xuất hiện ở màn hình
**Nguồn tự động** và máy chủ tự đồng bộ — không cần bấm "Đồng bộ" nữa.

## 5. Gmail báo ngay qua Pub/Sub (tuỳ chọn, ~15 phút)

Không làm mục này thì máy chủ vẫn kiểm tra Gmail mỗi 2 phút (email → việc ≤ 3 phút). Làm thì còn khoảng 1 phút.

1. **Pub/Sub → Topics → Create topic**: ID `gmail-mstudent`, bỏ chọn "Add a default subscription".
2. Mở topic → **Permissions → Add principal**: `gmail-api-push@system.gserviceaccount.com`, vai trò **Pub/Sub Publisher**
   (để Gmail được đăng vào topic).
3. **IAM & Admin → Service Accounts → Create**: tên `mstudent-push`, không cần cấp vai trò nào.
4. **Pub/Sub → Subscriptions → Create subscription**:
   - Topic: `gmail-mstudent`; Delivery type: **Push**
   - Endpoint URL: `https://mstudent.tailec1929.ts.net/api/hooks/gmail`
   - Bật **Enable authentication**, service account: `mstudent-push@<project-id>.iam.gserviceaccount.com`,
     Audience: để trống (mặc định = Endpoint URL)
   - Acknowledgement deadline: 10 giây; các mục khác để mặc định.
5. Thêm vào `/etc/mstudent.env` rồi `sudo systemctl restart mstudent`:
   ```
   MSTUDENT_PUBLIC_URL=https://mstudent.tailec1929.ts.net
   MSTUDENT_PUBSUB_TOPIC=projects/<project-id>/topics/gmail-mstudent
   MSTUDENT_PUBSUB_PUSH_SA=mstudent-push@<project-id>.iam.gserviceaccount.com
   ```
6. Kiểm tra: gửi một email thông báo tới hộp thư đã kết nối → trong ~1 phút có việc mới. Webhook kiểm chữ ký Google:
   `curl -X POST https://mstudent.tailec1929.ts.net/api/hooks/gmail` (không chữ ký) phải trả **403**.

Nếu Pub/Sub báo lỗi xác thực khi gửi (project tạo trước 4/2021): cấp vai trò **Service Account Token Creator** trên
`mstudent-push` cho `service-<project-number>@gcp-sa-pubsub.iam.gserviceaccount.com`.

## 6. Luồng hoạt động và lý do bảo mật

```
Điện thoại                         Backend                              Google
   │ Google Sign-In (native) ─────────────────────────────────────────────▶ │
   │ ◀──────────── ID token (+ server auth code nếu xin Gmail) ──────────── │
   │ POST /api/auth/google ─────────▶ kiểm chữ ký, aud, iss, exp           │
   │                                  đổi auth code + CLIENT SECRET ──────▶ │
   │                                  ◀──────────── refresh token ───────── │
   │ ◀── token của MStudent ───────── lưu refresh token đã MÃ HOÁ          │
   │ POST /api/google/gmail/sync ───▶ đọc thư mới ────────────────────────▶ │
   │ ◀── việc mới ─────────────────── Triage → Extractor → Planner         │
```

- **Client secret và refresh token của Google không bao giờ nằm trong app** — app chỉ cầm mã dùng một lần.
- Server chỉ chấp nhận ID token có `aud` thuộc các client ID của mình, do Google ký, email đã xác minh.
- Quyền xin là **chỉ đọc**; MStudent không gửi, xoá hay sửa thư. Người dùng ngắt kết nối trong Cài đặt → server thu hồi token ở Google.

## 7. Giới hạn cần biết (ảnh hưởng tới demo và mở rộng)

- **Testing mode**: quyền Gmail của test user **hết hạn sau 7 ngày** kể từ lúc đồng ý → kết nối lại Gmail trong tuần diễn ra demo. Riêng đăng nhập Google (chỉ email/hồ sơ) không bị giới hạn này và không cần nằm trong danh sách test user.
- Người dùng sẽ thấy cảnh báo "Google chưa xác minh ứng dụng này" khi cấp quyền Gmail → bấm *Nâng cao → Tiếp tục*.
- **Phát hành công khai**: quyền đọc Gmail thuộc nhóm *restricted scope*; cần Google xác minh app và đánh giá bảo mật trước khi mở cho người dùng bất kỳ. Đây là rào cản thật — nêu trong phần "Khả năng mở rộng" kèm phương án (xem `docs/PITCH.md`).

Nguồn: [Manage App Audience — Google Cloud Help](https://support.google.com/cloud/answer/15549945) ·
[OAuth production readiness — Google for Developers](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)
