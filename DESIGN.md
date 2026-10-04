---
# gstack: design-md-format=spec
name: OpenForm
description: 沿用 AdPilot 的浅色、紧凑、紫色强调工作台，让教师清楚地制作活动、查看课堂和复用校内资源。
colors:
  primary: "#6C5CE7"
  primary-strong: "#5B4BCB"
  primary-hover: "#4B3EB5"
  on-primary: "#FFFFFF"
  primary-soft: "#F0EEFF"
  canvas: "#F5F5F5"
  surface: "#FFFFFF"
  surface-subtle: "#F7F8FA"
  surface-hover: "#F7F5FF"
  text: "#161823"
  text-secondary: "#5C5F66"
  text-disabled: "#8A8F99"
  border: "#EAECEF"
  border-control: "#777D88"
  border-strong: "#D9DDE3"
  success: "#00754F"
  success-soft: "#E8F6F0"
  warning: "#A64B00"
  warning-soft: "#FFF4E6"
  error: "#C5221F"
  error-soft: "#FDECEB"
  info: "#2454CC"
  info-soft: "#EEF3FF"
typography:
  title:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 14px
    lineHeight: 1.6
  navigation:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 15px
    fontWeight: 500
  label:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 12px
    lineHeight: 1.5
  table:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 13px
    lineHeight: 1.5
  student-body:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 16px
    lineHeight: 1.7
  student-question:
    fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    fontSize: 22px
    fontWeight: 600
    lineHeight: 1.6
  mono:
    fontFamily: '"SF Mono", Menlo, Consolas, "IBM Plex Mono", monospace'
    fontFeature: tnum
rounded:
  tag: 3px
  control: 4px
  panel: 6px
  overlay: 8px
  avatar: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  page-inline: 28px
  xxl: 32px
components:
  topbar:
    height: 60px
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
  sidebar:
    width: 240px
    collapsedWidth: 64px
    backgroundColor: "{colors.surface}"
  nav-link:
    minHeight: 44px
    textColor: "{colors.text-secondary}"
  nav-link-active:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.text}"
  button-primary:
    minHeight: 32px
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.control}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  input:
    minHeight: 32px
    borderColor: "{colors.border-control}"
    rounded: "{rounded.control}"
  panel:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.panel}"
  table-header:
    height: 42px
    backgroundColor: "{colors.surface-subtle}"
  table-row:
    minHeight: 56px
    fontSize: 13px
  metric-strip:
    minHeight: 56px
    backgroundColor: "{colors.surface}"
  focus-bar:
    minHeight: 48px
    backgroundColor: "{colors.surface}"
  dialog:
    width: 520px
    rounded: "{rounded.overlay}"
    shadow: "0 8px 24px rgba(22, 24, 35, 0.12)"
  drawer:
    width: 560px
    rounded: "{rounded.overlay}"
    shadow: "0 8px 24px rgba(22, 24, 35, 0.12)"
  student-container:
    maxWidth: 720px
    padding: 24px
  student-option:
    minHeight: 56px
    rounded: "{rounded.control}"
  student-action:
    minHeight: 48px
    fontSize: 16px
  focus-visible:
    outline: "2px solid #5B4BCB"
    outlineOffset: 3px
  transition:
    duration: 150ms
    easing: ease-out
  breakpoint-sidebar:
    width: 1280px
  breakpoint-mobile:
    width: 768px
---

# OpenForm UI 设计规范

## 定位与依据

**设计主张：** 沿用 AdPilot 清楚、紧凑的业务工作台，以活动、学生提交和教学判断为信息中心。

用户已指定使用 AdPilot 的现有风格。本规范是据此整理的首版设计基线；页面布局为本轮设计提案，尚未经过用户逐页验收，也不表示产品已实现。

参考本机 AdPilot 根目录 `DESIGN.md` 与 R14 统一预览，提取白色顶栏、白色侧栏、浅灰画布、紫色选中态、紧凑筛选表格和轻量弹层。未采用旧 `tokens.css` 中已与该规范不一致的粉红色，也未复制 AdPilot 的商标、业务源码或投放文案。

教师端与校园管理端属于操作界面；教学诊断属于阅读与复核界面；学生端属于参与界面。三者共享颜色、字体和状态语言，按任务使用不同密度。

## 颜色

采用单一紫色强调，保持全浅色。紫色用于当前导航、交互选中和主要动作；成功、警告、错误和信息各有语义色，并同时提供文字，避免只靠颜色识别。

深紫用于白字按钮与正文链接。浅灰三级文字只用于禁用内容；说明、时间和统计口径使用可读的次级文字。表格分隔线保持轻量，必须辨认边界的输入框和选择控件使用更深边框，这是相对 AdPilot 的可访问性补充。

不新增渐变主视觉、深色制作器或多套学科主题。学校环境和投影使用优先清楚稳定，不以装饰区分版本。

## 字体

沿用 AdPilot 中文无衬线字体栈，标题不另配宣传字体。中文工作台的熟悉度优先于独特字形，属于用户指定参考风格的明确继承。

本机已找到 Microsoft YaHei 与 Menlo 字体文件；PingFang SC 与 Noto Sans SC 作为系统回退候选，不声称已在本机安装。预览不下载、复制或重新分发商业字体。离线环境不得依赖在线字体 CDN；部署时使用合法可用系统字体，若另行捆绑字体则先确认许可并复测布局。

数字使用等宽数字特性，表格数据右对齐；长活动名称允许换行或带可访问全文的截断。学生题干与答案扩大字号和行高，不将教师表格压缩成手机答题页。

## 布局

教师与校园端沿用全宽工作台，正文不居中限制宽度。顶栏承载教学、校内资源和校园管理；侧栏承载当前模块下的操作；空间切换位置固定。个人空间隐藏校园专属模块，切换到学校不暗示个人活动已迁移。

活动列表首屏直接显示筛选、表头和多条活动。指标合并为一条简洁统计栏，不用大面积数字卡片挤占操作区。主要按钮对应当前页的一件事：新建活动、试做检查、复核建议或发布资源。

制作活动进入专注布局：保留顶栏与活动上下文，收起业务侧栏；左侧教学要求、材料与收集内容，右侧活动预览。保持浅色，技术接入细节按需展开，默认使用教师能理解的语言。

诊断先呈现参与、完成和题目表现，再呈现 AI 归纳与教学建议。归纳标明覆盖范围、时间和可打开的原始依据，教师能在查看依据后复核。无答案标准时不能显示正确率。

校内资源采用可筛选的列表，先看教学主题、年级、样板类型、作者与版本。复制前写清“不含学生记录”；复制后进入自己的独立草稿。校园管理提供成员、班级任课等业务管理，不暗示管理员默认可以读取全部学生回答。

响应规则：低于侧栏断点收起文字、保留图标和可访问名称；低于手机断点改为可展开导航。表格允许容器内横向滚动，页面不得整体溢出。教师复杂制作建议使用电脑，但手机仍能查看课堂情况。学生端始终使用单列，桌面也保持适宜阅读宽度；窄屏以较小外边距换取题目空间，不缩小触控目标。

## 层次与形状

常规区域使用背景和细边框分区，不层层套卡片。只有弹窗、抽屉和浮层使用投影。控件、内容面板、弹层按圆角层级区分，圆形仅用于头像等真正适合的元素。图标使用一致的线性符号，必须配名称或可访问标签，不添加装饰插画。

## 组件与状态

| 组件 | 规则与课堂适配 |
|---|---|
| 导航 | 当前项同时有背景/下划线与文字；键盘焦点明显；空间与角色可辨认 |
| 按钮 | 页面级主按钮仅一个；其他动作为描边或文字；禁用原因在附近可见 |
| 筛选与表格 | 搜索、状态和类型紧邻结果；显示条数；筛选无结果可清空；数据列对齐 |
| 表单 | 可见标签、具体示例、行内错误；保留已有输入；不以 placeholder 代替标签 |
| 弹窗 | 原生对话框或等效焦点约束；支持 Escape；关闭后焦点回到来源；危险操作说明影响 |
| 草稿与版本 | 草稿、待试做、已验证版本、已发布课堂分别表达；修改不覆盖已发布课堂 |
| 任务进行中 | 显示排队/处理中和下一步；无真实进度时不编造百分比；保留已可用内容 |
| 数据接入 | 只有后端确认收到真实试做结果后才标记通过；页面能打开不等于已接入 |
| 学生保存 | 区分本机暂存、等待确认、已保存与已提交；无回执不显示提交成功 |
| 教学建议 | 与确定性统计分区；可追溯依据；保留教师复核入口；不自动产生正式成绩 |
| 空状态 | 说明当前没有什么以及下一步，例如“还没有活动 → 新建活动” |
| 异常状态 | 失败、无权限、断网、部分完成、数据冲突分别说明；保留可恢复的输入 |
| 校内资源 | 共享页面和教学配置，不默认共享学生数据；来源更新不自动覆盖副本 |

组件必须实现 hover、focus-visible、active、disabled。可交互边界、文字与背景的对比度需要在实现中验证。移动端表单至少使用学生正文字号，避免输入时自动缩放。尊重系统减少动态效果设置。

## 应当与避免

- 应当：保持 AdPilot 的白色框架、紫色强调和紧凑表格；让主要功能占首屏。
- 应当：用真实业务词表达动作，例如“试做并检查”“查看提交”“复制到我的活动”。
- 应当：把数据覆盖、版本和权限范围放在相关内容旁边，而不是埋入统一设置。
- 应当：学生单列、大题干、大点击区；教师数据密集但不牺牲说明可读性。
- 避免：大宣传横幅、彩色渐变、任意深色块、大圆角卡片网格、无意义动效。
- 避免：把校园管理等同于全部教学数据访问，把资源分享等同于学生记录分享。
- 避免：显示队列、协议、token、worker 等实现术语作为教师主流程步骤。
- 避免：用演示数据、前端切换或截图代表后端保存、权限和课堂验收。

## 动效

采用短暂功能性过渡，只帮助识别选中、展开和状态变化。学生答案选中有轻量边框与底色反馈；提交回执以清楚文字和图标呈现，不做庆祝动画或排名刺激。减少动态效果模式关闭非必要过渡。

## 决策记录

| 日期 | 决策 | 依据 |
|---|---|---|
| 2026-10-04 | 继承 AdPilot 最新规范与 R14 视觉，不另选品牌方向 | 用户明确指定 |
| 2026-10-04 | 用实际 HTML 页面演示同一风格，不制作三套不同审美方案 | 已有明确参考；更便于检查中文密度与操作状态 |
| 2026-10-04 | 教师/校园共享工作台，学生扩大题目和触控区域 | 三种使用任务不同，按推荐落地的设计提案 |
| 2026-10-04 | 默认浅色，不新增暗色切换；补强控件边框对比 | 与参考一致，同时保证操作识别 |
| 2026-10-04 | 外部独立审美提案未运行；页面尚待用户视觉反馈 | 不伪记独立评审或用户逐页批准 |
