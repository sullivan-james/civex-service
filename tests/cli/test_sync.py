from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_status_says_so_when_not_following_an_authority(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "status"])
    assert result.exit_code == 0, result.output
    assert "Not following" in result.output


def test_sync_now_without_an_authority_explains(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "now"])
    assert result.exit_code == 1
    assert "civex sync connect" in result.output


def test_devices_are_invited_listed_cancelled_and_revoked(project_dir: Path) -> None:
    assert runner.invoke(app, ["sync", "authority", "enable"]).exit_code == 0
    invited = runner.invoke(app, ["sync", "device", "invite", "laptop"])
    assert invited.exit_code == 0, invited.output
    assert "civex_inv_" in invited.output and "This authority's key" in invited.output
    assert "invited, until" in runner.invoke(app, ["sync", "device", "list"]).output
    assert runner.invoke(app, ["sync", "device", "cancel", "laptop"]).exit_code == 0
    assert runner.invoke(app, ["sync", "device", "cancel", "laptop"]).exit_code == 1
    assert runner.invoke(app, ["sync", "device", "revoke", "laptop"]).exit_code == 1


def test_conflicts_lists_nothing_on_a_fresh_project(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "conflicts"])
    assert result.exit_code == 0
    assert "No conflicts" in result.output


def test_the_recorded_name_can_be_chosen_and_reset(project_dir: Path) -> None:
    assert "Dana" in runner.invoke(app, ["sync", "user", "Dana"]).output
    assert "Dana" in runner.invoke(app, ["sync", "user"]).output
    assert "Dana" not in runner.invoke(app, ["sync", "user", "--reset"]).output


def test_the_name_lives_in_this_projects_config(project_dir: Path) -> None:
    runner.invoke(app, ["sync", "user", "Dana"])
    assert 'name = "Dana"' in (project_dir / "_civex" / "config.toml").read_text()


def test_the_interval_can_be_never(project_dir: Path) -> None:
    assert "only when asked" in runner.invoke(app, ["sync", "interval", "never"]).output
    assert runner.invoke(app, ["sync", "interval", "2"]).exit_code == 1


# -- what the app can do, the CLI can too ---------------------------------------


def _clash(ctx, make_schema, make_collection, make_record):
    """A record whose 'site' clashed: the authority's value stayed."""
    make_schema("spot", fields=[("site", "string")])
    make_collection("survey")
    record = make_record("survey", "spot", {"site": "theirs"})
    field = next(f for f in ctx.schema_svc.get("spot").fields if f.name == "site")
    clash = ctx.sync_repo.add_conflict(
        kind="conflict",
        entity_type="record",
        entity_id=record.id,
        field=f"data.{field.id}",
        yours="mine",
        theirs="theirs",
        op_id=None,
        device_name=None,
        message=None,
    )
    ctx.commit()
    return record, clash


def test_a_clash_can_be_settled_with_another_value(
    ctx, make_schema, make_collection, make_record
) -> None:
    record, clash = _clash(ctx, make_schema, make_collection, make_record)
    result = runner.invoke(
        app, ["sync", "resolve", str(clash.id), "--take", "value", "--value", '"both"']
    )
    assert result.exit_code == 0, result.output
    ctx._session.expire_all()
    assert ctx.record_svc.get(str(record.id)).data["site"] == "both"


def test_keeping_theirs_can_be_taken_back(
    ctx, make_schema, make_collection, make_record
) -> None:
    _, clash = _clash(ctx, make_schema, make_collection, make_record)
    runner.invoke(app, ["sync", "resolve", str(clash.id), "--take", "theirs"])
    result = runner.invoke(app, ["sync", "reopen", str(clash.id)])
    assert result.exit_code == 0, result.output
    assert "Opened 1 again" in result.output
    ctx._session.expire_all()
    assert ctx.sync_repo.get_conflict(clash.id).status == "open"


def test_conflicts_can_be_narrowed_to_one_record(
    ctx, make_schema, make_collection, make_record
) -> None:
    record, _ = _clash(ctx, make_schema, make_collection, make_record)
    mine = runner.invoke(app, ["sync", "conflicts", "--record", str(record.id)])
    other = runner.invoke(
        app, ["sync", "conflicts", "--record", "00000000-0000-0000-0000-000000000000"]
    )
    assert "mine" in mine.output and "theirs" in mine.output  # its row
    assert "No conflicts" in other.output


def test_connecting_without_an_invite_needs_to_have_joined(project_dir: Path) -> None:
    result = runner.invoke(app, ["sync", "connect", "http://127.0.0.1:9"])
    assert result.exit_code == 1
    assert "invite" in result.output


def test_serving_is_switched_the_same_way_as_in_the_app(project_dir: Path) -> None:
    from civex.config import load_config

    assert runner.invoke(app, ["sync", "authority", "enable"]).exit_code == 0
    assert load_config().sync.serve is True
    assert runner.invoke(app, ["sync", "authority", "disable"]).exit_code == 0
    assert load_config().sync.serve is False
