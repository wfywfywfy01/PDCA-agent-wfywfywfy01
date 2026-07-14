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
SERVICE_NAME="${PDCA_SYSTEMD_SERVICE:-}"

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
  if [[ -z "${VERTU_APP_KEY:-}" ]]; then
    echo "首次部署请先 export VERTU_APP_KEY='由 vertu-cli agent bind 签发的应用密钥'" >&2
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
VERTU_COMMAND=vertu-cli
VERTU_VPS_SERVICE_URL=${VERTU_VPS_SERVICE_URL:-https://vps-service.vertu.cn}
VERTU_APP_ID=${VERTU_APP_ID:-pdca-workbench}
VERTU_APP_KEY=$VERTU_APP_KEY
PDCA_REQUIRE_VERTU=1
PDCA_INCLUDE_DEMO_DATA=0
PDCA_SCHEDULER_ENABLED=1
PDCA_SYNC_CRON=0 6 * * *
PDCA_LOG_LEVEL=INFO
PDCA_WORKERS=1
EOF
  chmod 600 "$ENV_FILE"
  echo "已生成仅当前用户可读的 $ENV_FILE"
else
  python3 - "$ENV_FILE" "$MVP_ROOT" "$REPO_ROOT" <<'PY'
import os
import sys
from pathlib import Path

env_path, mvp, repo = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
updates = {
    "PDCA_ENV": "production",
    "PDCA_MVP_ROOT": mvp,
    "PDCA_REPO_ROOT": repo,
    "VERTU_COMMAND": "vertu-cli",
    "VERTU_VPS_SERVICE_URL": os.environ.get(
        "VERTU_VPS_SERVICE_URL", "https://vps-service.vertu.cn"
    ),
    "VERTU_APP_ID": os.environ.get("VERTU_APP_ID", "pdca-workbench"),
    "PDCA_REQUIRE_VERTU": "1",
    "PDCA_INCLUDE_DEMO_DATA": "0",
}
if os.environ.get("VERTU_APP_KEY"):
    updates["VERTU_APP_KEY"] = os.environ["VERTU_APP_KEY"]
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
if ! grep -Eq '^VERTU_APP_KEY=.+$' "$ENV_FILE"; then
  echo "VERTU_APP_KEY 未配置；请用 vertu-cli agent bind 签发后写入未跟踪的 .env" >&2
  exit 1
fi

if [[ -z "$SERVICE_NAME" ]]; then
  for candidate in pdca-workbench pdca; do
    if systemctl list-unit-files "$candidate.service" 2>/dev/null | grep -q "^$candidate.service"; then
      SERVICE_NAME="$candidate"
      break
    fi
  done
fi

if [[ -n "$SERVICE_NAME" ]] && systemctl list-unit-files "$SERVICE_NAME.service" 2>/dev/null | grep -q "^$SERVICE_NAME.service"; then
  if ! command -v node >/dev/null 2>&1 || [[ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]]; then
    echo "systemd 模式需要 Node.js >= 20" >&2
    exit 1
  fi
  if ! command -v vertu-cli >/dev/null 2>&1; then
    echo "systemd 模式找不到 vertu-cli；请安装固定版本: npm install -g vertu-cli@2.1.10" >&2
    exit 1
  fi
  vertu-cli --version
  python3 - "$ENV_FILE" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

env = os.environ.copy()
for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key in {"VERTU_VPS_SERVICE_URL", "VERTU_APP_ID", "VERTU_APP_KEY"}:
        env[key] = value.strip()
result = subprocess.run(
    ["vertu-cli", "auth", "status", "--json"],
    env=env,
    capture_output=True,
    text=True,
    timeout=30,
)
try:
    payload = json.loads(result.stdout)
except json.JSONDecodeError:
    payload = {}
if result.returncode or not payload.get("logged_in") or not payload.get("server_authorized"):
    raise SystemExit("vertu-cli 应用凭证预检失败；请检查 VERTU_APP_ID / VERTU_APP_KEY")
PY
  if command -v pip3 >/dev/null 2>&1; then
    pip3 install -q -r "$WB_DIR/requirements.lock"
  fi
  systemctl restart "$SERVICE_NAME"
elif command -v docker >/dev/null 2>&1; then
  (cd "$WB_DIR" && docker compose up -d --build)
else
  echo "未检测到 pdca-workbench/pdca systemd 服务或 Docker；也可用 PDCA_SYSTEMD_SERVICE 指定服务名" >&2
  exit 1
fi

sleep 2
curl -fsS "http://127.0.0.1:8767/health"
echo
echo "公网地址: https://pdca-workbench-teams.vertu.cn/"
echo "请使用 VERTU 一键进入或管理员创建的本地账号。"
