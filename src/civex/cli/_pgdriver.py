from __future__ import annotations


def detect_pg_driver() -> str | None:
    try:
        import psycopg  # noqa: F401

        return "psycopg"
    except ImportError:
        pass
    try:
        import psycopg2  # noqa: F401

        return "psycopg2"
    except ImportError:
        pass
    return None


def driver_install_hint() -> str:
    return "  uv sync --extra postgres\n  pip install 'civex\\[postgres]'"
