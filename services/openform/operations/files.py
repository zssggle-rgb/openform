"""Copy a stopped instance's files between a Docker volume and a private host staging mount."""
import argparse
import os
import shutil
from pathlib import Path


def copy_files(source: Path, destination: Path, *, restore: bool) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("目标文件目录必须为空，不能覆盖原实例。")
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if item.is_symlink() or not (item.is_dir() or item.is_file()):
            raise ValueError("文件卷包含不支持的链接或特殊文件。")
        target = destination / relative
        if item.is_dir():
            target.mkdir(mode=0o700, exist_ok=True)
        else:
            shutil.copyfile(item, target)
            target.chmod(0o600)
        if restore:
            os.chown(target, 10001, 10001)
    if restore:
        os.chown(destination, 10001, 10001)
        destination.chmod(0o700)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "restore"])
    args = parser.parse_args()
    if args.action == "export":
        copy_files(Path("/data/files"), Path("/snapshot/files"), restore=False)
    else:
        copy_files(Path("/snapshot/files"), Path("/data/files"), restore=True)


if __name__ == "__main__":
    main()
