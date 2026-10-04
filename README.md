<h1><img src="assets/brand/svg/openform-logo-primary.svg" alt="OpenForm" width="280"></h1>

面向教师和学校的互动教学活动平台，支持活动制作、课堂参与、持续数据保存、教学诊断和校内资源复用。

## 当前阶段

项目处于开发准备阶段，已完成主要需求评审、Git 基线与用户确认的 UI 风格，并交付 Logo / VI 1.0。当前仓库包含研究、需求、设计规范、品牌资产、可点击设计预览和待实施任务，尚无产品应用或产品测试结果。

教师版与校园版使用同一核心。首发教学场景为随堂测验、词汇/概念闯关和实验探究；首个里程碑是完整跑通一次词汇闯关课堂，并验证同校两位教师的数据隔离和活动复用。

## 需求与开发入口

- [正式需求方案](docs/designs/openform-classroom-platform.md)：主要功能、范围、验收条件和 T1–T10 实施任务。
- [页面与主流程方案](docs/designs/openform-page-plan.md)：教师端、校园管理端、学生端的页面职责、导航、主要操作和需求映射；当前为待设计评审草案。
- [QuickForm 项目研究](docs/research/quickform-study-and-openform-proposal-2026-10-04.md)：参考项目的价值、源码依据和重做建议。
- [需求评审记录](docs/reviews/openform-ceo-review-2026-10-04.md)：已确认决定及评审过程。
- [结构化任务清单](docs/planning/ceo-implementation-tasks.jsonl)：与需求方案对应的 10 项待实施任务，路径和投入仍需工程拆解。
- [后续候选](TODOS.md)：独立教师安装包、学校统一身份及多模态辅助分析。
- [开发约定](AGENTS.md)：代码、验证、数据和 Git 操作规则。
- [UI 设计规范](DESIGN.md)：继承 AdPilot 风格，定义教师、校园和学生界面的视觉基线。
- [UI 设计交付记录](docs/reviews/openform-ui-style-2026-10-04.md)：参考依据、页面预览位置与实际验证范围。
- [VI 使用规范](docs/brand/visual-identity.md)与[品牌资产](assets/brand/README.md)：Logo、图标、单色版本、封面和导出来源。

## 设计预览

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

下一步先完成工程设计和主流程原型，明确数据协议、空间与身份模型、技术栈和运行命令后，再建立应用骨架。React/TypeScript、FastAPI、PostgreSQL 当前只是候选，不是已完成的技术选型。

`.env`、模型密钥、学生真实记录、上传文件和本地数据库不进入版本库。示例配置仅使用占位值；测试使用合成数据。

## 参考与许可

本项目参考 [QuickForm](https://github.com/wstlab/quickform) 的开放网页数据接入思路，计划新建共享核心；当前仓库没有复制其产品源码。后续引用第三方代码时保留所需许可和来源说明。

仓库许可证见 [LICENSE](LICENSE)。
