# 制作、模型任务与页面导入

E06 提供教师自然语言生成/修改、持久化任务、文本 HTML/CSS/JS 生成包、带数据约定的外部 HTML 与 OpenForm JSON 页面包导入。保存后仍须完成当前草稿的真实保存、读取和最终提交试做，由教师确认内容，再发布固定版本。修改草稿不会改动已发布课堂；原试做证明不能用于新草稿。

## 模型配置

首个适配为用户指定的火山引擎方舟，地址 `https://ark.cn-beijing.volces.com/api/v3`，模型 `deepseek-v4-flash-ga-260731`。当前仅批准这一地址，不接受教师在 UI 填任意 URL。使用非流式 `POST /chat/completions`，Bearer 凭据、`messages`、`max_completion_tokens`，从 `choices[0].message.content` 与 `usage` 读取结果。[方舟官方 Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=en)

私有密钥文件 `.local/secrets/model-api-key.txt` 不进入 Git；Compose 以 secret 挂载到 API/worker 的 `/run/secrets/model_api_key`。API 仅报告是否配置，不返回密钥。没有模型仍可导入、试做、开展已发布课堂；学生不能调用模型。

默认每空间累计额度 1,000,000 tokens，排队前以 UTF-8 输入字节上界加输出上限原子预留；最多 20 个待处理任务、每空间运行 1 个、实例同时运行 2 个。已报告用量一次结算；缺少用量按预留上界计入，未知费用保留预留，不伪装成零。额度不是人民币费用估算，不自动按日重置。

429 尊重间隔，最多 3 次明确限流尝试。超时、响应中断、供应商不确定错误和调用后 worker 中断为 `outcome_unknown`，不自动重新调用；教师核对供应商记录后可手动创建新任务。未返回完整内容、非法包和草稿版本冲突均不能替换原草稿；可用原输出在任务详情中保留为文本，不执行。

## 任务和权限

PostgreSQL 持久化 jobs、输入草稿版本、操作键、额度预留及结果。独立 `openform_dispatch` 角色只读取/更新调度元数据及实例维护开关，没有学生内容或 jobs 表权限；业务 worker 持有受 RLS 约束的 app 连接，领取后再次核验发起者身份、会话、空间和对象权限。

短事务领取使用 SKIP LOCKED、租约和 generation。模型调用在事务外。结果落库须同代、未失租、权限仍有效且草稿仍是输入版本；草稿保存、任务结果与额度结算同一事务提交。调用标记先于模型请求提交；标记后崩溃宁可保留未知费用，不宣称外部模型恰好执行一次。

旧数据库在 0007 迁移前需 provision dispatcher；新数据库初始化已包含该角色。私有目录新增 `database-dispatch.txt`（随机凭据，0600）。将 `deploy/database/provision-dispatch.sh` 和凭据挂载到 PostgreSQL 容器，以 bootstrap 角色执行该脚本；随后以 migrate 角色运行 Alembic。不能给 worker 业务连接超级用户或 BYPASSRLS 权限。

## 导入格式和限制

制作器支持选择 UTF-8 `.html`，同时提供活动清单及服务端答案标准；也支持包含 `manifest`、base64 `assets`、`grading`、`expected_revision` 的 JSON 包，与既有活动 DraftInput 相同。可从已打开活动读取现有文件作为起点；清单包含每个收集字段、进度和最终提交 schema。单页没有接入 SDK 时不能获得试做通过标记。

包校验复用 E04 编译器：资源精确声明、哈希匹配、原始资源 8 MiB、编译文档 12 MiB、支持类型白名单，禁止外部网络资源、form、iframe、模块及内联事件。生成包首版只生成 UTF-8 HTML/CSS/JS；修改输入 ≤128 KiB，二进制资源需手动导入修改，不静默截断。外部包仍可携带编译器支持的私有静态资源。

兼容性失败原包保存到当前空间的受限导入记录，原活动不变；UI 提供恢复上次导入文件。每空间原导入包累计上限 100 MiB，达到上限会拒绝新文件并要求保留本地文件，不假报保存成功。原模型输出只显示文本，只有通过编译的活动才进入独立域试做。

## 当前验证状态

源码开发及一次 `/review` 随本任务记录；PR 只进行格式、类型与构建检查，不新增/运行自动化测试。真实模型生成、外部页面试做、修改后重验与校内复用、诊断在 Q3 统一做一次浏览器 QA。当前不能把适配代码描述为供应商已验收，也不以模型自评替代教师内容评价。
