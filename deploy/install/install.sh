#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_DIR="${BEEZA_INSTALL_DIR:-/opt/beezaoffice}"
COMPOSE_SOURCE="${SCRIPT_DIR}/compose.production.yml"
COMPOSE_FILE="${INSTALL_DIR}/compose.yml"
ENV_FILE="${INSTALL_DIR}/.env"
BEEZA_IMAGE="${BEEZA_IMAGE:-ghcr.io/paddman/beezaoffice:0.15.0}"
BEEZA_LICENSE_MODE="${BEEZA_LICENSE_MODE:-enforce}"
BEEZA_SKIP_SIGNATURE_VERIFY="${BEEZA_SKIP_SIGNATURE_VERIFY:-false}"
BEEZA_ALLOW_UNPINNED_IMAGE="${BEEZA_ALLOW_UNPINNED_IMAGE:-false}"

log() { printf '[BeezaOffice] %s\n' "$*"; }
fail() { printf '[BeezaOffice] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is required"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
[ -f "$COMPOSE_SOURCE" ] || fail "Missing compose template: $COMPOSE_SOURCE"

case "$BEEZA_IMAGE" in
  *@sha256:*) : ;;
  *)
    [ "$BEEZA_ALLOW_UNPINNED_IMAGE" = "true" ] || fail "BEEZA_IMAGE must be pinned by digest. Set BEEZA_ALLOW_UNPINNED_IMAGE=true only for a controlled test."
    ;;
esac

if [ "$BEEZA_SKIP_SIGNATURE_VERIFY" != "true" ]; then
  command -v cosign >/dev/null 2>&1 || fail "cosign is required to verify the signed release image"
  : "${BEEZA_COSIGN_IDENTITY:?Set BEEZA_COSIGN_IDENTITY to the release workflow identity}"
  : "${BEEZA_COSIGN_ISSUER:=https://token.actions.githubusercontent.com}"
  log "Verifying signed release image"
  cosign verify \
    --certificate-identity "$BEEZA_COSIGN_IDENTITY" \
    --certificate-oidc-issuer "$BEEZA_COSIGN_ISSUER" \
    "$BEEZA_IMAGE" >/dev/null
else
  log "WARNING: image signature verification was explicitly skipped"
fi

umask 077
mkdir -p "$INSTALL_DIR"
cp "$COMPOSE_SOURCE" "$COMPOSE_FILE"

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    od -An -N "$1" -tx1 /dev/urandom | tr -d ' \n'
  fi
}

if [ ! -f "$ENV_FILE" ]; then
  POSTGRES_PASSWORD="$(random_hex 24)"
  AUTH_TOKEN="$(random_hex 32)"
  METRICS_TOKEN="$(random_hex 32)"
  DEPLOYMENT_ID="${BEEZA_DEPLOYMENT_ID:-deployment:$(hostname | tr -cd 'A-Za-z0-9._-' | tr 'A-Z' 'a-z'):$(random_hex 6)}"
  cat > "$ENV_FILE" <<EOF
APP_ENV=production
APP_PORT=${APP_PORT:-8080}
BEEZA_BIND_ADDRESS=${BEEZA_BIND_ADDRESS:-127.0.0.1}
BEEZA_IMAGE=${BEEZA_IMAGE}

POSTGRES_DB=beezaoffice
POSTGRES_USER=beeza
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=postgresql+psycopg://beeza:${POSTGRES_PASSWORD}@postgres:5432/beezaoffice
REDIS_URL=redis://redis:6379/0

BEEZA_AUTH_TOKEN=${AUTH_TOKEN}
BEEZA_METRICS_TOKEN=${METRICS_TOKEN}
BEEZA_PUBLIC_URL=${BEEZA_PUBLIC_URL:-http://127.0.0.1:${APP_PORT:-8080}}
BEEZA_DEFAULT_TENANT=${BEEZA_DEFAULT_TENANT:-tenant:beeza}
BEEZA_DEPLOYMENT_ID=${DEPLOYMENT_ID}
BEEZA_LICENSE_MODE=${BEEZA_LICENSE_MODE}
BEEZA_LICENSE_ISSUER=${BEEZA_LICENSE_ISSUER:-beezaoffice-license}
BEEZA_LICENSE_AUDIENCE=${BEEZA_LICENSE_AUDIENCE:-beezaoffice}
BEEZA_LICENSE_ALGORITHMS=${BEEZA_LICENSE_ALGORITHMS:-EdDSA,RS256,ES256}
BEEZA_LICENSE_PUBLIC_KEY=${BEEZA_LICENSE_PUBLIC_KEY:-}
BEEZA_LICENSE_TOKEN=${BEEZA_LICENSE_TOKEN:-}

BEEZA_GOVERNANCE_ENFORCED=true
BEEZA_BUSINESS_ENABLED=true
BEEZA_BUSINESS_INTERVAL_SECONDS=60
BEEZA_DEFAULT_LABOR_RATE_USD=30
BEEZA_RUNTIME_SYNC_ENABLED=true
BEEZA_COLLAB_ENABLED=true
BEEZA_MEETING_ENABLED=true
BEEZA_SCHEDULER_ENABLED=true
BEEZA_EVALUATOR_ENABLED=true
BEEZA_SOP_ENABLED=true
BEEZA_PROTOCOL_ENABLED=true
EOF
  log "Created protected environment file at $ENV_FILE"
else
  log "Preserving existing environment file at $ENV_FILE"
fi

if [ "$BEEZA_LICENSE_MODE" = "enforce" ]; then
  grep -q '^BEEZA_LICENSE_PUBLIC_KEY=.' "$ENV_FILE" || log "WARNING: license public key is empty; product execution will remain blocked"
  grep -q '^BEEZA_LICENSE_TOKEN=.' "$ENV_FILE" || log "WARNING: license token is empty; import it through the Commercial API before go-live"
fi

cd "$INSTALL_DIR"
log "Pulling production images"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
log "Starting BeezaOffice"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans

attempt=0
until docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T beezaoffice \
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 40 ] || {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=200 beezaoffice
    fail "BeezaOffice did not become ready"
  }
  sleep 3
done

log "BeezaOffice is ready"
log "Install directory: $INSTALL_DIR"
log "Local endpoint: ${BEEZA_PUBLIC_URL:-http://127.0.0.1:${APP_PORT:-8080}}"
log "Keep $ENV_FILE private and back it up through the approved secret-management process"
