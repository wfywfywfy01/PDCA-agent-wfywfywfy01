# PDCA CI/CD

GitHub Actions 工作流位于 `.github/workflows/pdca-ci-cd.yml`。

## 流程

PR 和 `main` 的相关改动会执行：

1. Python 3.12 锁定依赖安装、22 项单元测试及编译检查。
2. Bash 与 Docker Compose 配置检查。
3. 完整生产 Docker 镜像构建，并实际启动隔离容器，验证 `/health`、登录页安全头和 `vertu-cli`。
4. `main` 的已测试镜像发布到 GHCR，生产服务器只拉取该精确 SHA，不再现场访问 Docker Hub 重建。
5. 只有 `main` 的前述检查全部通过后，才进入 `production` 环境并通过 SSH 发布精确的 Git commit。
6. 发布前备份 PostgreSQL，发布后同时检查服务器本机和公网健康状态。

## GitHub Secrets

在仓库 `Settings → Secrets and variables → Actions` 配置：

| 名称 | 必填 | 说明 |
|---|---:|---|
| `PDCA_DEPLOY_HOST` | 是 | 部署机域名或 IP |
| `PDCA_DEPLOY_USER` | 是 | 独立的非 root 部署账号 |
| `PDCA_DEPLOY_SSH_KEY` | 是 | 仅用于该部署账号的私钥 |
| `PDCA_DEPLOY_HOST_FINGERPRINT` | 是 | SSH 主机公钥 SHA256 指纹，防止中间人攻击 |
| `PDCA_DEPLOY_PORT` | 否 | SSH 端口，默认 22 |

主机指纹应由服务器控制台获取，不要通过未验证的首次 SSH 连接信任：

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

只把输出中的 `SHA256:...` 写入 GitHub Secret。

## 服务器前置条件

- 仓库位于 `/opt/PDCA-agent`，部署账号对该目录有写权限。
- 已安装 Git、Docker Compose、Python 3、curl、flock。
- `pdca-workbench/.env` 已配置且权限为 `600`，至少包含 `PDCA_SECRET_KEY`、`PDCA_DATABASE_URL`、`VERTU_APP_KEY`。
- 部署账号可运行 Docker，但不应开放交互式 root 密码登录。
- Caddy 反代 `127.0.0.1:8768`；容器内仍监听 8767。

## 本地发布前 Docker 测试

本地 Docker Desktop 启动后，在仓库根目录运行：

```bash
docker build -t pdca-workbench:local-smoke pdca-workbench
bash pdca-workbench/scripts/docker_smoke_test.sh pdca-workbench:local-smoke
```

脚本使用独立容器名且不向宿主机发布端口，不会占用开发服务的 8767 端口；检查通过或失败后都会自动删除测试容器。CI 使用同一脚本，因此以后发布前会自动执行相同的真实容器检查。

脚本兼容 Docker Context，但生产环境不要暴露无 TLS 的 `tcp://主机:2375`：Docker API 等同于主机 root 权限。远程使用应优先采用 `ssh://部署账号@主机` Context，或启用双向 TLS 的 2376。远程构建节点也应与 PostgreSQL 数据库节点分离，避免构建抢占数据库资源。

## 发布与回退

每次发布部署 `${{ github.sha }}`，不会在服务器重新读取一个可能已经变化的 `main`。服务器使用 `flock` 防止并发发布，并把状态记录在 `pdca-workbench/data/deploy/`。

若健康检查失败且此次提交没有修改数据库迁移或 `app/database.py`，脚本会回退上一提交。若包含数据库结构变化，脚本不会盲目回退旧代码，而是保留发布前备份并要求人工判断，避免旧代码与新结构不兼容。

## 推荐仓库设置

- 创建 GitHub `production` Environment，可按需要增加审批人。
- 保护 `main`，要求 `Python tests and configuration` 与 `Container build` 成功后才能合并。
- 禁止直接向 `main` 推送，日常改动统一通过 PR。
