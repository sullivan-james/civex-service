"""
civexhub-shell — SSH forced-command handler for civex-hub.

Installed in authorized_keys as:
    command="civexhub-shell --user <username>",no-port-forwarding,no-X11-forwarding,no-pty <pubkey>

sshd sets SSH_ORIGINAL_COMMAND to whatever the SSH client requested, e.g.:
    civex transfer-pack /alice/myrepo --since-seq 0

civexhub-keys — queried by sshd's AuthorizedKeysCommand directive.
Prints all public keys for a given username in authorized_keys format.
"""
from __future__ import annotations

import os
import sys


# ---------------------------------------------------------------------------
# civexhub-shell entry point
# ---------------------------------------------------------------------------

def shell_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--user", required=True)
    args, _ = parser.parse_known_args()
    username = args.user

    cmd_str = os.environ.get("SSH_ORIGINAL_COMMAND", "").strip()
    if not cmd_str:
        _die("No command provided. This shell only accepts civex plumbing commands.")

    parts = cmd_str.split()
    # Strip leading "civex" so callers can use either:
    #   civex transfer-pack owner/repo
    #   transfer-pack owner/repo
    if parts and parts[0] == "civex":
        parts = parts[1:]

    if len(parts) < 2:
        _die(f"Unrecognised command: {cmd_str!r}")

    verb = parts[0]
    repo_arg = parts[1].lstrip("/")  # strip leading slash from URL-parsed path

    if "/" not in repo_arg:
        _die(f"Expected <owner>/<repo>, got {repo_arg!r}")
    owner, repo_name = repo_arg.split("/", 1)

    cfg = _load_config()
    engine = _get_engine(cfg)
    store = _get_store(cfg)

    from sqlalchemy.orm import Session
    from civexhub.services.repo_service import RepoService
    from civexhub.services.user_service import UserService

    with Session(engine) as session:
        user_svc = UserService(session)
        user = user_svc.get_by_username(username)
        if user is None:
            _die(f"Unknown user: {username!r}")

        repo_svc = RepoService(session, engine, store, cfg.database_url)
        repo = repo_svc.get_repo_orm(owner, repo_name)
        if repo is None:
            _die(f"Repository {owner}/{repo_name} not found")

        from civexhub.services.access_service import get_effective_role
        role = get_effective_role(user.id, repo, session)

        if verb == "transfer-pack":
            if not repo.is_public and role is None:
                _die("Access denied")
            since_seq = 0
            if "--since-seq" in parts:
                idx = parts.index("--since-seq")
                if idx + 1 < len(parts):
                    since_seq = int(parts[idx + 1])
            ctx = repo_svc.build_repo_context(repo.id)
            try:
                from civex.sync.exporter import export_bundle
                bundle = export_bundle(ctx._session, since_seq)
            finally:
                ctx.close()
            sys.stdout.buffer.write(bundle.to_json().encode())
            sys.stdout.buffer.flush()

        elif verb == "receive-pack":
            if role not in ("write", "admin"):
                _die("Write access denied")
            raw = sys.stdin.buffer.read()
            from civex.sync.bundle import SyncBundle
            from civex.sync.importer import apply_bundle
            from civexhub.db.models import HubPush
            bundle = SyncBundle.from_json(raw.decode())
            ctx = repo_svc.build_repo_context(repo.id)
            try:
                apply_bundle(ctx._session, bundle)
                ctx.commit()
            finally:
                ctx.close()
            commit_ids = [c["id"] for c in bundle.commits]
            hub_push = HubPush(repo_id=repo.id, pusher_id=user.id, commit_ids=commit_ids)
            session.add(hub_push)
            session.commit()

        elif verb == "head-seq":
            if not repo.is_public and role is None:
                _die("Access denied")
            ctx = repo_svc.build_repo_context(repo.id)
            try:
                from civex.db.models import Commit
                from sqlalchemy import func
                seq = ctx._session.query(func.max(Commit.seq)).scalar() or 0
            finally:
                ctx.close()
            sys.stdout.buffer.write(str(seq).encode())
            sys.stdout.buffer.flush()

        elif verb == "get-object":
            if not repo.is_public and role is None:
                _die("Access denied")
            if len(parts) < 3:
                _die("Usage: get-object <owner/repo> <sha256>")
            sha256 = parts[2]
            try:
                data = store.get(sha256)
            except FileNotFoundError:
                _die(f"Object {sha256} not found")
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        elif verb == "put-object":
            if role not in ("write", "admin"):
                _die("Write access denied")
            if len(parts) < 3:
                _die("Usage: put-object <owner/repo> <sha256>")
            sha256 = parts[2]
            data = sys.stdin.buffer.read()
            store.put(data, sha256)

        else:
            _die(f"Unknown command: {verb!r}")


# ---------------------------------------------------------------------------
# civexhub-keys entry point (called by sshd AuthorizedKeysCommand)
# ---------------------------------------------------------------------------

def keys_main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)
    username = sys.argv[1]

    cfg = _load_config()
    engine = _get_engine(cfg)

    from sqlalchemy.orm import Session
    from civexhub.services.user_service import UserService

    with Session(engine) as session:
        user_svc = UserService(session)
        user = user_svc.get_by_username(username)
        if user is None:
            sys.exit(0)
        keys = user_svc.list_ssh_keys(user.id)
        for key in keys:
            opts = f'command="civexhub-shell --user {username}",no-port-forwarding,no-X11-forwarding,no-pty'
            print(f"{opts} {key.public_key}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _die(msg: str) -> None:
    print(f"civexhub-shell: {msg}", file=sys.stderr)
    sys.exit(1)


def _load_config():
    from civexhub.config import load_config
    return load_config()


def _get_engine(cfg):
    from civexhub.db.session import get_engine
    return get_engine(cfg.database_url)


def _get_store(cfg):
    if cfg.object_store == "s3":
        from civexhub.repositories.object_store import S3ObjectStore
        return S3ObjectStore(
            bucket=cfg.s3_bucket,
            prefix=cfg.s3_prefix,
            endpoint_url=cfg.s3_endpoint_url,
            access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key,
        )
    from civex.config import StoreConfig, VolumeConfig
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore
    vol = VolumeConfig(name="default", path=str(cfg.objects_dir))
    sc = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    return VolumeAwareFileObjectStore(sc, cfg.objects_dir)
