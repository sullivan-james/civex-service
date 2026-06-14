from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.config import Config, DBConfig
from civex.context import AppContext, build_local_context
from civexhub.db.models import Repository, User
from civexhub.db.session import create_repo_schema, drop_repo_schema
from civexhub.domain.dtos import RepoDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError


class RepoService:
    def __init__(
        self,
        session: Session,
        hub_engine,
        object_store,
        database_url: str,
    ) -> None:
        self._session = session
        self._hub_engine = hub_engine
        self._object_store = object_store
        self._database_url = database_url

    def create_repo(
        self,
        owner: User,
        name: str,
        description: str | None,
        is_public: bool,
    ) -> RepoDTO:
        if not name:
            raise ValidationError("Repository name is required")
        existing = (
            self._session.query(Repository)
            .filter_by(owner_id=owner.id, name=name)
            .first()
        )
        if existing:
            raise AlreadyExistsError(f"Repository '{owner.username}/{name}' already exists")

        repo = Repository(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name=name,
            description=description,
            is_public=is_public,
        )
        self._session.add(repo)
        self._session.flush()

        create_repo_schema(self._hub_engine, repo.id.hex)

        return _to_dto(repo, owner.username)

    def get_repo(self, owner_username: str, name: str) -> RepoDTO | None:
        result = (
            self._session.query(Repository, User)
            .join(User, Repository.owner_id == User.id)
            .filter(User.username == owner_username, Repository.name == name)
            .first()
        )
        if result is None:
            return None
        repo, owner = result
        return _to_dto(repo, owner.username)

    def get_repo_orm(self, owner_username: str, name: str) -> Repository | None:
        result = (
            self._session.query(Repository)
            .join(User, Repository.owner_id == User.id)
            .filter(User.username == owner_username, Repository.name == name)
            .first()
        )
        return result

    def list_repos(self, owner_username: str | None = None, include_private: bool = False) -> list[RepoDTO]:
        q = self._session.query(Repository, User).join(User, Repository.owner_id == User.id)
        if owner_username:
            q = q.filter(User.username == owner_username)
        if not include_private:
            q = q.filter(Repository.is_public.is_(True))
        return [_to_dto(repo, owner.username) for repo, owner in q.all()]

    def list_repos_for_user(self, user_id: uuid.UUID) -> list[RepoDTO]:
        """All repos owned by a user (public + private)."""
        q = (
            self._session.query(Repository, User)
            .join(User, Repository.owner_id == User.id)
            .filter(Repository.owner_id == user_id)
        )
        return [_to_dto(repo, owner.username) for repo, owner in q.all()]

    def delete_repo(self, owner_username: str, name: str) -> None:
        result = (
            self._session.query(Repository)
            .join(User, Repository.owner_id == User.id)
            .filter(User.username == owner_username, Repository.name == name)
            .first()
        )
        if result is None:
            raise NotFoundError(f"Repository '{owner_username}/{name}' not found")
        drop_repo_schema(self._hub_engine, result.id.hex)
        self._session.delete(result)

    def build_repo_context(self, repo_id: uuid.UUID) -> AppContext:
        """Build a civex AppContext pointed at this repo's PostgreSQL schema."""
        schema = f"repo_{repo_id.hex}"
        repo_url = _repo_db_url(self._database_url, schema)
        config = Config(
            project_root=Path("/tmp/civexhub-noop"),
            db=DBConfig(url=repo_url),
            remote=None,
        )
        return build_local_context(config, file_store=self._object_store)


def _repo_db_url(base_url: str, schema: str) -> str:
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}options=-csearch_path%3D{schema}"


def _to_dto(repo: Repository, owner_username: str) -> RepoDTO:
    return RepoDTO(
        id=repo.id,
        owner_id=repo.owner_id,
        owner_username=owner_username,
        name=repo.name,
        description=repo.description,
        is_public=repo.is_public,
        created_at=repo.created_at,
    )
