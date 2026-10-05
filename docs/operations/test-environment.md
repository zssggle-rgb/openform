# OpenForm 腾讯云测试环境

准备日期：2026-10-05。此次交付为开发联调入口、HTTPS 和部署目录；业务应用与数据库仍待工程任务实现。

## 主机与入口

| 项目 | 当前实际状态 |
|---|---|
| 主机 | 腾讯云轻量应用服务器 `49.232.26.35` |
| 域名 | `of.openforgeai.cn`，主机解析得到 `49.232.26.35` |
| 系统 | Ubuntu 24.04.4 LTS / amd64 |
| 资源 | 4 vCPU、约 4 GiB 内存、40 GiB 系统盘；与既有项目共用 |
| 容器运行时 | Docker 已运行，Compose v5.3.1 |
| 网关 | 现有系统 Caddy v2.6.2；systemd 开机启动，管理口仅 loopback |
| HTTPS | [测试入口](https://of.openforgeai.cn/)，外部正常证书校验通过 |
| 环境状态 | [GET /healthz](https://of.openforgeai.cn/healthz)，200 JSON |
| 业务应用 | 尚未部署；健康检查中明确 `application=not_deployed` |

这是开发与联调主机。正式需求的 500 人课堂容量尚未验证，负载验收要记录共享主机上其他服务的影响，不能以此次 HTTPS 验证代替容量验收。

## HTTPS 配置

原主配置没有 OpenForm 域名，因此 HTTP 的通用跳转能够响应，而该域名的 TLS 握手失败。本次新增独立站点，主配置仅加入这一行：

```caddyfile
import /etc/caddy/sites/openform-test.caddy
```

站点源文件：[openform-test.caddy](../../deploy/test/openform-test.caddy)。证书由 Caddy 自动管理，2026-10-05 日志记录 Let's Encrypt `tls-alpn-01` 校验通过并成功取得证书。当前证书主题为 `of.openforgeai.cn`，签发者为 Let's Encrypt YE2，到期时间为 **2027-01-03 02:18:12 UTC**。Caddy 已启用自动证书维护；未来续签是否成功仍应根据日志和实际证书检查。

证书数据保存在既有 `/var/lib/caddy/.local/share/caddy`，归 `caddy:caddy`、目录权限 0700；不得清空该持久化目录或把私钥提交到 Git。HTTP 自动返回 308，保留路径跳转到 HTTPS；站点使用 HSTS、禁止 MIME 嗅探、no-store 和禁止搜索引擎索引。

本次沿用主机已开放的 80/443，没有新增业务端口、改变 SSH 凭据或重启其他容器。腾讯云“设置 HTTPS 历史”仅记录控制台管理流程；本次是主机 Caddy 管理的证书，应以实际 TLS 验证和 Caddy 日志为准。[Caddy 官方自动 HTTPS 说明](https://caddyserver.com/docs/automatic-https)

## 目录和后续部署

| 路径 | 用途 / 权限 |
|---|---|
| `/etc/caddy/sites/openform-test.caddy` | OpenForm 网关配置，root 管理 |
| `/srv/openform/releases` | 后续应用发布目录，ubuntu 所有，0750 |
| `/srv/openform/data` | 后续私有数据卷，ubuntu 所有，0700；当前空目录 |
| `/srv/openform/backups` | 后续备份暂存，ubuntu 所有，0700；当前未执行业务备份 |
| `/var/backups/openform-gateway/` | 网关配置回退副本，root 管理，0700 |

后续按[工程方案](../designs/openform-engineering-plan.md)实现 Web/API/worker/PostgreSQL；业务服务仅绑定本机或私有容器网络，网关再代理到其端口。届时将 `/healthz` 的业务状态接到真实健康检查。生成/导入 HTML 的隔离运行域需要另行配置并完成 E04 测试，不能让它与教师管理页面共享凭据域。

## 配置更新与回退

安装脚本：[apply-gateway.sh](../../deploy/test/apply-gateway.sh)，专用于这台已经检查的 Ubuntu/Caddy 主机，以 `sudo sh` 执行。它先备份主配置和既有 OpenForm 站点，安装片段，校验完整 Caddy 配置，再平滑 reload；普通执行错误时恢复配置。脚本不会创建账户、安装软件或开放端口。

本次首次备份路径：`/var/backups/openform-gateway/20261005T031637Z-3833338`。再次运行会生成新的时间戳目录；需要撤销整个新站点时应使用首次备份，更新某次配置则使用对应更新前副本。回退前检查之后是否有其他项目修改主配置，有则仅移除 OpenForm import 行，避免覆盖其变更。

平常检查：

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy --since '1 hour ago' --no-pager
curl --fail --show-error https://of.openforgeai.cn/healthz
curl --head http://of.openforgeai.cn/healthz
```

验证时必须保留正常证书检查，不使用 `curl -k`。需要区分本机代理/DNS 与主机问题时，可指定已确认公网地址，仍以域名校验证书：

```sh
curl --noproxy '*' --resolve of.openforgeai.cn:443:49.232.26.35 \
  --fail --show-error https://of.openforgeai.cn/healthz
```

## 本次验证证据与限制

- Caddy 完整配置验证成功，服务 active/running，开机启动 enabled。
- Let's Encrypt 从多个校验节点完成域名验证；实际 TLS 证书主题、签发者和有效期读取成功。
- 外部 `curl` 未跳过证书验证：根入口与 `/healthz` 返回 HTTP/2 200；HTTP `/healthz` 返回 308，Location 为同路径 HTTPS。
- `/healthz` 返回 `{"status":"ready","service":"openform-test-gateway","application":"not_deployed"}`；`/.env` 返回 404。
- 抽查既有站点：`ai.lz-sec.com` 和 `openforgeai.cn` 的 200、`api.ai.lz-sec.com` 根路径的 404 均与变更前一致；这不是其他项目的完整功能验收。
- Chrome 自动访问显示“此页面已被 Chrome 屏蔽 / ERR_BLOCKED_BY_CLIENT”，不是本轮 curl 的证书错误。客户端拦截原因尚未确定；浏览器安全策略拒绝读取 `chrome://extensions/`，未绕过或调整保护设置。Chrome 侧正常打开仍需使用者检查客户端拦截，不能记录为浏览器验收通过。
- 配置、Shell 语法和部署检查已完成；OpenForm 业务功能、真实学生设备、校园网络与性能均待后续验收。
