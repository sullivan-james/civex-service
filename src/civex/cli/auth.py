from __future__ import annotations

import tomllib
from pathlib import Path

import typer

from civex.console import console

app = typer.Typer(help="Authenticate with a civex-hub server.")

_TOKENS_PATH = Path.home() / ".civex" / "tokens.toml"


def _read_tokens() -> dict:
    if not _TOKENS_PATH.exists():
        return {}
    with open(_TOKENS_PATH, "rb") as f:
        return tomllib.load(f)


def _write_tokens(data: dict) -> None:
    _TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for url, entry in data.items():
        lines.append(f'["{url}"]\n')
        for k, v in entry.items():
            lines.append(f'{k} = "{v}"\n')
        lines.append("\n")
    _TOKENS_PATH.write_text("".join(lines))


@app.command("login")
def login(
    hub_url: str = typer.Argument(..., help="civex-hub base URL (e.g. https://civexhub.example.com)"),
    username: str = typer.Option(None, "--username", "-u", help="Your username"),
    token_name: str = typer.Option("default", "--token-name", help="Label for this token"),
) -> None:
    """Log in to a civex-hub server and store an API token."""
    import urllib.request
    import urllib.error
    import json

    hub_url = hub_url.rstrip("/")

    if not username:
        username = typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True)

    payload = json.dumps({"username": username, "password": password, "name": token_name}).encode()
    req = urllib.request.Request(
        f"{hub_url}/auth/tokens",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        console.print(f"[red]Login failed ({e.code}):[/red] {body}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Connection error:[/red] {e}")
        raise typer.Exit(1)

    raw_token = result.get("token")
    if not raw_token:
        console.print("[red]Unexpected response — no token received.[/red]")
        raise typer.Exit(1)

    tokens = _read_tokens()
    tokens[hub_url] = {"token": raw_token, "username": username}
    _write_tokens(tokens)

    console.print(f"[green]Logged in to {hub_url} as {username}.[/green]")
    console.print(f"  Token saved to {_TOKENS_PATH}")


@app.command("logout")
def logout(
    hub_url: str = typer.Argument(None, help="Hub URL to log out from (omit to log out of all)"),
) -> None:
    """Remove stored credentials for a civex-hub server."""
    tokens = _read_tokens()
    if not tokens:
        console.print("[dim]Not logged in to any hub.[/dim]")
        return

    if hub_url:
        hub_url = hub_url.rstrip("/")
        if hub_url not in tokens:
            console.print(f"[dim]Not logged in to {hub_url}.[/dim]")
            return
        del tokens[hub_url]
        _write_tokens(tokens)
        console.print(f"[success]Logged out of {hub_url}.[/success]")
    else:
        _write_tokens({})
        console.print("[success]Logged out of all hubs.[/success]")


@app.command("status")
def status() -> None:
    """Show which civex-hub servers you are logged in to."""
    tokens = _read_tokens()
    if not tokens:
        console.print("[dim]Not logged in to any hub.[/dim]")
        return
    for url, entry in tokens.items():
        console.print(f"  {url}  ([dim]{entry.get('username', '?')}[/dim])")
