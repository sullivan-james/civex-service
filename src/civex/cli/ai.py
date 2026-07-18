from __future__ import annotations

from typing import Optional

import typer

from civex.cli.utils import cli_load_config
from civex.config import AIConfig, save_config
from civex.console import console

app = typer.Typer(help="Configure the AI assistant")

ANTHROPIC_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
]

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = "http://localhost:11434/v1"


@app.command("status")
def ai_status() -> None:
    """Show current AI configuration."""
    config = cli_load_config()
    if not config.ai:
        console.print("[warning]AI assistant not configured.[/warning]")
        console.print()
        console.print("Free option (Groq):")
        console.print("  1. Get a free key at [bold]console.groq.com/keys[/bold]")
        console.print("  2. Run [bold]civex ai set-key gsk_... --provider groq[/bold]")
        console.print()
        console.print("Or for Anthropic/Claude:")
        console.print("  [bold]civex ai set-key sk-ant-...[/bold]")
        return

    ai = config.ai
    key = ai.api_key
    hint = f"...{key[-6:]}" if len(key) >= 6 else "***"
    source = (
        "environment variable (ANTHROPIC_API_KEY)"
        if ai.from_env
        else "_civex/config.toml"
    )

    console.print("[bold]AI Configuration[/bold]")
    console.print("  Status   [success]configured[/success]")
    console.print(f"  Key      {hint}")
    console.print(f"  Model    {ai.model}")
    console.print(f"  Provider {ai.provider}")
    if ai.base_url:
        console.print(f"  Base URL {ai.base_url}")
    console.print(f"  Source   {source}")


@app.command("set-key")
def ai_set_key(
    api_key: str = typer.Argument(
        ...,
        help="API key. For Ollama, pass any value (e.g. 'ollama') — the key is ignored locally.",
    ),
    provider: str = typer.Option(
        "anthropic",
        "--provider",
        "-p",
        help="Provider: anthropic | groq | gemini | ollama | openai-compat",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model name (uses provider default if not set)"
    ),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", help="Base URL (only needed for openai-compat provider)"
    ),
) -> None:
    """Set the AI API key and provider in _civex/config.toml."""
    config = cli_load_config()

    # Resolve preset providers
    resolved_provider = "anthropic"
    resolved_base_url: str | None = None
    default_model = "claude-sonnet-4-6"

    if provider == "anthropic":
        resolved_provider = "anthropic"
        default_model = "claude-sonnet-4-6"
    elif provider == "groq":
        resolved_provider = "openai-compat"
        resolved_base_url = GROQ_BASE_URL
        default_model = "llama-3.3-70b-versatile"
    elif provider == "gemini":
        resolved_provider = "openai-compat"
        resolved_base_url = GEMINI_BASE_URL
        default_model = "gemini-1.5-flash"
    elif provider == "ollama":
        resolved_provider = "openai-compat"
        resolved_base_url = base_url or OLLAMA_BASE_URL
        default_model = "qwen2.5:7b"
    elif provider == "openai-compat":
        resolved_provider = "openai-compat"
        resolved_base_url = base_url
        if not resolved_base_url:
            console.print(
                "[error]--base-url is required for openai-compat provider.[/error]"
            )
            raise typer.Exit(1)
        default_model = model or ""
    else:
        console.print(
            f"[error]Unknown provider '{provider}'. Use: anthropic, groq, gemini, or openai-compat.[/error]"
        )
        raise typer.Exit(1)

    current_model = config.ai.model if config.ai else default_model
    final_model = model or current_model if config.ai else model or default_model

    config.ai = AIConfig(
        api_key=api_key,
        model=final_model,
        provider=resolved_provider,
        base_url=resolved_base_url,
        from_env=False,
    )
    save_config(config)
    hint = f"...{api_key[-6:]}" if len(api_key) >= 6 else "***"
    provider_label = {
        "anthropic": "Anthropic/Claude",
        "groq": "Groq",
        "gemini": "Gemini",
        "ollama": "Ollama (local)",
    }.get(provider, provider)
    console.print(
        f"[success]API key saved ({hint}). Provider: {provider_label}. Model: {final_model}[/success]"
    )


@app.command("set-model")
def ai_set_model(
    model: str = typer.Argument(..., help="Model name"),
) -> None:
    """Set the model used by the AI assistant."""
    config = cli_load_config()
    if not config.ai:
        console.print(
            "[error]No API key configured. Run `civex ai set-key` first.[/error]"
        )
        raise typer.Exit(1)
    if config.ai.provider == "anthropic" and model not in ANTHROPIC_MODELS:
        console.print(
            f"[warning]Warning: '{model}' is not a known Anthropic model.[/warning]"
        )
        console.print(f"Known Anthropic models: {', '.join(ANTHROPIC_MODELS)}")
    config.ai = AIConfig(
        api_key=config.ai.api_key,
        model=model,
        provider=config.ai.provider,
        base_url=config.ai.base_url,
        from_env=config.ai.from_env,
    )
    save_config(config)
    console.print(f"[success]Model set to {model}.[/success]")


@app.command("clear")
def ai_clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove the AI API key from _civex/config.toml."""
    config = cli_load_config()
    if not config.ai or config.ai.from_env:
        console.print("[info]No API key in config.toml to remove.[/info]")
        return
    if not yes:
        typer.confirm("Remove the AI API key from _civex/config.toml?", abort=True)
    config.ai = None
    save_config(config)
    console.print("[success]AI API key removed from config.toml.[/success]")
