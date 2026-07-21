#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"
: "${BACKUP_DIR:=/backup}"
: "${BEEZA_BACKUP_BUCKET:=beeza-backups}"
: "${BEEZA_BACKUP_RUN_KEY:?BEEZA_BACKUP_RUN_KEY is required}"
: "${BEEZA_CALLBACK_URL:?BEEZA_CALLBACK_URL is required}"
: "${BEEZA_AUTH_TOKEN:?BEEZA_AUTH_TOKEN is required}"
: "${BEEZA_BACKUP_IDENTITY:=service:enterprise}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${BACKUP_DIR}/${BEEZA_BACKUP_RUN_KEY}-${STAMP}"
mkdir -p "$WORK"

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

pg_dump "$DATABASE_URL" --format=custom --compress=9 --file "$WORK/postgres.dump"
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" --rdb "$WORK/redis.rdb"

cat > "$WORK/manifest.json" <<EOF
{
  "run_key": "${BEEZA_BACKUP_RUN_KEY}",
  "created_at": "${STAMP}",
  "targets": ["postgres", "redis"],
  "bucket": "${BEEZA_BACKUP_BUCKET}",
  "immutable_requested": true
}
EOF

sha256sum "$WORK"/* > "$WORK/SHA256SUMS"
ARCHIVE="${BACKUP_DIR}/${BEEZA_BACKUP_RUN_KEY}-${STAMP}.tar.gz"
tar -C "$WORK" -czf "$ARCHIVE" .
CHECKSUM="$(sha256sum "$ARCHIVE" | awk '{print $1}')"

# Upload is deliberately delegated to the site's approved S3/MinIO client.
# Set BEEZA_UPLOAD_COMMAND, for example:
#   mc cp --attr 'X-Amz-Object-Lock-Mode=COMPLIANCE' "$ARCHIVE" minio/beeza-backups/
if [ -n "${BEEZA_UPLOAD_COMMAND:-}" ]; then
  sh -c "$BEEZA_UPLOAD_COMMAND"
fi

curl -fsS -X POST \
  -H "Authorization: Bearer ${BEEZA_AUTH_TOKEN}" \
  -H "X-Beeza-Identity: ${BEEZA_BACKUP_IDENTITY}" \
  -H "X-Beeza-Risk-Level: HIGH" \
  -H "Content-Type: application/json" \
  "${BEEZA_CALLBACK_URL}/api/enterprise/backup/runs/${BEEZA_BACKUP_RUN_KEY}/complete" \
  -d "{\"status\":\"COMPLETED\",\"checksum\":\"${CHECKSUM}\",\"manifest\":{\"archive\":\"${ARCHIVE}\",\"bucket\":\"${BEEZA_BACKUP_BUCKET}\"}}"

printf 'Backup %s completed: %s\n' "$BEEZA_BACKUP_RUN_KEY" "$CHECKSUM"
