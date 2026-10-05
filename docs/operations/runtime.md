# 互动页面隔离与桥接（E04）

E04 提供页面包编译、独立只读运行进程、文档进入票据、宿主 MessageChannel 和页面 SDK。课堂、版本授权、进度和提交持久化由 E05 接入；本任务没有公开的“任意上传即运行”接口，也没有用假回执代替业务数据。

## 页面包与运行进程

活动清单沿用 E01 的 `openform.activity/1`。编译器逐项核验完整资源集合及 SHA-256，把声明的本地 JavaScript/CSS 内联，把 PNG/JPEG/woff2 转为内嵌数据资源。整个包最多 8 MiB，生成文档最多 12 MiB。不请求 CDN、在线字体或额外静态资源。

首版支持普通 HTML 控件、经典 JavaScript 和 CSS。模块脚本、动态执行、事件属性、原生表单、外部链接、嵌套页面、SVG/MathML 和未声明资源被拒绝；CSS 的 import 和转义也不接受。图像上传由 `requestUpload` 桥接申请，页面不能直接调用业务 API。导入页面需要适配这个明确的兼容范围。

不可变文档、清单、服务端 CSP 和当前 SDK 一起计算内容摘要，数据库按空间和摘要保存。业务角色不能 UPDATE 页面包。文档票据是 256 位随机值，只在数据库保存摘要，有效期一小时，可撤销；它不赋予学生身份、读取历史、保存或提交权限。票据由 E05 已授权的业务事务签发，不对任意调用方开放。

`openform.runtime.app:runtime_factory` 只提供精确 Host 的 GET/HEAD 文档读取和只读 readiness。它拒绝 query、其他方法和非页面路径，不挂载应用 API、静态目录、CORS 或学生会话。服务请求不记录访问 URL；反向代理也不得为该域名配置访问日志或 CSP 报告接收器。

QA 配置：宿主 `www.openforgeai.cn` → API 18800，运行域 `of.openforgeai.cn` → runtime 18801。两者仅绑定服务器回环地址。E04 只更新配置，待 Q2 统一部署；Q1 的线上应用与证据保持其原版本。

本地使用现有数据库配置，另启运行进程：

```sh
uv run --env-file .env uvicorn openform.runtime.app:runtime_factory --factory --host 127.0.0.1 --port 5174 --no-access-log
```

## 通信边界

宿主 iframe 仅 `sandbox="allow-scripts"`，没有同源、表单、弹窗或顶层导航能力。文档响应再设置 sandbox CSP；网络默认拒绝，脚本只接受编译时计算的 SHA-256，图片/字体仅内嵌数据，表单、嵌套页面和连接都被关闭。宿主 CSP 只允许运行域的 `/p/` 页面进入 iframe。

宿主在每次 load 重新生成 256 位一次性 nonce，同时关闭旧端口、取消请求。握手检查 `event.source`、严格消息结构、协议和 nonce 后才转移 MessagePort。opaque origin 无法用常规域名匹配代替来源检查，因此仅给受检查的 frame 发送初始化和端口。学生姓名、个人进入码、Cookie 和空间标识不出现在握手中。

端口只接受 E01 的八种方法，JSON Schema 与 Python 共用同一文件；AJV 在构建时生成独立校验函数，浏览器不执行动态编译。消息最多 64 KiB、深度 32、节点 10000，并限制到每秒 10 条、每分钟 120 条、并发 8 条。方法必须在发布清单声明，ready 的能力集合必须一致。宿主业务处理器绑定当前服务端上下文；页面提交的身份字段不能用于授权。

页面使用 `window.OpenForm.ready({ capabilities })`，然后调用 `loadProgress()`、`saveProgress({ idempotencyKey, expectedRevision, data })`、`submit(...)` 等方法。`OpenForm.newIdempotencyKey()` 创建新操作标识；同一操作重试应保留原键。SDK 超时或连接消失返回 `RESULT_UNKNOWN`，不会虚构已保存/已提交。`ActivityFrame` 的“通信已建立”只表示端口握手，不能作为试做验证通过的证据。

## 验证边界

按用户要求，E04 开发后执行一次 `/review`，不新增或运行自动化测试；与 E05/E07 集成后在 Q2 执行一次 `/qa`。代码和配置完成不能代表三种浏览器的恶意页面网络检查、真实持久化回执、真实设备或课堂验收已经通过。

CSP 的 URL 匹配包含 origin/path，但不提供 query 内容白名单；拒绝 query 与不记录 URL 是运行服务的明确规则。仍需在 Q2 检查 iframe 自导航、弹窗/表单/图片/嵌套框架、伪造消息与查询参数尝试，并记录真实网络行为，不能只凭响应头宣称隔离全部通过。

机制依据：[MDN iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)、[MDN postMessage](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)、[W3C CSP URL matching](https://w3c.github.io/webappsec-csp/#match-url-to-source-expression)。
