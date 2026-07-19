"""AI provider/model presets shared by the CLI (cli/ai.py) and the HTTP
config endpoint (server/routers/ai.py) -- previously each defined its own
copy of this data independently, which could silently drift (CIVEX-50). The
known-Anthropic-models catalog itself now lives on AnthropicProvider
(services/ai/providers/anthropic_provider.py, CIVEX-53) rather than here,
since it's provider-specific structured data (ModelInfo objects), not a
provider/base_url preset.
"""

from __future__ import annotations

DEFAULT_MODEL = "claude-sonnet-4-6"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = "http://localhost:11434/v1"


def resolve_preset(
    provider: str, base_url: str | None = None
) -> tuple[str, str | None, str] | None:
    """Resolve a CLI `--provider` preset name into
    (resolved_provider, resolved_base_url, default_model).

    `base_url`, when given, overrides the "ollama" preset's default base URL
    (mirrors `civex ai set-key`'s `--base-url` option) and is passed through
    as-is for "openai-compat", where it's required -- the caller must treat a
    None result there as an error. Returns None for an unrecognized provider.
    """
    if provider == "anthropic":
        return "anthropic", None, DEFAULT_MODEL
    if provider == "groq":
        return "openai-compat", GROQ_BASE_URL, "llama-3.3-70b-versatile"
    if provider == "gemini":
        return "openai-compat", GEMINI_BASE_URL, "gemini-1.5-flash"
    if provider == "ollama":
        return "openai-compat", base_url or OLLAMA_BASE_URL, "qwen2.5:7b"
    if provider == "openai-compat":
        return "openai-compat", base_url, ""
    return None
