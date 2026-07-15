#!/usr/bin/env bash
# Start the built image with isolated development settings and verify the real container.
set -Eeuo pipefail

IMAGE="${1:-pdca-workbench:local-smoke}"
CONTAINER_NAME="${PDCA_SMOKE_CONTAINER:-pdca-workbench-smoke}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MVP_ROOT="$REPO_ROOT/data_platform/data_role_pdca_mvp"
RUNTIME_ROOT="$(mktemp -d)"
SMOKE_DATE="$(date +%F)"
SMOKE_MONTH="${SMOKE_DATE:0:7}"

if ! command -v docker >/dev/null 2>&1; then
  echo "找不到 Docker" >&2
  exit 1
fi
cleanup() {
  # Files written through the bind mounts are owned by the container user
  # (root in production). Make the disposable runtime tree removable by the
  # CI runner before stopping the container.
  docker exec "$CONTAINER_NAME" chmod -R a+rwX \
    /mvp/inputs /mvp/outputs /mvp/outbox >/dev/null 2>&1 || true
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$RUNTIME_ROOT"
}
trap cleanup EXIT
cleanup
mkdir -p "$RUNTIME_ROOT/inputs" "$RUNTIME_ROOT/outputs" "$RUNTIME_ROOT/outbox"

docker run --detach \
  --name "$CONTAINER_NAME" \
  --env PDCA_ENV=development \
  --env PDCA_HOST=0.0.0.0 \
  --env PDCA_WORKBENCH_PORT=8767 \
  --env PDCA_SECRET_KEY=ci-smoke-secret-key-at-least-32-characters \
  --env PDCA_DATABASE_URL=sqlite:////tmp/pdca-smoke.db \
  --env PDCA_AUTH_MODE=local \
  --env PDCA_SECURE_COOKIES=0 \
  --env PDCA_REQUIRE_VERTU=0 \
  --env PDCA_INCLUDE_DEMO_DATA=0 \
  --env PDCA_SCHEDULER_ENABLED=0 \
  --env PDCA_MVP_ROOT=/mvp \
  --env PDCA_REPO_ROOT=/repo \
  --env PDCA_BOOTSTRAP_ADMIN_USERNAME=smoke-admin \
  --env PDCA_BOOTSTRAP_ADMIN_PASSWORD='SmokeAdmin123!' \
  --env PDCA_BOOTSTRAP_ADMIN_DISPLAY_NAME='Smoke Admin' \
  --env VERTU_COMMAND=vertu-cli \
  --volume "$MVP_ROOT:/mvp:ro" \
  --volume "$RUNTIME_ROOT/inputs:/mvp/inputs" \
  --volume "$RUNTIME_ROOT/outputs:/mvp/outputs" \
  --volume "$RUNTIME_ROOT/outbox:/mvp/outbox" \
  --volume "$REPO_ROOT:/repo:ro" \
  "$IMAGE" >/dev/null

health_body=""
for _ in $(seq 1 45); do
  health_body="$(docker exec "$CONTAINER_NAME" curl -fsS --connect-timeout 2 --max-time 5 \
    http://127.0.0.1:8767/health 2>/dev/null || true)"
  if docker exec -i --env HEALTH_JSON="$health_body" "$CONTAINER_NAME" python - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("HEALTH_JSON", ""))
except json.JSONDecodeError:
    raise SystemExit(1)
raise SystemExit(
    0
    if payload.get("status") == "ok"
    and payload.get("database") in {"sqlite", "sqlite-fallback"}
    else 1
)
PY
  then
    break
  fi
  sleep 2
done

if ! docker exec -i --env HEALTH_JSON="$health_body" "$CONTAINER_NAME" python - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("HEALTH_JSON", ""))
except json.JSONDecodeError:
    raise SystemExit(1)
raise SystemExit(0 if payload.get("status") == "ok" else 1)
PY
then
  echo "容器健康检查失败" >&2
  docker logs --tail 200 "$CONTAINER_NAME" >&2 || true
  exit 1
fi

headers="$(docker exec "$CONTAINER_NAME" curl -fsS -D - -o /dev/null \
  http://127.0.0.1:8767/login)"
if ! printf '%s' "$headers" | grep -Eiq '^x-content-type-options:[[:space:]]*nosniff'; then
  echo "登录页缺少 X-Content-Type-Options 安全头" >&2
  exit 1
fi

# Exercise the real auth lifecycle and representative writable business paths.
login_json="$(docker exec "$CONTAINER_NAME" curl -fsS -c /tmp/pdca-cookie \
  -H 'Content-Type: application/json' \
  --data '{"username":"smoke-admin","password":"SmokeAdmin123!"}' \
  http://127.0.0.1:8767/api/auth/login)"
docker exec -i --env PAYLOAD="$login_json" "$CONTAINER_NAME" python - <<'PY'
import json, os
payload = json.loads(os.environ["PAYLOAD"])
assert payload["must_change_password"] is True
PY

docker exec "$CONTAINER_NAME" curl -fsS -b /tmp/pdca-cookie -c /tmp/pdca-cookie \
  -H 'Content-Type: application/json' \
  --data '{"old_password":"SmokeAdmin123!","new_password":"SmokeAdmin456!"}' \
  http://127.0.0.1:8767/api/auth/change-password >/dev/null

docker exec "$CONTAINER_NAME" curl -fsS -b /tmp/pdca-cookie \
  "http://127.0.0.1:8767/questionnaire?date=$SMOKE_DATE" >/dev/null
questionnaire_status="$(docker exec "$CONTAINER_NAME" curl -sS -o /dev/null -w '%{http_code}' \
  -b /tmp/pdca-cookie --data-urlencode 'q0=smoke answer' \
  "http://127.0.0.1:8767/questionnaire?date=$SMOKE_DATE")"
test "$questionnaire_status" = "303"
docker exec "$CONTAINER_NAME" test -s "/mvp/inputs/questionnaires/${SMOKE_DATE}_questionnaire.md"

docker exec "$CONTAINER_NAME" curl -fsS -b /tmp/pdca-cookie \
  -H 'Content-Type: application/json' \
  --data '{"store_id":"smoke-store","name":"Smoke Store","region":"其他","country":"Test","dealer_level":"L1","team_key":"overseas"}' \
  http://127.0.0.1:8767/api/admin/stores >/dev/null
docker exec "$CONTAINER_NAME" curl -fsS -b /tmp/pdca-cookie \
  -H 'Content-Type: application/json' \
  --data "{\"report_date\":\"$SMOKE_DATE\",\"dealer_id\":\"smoke-store\",\"dealer_name\":\"Smoke Store\",\"walkin_visits\":3,\"touch_count\":2,\"wechat_add_count\":1,\"deal_count\":1,\"deal_amount_yuan\":100}" \
  http://127.0.0.1:8767/api/walkin-metrics >/dev/null
walkin_json="$(docker exec "$CONTAINER_NAME" curl -fsS -b /tmp/pdca-cookie \
  "http://127.0.0.1:8767/api/walkin?month=$SMOKE_MONTH")"
docker exec -i --env PAYLOAD="$walkin_json" "$CONTAINER_NAME" python - <<'PY'
import json, os
payload = json.loads(os.environ["PAYLOAD"])
assert payload["meta"]["storeCount"] >= 1
assert "unavailable" not in payload["meta"].get("dataSources", [])
smoke_store = next(item for item in payload["stores"] if item["id"] == "smoke-store")
assert smoke_store["fiveKit"]["total"] == 3
PY

today_json="$(docker exec "$CONTAINER_NAME" curl -fsS -b /tmp/pdca-cookie \
  "http://127.0.0.1:8767/api/workbench/today?date=$SMOKE_DATE")"
docker exec -i --env PAYLOAD="$today_json" "$CONTAINER_NAME" python - <<'PY'
import json, os
payload = json.loads(os.environ["PAYLOAD"])
assert payload["scope"]["mode"] == "all"
assert payload["facts"]["walkin_reported"]["state"] == "available"
assert payload["facts"]["walkin_reported"]["value"] >= 1
assert isinstance(payload["actions"], list)
PY

cli_version="$(docker exec "$CONTAINER_NAME" vertu-cli --version)"
legacy_cli_version="$(docker exec "$CONTAINER_NAME" vertu --version)"
echo "Docker 冒烟测试通过: image=$IMAGE cli=$cli_version legacy_cli=$legacy_cli_version health=$health_body"
