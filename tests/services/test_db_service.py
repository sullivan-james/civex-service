"""DbService: status/migrate/set_url must keep working even against a
project whose configured database is unreachable or misconfigured -- that's
the whole point of exposing them as their own surface (see
civex.services.db_service's module docstring). Docker setup/teardown aren't
covered here since they need a real Docker daemon; verified manually.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civex.config import load_config
from civex.domain.exceptions import ValidationError
from civex.services import db_service


def test_get_status_on_a_fresh_sqlite_project(project_dir: Path) -> None:
    config = load_config()
    status = db_service.get_status(config)

    assert status.dialect == "sqlite"
    assert status.docker_managed is False
    assert status.docker is None
    assert status.migration.up_to_date is True
    assert status.migration.error is None


def test_migrate_is_a_noop_when_already_current(project_dir: Path) -> None:
    config = load_config()
    status = db_service.migrate(config)
    assert status.migration.up_to_date is True


def test_set_url_points_at_a_new_sqlite_file(project_dir: Path) -> None:
    config = load_config()
    new_url = f"sqlite:///{project_dir / 'other.db'}"

    status = db_service.set_url(config, new_url)

    assert status.url == new_url
    assert status.docker_managed is False
    assert status.migration.up_to_date is True
    # Reloading from disk proves it was actually persisted, not just returned.
    assert load_config().db.url == new_url


def test_set_url_rejects_an_unparseable_url(project_dir: Path) -> None:
    config = load_config()
    with pytest.raises(ValidationError, match="Could not connect"):
        db_service.set_url(config, "not-a-real-url://nope")

    # Original config must survive a rejected attempt untouched.
    assert load_config().db.url == config.db.url


def test_migration_status_reports_error_instead_of_raising_when_unreachable() -> None:
    status = db_service.migration_status(
        "postgresql+psycopg2://postgres@localhost:1/does-not-exist"
    )
    assert status.error is not None
    assert status.current_revision is None
    assert status.up_to_date is False
    assert status.head_revision  # still resolvable without a connection


def test_redact_url_masks_password_only() -> None:
    assert (
        db_service.redact_url("postgresql://user:secret@host:5432/db")
        == "postgresql://user:***@host:5432/db"
    )
    assert db_service.redact_url("sqlite:///foo/bar.db") == "sqlite:///foo/bar.db"
