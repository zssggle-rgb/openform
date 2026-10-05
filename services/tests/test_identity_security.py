from unittest.mock import MagicMock, patch

import pytest
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.context import require_instance
from openform.identity.schemas import InviteInput, RegistrationInput
from openform.identity.security import csrf_token, hash_password, new_token, token_digest, verify_password
from pydantic import ValidationError


def test_opaque_tokens_have_required_entropy_and_invalid_forms_are_denied():
    first, second = new_token(), new_token()
    assert len(first) == 43 and first != second
    assert len(token_digest(first)) == 64 and token_digest(first) != token_digest(second)
    for value in ("", "short", first + "x", "!" * 43):
        with pytest.raises(ApiError) as error:
            token_digest(value)
        assert error.value.status == 401


def test_csrf_is_bound_to_this_session_not_reusable_between_identities():
    first, second = new_token(), new_token()
    assert csrf_token(first) == csrf_token(first)
    assert csrf_token(first) != csrf_token(second)
    assert csrf_token(first) != token_digest(first)


def test_maintained_hash_verifies_and_unknown_accounts_or_hashes_deny():
    password = "  synthetic password preserved  "
    hashed = hash_password(password)
    assert hashed.startswith("$argon2id$") and password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password(password.strip(), hashed)
    assert not verify_password(password, None)
    assert not verify_password(password, "unsupported-hash")


@pytest.mark.parametrize("operation", [hash_password, verify_password])
def test_expensive_hashing_has_bounded_capacity(operation):
    with patch("openform.identity.security.AUTH_SLOTS.acquire", return_value=False):
        with pytest.raises(ApiError) as error:
            operation("synthetic-password", None) if operation is verify_password else operation("synthetic-password")
    assert error.value.status == 429


def test_identity_fields_and_no_client_role_in_registration():
    data = RegistrationInput(login="Teacher.A", password="  twelve character password  ", display_name=" A ")
    assert data.login == "teacher.a" and data.display_name == "A"
    assert data.password.startswith("  ") and data.password.endswith("  ")
    for fields in ({"password": "short"}, {"display_name": "   "}, {"is_admin": True}, {"login": "路径/输入"}):
        values = {"login": "teacher", "password": "synthetic-password", "display_name": "Teacher", **fields}
        with pytest.raises(ValidationError):
            RegistrationInput(**values)
    with pytest.raises(ValidationError):
        InviteInput()


@pytest.mark.parametrize("state", [True, None])
def test_unknown_or_locked_instance_never_allows_account_writes(state):
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = state
    with pytest.raises(ApiError) as error:
        require_instance(connection)
    assert error.value.status == 503


def test_lost_activation_commit_acknowledgement_keeps_the_only_credential(tmp_path):
    from openform.manage import activate_school
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = "openform_migrate"
    engine.begin.return_value.__exit__.side_effect = ConnectionError("synthetic lost commit response")
    output = tmp_path / "private.invite"
    with patch("openform.manage.build_engine", return_value=engine), patch("openform.manage.insert_invite"):
        with pytest.raises(ConnectionError):
            activate_school(MagicMock(), "合成学校", "qa-admin", output)
    assert len(output.read_text().strip()) == 43
    assert output.stat().st_mode & 0o777 == 0o600
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("origin", ["https://example.com/path", "https://u:p@example.com", "https://example.com?x=1", "file:///tmp", "https://example.com/"])
def test_origin_configuration_does_not_silently_accept_paths_or_credentials(origin):
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://openform_app@localhost/openform", app_origin=origin)
