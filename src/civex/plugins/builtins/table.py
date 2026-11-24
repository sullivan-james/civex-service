from __future__ import annotations

import io
import logging
from typing import Any

from civex_plugin_sdk.plugin_base import IOSpec
from pydantic import BaseModel, ConfigDict, Field, field_validator

from civex.domain.dtos import FileRef
from civex.domain.exceptions import ValidationError
from civex_plugin_sdk import Ctx
from civex_plugin_sdk import Plugin as PluginBase
from civex.plugins.hints import advanced, choices, hint, says

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


class Plugin(PluginBase):
    id = "civex.table@1"
    name = "Table"
    description = (
        "Read a table from a spreadsheet or text file: CSV, TSV or Excel. Use "
        "the files from a Files step, or the file in a field of this record. "
        "Its rows can then be saved as records."
    )
    category = "bring-in"
    capabilities: list[str] = ["read"]
    inputs = [
        IOSpec(
            name="files",
            type="files",
            required=False,
            description="The file (or files, whose rows are put one after "
            "another) to read. Leave out to read the file in the Field setting.",
        )
    ]
    outputs = [IOSpec(name="table", type="table", description="The table it read.")]

    class Config(BaseModel):
        model_config = ConfigDict(
            json_schema_extra=says(
                "Reads a table from {files}, or from the file in {field}."
            )
        )
        field: str | None = Field(
            title="Read the file in field",
            json_schema_extra=hint("field", dtypes=["file"]),
            default=None,
            description="A file field of the record the workflow runs on. Not "
            "needed when files are given by a Files step.",
        )
        delimiter: str = Field(
            title="Columns separated by",
            json_schema_extra=choices(
                ("auto", "Work it out from the file"),
                (",", "Commas"),
                ("tab", "Tabs"),
                (";", "Semicolons"),
                ("|", "Pipes |"),
                ("space", "Spaces"),
            ),
            default="auto",
            description=(
                "Column separator of a text file: auto (commas, tabs or "
                "semicolons, whichever the file uses), one character, or a name "
                "(comma, tab, semicolon, pipe, space). Used when `delimiters` "
                "isn't set. Excel files need none."
            ),
        )
        delimiters: list[str] | None = Field(
            title="Or any of these separators",
            json_schema_extra=advanced(),
            default=None,
            description=(
                "Several separators the file may use, such as [comma, tab] to "
                "read both CSV and TSV files. The one the file's own lines use "
                "is picked; a file using none of them is read with the first. "
                "Overrides `delimiter`."
            ),
        )
        encoding: str = Field(
            title="Text encoding",
            json_schema_extra=advanced(),
            default="utf-8",
            description="Text encoding to decode a text file with.",
        )
        sheet: str | None = Field(
            title="Sheet",
            json_schema_extra=advanced(),
            default=None,
            description="Which sheet of an Excel file to read, by name. The "
            "first sheet when empty.",
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
        self, inputs: dict[str, Any], config: Config, ctx: Ctx
    ) -> dict[str, Any]:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "civex.table requires pandas: pip install 'civex[workflows]'"
            )

        refs = _files_to_read(inputs, config, ctx)
        frames = []
        for ref in refs:
            frames.append(_read_one(pd, ctx.get_file(ref.sha256), ref.filename, config))
        df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
        log.info(
            "Read table: %d rows x %d columns %s",
            len(df),
            len(df.columns),
            list(df.columns),
        )
        return {"table": df}


def _files_to_read(inputs: dict[str, Any], config: Any, ctx: Ctx) -> list[FileRef]:
    given = inputs.get("files")
    if given is None:
        if not config.field:
            raise ValidationError(
                "Say where the table is: connect a Files step, or choose the "
                "field holding the file."
            )
        raw = ctx.get_context_record()["data"].get(config.field)
        if raw is None:
            raise ValueError(f"Field '{config.field}' has no file on this record")
        given = raw
    if isinstance(given, dict):
        given = [given]
    refs = [
        FileRef.from_dict(f) for f in given if isinstance(f, dict) and "sha256" in f
    ]
    if not refs:
        raise ValidationError("There is no file to read a table from.")
    return refs


_EXCEL = (".xlsx", ".xlsm", ".xls")


def _read_one(pd: Any, raw: bytes, filename: str, config: Any) -> Any:
    try:
        if filename.lower().endswith(_EXCEL):
            try:
                return pd.read_excel(
                    io.BytesIO(raw), sheet_name=config.sheet or 0, engine=None
                )
            except ImportError as e:
                raise ValidationError(
                    f"'{filename}' is an Excel file this computer can't read yet "
                    f"({e}). Save it as .xlsx or CSV."
                ) from e
            except ValueError as e:
                raise ValidationError(f"Could not read '{filename}': {e}") from e
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
            log.info("Read '%s' as separated by %r", filename, delimiter)
        elif config.delimiter.strip().lower() == "auto":
            delimiter = detect_delimiter(text, [",", "\t", ";"])
            log.info("Read '%s' as separated by %r", filename, delimiter)
        else:
            delimiter = resolve_delimiter(config.delimiter, single_char=False)
        return pd.read_csv(io.StringIO(text), sep=delimiter)
    except UnicodeDecodeError as e:
        raise ValidationError(
            f"Could not decode '{filename}' as {config.encoding}: {e}"
        ) from e
    except pd.errors.EmptyDataError as e:
        raise ValidationError(f"'{filename}' has no data to read") from e
    except pd.errors.ParserError as e:
        raise ValidationError(f"Could not read '{filename}' as a table: {e}") from e
