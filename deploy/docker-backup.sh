#!/usr/bin/env bash
set -euo pipefail
source /opt/mstudent/docker/release.env
# No API credentials or network are needed for an SQLite snapshot.
exec docker run --rm --network none --read-only --user "$MSTUDENT_UID:$MSTUDENT_GID" \
  --mount "type=bind,src=$MSTUDENT_DATA_DIR,dst=/data" \
  --mount type=bind,src=/var/backups/mstudent,dst=/backups \
  "$MSTUDENT_IMAGE" python /app/deploy/backup.py /data/mstudent.db /backups 7
