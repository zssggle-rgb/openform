import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openform.config import Settings
from openform.database import build_engine
from openform.errors import ApiError
from openform.identity import accounts
from openform.identity.context import set_context
from openform.identity.schemas import LoginInput, RegistrationInput
from openform.identity.security import COOKIE_NAME, new_token, token_digest
from openform.main import create_app
from openform.manage import activate_school
from openform_contracts.validation import validate
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.postgres
ORIGIN = "https://openform.test"
PASSWORD = "synthetic-password-only"


@pytest.fixture
def environment(tmp_path):
    url = os.environ.get("OPENFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires the explicitly selected dedicated PostgreSQL 18 test database.")
    secret = Path(os.environ["OPENFORM_DATABASE_PASSWORD_FILE"])
    settings = Settings(database_url=url, database_password_file=secret, app_origin=ORIGIN, environment="qa")
    engine = build_engine(settings)
    migrate = settings.model_copy(update={"database_url": type(settings.database_url)(
        settings.connection_url().set(username="openform_migrate", password=None).render_as_string(hide_password=False)),
        "database_password_file": secret.with_name("database-migrate.txt")})
    migrator = build_engine(migrate)
    created_ids = []
    campus_ids = []

    def staff(*, api=False):
        login = "qa-" + uuid4().hex[:20]
        if api:
            response = client.post("/api/auth/register", json={"login": login, "password": PASSWORD, "display_name": "合成教师"}, headers={"Origin": ORIGIN})
            assert response.status_code == 201
            account_id = response.json()["account_id"]
            token = client.cookies[COOKIE_NAME]
        else:
            account_id, token = accounts.register(engine, RegistrationInput(login=login, password=PASSWORD, display_name="合成教师"))
        created_ids.append(account_id)
        return accounts.identify(engine, token), token, login

    def campus(admin_login):
        path = tmp_path / (uuid4().hex + ".invite")
        activate_school(migrate, "合成学校", admin_login, path)
        token = path.read_text().strip()
        with migrator.connect() as connection:
            workspace_id = connection.execute(text("SELECT workspace_id FROM staff_invites WHERE token_digest=:digest"),
                                              {"digest": token_digest(token)}).scalar_one()
        campus_ids.append(workspace_id)
        return workspace_id, token

    app = create_app(settings, engine=engine)
    with TestClient(app, base_url=ORIGIN) as client:
        yield engine, migrator, client, staff, campus, settings, migrate
    with migrator.begin() as connection:
        for campus_id in campus_ids:
            connection.execute(text("DELETE FROM staff_invites WHERE workspace_id=:id"), {"id": campus_id})
            connection.execute(text("DELETE FROM memberships WHERE workspace_id=:id"), {"id": campus_id})
            connection.execute(text("DELETE FROM workspaces WHERE id=:id"), {"id": campus_id})
        for account_id in created_ids:
            connection.execute(text("DELETE FROM memberships WHERE account_id=:id"), {"id": account_id})
            connection.execute(text("DELETE FROM workspaces WHERE owner_id=:id"), {"id": account_id})
            connection.execute(text("DELETE FROM auth_sessions WHERE account_id=:id"), {"id": account_id})
            connection.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": account_id})
    engine.dispose()
    migrator.dispose()


def sign_in(client, token):
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token)
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_registration_login_cookie_logout_and_no_role_self_selection(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    identity, old_token, login = staff(api=True)
    response = client.post("/api/auth/login", json={"login": login.upper(), "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Domain=" not in cookie
    session = client.get("/api/auth/session").json()
    assert len(session["workspaces"]) == 1 and session["workspaces"][0]["kind"] == "personal"
    assert "password" not in str(session) and "token_digest" not in str(session)
    token = client.cookies[COOKIE_NAME]
    assert token != old_token
    headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    with pytest.raises(ApiError):
        accounts.identify(engine, token)
    assert client.get("/api/auth/session").status_code == 401
    response = client.post("/api/auth/register", json={"login": login, "password": PASSWORD, "display_name": "合成", "is_admin": True}, headers={"Origin": ORIGIN})
    assert response.status_code == 422


def test_origin_csrf_oversize_and_unknown_account_have_safe_errors(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    identity, token, login = staff()
    headers = sign_in(client, token)
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/auth/logout", headers={**headers, "X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/auth/logout", headers={b"Origin": ORIGIN.encode(), b"X-CSRF-Token": b"\xff"*64}).status_code == 403
    response = client.post("/api/auth/login", content=b"x" * 17000, headers={"Origin": ORIGIN})
    assert response.status_code == 413 and response.json()["code"] == "PAYLOAD_TOO_LARGE"
    response = client.post("/api/auth/login", json={"login": "qa-missing-"+uuid4().hex[:20], "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 401 and "password_hash" not in response.text
    validate("error", response.json())


def test_rls_empty_context_pool_reuse_cross_space_write_is_rejected(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    first, first_token, _ = staff()
    second, _, _ = staff()
    one = accounts.list_workspaces(engine, first)[0]["id"]
    two = accounts.list_workspaces(engine, second)[0]["id"]
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM memberships")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM workspaces")).scalar_one() == 0
    with engine.begin() as connection:
        set_context(connection, account_id=first.account_id, workspace_id=one)
        assert connection.execute(text("SELECT count(*) FROM workspaces WHERE id=:id"), {"id": two}).scalar_one() == 0
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            set_context(connection, account_id=first.account_id, workspace_id=one)
            connection.execute(text("INSERT INTO memberships (workspace_id, account_id, is_teacher) VALUES (:space, :account, true)"), {"space": two, "account": first.account_id})
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM workspaces")).scalar_one() == 0
    sign_in(client, first_token)
    assert client.get(f"/api/workspaces/{two}/members").status_code == 403


def test_invitation_single_use_bound_admin_and_school_is_not_self_service(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    admin, token, login = staff()
    other, other_token, other_login = staff()
    workspace, activation = campus(login)
    other_headers = sign_in(client, other_token)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=other_headers).status_code == 403
    headers = sign_in(client, token)
    preview = client.post("/api/invites/preview", json={"token": activation}, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["name"] == "合成学校" and preview.json()["is_admin"] and not preview.json()["is_teacher"]
    response = client.post("/api/invites/accept", json={"token": activation}, headers=headers)
    assert response.status_code == 200 and response.json()["workspace_id"] == str(workspace)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=headers).status_code == 403
    assert client.get("/api/auth/session").status_code == 200
    session = client.get("/api/auth/session").json()
    school = next(space for space in session["workspaces"] if space["kind"] == "campus")
    assert school["is_admin"] and not school["is_teacher"]
    assert client.post("/api/workspaces", json={"name": "自建学校"}, headers=headers).status_code == 404
    assert client.get(f"/api/workspaces/{workspace}/members").status_code == 200
    with migrator.connect() as connection:
        assert connection.execute(text("SELECT token_digest FROM staff_invites WHERE workspace_id=:id"), {"id": workspace}).scalar_one() != activation


def test_member_teacher_cannot_manage_and_deactivation_preserves_personal_space(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    admin, admin_token, login = staff()
    teacher, teacher_token, teacher_login = staff()
    workspace, activation = campus(login)
    admin_headers = sign_in(client, admin_token)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=admin_headers).status_code == 200
    invite = client.post(f"/api/workspaces/{workspace}/invites", json={"is_teacher": True}, headers=admin_headers).json()
    teacher_headers = sign_in(client, teacher_token)
    assert client.post("/api/invites/accept", json={"token": invite["token"]}, headers=teacher_headers).status_code == 200
    assert client.get(f"/api/workspaces/{workspace}/members").status_code == 403
    assert client.post(f"/api/workspaces/{workspace}/invites", json={"is_admin": True}, headers=teacher_headers).status_code == 403
    admin_headers = sign_in(client, admin_token)
    assert client.patch(f"/api/workspaces/{workspace}/members/{teacher.account_id}", json={"is_teacher": True, "active": False, "expected_epoch": 1}, headers=admin_headers).status_code == 204
    sign_in(client, teacher_token)
    assert client.get(f"/api/workspaces/{workspace}/members").status_code == 403
    spaces = client.get("/api/auth/session").json()["workspaces"]
    assert next(space for space in spaces if space["kind"] == "personal")["active"]
    assert not next(space for space in spaces if space["kind"] == "campus")["active"]


def test_last_admin_personal_owner_and_revoked_or_expired_invites_are_protected(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    admin, token, login = staff()
    workspace, activation = campus(login)
    headers = sign_in(client, token)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=headers).status_code == 200
    assert client.patch(f"/api/workspaces/{workspace}/members/{admin.account_id}", json={"is_teacher": True, "active": False, "expected_epoch": 1}, headers=headers).status_code == 409
    personal = accounts.list_workspaces(engine, admin)[0]["id"]
    assert client.patch(f"/api/workspaces/{personal}/members/{admin.account_id}", json={"is_teacher": True, "active": False, "expected_epoch": 1}, headers=headers).status_code == 403
    invite = client.post(f"/api/workspaces/{workspace}/invites", json={"is_teacher": True}, headers=headers).json()
    listed = client.get(f"/api/workspaces/{workspace}/invites").json()["items"]
    assert any(item["id"] == invite["id"] for item in listed)
    assert all("token" not in item and "token_digest" not in item for item in listed)
    assert client.delete(f"/api/workspaces/{workspace}/invites/{invite['id']}", headers=headers).status_code == 204
    assert client.post("/api/invites/accept", json={"token": invite["token"]}, headers=headers).status_code == 403
    invite = client.post(f"/api/workspaces/{workspace}/invites", json={"is_teacher": True}, headers=headers).json()
    with migrator.begin() as connection:
        connection.execute(text("UPDATE staff_invites SET expires_at=now()-interval '1 second' WHERE id=:id"), {"id": invite["id"]})
    assert client.post("/api/invites/accept", json={"token": invite["token"]}, headers=headers).status_code == 403


def test_account_authorization_epoch_and_instance_lock_reject_old_sessions(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    identity, token, login = staff()
    sign_in(client, token)
    with migrator.begin() as connection:
        connection.execute(text("UPDATE accounts SET auth_epoch=auth_epoch+1 WHERE id=:id"), {"id": identity.account_id})
    assert client.get("/api/auth/session").status_code == 401
    token = accounts.login(engine, LoginInput(login=login, password=PASSWORD))
    client.cookies.set(COOKIE_NAME, token)
    with migrator.begin() as connection:
        connection.execute(text("UPDATE instance_state SET restored_locked=true WHERE id=true"))
    try:
        assert client.get("/api/auth/session").status_code == 503
    finally:
        with migrator.begin() as connection:
            connection.execute(text("UPDATE instance_state SET restored_locked=false WHERE id=true"))


def test_live_invitation_remains_visible_when_recent_history_exceeds_list_limit(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    admin, token, login = staff()
    workspace, activation = campus(login)
    headers = sign_in(client, token)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=headers).status_code == 200
    pending = client.post(f"/api/workspaces/{workspace}/invites", json={"is_teacher": True}, headers=headers).json()
    historical = [{"workspace": workspace, "id": uuid4(), "digest": token_digest(new_token())} for _ in range(101)]
    with migrator.begin() as connection:
        connection.execute(text("INSERT INTO staff_invites (workspace_id, id, token_digest, is_teacher, is_admin, active, expires_at) "
                                "VALUES (:workspace, :id, :digest, true, false, false, now()+interval '8 days')"), historical)
    items = client.get(f"/api/workspaces/{workspace}/invites").json()["items"]
    assert len(items) == 100 and items[0]["id"] == pending["id"]
    assert client.delete(f"/api/workspaces/{workspace}/invites/{pending['id']}", headers=headers).status_code == 204


def test_stale_member_update_cannot_restore_revoked_administrator_role(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    admin, admin_token, login = staff()
    target, target_token, target_login = staff()
    workspace, activation = campus(login)
    headers = sign_in(client, admin_token)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=headers).status_code == 200
    invitation = client.post(f"/api/workspaces/{workspace}/invites", json={"is_teacher": True, "is_admin": True}, headers=headers).json()
    target_headers = sign_in(client, target_token)
    assert client.post("/api/invites/accept", json={"token": invitation["token"]}, headers=target_headers).status_code == 200
    headers = sign_in(client, admin_token)
    path = f"/api/workspaces/{workspace}/members/{target.account_id}"
    assert client.patch(path, json={"is_teacher": True, "is_admin": False, "expected_epoch": 1}, headers=headers).status_code == 204
    stale = client.patch(path, json={"is_teacher": True, "is_admin": True, "active": False, "expected_epoch": 1}, headers=headers)
    assert stale.status_code == 409 and stale.json()["code"] == "REVISION_CONFLICT"
    actual = next(row for row in client.get(f"/api/workspaces/{workspace}/members").json()["items"] if row["account_id"] == str(target.account_id))
    assert actual["active"] and not actual["is_admin"] and actual["auth_epoch"] == 2
    assert client.patch(path, json={"is_teacher": True, "is_admin": False, "active": False, "expected_epoch": 2}, headers=headers).status_code == 204


def test_all_members_can_be_paged_searched_and_deactivated_beyond_two_hundred(environment):
    engine, migrator, client, staff, campus, settings, migrate = environment
    admin, token, login = staff()
    workspace, activation = campus(login)
    headers = sign_in(client, token)
    assert client.post("/api/invites/accept", json={"token": activation}, headers=headers).status_code == 200
    people = [{"id": uuid4(), "login": "qa_page_" + uuid4().hex[:20], "name": f"分页成员{index}"} for index in range(205)]
    try:
        with migrator.begin() as connection:
            connection.execute(text("INSERT INTO accounts (id, login, display_name, password_hash) VALUES (:id, :login, :name, 'synthetic-disabled')"), people)
            connection.execute(text("INSERT INTO memberships (workspace_id, account_id, is_teacher) VALUES (:space, :id, true)"), [{"space": workspace, "id": person["id"]} for person in people])
        collected = []
        cursor = None
        for _ in range(6):
            result = client.get(f"/api/workspaces/{workspace}/members", params={"cursor": cursor} if cursor else {}).json()
            assert len(result["items"]) <= 50
            collected.extend(row["account_id"] for row in result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
        assert cursor is None and len(collected) == len(set(collected)) == 206
        assert set(collected) == {str(admin.account_id), *(str(person["id"]) for person in people)}
        target = people[201]
        match = client.get(f"/api/workspaces/{workspace}/members", params={"q": "分页成员201"}).json()["items"]
        assert len(match) == 1 and match[0]["account_id"] == str(target["id"])
        assert client.get(f"/api/workspaces/{workspace}/members", params={"q": "%"}).json()["items"] == []
        assert client.get(f"/api/workspaces/{workspace}/members", params={"cursor": "invalid"}).status_code == 422
        assert client.get(f"/api/workspaces/{workspace}/members", params={"q": "x" * 81}).status_code == 422
        assert client.patch(f"/api/workspaces/{workspace}/members/{target['id']}", json={"is_teacher": True, "active": False, "expected_epoch": 1}, headers=headers).status_code == 204
    finally:
        with migrator.begin() as connection:
            for person in people:
                connection.execute(text("DELETE FROM memberships WHERE workspace_id=:space AND account_id=:id"), {"space": workspace, "id": person["id"]})
                connection.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": person["id"]})


def test_rate_limit_and_operator_activation_require_restricted_role_and_exclusive_file(environment, tmp_path):
    engine, migrator, client, staff, campus, settings, migrate = environment
    for _ in range(2):
        accounts.consume_rate(engine, "qa-rate-"+str(tmp_path), limit=2)
    with pytest.raises(ApiError) as error:
        accounts.consume_rate(engine, "qa-rate-"+str(tmp_path), limit=2)
    assert error.value.status == 429
    with pytest.raises(ValueError):
        activate_school(settings, "合成校园", "qa-admin", tmp_path / "denied.invite")
    assert not (tmp_path / "denied.invite").exists()
    occupied = tmp_path / "existing.invite"
    occupied.write_text("untouched")
    with pytest.raises(FileExistsError):
        activate_school(migrate, "合成校园", "qa-admin", occupied)
    assert occupied.read_text() == "untouched"


def test_operator_command_outputs_only_result_not_activation_credential(monkeypatch, tmp_path, capsys):
    from openform import manage
    called = []
    monkeypatch.setattr("sys.argv", ["manage", "activate-school", "--name", "合成校园",
                                    "--admin-login", "qa-admin", "--invite-file", str(tmp_path / "private.invite")])
    monkeypatch.setattr(manage, "Settings", lambda: "operator-configuration")
    monkeypatch.setattr(manage, "activate_school", lambda *args: called.append(args))
    manage.main()
    assert called == [("operator-configuration", "合成校园", "qa-admin", tmp_path / "private.invite")]
    assert "operator-configuration" not in capsys.readouterr().out
