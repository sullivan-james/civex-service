from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import cli_load_config, get_ctx
from civex.config import AIConfig, save_config
from civex.console import console
from civex.services.ai.config import resolve_preset
from civex.services.ai.providers import AnthropicProvider

app = typer.Typer(help="Configure the AI assistant")

# Flat id list, derived from the structured catalog (CIVEX-53).
ANTHROPIC_MODELS = [m.id for m in AnthropicProvider().known_models()]


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
    preset = resolve_preset(provider, base_url)
    if preset is None:
        console.print(
            f"[error]Unknown provider '{provider}'. Use: anthropic, groq, gemini, or openai-compat.[/error]"
        )
        raise typer.Exit(1)
    resolved_provider, resolved_base_url, default_model = preset
    if provider == "openai-compat":
        if not resolved_base_url:
            console.print(
                "[error]--base-url is required for openai-compat provider.[/error]"
            )
            raise typer.Exit(1)
        default_model = model or ""

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


@app.command("usage")
def ai_usage() -> None:
    """Show all-time AI token usage, broken down by provider/model."""
    ctx = get_ctx()
    total = ctx.ai_usage_svc.totals()
    by_model = ctx.ai_usage_svc.by_model()

    if total.requests == 0:
        console.print("[info]No AI usage recorded yet.[/info]")
        return

    console.print("[bold]AI Token Usage (all-time)[/bold]")
    console.print(f"  Requests  {total.requests}")
    console.print(f"  Input     {total.input_tokens:,} tokens")
    console.print(f"  Output    {total.output_tokens:,} tokens")
    console.print(f"  Total     {total.total_tokens:,} tokens")
    console.print()

    table = Table("Provider", "Model", "Requests", "Input", "Output", "Total")
    for m in by_model:
        table.add_row(
            m.provider,
            m.model,
            str(m.totals.requests),
            f"{m.totals.input_tokens:,}",
            f"{m.totals.output_tokens:,}",
            f"{m.totals.total_tokens:,}",
        )
    console.print(table)


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
