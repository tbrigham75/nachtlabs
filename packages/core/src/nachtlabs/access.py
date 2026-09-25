from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nachtlabs.errors import require
from nachtlabs.models import APIKey, Project, ProjectMember, User, UserSession

ADMIN_ROLES = {"owner", "admin"}
KEY_SCOPES = {"projects:read", "missions:read", "validation_journeys:read", "audit:read", "work_requests:create", "work_requests:read", "runs:read"}


@dataclass
class Principal:
    org_id: UUID
    actor: str
    user: User | None = None
    session: UserSession | None = None
    key: APIKey | None = None

    @property
    def admin(self) -> bool:
        return self.user is not None and self.user.role in ADMIN_ROLES

    def human_admin(self) -> User:
        require(self.admin, 403, "forbidden", "An Owner or Admin account is required")
        assert self.user is not None
        return self.user

    def scope(self, name: str) -> None:
        if self.key:
            require(name in self.key.scopes, 403, "scope_required", "API key scope is insufficient")


def project_access(db: Session, principal: Principal, project_id: UUID, lock: bool = False) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True)) if lock else db.get(Project, project_id)
    require(project is not None and project.org_id == principal.org_id, 404, "not_found", "Project not found")
    assert project is not None
    if principal.key:
        require(str(project_id) in principal.key.project_ids, 404, "not_found", "Project not found")
    elif not principal.admin:
        assert principal.user is not None
        membership = db.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == principal.user.id,
        ))
        require(membership is not None, 404, "not_found", "Project not found")
    return project

