"""Slug names vs. human labels.

Schemas and fields carry two identifiers that do different jobs:

``name``
    The stable machine key. It is what workflow YAML references
    (``civex.get_field``'s ``field:``, a trigger's ``schema:``, a
    ``reference`` restriction's target), what CSV headers use, and what
    name templates (``display_template``) refer to. Constrained to a slug
    so it stays writable by hand, diffable in git, and portable between
    projects.

``label``
    Free text shown to humans. Purely presentational, always safe to
    change, and ``None`` when nobody has set one -- callers rendering a
    label should go through :func:`display_label` for the fallback.

Slug validation is deliberately write-time only: existing rows with
non-slug names keep working, and ``civex schema lint`` reports them.
"""

from __future__ import annotations

import re
import unicodedata

from civex.domain.exceptions import ValidationError

#: A name is a lowercase identifier: letters, digits and underscores, never
#: leading with a digit. Mirrored in the frontend by ``isSlug()`` in
#: ``frontend/src/utils/naming.ts`` -- keep the two in sync.
SLUG_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

MAX_NAME_LENGTH = 255


def is_slug(name: str) -> bool:
    """Whether `name` is already a valid machine key."""
    return (
        bool(name) and len(name) <= MAX_NAME_LENGTH and SLUG_RE.match(name) is not None
    )


def slugify(text: str) -> str:
    """Best-effort conversion of a human label into a valid slug.

    ``"Recording Date"`` → ``"recording_date"``, ``"Age (years)"`` →
    ``"age_years"``, ``"Température"`` → ``"temperature"``. A result that
    would start with a digit is prefixed with an underscore rather than
    silently dropping the digit.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")
    if not slug:
        raise ValidationError(f"Cannot derive a name from {text!r}")
    if slug[0].isdigit():
        slug = f"_{slug}"
    return slug[:MAX_NAME_LENGTH]


def validate_name(name: str, kind: str = "name") -> str:
    """Return `name` unchanged, or raise if it isn't a usable machine key.

    Called on create and on rename only -- never on read -- so schemas and
    fields created before this rule existed keep resolving.
    """
    if not name or not name.strip():
        raise ValidationError(f"A {kind} cannot be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(
            f"{kind.capitalize()} '{name[:32]}...' is too long "
            f"({len(name)} > {MAX_NAME_LENGTH} characters)"
        )
    if not SLUG_RE.match(name):
        try:
            suggestion = slugify(name)
        except ValidationError:
            suggestion = None
        hint = f" Did you mean '{suggestion}'?" if suggestion else ""
        raise ValidationError(
            f"Invalid {kind} '{name}': use lowercase letters, digits and "
            f"underscores only, not starting with a digit. Set a display "
            f"label instead if you want spaces or capitals.{hint}"
        )
    return name


#: Path separators and control characters: a free-text name travels in URL
#: paths and file names, so these can't be part of one.
_UNUSABLE_IN_FREE_NAME = re.compile(r"[/\\\x00-\x1f\x7f]")


def validate_free_name(name: str, kind: str = "name") -> str:
    """For things people name in their own words -- a saved view -- rather
    than machine keys: any text goes (spaces, capitals, punctuation,
    accents), so long as it is non-empty, not absurdly long, and can sit in
    a URL path segment. Returns the trimmed name.

    Schemas and fields keep the slug rule (:func:`validate_name`) because
    workflows and CSV headers reference them as text; nothing references a
    view by name except its own URL and `civex view export`.
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError(f"A {kind} cannot be empty")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(
            f"{kind.capitalize()} '{cleaned[:32]}...' is too long "
            f"({len(cleaned)} > {MAX_NAME_LENGTH} characters)"
        )
    if _UNUSABLE_IN_FREE_NAME.search(cleaned) or set(cleaned) == {"."}:
        raise ValidationError(
            f"Invalid {kind} '{cleaned}': it can't contain '/' or '\\', "
            "control characters, or be only dots"
        )
    return cleaned


_UNSAFE_IN_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_filename(stem: str) -> str:
    """`stem` made safe to use as a download's file name."""
    return _UNSAFE_IN_FILENAME.sub("_", stem).strip(" .") or "export"


def display_label(name: str, label: str | None) -> str:
    """What a human should see: the explicit label, else a readable name."""
    if label:
        return label
    return name.replace("_", " ").strip().title() or name
