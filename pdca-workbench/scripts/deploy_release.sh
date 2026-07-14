#!/usr/bin/env bash
# Deploy one exact PDCA Git commit with a pre-deploy database backup and health checks.
set -Eeuo pipefail

TARGET_SHA="${1:-}"
if [[ ! "$TARGET_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "用法: deploy_release.sh <40位Git提交SHA>" >&2
  exit 2
fi

REPO_ROOT="${PDCA_REPO_ROOT:-$(git rev-parse --show-toplevel)}"
WB_DIR="$REPO_ROOT/pdca-workbench"
ENV_FILE="$WB_DIR/.env"
STATE_DIR="$WB_DIR/data/deploy"
LOCK_FILE="$STATE_DIR/deploy.lock"
PUBLIC_HEALTH_URL="${PDCA_PUBLIC_HEALTH_URL:-https://pdca-workbench-teams.vertu.cn/health}"

for command_name in git docker curl python3 flock; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "部署机缺少命令: $command_name" >&2
    exit 1
  fi
done

mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "已有另一项 PDCA 发布正在运行" >&2
  exit 1
fi

cd "$REPO_ROOT"
git cat-file -e "$TARGET_SHA^{commit}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "服务器仓库存在未提交的 tracked 改动，拒绝覆盖" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少服务器私有配置: $ENV_FILE" >&2
  exit 1
fi
chmod 600 "$ENV_FILE"
for key in PDCA_SECRET_KEY PDCA_DATABASE_URL VERTU_APP_KEY; do
  if ! grep -Eq "^${key}=.+$" "$ENV_FILE"; then
    echo ".env 缺少必填配置: $key" >&2
    exit 1
  fi
done

PREVIOUS_SHA="$(git rev-parse HEAD)"
SCHEMA_CHANGED=0
if ! git diff --quiet "$PREVIOUS_SHA" "$TARGET_SHA" -- \
  pdca-workbench/migrations pdca-workbench/app/database.py; then
  SCHEMA_CHANGED=1
fi

backup_database() {
  if ! docker ps --format '{{.Names}}' | grep -qx 'pdca-workbench'; then
    echo "当前没有运行中的 pdca-workbench 容器，跳过旧版本备份"
    return 0
  fi
  local backup_path
  backup_path="$(docker exec -i pdca-workbench python - <<'PY'
from app.scheduler.jobs import backup_database

path = backup_database()
if not path:
    raise SystemExit(1)
print(path)
PY
)"
  if [[ -z "$backup_path" ]]; then
    echo "发布前数据库备份没有返回文件路径" >&2
    return 1
  fi
  printf '%s\n' "$backup_path" > "$STATE_DIR/last_backup_path"
  echo "发布前数据库备份完成"
}

verify_public_health() {
  local body
  for _ in $(seq 1 12); do
    body="$(curl -fsS --connect-timeout 5 --max-time 15 "$PUBLIC_HEALTH_URL" 2>/dev/null || true)"
    if HEALTH_JSON="$body" python3 - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("HEALTH_JSON", ""))
except json.JSONDecodeError:
    raise SystemExit(1)
vertu = payload.get("vertu_cli") or {}
raise SystemExit(0 if payload.get("status") == "ok" and vertu.get("ok") is True else 1)
PY
    then
      return 0
    fi
    sleep 5
  done
  echo "公网健康检查失败: $PUBLIC_HEALTH_URL" >&2
  return 1
}

deploy_sha() {
  local sha="$1"
  local deploy_image=""
  git switch --detach "$sha"
  if [[ -n "${PDCA_IMAGE_REGISTRY:-}" ]]; then
    deploy_image="${PDCA_IMAGE_REGISTRY}:${sha}"
    docker pull "$deploy_image"
  fi
  PDCA_DEPLOY_IMAGE="$deploy_image" bash "$WB_DIR/scripts/docker_up.sh"
  verify_public_health
}

backup_database
echo "开始发布 $PREVIOUS_SHA -> $TARGET_SHA"
if deploy_sha "$TARGET_SHA"; then
  printf '%s\n' "$TARGET_SHA" > "$STATE_DIR/current_sha"
  printf '%s\n' "$PREVIOUS_SHA" > "$STATE_DIR/previous_sha"
  echo "PDCA 发布成功: $TARGET_SHA"
  exit 0
fi

echo "PDCA 发布失败" >&2
if [[ "$SCHEMA_CHANGED" -eq 1 ]]; then
  echo "本次包含数据库结构变更，为避免不兼容，不执行盲目代码回退；请结合发布前备份人工处理" >&2
  exit 1
fi

echo "未检测到数据库结构变更，尝试回退到 $PREVIOUS_SHA" >&2
if deploy_sha "$PREVIOUS_SHA"; then
  printf '%s\n' "$PREVIOUS_SHA" > "$STATE_DIR/current_sha"
  echo "代码与容器已回退到 $PREVIOUS_SHA" >&2
else
  echo "自动回退也失败，需要立即人工处理" >&2
fi
exit 1
