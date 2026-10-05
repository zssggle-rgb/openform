"""Select checks affected by a PR; unknown new service modules require an explicit map."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SERVICE_SCOPES = {
    "config.py": ["services/tests/test_foundation.py"],
    "database.py": ["services/tests/test_foundation.py", "services/tests/test_postgres.py"],
    "errors.py": ["services/tests/test_foundation.py"],
    "main.py": ["services/tests/test_foundation.py"],
    "worker.py": ["services/tests/test_foundation.py"],
    "__init__.py": ["services/tests/test_foundation.py"],
}


def select_checks(changed: list[str]) -> dict[str, object]:
    targets = set()
    web = docker = postgres = False
    for name in changed:
        if name.startswith("contracts/"):
            targets.add("contracts/tests")
        elif name in {"pyproject.toml", "uv.lock", "services/pyproject.toml"}:
            targets.update({"contracts/tests", "services/tests/test_foundation.py", "services/tests/test_postgres.py"})
            postgres = True
        elif name.startswith("services/openform/"):
            module = name.removeprefix("services/openform/")
            if module not in SERVICE_SCOPES:
                raise ValueError(f"Add a focused test mapping for {name}")
            targets.update(SERVICE_SCOPES[module])
            postgres |= "services/tests/test_postgres.py" in SERVICE_SCOPES[module]
        elif name == "services/alembic.ini" or name.startswith("services/migrations/") or name.startswith("deploy/database/") or name.startswith("deploy/compose"):
            targets.add("services/tests/test_postgres.py")
            postgres = True
        elif name.startswith("services/tests/") and name.endswith(".py"):
            targets.add(name)
            postgres |= name.endswith("test_postgres.py")
        elif name in {"tools/ci_scope.py", "tools/tests/test_ci_scope.py"}:
            targets.add("tools/tests/test_ci_scope.py")
        web |= name.startswith("apps/web/") or name.startswith("assets/brand/")
        docker |= name in {"deploy/Dockerfile", "deploy/uv-tool.requirements", ".dockerignore", "uv.lock", "pyproject.toml", "services/pyproject.toml", "apps/web/package-lock.json"}
        docker |= name == "services/alembic.ini" or name.startswith("services/migrations/")
    return {"python": bool(targets), "targets": sorted(targets), "web": web, "postgres": postgres, "docker": docker}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: ci_scope.py BASE_COMMIT_SHA")
    base = sys.argv[1]
    if not re.fullmatch(r"[a-f0-9]{40}", base):
        raise ValueError("CI base must be a full Git commit SHA.")
    names = subprocess.check_output(["git", "diff", "--name-only", "-z", base, "HEAD", "--"]).decode().split("\0")
    result = select_checks([name for name in names if name])
    print(json.dumps(result))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            for key, value in result.items():
                stream.write(f"{key}={json.dumps(value)}\n")


if __name__ == "__main__":
    main()
