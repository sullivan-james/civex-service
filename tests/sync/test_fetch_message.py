"""`civex sync fetch` says what is true about the files: under the on-demand
default it says how many are here and how many are not, and how to get them."""

from __future__ import annotations

from typer.testing import CliRunner

from civex.main import app

from .test_files_on_this_computer import _with_file

runner = CliRunner()


def _fetch(monkeypatch, ctx) -> str:
    class Held:
        def __getattr__(self, name):
            return getattr(ctx, name)

        def close(self) -> None:  # the test's context stays open
            pass

    monkeypatch.setattr("civex.cli.sync._ctx", lambda: Held())
    result = runner.invoke(app, ["sync", "fetch"])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


def test_fetch_under_on_demand_says_files_are_not_here_and_how_to_get_them(
    pair, monkeypatch
):
    laptop, phone, record = pair
    _with_file(laptop, record, b"twelve bytes")
    phone.sync_svc.set_download_files("opened")
    phone.commit()
    phone.sync_svc.sync()
    out = _fetch(monkeypatch, phone)
    assert "Every file" not in out
    assert "0 file(s) are on this computer and 1 are not" in out
    assert "civex sync keep" in out


def test_fetch_says_every_file_is_here_only_when_it_is(pair, monkeypatch):
    laptop, phone, record = pair
    _with_file(laptop, record, b"twelve bytes")
    phone.sync_svc.sync()
    phone.sync_svc.fetch_files()
    phone.commit()
    assert "Every file the server has is here (1)." in _fetch(monkeypatch, phone)
