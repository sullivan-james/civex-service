"""What a spreadsheet's cells mean as values: the types a column looks like,
the key a heading becomes, and a cell turned into a field's value.

Pure and framework-free. Cells arrive as the text they show (the Table step's
"keep every value as written"), so `007` is never `7` and a date is never a
number; `infer_dtype` says what a column looks like and `coerce_cell` makes the
value a field of that type holds, or says plainly why it can't.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from civex.domain.naming import slugify

#: The types a column can be filled into from a spreadsheet, in the order the
#: wizard offers them. Everything else a field can be (files, references, ...)
#: is set up in the app, not brought in as a cell.
IMPORT_DTYPES = (
    "string",
    "longtext",
    "integer",
    "float",
    "boolean",
    "date",
    "datetime",
    "url",
)

#: Longest a value is for a one-line text field.
SHORT_TEXT = 200
#: A whole number is only taken for an integer when it is safe in JSON/JS.
_MAX_INT = 2**53

_INT = re.compile(r"^[+-]?(0|[1-9]\d*)$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)$")
_LEADING_ZERO = re.compile(r"^[+-]?0\d")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]00:00(:00(\.0+)?)?$")
_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_TRUE = frozenset({"true", "yes"})
_FALSE = frozenset({"false", "no"})


def is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def derive_key(heading: str, taken: set[str], position: int) -> str:
    """The key (`^[a-z_][a-z0-9_]*$`) a heading becomes, different from every
    key in `taken` (which it joins). A blank or symbol-only heading becomes
    `column_<position>`; the heading itself stays the field's name."""
    base = slugify(heading) if str(heading).strip() else ""
    base = re.sub(r"[^a-z0-9_]", "_", base.lower()).strip("_")
    if not base:
        base = f"column_{position}"
    if base[0].isdigit():
        base = f"_{base}"
    key, n = base, 2
    while key in taken:
        key = f"{base}_{n}"
        n += 1
    taken.add(key)
    return key


def _is_date(text: str) -> bool:
    if not _DATE.match(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _is_datetime(text: str) -> bool:
    if not _DATETIME.match(text):
        return False
    try:
        _parse_datetime(text)
    except ValueError:
        return False
    return True


def _parse_datetime(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))


def _is_int(text: str) -> bool:
    return bool(_INT.match(text)) and abs(int(text)) < _MAX_INT


def infer_dtype(values: list[Any]) -> str:
    """What a column of cells (text) looks like: the first of integer, float,
    boolean, date, datetime that every non-blank value fits, else a one-line
    or, when some value is long or spans lines, long text. A column with no
    values is text. Never a guess that would lose something: `007` and an
    ID like `1e5` stay text."""
    texts = [str(v).strip() for v in values if not is_blank(v)]
    if not texts:
        return "string"
    if all(_is_int(t) for t in texts):
        return "integer"
    if all(_FLOAT.match(t) and not _LEADING_ZERO.match(t) for t in texts):
        return "float"
    if all(t.lower() in _TRUE | _FALSE for t in texts):
        return "boolean"
    if all(_is_date(t) or _MIDNIGHT.match(t) and _is_date(t[:10]) for t in texts):
        return "date"
    if all(_is_datetime(t) for t in texts):
        return "datetime"
    if any("\n" in t or len(t) > SHORT_TEXT for t in texts):
        return "longtext"
    return "string"


def coerce_cell(value: Any, dtype: str) -> Any:
    """The value a field of `dtype` holds for a cell. Raises ValueError with a
    plain reason ("'abc' is not a whole number") when it can't be one. A cell
    that is already a number, boolean or other value (a table read without
    "as written") is accepted where it fits; types this doesn't know are
    passed on unchanged, for the record's own checks."""
    if dtype not in IMPORT_DTYPES:
        return value
    if isinstance(value, bool):
        if dtype == "boolean":
            return value
        value = str(value).lower()
    text = str(value).strip()
    if dtype in ("string", "longtext", "url"):
        return value if isinstance(value, str) else text
    if dtype == "integer":
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"'{text}' is not a whole number") from None
        if not number.is_integer() or abs(number) >= _MAX_INT:
            raise ValueError(f"'{text}' is not a whole number")
        return int(number)
    if dtype == "float":
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"'{text}' is not a number") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"'{text}' is not a number")
        return number
    if dtype == "boolean":
        low = text.lower()
        if low in _TRUE or low in ("1", "1.0"):
            return True
        if low in _FALSE or low in ("0", "0.0"):
            return False
        raise ValueError(f"'{text}' is not yes or no")
    if dtype == "date":
        m = _MIDNIGHT.match(text)
        day = m.group(1) if m else text
        if not _is_date(day):
            raise ValueError(f"'{text}' is not a date (use year-month-day)")
        return day
    # datetime
    if _DATE.match(text) and _is_date(text):
        return f"{text}T00:00:00"
    if not _is_datetime(text):
        raise ValueError(f"'{text}' is not a date and time (year-month-day hh:mm)")
    return text.replace(" ", "T", 1)


@dataclass(frozen=True)
class ImportColumn:
    """A column of the spreadsheet as the wizard first offers it."""

    heading: str  # as the reader names it: what a mapping is keyed by
    label: str  # as shown: the heading, or "Column 3" when there is none
    key: str  # the field key it would become
    dtype: str  # what the first rows look like
    blanks: int  # blank cells among the rows looked at


@dataclass(frozen=True)
class ImportSheet:
    filename: str
    sheets: list[str]  # an Excel file's sheets; empty for text
    sheet: str | None  # the one read
    columns: list[ImportColumn]
    rows: list[list[str]]  # the first rows, as text, in column order
    total: int  # rows under the headings, in all


@dataclass(frozen=True)
class ColumnChoice:
    """What becomes of one column: put in a field that exists, in a field made
    for it (`create`, of `dtype`, named by the heading), or left out
    (`field` empty and not `create`)."""

    heading: str
    field: str | None = None
    create: bool = False
    dtype: str = "string"
    label: str | None = None


@dataclass(frozen=True)
class ImportSpec:
    sha256: str
    filename: str
    collection: str
    kind: str  # the kind of record: its key
    columns: list[ColumnChoice]
    kind_label: str | None = None  # makes the kind when it isn't there yet
    new_collection: bool = False  # makes the collection (named `collection`)
    sheet: str | None = None
    match_on: list[str] = field(default_factory=list)
    if_exists: str = "update"


@dataclass(frozen=True)
class ImportBatch:
    start: int  # rows before this part
    read: int  # rows in it
    created: int
    updated: int
    unchanged: int
    skipped: int
    problems: list[str]  # why rows were skipped, "Row n: ..." (the first ones)
    done: bool  # nothing is left after this part
