"""Operator-only school activation; never exposed as a teacher's create-school API."""
import argparse
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from openform.config import Settings
from openform.database import build_engine
from openform.identity.members import insert_invite
from openform.identity.schemas import InviteInput
from openform.identity.security import new_token


def activate_school(settings: Settings, name: str, admin_login: str, output: Path) -> None:
    """Creates a campus and a login-bound one-use administrator invitation as migrator."""
    name = name.strip()
    data = InviteInput(is_admin=True, target_login=admin_login)
    if not 1 <= len(name) <= 80:
        raise ValueError("学校名称需要 1–80 个字符。")
    # Reserve the destination before committing; never clobber an existing credential file.
    engine = build_engine(settings)
    committed = False
    credential_persisted = False
    reserved = False
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        reserved = True
        token, workspace_id = new_token(), uuid4()
        with os.fdopen(descriptor, "w") as stream:
            with engine.begin() as connection:
                role = connection.execute(text("SELECT current_user")).scalar_one()
                if role != "openform_migrate":
                    raise ValueError("开通学校必须使用独立部署运维的迁移角色。")
                connection.execute(text("INSERT INTO workspaces (id, name, kind) VALUES (:id, :name, 'campus')"),
                                   {"id": workspace_id, "name": name})
                insert_invite(connection, workspace_id, uuid4(), token, data)
                stream.write(token + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                credential_persisted = True
            committed = True
    finally:
        engine.dispose()
        if not committed and reserved and not credential_persisted:
            output.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenForm 部署运维入口")
    subcommands = parser.add_subparsers(dest="action", required=True)
    school = subcommands.add_parser("activate-school")
    school.add_argument("--name", required=True)
    school.add_argument("--admin-login", required=True)
    school.add_argument("--invite-file", required=True, type=Path)
    args = parser.parse_args()
    activate_school(Settings(), args.name, args.admin_login, args.invite_file)
    print("学校已开通，专用管理员邀请已写入受限文件；有效期 7 天。")


if __name__ == "__main__":
    main()
