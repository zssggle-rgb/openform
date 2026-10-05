"""Select checks affected by a PR; unknown new service modules require an explicit map."""
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SERVICE_SCOPES = {
    "config.py": ["services/tests/test_foundation.py", "services/tests/test_identity_security.py"],
    "database.py": ["services/tests/test_foundation.py", "services/tests/test_postgres.py", "services/tests/test_identity_postgres.py"],
    "errors.py": ["services/tests/test_foundation.py"],
    "main.py": ["services/tests/test_foundation.py", "services/tests/test_identity_postgres.py"],
    "worker.py": ["services/tests/test_foundation.py"],
    "__init__.py": ["services/tests/test_foundation.py"],
    "manage.py": ["services/tests/test_identity_postgres.py"],
    "identity/__init__.py": ["services/tests/test_identity_postgres.py"],
    "identity/accounts.py": ["services/tests/test_identity_postgres.py"],
    "identity/context.py": ["services/tests/test_identity_postgres.py"],
    "identity/members.py": ["services/tests/test_identity_postgres.py"],
    "identity/routes.py": ["services/tests/test_identity_postgres.py"],
    "identity/security.py": ["services/tests/test_identity_security.py", "services/tests/test_identity_postgres.py"],
    "identity/schemas.py": ["services/tests/test_identity_security.py", "services/tests/test_identity_postgres.py"],
    "identity/authorization.py": [],
    "identity/roster.py": [],
    "identity/roster_routes.py": [],
    "identity/roster_schemas.py": [],
    "identity/students.py": [],
    "runtime/__init__.py": [],
    "runtime/packages.py": [],
    "runtime/storage.py": [],
    "runtime/app.py": [],
    "runtime/client.js": [],
    "activities/__init__.py": [],
    "activities/schemas.py": [],
    "activities/service.py": [],
    "activities/samples.py": [],
    "activities/sample.js": [],
    "classrooms/__init__.py": [],
    "classrooms/schemas.py": [],
    "classrooms/service.py": [],
    "classrooms/guests.py": [],
    "classrooms/participants.py": [],
    "classrooms/records.py": [],
    "classrooms/summary.py": [],
    "classrooms/routes.py": [],
    "assets/__init__.py": [],
    "assets/storage.py": [],
    "assets/service.py": [],
    "assets/uploads.py": [],
    "assets/routes.py": [],
    "assets/cleanup.py": [],
    "authoring/__init__.py": [],
    "authoring/packages.py": [],
    "authoring/source.py": [],
    "authoring/imports.py": [],
    "authoring/routes.py": [],
    "jobs/__init__.py": [],
    "jobs/service.py": [],
    "jobs/runner.py": [],
    "models/__init__.py": [],
    "models/ark.py": [],
    "models/prompts.py": [],
    "library/__init__.py": [],
    "library/schemas.py": [],
    "library/service.py": [],
    "library/routes.py": [],
    "analysis/__init__.py": [],
    "analysis/model.py": [],
    "analysis/schemas.py": [],
    "analysis/service.py": [],
    "analysis/routes.py": [],
    "analysis/sharing.py": [],
}


def contract_dependencies_changed(previous: str, current: str) -> bool:
    """Compare only the resolved contract dependency tree, including package hashes."""
    def tree(content: str) -> dict[str, list[dict[str, object]]]:
        packages: dict[str, list[dict[str, object]]] = {}
        for package in tomllib.loads(content)["package"]:
            packages.setdefault(package["name"], []).append(package)
        pending = ["openform-contracts"]
        selected: dict[str, list[dict[str, object]]] = {}
        while pending:
            name = pending.pop()
            if name in selected:
                continue
            if name not in packages:
                raise ValueError("Lockfile lacks a referenced contract dependency.")
            selected[name] = packages[name]
            pending.extend(dependency["name"] for package in packages[name] for dependency in package.get("dependencies", []))
            if name == "openform-contracts":
                pending.extend(dependency["name"] for package in packages[name]
                               for dependency in package.get("dev-dependencies", {}).get("dev", []))
        return selected
    return tree(previous) != tree(current)


def select_checks(changed: list[str], *, contracts_affected: bool = True) -> dict[str, object]:
    targets = set()
    web = docker = postgres = service = False
    for name in changed:
        if name.startswith("contracts/"):
            targets.add("contracts/tests")
        elif name in {"pyproject.toml", "uv.lock", "services/pyproject.toml"}:
            targets.update({"services/tests/test_foundation.py", "services/tests/test_postgres.py",
                            "services/tests/test_identity_security.py", "services/tests/test_identity_postgres.py"})
            if name == "pyproject.toml" or name == "uv.lock" and contracts_affected:
                targets.add("contracts/tests")
            postgres = True
        elif name.startswith("services/openform/"):
            service = True
            module = name.removeprefix("services/openform/")
            if module not in SERVICE_SCOPES:
                raise ValueError(f"Add a focused test mapping for {name}")
            targets.update(SERVICE_SCOPES[module])
            postgres |= any("postgres" in target for target in SERVICE_SCOPES[module])
        elif name == "services/alembic.ini" or name.startswith("services/migrations/") or name.startswith("deploy/database/") or name.startswith("deploy/compose"):
            targets.add("services/tests/test_postgres.py")
            targets.add("services/tests/test_identity_postgres.py")
            postgres = True
        elif name.startswith("services/tests/") and name.endswith(".py"):
            targets.add(name)
            postgres |= "postgres" in name
        elif name in {"tools/ci_scope.py", "tools/tests/test_ci_scope.py"}:
            targets.add("tools/tests/test_ci_scope.py")
        web |= name.startswith("apps/web/") or name.startswith("assets/brand/")
        docker |= name in {"deploy/Dockerfile", "deploy/uv-tool.requirements", ".dockerignore", "uv.lock", "pyproject.toml", "services/pyproject.toml", "apps/web/package-lock.json"}
        docker |= name == "services/alembic.ini" or name.startswith("services/migrations/")
    return {"python": bool(targets) or service, "targets": sorted(targets), "web": web, "postgres": postgres, "docker": docker}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: ci_scope.py BASE_COMMIT_SHA")
    base = sys.argv[1]
    if not re.fullmatch(r"[a-f0-9]{40}", base):
        raise ValueError("CI base must be a full Git commit SHA.")
    names = subprocess.check_output(["git", "diff", "--name-only", "-z", base, "HEAD", "--"]).decode().split("\0")
    changed = [name for name in names if name]
    contracts_affected = True
    if "uv.lock" in changed:
        try:
            previous = subprocess.check_output(["git", "show", f"{base}:uv.lock"], stderr=subprocess.PIPE).decode()
        except subprocess.CalledProcessError:
            previous = None
        if previous is not None:
            current = subprocess.check_output(["git", "show", "HEAD:uv.lock"]).decode()
            contracts_affected = contract_dependencies_changed(previous, current)
    result = select_checks(changed, contracts_affected=contracts_affected)
    print(json.dumps(result))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            for key, value in result.items():
                stream.write(f"{key}={json.dumps(value)}\n")


if __name__ == "__main__":
    main()
