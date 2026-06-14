from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(name="civexhub", help="civex-hub server management", no_args_is_help=True)
console = Console()


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind address"),
    port: int = typer.Option(8001, "--port", "-p", help="Port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload (dev mode)"),
) -> None:
    """Start the civex-hub HTTP server."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn is required: pip install civexhub", err=True)
        raise typer.Exit(1)

    typer.echo(f"Starting civex-hub at http://{host}:{port}")
    typer.echo(f"API docs: http://{host}:{port}/docs")
    uvicorn.run("civexhub.server.app:app", host=host, port=port, reload=reload)


@app.command("init-db")
def init_db(
    username: str = typer.Option(None, "--admin-username", help="First admin username"),
    email: str = typer.Option(None, "--admin-email", help="First admin email"),
    password: str = typer.Option(None, "--admin-password", hide_input=True, help="First admin password"),
) -> None:
    """Create database tables and optionally create the first admin user."""
    from civexhub.config import load_config
    from civexhub.db.session import create_hub_tables, get_engine
    from civexhub.db.models import User

    try:
        cfg = load_config()
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)

    engine = get_engine(cfg.database_url)
    create_hub_tables(engine)
    console.print("[green]Hub tables created.[/green]")

    if not username:
        username = typer.prompt("Admin username")
    if not email:
        email = typer.prompt("Admin email")
    if not password:
        password = typer.prompt("Admin password", hide_input=True, confirmation_prompt=True)

    from sqlalchemy.orm import Session
    from civexhub.services.user_service import UserService
    from civex.domain.exceptions import AlreadyExistsError

    with Session(engine) as session:
        svc = UserService(session)
        try:
            dto = svc.create_user(username, email, password)
            session.commit()
            console.print(f"[green]Admin user '{dto.username}' created.[/green]")
        except AlreadyExistsError:
            console.print(f"[yellow]User '{username}' already exists — skipping.[/yellow]")


if __name__ == "__main__":
    app()
