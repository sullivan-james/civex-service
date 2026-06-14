from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_JSON = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "civexhub"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tokens: Mapped[list[Token]] = relationship("Token", back_populates="user", cascade="all, delete-orphan")
    ssh_keys: Mapped[list[SSHKey]] = relationship("SSHKey", back_populates="user", cascade="all, delete-orphan")
    repositories: Mapped[list[Repository]] = relationship(
        "Repository", foreign_keys="Repository.owner_id", back_populates="owner", cascade="all, delete-orphan"
    )
    org_memberships: Mapped[list[OrgMember]] = relationship("OrgMember", back_populates="user")


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = {"schema": "civexhub"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="tokens")


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("owner_id", "name"),
        {"schema": "civexhub"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.users.id"), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("civexhub.organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id], back_populates="repositories")
    org: Mapped[Organization | None] = relationship("Organization", back_populates="repositories")
    access_grants: Mapped[list[RepoAccess]] = relationship("RepoAccess", back_populates="repo", cascade="all, delete-orphan")
    hub_pushes: Mapped[list[HubPush]] = relationship("HubPush", back_populates="repo", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Organizations + Teams
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = {"schema": "civexhub"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    members: Mapped[list[OrgMember]] = relationship("OrgMember", back_populates="org", cascade="all, delete-orphan")
    teams: Mapped[list[Team]] = relationship("Team", back_populates="org", cascade="all, delete-orphan")
    repositories: Mapped[list[Repository]] = relationship("Repository", back_populates="org")


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("org_id", "user_id"), {"schema": "civexhub"})

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.organizations.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "owner" | "member"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    org: Mapped[Organization] = relationship("Organization", back_populates="members")
    user: Mapped[User] = relationship("User", back_populates="org_memberships")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("org_id", "name"), {"schema": "civexhub"})

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    org: Mapped[Organization] = relationship("Organization", back_populates="teams")
    members: Mapped[list[TeamMember]] = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"), {"schema": "civexhub"})

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.teams.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    team: Mapped[Team] = relationship("Team", back_populates="members")
    user: Mapped[User] = relationship("User")


class RepoAccess(Base):
    """Grants a user, team, or org a role on a repository."""
    __tablename__ = "repo_access"
    __table_args__ = (UniqueConstraint("repo_id", "subject_type", "subject_id"), {"schema": "civexhub"})

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.repositories.id"), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "user" | "team" | "org"
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # "admin" | "write" | "read"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repo: Mapped[Repository] = relationship("Repository", back_populates="access_grants")


# ---------------------------------------------------------------------------
# Push attribution (hub-level tracking of who pushed which commits)
# ---------------------------------------------------------------------------

class HubPush(Base):
    """One row per civex push received by the hub, linking local commits to a hub user."""
    __tablename__ = "hub_pushes"
    __table_args__ = {"schema": "civexhub"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.repositories.id"), nullable=False)
    pusher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.users.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    commit_ids: Mapped[list[Any]] = mapped_column(_JSON, default=list)

    repo: Mapped[Repository] = relationship("Repository", back_populates="hub_pushes")
    pusher: Mapped[User] = relationship("User")


# ---------------------------------------------------------------------------
# SSH keys
# ---------------------------------------------------------------------------

class SSHKey(Base):
    __tablename__ = "ssh_keys"
    __table_args__ = {"schema": "civexhub"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    public_key: Mapped[str] = mapped_column(String(4096), unique=True, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="ssh_keys")


# ---------------------------------------------------------------------------
# Fine-grained access control (hub-only, enforced on push)
# ---------------------------------------------------------------------------

class SchemaAccess(Base):
    """Per-schema read/write restrictions, by user / team / org."""
    __tablename__ = "schema_access"
    __table_args__ = (
        UniqueConstraint("repo_id", "schema_id", "subject_type", "subject_id"),
        {"schema": "civexhub"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.repositories.id"), nullable=False)
    schema_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)   # "user" | "team" | "org" | "public"
    subject_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)     # None when public
    role: Mapped[str] = mapped_column(String(10), nullable=False)           # "read" | "write" | "none"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repo: Mapped[Repository] = relationship("Repository")


class FieldAccess(Base):
    """Per-field read/write restrictions."""
    __tablename__ = "field_access"
    __table_args__ = (
        UniqueConstraint("repo_id", "field_id", "subject_type", "subject_id"),
        {"schema": "civexhub"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.repositories.id"), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_write: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repo: Mapped[Repository] = relationship("Repository")


class DatasetAccess(Base):
    """Dataset-level access control for private datasets."""
    __tablename__ = "dataset_access"
    __table_args__ = (
        UniqueConstraint("repo_id", "dataset_id", "subject_type", "subject_id"),
        {"schema": "civexhub"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("civexhub.repositories.id"), nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)   # "user" | "team" | "org" | "public"
    subject_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)           # "read" | "write" | "none"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repo: Mapped[Repository] = relationship("Repository")
