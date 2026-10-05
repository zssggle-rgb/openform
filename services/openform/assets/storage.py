import hashlib
import os
import shutil
import threading
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from openform.config import Settings
from openform.errors import ApiError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
DECODERS = threading.BoundedSemaphore(2)
Image.MAX_IMAGE_PIXELS = 4096 * 4096


def staging_file(settings: Settings) -> Path:
    directory = settings.file_directory / "staging"
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        disk = shutil.disk_usage(directory)
        if disk.free < settings.minimum_free_disk_bytes or disk.used / disk.total >= 0.9:
            raise ApiError(507, "STORAGE_FULL", "存储空间不足，本次图片尚未接收，请联系部署管理员。")
        return directory / uuid4().hex
    except OSError:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "图片存储暂不可用，请稍后重试。") from None


def file_path(settings: Settings, workspace_id: UUID, file_id: UUID) -> Path:
    return settings.file_directory / "images" / str(workspace_id) / (str(file_id) + ".image")


def normalize_image(source: Path, target: Path, declared_type: str) -> tuple[str, int, str]:
    if not DECODERS.acquire(blocking=False):
        raise ApiError(429, "UPLOAD_BUSY", "图片正在处理中，请稍后重试。")
    try:
        with Image.open(source, formats=["PNG", "JPEG"]) as image:
            media_type = "image/png" if image.format == "PNG" else "image/jpeg"
            if media_type != declared_type or max(image.size) > 4096 or min(image.size) < 1 or getattr(image, "n_frames", 1) != 1:
                raise ApiError(422, "INVALID_IMAGE", "图片必须是真实单帧 PNG/JPEG，最长边不超过 4096。")
            image.load()
            oriented = ImageOps.exif_transpose(image)
            mode = "RGBA" if media_type == "image/png" and ("A" in oriented.getbands() or "transparency" in oriented.info) else "RGB"
            clean = Image.new(mode, oriented.size)
            converted = oriented.convert(mode)
            clean.paste(converted)
            try:
                with target.open("xb") as stream:
                    os.chmod(target, 0o600)
                    clean.save(stream, format="PNG" if media_type == "image/png" else "JPEG", exif=b"", icc_profile=None)
                    stream.flush(); os.fsync(stream.fileno())
            finally:
                clean.close(); converted.close(); oriented.close()
        size = target.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ApiError(413, "IMAGE_TOO_LARGE", "处理后的图片超过 10 MiB，请缩小图片后重新上传。")
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        return media_type, size, digest.hexdigest()
    except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, SyntaxError):
        raise ApiError(422, "INVALID_IMAGE", "无法完整解码图片，请使用有效 PNG/JPEG。") from None
    except OSError:
        raise ApiError(422, "INVALID_IMAGE", "图片损坏或存储失败，本次图片未接收。") from None
    finally:
        DECODERS.release()
