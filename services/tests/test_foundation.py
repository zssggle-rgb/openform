from unittest.mock import MagicMock, patch

import pytest
from fastapi import Body
from fastapi.testclient import TestClient
from openform.config import Settings
from openform.database import DatabaseNotReady, build_engine, probe_database
from openform.errors import ApiError
from openform.main import create_app
from openform.worker import main, preflight
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError


@pytest.fixture
def settings():
    return Settings(database_url="postgresql+psycopg://openform_app@localhost/openform")


@pytest.mark.parametrize("url", ["sqlite:///fake.db", "not-a-url", "postgresql+psycopg://localhost"])
def test_only_configured_postgresql_is_accepted(url):
    with pytest.raises(ValidationError):
        Settings(database_url=url)


def test_password_file_does_not_leak_into_configuration_repr(settings, tmp_path):
    secret = tmp_path / "credential.txt"
    secret.write_text("synthetic-database-secret\n")
    config = settings.model_copy(update={"database_password_file": secret})
    assert config.connection_url().password == "synthetic-database-secret"
    assert "synthetic-database-secret" not in repr(config)
    secret.write_text("")
    with pytest.raises(ValueError):
        config.connection_url()


def test_engine_has_bounded_pool_and_hidden_parameters(settings):
    engine = build_engine(settings)
    assert engine.dialect.name == "postgresql"
    assert engine.hide_parameters is True
    assert engine.pool.size() == 10
    engine.dispose()


def connection_results(*results):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.side_effect = results
    return engine


def scalar(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def role(*flags):
    result = MagicMock()
    result.one.return_value = flags
    return result


def test_probe_requires_database_version_restricted_role_migration_and_unlocked_state():
    probe_database(connection_results(scalar(180003), role(False, False, False), scalar("0001_bootstrap"), scalar(False)))
    for version, flags, revision, locked in [
        (170007, (False, False, False), "0001_bootstrap", False),
        (180003, (True, False, False), "0001_bootstrap", False),
        (180003, (False, True, False), "0001_bootstrap", False),
        (180003, (False, False, True), "0001_bootstrap", False),
        (180003, (False, False, False), "old", False),
        (180003, (False, False, False), "0001_bootstrap", True),
    ]:
        with pytest.raises(DatabaseNotReady):
            probe_database(connection_results(scalar(version), role(*flags), scalar(revision), scalar(locked)))


def test_live_ready_and_database_failure_are_distinct_and_private(settings):
    app = create_app(settings, engine=MagicMock())
    with TestClient(app) as client:
        assert client.get("/api/health/live").json()["status"] == "alive"
        with patch("openform.main.probe_database"):
            response = client.get("/api/health/ready")
            assert response.status_code == 200
            assert response.json()["status"] == "ready"
        with patch("openform.main.probe_database", side_effect=OperationalError("secret SQL", {}, Exception("private failure"))):
            response = client.get("/api/health/ready")
            assert response.status_code == 503
            assert response.json()["code"] == "SERVICE_UNAVAILABLE"
            assert response.json()["retryable"] is True
            assert "private failure" not in response.text and "secret SQL" not in response.text
            assert response.headers["x-request-id"] == response.json()["requestId"]
        assert client.get("/api/unknown").json()["code"] == "NOT_FOUND"


def test_validation_and_domain_errors_use_safe_contract(settings):
    app = create_app(settings, engine=MagicMock())

    @app.post("/testing/validation")
    def validate_input(value: int = Body()):
        return {"value": value}

    @app.get("/testing/domain")
    def domain():
        raise ApiError(409, "STATE_CONFLICT", "状态已改变。")

    @app.get("/testing/unexpected")
    def unexpected():
        raise RuntimeError("synthetic-private-exception")

    with TestClient(app) as client:
        response = client.post("/testing/validation", json="synthetic-private-content")
        assert response.status_code == 422
        assert "synthetic-private-content" not in response.text
        assert client.get("/testing/domain").json()["code"] == "STATE_CONFLICT"
        response = client.get("/testing/unexpected")
        assert response.status_code == 500
        assert "synthetic-private-exception" not in response.text


def test_owned_engine_is_disposed_at_shutdown(settings):
    engine = MagicMock()
    with patch("openform.main.build_engine", return_value=engine):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/health/live").status_code == 200
    engine.dispose.assert_called_once()


def test_worker_preflight_and_cli_have_real_failure_status(settings, monkeypatch, capsys):
    engine = MagicMock()
    with patch("openform.worker.build_engine", return_value=engine), patch("openform.worker.probe_database"):
        assert preflight(settings) is True
    engine.dispose.assert_called_once()
    with patch("openform.worker.build_engine", return_value=MagicMock()), patch("openform.worker.probe_database", side_effect=DatabaseNotReady()):
        assert preflight(settings) is False
    monkeypatch.setattr("sys.argv", ["worker", "--check"])
    monkeypatch.setenv("OPENFORM_DATABASE_URL", "postgresql+psycopg://openform_app@localhost/openform")
    with patch("openform.worker.preflight", return_value=True):
        assert main() == 0
    with patch("openform.worker.preflight", return_value=False):
        assert main() == 1
    monkeypatch.setenv("OPENFORM_DATABASE_URL", "invalid-private-connection")
    assert main() == 1
    assert "invalid-private-connection" not in capsys.readouterr().out
