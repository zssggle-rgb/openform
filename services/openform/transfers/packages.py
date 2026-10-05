import hashlib
import json
import math
import re
import stat
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NoReturn
from uuid import UUID
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from PIL import Image
from pydantic import Field, ValidationError, model_validator

from openform.activities.schemas import DraftInput
from openform.activities.service import prepare_draft
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.schemas import Input

MAX_ZIP_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_CONTENT_BYTES = 50 * 1024 * 1024
MAX_FILES = 500
PACKAGE_READERS = threading.BoundedSemaphore(2)


class Source(Input):
    workspace_id: UUID
    object_id: UUID
    exported_at: str = Field(max_length=64)
    data_epoch: int | None = Field(default=None, ge=0)


class Version(Input):
    number: int = Field(ge=1)
    draft: DraftInput


class ArchivedImage(Input):
    source_file_id: UUID
    path: str = Field(pattern=r"^images/[0-9a-f-]{36}\.image$")
    media_type: Literal["image/png", "image/jpeg"]
    byte_size: int = Field(gt=0, le=10 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Record(Input):
    source_record_id: UUID
    source_actor_id: UUID
    actor_kind: Literal["student", "guest"]
    display_name: str = Field(min_length=1, max_length=80)
    attempt_number: int = Field(ge=1)
    created_at: str = Field(max_length=64)
    data: dict[str, Any]
    receipt_id: UUID
    images: list[ArchivedImage] = Field(default_factory=list, max_length=5)


class Package(Input):
    format: Literal["openform.resource/1", "openform.archive/1"]
    title: str = Field(min_length=1, max_length=80)
    source: Source
    versions: list[Version] = Field(min_length=1, max_length=50)
    records: list[Record] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def consistent(self) -> "Package":
        if len({version.number for version in self.versions}) != len(self.versions):
            raise ValueError("版本编号不能重复。")
        if self.format == "openform.resource/1" and self.records:
            raise ValueError("教学资源包不能携带课堂记录。")
        if self.format == "openform.archive/1" and (len(self.versions) != 1 or self.source.data_epoch is None):
            raise ValueError("课堂档案必须对应一个固定版本和资料代次。")
        if len({record.source_record_id for record in self.records}) != len(self.records):
            raise ValueError("档案记录标识不能重复。")
        for record in self.records:
            if len(json.dumps(record.data, ensure_ascii=False).encode()) > 65536:
                raise ValueError("单份记录超过 64 KiB。")
        return self


class FileEntry(Input):
    path: str = Field(max_length=100)
    byte_size: int = Field(gt=0, le=MAX_CONTENT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Index(Input):
    format: Literal["openform.package-index/1"]
    files: list[FileEntry] = Field(min_length=1, max_length=MAX_FILES - 1)


def _name(path: str) -> bool:
    return (path == str(PurePosixPath(path)) and not path.startswith("/") and "\\" not in path
            and (path == "content.json" or re.fullmatch(r"images/[0-9a-f-]{36}\.image", path) is not None))


def _reject_number(value: str) -> NoReturn:
    raise ValueError("迁移包不支持非有限数值。")


def _compatible_json(value: Any) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if "\x00" in item:
                raise ValueError("迁移正文不支持空字符。")
            item.encode("utf-8")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("迁移正文不支持非有限数值。")
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def read_package(path: Path, settings: Settings) -> Package:
    if not PACKAGE_READERS.acquire(blocking=False):
        raise ApiError(429, "PACKAGE_BUSY", "迁移包正在预检，请稍后用原操作键重试。")
    try:
        return _read_package(path, settings)
    finally:
        PACKAGE_READERS.release()


def _read_package(path: Path, settings: Settings) -> Package:
    """Validate in place; no extractall and no archive-provided filesystem paths."""
    try:
        if path.stat().st_size > MAX_ZIP_BYTES:
            raise ApiError(413, "PACKAGE_TOO_LARGE", "迁移包压缩大小不得超过 20 MiB。")
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (len(infos) > MAX_FILES or len(names) != len(set(names)) or "index.json" not in names
                    or sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES):
                raise ValueError("数量、重复路径或展开容量不符合约定。")
            for info in infos:
                mode = stat.S_IFMT(info.external_attr >> 16)
                if (info.is_dir() or mode not in {0, stat.S_IFREG} or info.flag_bits & 1
                        or info.filename != "index.json" and not _name(info.filename)):
                    raise ValueError("拒绝目录、特殊文件、加密、嵌套包或未支持路径。")
            if archive.getinfo("index.json").file_size > 256 * 1024:
                raise ValueError("索引过大。")
            index = Index.model_validate_json(archive.read("index.json"))
            entries = {entry.path: entry for entry in index.files}
            if len(entries) != len(index.files) or set(names) != {"index.json", *entries} or "content.json" not in entries:
                raise ValueError("包内容与完整清单不符。")
            for entry in entries.values():
                if not _name(entry.path) or archive.getinfo(entry.path).file_size != entry.byte_size:
                    raise ValueError("文件大小或路径不符。")
                digest = hashlib.sha256()
                with archive.open(entry.path) as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        digest.update(chunk)
                if digest.hexdigest() != entry.sha256:
                    raise ValueError("文件哈希不符。")
            if entries["content.json"].byte_size > MAX_CONTENT_BYTES:
                raise ValueError("记录内容过大。")
            content = json.loads(archive.read("content.json"), parse_constant=_reject_number)
            _compatible_json(content)
            package = Package.model_validate(content)
            for version in package.versions:
                prepare_draft(settings, version.draft.model_copy(update={"expected_revision": 0}))
            declared: set[str] = set()
            verified_images: dict[str, str] = {}
            for record in package.records:
                for image in record.images:
                    image_entry = entries.get(image.path)
                    if image_entry is None or image_entry.byte_size != image.byte_size or image_entry.sha256 != image.sha256:
                        raise ValueError("图片引用与清单不符。")
                    if image.path != f"images/{image.source_file_id}.image":
                        raise ValueError("图片来源标识与路径不符。")
                    declared.add(image.path)
                    if image.path in verified_images:
                        if verified_images[image.path] != image.media_type:
                            raise ValueError("重复图片引用的类型不符。")
                        continue
                    with archive.open(image.path) as stream, Image.open(stream, formats=["PNG", "JPEG"]) as decoded:
                        if (max(decoded.size) > 4096 or min(decoded.size) < 1 or getattr(decoded, "n_frames", 1) != 1
                                or ("image/png" if decoded.format == "PNG" else "image/jpeg") != image.media_type):
                            raise ValueError("图片格式或尺寸不符。")
                        decoded.load()
                    verified_images[image.path] = image.media_type
            if set(entries) != {"content.json", *declared}:
                raise ValueError("包包含未声明的文件，或资源包携带图片记录。")
            return package
    except ApiError:
        raise
    except (BadZipFile, ValidationError, ValueError, UnicodeError, OSError, RuntimeError, EOFError, RecursionError, SyntaxError, NotImplementedError, Image.DecompressionBombError):
        raise ApiError(422, "INVALID_PACKAGE", "包未通过协议、路径、完整性或内容检查；未创建活动或档案。仅支持 OpenForm resource/1 和 archive/1。") from None


def write_package(path: Path, package: Package, images: dict[str, Path]) -> None:
    content = package.model_dump_json().encode()
    if len(content) > MAX_CONTENT_BYTES or len(images) + 2 > MAX_FILES:
        raise ApiError(413, "EXPORT_TOO_LARGE", "所选资料超过单包 50 MiB 正文或 500 文件上限，请缩小课堂资料范围。")
    entries = [FileEntry(path="content.json", byte_size=len(content), sha256=hashlib.sha256(content).hexdigest())]
    size = len(content)
    with ZipFile(path, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("content.json", content)
        for name, source in sorted(images.items()):
            if not _name(name):
                raise ApiError(422, "INVALID_PACKAGE", "图片路径不符合导出约定。")
            data = source.read_bytes()
            size += len(data)
            if size > MAX_UNPACKED_BYTES:
                raise ApiError(413, "EXPORT_TOO_LARGE", "导出展开容量超过 100 MiB。")
            entries.append(FileEntry(path=name, byte_size=len(data), sha256=hashlib.sha256(data).hexdigest()))
            archive.writestr(name, data)
        archive.writestr("index.json", Index(format="openform.package-index/1", files=entries).model_dump_json())
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise ApiError(413, "EXPORT_TOO_LARGE", "导出压缩容量超过 20 MiB，请缩小资料范围。")
