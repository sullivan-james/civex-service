from __future__ import annotations

import io
import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, Field, field_validator

from civex.domain.exceptions import ValidationError
from civex.plugins.base import Tier0Plugin, WorkflowContext

log = logging.getLogger(__name__)

# Names that can be written in place of a separator, because a literal tab is
# awkward in YAML (and invisible in a config file).
_NAMED = {
    "comma": ",",
    "tab": "\t",
    "semicolon": ";",
    "pipe": "|",
    "space": " ",
    "colon": ":",
}
# How many lines of the file decide which separator it uses.
_SAMPLE_LINES = 10


def resolve_delimiter(token: str, *, single_char: bool = True) -> str:
    """The separator a workflow wrote: the character itself, a name (`tab`,
    `comma`, ...), or the two characters `\\t`. With `single_char=False` any
    other string is passed through unchanged, as pandas has always accepted
    (`||`, or a regular expression); the separators of a `delimiters` list must
    each be one character, since it is the file's own lines that choose between
    them."""
    if token == "\\t":
        return "\t"
    named = _NAMED.get(token.strip().lower())
    if named is not None:
        return named
    if len(token) == 1 or not single_char:
        return token
    raise ValueError(
        f"'{token}' is not a single separator character. Use one character, or "
        f"one of: {', '.join(_NAMED)}."
    )


def _count_outside_quotes(line: str, ch: str) -> int:
    """How many times `ch` separates fields in `line`: occurrences inside a
    double-quoted field don't count."""
    count, quoted = 0, False
    for c in line:
        if c == '"':
            quoted = not quoted
        elif c == ch and not quoted:
            count += 1
    return count


def detect_delimiter(text: str, candidates: list[str]) -> str:
    """The candidate separator this text actually uses.

    The first lines are looked at: a separator used by the file splits every
    line into the same number of fields, so the best candidate is the one that
    appears the same (non-zero) number of times on every sampled line, then the
    one that appears most, then the one listed first. A file that uses none of
    them (a single column) gets the first candidate.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()][:_SAMPLE_LINES]
    if not lines or len(candidates) == 1:
        return candidates[0]

    def score(i_ch: tuple[int, str]) -> tuple[int, int, int]:
        i, ch = i_ch
        counts = [_count_outside_quotes(ln, ch) for ln in lines]
        steady = len(set(counts)) == 1 and counts[0] > 0
        return (1 if steady else 0, min(counts), -i)

    best = max(enumerate(candidates), key=score)
    return best[1] if score(best)[1] > 0 else candidates[0]


class Plugin(Tier0Plugin):
    id = "civex.parse_table"
    name = "Parse Table"
    description = (
        "Parse delimited text (CSV, TSV, ...) into a table for a downstream "
        "records step."
    )
    category = "data-sources"
    capabilities: list[str] = []
    inputs = [
        IOSpec(
            name="bytes",
            type="bytes",
            description="Raw file contents: CSV, TSV or other delimited text.",
        )
    ]
    outputs = [
        IOSpec(name="table", type="table", description="The parsed rows and columns.")
    ]

    class Config(BaseModel):
        delimiter: str = Field(
            default=",",
            description=(
                "Column separator: one character, or a name (comma, tab, "
                "semicolon, pipe, space). Used when `delimiters` isn't set."
            ),
        )
        delimiters: list[str] | None = Field(
            default=None,
            description=(
                "Several separators the file may use, such as [comma, tab] to "
                "read both CSV and TSV files. The one the file's own lines use "
                "is picked; a file using none of them is read with the first. "
                "Overrides `delimiter`."
            ),
        )
        encoding: str = Field(
            default="utf-8", description="Text encoding to decode the file with."
        )

        @field_validator("delimiters")
        @classmethod
        def _all_separators(cls, value: list[str] | None) -> list[str] | None:
            if value is None:
                return None
            if not value:
                raise ValueError("Give at least one separator, or leave this out.")
            for token in value:
                resolve_delimiter(token)
            return value

    def invoke(
        self, inputs: dict[str, Any], config: Config, ctx: WorkflowContext
    ) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "civex.parse_table requires pandas: pip install 'civex[workflows]'"
            )

        raw: bytes = inputs["bytes"]
        try:
            # utf-8-sig drops a byte-order mark, which would otherwise end up
            # glued to the first column's name.
            text = raw.decode(
                "utf-8-sig"
                if config.encoding.lower() in ("utf-8", "utf8")
                else config.encoding
            )
            if config.delimiters:
                candidates = [resolve_delimiter(t) for t in config.delimiters]
                delimiter = detect_delimiter(text, candidates)
                log.info("Read the file as separated by %r", delimiter)
            else:
                delimiter = resolve_delimiter(config.delimiter, single_char=False)
            df = pd.read_csv(io.StringIO(text), sep=delimiter)
        except UnicodeDecodeError as e:
            raise ValidationError(
                f"Could not decode the file as {config.encoding}: {e}"
            ) from e
        except pd.errors.EmptyDataError as e:
            raise ValidationError("The file has no data to parse") from e
        except pd.errors.ParserError as e:
            raise ValidationError(f"Could not parse the file as a table: {e}") from e
        log.info(
            "Parsed table: %d rows × %d columns %s",
            len(df),
            len(df.columns),
            list(df.columns),
        )
        return {"table": df}
