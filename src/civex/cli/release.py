"""`civex release`: releases are published on a civex hub, not made, kept or
read on a personal computer. (A release is a permanent name, frozen content, a
citation, a public page and access control; none of that is local. To take a
hub's release, `civex clone <repo-url> --release NAME`; for a free local copy
of your own data, `civex bundle export`.)"""

from __future__ import annotations

import typer

from civex.console import console

HUB_ONLY = "Releases are published on a civex hub."

app = typer.Typer(
    help=(
        "Releases are published on a civex hub, not made here. Take one with "
        "`civex clone <repo-url> --release NAME`; copy your own data with "
        "`civex bundle export`."
    ),
    invoke_without_command=True,
)


@app.callback()
def _hub_only(ctx: typer.Context) -> None:
    console.print(
        f"{HUB_ONLY} To take one, run `civex clone <repo-url> --release NAME`; "
        "`civex bundle export` copies your own data."
    )
