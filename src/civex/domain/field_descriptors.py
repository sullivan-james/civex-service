"""What each field type is, and what rules a field of that type can carry.

This is the one place that says which restriction keys exist for a type and
how they should be presented. `schema_service.VALID_RESTRICTION_KEYS` is
derived from it, and it is served to the web UI (`GET /schemas/field-types`)
so the field editor and the record form render from data instead of
branching on type names in four places.

Descriptors only describe. Whether a *value* is acceptable is still decided
by `RecordService._check_restrictions()` (stored values) and
`SchemaService` (the restriction values themselves).

Rules (validation) are deliberately a separate thing from views (how a value
is displayed, e.g. a spectrogram for audio). Views will get their own
descriptors later; nothing here assumes they live in `restrictions`.

`control` names the editor to show for a restriction:

    number, integer      plain numeric input
    bytes                a size, entered as KB / MB / GB, stored as bytes
    choices              an editable list of allowed values
    accept               file-type presets plus extra extensions
    filename_template    a template with insertable field names
    schema               pick another schema
    timezone             pick an IANA zone
    date_bound           year, month or day text (partial dates allowed)
    datetime_bound       a date and time in the field's zone
    unit                 a unit symbol, grouped by what it measures
    precision            year / month / day
    geometry_types       tick the shapes accepted
    bbox                 west, south, east, north in degrees
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RestrictionDescriptor:
    key: str
    label: str
    control: str
    help: str = ""


@dataclass(frozen=True)
class FieldTypeDescriptor:
    type: str
    label: str
    description: str
    #: How the value is held, in a sentence a researcher can follow.
    stored_as: str
    #: One line shown beside the input on the record page.
    entry_hint: str
    example: str
    restrictions: tuple[RestrictionDescriptor, ...] = ()
    #: Whether "default value" makes sense when creating the field.
    supports_default: bool = True


@dataclass(frozen=True)
class FieldKind:
    """An entry in the 'what kind of data is this?' picker. Several kinds can
    share one storage type (a quantity is a float with a unit)."""

    key: str
    label: str
    type: str
    description: str
    #: Restriction the editor should lead with for this kind, if any.
    focus: str | None = None


_R = RestrictionDescriptor

_MIN_MAX_NUM = (
    _R("min", "Smallest allowed", "number"),
    _R("max", "Largest allowed", "number"),
)

_FILE_RULES = (
    _R(
        "accept",
        "File types accepted",
        "accept",
        "Leave empty to accept any file.",
    ),
    _R("max_size", "Largest file", "bytes"),
    _R(
        "filename_template",
        "Download file name",
        "filename_template",
        "Name downloads from this record's other fields, e.g. {deployment_id}_clip.{ext}. "
        "Falls back to the original name when a field it uses is empty.",
    ),
)

_REFERENCE_RULES = (
    _R(
        "schema",
        "Points at",
        "schema",
        "Records in this field can only be of this type.",
    ),
)

FIELD_TYPES: dict[str, FieldTypeDescriptor] = {
    d.type: d
    for d in (
        FieldTypeDescriptor(
            "string",
            "Text",
            "Free text, or one value from a fixed list.",
            "Text",
            "Type text.",
            "Grey seal",
            (
                _R(
                    "choices",
                    "Allowed values",
                    "choices",
                    "Leave empty to allow any text.",
                ),
                _R("max_length", "Longest allowed", "integer"),
            ),
        ),
        FieldTypeDescriptor(
            "integer",
            "Whole number",
            "Counts and other whole numbers.",
            "Integer",
            "Enter a whole number.",
            "42",
            _MIN_MAX_NUM,
        ),
        FieldTypeDescriptor(
            "float",
            "Decimal number",
            "Measurements. Give it a unit and every value is stored in that unit.",
            "Decimal number, in the field's unit when it has one",
            "Enter a number. With a unit set you can also type a value with "
            "another unit, such as 1024 ft, and it is converted.",
            "312.4",
            (
                *_MIN_MAX_NUM,
                _R(
                    "unit",
                    "Unit",
                    "unit",
                    "Every value is stored in this unit. Nothing already stored is "
                    "ever converted if you change it.",
                ),
            ),
        ),
        FieldTypeDescriptor(
            "boolean",
            "Yes / no",
            "True or false.",
            "True or false",
            "Tick for yes.",
            "true",
        ),
        FieldTypeDescriptor(
            "date",
            "Date",
            "A day, or a month or year when you only know that much.",
            "ISO text at the precision it was written: 2019, 2019-06 or 2019-06-14",
            "Enter a date as YYYY-MM-DD.",
            "2024-03-15",
            (
                _R(
                    "precision",
                    "Least precise value allowed",
                    "precision",
                    "Year accepts a year, a month or a day. Day accepts full dates only.",
                ),
                _R("min", "Earliest", "date_bound"),
                _R("max", "Latest", "date_bound"),
            ),
        ),
        FieldTypeDescriptor(
            "datetime",
            "Date and time",
            "A moment in time. Stored as UTC; read and shown in a time zone.",
            "UTC instant",
            "Enter a date and time.",
            "2024-03-15T09:30",
            (
                _R(
                    "timezone",
                    "Time zone",
                    "timezone",
                    "Values without a UTC offset are read in this zone. Leave unset "
                    "to use the collection's.",
                ),
                _R("min", "Not before", "datetime_bound"),
                _R("max", "Not after", "datetime_bound"),
            ),
        ),
        FieldTypeDescriptor(
            "geo",
            "Location",
            "A point, line or area on the Earth, in latitude and longitude.",
            "GeoJSON geometry (WGS84, longitude first)",
            "Enter latitude, longitude in degrees, for example 56.12, -3.41. "
            "South and west are negative.",
            "56.12, -3.41",
            (
                _R(
                    "geometry_types",
                    "Shapes allowed",
                    "geometry_types",
                    "Leave all unticked to allow any shape.",
                ),
                _R(
                    "bbox",
                    "Restrict to an area",
                    "bbox",
                    "Degrees. West greater than east crosses the 180th meridian.",
                ),
            ),
            supports_default=False,
        ),
        FieldTypeDescriptor(
            "file",
            "File",
            "One file: an image, recording, track, table or anything else.",
            "A reference to the file's contents",
            "Attach a file.",
            "recording.wav",
            _FILE_RULES,
            supports_default=False,
        ),
        FieldTypeDescriptor(
            "file_list",
            "Files",
            "Several files in one field.",
            "A list of file references",
            "Attach one or more files.",
            "photo_1.jpg, photo_2.jpg",
            _FILE_RULES,
            supports_default=False,
        ),
        FieldTypeDescriptor(
            "reference",
            "Link to a record",
            "Points at one record of another type.",
            "The linked record's ID",
            "Search for the record to link.",
            "Deployment GS-2026-014",
            _REFERENCE_RULES,
            supports_default=False,
        ),
        FieldTypeDescriptor(
            "reference_list",
            "Links to records",
            "Points at several records of another type.",
            "A list of record IDs",
            "Search for the records to link.",
            "Two deployments",
            _REFERENCE_RULES,
            supports_default=False,
        ),
        FieldTypeDescriptor(
            "enum",
            "Choice (legacy)",
            "One value from a fixed list. New fields should use Text with allowed values.",
            "Text",
            "Pick a value.",
            "left",
            (_R("choices", "Allowed values", "choices"),),
        ),
        FieldTypeDescriptor(
            "url",
            "Web address",
            "A link starting with http:// or https://.",
            "Text",
            "Enter a web address.",
            "https://example.org/data",
        ),
        FieldTypeDescriptor(
            "tags",
            "Tags",
            "A list of short labels.",
            "A list of text values",
            "Enter tags separated by commas.",
            "seal, tagged",
            supports_default=False,
        ),
    )
}

#: The kind picker. Order is the order shown.
FIELD_KINDS: tuple[FieldKind, ...] = (
    FieldKind("text", "Text", "string", "Free text."),
    FieldKind(
        "choice",
        "Choice",
        "string",
        "One value from a list you define.",
        focus="choices",
    ),
    FieldKind("integer", "Whole number", "integer", "Counts."),
    FieldKind("number", "Number", "float", "A plain decimal number."),
    FieldKind(
        "quantity",
        "Quantity",
        "float",
        "A measurement with a unit, such as depth in metres.",
        focus="unit",
    ),
    FieldKind("yes_no", "Yes / no", "boolean", "True or false."),
    FieldKind(
        "date",
        "Date",
        "date",
        "A day, or just a month or year.",
        focus="precision",
    ),
    FieldKind("datetime", "Date and time", "datetime", "A moment, with a time zone."),
    FieldKind(
        "location",
        "Location",
        "geo",
        "A point, line or area. Latitude and longitude.",
        focus="geometry_types",
    ),
    FieldKind(
        "file",
        "File",
        "file",
        "An image, recording, track or any other file.",
        focus="accept",
    ),
    FieldKind(
        "files",
        "Files",
        "file_list",
        "Several files.",
        focus="accept",
    ),
    FieldKind(
        "link",
        "Link to a record",
        "reference",
        "Points at a record of another type.",
        focus="schema",
    ),
    FieldKind(
        "links",
        "Links to records",
        "reference_list",
        "Points at several records.",
        focus="schema",
    ),
    FieldKind("tags", "Tags", "tags", "A list of short labels."),
    FieldKind("url", "Web address", "url", "A link."),
)


def restriction_keys() -> dict[str, frozenset[str]]:
    """Valid restriction keys per type: what the service accepts on save."""
    return {t: frozenset(r.key for r in d.restrictions) for t, d in FIELD_TYPES.items()}


__all__ = [
    "FIELD_KINDS",
    "FIELD_TYPES",
    "FieldKind",
    "FieldTypeDescriptor",
    "RestrictionDescriptor",
    "restriction_keys",
]
