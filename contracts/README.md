# 活动协议 v1 与权限契约

E01 是可执行契约和合成教学样例。它没有 API、数据库或运行隔离；真实桥接在 E04、服务端持久化回执在 E05 实现。

协议版本为 `openform.activity/1`。`schemas/` 定义活动清单、操作请求、桥接请求、握手、错误、回执和私有评分规则。Python 包提供字段验证和默认拒绝的对象权限判断，后续 API 复用同一包；前端使用同一 JSON Schema。

## 数据与信任边界

| 对象 | 固定语义 |
|---|---|
| Workspace | 个人或校园空间；加入校园不迁移个人资产。每个业务对象带服务端核验的空间标识。 |
| Member / Student | 成员角色与稳定学生标识分开。换码、换班不新建学生身份；临时参与者只在单次课堂范围有效。 |
| Activity / Draft / Version | 活动拥有者、可变草稿及不可变发布版本分开；每次课堂固定一个版本。 |
| Classroom / Participation / Attempt | 开展实例、参与身份和主动重试分开；名单快照与额外参加者分开。 |
| Progress / Submission / Receipt | 进度可修订；完成提交保留历史。只有数据库事务提交后才返回回执，客户端暂存不等于已保存。 |
| Event | 仅记录页面明确上报的事件；事件标识去重，不推断未采集的行为。 |
| Job / Report / ResourceVersion | 持久任务、固定数据快照报告及不含学生记录的资源版本分开。 |

`AccessFacts` 只能由 API 从可信身份、空间、对象归属及授权记录构建。它不是请求 DTO，空间与成员有效性默认拒绝，必须显式核验。客户端的角色、姓名、班级、空间标识不能用于直接调用权限判断。E03 将实现事实获取和权限变化的事务检查。

- 校园管理员管理成员、班级和模型配置；查看学生回答需要另外的教学授权。
- 教师查看本人或明确授权的对象。`activity.edit` 不隐含发布、查看回答或导出权限。
- 班级开展要求可使用活动及有效任课关系；快速开展可不建班，但仍要活动使用权限。
- 学生仅访问已核验的本人数据和教师开放的汇总。运维备份/恢复权限独立于空间管理员。

## 活动数据

清单声明相对资源路径及 SHA-256、入口、题目和数据路径、过程与提交字段 schema，以及能力列表。正确答案和分值放在仅服务端可读的私有评分文件中，禁止加入发给学生的清单。客观题首版采用 `equals` 规则；开放回答保留原文供教师复核，不自动伪造分数。

字段 schema 是 JSON Schema 2020-12 的有界子集：对象、数组、字符串、数值、布尔、null，及对应类型长度/范围、标量枚举/常量。对象必须关闭额外属性；数组最多 100 项，schema 深度最多 8 层，每对象最多 100 个字段。字符串必须显式限长至 16000 字符以内，或使用有界的枚举/常量。拒绝引用、正则、组合分支、自定义格式和网络解析。`validate_data` 和 `validate_grading` 的前提是清单已通过 `validate_manifest`。

`examples/words`、`quiz`、`lab` 分别是词汇闯关、随堂诊断、实验探究。HTML 是资源包样例，页面当前明确显示桥接尚未实现；不能作为隔离验证或已提交证据。数据完全合成。

## 桥接与恢复

启动信封仅带版本、阶段和 256 位 nonce。E04 必须核验 `event.source`、nonce、版本，再建立专用 MessageChannel；活动 iframe 不接触会话、个人码和平台凭据。

八个方法为 `ready`、`loadProgress`、`saveProgress`、`appendEvents`、`submit`、`requestUpload`、`getOwnHistory`、`getSharedSummary`。每个方法有独立参数约束，身份和 attempt 由宿主绑定。消息上限 64 KiB，JSON 深度最多 32；调用频率、能力授权及上下文生命周期由 E04 检查。本人历史还要求清单说明用途和服务端允许的范围。

写请求使用 `idempotencyKey`、`expectedRevision`、结构化 `data`。同键同载荷重试返回原回执；同键不同载荷返回 `IDEMPOTENCY_CONFLICT`。版本过期返回 `REVISION_CONFLICT`；不静默覆盖。一个 attempt 只完成一次，主动重做必须创建新 attempt。E05 负责唯一约束、课堂状态锁及事务落盘。

错误固定含 `code / message / requestId / retryable / details`；details 只包含字段路径和规则，不包含提交值，路径超过 300 字符时截断。`RESULT_UNKNOWN` 需要查询原请求回执，不擅自宣告成功。回执固定包含 `receiptId / attemptId / revision / state / receivedAt`。

## 本地验证

依赖由 uv 锁定，Python 3.13：

```sh
uv sync --project contracts
uv run --project contracts pytest contracts/tests --cov=openform_contracts --cov-report=term-missing --cov-fail-under=80
```

这里只验证契约、教学样例和权限矩阵，不替代后续真实 PostgreSQL、浏览器 QA 或课堂验收。
