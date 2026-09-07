#!/usr/bin/env bash
# Disposable real-PostgreSQL acceptance; no production config or external network.
set -Eeuo pipefail
IMAGE="${1:?Usage: docker_postgres_smoke_test.sh IMAGE}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NETWORK="pdca-pg-smoke-$$"
DB="${NETWORK}-db"
APP="${NETWORK}-app"
cleanup() {
  docker rm -f -v "$APP" "$DB" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$NETWORK" >/dev/null
docker run -d --name "$DB" --network "$NETWORK" \
  -e POSTGRES_USER=pdca -e POSTGRES_PASSWORD=isolated-ci-only -e POSTGRES_DB=pdca_review \
  --tmpfs /var/lib/postgresql/data postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do
  if docker exec "$DB" pg_isready -U pdca -d pdca_review >/dev/null 2>&1; then break; fi
  sleep 1
done
docker run -d --name "$APP" --network "$NETWORK" \
  -e PDCA_ENV=development -e TZ=Asia/Shanghai -e PDCA_SCHEDULER_ENABLED=0 \
  -e "PDCA_DATABASE_URL=postgresql+psycopg2://pdca:isolated-ci-only@$DB:5432/pdca_review" \
  -e PDCA_SECRET_KEY=isolated-ci-only-key-at-least-32-characters \
  -e PDCA_AUTH_MODE=local -e PDCA_SECURE_COOKIES=0 -e PDCA_REQUIRE_VERTU=0 \
  -e PDCA_INCLUDE_DEMO_DATA=0 -e PDCA_BOOTSTRAP_ADMIN_USERNAME=smoke-admin \
  -e 'PDCA_BOOTSTRAP_ADMIN_PASSWORD=SmokeAdmin123!' \
  -v "$REPO_ROOT:/repo:ro" -v "$REPO_ROOT/data_platform/data_role_pdca_mvp:/mvp:ro" \
  --tmpfs /app/data --tmpfs /mvp/inputs --tmpfs /mvp/outputs --tmpfs /mvp/outbox "$IMAGE" >/dev/null
for _ in $(seq 1 45); do
  if docker exec "$APP" curl -fsS --max-time 3 http://127.0.0.1:8767/health >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$APP" python -m scripts.postgres_acceptance
# Verify a real database outage is not falsely healthy; this DB contains only QA fixtures.
docker stop --time 10 "$DB" >/dev/null
docker exec -i "$APP" python - <<'PY'
import json, urllib.error, urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:8767/health", timeout=15)
except urllib.error.HTTPError as exc:
    assert exc.code == 503
    assert json.load(exc)["database_connected"] is False
else:
    raise AssertionError("Database outage falsely reported healthy")
print("PASS: real PostgreSQL outage returns HTTP 503")
PY
