# Quickstart: Triển khai lên VPS trường

Giả định: Ubuntu/Debian có sudo, ra được Internet. Thay `<user>` bằng tài khoản SSH của bạn.

## 1–3. Cài đặt và chạy dịch vụ (script tự động)

Trên laptop, đóng gói mã nguồn và chép lên VPS (repo private nên VPS không clone trực tiếp):

```bash
git archive --format=tar.gz -o /tmp/mstudent.tgz 001-backend-production backend
scp /tmp/mstudent.tgz bcse-kit:~/
```

Trên VPS:

```bash
rm -rf ~/mstudent-src && mkdir ~/mstudent-src && tar xzf ~/mstudent.tgz -C ~/mstudent-src
sudo bash ~/mstudent-src/backend/deploy/install.sh
```

Lần đầu script tạo `/etc/mstudent.env` (tự sinh `MSTUDENT_SECRET_KEY`) rồi dừng. Điền `OPENAI_API_KEY` và
`MSTUDENT_ADMIN_EMAILS` bằng `sudo nano /etc/mstudent.env`, sau đó chạy lại lệnh `install.sh`. Cập nhật bản mới
cũng dùng đúng hai bước trên; dữ liệu và file cấu hình được giữ nguyên.

Biến tuỳ chọn: `GOOGLE_*`, `MSTUDENT_LLM_DAILY_USD=5`, `MSTUDENT_ALERT_WEBHOOK`.

## 4. HTTPS qua Tailscale Funnel

```bash
curl -fsSL https://tailscale.com/install.sh | sh      # hoặc theo hướng dẫn apt chính thức
sudo tailscale up                                     # mở link in ra để đăng nhập
sudo tailscale funnel --bg 8000
tailscale funnel status                               # ghi lại https://<máy>.<tailnet>.ts.net
```

Kiểm tra từ điện thoại dùng 4G: mở `https://<máy>.ts.net/api/health`.

## 5. Giám sát

UptimeRobot → New monitor → HTTP(s) → `https://<máy>.ts.net/api/health`, chu kỳ 5 phút → thêm email/Telegram
nhận cảnh báo.

## 6. App

```bash
cd mobile
EXPO_PUBLIC_API_URL=https://<máy>.ts.net eas build -p android --profile preview
```

## Khôi phục từ sao lưu

```bash
sudo systemctl stop mstudent
ls /var/backups/mstudent/
sudo -u mstudent cp /var/backups/mstudent/mstudent-YYYYMMDD.db /opt/mstudent/data/mstudent.db
sudo rm -f /opt/mstudent/data/mstudent.db-wal /opt/mstudent/data/mstudent.db-shm
sudo systemctl start mstudent
```

## Lùi về local khi demo

Trên laptop: `cd backend && python run_local.py` → trong app đổi địa chỉ server thành `http://192.168.x.x:8000`.
