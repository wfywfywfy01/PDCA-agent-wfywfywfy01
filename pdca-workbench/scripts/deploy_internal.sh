#!/usr/bin/env bash
# PDCA 对内工作台一键部署/修复。
# 敏感配置必须通过环境变量或已有的未跟踪 .env 提供。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WB_DIR/.." && pwd)"
MVP_ROOT="$REPO_ROOT/data_platform/data_role_pdca_mvp"
HOME_INDEX="$MVP_ROOT/modules/home_dashboard/index.html"
ENV_FILE="$WB_DIR/.env"
SERVICE_NAME="${PDCA_SYSTEMD_SERVICE:-pdca-workbench}"

echo "PDCA 工作台部署"
echo "仓库根目录: $REPO_ROOT"
echo "工作台目录: $WB_DIR"

if [[ ! -f "$HOME_INDEX" ]]; then
  echo "找不到经营首页文件: $HOME_INDEX" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -z "${PDCA_DATABASE_URL:-}" ]]; then
    echo "首次部署请先 export PDCA_DATABASE_URL='postgresql+psycopg2://...'" >&2
    exit 1
  fi
  SECRET="${PDCA_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
  cat > "$ENV_FILE" <<EOF
PDCA_ENV=production
PDCA_HOST=0.0.0.0
PDCA_WORKBENCH_PORT=8767
PDCA_SECRET_KEY=$SECRET
PDCA_DATABASE_URL=$PDCA_DATABASE_URL
PDCA_MVP_ROOT=$MVP_ROOT
PDCA_REPO_ROOT=$REPO_ROOT
PDCA_AUTH_MODE=${PDCA_AUTH_MODE:-hybrid}
PDCA_VPS_LOGIN_URL=https://vps.vertu.cn
PDCA_SECURE_COOKIES=1
PDCA_TRUST_PROXY_HEADERS=0
PDCA_VPS_SYNC_ROLE=0
PDCA_CORS_ORIGINS=https://pdca-workbench-teams.vertu.cn
VERTU_COMMAND=vertu
PDCA_SCHEDULER_ENABLED=1
PDCA_SYNC_CRON=0 6 * * *
PDCA_LOG_LEVEL=INFO
PDCA_WORKERS=1
EOF
  chmod 600 "$ENV_FILE"
  echo "已生成仅当前用户可读的 $ENV_FILE"
else
  python3 - "$ENV_FILE" "$MVP_ROOT" "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path

env_path, mvp, repo = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
updates = {"PDCA_ENV": "production", "PDCA_MVP_ROOT": mvp, "PDCA_REPO_ROOT": repo}
lines = env_path.read_text(encoding="utf-8").splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chmod 600 "$ENV_FILE"
fi

if ! grep -Eq '^PDCA_SECRET_KEY=.{32,}$' "$ENV_FILE"; then
  echo "PDCA_SECRET_KEY 缺失或不足 32 位" >&2
  exit 1
fi
if ! grep -Eq '^PDCA_DATABASE_URL=postgresql' "$ENV_FILE"; then
  echo "PDCA_DATABASE_URL 未配置 PostgreSQL" >&2
  exit 1
fi

if command -v pip3 >/dev/null 2>&1; then
  pip3 install -q -r "$WB_DIR/requirements.txt"
fi

if systemctl list-unit-files "$SERVICE_NAME.service" 2>/dev/null | grep -q "$SERVICE_NAME"; then
  systemctl restart "$SERVICE_NAME"
elif command -v docker >/dev/null 2>&1; then
  (cd "$WB_DIR" && docker compose up -d --build)
else
  echo "未检测到 systemd 或 Docker，请手动执行 python3 $WB_DIR/run.py" >&2
  exit 1
fi

sleep 2
curl -fsS "http://127.0.0.1:8767/health"
echo
echo "公网地址: https://pdca-workbench-teams.vertu.cn/"
echo "请使用 VPS 一键进入或管理员创建的本地账号。"
