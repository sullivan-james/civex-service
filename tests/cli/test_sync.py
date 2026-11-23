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


def test_connecting_without_an_invite_asks_the_server_to_be_let_in(
    project_dir: Path,
) -> None:
    """Never joined and no invite: the command asks the server for a code to
    be approved, so a server that can't be reached is what fails."""
    result = runner.invoke(app, ["sync", "connect", "http://127.0.0.1:9"])
    assert result.exit_code == 1
    assert "Could not reach" in result.output


def test_serving_is_switched_the_same_way_as_in_the_app(project_dir: Path) -> None:
    from civex.config import load_config

    assert runner.invoke(app, ["sync", "authority", "enable"]).exit_code == 0
    assert load_config().sync.serve is True
    assert runner.invoke(app, ["sync", "authority", "disable"]).exit_code == 0
    assert load_config().sync.serve is False


# -- device sign-in from the CLI --------------------------------------------------


def _fake_connect(verify_url: str | None, seen: dict):
    from civex.domain.sync import LoginStarted

    def connect(self, url, invite, progress=None, on_code=None):  # noqa: ANN001
        seen["invite"] = invite
        assert on_code is not None
        on_code(
            LoginStarted(
                user_code="ABCD-2345",
                device_code="secret",
                expires_at=4_000_000_000,
                interval=1,
                verify_url=verify_url,
            )
        )
        return "empty"

    return connect


def test_the_code_is_shown_with_the_page_to_enter_it_at(
    project_dir: Path, monkeypatch
) -> None:
    from civex.services.sync_service import SyncService

    monkeypatch.setattr(
        SyncService, "connect", _fake_connect("https://hub.example/device", {})
    )
    result = runner.invoke(app, ["sync", "connect", "https://hub.example"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "Open https://hub.example/device and enter the code" in out
    assert "ABCD-2345" in out
    assert "civex sync device approve" not in out


def test_the_old_hint_stays_for_an_authority_with_no_page(
    project_dir: Path, monkeypatch
) -> None:
    from civex.services.sync_service import SyncService

    monkeypatch.setattr(SyncService, "connect", _fake_connect(None, {}))
    result = runner.invoke(app, ["sync", "connect", "http://127.0.0.1:9"])
    assert result.exit_code == 0, result.output
    assert "civex sync device approve ABCD-2345" in " ".join(result.output.split())


def test_clone_signs_in_when_there_is_no_invite(tmp_path: Path, monkeypatch) -> None:
    from civex.services.sync_service import SyncService

    monkeypatch.chdir(tmp_path)
    seen: dict = {}
    monkeypatch.setattr(
        SyncService, "connect", _fake_connect("https://hub.example/device", seen)
    )
    monkeypatch.delenv("CIVEX_SYNC_INVITE", raising=False)
    result = runner.invoke(app, ["clone", "https://hub.example/birds", "copy"])
    assert result.exit_code == 0, result.output
    assert seen["invite"] is None
    assert "ABCD-2345" in result.output and "Cloned into" in result.output
    assert (tmp_path / "copy").is_dir()


def test_auth_status_says_so_when_not_following(project_dir: Path) -> None:
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0, result.output
    assert "Not following" in result.output


def test_auth_status_shows_remote_device_joined_and_last_error(
    project_dir: Path, monkeypatch
) -> None:
    from civex.services.sync_service import DeviceIdentity, SyncService

    who = DeviceIdentity(
        remote="https://hub.example",
        device_id="d-1",
        joined=True,
        device_name="laptop",
        last_error="boom",
        last_error_at="2026-01-01",
    )
    monkeypatch.setattr(SyncService, "identity", lambda self, ask=True: who)
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "Authority https://hub.example" in out
    assert "Device laptop" in out
    assert "Device id d-1" in out
    assert "Joined yes" in out
    assert "Last sync error boom" in out


def test_clone_stops_cleanly_when_sign_in_is_denied_and_can_be_run_again(
    tmp_path: Path, monkeypatch
) -> None:
    from civex.domain.sync import SyncError
    from civex.services.sync_service import SyncService

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CIVEX_SYNC_INVITE", raising=False)

    def denied(self, url, invite, progress=None, on_code=None):  # noqa: ANN001
        raise SyncError("The request was denied, or it expired", retryable=False)

    monkeypatch.setattr(SyncService, "connect", denied)
    result = runner.invoke(app, ["clone", "https://hub.example/birds", "copy"])
    assert result.exit_code == 1
    assert "denied, or it expired" in " ".join(result.output.split())
    assert "Cloned into" not in result.output

    # The folder an attempt left behind is used again, not refused.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(SyncService, "connect", _fake_connect(None, {}))
    again = runner.invoke(app, ["clone", "https://hub.example/birds", "copy"])
    assert again.exit_code == 0, again.output
    assert "Cloned into" in again.output


def test_clone_will_not_connect_a_project_that_already_holds_data(
    tmp_path: Path, monkeypatch
) -> None:
    from civex.services.sync_service import SyncService

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(SyncService, "connect", _fake_connect(None, {}))
    assert runner.invoke(app, ["clone", "https://hub.example/birds", "copy"]).exit_code == 0
    monkeypatch.chdir(tmp_path / "copy")
    assert runner.invoke(app, ["schema", "create", "thing"]).exit_code == 0
    monkeypatch.chdir(tmp_path)
    again = runner.invoke(app, ["clone", "https://hub.example/birds", "copy"])
    assert again.exit_code == 1
    assert "already a civex project" in " ".join(again.output.split())
