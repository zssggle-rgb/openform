#!/usr/bin/env python3
"""Linux operator CLI. No application Docker socket; no credentials in arguments or logs."""
import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
POSTGRES_IMAGE = "postgres:18@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722"
SERVICES = ["api", "runtime", "worker", "file-cleanup"]
MAX_BACKUP_BYTES = 32 * 1024**3


def run(command: list[str], *, data: bytes | None = None, output: Any = subprocess.PIPE) -> bytes:
    result = subprocess.run(command, input=data, stdout=output, stderr=subprocess.PIPE, cwd=ROOT, check=False)
    if result.returncode:
        # Tool stderr can contain private paths or restored data; keep it out of ordinary logs.
        raise RuntimeError(f"操作失败：{command[0]}。原实例/恢复目标保留，请按运维文档处理。")
    return result.stdout or b""


def compose(project: str, *command: str, data: bytes | None = None, output: Any = subprocess.PIPE) -> bytes:
    args = ["docker", "compose", "-p", project, "-f", str(ROOT / "deploy/compose.yaml")]
    if (ROOT / ".env").is_file():
        args += ["--env-file", str(ROOT / ".env")]
    options = ["--pull", "never"] if command[0] in {"up", "run"} else []
    if command[0] == "up":
        options += ["--no-build"]
    elif command[0] == "run":
        # Compose run has no --no-build flag. Validate the loaded image first.
        run(["docker", "image", "inspect", image(project)])
    return run([*args, command[0], *options, *command[1:]], data=data, output=output)


def database(project: str, command: list[str], *, data: bytes | None = None, output: Any = subprocess.PIPE) -> bytes:
    return compose(project, "exec", "-T", "postgres", *command, data=data, output=output)


def manage(project: str, action: str, **data: Any) -> dict[str, Any]:
    value = compose(project, "run", "--rm", "--no-deps", "-T", "migrate", "python", "-m",
                    "openform.operations.manage", data=json.dumps({"action": action, **data}).encode())
    return json.loads(value)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("密钥或授权输入必须是权限 0600 的独立普通文件。")


def image(project: str) -> str:
    config = json.loads(compose(project, "config", "--format", "json"))
    return str(config["services"]["api"]["image"])


def file_copy(project: str, directory: Path, mode: str) -> None:
    run(["docker", "run", "--rm", "--network", "none", "--user", "0:0",
         "-v", f"{project}_files:/data/files" + (":ro" if mode == "export" else ""),
         "-v", f"{directory}:/snapshot", image(project), "python", "-m", "openform.operations.files", mode])


def maintenance(project: str) -> None:
    manage(project, "maintenance-on")
    # Existing locks drain DB writes; dispatcher sees the lock and claims nothing new.
    # Allow issued model calls to reach a durable terminal state before stopping workers.
    deadline = time.monotonic() + 360
    while manage(project, "status")["inflight"]:
        if time.monotonic() > deadline:
            raise RuntimeError("任务未及时停止，维护锁继续保留；请核对未知模型调用，不自动重复调用。")
        time.sleep(5)
    compose(project, "stop", "-t", "30", *SERVICES)


def start(project: str) -> None:
    try:
        compose(project, "up", "-d", "--no-deps", *SERVICES)
        for attempt in range(10):
            try:
                compose(project, "exec", "-T", "api", "python", "-c",
                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=10).read()")
                return
            except RuntimeError:
                if attempt == 9:
                    raise
                time.sleep(2)
    except RuntimeError:
        manage(project, "maintenance-on")
        compose(project, "stop", *SERVICES)
        raise


def crypt(source: Path, target: Path, key: Path, *, decrypt: bool) -> None:
    private_file(key)
    if not 32 <= len(key.read_bytes().strip()) <= 4096:
        raise ValueError("备份密钥文件需至少 32 字节，独立保管。")
    run(["gpg", "--batch", "--no-tty", "--pinentry-mode", "loopback", "--passphrase-file", str(key),
         "--output", str(target), *(["--decrypt"] if decrypt else ["--symmetric", "--cipher-algo", "AES256"]), str(source)])
    target.chmod(0o600)


def manifest(directory: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for file in sorted(directory.rglob("*")):
        if file.is_symlink() or not (file.is_dir() or file.is_file()):
            raise ValueError("备份包含链接或特殊文件。")
        if file.is_file() and file.name != "manifest.json":
            result[file.relative_to(directory).as_posix()] = {"bytes": file.stat().st_size, "sha256": digest(file)}
    return result


def unpack(archive: Path, directory: Path) -> dict[str, Any]:
    total = 0
    seen = set()
    with tarfile.open(archive, "r:") as bundle:
        for member in bundle:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or ".." in name.parts or str(name) != member.name
                    or member.name in seen or len(seen) >= 100000
                    or not (member.name in {"database.dump", "metadata.json", "manifest.json"} or member.name.startswith("files/"))):
                raise ValueError("备份目录、文件类型或数量不符合要求。")
            seen.add(member.name)
            total += member.size
            if total > MAX_BACKUP_BYTES:
                raise ValueError("备份超过首版 32 GiB 恢复上限。")
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError("备份文件无法读取。")
            target = directory / member.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with source, target.open("xb") as stream:
                shutil.copyfileobj(source, stream)
            target.chmod(0o600)
    expected = json.loads((directory / "manifest.json").read_text())
    if manifest(directory) != expected or not {"database.dump", "metadata.json"}.issubset(expected):
        raise ValueError("备份文件摘要或文件清单不一致，未恢复。")
    metadata = json.loads((directory / "metadata.json").read_text())
    if any(expected.get(name) != value for name, value in metadata["images"].items()):
        raise ValueError("数据库中的图片引用与备份文件不一致。")
    return metadata


def backup(project: str, destination: Path, key: Path, *, keep_maintenance: bool = False) -> dict[str, Any]:
    destination = destination.resolve()
    if destination.exists() or destination.with_suffix(destination.suffix + ".json").exists():
        raise ValueError("备份目标已存在，保留历史备份，请使用新文件名。")
    private_file(key)
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    maintenance(project)
    # On every failure keep maintenance and stopped services. Do not silently resume writes.
    with tempfile.TemporaryDirectory(prefix="openform-backup-") as temporary:
        directory = Path(temporary)
        metadata = manage(project, "snapshot")
        inspected = json.loads(run(["docker", "image", "inspect", image(project)]))[0]
        metadata.update(image_id=inspected["Id"], architecture=inspected["Architecture"], postgres_image=POSTGRES_IMAGE)
        with (directory / "database.dump").open("xb") as dump:
            database(project, ["pg_dump", "-U", "openform_bootstrap", "-d", "openform", "--format=custom"], output=dump)
        file_copy(project, directory, "export")
        (directory / "metadata.json").write_text(json.dumps(metadata))
        entries = manifest(directory)
        if any(entries.get(name) != value for name, value in metadata["images"].items()):
            raise ValueError("原实例图片引用与实际文件不一致，维护锁继续保留。")
        if sum(item["bytes"] for item in entries.values()) > MAX_BACKUP_BYTES:
            raise ValueError("备份超过首版容量上限，维护锁继续保留。")
        (directory / "manifest.json").write_text(json.dumps(entries))
        archive = directory / "snapshot.tar"
        with tarfile.open(archive, "w") as bundle:
            for name in [*entries, "manifest.json"]:
                bundle.add(directory / name, arcname=name, recursive=False)
        # Exclusive reservation prevents an accidental overwrite; gpg encrypts to a private staging path.
        encrypted = directory / "snapshot.gpg"
        crypt(archive, encrypted, key, decrypt=False)
        verified_tar = directory / "verify.tar"
        crypt(encrypted, verified_tar, key, decrypt=True)
        verified = directory / "verified"
        verified.mkdir(mode=0o700)
        unpack(verified_tar, verified)
        with destination.open("xb") as stream, encrypted.open("rb") as source:
            os.fchmod(stream.fileno(), 0o600)
            shutil.copyfileobj(source, stream)
            stream.flush()
            os.fsync(stream.fileno())
        receipt = {"id": metadata["id"], "snapshot_at": metadata["snapshot_at"], "cipher_sha256": digest(destination)}
        receipt_path = destination.with_suffix(destination.suffix + ".json")
        with receipt_path.open("x") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(receipt, stream)
        manage(project, "backup-verified", id=receipt["id"], cipher_sha256=receipt["cipher_sha256"])
    if not keep_maintenance:
        manage(project, "maintenance-off")
        start(project)
    return receipt


def fresh(project: str) -> None:
    volumes = run(["docker", "volume", "ls", "--format", "{{.Name}}"] ).decode().splitlines()
    containers = run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.ID}}"])
    if containers.strip() or f"{project}_database" in volumes or f"{project}_files" in volumes:
        raise ValueError("目标已有容器或数据卷，只能安装或恢复到新的实例名。")


def restore(project: str, source: Path, key: Path) -> dict[str, Any]:
    fresh(project)
    receipt = json.loads(source.with_suffix(source.suffix + ".json").read_text())
    if receipt["cipher_sha256"] != digest(source):
        raise ValueError("加密备份摘要不匹配。")
    with tempfile.TemporaryDirectory(prefix="openform-restore-") as temporary:
        directory = Path(temporary)
        archive = directory / "snapshot.tar"
        crypt(source, archive, key, decrypt=True)
        snapshot = directory / "snapshot"
        snapshot.mkdir(mode=0o700)
        metadata = unpack(archive, snapshot)
        if metadata["id"] != receipt["id"] or metadata["architecture"] != "amd64":
            raise ValueError("备份编号或架构不支持。")
        if json.loads(run(["docker", "image", "inspect", image(project)]))[0]["Id"] != metadata["image_id"]:
            raise ValueError("恢复必须先使用备份时的同一应用镜像，之后再升级。")
        # No API, runtime or worker is started until sanitization and the restore lock commit.
        compose(project, "up", "-d", "--wait", "postgres")
        with (snapshot / "database.dump").open("rb") as stream:
            command = ["docker", "compose", "-p", project, "-f", str(ROOT / "deploy/compose.yaml")]
            if (ROOT / ".env").is_file():
                command += ["--env-file", str(ROOT / ".env")]
            result = subprocess.run([*command, "exec", "-T", "postgres", "pg_restore", "-U", "openform_bootstrap",
                                     "-d", "openform", "--clean", "--if-exists", "--exit-on-error", "--single-transaction"],
                                    stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=ROOT)
            if result.returncode:
                raise RuntimeError("数据库恢复失败，未启动业务；目标保留用于核对。")
        file_copy(project, snapshot, "restore")
        manage(project, "restore-lock", metadata=metadata, cipher_sha256=receipt["cipher_sha256"])
        compose(project, "up", "-d", "--no-deps", "api", "runtime")
    return manage(project, "status")


def initialize(args: argparse.Namespace) -> None:
    fresh(args.project)
    secret_dir = ROOT / ".local/secrets"
    if secret_dir.exists() or (ROOT / ".env").exists():
        raise ValueError("新安装目录不能包含既有凭据或环境配置。")
    for origin in (args.origin, args.runtime_origin):
        parsed = urlsplit(origin)
        if (not re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::[0-9]{1,5})?", origin)
                or parsed.scheme != "https" and not (args.development and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
                or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password
                or parsed.port is not None and not 1 <= parsed.port <= 65535):
            raise ValueError("正式环境需要独立 HTTPS origin；开发演练仅允许本机 HTTP。")
    if urlsplit(args.origin).hostname == urlsplit(args.runtime_origin).hostname and not args.development:
        raise ValueError("业务与运行页面必须使用不同主机名。")
    if not 1024 <= args.api_port <= 65535 or not 1024 <= args.runtime_port <= 65535 or args.api_port == args.runtime_port:
        raise ValueError("需要两个不同的非特权本机端口。")
    if not re.fullmatch(r"[A-Za-z0-9./:@_-]+", args.image):
        raise ValueError("镜像名称不符合要求。")
    inspected = json.loads(run(["docker", "image", "inspect", args.image]))[0]
    if inspected["Architecture"] != "amd64":
        raise ValueError("首版仅支持 Linux amd64 镜像。")
    secret_dir.mkdir(mode=0o700, parents=True)
    for name in ("database-bootstrap", "database-migrate", "database-app", "database-dispatch", "operator-key", "model-api-key"):
        path = secret_dir / f"{name}.txt"
        with path.open("x") as stream:
            # Root/0700 host directory; each container sees only its selected read-only mounts.
            os.fchmod(stream.fileno(), 0o444 if name.startswith("database-") else 0o600)
            stream.write("" if name == "model-api-key" else secrets.token_urlsafe(32) + "\n")
        os.chown(path, 10001, 10001)
    values = {"OPENFORM_IMAGE": args.image, "OPENFORM_APP_ORIGIN": args.origin, "OPENFORM_RUNTIME_ORIGIN": args.runtime_origin,
              "OPENFORM_API_PORT": args.api_port, "OPENFORM_RUNTIME_PORT": args.runtime_port,
              "OPENFORM_OFFLINE_NETWORK": "true" if args.offline else "false",
              "OPENFORM_ENVIRONMENT": "development" if args.development else "production"}
    release_file = ROOT / "release.json"
    if release_file.is_file():
        release = json.loads(release_file.read_text())
        loaded = json.loads(run(["docker", "image", "inspect", release["postgres_image"]]))[0]
        if loaded["Id"] != release["postgres_id"]:
            raise ValueError("离线数据库镜像 ID 与发布清单不一致。")
        values["OPENFORM_POSTGRES_IMAGE"] = release["postgres_image"]
    with (ROOT / ".env").open("x") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenForm Linux 安装、升级、加密备份与新实例恢复")
    parser.add_argument("--project", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--image", required=True)
    init.add_argument("--origin", required=True)
    init.add_argument("--runtime-origin", required=True)
    init.add_argument("--api-port", type=int, default=18800)
    init.add_argument("--runtime-port", type=int, default=18801)
    init.add_argument("--development", action="store_true")
    init.add_argument("--offline", action="store_true", help="容器仅内部网络，不自动访问公网；仍需校园 DNS/HTTPS")
    sub.add_parser("install")
    sub.add_parser("status")
    sub.add_parser("resume")
    sub.add_parser("recovery-open")
    for name in ("backup", "restore"):
        command = sub.add_parser(name)
        command.add_argument("--file", required=True, type=Path)
        command.add_argument("--key-file", required=True, type=Path)
    offsite = sub.add_parser("ack-offsite")
    offsite.add_argument("--receipt", required=True, type=Path)
    auth = sub.add_parser("authorize")
    auth.add_argument("--file", required=True, type=Path)
    upgrade = sub.add_parser("upgrade")
    upgrade.add_argument("--image", required=True)
    upgrade.add_argument("--backup-file", required=True, type=Path)
    upgrade.add_argument("--key-file", required=True, type=Path)
    args = parser.parse_args()
    lock = None
    try:
        if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"} or os.geteuid() != 0:
            raise ValueError("此命令需要 Linux amd64 主机的独立部署运维 sudo 权限。")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,50}", args.project):
            raise ValueError("实例名不符合要求。")
        lock = os.open(f"/run/lock/openform-{args.project}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result: Any = {"status": "completed", "action": args.action}
        if args.action == "init":
            initialize(args)
        elif args.action == "install":
            fresh(args.project)
            compose(args.project, "up", "-d", "--wait", "postgres")
            compose(args.project, "run", "--rm", "--no-deps", "migrate")
            compose(args.project, "run", "--rm", "--no-deps", "files-init")
            start(args.project)
        elif args.action == "status":
            result = manage(args.project, "status")
        elif args.action == "backup":
            result = backup(args.project, args.file, args.key_file)
        elif args.action == "restore":
            result = restore(args.project, args.file, args.key_file)
        elif args.action == "ack-offsite":
            data = json.loads(args.receipt.read_text())
            result = manage(args.project, "backup-offsite", id=data["id"], cipher_sha256=data["cipher_sha256"])
        elif args.action == "authorize":
            private_file(args.file)
            data = json.loads(args.file.read_text())
            if set(data) != {"workspace_id", "login", "password", "teacher", "admin"}:
                raise ValueError("授权文件字段不符合要求。")
            result = manage(args.project, "authorize", **data)
        elif args.action in {"resume", "recovery-open"}:
            result = manage(args.project, "maintenance-off" if args.action == "resume" else "recovery-open")
            start(args.project)
        elif args.action == "upgrade":
            # Build/pull the version beforehand; preserving the old snapshot is mandatory.
            if not re.fullmatch(r"[A-Za-z0-9./:@_-]+", args.image):
                raise ValueError("镜像名称不符合要求。")
            run(["docker", "image", "inspect", args.image])
            result = backup(args.project, args.backup_file, args.key_file, keep_maintenance=True)
            os.environ["OPENFORM_IMAGE"] = args.image
            compose(args.project, "run", "--rm", "--no-deps", "migrate")
            # Keep writers closed during the new image's restricted-role and schema checks.
            compose(args.project, "up", "-d", "--no-deps", "api", "runtime")
            compose(args.project, "exec", "-T", "api", "python", "-c",
                    "from openform.config import Settings; from openform.database import build_engine,SCHEMA_REVISION; "
                    "from sqlalchemy import text; e=build_engine(Settings()); "
                    "c=e.connect(); assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==SCHEMA_REVISION; "
                    "assert not any(c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()); "
                    "c.close(); e.dispose()")
            try:
                manage(args.project, "maintenance-off")
                start(args.project)
            except RuntimeError:
                manage(args.project, "maintenance-on")
                compose(args.project, "stop", *SERVICES)
                raise
            # Persist the selected image only after a successful readiness response.
            environment = ROOT / ".env"
            previous = environment.read_text() if environment.exists() else ""
            environment.write_text("\n".join(line for line in previous.splitlines() if not line.startswith("OPENFORM_IMAGE="))
                                   + f"\nOPENFORM_IMAGE={args.image}\n")
            environment.chmod(0o600)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError):
        print("运维操作未完成或存在并发操作，保留原实例及恢复目标；核对受限输入、磁盘容量与运维文档。", file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    sys.exit(main())
