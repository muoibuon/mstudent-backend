#!/usr/bin/env bash
# Bật Đăng nhập Google + Gmail + Classroom trên máy chủ. Chạy TRÊN MÁY CHỦ:
#   sudo bash ~/mstudent/backend/deploy/set_google_oauth.sh
# Cần 3 giá trị từ Google Cloud Console → Google Auth Platform → Clients (xem docs/GOOGLE_CLOUD_SETUP.md mục 1–3):
#   Web client ID, Web client secret (GOCSPX-…), iOS client ID. Client secret gõ/dán ở chế độ ẩn, không hiện trên màn hình,
#   không vào lịch sử lệnh; ghi vào /etc/mstudent.env (quyền 600). Để trống Web client ID = tắt Google.
set -euo pipefail
ENV_FILE=${MSTUDENT_ENV_FILE:-/etc/mstudent.env}
[ -f "$ENV_FILE" ] || { echo "Không thấy $ENV_FILE" >&2; exit 1; }
ID_RE='^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$'

read -r -p "Web client ID (…apps.googleusercontent.com, trống = tắt Google): " WEB
SECRET=""; IOS=""
if [ -n "$WEB" ]; then
  [[ "$WEB" =~ $ID_RE ]] || { echo "Web client ID không đúng dạng" >&2; exit 1; }
  read -r -s -p "Web client secret (GOCSPX-…, ẩn): " SECRET; echo
  [[ "$SECRET" =~ ^GOCSPX-[A-Za-z0-9_-]{10,}$ ]] || { echo "Client secret không đúng dạng" >&2; exit 1; }
  read -r -p "iOS client ID (trống nếu chưa tạo): " IOS
  [ -z "$IOS" ] || [[ "$IOS" =~ $ID_RE ]] || { echo "iOS client ID không đúng dạng" >&2; exit 1; }
fi

TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
grep -vE '^(GOOGLE_WEB_CLIENT_ID|GOOGLE_CLIENT_SECRET|GOOGLE_IOS_CLIENT_ID)=' "$ENV_FILE" > "$TMP" || true
printf 'GOOGLE_WEB_CLIENT_ID=%s\nGOOGLE_CLIENT_SECRET=%s\nGOOGLE_IOS_CLIENT_ID=%s\n' "$WEB" "$SECRET" "$IOS" >> "$TMP"
cat "$TMP" > "$ENV_FILE"   # ghi đè tại chỗ: giữ nguyên chủ sở hữu và quyền 600
systemctl restart mstudent
for _ in $(seq 1 30); do
  if OUT=$(curl -fsS -m 3 http://127.0.0.1:8000/api/public-config 2>/dev/null); then echo "$OUT"; break; fi; sleep 1
done
echo "Xong. \"enabled\":true và \"gmail\":true nghĩa là đăng nhập Google và Gmail/Classroom đã bật."
[ -z "$IOS" ] || echo "Build lại app iOS với GOOGLE_IOS_URL_SCHEME=com.googleusercontent.apps.${IOS%%.apps.googleusercontent.com}"
