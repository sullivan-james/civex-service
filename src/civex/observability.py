"""
Central logging + telemetry configuration for civex.

Design goals (local-first, like git):
  * One call — configure_logging() — sets up the whole stdlib + structlog pipeline.
  * Every existing `logging.getLogger(__name__)` call keeps working; library logs
    (sqlalchemy, uvicorn, ...) flow through the same renderer.
  * Human-friendly colored output on a TTY; structured JSON to a rotating file.
  * Secrets/PII are scrubbed in a processor so they can never reach a sink.
  * Telemetry (Sentry) is strictly opt-in and off by default — nothing leaves the
    machine unless the user configures a DSN.

Use `get_logger(__name__)` for new structured logging; old stdlib calls are fine too.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import structlog

# Request-scoped correlation id, set by the server middleware and read back by the
# error handlers so the client gets the same id that appears in the logs.
request_id_var: ContextVar[str | None] = ContextVar("civex_request_id", default=None)

# Keys whose values must never be logged, matched case-insensitively.
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "cookie",
        "set-cookie",
        "x-api-key",
        "dsn",
    }
)

_configured = False


def _scrub_sensitive(_logger: Any, _method: str, event_dict: dict) -> dict:
    """Redact values whose key looks like a credential."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***"
    return event_dict


def get_logger(name: str | None = None):
    """Return a structlog logger. Prefer this in new code."""
    return structlog.get_logger(name)


def configure_logging(
    level: str = "INFO",
    *,
    json_console: bool | None = None,
    log_file: Path | str | None = None,
) -> None:
    """
    Configure stdlib logging + structlog.

    level        Root log level (e.g. "INFO", "DEBUG").
    json_console Force JSON on the console. Default (None) = auto: pretty colored
                 output on a TTY, JSON otherwise (e.g. when piped/captured).
    log_file     If set, append rotating JSON logs here (5 MB × 3 backups).
    """
    global _configured

    shared_processors = [
        structlog.contextvars.merge_contextvars,  # pulls in request_id etc.
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _scrub_sensitive,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    use_json_console = (
        json_console if json_console is not None else not sys.stderr.isatty()
    )
    if use_json_console:
        console_renderer: Any = structlog.processors.JSONRenderer()
        console_exc = structlog.processors.format_exc_info
    else:
        console_renderer = structlog.dev.ConsoleRenderer(colors=True)
        # ConsoleRenderer formats exc_info itself — don't pre-render it.
        console_exc = _passthrough

    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_exc,
            console_renderer,
        ],
    )

    root = logging.getLogger()
    # Drop handlers we installed on a previous call (idempotent reconfigure).
    for h in [h for h in root.handlers if getattr(h, "_civex", False)]:
        root.removeHandler(h)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)
    console_handler._civex = True  # type: ignore[attr-defined]
    root.addHandler(console_handler)

    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        file_handler._civex = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    root.setLevel(level.upper())

    # Tame chatty libraries so INFO stays useful (uvicorn.access is left alone so
    # request logging still appears).
    for noisy in ("sqlalchemy.engine", "httpx", "watchfiles", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def _passthrough(_logger: Any, _method: str, event_dict: dict) -> dict:
    return event_dict


def init_telemetry(
    dsn: str | None,
    *,
    environment: str = "local",
    release: str | None = None,
) -> bool:
    """
    Opt-in error reporting via Sentry. Returns True if enabled.

    No-op (returns False) when no DSN is given or sentry-sdk isn't installed, so
    the default local experience never phones home.
    """
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        get_logger(__name__).warning(
            "telemetry_dsn_set_but_sdk_missing",
            hint="pip install 'civex[telemetry]'",
        )
        return False

    if release is None:
        try:
            from civex import __version__

            release = f"civex@{__version__}"
        except Exception:
            release = None

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        # Errors only by default — no performance tracing overhead for a local tool.
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    get_logger(__name__).info("telemetry_enabled", environment=environment)
    return True
