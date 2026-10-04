#!/usr/bin/env python3
"""Build native SVG brand assets and render PNG exports; no raster tracing/editing.

Requires Python 3, fonttools and rsvg-convert. Run from any directory.
The shape source is assets/brand/source/mark-master.svg. All generated SVGs use
outlined glyphs, so deployed assets do not need a font or a network request.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "assets" / "brand"
SVG = BRAND / "svg"
PNG = BRAND / "png"
NAMESPACE = {"s": "http://www.w3.org/2000/svg"}


def _document(width: float, height: float, content: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" '
        'role="img" aria-labelledby="title">\n'
        f'  <title id="title">{title}</title>\n{content}\n</svg>\n'
    )


def _wordmark() -> tuple[str, float]:
    font_path = BRAND / "source" / "Manrope-wght.ttf"
    with TTFont(font_path) as original:
        font = instantiateVariableFont(original, {"wght": 700}, inplace=False)
    try:
        glyphs = font.getGlyphSet()
        cmap = font.getBestCmap()
        cursor = 0
        paths = []
        bounds = []
        for character in "OpenForm":
            glyph_name = cmap[ord(character)]
            glyph = glyphs[glyph_name]
            pen = SVGPathPen(glyphs)
            glyph.draw(pen)
            bounds_pen = BoundsPen(glyphs)
            glyph.draw(bounds_pen)
            x0, y0, x1, y1 = bounds_pen.bounds
            bounds.append((x0 + cursor, y0, x1 + cursor, y1))
            paths.append(f'<path transform="translate({cursor:g} 0)" d="{pen.getCommands()}"/>')
            cursor += glyph.width - font["head"].unitsPerEm * 0.018
        x0 = min(b[0] for b in bounds)
        y0 = min(b[1] for b in bounds)
        x1 = max(b[2] for b in bounds)
        y1 = max(b[3] for b in bounds)
        scale = 64 / (y1 - y0)
        width = (x1 - x0) * scale
        path_group = (
            f'<g transform="scale({scale:.8f} {-scale:.8f}) translate({-x0:g} {-y1:g})">'
            + "".join(paths) + "</g>"
        )
        return path_group, width
    finally:
        font.close()


def _build() -> None:
    renderer = shutil.which("rsvg-convert")
    if not renderer:
        raise RuntimeError("rsvg-convert is required to render PNG exports; no files were generated.")
    tokens = json.loads((BRAND / "tokens.json").read_text())
    colors = tokens["colors"]
    geometry = tokens["geometry"]
    shape = ET.parse(BRAND / "source" / "mark-master.svg")
    shape_paths = "".join(f'<path d="{node.attrib["d"]}"/>' for node in shape.findall(".//s:path", NAMESPACE))
    if len(shape.findall(".//s:path", NAMESPACE)) != 3:
        raise ValueError("The approved mark construction must have exactly three paths.")
    word, word_width = _wordmark()
    lockup_width = round(122 + word_width + 4, 4)
    sources = {}
    for variant, mark_color, text_color in [
        ("primary", colors["primary"], colors["ink"]),
        ("ink", colors["ink"], colors["ink"]),
        ("white", colors["white"], colors["white"]),
        ("purple", colors["primary"], colors["primary"]),
    ]:
        sources[f"openform-logo-{variant}.svg"] = _document(
            lockup_width, 104,
            f'<g fill="{mark_color}" transform="translate(0 1)">{shape_paths}</g>'
            f'<g fill="{text_color}" transform="translate(122 22)">{word}</g>',
            f"OpenForm — {variant} horizontal logo",
        )
        if variant != "purple":
            sources[f"openform-mark-{variant}.svg"] = _document(
                100, 100, f'<g fill="{mark_color}">{shape_paths}</g>', f"OpenForm — {variant} symbol"
            )
    sources["openform-logo-stacked.svg"] = _document(
        360, 260,
        f'<g transform="translate(110 12) scale(1.4)" fill="{colors["primary"]}">{shape_paths}</g>'
        f'<g transform="translate(24 186) scale({312 / word_width:.8f})" fill="{colors["ink"]}">{word}</g>',
        "OpenForm — stacked logo",
    )
    for variant, background, mark_color in [
        ("primary", colors["primary"], colors["white"]),
        ("ink", colors["ink"], colors["white"]),
    ]:
        sources[f"openform-app-{variant}.svg"] = _document(
            512, 512,
            f'<rect width="512" height="512" rx="112" fill="{background}"/>'
            f'<g transform="translate(86 78) scale(3.4)" fill="{mark_color}">{shape_paths}</g>',
            f"OpenForm — {variant} application icon",
        )
    sources["openform-favicon.svg"] = _document(
        100, 100, f'<g fill="{colors["primary"]}">{shape_paths}</g>', "OpenForm"
    )
    # Artwork for a repository/project cover. This is not a product-page hero.
    cover_logo_scale = 660 / lockup_width
    sources["openform-project-cover.svg"] = _document(
        1200, 630,
        f'<rect width="1200" height="630" fill="{colors["white"]}"/>'
        f'<rect x="48" y="48" width="1104" height="534" rx="8" fill="{colors["canvas"]}"/>'
        f'<g transform="translate(120 181) scale({cover_logo_scale:.8f})">'
        f'<g fill="{colors["primary"]}">{shape_paths}</g>'
        f'<g fill="{colors["ink"]}" transform="translate(122 22)">{word}</g></g>'
        '<text x="126" y="397" font-family="Microsoft YaHei, PingFang SC, sans-serif" '
        f'font-size="30" fill="{colors["ink"]}">制作互动活动 · 看见课堂反馈 · 共享教学资源</text>'
        f'<path d="M120 470H1080" stroke="{colors["primary"]}" stroke-width="2"/>'
        '<text x="126" y="523" font-family="sans-serif" font-size="16" '
        f'letter-spacing="2" fill="{colors["secondaryText"]}">OPENFORM / CLASSROOM INTERACTION PLATFORM</text>',
        "OpenForm — project cover",
    )
    SVG.mkdir(parents=True, exist_ok=True)
    PNG.mkdir(parents=True, exist_ok=True)
    css_values = {f"--of-{key}": value for key, value in colors.items()}
    css_values.update({
        "--of-logo-desktop-width": f'{geometry["desktopHeaderLogoWidthPx"]}px',
        "--of-logo-student-width": f'{geometry["studentHeaderLogoWidthPx"]}px',
        "--of-logo-collapsed-width": f'{geometry["collapsedMarkCssPx"]}px',
    })
    (BRAND / "brand.css").write_text(
        "/* Generated from tokens.json by tools/brand/build_assets.py. */\n:root {\n"
        + "".join(f"  {name}: {value};\n" for name, value in css_values.items())
        + "}\n"
    )
    for name, data in sources.items():
        (SVG / name).write_text(data)
    exports = {
        "openform-logo-primary.png": ("openform-logo-primary.svg", 1440, None),
        "openform-logo-ink.png": ("openform-logo-ink.svg", 1440, None),
        "openform-logo-white.png": ("openform-logo-white.svg", 1440, None),
        "openform-logo-stacked.png": ("openform-logo-stacked.svg", 720, 520),
        "openform-mark-primary.png": ("openform-mark-primary.svg", 1000, 1000),
        "openform-mark-ink.png": ("openform-mark-ink.svg", 1000, 1000),
        "openform-mark-white.png": ("openform-mark-white.svg", 1000, 1000),
        "openform-app-512.png": ("openform-app-primary.svg", 512, 512),
        "openform-app-192.png": ("openform-app-primary.svg", 192, 192),
        "openform-app-180.png": ("openform-app-primary.svg", 180, 180),
        "openform-favicon-32.png": ("openform-favicon.svg", 32, 32),
        "openform-favicon-16.png": ("openform-favicon.svg", 16, 16),
        "openform-project-cover.png": ("openform-project-cover.svg", 1200, 630),
    }
    for name, (source, width, height) in exports.items():
        command = [renderer, "--width", str(width)]
        if height:
            command.extend(["--height", str(height)])
        command.extend(["--output", str(PNG / name), str(SVG / source)])
        subprocess.run(command, check=True, capture_output=True, text=True)
    manifest = {
        "brand": "OpenForm",
        "version": "1.0",
        "source": "Native SVG geometry reconstructed from imagegen exploration; not automatic raster tracing",
        "wordmark": "Manrope 700 outlined glyph paths; supplied OFL license",
        "horizontalViewBox": f"0 0 {lockup_width:g} 104",
        "files": [],
    }
    for path in sorted([*SVG.glob("*.svg"), *PNG.glob("*.png"), BRAND / "brand.css"]):
        manifest["files"].append({
            "path": str(path.relative_to(BRAND)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (BRAND / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {len(sources)} SVG and {len(exports)} PNG assets; wordmark width: {word_width:.2f}.")


if __name__ == "__main__":
    _build()
