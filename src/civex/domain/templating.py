"""String templates with variables — the one builder behind record names and
file download names.

A template is literal text with ``{name}`` or ``{name:spec}`` variables;
``{{`` and ``}}`` write a literal brace. A spec is one or more operations
joined by ``|``::

    {site:upper}                 SITE-A
    {taken_on:YYYY-MM-DD}        2019-06-14  (partial dates keep their precision)
    {sample_no:04}               0042        ({x:.2f} rounds a number)
    {title:slug|trunc(20)}       chained, left to right

Variables are field names or one of the reserved built-ins a caller supplies
(``schema``, ``id``). ``{site.name}`` reaches one field of the record a
reference field ``site`` points at (one hop, never deeper); the caller resolves
it and hands ``render`` a value under the key ``"site.name"``. A file name
template names only the file's stem: the extension is always the file's own,
added after rendering (``file_stem_template``), never written by a person. Rendering only reads values it is handed, so
nothing here touches a database; ``rename_field`` / ``remove_field`` keep a
stored template pointing at fields that exist.

``domain/naming.py`` is the only other civex module imported, for ``slugify``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from civex.domain.exceptions import ValidationError
from civex.domain.naming import slugify

# Field types whose values can't be written into a name. Mirrored by
# NON_NAMEABLE in frontend/src/utils/templates.ts.
UNNAMEABLE_DTYPES = frozenset(
    {"reference", "reference_list", "file", "file_list", "tags", "geo", "longtext"}
)

BUILTINS_RECORD = ("schema", "id")
# `{ext}` is no longer offered: the extension is added for you. Templates saved
# before keep rendering (a trailing `.{ext}` is dropped by file_stem_template).
BUILTINS_FILE = ("schema", "id")
_TRAILING_EXT_RE = re.compile(r"\.?\{ext\}\s*\Z")

OnMissing = Literal["skip", "fallback", "empty"]

_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?\Z")
_DATE_TOKEN_RE = re.compile(r"YYYY|MM|DD|HH|mm|SS")
_NUMBER_SPEC_RE = re.compile(r"(0?\d+)?(\.\d+f)?\Z")
_TRUNC_RE = re.compile(r"trunc\((\d+)\)\Z")
_TEXT_OPS = {
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
    "slug": lambda s: _safe_slug(s),
}
_ISO_RE = re.compile(
    r"(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2})"
    r"(?:[T ](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?)?)?"
)
_DATE_PARTS = {
    "YYYY": "year",
    "MM": "month",
    "DD": "day",
    "HH": "hour",
    "mm": "minute",
    "SS": "second",
}


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Variable:
    name: str
    spec: str | None = None

    @property
    def base(self) -> str:
        """The field the variable starts from (`site` in `site.name`)."""
        return self.name.split(".", 1)[0]

    @property
    def sub(self) -> str | None:
        """The field reached through a reference, if any."""
        return self.name.split(".", 1)[1] if "." in self.name else None


Token = Text | Variable


def _safe_slug(text: str) -> str:
    try:
        return slugify(text)
    except ValidationError:
        return ""


def _check_op(op: str) -> None:
    if op in _TEXT_OPS or _TRUNC_RE.match(op):
        return
    if _DATE_TOKEN_RE.search(op):
        return
    if op and _NUMBER_SPEC_RE.match(op):
        return
    raise ValidationError(
        f"Unknown format {op!r}. Use upper, lower, title, slug, trunc(N), a number"
        " format such as 03 or .2f, or a date pattern such as YYYY-MM-DD"
    )


def parse(template: str) -> list[Token]:
    """The tokens of `template`. Raises ValidationError on a stray or
    unclosed brace, a bad variable name or an unknown format."""
    return list(_parse(template))


@lru_cache(maxsize=4096)
def _parse(template: str) -> tuple[Token, ...]:
    """`parse`, remembered: a page of records renders the same few templates
    (names, file names) once per record, so each is read once. Tokens are
    frozen, so sharing them is safe; a template that doesn't parse raises
    every time (lru_cache keeps no exceptions)."""
    tokens: list[Token] = []
    buf: list[str] = []
    i, n = 0, len(template)

    def flush() -> None:
        if buf:
            tokens.append(Text("".join(buf)))
            buf.clear()

    while i < n:
        ch = template[i]
        if ch == "{":
            if template[i + 1 : i + 2] == "{":
                buf.append("{")
                i += 2
                continue
            end = template.find("}", i + 1)
            if end == -1:
                raise ValidationError("Template has a '{' with no closing '}'")
            body = template[i + 1 : end]
            name, _, spec = body.partition(":")
            name = name.strip()
            if not _NAME_RE.match(name):
                raise ValidationError(f"{body!r} is not a valid variable name")
            if ":" in body:
                for op in spec.split("|"):
                    _check_op(op.strip())
            flush()
            tokens.append(Variable(name, spec.strip() or None))
            i = end + 1
        elif ch == "}":
            if template[i + 1 : i + 2] == "}":
                buf.append("}")
                i += 2
                continue
            raise ValidationError("Template has a '}' with no opening '{'")
        else:
            buf.append(ch)
            i += 1
    flush()
    return tuple(tokens)


def referenced_names(template: str) -> list[str]:
    """Variable names in order of first use."""
    seen: list[str] = []
    for tok in parse(template):
        if isinstance(tok, Variable) and tok.name not in seen:
            seen.append(tok.name)
    return seen


def validate(
    template: str,
    known_fields: set[str],
    builtins: tuple[str, ...] = (),
    reference_targets: Mapping[str, set[str]] | None = None,
) -> None:
    """Raise ValidationError if `template` is malformed or names a variable
    that is neither a known field nor an allowed built-in.

    `reference_targets` maps each usable reference field to the field names of
    the schema it points at; without it, ``{ref.field}`` is not allowed."""
    unknown: list[str] = []
    for name in referenced_names(template):
        base, _, sub = name.partition(".")
        if not sub:
            if name not in known_fields and name not in builtins:
                unknown.append(name)
        elif reference_targets is None:
            raise ValidationError(
                f"{name!r}: another record's values can't be used here"
            )
        elif base not in reference_targets:
            raise ValidationError(
                f"{name!r}: {base!r} must be a reference field that names"
                " the schema it points at"
            )
        elif sub not in reference_targets[base]:
            raise ValidationError(
                f"{name!r}: the schema {base!r} points at has no field {sub!r}"
            )
    if unknown:
        raise ValidationError(f"Template uses unknown variable(s) {sorted(unknown)}")


def file_stem_template(template: str) -> str:
    """A file name template without the extension a template saved before the
    extension was added automatically ended with (``{a}.{ext}`` -> ``{a}``)."""
    return _TRAILING_EXT_RE.sub("", template).rstrip()


def check_file_template(template: str) -> str:
    """The file name template to store: a trailing ``.{ext}`` dropped (the file
    keeps its own extension anyway). Raises ValidationError if ``{ext}`` is
    still used elsewhere, since the extension is never chosen by a template."""
    stem = file_stem_template(template)
    if "ext" in referenced_names(stem):
        raise ValidationError(
            "{ext} can't be used: the file's own extension is added at the end for you"
        )
    return stem


def with_extension(stem: str, original: str) -> str:
    """`stem` with the extension of the file name `original`, unless it
    already ends with it."""
    dot = original.rfind(".")
    ext = original[dot:] if dot > 0 else ""
    if not ext or stem.lower().endswith(ext.lower()):
        return stem
    return stem + ext


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _format_date(value: str, pattern: str) -> str | None:
    """`value` (an ISO date or datetime) in `pattern`. A pattern that asks for
    more precision than the value has stops at the last part it can fill."""
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    parts = m.groupdict()
    out: list[str] = []
    pos = 0
    for tok in _DATE_TOKEN_RE.finditer(pattern):
        got = parts[_DATE_PARTS[tok.group()]]
        if got is None:
            return "".join(out + [pattern[pos : tok.start()]]).rstrip(" -_/.:T")
        out.append(pattern[pos : tok.start()])
        out.append(got)
        pos = tok.end()
    out.append(pattern[pos:])
    return "".join(out)


def _apply_op(op: str, value: Any) -> Any:
    if op in _TEXT_OPS:
        return _TEXT_OPS[op](str(value))
    m = _TRUNC_RE.match(op)
    if m:
        return str(value)[: int(m.group(1))]
    if _DATE_TOKEN_RE.search(op):
        if isinstance(value, str):
            formatted = _format_date(value, op)
            if formatted is not None:
                return formatted
        return value
    m = _NUMBER_SPEC_RE.match(op)
    if m and not isinstance(value, bool) and isinstance(value, (int, float)):
        width, decimals = m.group(1), m.group(2)
        if decimals:
            text = f"{value:{decimals}}"
            return text.zfill(int(width)) if width else text
        return str(int(value)).zfill(int(width)) if width else str(value)
    return value


def _render_variable(tok: Variable, value: Any) -> str:
    if tok.spec:
        for op in tok.spec.split("|"):
            value = _apply_op(op.strip(), value)
    return str(value)


def render(
    template: str,
    values: Mapping[str, Any],
    builtins: Mapping[str, Any] | None = None,
    on_missing: OnMissing = "skip",
) -> str | None:
    """`template` filled from `values` (name-keyed field values) and
    `builtins` (which win over fields of the same name).

    A variable is missing when its value is None or blank. What happens:

    - ``skip``: it is dropped along with the separator text next to it, so
      ``"{a} - {b}"`` with no ``a`` gives just ``b``;
    - ``fallback``: the whole result is None, so the caller can use something
      else (a file keeps its original name rather than a partial one);
    - ``empty``: it renders as nothing.

    The result is also None when it is blank.
    """
    builtins = builtins or {}
    pieces: list[tuple[str, bool]] = []  # (text, is_literal)
    skip_next_literal = False
    any_value = False
    has_variable = False
    for tok in parse(template):
        if isinstance(tok, Text):
            if skip_next_literal:
                skip_next_literal = False
                continue
            pieces.append((tok.text, True))
            continue
        has_variable = True
        skip_next_literal = False
        value = builtins[tok.name] if tok.name in builtins else values.get(tok.name)
        if _is_blank(value):
            if on_missing == "fallback":
                return None
            if on_missing == "skip":
                if pieces and pieces[-1][1]:
                    pieces.pop()
                else:
                    skip_next_literal = True
            continue
        any_value = True
        pieces.append((_render_variable(tok, value), False))
    if has_variable and not any_value and on_missing != "empty":
        return None
    result = "".join(text for text, _ in pieces).strip()
    return result or None


def _format_token(tok: Token) -> str:
    if isinstance(tok, Text):
        return tok.text.replace("{", "{{").replace("}", "}}")
    return "{" + tok.name + (f":{tok.spec}" if tok.spec else "") + "}"


def rename_field(template: str, old: str, new: str, via: str | None = None) -> str:
    """`template` with the field `old` renamed to `new`.

    With `via=None`, `old` is a field of the schema itself: ``{old}`` and
    ``{old.x}`` follow it. With `via="site"`, `old` is a field of the schema
    that reference `site` points at, so only ``{site.old}`` changes."""

    def renamed(t: Variable) -> Variable:
        if via is None:
            if t.sub is None and t.name == old:
                return Variable(new, t.spec)
            if t.sub is not None and t.base == old:
                return Variable(f"{new}.{t.sub}", t.spec)
        elif t.base == via and t.sub == old:
            return Variable(f"{via}.{new}", t.spec)
        return t

    return "".join(
        _format_token(renamed(t) if isinstance(t, Variable) else t)
        for t in parse(template)
    )


def remove_field(template: str, name: str, via: str | None = None) -> str:
    """`template` without the variables that used the field `name` (see
    `rename_field` for `via`) and the separator beside each."""

    def gone(t: Variable) -> bool:
        if via is None:
            return t.name == name or t.base == name
        return t.base == via and t.sub == name

    pieces: list[Token] = []
    skip_next_literal = False
    for tok in parse(template):
        if isinstance(tok, Variable) and gone(tok):
            if pieces and isinstance(pieces[-1], Text):
                pieces.pop()
            else:
                skip_next_literal = True
            continue
        if isinstance(tok, Text) and skip_next_literal:
            skip_next_literal = False
            continue
        skip_next_literal = False
        pieces.append(tok)
    return "".join(_format_token(t) for t in pieces)


def from_field_list(names: list[str]) -> str:
    """The template that joins `names` with a space — what a list of display
    fields meant before templates existed."""
    return " ".join("{" + n + "}" for n in names)
