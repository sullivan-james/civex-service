"""A release: a frozen, citable copy of a project's data.

A person names a version (`v1`, `2026-thesis`), says what it is (title,
description, authors with ORCID and affiliation, licence, keywords, an
optional DOI) and what it covers (the whole project, some collections, or the
records a query lists). civex writes a small bundle of exactly those records
(`domain/bundle.py`, the one exporter, without files), keeps it in the object
store like any file, and records a manifest: the content hash, counts, the
history position it was taken at and the civex that made it. The files the
records cite are not copied: the release owns them where they already are.

Beside the records the bundle holds `structure.json` (the schemas, with
their fields, and the collections, each with its id, as they were) and
`records.hashes`: one line per record, sorted by id, `<id> <record hash>
<collection id>`. A **record hash** (`record_hash`) is the sha256 of the
canonical JSON of the record's id, collection id, schema id, parent id and
its stored values keyed by **field id**: only the live, stored fields of its
kind (a formula's value is worked out, never stored), blank values left out,
and what a read adds to a file value (`location`, `resolved_filename`)
stripped. Renaming a field or changing a label changes no record hash; the
same definition hashes a live record (`ReleaseService.compare`) and a line of
the bundle (`line_hashes`), so a record whose values are as they were (an
edit undone included) hashes the same.

The **content hash** is over what the release holds, never the zip's bytes:
`sha256:` + the sha256 of, in order, a header line, `structure.json`
(canonical JSON), the sorted `(id, record hash)` pairs of `records.hashes`,
the sha256 of every file the records cite, sorted (a file's hash is its
content, so the files are covered without reading one), then the workflows
and plugins (name and sha256 of their bytes), sorted. Canonical JSON is
`sort_keys`, no spaces, UTF-8. `release.json` and `CITATION.cff` (written
after the hash) are not part of it. `hash_bundle` recomputes it from the
sidecar and checks the sidecar against the record lines.

This module is pure: the rules for a release's words, the hash, and the
citation forms. `services/release_service.py` makes and keeps releases.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from civex.domain import bundle as spec
from civex.domain.audit_diff import strip_derived
from civex.domain.field_descriptors import COMPUTED_DTYPES
from civex.domain.exceptions import ValidationError

HASH_PREFIX = "sha256:"
# Bumped only if what the hash covers changes; written into the header line, so
# an old hash can never be mistaken for one over different contents.
HASH_VERSION = 2

# Members the release adds to its bundle after hashing it.
RELEASE_JSON = "release.json"
CITATION_CFF = "CITATION.cff"
RELEASE_MEMBERS = frozenset({RELEASE_JSON, CITATION_CFF})

# A release's name: a version people type and cite (`v1`, `2026-thesis`).
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
MAX_TITLE = 300
MAX_DESCRIPTION = 10_000
MAX_AUTHORS = 100
MAX_KEYWORDS = 50
_ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

# What a release *is*: fixed once made. Everything else is citation metadata a
# person may correct (each correction is in history), plus the withdrawal and
# the yank.
CONTENT_FIELDS = frozenset(
    {
        "id",
        "name",
        "scope",
        "content_hash",
        "bundle_sha256",
        "bundle_size",
        "counts",
        "feed_seq",
        "civex_version",
        "created_at",
        "created_by",
    }
)
METADATA_FIELDS = (
    "title",
    "description",
    "authors",
    "licence",
    "doi",
    "keywords",
)


def check_name(name: Any) -> str:
    text = str(name or "").strip()
    if not _NAME.match(text):
        raise ValidationError(
            "A release's name is a version like 'v1' or '2026-thesis': letters, "
            "digits, '.', '_' and '-', starting with a letter or digit, at most "
            "64 characters"
        )
    return text


def check_metadata(values: dict[str, Any]) -> dict[str, Any]:
    """The citation metadata in `values` (only the keys given), tidied and
    checked: a title is needed, authors are names, a DOI looks like one."""
    out: dict[str, Any] = {}
    if "title" in values:
        title = str(values["title"] or "").strip()
        if not title:
            raise ValidationError("A release needs a title")
        if len(title) > MAX_TITLE:
            raise ValidationError(f"A title is at most {MAX_TITLE} characters")
        out["title"] = title
    if "description" in values:
        text = str(values["description"] or "").strip()
        if len(text) > MAX_DESCRIPTION:
            raise ValidationError(
                f"A description is at most {MAX_DESCRIPTION} characters"
            )
        out["description"] = text or None
    if "authors" in values:
        raw = values["authors"] or []
        if not isinstance(raw, list):
            raise ValidationError("Authors are a list")
        authors = [a for a in (check_author(a) for a in raw) if a]
        if len(authors) > MAX_AUTHORS:
            raise ValidationError(f"At most {MAX_AUTHORS} authors")
        out["authors"] = authors
    if "keywords" in values:
        raw = values["keywords"] or []
        if not isinstance(raw, list):
            raise ValidationError("Keywords are a list of words")
        words = list(dict.fromkeys(str(k).strip() for k in raw if str(k or "").strip()))
        if len(words) > MAX_KEYWORDS or any(len(w) > 100 for w in words):
            raise ValidationError(
                f"At most {MAX_KEYWORDS} keywords, each at most 100 characters"
            )
        out["keywords"] = words
    if "licence" in values:
        out["licence"] = str(values["licence"] or "").strip() or None
    if "doi" in values:
        doi = str(values["doi"] or "").strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix) :]
        if doi and not _DOI.match(doi):
            raise ValidationError("A DOI looks like 10.1234/abcd")
        out["doi"] = doi or None
    return out


def check_author(raw: Any) -> dict[str, str] | None:
    """One author: `{name, orcid?, affiliation?}` (a plain string is a name).
    A blank name is no author; an ORCID is `0000-0002-1825-0097` (the
    orcid.org address is taken off)."""
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        raise ValidationError("An author is a name, with an ORCID and affiliation")
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    author = {"name": name}
    orcid = str(raw.get("orcid") or "").strip()
    for prefix in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if orcid.lower().startswith(prefix):
            orcid = orcid[len(prefix) :]
    if orcid:
        if not _ORCID.match(orcid.upper()):
            raise ValidationError(
                f"{name}'s ORCID looks like 0000-0002-1825-0097, not '{orcid}'"
            )
        author["orcid"] = orcid.upper()
    affiliation = str(raw.get("affiliation") or "").strip()
    if affiliation:
        author["affiliation"] = affiliation
    return author


# -- the content hash ----------------------------------------------------------


STRUCTURE_JSON = "structure.json"
RECORD_HASHES = "records.hashes"


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# -- per-record hashes ---------------------------------------------------------


def structure_of(schemas: list[Any], collections: list[Any]) -> dict[str, Any]:
    """`structure.json`: the live schemas (`SchemaDTO`, with their live
    fields) and collections (`DatasetDTO`), each with its id, sorted by id.
    What a release's record lines are read back by, and what the structural
    side of a comparison compares."""
    return {
        "schemas": sorted(
            (
                {
                    "id": str(s.id),
                    "name": s.name,
                    "label": s.label,
                    "description": s.description,
                    "parent_id": str(s.parent_id) if s.parent_id else None,
                    "display_template": s.display_template,
                    "unique_keys": [list(k) for k in s.unique_keys],
                    "fields": sorted(
                        (
                            {
                                "id": str(f.id),
                                "name": f.name,
                                "label": f.label,
                                "type": f.dtype,
                                "required": f.required,
                                "restrictions": f.restrictions or {},
                                "default_value": f.default_value,
                            }
                            for f in s.fields
                        ),
                        key=lambda f: f["id"],
                    ),
                }
                for s in schemas
                if getattr(s, "deleted_at", None) is None
            ),
            key=lambda s: s["id"],
        ),
        "collections": sorted(
            (
                {
                    "id": str(c.id),
                    "name": c.name,
                    "scope": c.scope,
                    "timezone": c.timezone,
                }
                for c in collections
                if getattr(c, "deleted_at", None) is None
            ),
            key=lambda c: c["id"],
        ),
    }


#: What a schema or field is compared by (`structure_changes`).
_SCHEMA_KEYS = (
    "name",
    "label",
    "description",
    "parent_id",
    "display_template",
    "unique_keys",
)
_FIELD_KEYS = ("name", "label", "type", "required", "restrictions", "default_value")


def structure_changes(
    then: dict[str, Any], now: dict[str, Any]
) -> list[dict[str, Any]]:
    """Schemas and fields added, removed or changed between two
    `structure_of`s, by id (a rename is a change, never a remove and an
    add): `{kind, change, name, schema, what}`, `what` naming the attributes
    that differ."""
    out: list[dict[str, Any]] = []
    a = {s["id"]: s for s in then.get("schemas") or []}
    b = {s["id"]: s for s in now.get("schemas") or []}

    def compare(kind: str, x: dict, y: dict, keys: tuple, schema: str | None):
        for i in sorted(set(x) | set(y)):
            was, cur = x.get(i), y.get(i)
            name = (cur or was or {}).get("name")
            if was is None:
                out.append(
                    dict(kind=kind, change="added", name=name, schema=schema, what=[])
                )
            elif cur is None:
                out.append(
                    dict(kind=kind, change="removed", name=name, schema=schema, what=[])
                )
            else:
                what = [k for k in keys if was.get(k) != cur.get(k)]
                if what:
                    out.append(
                        dict(
                            kind=kind,
                            change="changed",
                            name=name,
                            schema=schema,
                            what=what,
                        )
                    )

    compare("schema", a, b, _SCHEMA_KEYS, None)
    for sid in sorted(set(a) & set(b)):  # a schema added or removed is one line
        owner = b[sid].get("name")
        compare(
            "field",
            {f["id"]: f for f in a[sid].get("fields") or []},
            {f["id"]: f for f in b[sid].get("fields") or []},
            _FIELD_KEYS,
            owner,
        )
    return out


def stored_fields(structure: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Per schema id, the fields a record of it stores, `{name: field id}`:
    its own then those above it (the first of a name wins, as a record reads
    them), leaving out fields worked out when read (`computed`)."""
    schemas = {str(s["id"]): s for s in structure.get("schemas") or []}
    out: dict[str, dict[str, str]] = {}
    for sid in schemas:
        names: dict[str, str] = {}
        seen: set[str] = set()
        at: str | None = sid
        while at and at in schemas and at not in seen:
            seen.add(at)
            for f in schemas[at].get("fields") or []:
                if f.get("computed") or f.get("type") in COMPUTED_DTYPES:
                    continue
                names.setdefault(str(f["name"]), str(f["id"]))
            parent = schemas[at].get("parent_id")
            at = str(parent) if parent else None
        out[sid] = names
    return out


def record_hash(
    record_id: Any,
    collection_id: Any,
    schema_id: Any,
    parent_id: Any,
    data: dict[str, Any],
    fields: Any,
) -> str:
    """A record's comparison hash (see the module docstring). `data` is keyed
    by field id, as stored; only the ids in `fields` (the stored fields of its
    kind) count, blank values are left out and derived file keys stripped."""
    values = {
        fid: strip_derived(value)
        for fid, value in data.items()
        if fid in fields and value is not None and value != [] and value != ""
    }
    return hashlib.sha256(
        canonical(
            [
                str(record_id),
                str(collection_id) if collection_id else None,
                str(schema_id) if schema_id else None,
                str(parent_id) if parent_id else None,
                values,
            ]
        )
    ).hexdigest()


def read_structure(zf: zipfile.ZipFile) -> dict[str, Any] | None:
    try:
        value = json.loads(zf.read(STRUCTURE_JSON))
    except (KeyError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def line_hashes(
    zf: zipfile.ZipFile, structure: dict[str, Any]
) -> tuple[list[tuple[str, str, str]], set[str], list[str]]:
    """Each record line's `(id, record hash, collection id)`, sorted by id,
    the files the lines cite, and what could not be read. Names in a line
    are turned back into the ids they had (`structure.json`)."""
    fields = stored_fields(structure)
    schema_ids = {str(s["name"]): str(s["id"]) for s in structure["schemas"]}
    collection_ids = {
        str(c["name"]): str(c["id"]) for c in structure.get("collections") or []
    }
    out: list[tuple[str, str, str]] = []
    cited: set[str] = set()
    problems: list[str] = []
    if spec.RECORDS not in zf.namelist():
        return out, cited, problems
    with zf.open(spec.RECORDS) as f:
        for raw in f:
            text = raw.decode("utf-8").strip()
            if not text:
                continue
            try:
                line = json.loads(text)
                data = spec.plain_data(line.get("data") or {})
                sid = schema_ids[str(line["schema"])]
                cid = collection_ids[str(line["collection"])]
                names = fields[sid]
                unknown = set(data) - set(names)
                if unknown - _computed_names(structure, sid):
                    raise KeyError(sorted(unknown)[0])
                by_id = {names[k]: v for k, v in data.items() if k in names}
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
                problems.append(f"A line of records.jsonl can't be read ({e})")
                continue
            cited.update(r["sha256"] for r in spec.file_refs(data))
            out.append(
                (
                    str(line["id"]),
                    record_hash(
                        line["id"], cid, sid, line.get("parent"), by_id, set(by_id)
                    ),
                    cid,
                )
            )
    out.sort()
    return out, cited, problems


def _computed_names(structure: dict[str, Any], sid: str) -> set[str]:
    """Names of worked-out fields of a schema and those above it: a line may
    carry their values, which are not stored and so not hashed."""
    schemas = {str(s["id"]): s for s in structure.get("schemas") or []}
    out: set[str] = set()
    seen: set[str] = set()
    at: str | None = sid
    while at and at in schemas and at not in seen:
        seen.add(at)
        out |= {
            str(f["name"])
            for f in schemas[at].get("fields") or []
            if f.get("computed") or f.get("type") in COMPUTED_DTYPES
        }
        parent = schemas[at].get("parent_id")
        at = str(parent) if parent else None
    return out


def hashes_text(hashes: list[tuple[str, str, str]]) -> str:
    """`records.hashes`: one `<id> <hash> <collection id>` line per record."""
    return "".join(f"{i} {h} {c}\n" for i, h, c in sorted(hashes))


def read_hashes(zf: zipfile.ZipFile) -> list[tuple[str, str, str]] | None:
    """`records.hashes`, as written (None when the bundle has none)."""
    try:
        text = zf.read(RECORD_HASHES).decode("utf-8")
    except KeyError:
        return None
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


@dataclass
class HashResult:
    """A bundle's content hash, and what was wrong with its contents (a line
    that can't be read, a sidecar that doesn't match the lines)."""

    content_hash: str
    problems: list[str] = field(default_factory=list)
    records: int = 0
    # The files the records cite (by sha256, sorted).
    cited: list[str] = field(default_factory=list)


def hash_bundle(zf: zipfile.ZipFile) -> HashResult:
    """The content hash of an open bundle (see the module docstring),
    recomputed from `records.hashes`, which is checked against the record
    lines (each line hashed again). One pass over the records; no file is
    read."""
    structure = read_structure(zf)
    if structure is None:
        return HashResult("", ["The bundle has no readable structure.json"])
    lines, cited, problems = line_hashes(zf, structure)
    sidecar = read_hashes(zf)
    if sidecar is None:
        problems.append("The bundle has no records.hashes")
        sidecar = lines
    elif sorted(sidecar) != lines:
        known = {i: h for i, h, _ in lines}
        differ = sum(1 for i, h, _ in sidecar if known.get(i) != h)
        differ += len(set(known) - {i for i, _, _ in sidecar})
        problems.append(f"records.hashes does not match the records ({differ} differ)")
    names = zf.namelist()
    members = sorted(
        (n, _sha_of(zf, n))
        for n in names
        if n.startswith((spec.WORKFLOWS_DIR, spec.PLUGINS_DIR)) and not n.endswith("/")
    )
    files = sorted(cited)
    h = hashlib.sha256(f"civex-release-content/{HASH_VERSION}\n".encode())
    h.update(canonical(structure))
    h.update(b"\nrecords\n")
    for rid, digest, _ in sorted(sidecar):
        h.update(f"{rid} {digest}\n".encode())
    h.update(b"files\n")
    for sha in files:
        h.update(sha.encode() + b"\n")
    h.update(b"members\n")
    for name, sha in members:
        h.update(canonical([name, sha]) + b"\n")
    return HashResult(HASH_PREFIX + h.hexdigest(), problems, len(sidecar), files)


def _sha_of(zf: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name) as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


# -- citing --------------------------------------------------------------------


@dataclass
class CitationFacts:
    """What a citation is made from: a release's metadata and hash."""

    name: str
    title: str
    authors: list[dict[str, str]]  # {name, orcid?, affiliation?}
    year: str
    date: str  # YYYY-MM-DD
    content_hash: str
    licence: str | None = None
    doi: str | None = None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [a["name"] for a in self.authors]


def _author_list(names: list[str]) -> str:
    if not names:
        return "Anonymous"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " & " + names[-1]


def short_hash(content_hash: str) -> str:
    return content_hash.removeprefix(HASH_PREFIX)[:12]


def citation_text(c: CitationFacts) -> str:
    """One paragraph to paste into a reference list."""
    text = (
        f"{_author_list(c.names)} ({c.year}). {c.title} (Version {c.name}) [Data set]."
    )
    if c.doi:
        text += f" https://doi.org/{c.doi}"
    return text + f" Content hash {c.content_hash}."


def _bib_escape(text: str) -> str:
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("$", "\\$")
        .replace("#", "\\#")
        .replace("_", "\\_")
    )


def bibtex_key(c: CitationFacts) -> str:
    first = re.sub(r"[^A-Za-z0-9]", "", (c.names[0].split()[-1] if c.names else ""))
    version = re.sub(r"[^A-Za-z0-9]", "", c.name)
    return f"{first or 'data'}{c.year}{version}"


def bibtex(c: CitationFacts) -> str:
    fields = [
        ("title", _bib_escape(c.title)),
        ("author", " and ".join(_bib_escape(a) for a in c.names) or "Anonymous"),
        ("year", c.year),
        ("version", _bib_escape(c.name)),
        ("howpublished", "Data set"),
        ("note", f"Content hash {c.content_hash}"),
    ]
    if c.doi:
        fields.append(("doi", _bib_escape(c.doi)))
        fields.append(("url", f"https://doi.org/{c.doi}"))
    if c.licence:
        fields.append(("license", _bib_escape(c.licence)))
    if c.keywords:
        fields.append(("keywords", _bib_escape(", ".join(c.keywords))))
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields)
    return f"@misc{{{bibtex_key(c)},\n{body}\n}}\n"


def _yaml(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a JSON string is valid YAML


def _cff_person(author: dict[str, str]) -> list[str]:
    name = author["name"]
    if "," in name:
        family, _, given = name.partition(",")
    else:
        given, _, family = name.rpartition(" ")
    if not given.strip():
        lines = [f"  - name: {_yaml(name)}"]
    else:
        lines = [
            f"  - family-names: {_yaml(family.strip())}",
            f"    given-names: {_yaml(given.strip())}",
        ]
    if author.get("orcid"):
        lines.append(f"    orcid: {_yaml('https://orcid.org/' + author['orcid'])}")
    if author.get("affiliation"):
        lines.append(f"    affiliation: {_yaml(author['affiliation'])}")
    return lines


def citation_cff(c: CitationFacts) -> str:
    """CITATION.cff (Citation File Format 1.2.0), written into the bundle."""
    lines = [
        "cff-version: 1.2.0",
        'message: "If you use this data, please cite it as below."',
        "type: dataset",
        f"title: {_yaml(c.title)}",
        f"version: {_yaml(c.name)}",
        f"date-released: {_yaml(c.date)}",
        "authors:",
    ]
    for author in c.authors or [{"name": "Anonymous"}]:
        lines += _cff_person(author)
    if c.description:
        lines.append(f"abstract: {_yaml(c.description)}")
    if c.licence:
        lines.append(f"license: {_yaml(c.licence)}")
    if c.doi:
        lines.append(f"doi: {_yaml(c.doi)}")
    if c.keywords:
        lines.append("keywords:")
        lines += [f"  - {_yaml(k)}" for k in c.keywords]
    lines += [
        "identifiers:",
        "  - type: other",
        f"    value: {_yaml(c.content_hash)}",
        '    description: "Content hash of the civex release"',
    ]
    return "\n".join(lines) + "\n"


CITATION_FORMATS = ("text", "bibtex", "cff")


def citation(c: CitationFacts, form: str) -> str:
    if form == "text":
        return citation_text(c)
    if form == "bibtex":
        return bibtex(c)
    if form == "cff":
        return citation_cff(c)
    raise ValidationError(f"A citation is one of: {', '.join(CITATION_FORMATS)}")
