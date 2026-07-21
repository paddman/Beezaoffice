#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"
: "${BACKUP_ARCHIVE:?BACKUP_ARCHIVE is required}"
: "${RESTORE_DIR:=/restore}"
: "${CONFIRM_RESTORE:?Set CONFIRM_RESTORE=RESTORE_BEEZAOFFICE}"

if [ "$CONFIRM_RESTORE" != "RESTORE_BEEZAOFFICE" ]; then
  echo "Restore confirmation is invalid" >&2
  exit 2
fi

WORK="${RESTORE_DIR}/beeza-restore-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT INT TERM

tar -C "$WORK" -xzf "$BACKUP_ARCHIVE"
(cd "$WORK" && sha256sum -c SHA256SUMS)

# Restore PostgreSQL into a prepared empty database or maintenance window.
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" "$WORK/postgres.dump"

# Redis restore requires a maintenance restart so Redis can load dump.rdb.
# The site-specific orchestration command must atomically replace the RDB file.
if [ -n "${BEEZA_REDIS_RESTORE_COMMAND:-}" ]; then
  sh -c "$BEEZA_REDIS_RESTORE_COMMAND"
else
  echo "PostgreSQL restored. Redis RDB validated but not installed; set BEEZA_REDIS_RESTORE_COMMAND." >&2
fi

printf 'Restore completed from %s\n' "$BACKUP_ARCHIVE"
