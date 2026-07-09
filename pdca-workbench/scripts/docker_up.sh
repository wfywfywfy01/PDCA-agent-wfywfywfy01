#!/usr/bin/env bash
# Docker 一键拉起（配置已内置，一般不用手改 .env）
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

# 可选：把 env.docker 复制为 .env，方便同事以后改密钥（非必须）
if [[ ! -f .env ]]; then
  cp env.docker .env
  echo "✅ 已从 env.docker 生成 .env（可按需修改）"
else
  echo "✅ 使用已有 .env（compose 仍强制 PDCA_MVP_ROOT=/mvp）"
fi

echo "→ docker compose up -d --build …"
docker compose up -d --build

echo
echo "→ 等待健康检查…"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8767/health >/dev/null 2>&1; then
    echo "✅ 服务就绪: $(curl -fsS http://127.0.0.1:8767/health)"
    break
  fi
  sleep 2
  if [[ $i -eq 30 ]]; then
    echo "⚠️  超时，请查看: docker compose logs -f pdca-app"
  fi
done

echo
echo "=========================================="
echo " 打开: https://pdca-workbench-teams.vertu.cn/"
echo " 或本机: http://服务器IP/"
echo " 登录: admin / admin123  或 VPS 一键进入"
echo " 日志: cd $WB_DIR && docker compose logs -f"
echo "=========================================="
