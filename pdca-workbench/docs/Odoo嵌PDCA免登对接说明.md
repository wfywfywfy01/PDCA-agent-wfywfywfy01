# Odoo 嵌 PDCA 免登对接说明（给 ERP 同事）

> 适用环境：`https://admin.vertu.cn`（Odoo 17）嵌套 `https://pdca-workbench.vertu.cn`  
> PDCA 侧接口已上线，**缺的是 Odoo 侧 3 件事：装模块、配密钥、改 iframe 地址**。  
> 需要：Odoo 后台 **设置管理员**（能装应用、能写系统参数、能改 `dealer_sale` 前端）。

---

## 1. 背景

海外渠道中台（`dealer_sale`，菜单「经销商管理」）里，部分页面用 iframe 打开 PDCA：

```
https://pdca-workbench.vertu.cn/
```

两个站点不同源：

| 站点 | 域 |
|---|---|
| Odoo | `admin.vertu.cn` |
| PDCA 五件套门户 | `pdca-workbench.vertu.cn` |

Odoo 的 `session_id` **不会**带到 PDCA。用户在 Odoo 已登录，iframe 里仍要再登一次 PDCA。

另外：PDCA 默认禁止被别的网站嵌套。现已对 `https://admin.vertu.cn` 放开 `frame-ancestors`。若控制台再报 `frame-ancestors 'self'`，先找 PDCA 确认门户容器是否被旧镜像覆盖。

---

## 2. 方案（不要改成跨域读 Cookie）

Odoo 已登录用户打开一个 **Odoo 同源入口**，由 Odoo 签发 2 分钟 HMAC 票据，302 跳到 PDCA；PDCA 验票后写自己的登录 Cookie。

```
用户已登录 Odoo
    ↓
iframe src = https://admin.vertu.cn/pdca/embed
    ↓  （同源，Odoo 知道当前 user）
签发 ticket（120 秒有效，一次性跳转）
    ↓
https://pdca-workbench.vertu.cn/api/auth/odoo-sso?ticket=...&next=/
    ↓
PDCA 校验 HMAC → 按 Odoo login 映射/创建本地账号 → 种 pdca_token → 进入页面
```

**iframe 必须改成 Odoo 地址，不能继续直链 `pdca-workbench.vertu.cn`。**  
直链 PDCA 时，PDCA 拿不到 Odoo 登录态。

---

## 3. 你要做的三步

### 步骤 A：安装模块 `pdca_embed_sso`

模块已放在 PDCA 仓库（让 PDCA 同事发你这一份目录即可）：

```
pdca-workbench/odoo_addons/pdca_embed_sso/
├── __init__.py
├── __manifest__.py
└── controllers/
    ├── __init__.py
    └── embed.py
```

1. 把整个 `pdca_embed_sso` 目录拷到 Odoo addons 路径（与现有 `dealer_sale`、`vt_crm` 同级）。  
   生产代码目录参考：`/root/odoo-online/vertu-erp/`（以你们实际 addons path 为准）。
2. 确认该 path 已在 `addons_path` 里。
3. 重启 Odoo 或更新模块列表。
4. 打开 **应用**，去掉「应用」筛选（显示技术模块），搜索 **PDCA Embed SSO**。
5. 安装。依赖：`web`、`hr`（生产已有，不用新装）。

安装成功后，已登录用户浏览器访问：

```
https://admin.vertu.cn/pdca/embed
```

应变为 **302** 跳到 `https://pdca-workbench.vertu.cn/api/auth/odoo-sso?ticket=...`。  
若仍是 404，模块没加载到（addons_path / 没重启 / 没点安装）。

未登录访问该 URL：Odoo 会先跳自己的登录页，这是正常的（`auth='user'`）。

---

### 步骤 B：配置共享密钥

Odoo 和 PDCA **必须用同一串密钥**。

1. 用管理员账号打开：  
   **设置 → 技术 → 参数 → 系统参数**
2. 新建：

   | 字段 | 值 |
   |---|---|
   | Key | `pdca.sso_secret` |
   | Value | 向 PDCA 负责人要（已写在 PDCA 容器 `/app/data/odoo_sso_secret`） |

3. 保存。不要把密钥提交到 Git、不要发到公开群。

密钥为空或两边不一致时：`/pdca/embed` 会把用户送到 PDCA **登录页**（免登失败，看起来像「没生效」）。

若要自己轮换密钥：两边同时改，先改 PDCA（环境变量 `PDCA_ODOO_SSO_SECRET` 或上述文件），再改 Odoo 系统参数。

---

### 步骤 C：改 iframe 地址

把中台里嵌 PDCA 的 `src` 从：

```
https://pdca-workbench.vertu.cn/
```

改成：

```
https://admin.vertu.cn/pdca/embed
```

若 iframe 要直接进五件套填报页：

```
https://admin.vertu.cn/pdca/embed?next=/walkin-submit
```

`next` 只允许 PDCA 站内相对路径（以 `/` 开头，不能 `//`）。

#### 在代码里可能出现的位置

当前中台应用 xmlid 前缀是 `dealer_sale`，顶栏菜单包括：数据看板、销售订单、设置、库存、数据导入导出、Walk-In接待报表 等。

数据看板对应 client action：

| 项 | 值 |
|---|---|
| xmlid | `dealer_sale.action_dealer_dashboard` |
| tag | `dealer_dashboard` |
| 菜单 | `dealer_sale.menu_dealer_dashboard` |

iframe URL 很大概率写在 `dealer_sale` 的 OWL/JS（`dealer_dashboard`）或相应 QWeb/XML 里，搜索：

```
pdca-workbench.vertu.cn
```

销售订单菜单 `dealer_sale.dealer_sale_order_menu_action`（action 1590）目前是原生 `dealer.sale.order` 列表。若你们后来改成了 iframe，同样搜上面这个域名并替换。

改完后：**升级/更新 `dealer_sale` 模块**，浏览器强刷（Ctrl+F5）。静态资源有 hash 时清一下资源缓存。

不要用 `https://pdca-workbench.vertu.cn/api/auth/odoo-sso?ticket=...` 当 iframe 的固定 src。ticket 120 秒过期，必须每次经 `/pdca/embed` 现签。

---

## 4. 验收

用 **已经登录 Odoo** 的员工号（不要用 Public）：

1. 新开标签访问 `https://admin.vertu.cn/pdca/embed`  
   - 应很快跳进 PDCA，**不再出现 PDCA 登录页**。
2. 打开海外渠道中台里原来嵌 PDCA 的菜单（数据看板 / 销售订单，以实际改过的为准）。  
   - iframe 内应直接是 PDCA 业务页。  
   - 控制台不应再有 `frame-ancestors` / `拒绝连接`。
3. 隐身窗口、未登录 Odoo 打开中台：应先 Odoo 登录，登录后再免登进 PDCA。
4. PDCA 本地用户：按 Odoo 的 `login` 映射；没有则自动创建。职位含「中台 / 主管 / 销售」会影响默认角色（可在 PDCA 后台再改，不会被日常免登覆盖）。

---

## 5. 失败对照

| 现象 | 原因 | 处理 |
|---|---|---|
| `/pdca/embed` 404 | 模块未安装或 addons_path 不对 | 步骤 A |
| iframe 仍「拒绝连接」 | PDCA CSP 被旧镜像盖掉，或 iframe 还在直链且被拦 | 找 PDCA 看 `curl -sI https://pdca-workbench.vertu.cn/` 是否含 `frame-ancestors ... admin.vertu.cn` |
| 能嵌进去但仍是 PDCA 登录页 | 密钥没配/配错，或 iframe 仍直链 PDCA | 步骤 B、C |
| 跳登录后马上失败 | ticket 过期（签发到跳转超过 120s）或 HMAC 算法被改 | 不要改 `embed.py` 签名格式；检查服务器时间 |
| 门户用户 / public 进不去 | 故意拒绝 `public` 等账号 | 用内部员工账号 |
| 下次 PDCA 发版免登又没了 | 热补被镜像覆盖 | PDCA 把代码打进正式镜像 |

**不要改** `controllers/embed.py` 里的签名算法（payload JSON + urlsafe base64 + HMAC-SHA256 hex）。PDCA `/api/auth/odoo-sso` 按同一规则验。

---

## 6. 安全约束（给评审）

- 票据含 `login / uid / name / job_title / department_name / exp`，120 秒失效。
- 密钥只放 Odoo 系统参数和 PDCA 服务器，不进前端 JS。
- iframe 仍指向 Odoo 同源 `/pdca/embed`，避免把 `session_id` 拼进 PDCA URL。
- PDCA 只接受 `admin.vertu.cn` 嵌套（CSP `frame-ancestors`）。

---

## 7. 联系人与仓库

| 项 | 说明 |
|---|---|
| 模块路径 | PDCA 仓 `pdca-workbench/odoo_addons/pdca_embed_sso` |
| PDCA 验票 | `GET https://pdca-workbench.vertu.cn/api/auth/odoo-sso` |
| Odoo 入口 | `GET https://admin.vertu.cn/pdca/embed` |
| 密钥 | 向 PDCA 要；Odoo key 固定为 `pdca.sso_secret` |

装完、iframe 改完后告诉 PDCA 一声，方便对一下响应头和验票日志。
