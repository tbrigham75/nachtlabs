from datetime import timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from nachtlabs.access import project_access
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.models import (
    GovernanceApproval,
    GovernanceDocument,
    GovernanceVersion,
    HoldoutContent,
    IntegrationConnection,
    IntegrationProbe,
    Project,
    ProjectIntegration,
    ProjectMember,
    User,
    now,
)
from nachtlabs.security import decrypt, encrypt
from sqlalchemy import select

from nachtlabs_api.dependencies import DB, Actor, context
from nachtlabs_api.output import GovernanceOutput, ProjectOutput
from nachtlabs_api.schemas import (
    ApprovalInput,
    DocumentInput,
    JourneyContent,
    MemberInput,
    MissionContent,
    ProjectChange,
    ProjectInput,
)

router = APIRouter(prefix="/projects", tags=["Projects and governance"])
Kind = Literal["mission", "journey", "holdout"]


def project_view(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "archived": project.archived,
        "version": project.version,
        "plan_approval_required": project.plan_approval_required,
        "delivery_mode": project.delivery_mode,
        "execution_enabled": False,
    }


@router.get("", response_model=list[ProjectOutput])
def projects(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.scope("projects:read")
    query = select(Project).where(Project.org_id == actor.org_id).order_by(Project.name, Project.id)
    if actor.key:
        query = query.where(Project.id.in_([UUID(p) for p in actor.key.project_ids]))
    elif not actor.admin:
        assert actor.user is not None
        query = query.join(ProjectMember).where(ProjectMember.user_id == actor.user.id)
    return [project_view(p) for p in db.scalars(query)]


@router.post("", status_code=201, response_model=ProjectOutput)
def create_project(body: ProjectInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    project = Project(org_id=actor.org_id, **body.model_dump())
    db.add(project)
    db.flush()
    record(
        db,
        context(request),
        "project.created",
        str(project.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project.id,
    )
    return project_view(project)


@router.get("/{project_id}", response_model=ProjectOutput)
def detail(project_id: UUID, actor: Actor, db: DB) -> dict[str, Any]:
    actor.scope("projects:read")
    project = project_access(db, actor, project_id)
    mission = db.scalar(
        select(GovernanceDocument).where(
            GovernanceDocument.project_id == project_id, GovernanceDocument.kind == "mission"
        )
    )
    journeys = list(
        db.scalars(
            select(GovernanceDocument).where(
                GovernanceDocument.project_id == project_id,
                GovernanceDocument.kind == "journey",
                GovernanceDocument.approved_version.is_not(None),
                GovernanceDocument.archived.is_(False),
            )
        )
    )
    binding = db.get(ProjectIntegration, project_id)
    connection = db.get(IntegrationConnection, binding.connection_id) if binding else None
    probe = db.get(IntegrationProbe, binding.probe_id) if binding else None
    checked = bool(
        connection
        and connection.active
        and probe
        and probe.state == "succeeded"
        and probe.connection_version == connection.version
        and probe.finished_at
        and probe.finished_at > now() - timedelta(hours=24)
    )
    return {
        **project_view(project),
        "readiness": {
            "approved_mission": bool(mission and mission.approved_version),
            "approved_journey": bool(journeys),
            "repository_configured": binding is not None,
            "repository_checked": checked,
            "agent_configured": bool(
                binding and binding.implementation_agent_id and binding.verifier_agent_id
            ),
            "execution_available": False,
        },
    }


@router.patch("/{project_id}", response_model=ProjectOutput)
def update_project(
    project_id: UUID, body: ProjectChange, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    actor.human_admin()
    project_access(db, actor, project_id)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert project is not None
    require(
        project.version == body.version, 409, "stale_version", "Project changed; refresh and retry"
    )
    project.name, project.description, project.archived = body.name, body.description, body.archived
    project.version += 1
    record(
        db,
        context(request),
        "project.updated",
        str(project.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project.id,
    )
    return project_view(project)


@router.get("/{project_id}/members")
def members(project_id: UUID, actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    project_access(db, actor, project_id)
    return [
        {"id": u.id, "name": u.name, "email": u.email, "role": u.role}
        for u in db.scalars(
            select(User)
            .join(ProjectMember)
            .where(ProjectMember.project_id == project_id, User.org_id == actor.org_id)
        )
    ]


@router.post("/{project_id}/members", status_code=201)
def add_member(
    project_id: UUID, body: MemberInput, request: Request, actor: Actor, db: DB
) -> dict[str, bool]:
    actor.human_admin()
    project_access(db, actor, project_id)
    user = db.get(User, body.user_id)
    require(
        user is not None and user.org_id == actor.org_id and user.active,
        404,
        "not_found",
        "Active user not found",
    )
    if db.get(ProjectMember, (project_id, body.user_id)) is None:
        db.add(ProjectMember(project_id=project_id, user_id=body.user_id))
    record(
        db,
        context(request),
        "project.member.added",
        str(body.user_id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
    )
    return {"ok": True}


@router.delete("/{project_id}/members/{user_id}")
def remove_member(
    project_id: UUID, user_id: UUID, request: Request, actor: Actor, db: DB
) -> dict[str, bool]:
    actor.human_admin()
    project_access(db, actor, project_id)
    member = db.get(ProjectMember, (project_id, user_id))
    if member:
        db.delete(member)
    record(
        db,
        context(request),
        "project.member.removed",
        str(user_id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
    )
    return {"ok": True}


def document_access(actor: Actor, kind: Kind) -> None:
    if kind == "holdout":
        actor.human_admin()
    else:
        actor.scope("missions:read" if kind == "mission" else "validation_journeys:read")


def version_view(
    db: DB, document: GovernanceDocument, version: GovernanceVersion
) -> dict[str, Any]:
    content = version.content
    if document.kind == "holdout":
        protected = db.get(HoldoutContent, version.id)
        assert protected is not None
        content = decrypt(protected.ciphertext, f"holdout:{version.id}")
    approval = db.scalar(
        select(GovernanceApproval).where(GovernanceApproval.version_id == version.id)
    )
    return {
        "id": document.id,
        "name": document.name,
        "kind": document.kind,
        "version": version.number,
        "latest_version": document.version,
        "approved_version": document.approved_version,
        "content": content,
        "author_id": version.author_id,
        "created_at": version.created_at,
        "approved_at": approval.created_at if approval else None,
        "approver_id": approval.approver_id if approval else None,
        "last_run": None,
        "execution_available": False,
    }


@router.get("/{project_id}/governance/{kind}", response_model=list[GovernanceOutput])
def documents(
    project_id: UUID, kind: Kind, request: Request, actor: Actor, db: DB
) -> list[dict[str, Any]]:
    project_access(db, actor, project_id)
    document_access(actor, kind)
    docs = db.scalars(
        select(GovernanceDocument)
        .where(
            GovernanceDocument.project_id == project_id,
            GovernanceDocument.kind == kind,
            GovernanceDocument.archived.is_(False),
        )
        .order_by(GovernanceDocument.created_at)
    )
    result = []
    for doc in docs:
        version = db.scalar(
            select(GovernanceVersion).where(
                GovernanceVersion.document_id == doc.id, GovernanceVersion.number == doc.version
            )
        )
        assert version is not None
        result.append(version_view(db, doc, version))
    if kind == "holdout":
        record(
            db,
            context(request),
            "governance.protected.read",
            str(project_id),
            actor=actor.actor,
            org_id=actor.org_id,
            project_id=project_id,
        )
    return result


def persist_document(
    project_id: UUID,
    kind: Kind,
    body: DocumentInput,
    request: Request,
    actor: Actor,
    db: DB,
    document_id: UUID | None = None,
) -> dict[str, Any]:
    user = actor.human_admin()
    project = project_access(db, actor, project_id, lock=True)
    require(not project.archived, 409, "archived", "Restore the project before editing governance")
    require(
        isinstance(body.content, MissionContent if kind == "mission" else JourneyContent),
        422,
        "content_type",
        "Content does not match the governance type",
    )
    if document_id:
        doc = db.scalar(
            select(GovernanceDocument)
            .where(
                GovernanceDocument.id == document_id,
                GovernanceDocument.project_id == project_id,
                GovernanceDocument.kind == kind,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        require(doc is not None, 404, "not_found", "Governance document not found")
        assert doc is not None
        require(
            doc.version == body.expected_version,
            409,
            "stale_version",
            "Document changed; reload before saving",
        )
    else:
        require(
            body.expected_version == 0,
            409,
            "stale_version",
            "New documents must begin at version zero",
        )
        doc = GovernanceDocument(project_id=project_id, kind=kind, name=body.name, version=0)
        db.add(doc)
        db.flush()
    content = body.content.model_dump(mode="json")
    if isinstance(body.content, MissionContent):
        required = set(body.content.required_journey_ids)
        found = set(
            db.scalars(
                select(GovernanceDocument.id).where(
                    GovernanceDocument.id.in_(required),
                    GovernanceDocument.project_id == project_id,
                    GovernanceDocument.kind == "journey",
                )
            )
        )
        require(
            found == required,
            422,
            "invalid_baseline",
            "Baseline journeys must belong to this project",
        )
    doc.version += 1
    doc.name = body.name if kind != "holdout" else "Protected validation"
    version_id = uuid4()
    version = GovernanceVersion(
        id=version_id,
        document_id=doc.id,
        number=doc.version,
        author_id=user.id,
        content={} if kind == "holdout" else content,
    )
    db.add(version)
    db.flush()
    if kind == "holdout":
        db.add(
            HoldoutContent(
                version_id=version_id, ciphertext=encrypt(content, f"holdout:{version_id}")
            )
        )
        db.flush()
    record(
        db,
        context(request),
        f"governance.{kind}.version_created",
        str(doc.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
        details={"version": doc.version},
    )
    return version_view(db, doc, version)


@router.post("/{project_id}/governance/{kind}", status_code=201, response_model=GovernanceOutput)
def create_document(
    project_id: UUID, kind: Kind, body: DocumentInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    return persist_document(project_id, kind, body, request, actor, db)


@router.put("/{project_id}/governance/{kind}/{document_id}", response_model=GovernanceOutput)
def update_document(
    project_id: UUID,
    kind: Kind,
    document_id: UUID,
    body: DocumentInput,
    request: Request,
    actor: Actor,
    db: DB,
) -> dict[str, Any]:
    return persist_document(project_id, kind, body, request, actor, db, document_id)


@router.get(
    "/{project_id}/governance/{kind}/{document_id}/history", response_model=list[GovernanceOutput]
)
def history(
    project_id: UUID, kind: Kind, document_id: UUID, request: Request, actor: Actor, db: DB
) -> list[dict[str, Any]]:
    project_access(db, actor, project_id)
    document_access(actor, kind)
    doc = db.get(GovernanceDocument, document_id)
    require(
        doc is not None and doc.project_id == project_id and doc.kind == kind,
        404,
        "not_found",
        "Document not found",
    )
    assert doc is not None
    record(
        db,
        context(request),
        "governance.history.read",
        str(doc.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
    )
    return [
        version_view(db, doc, v)
        for v in db.scalars(
            select(GovernanceVersion)
            .where(GovernanceVersion.document_id == doc.id)
            .order_by(GovernanceVersion.number.desc())
        )
    ]


@router.post("/{project_id}/governance/{kind}/{document_id}/approve")
def approve(
    project_id: UUID,
    kind: Kind,
    document_id: UUID,
    body: ApprovalInput,
    request: Request,
    actor: Actor,
    db: DB,
) -> dict[str, bool]:
    user = actor.human_admin()
    project = project_access(db, actor, project_id, lock=True)
    require(
        not project.archived,
        409,
        "project_archived",
        "Restore this project before approving governance",
    )
    doc = db.scalar(
        select(GovernanceDocument)
        .where(
            GovernanceDocument.id == document_id,
            GovernanceDocument.project_id == project_id,
            GovernanceDocument.kind == kind,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(doc is not None, 404, "not_found", "Document not found")
    assert doc is not None
    require(
        doc.version == body.expected_version,
        409,
        "stale_version",
        "Document changed; review the latest version",
    )
    version = db.scalar(
        select(GovernanceVersion).where(
            GovernanceVersion.document_id == doc.id, GovernanceVersion.number == doc.version
        )
    )
    assert version is not None
    if kind == "mission":
        ids = [UUID(v) for v in version.content.get("required_journey_ids", [])]
        require(
            bool(ids),
            409,
            "baseline_required",
            "Select at least one approved baseline Journey before approving the Mission",
        )
        approved = list(
            db.scalars(
                select(GovernanceDocument.id)
                .join(
                    GovernanceVersion,
                    (GovernanceVersion.document_id == GovernanceDocument.id)
                    & (GovernanceVersion.number == GovernanceDocument.approved_version),
                )
                .where(
                    GovernanceDocument.id.in_(ids),
                    GovernanceVersion.content["enabled"].as_boolean().is_(True),
                    GovernanceDocument.project_id == project_id,
                    GovernanceDocument.kind == "journey",
                    GovernanceDocument.approved_version.is_not(None),
                    GovernanceDocument.archived.is_(False),
                )
            )
        )
        require(
            set(ids) == set(approved),
            409,
            "baseline_unapproved",
            "Approve enabled baseline Journeys first",
        )
    if (
        db.scalar(select(GovernanceApproval.id).where(GovernanceApproval.version_id == version.id))
        is None
    ):
        db.add(GovernanceApproval(version_id=version.id, approver_id=user.id))
    doc.approved_version = version.number
    record(
        db,
        context(request),
        f"governance.{kind}.approved",
        str(doc.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
        details={"version": doc.version},
    )
    return {"ok": True}
