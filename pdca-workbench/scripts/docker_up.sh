#!/usr/bin/env bash
# Docker 一键拉起（非敏感默认项已内置，密钥必须放在未跟踪的 .env）
# 用法：
#   cd /opt/PDCA-agent && bash pdca-workbench/scripts/docker_up.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WB_DIR/.." && pwd)"
MVP_INDEX="$REPO_ROOT/data_platform/data_role_pdca_mvp/modules/home_dashboard/index.html"

echo "=========================================="
echo " PDCA · Docker 一键启动"
echo "=========================================="
echo "仓库: $REPO_ROOT"
echo

if [[ ! -f "$MVP_INDEX" ]]; then
  echo "❌ 缺少经营首页文件，请先拉取完整仓库："
  echo "   cd /opt && git clone https://github.com/Frankie-Foo/PDCA-agent.git"
  echo "   当前期望文件: $MVP_INDEX"
  exit 1
fi
echo "✅ MVP 经营首页文件存在"

if ! command -v docker >/dev/null 2>&1; then
  echo "❌ 未安装 docker，请先安装 Docker / Docker Compose"
  exit 1
fi

cd "$WB_DIR"

# 首次生成未跟踪的 .env 模板；敏感项不会写入仓库。
if [[ ! -f .env ]]; then
  cp env.docker .env
  cat >> .env <<'EOF'

# 必填敏感配置（不要提交 .env）
PDCA_SECRET_KEY=
PDCA_DATABASE_URL=
VERTU_APP_KEY=
EOF
  chmod 600 .env
  echo "❌ 已生成 .env 模板。请填写 PDCA_SECRET_KEY、PDCA_DATABASE_URL、VERTU_APP_KEY 后重试。"
  exit 1
else
  echo "✅ 使用已有 .env（compose 仍强制 PDCA_MVP_ROOT=/mvp）"
fi

for key in PDCA_SECRET_KEY PDCA_DATABASE_URL VERTU_APP_KEY; do
  if ! grep -Eq "^${key}=.+$" .env; then
    echo "❌ .env 缺少必填配置: $key" >&2
    exit 1
  fi
done

if [[ -n "${PDCA_DEPLOY_IMAGE:-}" ]]; then
  export PDCA_IMAGE="$PDCA_DEPLOY_IMAGE"
  echo "→ 使用已通过 CI 的镜像: $PDCA_IMAGE"
  docker compose up -d --no-build pdca-app
else
  echo "→ docker compose up -d --build …"
  docker compose up -d --build pdca-app
fi

echo
echo "→ 等待健康检查…"
ready=0
host_port="${PDCA_HOST_PORT:-8768}"
for i in $(seq 1 30); do
  health="$(curl -fsS "http://127.0.0.1:${host_port}/health" 2>/dev/null || true)"
  if printf '%s' "$health" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    echo "✅ 服务就绪: $health"
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" -ne 1 ]]; then
  echo "❌ 健康检查超时，请查看: docker compose logs -f pdca-app" >&2
  exit 1
fi

echo
echo "=========================================="
echo " 打开: https://pdca-workbench-teams.vertu.cn/"
echo " 或本机: http://服务器IP/"
echo " 登录: VERTU 一键进入，或使用管理员创建的本地账号"
echo " 日志: cd $WB_DIR && docker compose logs -f"
echo "=========================================="
