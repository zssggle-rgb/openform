<h1><img src="assets/brand/svg/openform-logo-primary.svg" alt="OpenForm" width="280"></h1>

面向教师和学校的互动教学活动平台，支持活动制作、课堂参与、持续数据保存、教学诊断和校内资源复用。

## 当前阶段

E01–E12 已有源码，Q1–Q5 已在腾讯云真实应用验证各组主要流程。当前支持隔离页面、真实试做与固定发布版本、课堂开停、进度和最终回执、私有图片、火山引擎模型生成/修改、页面包导入、同校教师独立复用及有依据的教师复核诊断。Linux amd64 离线包已实际生成，完成同主机新容器卷安装、维护升级、加密备份、实例外拷贝和新实例锁定恢复。模型初稿仍需试做与教师检查，QA 的具体未验证边界见报告。真实校园现场、独立干净物理主机和 500 人容量验收未进行，E13 保持开放。23 页交互原型继续作为设计参考，不能作为产品后端或课堂验收证据。

教师版与校园版使用同一核心。首发教学场景为随堂测验、词汇/概念闯关和实验探究；首个里程碑是完整跑通一次词汇闯关课堂，并验证同校两位教师的数据隔离和活动复用。

## 需求与开发入口

- [HTML 用户使用说明](apps/web/guide.html)：先介绍软件用途，再分别说明教师、校园管理员和学生的使用方法；部署后访问 `/guide.html`，各角色顶栏均有“使用说明”入口。开发与部署资料见下方独立文档。
- [正式需求方案](docs/designs/openform-classroom-platform.md)：主要功能、范围、验收条件和 T1–T10 实施任务。
- [工程方案与评审](docs/designs/openform-engineering-plan.md)：技术选型、数据与权限边界、活动运行协议、可靠提交、实施顺序和发布门槛；配套[工程测试计划](docs/reviews/openform-engineering-test-plan.md)与[工程任务清单](docs/planning/eng-implementation-tasks.jsonl)。
- [腾讯云 QA 环境](docs/operations/test-environment.md)：`https://www.openforgeai.cn` 已部署 E01–E12 应用，独立运行域为 `https://of.openforgeai.cn`；两者使用 HTTPS，环境不部署交互原型。
- [Q2 主流程报告](docs/reviews/qa-q2-2026-10-05.md)：词汇课堂、实验图片、暂停后恢复、学生最终回执和教师结果的实际证据及验证范围。
- [Q3 主流程报告](docs/reviews/qa-q3-2026-10-06.md)：实际模型生成/修改、页面包导入、同校两位教师复用课堂、诊断依据及学生摘要的证据和限制。
- [Q4 集成报告](docs/reviews/qa-q4-2026-10-06.md)：三端路由、策略、档案交接与删除、资源及档案往返，和本轮修复的定点证据。
- [Q5 安装恢复报告](docs/reviews/qa-q5-2026-10-06.md)：发行包及镜像摘要、实际备份/恢复、旧凭据失效和重新授权开放的证据。
- [发布与课堂试用状态](docs/acceptance/release-gates-2026-10-06.md)：源码、QA、容量及真实课堂分别记录，现场缺项保持开放。
- [活动制作与模型配置](docs/operations/authoring.md)：E06 生成、修改、导入、任务恢复与额度账本；实际联动范围见 Q3 报告。
- [校园资产与资料生命周期](docs/operations/school-lifecycle.md)：E10b 交接、保留/删除、额度与模型开关；实际验证范围见 Q4。
- [资料导入导出](docs/operations/transfers.md)：E11 固定版本资源包、课堂档案、预检确认与下载权限；实际验证范围见 Q4。
- [应用页面与入口](docs/operations/pages.md)：E08 教师、校园管理和学生端真实路由、操作及权限边界。
- [Linux 安装与备份恢复](docs/operations/linux-operations.md)：E12 离线分发、独立运维 O01、维护升级、加密备份和新实例锁定恢复；实际结果以 Q5 记录为准。
- [工程开发跟踪](https://github.com/zssggle-rgb/openform/issues/2)：E01–E13 的 Issue、依赖顺序、逐任务 review 和分组 QA。
- [活动协议](contracts/README.md)与[工程启动](docs/operations/development.md)：当前可执行契约、锁定依赖及真实数据库验证方法。
- [账号与校园开通](docs/operations/identity.md)：E03 首批入口、权限边界和部署运维的学校激活方式。
- [页面与主流程方案](docs/designs/openform-page-plan.md)：22 个业务页面及独立运维页面的职责、导航与状态。
- [整合原型使用说明](prototype/README.md)与[本轮验证记录](docs/reviews/page-integration-2026-10-05.md)：实际连通范围、测试证据及未验证边界。
- [页面设计评审记录](docs/reviews/openform-page-design-review-2026-10-04.md)：10 项设计修订、七项检查、结构线框证据及验证限制。
- [QuickForm 项目研究](docs/research/quickform-study-and-openform-proposal-2026-10-04.md)：参考项目的价值、源码依据和重做建议。
- [需求评审记录](docs/reviews/openform-ceo-review-2026-10-04.md)：已确认决定及评审过程。
- [结构化任务清单](docs/planning/ceo-implementation-tasks.jsonl)：与需求方案对应的 10 项待实施任务，路径和投入仍需工程拆解。
- [后续候选](TODOS.md)：独立教师安装包、学校统一身份及多模态辅助分析。
- [开发约定](AGENTS.md)：代码、验证、数据和 Git 操作规则。
- [UI 设计规范](DESIGN.md)：继承 AdPilot 风格，定义教师、校园和学生界面的视觉基线。
- [UI 设计交付记录](docs/reviews/openform-ui-style-2026-10-04.md)：参考依据、页面预览位置与实际验证范围。
- [VI 使用规范](docs/brand/visual-identity.md)与[品牌资产](assets/brand/README.md)：Logo、图标、单色版本、封面和导出来源。

## 设计预览

启动整合原型（在仓库根目录运行）：

```sh
python3 -m http.server 8772 --bind 127.0.0.1
```

打开 [OpenForm 整合原型](http://127.0.0.1:8772/prototype/#G01)。选择林老师进入工作台，从课堂的“学生参与入口”打开另一个标签页即可演示跨角色联动。原型源码在 `prototype/`，不依赖构建服务或外部 CDN。

原型检查命令（本轮使用 Node.js 23.11.0）：

```sh
node prototype/check.mjs
node --test --experimental-test-coverage prototype/tests/*.test.mjs
```

测试只验证原型领域规则、存储适配与页面呈现；浏览器主流程另有实际走查记录，不代表产品后端或校园现场验收。

原有 VI 和 UI 设计入口继续保留：

```sh
python3 -m http.server 8768 --bind 127.0.0.1
```

打开 [VI 展示](http://127.0.0.1:8768/brand.html)或 [UI 预览](http://127.0.0.1:8768/preview.html#activities)。预览源文件为 `brand.html` 与 `preview.html`，均使用本仓库的品牌资产；预览数据为合成样例，不连接真实课堂。

## 开发流程

`main` 为基线分支，从最新的 `main` 创建功能分支，小步提交。常用操作：

```sh
git switch main
git pull --ff-only
git switch -c feat/activity-core
```

提交前检查 `git status` 和 `git diff`，使用明确文件路径暂存，再检查 `git diff --cached`。保持需求变更、代码实现、测试结果和部署验收可区分。

工程基线采用 Node 24、React 19 / TypeScript / Vite、Python 3.13 / FastAPI / SQLAlchemy、PostgreSQL 18。Python workspace 使用根目录 `uv.lock`，前端使用 `apps/web/package-lock.json`。本机原型的原生 JavaScript 只作为设计参考。

按用户确认的流程，每项任务开发完成后做一次 `/review`，完成可联动的一组功能后做一次 `/qa`。不自行新增测试内容、覆盖率工作或额外测试运行。PR CI 默认仅做格式、类型与构建检查，合并 main 不重复执行；现有自动化测试保留，只有明确手动触发工作流并选择 `run_tests` 才运行。不把健康接口检查称为浏览器 QA。

`.env`、模型密钥、学生真实记录、上传文件和本地数据库不进入版本库。示例配置仅使用占位值；测试使用合成数据。

## 参考与许可

本项目参考 [QuickForm](https://github.com/wstlab/quickform) 的开放网页数据接入思路，计划新建共享核心；当前仓库没有复制其产品源码。后续引用第三方代码时保留所需许可和来源说明。

仓库许可证见 [LICENSE](LICENSE)。
