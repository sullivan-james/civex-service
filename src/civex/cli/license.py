"""civex license — print this build's software license text.

Deliberately doesn't require a civex project (no cli_load_config()/get_ctx())
-- it's the license for the software itself, not project-scoped data.
"""

from __future__ import annotations

from civex.console import console
from civex.services.policy_service import _find_license_text


def license_cmd() -> None:
    """Print civex's software license."""
    console.print(_find_license_text())
