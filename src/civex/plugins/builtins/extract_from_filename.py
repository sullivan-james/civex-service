from __future__ import annotations

import re
from datetime import date as _date, datetime as _dt, timezone as _tz
from typing import Any

from pydantic import BaseModel

from civex.plugins.base import BasePlugin, WorkflowContext

_TOKEN_RE = re.compile(r"(YYYY|MM|DD|HH|mm|SS)")
_TOKEN_MAP = {
    "YYYY": r"(?P<year>\d{4})",
    "MM": r"(?P<month>\d{2})",
    "DD": r"(?P<day>\d{2})",
    "HH": r"(?P<hour>\d{2})",
    "mm": r"(?P<minute>\d{2})",
    "SS": r"(?P<second>\d{2})",
}


def _parse_by_format(raw: str, fmt: str, output_type: str) -> str:
    """Convert *raw* string → ISO date/datetime using token format like 'YYYYMMDD-HHmmSS'.

    Known tokens (YYYY MM DD HH mm SS) become named capture groups.
    Everything else is treated as a raw regex fragment, so you can use character
    classes — e.g. 'YYYYMMDD[-_]HHmmSS' matches both dashes and underscores.
    """
    parts = _TOKEN_RE.split(fmt)
    regex_parts = [_TOKEN_MAP[p] if p in _TOKEN_MAP else p for p in parts]
    pattern = "".join(regex_parts)
    m = re.search(pattern, raw)
    if m is None:
        raise ValueError(f"Format '{fmt}' did not match '{raw}'")
    g = m.groupdict()
    year = int(g.get("year", 1970))
    month = int(g.get("month", 1))
    day = int(g.get("day", 1))
    hour = int(g.get("hour", 0))
    minute = int(g.get("minute", 0))
    second = int(g.get("second", 0))
    if output_type == "date":
        return _date(year, month, day).isoformat()
    else:
        return _dt(year, month, day, hour, minute, second, tzinfo=_tz.utc).isoformat()


class Plugin(BasePlugin):
    id = "civex.extract_from_filename"
    name = "Extract from Filename"
    category = "data-access"

    class Config(BaseModel):
        field: str
        pattern: str = r"(.+)"
        output_type: str = "string"  # string | integer | float | date | datetime
        date_format: str | None = (
            None  # e.g. "YYYYMMDD-HHmmSS"; required when output_type is date/datetime
        )

    def run(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        raw_value = ctx.record.data.get(config.field)
        if raw_value is None:
            raise ValueError(f"Field '{config.field}' not found on record")

        if isinstance(raw_value, dict) and "filename" in raw_value:
            filename = raw_value["filename"]
        elif (
            isinstance(raw_value, list) and raw_value and isinstance(raw_value[0], dict)
        ):
            filename = raw_value[0]["filename"]
        elif isinstance(raw_value, str):
            filename = raw_value
        else:
            raise ValueError(
                f"Field '{config.field}' is not a file reference or string"
            )

        m = re.search(config.pattern, filename)
        if m is None:
            raise ValueError(
                f"Pattern '{config.pattern}' did not match filename '{filename}'"
            )
        extracted = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)

        if config.output_type == "integer":
            value = int(extracted)
        elif config.output_type == "float":
            value = float(extracted)
        elif config.output_type in ("date", "datetime"):
            if not config.date_format:
                raise ValueError(
                    "date_format is required when output_type is 'date' or 'datetime'"
                )
            value = _parse_by_format(extracted, config.date_format, config.output_type)
        else:
            value = extracted

        return {"value": value, "filename": filename, "extracted": extracted}
