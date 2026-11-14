#!/usr/bin/env bash
# Bật AI lọc (Google Gemini Decision) trên máy chủ. Chạy TRÊN MÁY CHỦ:  sudo bash backend/deploy/set_gemini_key.sh
# Khoá được gõ/dán ở chế độ ẩn (không hiện trên màn hình, không vào lịch sử lệnh), ghi vào /etc/mstudent.env (quyền 600).
# Lấy khoá: https://aistudio.google.com/apikey . Tắt lại: chạy script và để trống khoá.
set -euo pipefail
ENV_FILE=${MSTUDENT_ENV_FILE:-/etc/mstudent.env}
[ -f "$ENV_FILE" ] || { echo "Không thấy $ENV_FILE" >&2; exit 1; }
read -r -s -p "Dán GEMINI_API_KEY (để trống = tắt Gemini): " KEY; echo
case "$KEY" in *[[:space:]\"\'\\]*) echo "Khoá có ký tự lạ, thử lại" >&2; exit 1;; esac
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
grep -v '^GEMINI_API_KEY=' "$ENV_FILE" > "$TMP" || true
printf 'GEMINI_API_KEY=%s\n' "$KEY" >> "$TMP"
cat "$TMP" > "$ENV_FILE"   # ghi đè tại chỗ: giữ nguyên chủ sở hữu và quyền 600 của tệp
systemctl restart mstudent
for _ in $(seq 1 20); do
  if OUT=$(curl -fsS -m 3 http://127.0.0.1:8000/api/health 2>/dev/null); then echo "$OUT"; break; fi; sleep 1
done
echo "Xong. filter_model = gemini-decision-1 nghĩa là AI lọc đã bật; kiểm tra thật bằng nút \"Kiểm tra AI ngay\" trong app."
