"""Every non-hidden CLI option and argument must have help= set.

Bare options render as empty description cells on the generated CLI reference
pages, which is far more visible there than in terminal --help output.
"""
from __future__ import annotations

import typer.main
from typing import Any

from civex.main import app as cli_app

# typer vendors its own Click fork under typer._click and does not depend on
# the PyPI click package, so isinstance checks against click.core.Group /
# Command don't hold here — duck-type on `.commands` instead.


def _param_hint(param: Any) -> str:
    opts = getattr(param, "opts", None)
    if opts:
        long_opts = [o for o in opts if o.startswith("--")]
        return long_opts[0] if long_opts else opts[0]
    name = getattr(param, "name", "arg")
    return f"<{name}>"


def _iter_visible_params(cmd: Any, path: list[str], hidden: bool) -> list[tuple[str, str]]:
    hidden = hidden or getattr(cmd, "hidden", False)
    if hidden:
        return []

    missing: list[tuple[str, str]] = []
    for param in getattr(cmd, "params", []):
        if getattr(param, "hidden", False):
            continue
        if not getattr(param, "help", None):
            missing.append((" ".join(path), _param_hint(param)))

    if hasattr(cmd, "commands"):
        for name, sub in cmd.commands.items():
            missing += _iter_visible_params(sub, path + [name], hidden)

    return missing


def test_all_cli_options_and_arguments_have_help() -> None:
    click_app = typer.main.get_command(cli_app)
    missing = _iter_visible_params(click_app, [], hidden=False)
assert not missing, (
    "These CLI options/arguments are missing help=:\n"
    + "\n".join(
        f"  civex {cmd} {param}" if cmd else f"  civex {param}"
        for cmd, param in missing
    )
)
