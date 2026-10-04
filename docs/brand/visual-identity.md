# OpenForm 品牌视觉识别规范 · VI 1.0

2026-10-04。UI 风格已由用户确认；本轮按用户“VI 放到项目里面，UI 设计基于 VI 调整”的要求，交付品牌资产并接入预览。Logo 和 VI 是本轮推荐版本，未将“同意继续制作”记录为用户对每个图形细节的逐项批准。

## 品牌图形

外侧开放的 **O** 表达开放的课堂与创作空间；内侧两片页面形成 **F**，表达教学活动的制作与分享。整体保持紧凑，能在工作台顶栏、学生页面和浏览器标签中辨认。

正式名称统一写作 **OpenForm**，保留大写 O 与 F。不另造中文注册名称，也不在正式 Logo 中固定宣传口号。VI 展示页的“开放的课堂，共同创造”用于解释设计方向。

图形从 imagegen 视觉探索中选取方向，再按明确的三条路径重建为原生 SVG。正式资产采用纯色，移除了探索稿中的渐变、临时英文口号和示例域名；不是对生成图片的自动描摹，也不是把位图嵌进 SVG。

## 标准资产

所有文件位于 [`assets/brand/`](../../assets/brand/README.md)。优先使用 SVG，位图场景使用已导出的透明 PNG。

| 用途 | 文件 |
|---|---|
| 默认横版 Logo | `svg/openform-logo-primary.svg` |
| 单色深色 / 反白 | `svg/openform-logo-ink.svg` / `svg/openform-logo-white.svg` |
| 全紫色横版 | `svg/openform-logo-purple.svg` |
| 纵向组合 | `svg/openform-logo-stacked.svg` |
| 单独图形 | `svg/openform-mark-primary.svg`，另有 ink / white |
| 应用图标 | `svg/openform-app-primary.svg`，另有 ink |
| 浏览器图标 | `svg/openform-favicon.svg`，以及 16 / 32px PNG |
| 手机快捷方式 | `png/openform-app-180.png`、`openform-app-192.png`、`openform-app-512.png` |
| 项目介绍封面 | `svg/openform-project-cover.svg` / `png/openform-project-cover.png` |
| 原始图形路径 | `source/mark-master.svg` |
| 品牌数值与文件校验 | `tokens.json` / `manifest.json` |

横版与图形 PNG 默认透明背景。反白文件本身也是透明底，应放在深色背景上；打开在白色背景上看不见不代表文件为空。应用图标有实色底；项目封面有浅色画布。

## 颜色

| 名称 | 色值 | 作用 |
|---|---|---|
| 品牌紫 | `#6C5CE7` | Logo、导航选中、小面积识别 |
| 交互深紫 | `#5B4BCB` | 白字主按钮与正文链接 |
| 深紫悬停 | `#4B3EB5` | 主要操作 hover |
| 浅紫 | `#F0EEFF` | 选中态背景 |
| 墨色 | `#161823` | 正文、标准字与单色标志 |
| 次级文字 | `#5C5F66` | 可读说明文字 |
| 工作区灰 | `#F5F5F5` | 页面画布 |
| 白色 | `#FFFFFF` | 顶栏、侧栏与内容区域 |

这些值延续已确认 UI。成功、警告、错误色仍按 `DESIGN.md` 的业务语义使用，不为了“统一品牌”全部改成紫色。反白 Logo 可以用于品牌物料的深色底，不意味着产品新增深色主题。

## 字体与标准字

Logo 标准字以 **Manrope 700** 构成，进行了组合字距调整，交付为路径。使用 Logo 不需要安装 Manrope，不受不同电脑字体替换影响。

项目附带 Google Fonts 仓库版本的字体源文件、`OFL-Manrope.txt` 与 `FONTLOG-Manrope.txt`；来源为 [Google Fonts / Manrope](https://github.com/google/fonts/tree/main/ofl/manrope)。许可证随字体保留，不能用项目根目录的 MIT 许可覆盖第三方字体许可。

正文和中文界面继续使用 `DESIGN.md` 的中文无衬线字体栈，不全站加载新的英文展示字体。项目封面 SVG 的中文说明保留为可编辑文字，跨机器呈现优先使用随附 PNG；Logo 标准字均已转为路径。

## 留白、尺寸与变体

- 以图形实际高度 H 为参照，四周净空至少为 H / 4；净空内不放其他文字、边框或学校标志。
- 产品内单独图形最小为 24 CSS px；16px 仅作为浏览器图标用途。
- 横版组合推荐最小宽度 132 CSS px；教师顶栏默认 152px，学生页默认 136px。
- 窄屏顶栏空间不足时可用 110–130px 的紧凑横版，仅限已检查的移动导航；收起侧栏时改用 28px 单独图形。需要更清楚识别时优先只保留图形，不继续缩小文字。
- 应用图标保持自带留白和底色，不把完整横版文字塞进图标。
- 学校名称放在空间切换或说明位置，不嵌入 OpenForm 标志，也不改变三个图形路径的相对位置。
- 不拉伸、倾斜、旋转、任意拆分、增加描边或渐变；不为每个学科另配一套 Logo 颜色。

## UI 接入规则

本轮将可点击 UI 预览源文件纳入项目的 [`preview.html`](../../preview.html)，VI 展示页为 [`brand.html`](../../brand.html)。二者直接引用同一套 `assets/brand`，不再复制一个不一致的临时图标。

两页通过 `assets/brand/brand.css` 共用 `tokens.json` 中的颜色和 Logo 尺寸。调整品牌数值时先修改 tokens，再运行导出工具，不在每个页面分别改一套相似色值。

| 界面位置 | 调整 |
|---|---|
| 教师 / 校园顶栏 | 使用标准横版 Logo，窄侧栏改用单独图形 |
| 活动制作顶栏 | 使用同一 Logo，保持专注制作布局 |
| 学生页顶栏 | 同一标准字与标志，控制横向宽度，保留大题干和大按钮 |
| 浏览器标签 | 引用 SVG 与 32px PNG favicon |
| 手机快捷方式 | 引用 180px 应用图标 |
| 设计预览控制条 | 提供 VI 展示入口，便于同时核对品牌与界面 |
| README / 项目介绍 | 使用正式标准 Logo 和项目封面 |

VI 不改变已确认的顶部/侧边结构、表格密度、状态语义、功能范围和学生参与流程。不添加品牌横幅占据课堂操作空间。

## 预览、导出与维护

在仓库根目录启动静态预览：

```sh
python3 -m http.server 8768 --bind 127.0.0.1
```

- VI：`http://127.0.0.1:8768/brand.html`
- UI：`http://127.0.0.1:8768/preview.html#activities`
- 学生：`http://127.0.0.1:8768/preview.html#student`

已存在预览服务时直接访问，不重复启动。页面与资产均在项目中，不需要外网字体或图片服务。预览继续使用合成数据，没有后台生成、真实学生记录或服务端权限功能。

修改 `source/mark-master.svg` 或 `tokens.json` 后，运行：

```sh
python3 tools/brand/build_assets.py
```

该工具依赖 Python 的 `fonttools` 与系统 `rsvg-convert`。字体只在导出阶段使用；产出的 Logo SVG 不依赖运行环境字体。修改图形后复查横版、单色、24px 和 16px 图标，再检查教师/学生顶栏与浏览器资源加载。

生成稿只是探索资料，正式资产以本目录矢量母版、tokens 和导出清单为准；维护时不要再次让模型凭文字随机重画同名 Logo。

## 本轮验证

- 8 个展示/预览页面在 320、390、768、1024、1280、1440px 六档宽度下完成 48 项检查：无整页横向溢出、无缺失图片，品牌色读取与共享 tokens 一致。
- 教师桌面 Logo 为 152px；学生手机页为 136px；收起侧栏时切换为 28px 图形，均在浏览器中核对。
- 6 项交互回归通过，包括原预览地址继续访问、创建弹窗、键盘焦点返回、活动筛选、学生三题提交演示和资源下载路径。
- 12 SVG / 13 PNG / 1 CSS 文件完整；Logo 标准字均为路径，无嵌入位图、脚本或外部字体引用。核对透明通道、favicon 尺寸、各色 Logo 几何一致性，重新导出结果可复现。
- 预览脚本语法、Markdown/HTML 本地链接与 `DESIGN.md` 格式检查通过，最终浏览器检查无控制台错误。

详细结果见 [qa-results.json](qa-results.json)；视觉留档见 [VI 全览](vi-overview.png)、[教师制作页](ui-editor.png)、[学生页](ui-student.png)。这些是资产和静态设计预览验证，不是产品后台、真实手机、辅助技术或课堂验收。
