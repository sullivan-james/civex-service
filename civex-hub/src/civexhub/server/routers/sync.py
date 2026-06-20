from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from civex.sync.bundle import SyncBundle
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle
from civexhub.db.models import HubPush
from civexhub.server.deps import CurrentUser, HubSession, OptionalUser, get_repo_service
from civexhub.services.access_service import get_effective_role

router = APIRouter(prefix="/api/v1/repos", tags=["sync"])


def _get_repo_or_404(svc, owner: str, name: str):
    repo = svc.get_repo_orm(owner, name)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("/{owner}/{name}/transfer-pack")
def transfer_pack(
    owner: str,
    name: str,
    session: HubSession,
    current_user: OptionalUser,
    since_seq: int = 0,
) -> Response:
    svc = get_repo_service(session)
    repo = _get_repo_or_404(svc, owner, name)

    if not repo.is_public:
        if current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        role = get_effective_role(current_user.id, repo, session)
        if role is None:
            raise HTTPException(status_code=403, detail="Access denied")

    ctx = svc.build_repo_context(repo.id)
    try:
        bundle = export_bundle(ctx._session, since_seq)
    finally:
        ctx.close()

    return Response(content=bundle.to_json(), media_type="application/json")


@router.post("/{owner}/{name}/receive-pack", status_code=204)
async def receive_pack(
    owner: str,
    name: str,
    request: Request,
    session: HubSession,
    current_user: CurrentUser,
) -> None:
    svc = get_repo_service(session)
    repo = _get_repo_or_404(svc, owner, name)

    role = get_effective_role(current_user.id, repo, session)
    if role not in ("write", "admin"):
        raise HTTPException(status_code=403, detail="Write access denied")

    raw = await request.body()
    try:
        bundle = SyncBundle.from_json(raw.decode())
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid bundle: {e}")

    ctx = svc.build_repo_context(repo.id)
    try:
        apply_bundle(ctx._session, bundle)
        ctx.commit()
    finally:
        ctx.close()

    commit_ids = [c["id"] for c in bundle.commits]
    hub_push = HubPush(
        repo_id=repo.id,
        pusher_id=current_user.id,
        commit_ids=commit_ids,
    )
    session.add(hub_push)
    session.commit()


@router.get("/{owner}/{name}/objects/{sha256}")
def get_object(
    owner: str,
    name: str,
    sha256: str,
    request: Request,
    session: HubSession,
    current_user: OptionalUser,
    filename: str | None = None,
) -> Response:
    svc = get_repo_service(session)
    repo = _get_repo_or_404(svc, owner, name)

    if not repo.is_public:
        if current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        role = get_effective_role(current_user.id, repo, session)
        if role is None:
            raise HTTPException(status_code=403, detail="Access denied")

    from civexhub.server.app import get_object_store
    store = get_object_store()
    try:
        data = store.get(sha256)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Object {sha256} not found")
    dl_name = filename or sha256
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{dl_name}"'},
    )


@router.put("/{owner}/{name}/objects/{sha256}", status_code=204)
async def put_object(
    owner: str,
    name: str,
    sha256: str,
    request: Request,
    session: HubSession,
    current_user: CurrentUser,
) -> None:
    svc = get_repo_service(session)
    repo = _get_repo_or_404(svc, owner, name)

    role = get_effective_role(current_user.id, repo, session)
    if role not in ("write", "admin"):
        raise HTTPException(status_code=403, detail="Write access denied")

    data = await request.body()
    from civexhub.server.app import get_object_store
    store = get_object_store()
    store.put(data, sha256)
