# OpenForm 品牌资产

VI 1.0，2026-10-04。UI 风格已确认，本轮 VI 为项目内的推荐设计版本。

![OpenForm](png/openform-logo-primary.png)

- `svg/`：12 个矢量文件，包含横版、纵版、独立图形、单色/反白、应用图标与项目封面。
- `png/`：13 个位图导出，包含透明 Logo、16/32px favicon、180/192/512px 应用图标。
- `source/mark-master.svg`：图形母版，只有三个纯色路径。
- `source/Manrope-wght.ttf`：生成标准字轮廓使用的字体；附 OFL 许可与 FONTLOG。
- `tokens.json`：正式品牌色、尺寸与使用约束。
- `brand.css`：从 tokens 导出的共享颜色和 Logo 尺寸，UI 与 VI 展示页共同引用。
- `manifest.json`：导出文件名、字节数与 SHA-256，便于检查复制是否完整。

[VI 使用规范](../../docs/brand/visual-identity.md) · [浏览器品牌展示](../../brand.html) · [UI 预览](../../preview.html)

Logo SVG 使用路径，既不嵌入位图，也不引用在线字体。项目封面 SVG 的中文是可编辑文字，发送给其他人时可优先使用对应 PNG。

生成命令：`python3 tools/brand/build_assets.py`，在项目根目录执行。下载与生成过程见 [来源记录](source/PROVENANCE.md)。
