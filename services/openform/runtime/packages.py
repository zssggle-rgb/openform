import base64
import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from openform_contracts.validation import ContractViolation, validate_manifest

from openform.errors import ApiError

MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
VOID_TAGS = frozenset({"br", "hr", "img", "input", "wbr", "meta", "link"})
TAGS = frozenset(("html head body title meta link script style main section article aside header footer nav "
                  "div span p h1 h2 h3 h4 h5 h6 ul ol li dl dt dd table thead tbody tfoot tr th td caption "
                  "colgroup col pre code blockquote strong em b i small sub sup mark abbr label input "
                  "textarea button select option optgroup fieldset legend details summary figure figcaption "
                  "a img br hr wbr progress meter output").split())
URL_ATTRIBUTES = frozenset({"src", "href", "action", "formaction", "poster", "background", "cite", "ping", "srcset"})


@dataclass(frozen=True)
class RuntimePackage:
    digest: str
    manifest: dict[str, Any]
    document: str
    policy: str


def _incompatible() -> ApiError:
    return ApiError(422, "UNSUPPORTED_PACKAGE", "页面包含未声明资源、外部地址或不支持的执行方式，请按 OpenForm 页面协议调整。")


def _text(content: bytes) -> str:
    try:
        value = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise _incompatible() from None
    if "\x00" in value:
        raise _incompatible()
    return value


class _Document(HTMLParser):
    def __init__(self, entry: str, assets: dict[str, bytes], media: dict[str, str]) -> None:
        super().__init__(convert_charrefs=False)
        self.entry = entry
        self.assets = assets
        self.media = media
        self.output: list[str] = []
        self.scripts: list[str] = []
        self.raw_tag: str | None = None
        self.raw_content: list[str] = []
        self.raw_external: str | None = None
        self.skip_title = False

    def _asset(self, value: str, parent: str, accepted: set[str]) -> str:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or value.startswith("/") or "\\" in value:
            raise _incompatible()
        path = str(PurePosixPath(parent).parent / value)
        if ".." in PurePosixPath(path).parts or path not in self.assets or self.media[path] not in accepted:
            raise _incompatible()
        return path

    def _data_url(self, path: str) -> str:
        return f"data:{self.media[path]};base64,{base64.b64encode(self.assets[path]).decode('ascii')}"

    def _css(self, content: str, parent: str) -> str:
        # Reject escapes and imports rather than guessing how the browser will normalize a URL.
        if "\\" in content or re.search(r"@import|</style", content, re.IGNORECASE):
            raise _incompatible()

        def replace(match: re.Match[str]) -> str:
            value = match.group(1).strip().strip("\"'")
            path = self._asset(value, parent, {"image/png", "image/jpeg", "font/woff2"})
            return f'url("{self._data_url(path)}")'

        return re.sub(r"url\(\s*([^)]*)\)", replace, content, flags=re.IGNORECASE)

    def add_script(self, content: str) -> None:
        if re.search(r"</script", content, re.IGNORECASE):
            raise _incompatible()
        self.scripts.append(content)
        self.output.append(f"<script>{content}</script>")

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if tag not in TAGS or self.raw_tag:
            raise _incompatible()
        attrs = dict(attributes)
        if len(attrs) != len(attributes) or any(key.startswith("on") for key in attrs):
            raise _incompatible()
        if tag in {"html", "head", "body"}:
            return
        if tag == "title":
            self.skip_title = True
            return
        if tag == "meta":
            if "http-equiv" in attrs or set(attrs) - {"charset", "name", "content"}:
                raise _incompatible()
            return  # The host supplies charset and viewport; input cannot override policy or referrer.
        if tag == "link":
            if attrs.get("rel") != "stylesheet" or set(attrs) - {"rel", "href"}:
                raise _incompatible()
            path = self._asset(attrs.get("href") or "", self.entry, {"text/css"})
            self.output.append(f"<style>{self._css(_text(self.assets[path]), path)}</style>")
            return
        if tag in {"script", "style"}:
            if set(attrs) - ({"src", "type"} if tag == "script" else {"type"}):
                raise _incompatible()
            if attrs.get("type") not in {None, "text/javascript" if tag == "script" else "text/css"}:
                raise _incompatible()
            self.raw_tag = tag
            self.raw_content = []
            self.raw_external = self._asset(attrs["src"] or "", self.entry, {"text/javascript"}) if "src" in attrs else None
            return
        rendered: list[str] = []
        for key, value in attributes:
            if key in {"target", "download", "form", "srcdoc", "autofocus", "is"}:
                raise _incompatible()
            if key in URL_ATTRIBUTES:
                if key == "src" and tag == "img":
                    value = self._data_url(self._asset(value or "", self.entry, {"image/png", "image/jpeg"}))
                elif key == "href" and tag == "a" and value and re.fullmatch(r"#[A-Za-z0-9_-]+", value):
                    pass
                else:
                    raise _incompatible()
            if key == "style":
                value = self._css(value or "", self.entry)
            rendered.append(f' {key}="{escape(value, quote=True)}"' if value is not None else f" {key}")
        self.output.append(f"<{tag}{''.join(rendered)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in TAGS:
            raise _incompatible()
        if tag == self.raw_tag:
            content = "".join(self.raw_content)
            if self.raw_external:
                if content.strip():
                    raise _incompatible()
                content = _text(self.assets[self.raw_external])
            if tag == "script":
                self.add_script(content)
            else:
                self.output.append(f"<style>{self._css(content, self.entry)}</style>")
            self.raw_tag = None
            self.raw_external = None
        elif tag == "title":
            self.skip_title = False
        elif tag not in {"html", "head", "body"} and tag not in VOID_TAGS:
            if self.raw_tag:
                raise _incompatible()
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.raw_tag:
            self.raw_content.append(data)
        elif not self.skip_title:
            self.output.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self.skip_title:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_title:
            self.output.append(f"&#{name};")


def prepare_package(manifest: dict[str, Any], assets: dict[str, bytes], *, app_origin: str) -> RuntimePackage:
    """Compile an exact declared bundle; no resource endpoint or network allowlist is exposed."""
    try:
        validate_manifest(manifest)
    except ContractViolation:
        raise ApiError(422, "INVALID_CONTRACT", "活动清单不符合页面协议。") from None
    declared = {asset["path"]: asset for asset in manifest["assets"]}
    if set(assets) != set(declared) or sum(map(len, assets.values())) > MAX_PACKAGE_BYTES:
        raise _incompatible()
    for path, content in assets.items():
        if hashlib.sha256(content).hexdigest() != declared[path]["sha256"]:
            raise ApiError(422, "ASSET_MISMATCH", "页面资源与清单摘要不一致，请重新导入完整页面包。")
    document = _Document(manifest["entry"], assets, {path: item["mediaType"] for path, item in declared.items()})
    document.add_script(files("openform.runtime").joinpath("client.js").read_text(encoding="utf-8"))
    document.feed(_text(assets[manifest["entry"]]))
    document.close()
    if document.raw_tag or document.skip_title:
        raise _incompatible()
    html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(manifest["title"])}</title></head><body>{"".join(document.output)}</body></html>')
    if len(html.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise _incompatible()
    hashes = sorted({"'sha256-" + base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii") + "'"
                     for script in document.scripts})
    policy = ("default-src 'none'; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; "
              "base-uri 'none'; form-action 'none'; img-src data:; font-src data:; media-src 'none'; "
              f"script-src {' '.join(hashes)}; script-src-attr 'none'; style-src 'unsafe-inline'; "
              f"frame-ancestors {app_origin}; sandbox allow-scripts")
    # Detach caller-owned objects; document, policy and SDK version all participate in immutability.
    manifest_copy = json.loads(json.dumps(manifest, ensure_ascii=False, allow_nan=False))
    encoded = json.dumps([manifest_copy, html, policy], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return RuntimePackage(hashlib.sha256(encoded.encode("utf-8")).hexdigest(), manifest_copy, html, policy)
