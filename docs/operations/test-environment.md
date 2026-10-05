# OpenForm 腾讯云 QA 环境

环境更新：2026-10-06。用户最终指定 `www.openforgeai.cn`；已部署 E01–E07、E09、E10a 的真实应用及专用 PostgreSQL，完成 Q1–Q3 课堂主流程分组 QA。没有部署交互原型。交接、资料生命周期、迁移和安装恢复继续开发。

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
| 业务应用 | 真实 Web/API，API 仅绑定 `127.0.0.1:18800` |
| 数据库 | 专用 PostgreSQL 18，schema `0009_analysis`，QA 访问仅绑定 `127.0.0.1:15432` |
| 原型 | 未部署 |
| 独立运行域 | `of.openforgeai.cn`，运行服务仅绑定 `127.0.0.1:18801`；只服务短期文档票据，不挂载学生文件卷 |

环境检查来自实际 API readiness，包含数据库 schema 状态；不代表后续模块或全部 QA 已完成。实际范围见 [Q1 报告](../reviews/qa-q1-2026-10-05.md)、[Q2 报告](../reviews/qa-q2-2026-10-05.md)与 [Q3 报告](../reviews/qa-q3-2026-10-06.md)。正式需求的 500 人课堂容量、真实学生设备和校园网络均未验证；按用户收敛要求，本轮没有增加压力测试。

## 旧测试内容处理

原配置将 `openforgeai.cn` 与 `www.openforgeai.cn` 同时代理到 `127.0.0.1:3001` 的 AI SIGNAL 服务。本次从原站点移除 www，交由 OpenForm 独立站点管理；原 www 下的页面、静态资源和 API 不再进入旧服务。

旧文件位于 `/opt/ai-signal/current`，容器为 `ai-signal-web`。它们同时支撑根域名 `openforgeai.cn`，因此未删除共享文件或容器。用户指定的 www 下已无旧测试内容；现在接收 OpenForm 的 Web/API 请求。

初次整理时目录为空。开发后应用使用独立 Compose 项目 `openform-e02` 及其数据库卷；更新 API 时保留现有 QA 数据库，没有重置其他项目的数据或容器。

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
| `/srv/openform/releases/q1-c16d1a3` | Q1 源码构建目录；修复后的实际源码提交与镜像记录在 QA 报告 |
| `/srv/openform/releases/q2-b92f6a2` | 历史 Q2 源码构建目录与镜像；证据见 Q2 报告 |
| `/srv/openform/releases/q3-7e1e0e8` | 当前 Q3 修复源码构建目录，镜像 `openform:q3-7e1e0e8`；源码及镜像摘要见 Q3 报告 |
| Docker 卷 `openform-e02_files` | 私有图片，API 与每小时清理服务共享，归 UID 10001、目录 0700 |
| `/srv/openform/data` | 私有运维资料与合成 QA 的受限邀请文件，0700 |
| `/srv/openform/backups` | 后续备份暂存，0700；本阶段尚未执行恢复演练 |
| `/var/backups/openform-gateway/` | 网关配置回退副本，root 管理，0700 |

按[工程方案](../designs/openform-engineering-plan.md)分阶段部署，业务端口仅绑定本机或私有容器网络。www 已代理到 Web/API，of 已代理到独立运行服务，私有文件清理服务与两个模型 worker 已运行。使用合成账号和学生名单进行 QA。当前 `/healthz` 返回：

```json
{"status":"ready","service":"openform-api"}
```

活动页面在独立运行域的 opaque-origin sandbox 中执行，通过可信父页面保存与提交。Q2 已走通保存、重载恢复、最终提交和图片；Q3 已走通真实模型生成/修改、页面包导入、校内复用及诊断共享。完整对抗矩阵未运行，模型初稿仍须真实试做与教师确认。

## 配置更新与回退

[apply-gateway.sh](../../deploy/test/apply-gateway.sh) 专用于这台已检查的 Ubuntu/Caddy 主机，以 `sudo sh` 执行。它备份主配置及 OpenForm 站点，按已确认的共享站点结构移除 www，安装独立配置，校验完整配置后平滑 reload；普通执行错误时恢复配置。发现主配置仍有其他 www 定义时停止并回退，避免覆盖未经检查的站点。

所有 Caddy 配置写入应共用 `/run/lock/caddy-config.lock`；本脚本使用 flock 拒绝并发运行。写入前核对主配置仍与备份一致，回退只处理本次改动且内容未被再次修改的文件。若其他操作未遵守锁并改动了配置，保留其文件并停止自动回退/reload，由运维根据备份核对；不要强行覆盖共享主配置。

初次域名切换前备份为 `/var/backups/openform-gateway/20261005T054606Z-3906568`，含原主配置和原 `of.openforgeai.cn` 站点。Q2 接入独立运行域的备份为 `/var/backups/openform-gateway/20261005T151956Z-124704`。恢复前核对其他项目是否修改主配置，避免用旧文件覆盖其变更；选择对应变更的备份，先执行 Caddy validate，成功后 reload。

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

## 初次环境整理的历史证据与限制

- Caddy 完整配置验证成功，服务 active、开机启动 enabled；主配置与备份相比仅移除了原共享站点的 www 别名。
- 外部 curl 未跳过证书验证：根入口和 `/healthz` 返回 HTTP/2 200；正常 DNS 访问根入口也返回 QA 提示。
- HTTP `/healthz` 返回 308 到同路径 HTTPS；旧域名 HTTPS `/healthz` 返回 308 到新 QA 域名。
- 原 AI SIGNAL 的 `/_next/static/chunks/framework-BgSIrAUN.js`、`/og.png`、`/api` 均返回 404。
- `/prototype/`、`/preview.html`、`/.env`、`/.git/config` 均返回 404；发布和数据目录为空，确认没有部署原型或应用。
- 抽查既有站点：`openforgeai.cn`、`ai.lz-sec.com` 返回 200，`api.ai.lz-sec.com` 根路径返回 404，与变更前一致；这不是其他项目的完整功能验收。
- Chrome 自动访问仍显示“此页面已被 Chrome 屏蔽 / ERR_BLOCKED_BY_CLIENT”。未调整客户端保护设置；浏览器正常访问这一项尚未通过，不能以 curl 成功代替浏览器验收。
- Shell 语法、Git 差异及部署配置检查完成。业务功能、跨设备课堂、校园网络、性能和恢复演练尚未执行。

以上为应用部署前的历史记录，不能作为当前业务验收。Q1–Q3 已使用 gstack 浏览器实际访问 HTTPS Web/API 与独立运行域；当时 Chrome 的 ERR_BLOCKED_BY_CLIENT 不是本次浏览器运行的结果。当前功能范围、修复复查及尚未验证的事项以分组 QA 报告为准。
