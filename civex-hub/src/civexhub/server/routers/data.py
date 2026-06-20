"""
Per-repo data API: thin wrappers around civex service methods.
All routes are prefixed /api/v1/repos/{owner}/{name}/.
Commit and audit log endpoints surface the history stored in the repo schema.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from civexhub.server.deps import CurrentUser, HubSession, OptionalUser, get_repo_service
from civexhub.services.access_service import get_effective_role

router = APIRouter(prefix="/api/v1/repos", tags=["data"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_repo_and_ctx(svc, owner: str, name: str, session, user, write: bool = False):
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.is_public or write:
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        role = get_effective_role(user.id, repo, session)
        if role is None:
            raise HTTPException(status_code=403, detail="Access denied")
        if write and role not in ("write", "admin"):
            raise HTTPException(status_code=403, detail="Write access required")
    ctx = svc.build_repo_context(repo.id)
    return ctx


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

@router.get("/{owner}/{name}/schemas")
def list_schemas(owner: str, name: str, session: HubSession, current_user: OptionalUser) -> list[dict]:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        schemas = ctx.schema_svc.list_all()
        return [_schema_dict(s) for s in schemas]
    finally:
        ctx.close()


@router.post("/{owner}/{name}/schemas", status_code=201)
def create_schema(owner: str, name: str, body: dict, session: HubSession, current_user: CurrentUser) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        s = ctx.schema_svc.create(name=body["name"], description=body.get("description"), parent=body.get("parent"))
        ctx.commit()
        return _schema_dict(s)
    finally:
        ctx.close()


@router.get("/{owner}/{name}/schemas/{schema_name}")
def get_schema(owner: str, name: str, schema_name: str, session: HubSession, current_user: OptionalUser) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        return _schema_dict(ctx.schema_svc.get(schema_name))
    finally:
        ctx.close()


@router.delete("/{owner}/{name}/schemas/{schema_name}", status_code=204)
def delete_schema(owner: str, name: str, schema_name: str, session: HubSession, current_user: CurrentUser) -> None:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        ctx.schema_svc.delete(schema_name)
        ctx.commit()
    finally:
        ctx.close()


@router.post("/{owner}/{name}/schemas/{schema_name}/fields", status_code=201)
def add_field(owner: str, name: str, schema_name: str, body: dict, session: HubSession, current_user: CurrentUser) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        f = ctx.schema_svc.add_field(
            schema_name=schema_name,
            field_name=body["name"],
            dtype=body["dtype"],
            required=body.get("required", False),
            restrictions=body.get("restrictions"),
        )
        ctx.commit()
        return {"id": str(f.id), "name": f.name, "dtype": f.dtype, "required": f.required}
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

@router.get("/{owner}/{name}/datasets")
def list_datasets(owner: str, name: str, session: HubSession, current_user: OptionalUser) -> list[dict]:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        return [_dataset_dict(d) for d in ctx.dataset_svc.list_all()]
    finally:
        ctx.close()


@router.post("/{owner}/{name}/datasets", status_code=201)
def create_dataset(owner: str, name: str, body: dict, session: HubSession, current_user: CurrentUser) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        d = ctx.dataset_svc.create(name=body["name"], description=body.get("description"))
        ctx.commit()
        return _dataset_dict(d)
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@router.get("/{owner}/{name}/datasets/{dataset_name}/records")
def list_records(
    owner: str, name: str, dataset_name: str,
    session: HubSession, current_user: OptionalUser,
    schema: str | None = None, search: str | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        records = ctx.record_svc.find(dataset_name, schema_name=schema, search=search, limit=limit, offset=offset)
        return [_record_dict(r) for r in records]
    finally:
        ctx.close()


@router.post("/{owner}/{name}/datasets/{dataset_name}/records", status_code=201)
def create_record(
    owner: str, name: str, dataset_name: str, body: dict,
    session: HubSession, current_user: CurrentUser,
) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        r = ctx.record_svc.add(
            dataset_name=dataset_name,
            schema_name=body["schema"],
            data=body.get("data", {}),
            parent_record_id=body.get("parent_record_id"),
        )
        ctx.commit()
        return _record_dict(r)
    finally:
        ctx.close()


@router.get("/{owner}/{name}/records/{record_id}")
def get_record(owner: str, name: str, record_id: str, session: HubSession, current_user: OptionalUser) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        return _record_dict(ctx.record_svc.get(record_id))
    finally:
        ctx.close()


@router.patch("/{owner}/{name}/records/{record_id}")
def update_record(
    owner: str, name: str, record_id: str, body: dict,
    session: HubSession, current_user: CurrentUser,
) -> dict:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        r = ctx.record_svc.update(record_id, body.get("data", {}))
        ctx.commit()
        return _record_dict(r)
    finally:
        ctx.close()


@router.delete("/{owner}/{name}/records/{record_id}", status_code=204)
def delete_record(
    owner: str, name: str, record_id: str,
    session: HubSession, current_user: CurrentUser,
) -> None:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user, write=True)
    try:
        ctx.record_svc.delete(record_id)
        ctx.commit()
    finally:
        ctx.close()


@router.get("/{owner}/{name}/records/{record_id}/children")
def get_record_children(
    owner: str, name: str, record_id: str,
    session: HubSession, current_user: OptionalUser,
) -> list[dict]:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        parent = ctx.record_svc.get(record_id)
        datasets = ctx.dataset_svc.list_all()
        ds = next((d for d in datasets if d.id == parent.dataset_id), None)
        if ds is None:
            return []
        children = ctx.record_svc.find(dataset_name=ds.name, parent_record_id=record_id)
        return [_record_dict(c) for c in children]
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Schema access control
# ---------------------------------------------------------------------------

class _AccessBody(BaseModel):
    subject_type: str
    subject_id: str | None = None
    role: str


@router.get("/{owner}/{name}/schemas/{schema_name}/access")
def list_schema_access(
    owner: str, name: str, schema_name: str,
    session: HubSession, current_user: CurrentUser,
) -> list[dict]:
    from civexhub.db.models import SchemaAccess
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        schema = ctx.schema_svc.get(schema_name)
    finally:
        ctx.close()
    grants = session.query(SchemaAccess).filter_by(repo_id=repo.id, schema_id=schema.id).all()
    return [_access_dict(g) for g in grants]


@router.post("/{owner}/{name}/schemas/{schema_name}/access", status_code=201)
def grant_schema_access(
    owner: str, name: str, schema_name: str, body: _AccessBody,
    session: HubSession, current_user: CurrentUser,
) -> dict:
    from civexhub.db.models import SchemaAccess
    from civexhub.services.access_service import require_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    require_role(current_user.id, repo, session, minimum="admin")
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        schema = ctx.schema_svc.get(schema_name)
    finally:
        ctx.close()
    existing = session.query(SchemaAccess).filter_by(
        repo_id=repo.id, schema_id=schema.id,
        subject_type=body.subject_type,
        subject_id=uuid.UUID(body.subject_id) if body.subject_id else None,
    ).first()
    if existing:
        existing.role = body.role
    else:
        existing = SchemaAccess(
            repo_id=repo.id,
            schema_id=schema.id,
            subject_type=body.subject_type,
            subject_id=uuid.UUID(body.subject_id) if body.subject_id else None,
            role=body.role,
        )
        session.add(existing)
    session.commit()
    return _access_dict(existing)


@router.delete("/{owner}/{name}/schemas/{schema_name}/access/{grant_id}", status_code=204)
def revoke_schema_access(
    owner: str, name: str, schema_name: str, grant_id: str,
    session: HubSession, current_user: CurrentUser,
) -> None:
    from civexhub.db.models import SchemaAccess
    from civexhub.services.access_service import require_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    require_role(current_user.id, repo, session, minimum="admin")
    grant = session.get(SchemaAccess, uuid.UUID(grant_id))
    if grant and grant.repo_id == repo.id:
        session.delete(grant)
        session.commit()


@router.get("/{owner}/{name}/schemas/{schema_name}/fields/{field_id}/access")
def list_field_access(
    owner: str, name: str, schema_name: str, field_id: str,
    session: HubSession, current_user: CurrentUser,
) -> list[dict]:
    from civexhub.db.models import FieldAccess
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    grants = session.query(FieldAccess).filter_by(
        repo_id=repo.id, field_id=uuid.UUID(field_id)
    ).all()
    return [_field_access_dict(g) for g in grants]


class _FieldAccessBody(BaseModel):
    subject_type: str
    subject_id: str | None = None
    can_read: bool = True
    can_write: bool = True


@router.post("/{owner}/{name}/schemas/{schema_name}/fields/{field_id}/access", status_code=201)
def grant_field_access(
    owner: str, name: str, schema_name: str, field_id: str, body: _FieldAccessBody,
    session: HubSession, current_user: CurrentUser,
) -> dict:
    from civexhub.db.models import FieldAccess
    from civexhub.services.access_service import require_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    require_role(current_user.id, repo, session, minimum="admin")
    fid = uuid.UUID(field_id)
    sid = uuid.UUID(body.subject_id) if body.subject_id else None
    existing = session.query(FieldAccess).filter_by(
        repo_id=repo.id, field_id=fid, subject_type=body.subject_type, subject_id=sid,
    ).first()
    if existing:
        existing.can_read = body.can_read
        existing.can_write = body.can_write
    else:
        existing = FieldAccess(
            repo_id=repo.id, field_id=fid,
            subject_type=body.subject_type, subject_id=sid,
            can_read=body.can_read, can_write=body.can_write,
        )
        session.add(existing)
    session.commit()
    return _field_access_dict(existing)


@router.delete("/{owner}/{name}/schemas/{schema_name}/fields/{field_id}/access/{grant_id}", status_code=204)
def revoke_field_access(
    owner: str, name: str, schema_name: str, field_id: str, grant_id: str,
    session: HubSession, current_user: CurrentUser,
) -> None:
    from civexhub.db.models import FieldAccess
    from civexhub.services.access_service import require_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    require_role(current_user.id, repo, session, minimum="admin")
    grant = session.get(FieldAccess, uuid.UUID(grant_id))
    if grant and grant.repo_id == repo.id:
        session.delete(grant)
        session.commit()


# ---------------------------------------------------------------------------
# Dataset access control
# ---------------------------------------------------------------------------

@router.get("/{owner}/{name}/datasets/{dataset_name}/access")
def list_dataset_access(
    owner: str, name: str, dataset_name: str,
    session: HubSession, current_user: CurrentUser,
) -> list[dict]:
    from civexhub.db.models import DatasetAccess
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        dataset = ctx.dataset_svc.get(dataset_name)
    finally:
        ctx.close()
    grants = session.query(DatasetAccess).filter_by(repo_id=repo.id, dataset_id=dataset.id).all()
    return [_access_dict(g) for g in grants]


@router.post("/{owner}/{name}/datasets/{dataset_name}/access", status_code=201)
def grant_dataset_access(
    owner: str, name: str, dataset_name: str, body: _AccessBody,
    session: HubSession, current_user: CurrentUser,
) -> dict:
    from civexhub.db.models import DatasetAccess
    from civexhub.services.access_service import require_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    require_role(current_user.id, repo, session, minimum="admin")
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        dataset = ctx.dataset_svc.get(dataset_name)
    finally:
        ctx.close()
    sid = uuid.UUID(body.subject_id) if body.subject_id else None
    existing = session.query(DatasetAccess).filter_by(
        repo_id=repo.id, dataset_id=dataset.id,
        subject_type=body.subject_type, subject_id=sid,
    ).first()
    if existing:
        existing.role = body.role
    else:
        existing = DatasetAccess(
            repo_id=repo.id, dataset_id=dataset.id,
            subject_type=body.subject_type, subject_id=sid, role=body.role,
        )
        session.add(existing)
    session.commit()
    return _access_dict(existing)


@router.delete("/{owner}/{name}/datasets/{dataset_name}/access/{grant_id}", status_code=204)
def revoke_dataset_access(
    owner: str, name: str, dataset_name: str, grant_id: str,
    session: HubSession, current_user: CurrentUser,
) -> None:
    from civexhub.db.models import DatasetAccess
    from civexhub.services.access_service import require_role
    svc = get_repo_service(session)
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    require_role(current_user.id, repo, session, minimum="admin")
    grant = session.get(DatasetAccess, uuid.UUID(grant_id))
    if grant and grant.repo_id == repo.id:
        session.delete(grant)
        session.commit()


# ---------------------------------------------------------------------------
# Commits and audit log (read from repo schema tables)
# ---------------------------------------------------------------------------

@router.get("/{owner}/{name}/commits")
def list_commits(
    owner: str, name: str,
    session: HubSession, current_user: OptionalUser,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    from civexhub.db.models import HubPush
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    repo = svc.get_repo_orm(owner, name)
    try:
        commits = ctx.audit_svc.list_commits(limit=limit, offset=offset)
    finally:
        ctx.close()

    hub_pushes = session.query(HubPush).filter_by(repo_id=repo.id).all()
    push_map: dict[str, str] = {}
    for hp in hub_pushes:
        for cid in (hp.commit_ids or []):
            push_map[cid] = hp.pusher.username if hp.pusher else "unknown"

    return [
        {
            "id": str(c.id),
            "message": c.message,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "record_count": c.record_count,
            "schema_count": c.schema_count,
            "dataset_count": c.dataset_count,
            "pushed_at": c.pushed_at.isoformat() if c.pushed_at else None,
            "pushed_by": push_map.get(str(c.id)),
        }
        for c in commits
    ]


@router.get("/{owner}/{name}/commits/{commit_id}/audit")
def get_commit_audit(
    owner: str, name: str, commit_id: str,
    session: HubSession, current_user: OptionalUser,
) -> list[dict]:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        entries = ctx.audit_svc.list_audit(commit_id=uuid.UUID(commit_id))
        return [_audit_dict(e) for e in entries]
    finally:
        ctx.close()


@router.get("/{owner}/{name}/audit")
def get_audit_log(
    owner: str, name: str,
    session: HubSession, current_user: OptionalUser,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    svc = get_repo_service(session)
    ctx = _get_repo_and_ctx(svc, owner, name, session, current_user)
    try:
        eid = uuid.UUID(entity_id) if entity_id else None
        entries = ctx.audit_svc.list_audit(
            entity_id=eid, entity_type=entity_type, limit=limit, offset=offset
        )
        return [_audit_dict(e) for e in entries]
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _schema_dict(s) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "parent_id": str(s.parent_id) if s.parent_id else None,
        "fields": [{"id": str(f.id), "name": f.name, "dtype": f.dtype, "required": f.required} for f in s.fields],
    }


def _dataset_dict(d) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "description": d.description,
        "record_count": d.record_count,
    }


def _record_dict(r) -> dict:
    return {
        "id": str(r.id),
        "schema": r.schema_name,
        "natural_name": r.natural_name,
        "dataset_id": str(r.dataset_id),
        "parent_record_id": str(r.parent_record_id) if r.parent_record_id else None,
        "data": r.data,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _audit_dict(e) -> dict:
    return {
        "id": str(e.id),
        "commit_id": str(e.commit_id) if e.commit_id else None,
        "action": e.action,
        "entity_type": e.entity_type,
        "entity_id": str(e.entity_id),
        "old_data": e.old_data,
        "new_data": e.new_data,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
    }


def _access_dict(g) -> dict:
    return {
        "id": str(g.id),
        "subject_type": g.subject_type,
        "subject_id": str(g.subject_id) if g.subject_id else None,
        "role": g.role,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


def _field_access_dict(g) -> dict:
    return {
        "id": str(g.id),
        "subject_type": g.subject_type,
        "subject_id": str(g.subject_id) if g.subject_id else None,
        "can_read": g.can_read,
        "can_write": g.can_write,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }
