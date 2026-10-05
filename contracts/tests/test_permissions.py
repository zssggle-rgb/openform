from dataclasses import replace

import pytest

from openform_contracts.permissions import ACTIONS, AccessFacts, permits


def facts(**changes):
    return replace(AccessFacts("t1", "staff", "school1", "school1", workspace_active=True, membership_active=True), **changes)


OWNER_ACTIONS = {
    "activity.create", "activity.read", "activity.edit", "activity.publish", "activity.use",
    "class.read", "classroom.start", "classroom.manage", "classroom.read", "records.read",
    "records.delete", "analysis.create", "export.create", "resource.read", "resource.publish", "resource.copy",
}
ADMIN_ACTIONS = {"membership.manage", "model.configure", "class.manage", "class.read"}
STUDENT_ACTIONS = {"attempt.load", "attempt.save", "attempt.submit", "student.history", "shared.read"}


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_independent_persona_permission_matrix(action):
    teacher = facts(roles=frozenset({"teacher"}), owner_id="t1", assigned_class=True, activity_use=True)
    admin = facts(roles=frozenset({"admin"}))
    student = facts(actor_id="s1", actor_kind="student", subject_student_id="s1", participation_active=True, history_allowed=True, shared_published=True)
    assert permits(action, teacher) == (action in OWNER_ACTIONS)
    assert permits(action, admin) == (action in ADMIN_ACTIONS)
    assert permits(action, student) == (action in STUDENT_ACTIONS)
    personal = replace(teacher, personal_owner=True)
    assert permits(action, personal) == (action in OWNER_ACTIONS | ADMIN_ACTIONS)


@pytest.mark.parametrize("change", [
    {"target_workspace_id": "another-school"}, {"workspace_active": False},
    {"membership_active": False}, {"actor_kind": "unknown"},
])
def test_invalid_server_context_denies_all_workspace_actions(change):
    actor = facts(roles=frozenset({"teacher", "admin"}), owner_id="t1", personal_owner=True, **change)
    assert not any(permits(action, actor) for action in ACTIONS)


def test_collaboration_is_explicit_and_does_not_grant_student_data():
    editor = facts(roles=frozenset({"teacher"}), owner_id="t2", grants=frozenset({"activity.edit"}))
    assert permits("activity.edit", editor)
    assert not permits("activity.publish", editor)
    assert not permits("records.read", editor)
    assert not permits("analysis.create", editor)
    assert not permits("export.create", editor)
    assert not permits("activity.edit", replace(editor, roles=frozenset()))
    assert permits("records.read", replace(editor, grants=frozenset({"records.read"})))


def test_class_start_requires_activity_use_and_assignment_except_quick_activity():
    teacher = facts(roles=frozenset({"teacher"}), activity_use=True)
    assert not permits("classroom.start", teacher)
    assert permits("classroom.start", replace(teacher, assigned_class=True))
    assert permits("classroom.start", replace(teacher, quick_activity=True))
    assert not permits("classroom.start", replace(teacher, quick_activity=True, activity_use=False))
    assert permits("class.read", replace(teacher, grants=frozenset({"class.read"})))
    assert permits("classroom.start", replace(teacher, grants=frozenset({"classroom.start"})))


def test_students_can_only_access_verified_self_and_allowed_feedback():
    student = facts(actor_id="s1", actor_kind="student", subject_student_id="s1", participation_active=True)
    assert permits("attempt.load", student)
    assert not permits("student.history", student)
    assert not permits("shared.read", student)
    assert permits("shared.read", replace(student, shared_published=True))
    assert not permits("attempt.submit", replace(student, subject_student_id="s2"))
    assert not permits("attempt.load", replace(student, participation_active=False))
    assert not permits("student.history", replace(student, history_allowed=True, membership_active=False))


def test_operations_access_is_separate_from_campus_administration():
    admin = facts(roles=frozenset({"admin"}), ops_verified=True)
    assert not permits("instance.restore", admin)
    operator = facts(actor_kind="ops", ops_verified=True)
    assert permits("instance.backup", operator)
    assert permits("instance.restore", operator)
    assert not permits("records.read", operator)
    assert not permits("instance.backup", replace(operator, ops_verified=False))
    assert not permits("made-up-action", operator)


def test_omitted_liveness_facts_are_not_an_authorization():
    actor = AccessFacts("t1", "staff", "school1", "school1", personal_owner=True, owner_id="t1")
    assert not any(permits(action, actor) for action in ACTIONS)


def test_removed_class_participation_does_not_erase_allowed_self_history():
    student = facts(actor_id="s1", actor_kind="student", subject_student_id="s1", participation_active=False, history_allowed=True)
    assert permits("student.history", student)
    assert not permits("attempt.submit", student)
