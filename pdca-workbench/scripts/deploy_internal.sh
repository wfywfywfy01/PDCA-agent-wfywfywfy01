#!/usr/bin/env bash
# PDCA 对内工作台一键部署/修复
# 用法（在服务器上）：
#   cd /opt/PDCA-agent && bash pdca-workbench/scripts/deploy_internal.sh
# 或：
#   bash /opt/PDCA-agent/pdca-workbench/scripts/deploy_internal.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WB_DIR/.." && pwd)"
MVP_ROOT="$REPO_ROOT/data_platform/data_role_pdca_mvp"
HOME_INDEX="$MVP_ROOT/modules/home_dashboard/index.html"
ENV_FILE="$WB_DIR/.env"
SERVICE_NAME="${PDCA_SYSTEMD_SERVICE:-pdca-workbench}"

echo "=========================================="
echo " PDCA 对内工作台 · 一键部署/修复"
echo "=========================================="
echo "仓库根目录: $REPO_ROOT"
echo "工作台目录: $WB_DIR"
echo "MVP 目录:   $MVP_ROOT"
echo

# ── 1. 检查经营首页文件 ──────────────────────────────────────────────────────
if [[ ! -f "$HOME_INDEX" ]]; then
  echo "❌ 找不到经营首页文件："
  echo "   $HOME_INDEX"
  echo
  echo "请先拉取完整仓库（不要只拷 pdca-workbench）："
  echo "  cd /opt && git clone https://github.com/Frankie-Foo/PDCA-agent.git"
  echo "  或：cd $REPO_ROOT && git pull origin main"
  exit 1
fi
echo "✅ 经营首页文件存在"

# ── 2. 生成 / 修补 .env ──────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  echo "→ 未找到 .env，自动生成…"
  SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)"
  cat > "$ENV_FILE" <<EOF
PDCA_HOST=0.0.0.0
PDCA_WORKBENCH_PORT=8767
PDCA_SECRET_KEY=$SECRET
PDCA_TOKEN_EXPIRE_MINUTES=480
PDCA_DATABASE_URL=postgresql+psycopg2://postgres:H1UaJoeo-aSF-zpM6V-0ARP@10.100.0.176:5432/pdca
PDCA_PG_HOST=10.100.0.176
PDCA_PG_PORT=5432
PDCA_PG_USER=postgres
PDCA_PG_PASSWORD=H1UaJoeo-aSF-zpM6V-0ARP
PDCA_PG_DATABASE=pdca
PDCA_MVP_ROOT=$MVP_ROOT
PDCA_REPO_ROOT=$REPO_ROOT
PDCA_AUTH_MODE=hybrid
PDCA_VPS_LOGIN_URL=https://vps.vertu.cn
PDCA_SECURE_COOKIES=1
PDCA_TRUST_PROXY_HEADERS=0
PDCA_VPS_SYNC_ROLE=0
PDCA_CORS_ORIGINS=https://pdca-workbench-teams.vertu.cn
VERTU_COMMAND=vertu
PDCA_SCHEDULER_ENABLED=1
PDCA_SYNC_CRON=0 6 * * *
PDCA_LOG_LEVEL=INFO
PDCA_WORKERS=2
EOF
  echo "✅ 已生成 $ENV_FILE"
else
  echo "→ 已有 .env，自动校正 MVP / REPO 路径…"
  # 用临时文件改写关键路径，保留其余配置
  python3 - "$ENV_FILE" "$MVP_ROOT" "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path
env_path, mvp, repo = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = env_path.read_text(encoding="utf-8").splitlines()
keys = {
    "PDCA_MVP_ROOT": mvp,
    "PDCA_REPO_ROOT": repo,
}
seen = set()
out = []
for line in lines:
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k in keys:
        out.append(f"{k}={keys[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in keys.items():
    if k not in seen:
        out.append(f"{k}={v}")
# 确保 hybrid（若未设置）
if not any(l.startswith("PDCA_AUTH_MODE=") for l in out):
    out.append("PDCA_AUTH_MODE=hybrid")
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("patched", env_path)
PY
  echo "✅ 已校正 PDCA_MVP_ROOT / PDCA_REPO_ROOT"
fi

# ── 3. 安装依赖（若有 pip）───────────────────────────────────────────────────
if command -v pip3 >/dev/null 2>&1; then
  echo "→ 安装/更新 Python 依赖…"
  pip3 install -q -r "$WB_DIR/requirements.txt" || pip3 install -r "$WB_DIR/requirements.txt"
  echo "✅ 依赖就绪"
else
  echo "⚠️  未找到 pip3，跳过依赖安装（Docker 部署可忽略）"
fi

# ── 4. 重启服务 ──────────────────────────────────────────────────────────────
restarted=0
if systemctl list-unit-files "$SERVICE_NAME.service" 2>/dev/null | grep -q "$SERVICE_NAME"; then
  echo "→ 重启 systemd: $SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  sleep 2
  systemctl --no-pager --full status "$SERVICE_NAME" | head -n 15 || true
  restarted=1
elif command -v docker >/dev/null 2>&1 && [[ -f "$WB_DIR/docker-compose.yml" ]]; then
  echo "→ 使用 docker compose 重启…"
  (cd "$WB_DIR" && docker compose up -d --build)
  restarted=1
else
  echo "⚠️  未检测到 systemd 服务或 docker。"
  echo "   可手动启动："
  echo "   cd $WB_DIR && python3 run.py"
fi

# ── 5. 健康检查 ──────────────────────────────────────────────────────────────
echo
echo "→ 健康检查…"
sleep 1
if curl -fsS "http://127.0.0.1:8767/health" >/tmp/pdca_health.json 2>/dev/null; then
  cat /tmp/pdca_health.json
  echo
  echo "✅ 服务正常"
else
  echo "⚠️  暂时无法访问 http://127.0.0.1:8767/health"
  echo "   若刚启动，请等几秒再试；或检查 journalctl -u $SERVICE_NAME -f"
fi

echo
echo "=========================================="
echo " 完成。浏览器打开："
echo "   https://pdca-workbench-teams.vertu.cn/"
echo " 登录（hybrid）：admin / admin123"
echo " 或登录页「VPS 一键进入」"
echo "=========================================="
