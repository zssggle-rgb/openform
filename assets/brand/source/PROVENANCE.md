# 来源与生成记录

## 图形

- 2026-10-04 使用内置 `image_gen.imagegen` 生成一次 `logo-brand` 视觉探索。
- 提示词见 [concept-prompt.md](concept-prompt.md)。探索图保持在本机设计工作目录，不作为产品运行资产。
- 从生成方向提取“开放 O + 两片 F 页面”的构成，以 `mark-master.svg` 的三条纯色路径重新建立几何母版。
- 生产 SVG、单色变体与 PNG 由原生矢量导出工具生成；没有对生成位图做裁切、抠图或自动描摹。
- 生成稿中的临时口号、示例网址和渐变不进入正式资产。项目名称保持 OpenForm。

## 标准字字体

- 来源：[Google Fonts / Manrope](https://github.com/google/fonts/tree/main/ofl/manrope)。
- 字体地址：`https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/Manrope%5Bwght%5D.ttf`。
- 附原始 `OFL.txt` 为 `OFL-Manrope.txt`，`FONTLOG.txt` 为 `FONTLOG-Manrope.txt`。
- 这两个文本仅清除了原文件的行末空格，许可与说明文字未改动。
- 本地导出工具：fonttools 4.63.0，librsvg / rsvg-convert 2.60.0。
- 取 700 字重并将 OpenForm 标准字转换成路径；源字体不在浏览器端加载。

## 项目文件

`tools/brand/build_assets.py` 从母版与字体产生 12 SVG / 13 PNG，以及共享的 `brand.css`，写入 `assets/brand/manifest.json`。输出不是 imagegen 直接产生的可编辑矢量文件，而是本轮依据设计方向制作的项目原生资产。
