#!/usr/bin/env bash
# Ежедневный бэкап БД и фото (ТЗ «Мастер-данные» §8: срок хранения 30 дней).
# Запуск из cron:  0 2 * * * /home/ubuntu/dress-rental/scripts/backup.sh >> /home/ubuntu/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${BACKUP_DIR:-/home/ubuntu/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%F)"
mkdir -p "$DEST"
docker compose exec -T postgres pg_dump -U "${DB_USER:-dress_app}" "${DB_NAME:-dress_db}" | gzip > "$DEST/db_$STAMP.sql.gz"
docker compose exec -T backend tar -C /app -czf - media > "$DEST/media_$STAMP.tar.gz"
find "$DEST" -name 'db_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -name 'media_*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "[$(date)] backup ok: $DEST/db_$STAMP.sql.gz, $DEST/media_$STAMP.tar.gz"
