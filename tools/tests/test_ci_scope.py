import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("ci_scope", Path(__file__).parents[1] / "ci_scope.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_documentation_change_does_not_schedule_any_tests():
    assert module.select_checks(["README.md", "docs/designs/proposal.md"]) == {
        "python": False, "targets": [], "web": False, "postgres": False, "docker": False,
    }


def test_contract_and_web_changes_do_not_run_service_tests():
    result = module.select_checks(["contracts/src/openform_contracts/validation.py", "apps/web/src/api.ts"])
    assert result["targets"] == ["contracts/tests"]
    assert result["web"] is True
    assert result["postgres"] is False


def test_database_change_runs_only_foundation_and_real_postgres_checks():
    result = module.select_checks(["services/openform/database.py"])
    assert result["targets"] == ["services/tests/test_foundation.py", "services/tests/test_postgres.py"]
    assert result["postgres"] is True


@pytest.mark.parametrize("path", ["services/alembic.ini", "services/migrations/env.py"])
def test_migration_configuration_selects_database_and_packaging_checks(path):
    result = module.select_checks([path])
    assert result["targets"] == ["services/tests/test_postgres.py"]
    assert result["postgres"] is True
    assert result["docker"] is True


def test_new_module_requires_a_mapping_instead_of_silent_skip_or_full_suite():
    with pytest.raises(ValueError, match="focused test mapping"):
        module.select_checks(["services/openform/new_module.py"])


def test_cli_emits_runner_outputs_and_uses_delimited_git_arguments(monkeypatch, tmp_path, capsys):
    base = "a" * 40
    monkeypatch.setattr("sys.argv", ["ci_scope", base])
    monkeypatch.setattr(module.subprocess, "check_output", lambda args: b"README.md\0" if args == ["git", "diff", "--name-only", "-z", base, "HEAD", "--"] else pytest.fail("unsafe git arguments"))
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    module.main()
    assert json.loads(capsys.readouterr().out)["python"] is False
    assert "targets=[]\n" in output.read_text()


def test_cli_rejects_non_commit_arguments(monkeypatch):
    monkeypatch.setattr("sys.argv", ["ci_scope", "--malformed-base"])
    with pytest.raises(ValueError, match="full Git commit"):
        module.main()
    monkeypatch.setattr("sys.argv", ["ci_scope"])
    with pytest.raises(SystemExit, match="Usage"):
        module.main()
