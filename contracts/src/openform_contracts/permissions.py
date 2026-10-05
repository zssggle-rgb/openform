"""Object policy over server-established facts, never client-supplied roles."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccessFacts:
    actor_id: str
    actor_kind: str
    workspace_id: str
    target_workspace_id: str
    workspace_active: bool = False
    membership_active: bool = False
    roles: frozenset[str] = field(default_factory=frozenset)
    personal_owner: bool = False
    owner_id: str | None = None
    assigned_class: bool = False
    quick_activity: bool = False
    activity_use: bool = False
    grants: frozenset[str] = field(default_factory=frozenset)
    subject_student_id: str | None = None
    participation_active: bool = False
    history_allowed: bool = False
    shared_published: bool = False
    ops_verified: bool = False


ACTIONS = frozenset({
    "activity.create", "activity.read", "activity.edit", "activity.publish", "activity.use",
    "class.manage", "class.read", "classroom.start", "classroom.manage", "classroom.read",
    "records.read", "records.delete", "analysis.create", "export.create",
    "resource.read", "resource.publish", "resource.copy", "membership.manage", "model.configure",
    "attempt.load", "attempt.save", "attempt.submit", "student.history", "shared.read",
    "instance.backup", "instance.restore",
})


def permits(action: str, facts: AccessFacts) -> bool:
    """Central deny-by-default capability contract; the API supplies locked facts."""
    if action not in ACTIONS:
        return False
    if action in {"instance.backup", "instance.restore"}:
        return facts.actor_kind == "ops" and facts.ops_verified
    if (not facts.workspace_active or not facts.membership_active
            or facts.workspace_id != facts.target_workspace_id):
        return False
    if facts.actor_kind == "student":
        if facts.actor_id != facts.subject_student_id:
            return False
        if action == "student.history":
            return facts.history_allowed
        if action == "shared.read":
            return facts.participation_active and facts.shared_published
        return action in {"attempt.load", "attempt.save", "attempt.submit"} and facts.participation_active
    if facts.actor_kind != "staff":
        return False
    teacher = facts.personal_owner or "teacher" in facts.roles
    admin = facts.personal_owner or "admin" in facts.roles
    owner = teacher and facts.owner_id == facts.actor_id
    if action in {"membership.manage", "model.configure", "class.manage"}:
        return admin
    if action == "class.read":
        return admin or teacher and (facts.assigned_class or action in facts.grants)
    if action in {"resource.read", "resource.copy", "activity.create"}:
        return teacher
    if action == "classroom.start":
        return teacher and facts.activity_use and (facts.quick_activity or facts.personal_owner or facts.assigned_class or action in facts.grants)
    if action in {"activity.read", "activity.edit", "activity.publish", "activity.use", "resource.publish"}:
        return teacher and (owner or action in facts.grants)
    if action in {"classroom.read", "classroom.manage", "records.read", "records.delete", "analysis.create", "export.create"}:
        return teacher and (owner or action in facts.grants)
    return False
