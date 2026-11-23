"""`civex release`: releases are published on a hub, so the command only says
where; it has no subcommands (nothing is made, kept or read on this computer)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from civex.main import app

runner = CliRunner()


def test_civex_release_says_where_releases_are_published():
    bare = runner.invoke(app, ["release"])
    assert bare.exit_code == 0
    text = " ".join(bare.output.split())
    assert "published on a civex hub" in text
    assert "civex clone <repo-url> --release NAME" in text


@pytest.mark.parametrize(
    "command",
    [
        "create",
        "correct",
        "withdraw",
        "yank",
        "list",
        "show",
        "verify",
        "cite",
        "diff",
        "gather",
        "download",
        "export",
        "files",
    ],
)
def test_no_release_command_remains(command: str):
    answer = runner.invoke(app, ["release", command, "v1"])
    assert answer.exit_code == 2, (command, answer.output)
