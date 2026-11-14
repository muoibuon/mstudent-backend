#!/usr/bin/env bash
# Docker-first deployment on the Linux VPS. Run from an exact source revision as root.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng sudo." >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/mstudent
ENV_FILE=/etc/mstudent.env
docker version >/dev/null
docker compose version >/dev/null
[ -f "$ENV_FILE" ] || { echo "Tạo $ENV_FILE từ deploy/mstudent.env.example trước khi chạy." >&2; exit 1; }
id mstudent >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin mstudent
install -d -o mstudent -g mstudent -m 700 "$APP/data" /var/backups/mstudent
install -d -m 700 "$APP/docker" "$APP/deploy-backups"
REV="${MSTUDENT_REVISION:-$(git -C "$SRC" rev-parse HEAD)}"
[[ "$REV" =~ ^[0-9a-f]{40}$ ]] || { echo "Cần MSTUDENT_REVISION là full Git commit." >&2; exit 1; }
IMAGE="mstudent-backend:$REV"
UID_APP="$(id -u mstudent)"; GID_APP="$(id -g mstudent)"
BACKUP="$(mktemp -d "$APP/deploy-backups/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
cp -p "$ENV_FILE" "$BACKUP/mstudent.env"
if [ -f "$APP/docker/release.env" ]; then
  cp -p "$APP/docker/release.env" "$BACKUP/release.env"
  cp -p "$APP/docker/compose.yaml" "$BACKUP/compose.yaml"
fi
cp "$SRC/deploy/compose.yaml" "$APP/docker/compose.yaml.new"
printf 'MSTUDENT_IMAGE=%s\nMSTUDENT_REVISION=%s\nMSTUDENT_UID=%s\nMSTUDENT_GID=%s\nMSTUDENT_ENV_FILE=%s\nMSTUDENT_DATA_DIR=%s\n' \
  "$IMAGE" "$REV" "$UID_APP" "$GID_APP" "$ENV_FILE" "$APP/data" > "$APP/docker/release.env.new"
docker build --build-arg "VCS_REF=$REV" -t "$IMAGE" "$SRC"

OLD_SYSTEMD=0
systemctl is-active --quiet mstudent.service && OLD_SYSTEMD=1
OLD_DOCKER=0
if [ -f "$APP/docker/release.env" ]; then
  [ -n "$(docker compose -p mstudent --env-file "$APP/docker/release.env" -f "$APP/docker/compose.yaml" ps -q backend)" ] && OLD_DOCKER=1
fi
SWITCHED=0
rollback() {
  code=$?
  trap - ERR
  if [ "$SWITCHED" -eq 1 ]; then
    if [ -f "$APP/docker/release.env" ]; then
      docker compose -p mstudent --env-file "$APP/docker/release.env" -f "$APP/docker/compose.yaml" down || true
    fi
    if [ "$OLD_DOCKER" -eq 1 ]; then
      cp -p "$BACKUP/release.env" "$APP/docker/release.env"
      cp -p "$BACKUP/compose.yaml" "$APP/docker/compose.yaml"
      docker compose -p mstudent --env-file "$APP/docker/release.env" -f "$APP/docker/compose.yaml" up -d --no-build || true
    elif [ "$OLD_SYSTEMD" -eq 1 ]; then
      systemctl start mstudent.service || true
    fi
  fi
  echo "Deploy lỗi; xem rollback và snapshot tại $BACKUP" >&2
  exit "$code"
}
trap rollback ERR

if [ "$OLD_SYSTEMD" -eq 1 ]; then systemctl stop mstudent.service; fi
if [ "$OLD_DOCKER" -eq 1 ]; then
  docker compose -p mstudent --env-file "$APP/docker/release.env" -f "$APP/docker/compose.yaml" stop backend
fi
SWITCHED=1
# A consistent final snapshot with all application writers stopped.
if [ -f "$APP/data/mstudent.db" ]; then
  docker run --rm --read-only --user 0:0 \
    --mount "type=bind,src=$APP/data,dst=/data" --mount "type=bind,src=$BACKUP,dst=/snapshot" \
    "$IMAGE" python -c "import sqlite3,os; a=sqlite3.connect('file:/data/mstudent.db?mode=ro',uri=True); b=sqlite3.connect('/snapshot/mstudent.db'); a.backup(b); assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; b.close(); a.close(); os.chmod('/snapshot/mstudent.db',0o600)"
fi
mv "$APP/docker/compose.yaml.new" "$APP/docker/compose.yaml"
mv "$APP/docker/release.env.new" "$APP/docker/release.env"
docker compose -p mstudent --env-file "$APP/docker/release.env" -f "$APP/docker/compose.yaml" up -d --no-build
healthy=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null; then healthy=1; break; fi
  sleep 2
done
[ "$healthy" -eq 1 ]
if [ "$OLD_SYSTEMD" -eq 1 ]; then systemctl disable mstudent.service; fi
install -m 700 "$SRC/deploy/docker-backup.sh" "$APP/docker/backup.sh"
install -m 644 "$SRC/deploy/mstudent-backup.service" "$SRC/deploy/mstudent-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mstudent-backup.timer
trap - ERR
echo "Docker release $REV đang chạy; snapshot: $BACKUP"
