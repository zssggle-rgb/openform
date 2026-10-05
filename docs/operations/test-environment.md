# OpenForm 腾讯云 QA 环境

整理日期：2026-10-05。用户最终指定 `www.openforgeai.cn`，明确本轮不部署交互原型；该环境留待工程实现后用于 QA。当前仅有 HTTPS 网关、环境检查和部署目录，没有业务应用或 OpenForm 数据库。

## 主机与入口

| 项目 | 当前实际状态 |
|---|---|
| 主机 | 腾讯云轻量应用服务器 `49.232.26.35` |
| QA 域名 | `www.openforgeai.cn`，主机解析得到 `49.232.26.35` |
| 系统 | Ubuntu 24.04.4 LTS / amd64 |
| 资源 | 4 vCPU、约 4 GiB 内存、40 GiB 系统盘；与既有项目共用 |
| 容器运行时 | Docker 已运行，Compose v5.3.1 |
| 网关 | 现有系统 Caddy v2.6.2；systemd 开机启动，管理口仅 loopback |
| HTTPS | [QA 入口](https://www.openforgeai.cn/)，外部正常证书校验通过 |
| 环境状态 | [GET /healthz](https://www.openforgeai.cn/healthz)，200 JSON |
| 原型 / 业务应用 | 均未部署；`application=not_deployed` |
| 旧地址 | `of.openforgeai.cn` 以 308 跳转到 QA 域名，保留请求路径和查询参数 |

环境检查只代表网关就绪，不代表业务可用或 QA 已完成。正式需求的 500 人课堂容量、真实学生设备和校园网络均待后续验证；负载验收应记录共享主机上其他服务的影响。

## 旧测试内容处理

原配置将 `openforgeai.cn` 与 `www.openforgeai.cn` 同时代理到 `127.0.0.1:3001` 的 AI SIGNAL 服务。本次从原站点移除 www，交由 OpenForm 独立站点管理；原 www 下的页面、静态资源和 API 不再进入旧服务。

旧文件位于 `/opt/ai-signal/current`，容器为 `ai-signal-web`。它们同时支撑根域名 `openforgeai.cn`，因此未删除共享文件或容器。用户指定的 www 下已无旧测试内容；这里只接收 `/` 和 `/healthz`，其他路径返回 404。

`/srv/openform/releases`、`data`、`backups` 检查时均为空，未上传原型发布包，未启动 OpenForm 业务容器或数据库。

## HTTPS 配置

站点源文件：[openform-test.caddy](../../deploy/test/openform-test.caddy)。主配置已有并沿用：

```caddyfile
import /etc/caddy/sites/openform-test.caddy
```

`www.openforgeai.cn` 使用 Caddy 已管理的有效证书，主题为该域名，签发者为 Let's Encrypt YE1，到期时间为 **2026-11-22 07:41:34 UTC**。Caddy 已启用自动证书维护；未来实际续签仍应检查证书和日志。本次没有重复申请或删除已有证书。[Caddy 官方自动 HTTPS 说明](https://caddyserver.com/docs/automatic-https)

证书数据位于既有 `/var/lib/caddy/.local/share/caddy`，归 `caddy:caddy`、目录权限 0700；不得清空持久化目录或把私钥提交到 Git。HTTP 自动返回 308，保留路径跳转到 HTTPS。QA 站点设置 HSTS、禁止 MIME 嗅探、no-store 与禁止搜索引擎索引。

本次没有新增业务公网端口、改变 SSH 凭据或重启其他项目容器。腾讯云控制台的“设置 HTTPS 历史”不能替代实际 TLS 验证与 Caddy 日志。

## 目录与后续 QA 部署

| 路径 | 用途 / 权限 |
|---|---|
| `/etc/caddy/sites/openform-test.caddy` | OpenForm QA 网关配置，root 管理 |
| `/srv/openform/releases` | 后续应用发布目录，ubuntu 所有，0750；当前空 |
| `/srv/openform/data` | 后续私有数据卷，ubuntu 所有，0700；当前空 |
| `/srv/openform/backups` | 后续备份暂存，ubuntu 所有，0700；当前空 |
| `/var/backups/openform-gateway/` | 网关配置回退副本，root 管理，0700 |

工程实现后按[工程方案](../designs/openform-engineering-plan.md)部署 Web/API/worker/PostgreSQL，业务端口仅绑定本机或私有容器网络。再将此域名代理到应用，将业务就绪检查接到真实依赖，记录部署的提交和数据库迁移版本，使用合成测试数据进行 QA。当前 `/healthz` 返回：

```json
{"status":"ready","service":"openform-qa-gateway","environment":"qa","application":"not_deployed"}
```

生成/导入 HTML 的隔离运行域须另行配置并完成 E04 测试，不能与教师管理页面共享凭据域。当前没有开放该运行能力。

## 配置更新与回退

[apply-gateway.sh](../../deploy/test/apply-gateway.sh) 专用于这台已检查的 Ubuntu/Caddy 主机，以 `sudo sh` 执行。它备份主配置及 OpenForm 站点，按已确认的共享站点结构移除 www，安装独立配置，校验完整配置后平滑 reload；普通执行错误时恢复配置。发现主配置仍有其他 www 定义时停止并回退，避免覆盖未经检查的站点。

此次域名切换前备份为 `/var/backups/openform-gateway/20261005T054606Z-3906568`，含原主配置和原 `of.openforgeai.cn` 站点。后续更新产生新备份；恢复前核对其他项目是否修改主配置，避免用旧文件覆盖其变更。需要回退此次切换时恢复上述两份配置，先执行 Caddy validate，成功后 reload。

检查命令：

```sh
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy --since '1 hour ago' --no-pager
curl --fail --show-error https://www.openforgeai.cn/healthz
curl --head http://www.openforgeai.cn/healthz
```

验证必须保留正常证书校验，不使用 `curl -k`。需要区分本机代理/DNS 与主机问题时，可指定已确认的公网地址，仍以域名校验证书：

```sh
curl --noproxy '*' --resolve www.openforgeai.cn:443:49.232.26.35 \
  --fail --show-error https://www.openforgeai.cn/healthz
```

## 本次验证证据与限制

- Caddy 完整配置验证成功，服务 active、开机启动 enabled；主配置与备份相比仅移除了原共享站点的 www 别名。
- 外部 curl 未跳过证书验证：根入口和 `/healthz` 返回 HTTP/2 200；正常 DNS 访问根入口也返回 QA 提示。
- HTTP `/healthz` 返回 308 到同路径 HTTPS；旧域名 HTTPS `/healthz` 返回 308 到新 QA 域名。
- 原 AI SIGNAL 的 `/_next/static/chunks/framework-BgSIrAUN.js`、`/og.png`、`/api` 均返回 404。
- `/prototype/`、`/preview.html`、`/.env`、`/.git/config` 均返回 404；发布和数据目录为空，确认没有部署原型或应用。
- 抽查既有站点：`openforgeai.cn`、`ai.lz-sec.com` 返回 200，`api.ai.lz-sec.com` 根路径返回 404，与变更前一致；这不是其他项目的完整功能验收。
- Chrome 自动访问仍显示“此页面已被 Chrome 屏蔽 / ERR_BLOCKED_BY_CLIENT”。未调整客户端保护设置；浏览器正常访问这一项尚未通过，不能以 curl 成功代替浏览器验收。
- Shell 语法、Git 差异及部署配置检查完成。业务功能、跨设备课堂、校园网络、性能和恢复演练尚未执行。
