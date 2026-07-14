#!/usr/bin/env bash
# Start the built image with isolated development settings and verify the real container.
set -Eeuo pipefail

IMAGE="${1:-pdca-workbench:local-smoke}"
CONTAINER_NAME="${PDCA_SMOKE_CONTAINER:-pdca-workbench-smoke}"

if ! command -v docker >/dev/null 2>&1; then
  echo "找不到 Docker" >&2
  exit 1
fi
cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

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
  --env PDCA_MVP_ROOT=/tmp/mvp \
  --env PDCA_REPO_ROOT=/tmp/repo \
  --env VERTU_COMMAND=vertu-cli \
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

cli_version="$(docker exec "$CONTAINER_NAME" vertu-cli --version)"
echo "Docker 冒烟测试通过: image=$IMAGE cli=$cli_version health=$health_body"
