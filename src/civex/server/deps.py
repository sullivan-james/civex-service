from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.exceptions import ConfigError


def get_ctx() -> Generator[AppContext, None, None]:
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    ctx = build_local_context(config)
    try:
        yield ctx
        ctx.commit()
    except Exception:
        ctx._session.rollback()
        raise
    finally:
        ctx.close()
