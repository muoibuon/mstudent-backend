# Docker trên VPS Linux

Image dùng code theo revision Git, chạy non-root, filesystem chỉ đọc và mount riêng SQLite. Compose dùng host network;
Uvicorn chỉ bind `127.0.0.1:8000` để giữ đường Tailscale Funnel hiện có và boundary đọc proxy headers của ứng dụng.
Không thêm `ports` hoặc đổi host thành `0.0.0.0` với cấu hình này.

## Chuẩn bị

Docker Engine và Compose plugin phải được cài trên VPS. Giữ khóa trong `/etc/mstudent.env` mode 600, không copy vào
source hoặc image. Giữ nguyên `MSTUDENT_SECRET_KEY` để phiên đăng nhập và Google refresh token mã hóa còn dùng được.

```bash
export MSTUDENT_REVISION="<full-git-commit>"
export MSTUDENT_IMAGE="mstudent-backend:$MSTUDENT_REVISION"
export MSTUDENT_UID="$(id -u mstudent)"
export MSTUDENT_GID="$(id -g mstudent)"
docker compose -p mstudent -f deploy/compose.yaml build
```

Đường host mặc định `/opt/mstudent/data/mstudent.db`, trong container `/data/mstudent.db`. Compose override riêng
`MSTUDENT_DB`; file env trên host vẫn giữ đường DB host để công cụ backup hiện có tiếp tục dùng được.

Trước khi chuyển: sao lưu code cũ, service unit, env và DB bằng SQLite backup API, kiểm `PRAGMA integrity_check`.
Thử image bằng DB clone và tắt `MSTUDENT_SYNC_ENABLED`, sau đó kiểm tra gateway/Decision bằng dữ liệu tổng hợp trên
clone. Không chạy hai scheduler trên cùng DB production.

Đường triển khai chính: `sudo bash deploy/install.sh`. Với source từ `git archive` không có metadata Git, truyền
`sudo MSTUDENT_REVISION=<full-commit> bash deploy/install.sh`. Script lưu manifest không có khóa tại
`/opt/mstudent/docker/release.env`, build image rồi chuyển container với kiểm health/rollback. Lần đầu cần chuẩn bị
`/etc/mstudent.env` và Docker trước; script không tự ghi đè cấu hình/khóa đang có.

## Chuyển từ service systemd

```bash
sudo systemctl stop mstudent.service
# Lấy bản backup DB cuối khi writer đã dừng, kiểm tra toàn vẹn và quyền sở hữu.
docker compose -p mstudent -f deploy/compose.yaml up -d --no-build
curl -fsS http://127.0.0.1:8000/api/health
docker compose -p mstudent -f deploy/compose.yaml ps
```

Sau khi xác minh local/public HTTPS và smoke test thành công, disable `mstudent.service` để không tranh cổng khi reboot.
Docker restart policy đảm nhiệm khởi động container. Giữ unit cũ, venv và code cũ làm điểm rollback.
Timer backup được cập nhật để gọi `docker-backup.sh`: container không có network, không được truyền API keys, chạy
đúng UID/GID và ghi snapshot tại `/var/backups/mstudent`. Kiểm tra backup thành công trước khi coi deploy hoàn tất.

## Rollback

```bash
docker compose -p mstudent -f deploy/compose.yaml down
sudo systemctl enable --now mstudent.service
```

Nếu env/model setting đã đổi trong đợt triển khai, khôi phục các giá trị được sao lưu của đúng đợt trước khi start
service cũ. Chỉ restore toàn bộ DB khi đã xác định cần thiết; restore snapshot có thể mất dữ liệu sinh ra sau snapshot.
Không xóa volume/data hoặc chạy `down -v` khi rollback. Muốn quay lại Docker image trước, dùng tag revision cũ đã lưu,
không dùng `latest` để xác định phiên bản.

Container health chỉ kiểm tra API, không chứng minh OAuth hoặc provider đang nhận request thật. Xác minh hai phần đó
riêng. Không xuất `docker inspect` toàn bộ hoặc `docker compose config` ra log vì có thể chứa env secret đã resolve.
