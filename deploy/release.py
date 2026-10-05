#!/usr/bin/env python3
"""Build a versioned, checksum-verifiable Linux amd64 offline distribution from committed source."""
import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

POSTGRES_IMAGE = "postgres:18@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722"
POSTGRES_OFFLINE_TAG = "openform-postgres:18-5a5a84b1"
ROOT = Path(__file__).resolve().parent.parent


def run(args: list[str], output: object = subprocess.PIPE) -> bytes:
    result = subprocess.run(args, cwd=ROOT, stdout=output, stderr=subprocess.PIPE, check=True)
    return result.stdout or b""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true", help="核对解包目录 manifest，不读取密钥")
    args = parser.parse_args()
    if args.verify:
        expected = json.loads((args.output / "release-manifest.json").read_text())
        actual = {}
        for file in sorted(args.output.rglob("*")):
            if file.is_symlink():
                raise ValueError("发布包不允许链接。")
            if file.is_file() and file.name != "release-manifest.json":
                with file.open("rb") as stream:
                    actual[file.relative_to(args.output).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected["files"]:
            raise ValueError("发布包文件摘要不一致。")
        print("发布包文件清单与摘要一致；这不代表现场验收。")
        return
    if args.output.exists():
        raise ValueError("发布文件已存在，不能覆盖。")
    revision = run(["git", "rev-parse", "HEAD"]).decode().strip()
    application = json.loads(run(["docker", "image", "inspect", args.image]))[0]
    postgres = json.loads(run(["docker", "image", "inspect", POSTGRES_IMAGE]))[0]
    if (application["Architecture"] != "amd64" or postgres["Architecture"] != "amd64"
            or application["Config"].get("Labels", {}).get("org.opencontainers.image.revision") != revision):
        raise ValueError("需要与当前提交一致且带修订标签的 Linux amd64 应用镜像。")
    with tempfile.TemporaryDirectory(prefix="openform-release-") as temporary:
        directory = Path(temporary)
        archive = directory / "source.tar"
        with archive.open("wb") as stream:
            run(["git", "archive", "HEAD"], output=stream)
        payload = directory / "openform"
        payload.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(payload, filter="data")
        run(["docker", "tag", POSTGRES_IMAGE, POSTGRES_OFFLINE_TAG])
        run(["docker", "save", "--output", str(payload / "images.tar"), args.image, POSTGRES_OFFLINE_TAG])
        info = {"version": args.version, "revision": revision, "architecture": "linux/amd64",
                "application_image": args.image, "application_id": application["Id"], "postgres_image": POSTGRES_OFFLINE_TAG,
                "postgres_id": postgres["Id"], "postgres_source": POSTGRES_IMAGE,
                "requirements": ["Linux amd64", "Docker Engine 28+", "Docker Compose 2.24+", "Python 3.11+", "GnuPG 2.2+",
                                 "两独立 HTTPS origin 及所有学生设备信任的证书", "备份密钥与实例外存储单独保管"],
                "dependencies": "Python 精确版本与下载摘要见 uv.lock；Node 依赖见 apps/web/package-lock.json；基础镜像见 deploy/Dockerfile。"}
        (payload / "release.json").write_text(json.dumps(info, ensure_ascii=False, indent=2))
        files = {}
        for file in sorted(payload.rglob("*")):
            if file.is_file():
                with file.open("rb") as stream:
                    files[file.relative_to(payload).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
        (payload / "release-manifest.json").write_text(json.dumps({"files": files}, indent=2))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # An uncompressed archive avoids spending classroom deployment time recompressing container layers.
        with args.output.open("xb") as output:
            with tarfile.open(fileobj=output, mode="w") as bundle:
                bundle.add(payload, arcname="openform")
            output.flush()
            os.fsync(output.fileno())
    with args.output.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    with args.output.with_suffix(args.output.suffix + ".sha256").open("x") as stream:
        stream.write(f"{checksum}  {args.output.name}\n")
    print(json.dumps({"version": args.version, "revision": revision, "sha256": checksum, "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
