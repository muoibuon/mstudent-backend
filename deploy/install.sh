#!/usr/bin/env bash
# Cài hoặc cập nhật MStudent backend trên VPS Ubuntu/Debian. Chạy lại bao nhiêu lần cũng được.
#
#   sudo bash backend/deploy/install.sh        (chạy từ thư mục gốc của mã nguồn đã giải nén)
#
# Lần đầu: script tạo /etc/mstudent.env (tự sinh khoá ký) rồi dừng để bạn điền OPENAI_API_KEY và
# MSTUDENT_ADMIN_EMAILS. Điền xong chạy lại script để khởi động dịch vụ.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"          # thư mục backend/ của mã nguồn
APP=/opt/mstudent
ENV_FILE=/etc/mstudent.env

echo "==> Gói hệ thống"
apt-get update -qq
apt-get install -y -qq python3-venv sqlite3 rsync >/dev/null

echo "==> Người dùng và thư mục"
id mstudent >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin mstudent
install -d -o mstudent -g mstudent -m 755 "$APP" "$APP/app"
install -d -o mstudent -g mstudent -m 700 "$APP/data" /var/backups/mstudent

echo "==> Mã nguồn → $APP/app/backend"
rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.db*' --exclude .env --exclude .secret_key \
  "$SRC/" "$APP/app/backend/"
chown -R mstudent:mstudent "$APP/app"

echo "==> Thư viện Python"
[ -x "$APP/venv/bin/python" ] || sudo -u mstudent python3 -m venv "$APP/venv"
sudo -u mstudent "$APP/venv/bin/pip" install -q --upgrade pip
sudo -u mstudent "$APP/venv/bin/pip" install -q -r "$APP/app/backend/requirements.txt"

echo "==> Cấu hình"
if [ ! -f "$ENV_FILE" ]; then
  install -o mstudent -g mstudent -m 600 "$SRC/deploy/mstudent.env.example" "$ENV_FILE"
  KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i "s|^MSTUDENT_SECRET_KEY=.*|MSTUDENT_SECRET_KEY=$KEY|" "$ENV_FILE"
  echo "    Đã tạo $ENV_FILE và tự sinh MSTUDENT_SECRET_KEY."
fi
chown mstudent:mstudent "$ENV_FILE"; chmod 600 "$ENV_FILE"

echo "==> Dịch vụ systemd"
install -m 644 "$SRC/deploy/mstudent.service" "$SRC/deploy/mstudent-backup.service" \
  "$SRC/deploy/mstudent-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q mstudent mstudent-backup.timer

missing=""
grep -Eq "^MSTUDENT_ADMIN_EMAILS=.+" "$ENV_FILE" || missing="$missing MSTUDENT_ADMIN_EMAILS"
grep -Eq "^(OPENAI_API_KEY=.+|MSTUDENT_OFFLINE=1)" "$ENV_FILE" || missing="$missing OPENAI_API_KEY(hoặc MSTUDENT_OFFLINE=1)"
if [ -n "$missing" ]; then
  echo
  echo "!! Chưa khởi động: còn thiếu trong $ENV_FILE:$missing"
  echo "   Mở file:  sudo nano $ENV_FILE   → điền → lưu → chạy lại:  sudo bash $0"
  exit 0
fi

systemctl restart mstudent
systemctl start mstudent-backup.timer
echo "==> Kiểm tra"
ok=""
for _ in $(seq 1 15); do  # khởi động có thể mất vài giây (nạp thư viện AI)
  sleep 1
  if curl -fsS --max-time 5 http://127.0.0.1:8000/api/health; then ok=1; break; fi
done
if [ -n "$ok" ]; then
  echo; echo "OK: backend đang chạy ở 127.0.0.1:8000"
else
  echo "!! Backend chưa trả lời. Xem log:  sudo journalctl -u mstudent -n 40 --no-pager"; exit 1
fi
