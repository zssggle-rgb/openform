<h1><img src="assets/brand/svg/openform-logo-primary.svg" alt="OpenForm" width="280"></h1>

面向教师和学校的互动教学活动平台，支持活动制作、课堂参与、持续数据保存、教学诊断和校内资源复用。

## 当前阶段

项目已开始工程实现：E01 活动协议与权限契约已合并，E02 建立 React / FastAPI / PostgreSQL 工程骨架和按改动范围运行的 CI。当前应用仅提供服务就绪检查；正式登录、课堂持久化和模型生成由后续任务实现。23 页交互原型继续作为设计参考，使用合成数据，不能作为产品后端或课堂验收证据。

教师版与校园版使用同一核心。首发教学场景为随堂测验、词汇/概念闯关和实验探究；首个里程碑是完整跑通一次词汇闯关课堂，并验证同校两位教师的数据隔离和活动复用。

## 需求与开发入口

- [正式需求方案](docs/designs/openform-classroom-platform.md)：主要功能、范围、验收条件和 T1–T10 实施任务。
- [工程开发跟踪](https://github.com/zssggle-rgb/openform/issues/2)：E01–E13 的 Issue、依赖顺序、逐任务 review 和分组 QA。
- [活动协议](contracts/README.md)与[工程启动](docs/operations/development.md)：当前可执行契约、锁定依赖及真实数据库验证方法。
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

只运行当前任务涉及的测试。CI 通过 `tools/ci_scope.py` 选择 Python 目标，前端使用 Vitest 的改动依赖分析；文档修改不启动测试，新服务模块必须补充对应测试映射。每项任务完成后执行 `/review`，完成可联动的一组功能后执行 `/qa`，不把健康接口检查称为浏览器 QA。

`.env`、模型密钥、学生真实记录、上传文件和本地数据库不进入版本库。示例配置仅使用占位值；测试使用合成数据。

## 参考与许可

本项目参考 [QuickForm](https://github.com/wstlab/quickform) 的开放网页数据接入思路，计划新建共享核心；当前仓库没有复制其产品源码。后续引用第三方代码时保留所需许可和来源说明。

仓库许可证见 [LICENSE](LICENSE)。
