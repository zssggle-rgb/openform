# OpenForm 工程方案与评审

日期：2026-10-05。评审方式：`/plan-eng-review`，FULL_REVIEW。基线：`main@9490b2643c38fb8e96ca788393a164b517a4a92e`。

**结论：按模块化单体、独立任务进程、PostgreSQL 和隔离活动运行环境开始开发。** 保留已确认的教师个人版、校园多用户版及三类课堂活动。先交付一条真实课堂链路，再完成首版其余功能。此文是工程实施依据，不表示后端、模型接入、生产部署或课堂验收已经完成。

正式范围以[需求方案](openform-classroom-platform.md)为准，页面职责以[页面整合方案](openform-page-integration-plan.md)为准，视觉继续采用 [DESIGN.md](../../DESIGN.md) 和现有 VI。本方案细化实现，不撤销既有 D1–D14 决定。实施任务 E01–E13 是原 T1–T10 的工程拆解，不是新增产品范围。

用户此前明确“后续都按你的建议选择”。本次依该持续授权逐项采纳推荐 A，未逐题重新询问；这不等于用户逐项作了新的回答。实际主机、域名、教师样本和模型账户由开发/试点阶段填入，不妨碍工程设计，本轮不购买或创建外部资源。

## 0. Scope Challenge

- 保留范围：自然语言生成与修改、外部 HTML/静态包导入、真实试做、固定版本开展、续做与最终提交、基础统计与 AI 诊断、三端权限、校内复用、迁移、Linux 私有部署与恢复。不能把核心缩成只有固定表单。
- 最小有价值里程碑：教师制作词汇活动 → 在真正的隔离 HTML 中试做并收到服务端回执 → 开班级课堂 → 两台学生设备分别续做和提交 → 教师看到可对账结果；同时验证同校另一教师不能越权，并能复制明确发布的教学资源。先跑通这一链，不先铺满空白页面。
- 复杂度挑战：完整首版显然超过 8 个文件，并包含 Web、API、worker、数据库及网关等进程。接受这些交付单元，但 API 与 worker 共用一个代码库和镜像、一个业务数据库；不拆微服务，不引入消息中间件或容器集群。
- 已有实现有 3 类可复用模式：`prototype/model.mjs` 的业务对象与状态语义、`prototype/store.mjs` 的“持久化后通知”、`prototype/teacher.mjs` / `admin.mjs` / `student.mjs` / `ui.mjs` 的页面、导航及焦点契约。复用流程、合成样例和外观，生产权限与事务重新在服务端实现。
- 现有 27 个原型测试可保留；生成页脚本执行、真实身份、数据库并发、模型和文件存储没有可复用的生产实现。不能声称已有三种后端模式可直接照搬。
- 分发流水线属于首版：持续集成、容器镜像、离线镜像包、数据库迁移、安装升级与恢复验证均进入 E02/E12。未把运维留作“以后再补”。

## 1. Architecture Review：7 项

下列发现均为首版实施前 P1，置信度针对“计划需要补齐该机制”，不表示产品已经发生这些故障。选项性质不同的架构比较不虚构完整度分数。

| ID / 证据与影响 | A：采纳的方案及代价 | B：未采用方案 | 置信度 |
|---|---|---|---|
| A1：需求方案:169 的“工程候选”尚未落到代码边界；容易个人版、学校版各写一套 | 共用空间模型、模块化单体和独立 worker；两种语言、两个测试栈的维护成本可控 | 全 TypeScript 单体也可行，但会改变原候选及 Python 模型处理路线；微服务增加部署和一致性成本 | 8/10 |
| A2：`prototype/app.mjs:157` 明确“课堂使用制作器中的结构化题目”，导入 iframe 禁止脚本；尚不满足真正互动 HTML 接入 | 版本化活动协议、独立域 sandbox、可信宿主代理读写、真实试做闸门；限制可支持的 HTML 能力 | 继续只渲染结构化题目，降低成本但缺失 D3 的主功能；不采纳 | 9/10 |
| A3：需求:225–229、308–315 要求重试和竞态正确；`prototype/store.mjs:32` 只写本机 localStorage | 数据库唯一约束、载荷摘要、回执和状态共事务、固定锁序；需要真实并发测试 | 前端防双击或单次权限检查，简单但不能保证跨设备正确；不采纳 | 9/10 |
| A4：需求:192–206、238 的个人/校园、协作、交接权限需要统一落实 | 稳定身份、显式对象授权、空间隔离和授权版本；增加权限矩阵集成测试 | 仅靠前端角色隐藏，或校管默认能读全校答案，违反范围 | 9/10 |
| A5：需求:237、367、373 的任务重跑、模型覆盖和证据不是普通同步请求 | 持久化任务、租约代次、配额预留、确定性统计与报告快照；需处理不确定的外部调用结果 | API 请求内调用模型，或普通进程内后台任务；重启后可能丢任务 | 8/10 |
| A6：需求:230–236 的图片、资源包与课堂档案缺少落盘事务和格式边界 | 文件暂存→校验→引用；不可变资源清单；档案独立、迁移先验后提交；需要清理暂存文件 | 上传即公开/逐行直接导入，易产生半成品和跨空间引用 | 8/10 |
| A7：需求:208、410–411 的校内部署与恢复需要可分发产物 | 一个 Linux 容器方案，版本化迁移、维护窗口备份、新实例锁定恢复；承认单机故障与停写成本 | 只给开发启动命令，或原地覆盖恢复，不能交付 D10/Q9 | 8/10 |

A2/A3/A4/A5/A6/A7 均为完整方案与缺项捷径的比较：A 完整度 10/10，B 分别为 4/3/3/5/4/4。分数仅表示对本项目要求的计划覆盖。A1 为方案类型比较，无完整度分数。所有推荐遵循简单可维护、规则集中、关键边界明确的项目约定。

### 1.1 技术与模块

| 层 | 本次采纳 | 边界 |
|---|---|---|
| 三端 Web | React 19、TypeScript、Vite；Node 24 LTS 作为构建运行时 | 同一 Web 工程按角色/空间组织路由；保留现有 UI/VI；不引入 SSR 需求 |
| API / worker | Python 3.13、FastAPI、Pydantic 2、SQLAlchemy 2、psycopg 3、Alembic | 一个镜像、两个入口，共享领域规则；worker 不能绕过对象权限 |
| 数据 | PostgreSQL 18 | 事实、任务、配额和审计在同一数据库；不用 SQLite 模拟锁和生产事务 |
| 文件 | 本地受控卷优先；存储接口预留 S3 适配 | 首发只承诺已完成同一验收套件的适配；没有 S3 实测不宣传其支持 |
| 网关/部署 | Caddy、Docker Compose、Linux amd64 | TLS、可信应用域和无凭据活动域；离线部署也要本地可用证书和域名解析 |
| 测试 | pytest、真实 PostgreSQL 集成测试、Vitest、Playwright、k6、固定模型评估集 | 每层验证自己的行为，不用纯函数测试替代服务和浏览器验证 |

主要版本是工程基线；E02 实施时复核补丁版本、兼容性、许可与漏洞公告，提交 lockfile 和镜像 digest。当前没有安装这些生产依赖，不能把此表当作已建环境。React、Vite、Node、Python、SQLAlchemy 官方依据见文末；其余工具是本项目选型，不声称官方推荐这一组合。

```text
教师/校管 Web ─┐                      ┌─ activities / versions / runtime
学生可信宿主 ──┼─ TLS / API ─ authz ──┼─ classrooms / attempts / submissions
               │                      ├─ reports / library / transfers
隔离 HTML <─ MessageChannel ─ 宿主    └─ administration / audit
 (不能直接拿凭据或调用业务 API)                    |
                                        PostgreSQL + 私有文件卷
                                             |
                                      durable_jobs / quota
                                             |
                                      独立 worker ─ 模型服务
                                             |
                                      生成草稿 / 有依据的报告

独立实例运维入口 ─ ops 授权 ─ 安装/升级/备份/锁定恢复
```

拟建目录：`apps/web/`、`services/openform/`（模块目录按上图）、`contracts/`（协议/样例/OpenAPI 产物）、`tests/e2e/`、`tests/load/`、`evals/`、`deploy/`。保留 `prototype/` 作为设计验收参考，不将其 localStorage 数据自动升级为真实学生数据。

### 1.2 空间、身份与对象

| 对象组 | 必须固定的关系/约束 |
|---|---|
| 用户、空间、成员 | 教师账号可有个人及多个学校 membership；个人空间也是 workspace；校园停用不删除其个人空间。首发本地账号/密码和邀请接受，不依赖学校 SSO 或邮件服务 |
| 班级、任课、学生 | `student_id` 在空间内稳定，调班不重建身份；班级码仅定位，个人码兑换可撤销会话；快速活动为限定课堂的临时身份，不能按姓名认领历史 |
| 活动、草稿、版本 | 草稿 revision 乐观并发；发布版本固定 HTML、资产摘要、收集字段、题目/答案规则、教学目标和协议版本；课堂只能指向已验证版本 |
| 课堂、参与者、尝试 | 课堂固定活动版本；参与者身份与名单分开；进度按 attempt 保存；一次 attempt 最多一条最终 submission，再做产生新 attempt |
| 回执、事件、文件 | operation 保存请求摘要与回执；事件有去重键，不充当最终提交；附件引用必须是该参与者、该活动授权且已校验的文件 |
| 报告、共享、资源 | 报告绑定源记录集合；共享绑定教师发布的筛选快照；资源版本只含教学资产，无学生身份、回答或访问凭据 |
| 任务、配额、审计 | 任务有请求者/空间/对象/输入版本、lease generation 和结果；配额预留与结算单独记账；审计记录动作及对象，不存学生原始回答或完整凭据 |

所有空间业务表带 `workspace_id`，父子引用使用包含该字段的复合外键。服务端逐对象检查能力（制作、开课、读记录、诊断、导出、共享、交接），不把前端选择的空间/姓名当授权。校园管理默认只能管理成员、名单、任课和配置。活动协作显式授予制作/使用等能力，不自动获得已有课堂学生数据；课堂数据访问需另有明确教学授权。实例运维身份独立于校园管理员。

采用数据库行级安全策略作为空间隔离补充：业务数据库角色非 owner、非超级用户、无 BYPASSRLS；空间上下文只在事务内设置，缺失时拒绝；迁移角色单独使用。行级隔离不能替代活动、课堂和文件的业务权限。连接池切换空间、后台任务换空间、空上下文都须负向测试。[PostgreSQL 行安全说明](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)

首版会话采用服务端可撤销记录与 HttpOnly/Secure cookie，写操作校验 CSRF/Origin；账号密码使用经维护库实现的安全哈希。个人码和邀请凭据仅存摘要、有限有效期、限速；重发码递增授权代次，旧会话同时失效。学校/成员/任课/对象授权变化均影响后续请求，不能只在登录时检查。授权表保留稳定状态行，以便撤销与并发操作共用事务锁点。

班级课堂启动时冻结“计划参与名单”；完成率分母不被以后调班悄悄改写。新加入班级且获准参加的学生列为“额外参与”，不把其完成数混入原名单分子；教师同时看计划名单完成数和全部参与/完成数。移出班级后不能继续该班新写入，但稳定身份仍按本人历史策略读取已完成回执；已开始但失去资格的记录保留，不伪装完成。小组实验按指定记录员的参与单元计数，不把组员人数混成提交份数。快速活动人数未知时显示未知，不显示 0% 或虚构分母。

### 1.3 生成/导入到真实活动

活动协议 `openform.activity/1` 包括 `protocolVersion`、入口、资产清单/哈希、字段 schema、题目语义、服务端评分规则、允许的数据能力。普通 HTML 可预览，但只有完成协议接入和真实试做才可开课；导入失败指出不兼容项并保留草稿。限制不是把导入功能降为静态截图。

首版桥接能力：`ready`、`loadProgress`、`saveProgress`、`appendEvents`、`submit`、`requestUpload`、`getOwnHistory`、`getSharedSummary`。个人历史列表由可信宿主呈现；活动读取历史必须声明用途并限定同一学生、同一活动的必要字段，不提供全空间搜索。评分答案和隐私字段不混入通用运行 manifest。

运行域与应用域分开，活动 iframe 只开启 `allow-scripts`；不开放同源、表单、弹窗、顶层跳转或任意下载。使用服务端 CSP 和固定资产清单限制脚本、图片、字体、子框架和网络连接；不依赖导入 HTML 自己写的 meta 标签。宿主限制 frame 来源/导航，包内外链、重定向、动态加载和外网导航均进入攻击样例验证。运行域不承载 cookie、业务 API、可写用户目录或学生文件公开链接。

宿主核验 iframe 的 `event.source`、一次性握手 nonce 和协议版本后建立专属 MessageChannel；不把 sandbox 的 `origin="null"` 单独当身份。收到消息仍做类型、长度、方法和频率检查；frame 刷新/导航即关闭端口并重新握手。跨 opaque origin 的初次握手不得携带访问凭据或学生数据。宿主持有会话并调用 API，只回传本次活动获准的数据；最终成功状态由服务端回执驱动。

HTML 可以执行脚本，不等于允许不受限制的任意网页。E04 必须在三种浏览器内记录恶意样例的网络请求，覆盖自行导航、外链图片、表单、嵌套 frame、postMessage 冒充和资产 URL 参数外带。如果允许名单无法约束某种能力，拒绝该能力/包并给出兼容性说明；不能以 iframe 存在宣称已经阻止全部泄露。教师审核内容也不能替代运行隔离测试。[MDN iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)、[消息来源校验](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)、[frame-src](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-src)

```text
自然语言/样板/HTML包 -> 草稿 revision N -> 静态协议校验
                                        |不兼容 -> 保留草稿 + 修复说明
                                        v
                               隔离运行 + ready 握手
                                        v
                     真实保存 -> 重新读取 -> 最终提交 -> 服务端回执
                                        v
                    教师核对题意/收集内容 -> 绑定 N 的试做证据
                                        v
                            事务发布不可变 version V
                                        v
                             classroom -> 固定 V
任何草稿修改 -> N+1 -> 验证失效；已发布 V 不改变
```

试做使用单独的 trial 命名空间和数据，不进入学生统计。发布时同时检查草稿 revision、manifest hash、校验结果和试做证据；页面 load 事件不能代替 ready 或回执。生成页的文字、脚本和资源均视为不可信输入，模型输出不能直接运行后端命令。

### 1.4 进度、提交与并发的唯一规则

1. 请求带不可复用的操作键、attempt、expectedRevision 和规范化载荷摘要。唯一约束为 `(workspace, actor, operation, idempotency_key)`；客户端本机待发送队列按真实身份/课堂/attempt 隔离，退出或共享设备换人时清除可读缓存。
2. 事务内重新鉴权，然后查同操作键：同摘要返回原回执，不同摘要报冲突。**已经接收的提交，即使课堂后来结束，也可以按本人权限找回原回执**；不能因为结束状态误报“未提交”。已撤销身份则先拒绝访问，需重新验证身份。
3. 新操作锁定授权状态与课堂开放状态，再更新该 attempt；进度采用 revision 比较，冲突返回当前版本，不能默默覆盖另一设备。最终提交、附件归属、回执、去重操作记录一次提交事务完成。
4. 网络断开/回执丢失时显示“待确认”，按相同操作键查询或重试；数据库不可用保持未知，不能换一个键盲目补交。同一 attempt 即便不同操作键也只有一条最终提交；载荷不同则需显式新尝试。
5. 所有新提交与暂停/结束共享课堂状态锁点；写入持 `FOR SHARE`，关闭状态更新需冲突锁。共享锁允许不同学生同时提交；不可每个学生都独占课堂行。授权撤销同理。`FOR KEY SHARE` 不足以阻止普通状态更新。[行锁冲突关系](https://www.postgresql.org/docs/18/explicit-locking.html)
6. 统一锁序：空间状态 → 身份/授权状态（固定 ID 顺序）→ 活动/班级/课堂 → attempt → 操作/配额记录。批量交接、删除、撤销遵循相同顺序；死锁有限重试，复用操作键。事务内不调用模型、不上传大文件、不等待用户。

```text
本机编辑 -> 待发送 -> API 持久化进度 -> 已保存
                 \-> 超时/断网 -> 待确认 -> 查询相同 operation
最终提交 -> 校验/鉴权/锁定 -> COMMIT [submission + receipt + operation]
                                   |                         |
                                   v                         v
                              返回回执                   响应丢失
                                   |                         |
                                   +---- 相同操作找回 <-------+

课堂: prepared -> open <-> paused -> ended（不可重新开放）
尝试: in_progress -> submitted（不可修改；删除用 tombstone）
再做: 创建新 attempt；统计按每人最近一次已完成尝试取值
```

### 1.5 统计、诊断、异步任务

基础统计由数据库/领域函数计算，区分未参与、进行中、完成、有评分依据与未知；没有答案标准不计算正确率。原始历史不覆盖。生成诊断时在一致性读事务中固定源 submission ID 集合与内容版本、统计口径、名单快照和数据代次，持久化报告输入后结束事务。不能用 `max(id)` 或单个时间戳冒充已提交快照。[PostgreSQL 事务隔离](https://www.postgresql.org/docs/18/transaction-iso.html)

模型只分析规定字段，去掉姓名、进入码和无关身份信息。标准诊断和教师自定义分析均通过固定输出 schema 返回结论、建议、覆盖数量及依据 ID；服务端验证所有引用确在输入集合内。3/10 批成功只能发布标注 3/10 的部分报告；空集合不调用模型，不把失败记录默认为全错。教师复核绑定具体 report ID，不覆盖其他版本。

任务进入 PostgreSQL `jobs`，worker 用短事务 `FOR UPDATE SKIP LOCKED` 领取可运行项、登记租约和递增 generation；业务执行在事务外，完成时校验 generation、权限、源数据代次，过期 worker 无权提交旧结果。这是本项目使用数据库队列的选择；官方说明 SKIP LOCKED 适合队列消费者，但不提供业务一致性快照。[SELECT 文档](https://www.postgresql.org/docs/18/sql-select.html)

跨空间调度只读取无学生内容的 dispatch 索引（task ID、space ID、可运行时间、租约），专用角色仅能领取/维护这些元数据。领取后以该空间事务上下文读取 jobs 输入并重新核验发起者权限；不能给通用 worker 超级用户权限来绕过行安全。创建任务、预留配额、插入 dispatch 必须在同一事务中完成。

配额在排队前原子预留，有任务键和金额/令牌上限；执行前再次核验权限，完成或可判定失败时一次结算/释放。每空间并发初始 1，全实例模型调用并发初始 2，按队列年龄公平轮转；可配置但要压测。超时、429、拒绝、空输出、格式错误分别处理；只对明确可重试错误限次退避。外部调用已经发出但结果未知时标记 `outcome_unknown`，保留费用不确定性，不能承诺外部模型“恰好执行一次”；仅在供应商明确支持幂等时安全重试，否则需查账/人工重试新任务。

生成和分析共用任务、模型适配及配额设施，分开输入/输出协议。首版实现一个经测试的 OpenAI-compatible HTTP 适配，不承诺所有兼容厂商都能无差别工作；配置权与模型凭据在服务端，地址需实例管理员批准并防止请求未授权内部地址。学生无直接模型调用。FastAPI 的普通 BackgroundTasks 不承担这些持久化任务。[FastAPI 官方说明](https://fastapi.tiangolo.com/tutorial/background-tasks/)

删除源记录时先事务标记删除并提高数据代次，使相关报告、共享、导出立即不可读，再异步清理正文/文件；后台发布旧结果必须失败。受控下载每次鉴权，短期服务缓存按空间/对象版本/数据代次分隔；不使用永久公开学生文件 URL。已开始传输的字节和已下载副本无法远程收回，产品如实说明。

### 1.6 图片、资源复用、迁移

- 图片仅 PNG/JPEG，单张不超过 10 MiB、每次最终提交最多 5 张、解码后最长边不超过 4096；验证内容类型、真实解码、尺寸及配额，去除不必要元数据。流式接收、受限解码，不把五张图同时全量装进 API 内存。
- 文件先进入 staging，校验和持久化成功后得到可引用 ID；提交事务验证所有 ID 的空间、身份和状态。存储失败时显示上传失败/待确认，不允许缺失附件的“完整提交”。引用不可变文件，失去引用的暂存对象定时回收，磁盘水位阻止新上传并提示运维。
- 资源发布锁定已经验证的活动版本；复制前和写入时核验发布状态与权限，产生目标空间独立草稿。源资源后来修改/撤回不改写已有副本。校园库只在校内发现，标签和搜索使用数据库索引。
- `openform.resource/1` 与 `openform.archive/1` 分离：前者仅教学资产；后者包含获准课堂历史，只导入只读档案，不自动关联当前同名学生或参与统计。迁移先校验版本/哈希/路径/配额/归属，展示预检，再原子提交数据库清单；失败清 staging。发布单个提交点避免“导入一半成功”。
- ZIP 默认上限建议压缩 20 MiB、展开 100 MiB、500 文件，可由实例配置在配额内调整；拒绝路径穿越、符号链接、嵌套压缩包和外部引用。QuickForm 仅支持明确测试过的样本/字段白名单，报告未支持项，不承诺其任意历史包和 QFLink 都兼容。

### 1.7 分发、升级、恢复

持续集成跑类型/静态检查、单元、真实 PostgreSQL 事务、协议攻击样例与浏览器主流程；版本 tag 生成 API/worker 共用镜像、Web/网关资源、Compose、迁移脚本和示例配置，发布到 GHCR，并提供离线镜像归档、校验和、依赖清单及安装说明。首版受支持目标为 Linux amd64；macOS 是开发环境，桌面安装器仍在 TODOS。真实凭据、数据库和学生材料不得进入镜像或 Git。

升级先备份并校验可用，再迁移、部署和健康探针。采用向前兼容的扩展/迁移/后续清理，应用回滚必须与当前 schema 兼容；不把执行不可逆数据库降级当通用回滚。迁移只能由单个运维任务执行，运行失败保持维护态，旧环境和备份保留。

单机备份采用可见维护窗口：拒绝新写入 → 等待在途事务/任务落定 → 数据库 dump 与不可变文件清单/校验和形成同一备份 → 恢复写入；备份加密并存放到实例外，密钥另存。失败不删除上一次成功备份。保留周期和容量由部署配置明确，不能显示一个未实际执行的备份日期。

校内离线交付必须验证每台学生设备对应用域与运行域的解析和证书信任；容器内部自动获得证书不等于手机已信任。不能把关闭 HTTPS 校验作为正式安装步骤。[Caddy HTTPS 说明](https://caddyserver.com/docs/automatic-https)

恢复只能建新实例，核验 DB、文件、schema 和备份时间，默认 ops-only 锁定。启动注入新实例标识和授权代次，旧 cookie/个人码/邀请/成员授权均不生效；模型密钥重新配置，运维和学校重新授权后才开放。显示备份时间之后的数据缺口，禁止覆盖正在接收数据的原实例。恢复演练是发布门槛，不以“能导出 SQL”代替。

## 2. Code Quality Review：2 项

| ID / 证据 | 采纳 A | 未采用 B / 代价 | 置信度 |
|---|---|---|---|
| C1：`prototype/model.mjs:83,130,152` 集中权限、统计、命令分派；适合作为原型，却不宜复制到三个客户端 | 按 identity/activities/classrooms/analysis/library/transfers 模块分领域函数、用例事务与存储；接口从 OpenAPI 生成 TS 类型，规则只在服务端权威执行 | 延续巨大 command switch 并在三端同步规则，初期少文件但长期重复；A 多些边界文件，便于单独测试 | 9/10 |
| C2：`prototype/store.mjs:29` 依赖完整 state；整合方案:162 的恢复矩阵要求服务错误跨页可找回 | API 错误码稳定、对象路由显式、可见状态统一；复用既有导航和焦点测试语义，React 中按对象 ID 更新 | 将 localStorage 调用机械替换成 fetch，无法正确处理部分失败、过期状态和焦点 | 8/10 |

C1 为组织方式比较，无完整度分数。C2：A 完整度 10/10，B 5/10。借用原型的流程契约与视觉资产，重写实际状态管理；不新建通用插件系统、通用权限 DSL 或自研查询框架。

错误返回 `{code, message, requestId, retryable, details}`，details 只含安全的字段问题；400/422 为输入，401 为需重新验证，403/404 为受限/不可见对象，409 为版本/状态/操作键冲突，413 为大小超限，429 为速率/配额，503 为暂不可用。未知结果不是成功。前端保留输入，任务中心按 task ID 找回结果；路由不得含进入码或令牌。

迁移三端页面时保持全部 23 个页面 ID 和对象上下文（T04/C04/C05 仍为子视图）。生产 URL 采用 `/w/:workspaceId/.../:objectId`，学生入口 `/join/:classroomLocator`、本人历史 `/student/history`；URL 是定位不是权限。管理与教学返回路径保留区域/筛选；固定版本不能回退显示新草稿。组件必须支持中文长文本、390px 学生窄屏、教师折叠菜单、键盘焦点、失权后安全返回。

内联 ASCII 图应落在运行协议、提交事务、任务租约、删除失效和恢复状态模块旁；本轮没有修改原型，其既有说明图不需改写。

## 3. Test Review：8 组缺口

2026-10-05 在评审基线运行 `node --test prototype/tests/*.test.mjs`：**27/27 通过**。未运行不存在的生产构建和后端测试。样本质量：`model.test.mjs:19,35,84` 为 ★★★（行为+边界+错误）、`store.test.mjs:9` 为 ★★★（保存失败不通知成功）、`views.test.mjs:13` 为 ★（大量页面渲染/文本检查）；这不是全项目覆盖率审计。

```text
既有原型: 业务状态/回执/撤销 ★★★ ─ 页面渲染 ★ ─ 导航/焦点定向回归
                                  |
生产链（下列均 GAP，已有的是计划）：
G1 身份/空间/协作 -> 进入/失权/跨租户读取             [->E2E]
G2 生成/导入 -> sandbox -> 真试做 -> 固定发布         [->E2E][->EVAL]
G3 进度 -> 竞态/重试 -> DB回执 -> 暂停/结束           [->E2E]
G4 图片/复制/迁移 -> 校验 -> 原子引用 -> 受控下载       [->E2E]
G5 数据快照 -> 任务/配额 -> 部分诊断 -> 删除失效       [->E2E][->EVAL]
G6 校园任课/停用/交接 -> 生效范围与历史归属           [->E2E]
G7 构建/安装/升级 -> 备份 -> 新实例锁定恢复           [->E2E]
G8 三端页面 -> 跨设备/500人负载 -> 真实课堂            [->E2E]
```

生产路径组的实测覆盖为 0/8；全部 8 组已纳入验收计划。没有发现由本轮文档改动引入的代码回归；迁移原型时导航、筛选、焦点和固定版本的既有回归样例必须保留。所有新增公共函数跟随功能交付测试，行/分支覆盖目标至少 80%，安全、并发和故障路径逐项验收，百分比不能抵消关键漏测。

| GAP | 计划测试文件（尚未创建）及关键断言 | 层级 / 原验收 |
|---|---|---|
| G1 | `services/tests/integration/test_authorization.py`：A 校/个人/B 校同 ID 猜测、校管答案拒绝、协作与数据权限分开、cookie/码代次、连接池换空间 | DB/API + E2E；Q3/Q6 |
| G2 | `tests/e2e/authoring-runtime.spec.ts`、`evals/generation/`：真实 HTML 保存重读/提交才可验证；改一个字需重验；旧课堂不变；注入/外传/伪造消息被阻止 | E2E + EVAL；Q1 |
| G3 | `services/tests/integration/test_submission_races.py`：100 次同键同载荷一回执，同键异载荷 409；断响应后查回执；不同键同 attempt 不重复；暂停/撤销/两设备两个顺序 | 真实 DB 并发；Q2/Q4 |
| G4 | `services/tests/integration/test_assets_transfers.py`：10 MiB/4096/5 张边界、伪图、越权 ID、磁盘满、撤回与复制竞态、ZIP 穿越及中断回滚、档案不计当前统计 | API/文件 + E2E；Q2/Q7 |
| G5 | `services/tests/integration/test_jobs_reports.py`、`evals/analysis/`：worker 双执行/失租、配额抢占、429/未知结果、3/10 覆盖、伪造引用、删除与发布两个顺序 | DB/worker + EVAL；Q5/Q8 |
| G6 | `services/tests/integration/test_school_lifecycle.py`：同名学生/调班、名单分母不漂移、双身份用户停用、无接收人、交接中接收人失效、任课撤销影响数据访问 | API + E2E；Q3/Q6 |
| G7 | `tests/e2e/operations.spec.ts`、`deploy/tests/`：干净主机安装、升级失败维护态、备份缺文件拒绝、旧备份不能复活旧授权、断公网课堂可用 | 容器/恢复；Q9 |
| G8 | `tests/e2e/classroom.spec.ts`、`tests/load/classroom.js`：23 路由主要入口/退出/失权、三浏览器、两真实设备、500 并发和现场试点 | E2E/负载/人工；Q1–Q9 |

每组统一比较 A“本层真实依赖测试+错误恢复验收”（完整度 10/10）与 B“只保留原型/正常路径”（分别 3/4/3/4/4/4/3/4），均采纳 A。8 项置信度均 9/10：仓库中尚无这些生产层，不把其缺失描述成现有产品漏洞。

并发测试使用事务屏障/受控故障注入，分别固定先提交/先关闭、先授权检查/先撤销、先取快照/先删除；不用随机 sleep 偶然碰撞。模型测试分两层：受控假供应商验证重试/配额/状态；固定合成教学样本调用获准真实模型并由教师标注基准评估。输入注入不能改变系统指令，引用越界/越权为硬失败；教学价值由教师评价，不能让同一模型自评即通过。比较固定 prompt/model/version 与上一批准基线，记录版本、成功率、成本、覆盖和失败样本，提示词修改必须重跑。

## 4. Performance Review：2 项

| ID / 证据 | 采纳 A | B 及取舍 | 置信度 |
|---|---|---|---|
| P1：`prototype/model.mjs:130` 扫本机集合；需求:319/383 提出 1 万记录和 500 人，但未规定负载形状 | 分页/聚合查询、关键索引、受限轮询与明确压测模型；需要测量而非外推 | 直接迁移全量 state、每次拉全班答案；简单但内存/网络增长失控。A 10/10，B 4/10 | 8/10 |
| P2：需求:379 的任务、上传、备份争用可能拖慢上课 | API/worker 资源隔离、池上限、队列背压、流式文件；大备份使用维护窗口 | 先上 Redis/WebSocket/多机也可，但不能先解决业务口径及真实瓶颈；类型不同不评分 | 8/10 |

课堂概览先用 HTTP 轮询：教师可见页每 3 秒取聚合摘要，学生每 5 秒取课堂状态，带随机抖动和隐藏页降频；输入本机即时保留，进度合并最多每 5 秒一次，最终提交立即发送。暂停/结束的最终判定在服务端，轮询延迟不构成写入许可。先不引入 WebSocket/Redis；若实测不能达到目标，再按观测数据升级传输或缓存。

索引至少覆盖 `(workspace_id, classroom_id, participant_id)`、attempt 唯一最终提交、幂等唯一键、课堂更新时间/分页游标、job 状态/next_run_at、资源标题/标签。查询返回分页 DTO，统计 SQL 批量聚合，禁止逐学生读进度的 N+1；1 万记录导出流式进入异步任务。缓存键含空间、对象版本和数据代次，权限每次核验；学生原始回答不进入公开 CDN。

初始压测环境约定为 Linux amd64、8 vCPU/16 GiB、SSD、独立压测客户端；记录实际 CPU 型号、盘、网络和镜像 digest。这是可比较的测试预算，不是已验证硬件推荐。API 初始 4 进程，每个连接池 5、溢出最多 2；worker 池总计最多 4，另留运维余量，数据库连接上限和查询/锁等待超时明确配置，防止无限排队。

负载：10 教师 × 50 学生，30 分钟稳态；学生 5 秒一次状态读取与进度合并（约各 100 次/秒），教师摘要约 3.3 次/秒；最终提交 500 次分布于 5 秒，并加一轮同秒突发。分别测试无图片和 50 个并行 1 MiB 图片上传，另测允许上限的大图及 1 万历史记录导出；并行两任务模型故障/worker 重启。无故障、有效已验证请求的普通最终提交从完整请求收到至回执 p99 ≤2 秒，课堂摘要新鲜度 ≤5 秒；故障阶段考核不假成功、不丢已确认数据、恢复后可查询，不要求数据库宕机时仍满足 2 秒。

观察 API 延迟/错误、锁等待、重复键命中、队列年龄、预留/结算、磁盘水位、CPU/内存和备份年龄。日志只用 request/operation/task/object ID，不记录进入码或学生答案。自动负载不能代替学校 Wi-Fi、手机/平板、投影和真实课堂验收。

## 5. Failure Modes Registry

以下“处理/测试”均是强制实施要求，当前生产实现和生产测试均未完成。计划中没有“既无处理又无测试且静默”的未处置路径；因此未处置的计划 critical gap 为 0，不表示当前原型可上线。

| 路径 | 现实失败 | 处理与可见恢复 | 测试 |
|---|---|---|---|
| 账号/码/邀请 | 失效会话仍停留在页面 | 服务端拒绝，回正确课堂/登录，保留安全的返回目标 | G1/G6 |
| 生成/修改 | 429、空输出、超时、格式不符 | 草稿保留，明确排队/失败/结果未知，不显示已完成 | G2/G5 |
| 导入/运行 | HTML 外带数据、协议未就绪 | 拒绝不兼容包/能力，保留问题说明，禁止开课 | G2/G4 |
| 试做/发布 | 试做后另一教师改稿 | revision/hash 不符拒绝发布，提示重新试做 | G2/G3 |
| 保存/最终提交 | DB 已提交但响应丢失 | 待确认，同键查原回执，禁止假成功或重复计数 | G3 |
| 暂停/撤销 | 与学生写入同时发生 | 共用事务锁点，确定两个合法顺序，显示当前状态 | G1/G3 |
| 图片/文件 | 解码炸弹、磁盘满、引用他人文件 | 流式限额和归属核验，失败不可附着，提示重传 | G4 |
| 统计/报告 | 批次失败、源记录删除 | 显示实际覆盖；过期证据/报告不可读，不补造全班结论 | G5 |
| worker/配额 | 双执行、失租、外部费用未知 | generation 阻止旧结果，账本一次结算，未知保留查账状态 | G5 |
| 校内复制/交接 | 源撤回/接收人停用 | 事务重查，失败保留原归属；副本成功后独立 | G4/G6 |
| 导入/导出 | 恶意 ZIP、版本不支持、中途失败 | 预检+原子清单+staging 清理；任务可查明确失败 | G4 |
| 安装/升级/恢复 | 迁移失败、备份缺文件、旧授权复活 | 维护态/新实例锁定/校验失败不开放，原实例保留 | G7 |
| 前端/课堂容量 | 网络慢、列表超长、后台任务抢资源 | 保留输入、分页、背压、可查询任务；现场验证 | G8 |

## 6. What already exists / NOT in scope

已有：正式需求和决策、UI/VI/品牌资产、23 页整合原型、27 个通过的原型测试及设计回归记录。复用需求、合成教学样例、流程和视觉，不重复设计首页、Logo 或更换风格。现有 iframe 静态预览、本机模拟模型/任务/恢复不被登记为生产能力。

本轮不实现应用、不创建云资源、不部署、不发 PR 或合并；本次只生成工程文档和任务。首版不做完整教务、公共资源市场、任意后端代码运行、通用 IDE、自动正式成绩、音视频/图片 AI、离线桌面安装器或学校 SSO。后三项已有 [TODOS.md](../../TODOS.md) 及触发条件，本轮新增 TODO 提案 **0 项**。微服务、Redis、WebSocket、多机高可用留待实测瓶颈，不以未来扩容为由推迟当下权限或可靠性。

## 7. Implementation Tasks

所有路径是拟建目标，不是现有代码。人工/AI 投入采用相对规模 M/L/XL，仓库无可核验的压缩系数，故不编造小时或 AI 工期；AI 不能代替教师评估和课堂观察。全部任务均来自本次发现，均为首版发布前 P1。

| 任务 | 工作与来源 | 目标模块/路径 | 依赖 | 完成证据 | 人工 / AI 辅助 |
|---|---|---|---|---|---|
| E01 | 固定对象、权限、活动协议与三类合成教学样例；A1–A4/G1–G3 | `contracts/` | — | 字段/错误/授权矩阵和正反例可执行；原 T1/T3 | L / M |
| E02 | 建工程骨架、依赖锁和 CI；A1/A7/C1/G7 | `apps/web/`、`services/`、`.github/workflows/` | E01 | 干净环境安装，类型/单元/真实 DB 冒烟通过；原 T2/T9 | M / M |
| E03 | 实现账号、个人/校园、任课、稳定学生与协作授权；A4/G1/G6 | `services/openform/identity/`、`services/tests/` | E02 | 权限矩阵逐格允许/拒绝、撤码/换空间；原 T2 | L / L |
| E04 | 实现隔离 runtime 和可信桥接；A2/G2 | `apps/web/runtime/`、`services/openform/runtime/`、`tests/e2e/` | E01–E03 | 三浏览器协议与恶意样例通过；接 E05 后真实数据验证；原 T3 | XL / L |
| E05 | 实现版本、课堂、进度、事件、提交和确定性统计；A3/G3/P1 | `services/openform/activities/`、`services/openform/classrooms/`、`services/tests/` | E03/E04 | 双设备、同键 100 次、状态竞态、名单快照通过；原 T3/T4 | XL / L |
| E06 | 接入持久化生成任务及制作/试做/发布 API；A2/A5/C1/G2 | `services/openform/authoring/`、`services/openform/jobs/`、`services/openform/models/`、`evals/generation/` | E05/E07 | 真模型与支持的外部 HTML 均可真实试做；修改须重验；原 T5 | XL / L |
| E07 | 实现受控图片与文件生命周期；A6/G4/P2 | `services/openform/assets/`、`services/tests/` | E05 | 上限、伪图、越权和存储失败样例；原 T4 | L / M |
| E08 | 按既有设计实现三端页面与任务恢复；C2/G8 | `apps/web/`、`tests/e2e/` | E04；真实验收依赖 E05/E06/E07/E09/E10/E11 相应 API | 23 页、三端主流程、原型回归、窄屏/焦点通过；原 T5/T6 | XL / L |
| E09 | 实现快照诊断、自定义分析、共享复核、配额与故障处理；A5/G5/P2 | `services/openform/analysis/`、`services/openform/jobs/`、`evals/analysis/` | E06/E07 | 部分覆盖、伪造依据、失租、费用未知、删除竞态通过；原 T7 | XL / L |
| E10 | 实现校园成员生命周期、交接和版本化资源库；A4/A6/G6 | `services/openform/school/`、`services/openform/library/` | E05/E06 | 同校两教师复用且数据隔离，停用/交接竞态通过；原 T8 | L / L |
| E11 | 实现资源/档案包、预检、异步导出和受控下载；A6/G4 | `services/openform/transfers/`、`services/tests/` | E07/E09/E10 | 支持清单往返、恶意包拒绝、档案隔离；原 T8 | L / L |
| E12 | 交付 Linux 安装、升级、观测、备份与锁定恢复；A7/G7/P2 | `deploy/`、`.github/workflows/`、`docs/operations/` | E05–E11 | 干净主机、断公网、升级/恢复演练与离线包；原 T9 | XL / L |
| E13 | 执行性能、模型和真实课堂发布门槛；G8/P1/P2 | `tests/load/`、`evals/`、`docs/acceptance/` | E08/E12 | 500 人报告、3 类活动、3–5 教师/1 校管/5–10 节课证据；原 T10 | L / L + 人工现场 |

配套机器清单：[eng-implementation-tasks.jsonl](../planning/eng-implementation-tasks.jsonl)。测试人员入口：[工程测试计划](../reviews/openform-engineering-test-plan.md)。每项实现时补齐具体运行命令；本轮未声称未来命令已经运行。

里程碑 M1：E01–E07、E10 的资源发布/独立复制能力，加 E08 对应的制作/开课/学生/结果/复用页，真实词汇课堂与两教师隔离、复用通过。M2：完成 E08–E11 的剩余部分，测验/实验、分析、校内管理交接与迁移齐备。M3：E12–E13，托管和校内交付、负载与真实课堂验收；三个里程碑合起来才是首版范围。

## 8. Worktree parallelization

| Lane | 模块与顺序 | 何时开始 |
|---|---|---|
| A：基础 | E01 → E02 → E03 → E04；contracts/、基础 services/、runtime/ | 先顺序完成并合并协议基线 |
| B：后端 | E05 → E07 → E06 → E10 的资源复用 → E09 → E10 其余部分 → E11；services/、services/tests/、evals/ | A 后，与 C 可并行；共享数据库迁移/任务模块，Lane 内顺序 |
| C：前端 | E08；apps/web/、tests/e2e/ | A 后，与 B 可并行；先用契约模拟，最终串真 API |
| D：发布与验收 | E12 → E13；deploy/、CI、tests/load/、验收证据 | B/C 完成整合后，顺序发布验证 |

4 条 lane；B/C 两条可并行，A/D 为前后顺序门槛。E04 的 web/runtime 与 E08 共享模块，必须先合入 A；B 不修改 Web/E2E，C 不修改后端迁移。contracts/ 若变更先集中合并，双方再更新生成代码。分支只能暂存自身产物。此处是未来并行策略，本轮没有启动并行编码代理。

## 9. Completion Summary

| 项目 | 本轮结果 |
|---|---|
| Step 0 | 保留正式范围，收敛实现结构和首个里程碑 |
| Architecture / Code Quality | 7 / 2 项，方案均纳入 |
| Test Review | 已绘覆盖图；8 组生产测试缺口进入任务 |
| Performance | 2 项，定义测试环境/负载/指标与背压 |
| NOT in scope / What already exists | 已写明 |
| TODOS | 0 项新增提案，保留原 3 项 |
| Failure modes | 13 条路径有处理和测试计划；未处置的计划 critical gap 0 |
| Outside voice | 按当前 `codex_reviews=disabled` 跳过，没有跨模型复核结论 |
| Parallelization | 4 lanes；2 条可并行、2 条顺序门槛 |
| Lake Score | 16/16 次完整方案优于缺项捷径的比较采纳完整方案；另 3 项为类型比较 |
| Unresolved decisions | 0；实施、容量、安全和现场效果仍待上述验证 |

## 10. 官方资料与本项目推导

检索日期 2026-10-05，工具为官方网页读取（本机 Aside 不可用）。以下支持机制判断，技术组合和资源参数是本项目决策，并非供应商保证。

- [React 19](https://react.dev/blog/2024/12/05/react-19)、[Vite 环境要求](https://vite.dev/guide/)、[Node 24 LTS](https://nodejs.org/en/blog/migrations/v22-to-v24)、[Python 支持状态](https://devguide.python.org/versions/)：核对主版本路线；安装时仍锁定当时经验证的补丁。
- [SQLAlchemy 事务](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)：用例事务边界依据；跨对象锁序由本项目明确。
- [PostgreSQL 行锁](https://www.postgresql.org/docs/18/explicit-locking.html)、[行级安全](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)、[SELECT/SKIP LOCKED](https://www.postgresql.org/docs/18/sql-select.html)、[事务隔离](https://www.postgresql.org/docs/18/transaction-iso.html)：分别支持竞态、租户防护、任务领取、一致性报告设计。
- [MDN iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)、[postMessage](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)、[frame-src](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-src)：运行隔离与消息校验的基础，不构成本项目安全验收。
- [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)：普通后台任务的适用边界；持久化数据库队列是本项目推导。
- [Docker Compose 生产配置](https://docs.docker.com/compose/how-tos/production/)、[GitHub 镜像发布](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)、[Caddy HTTPS](https://caddyserver.com/docs/automatic-https)、[k6 指标](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/)：单机分发、TLS 与压测实现的官方入口；交付效果仍须实测。

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---|---|---|
| CEO Review | 历史 `/plan-ceo-review` 文档 | 已确认主功能范围 | 本轮 0 | 沿用；非本轮重跑 | D1–D14，未重开产品方向 |
| Eng Review | 本轮 `/plan-eng-review` | 架构/质量/测试/性能 | 1 | CLEAR (PLAN) | 19 项已形成计划；0 未处置计划关键缺口 |
| Design Review | 已合并页面方案/整合检查 | 页面与视觉基线 | 本轮 0 | 沿用；非本轮重跑 | 23 页原型，27 项原型测试本轮通过 |
| Outside Review | codex host / claude-code provider | 独立第二意见 | 0 | disabled | 当前配置关闭；无外部复核覆盖 |
| DX Review | 未调用 | 开发体验 | 0 | 未运行 | 无结果 |

**OUTSIDE COVERAGE:** plan-review / claude-code / disabled；未启动外部 CLI 或替代子代理。新分支无既有 review log，历史状态以对应仓库文档引用，不伪造本轮运行次数。

**VERDICT:** 工程计划评审完成，可以开始 E01–E04；完整产品发布仍必须完成 E01–E13 的实现与验收。

NO UNRESOLVED DECISIONS
