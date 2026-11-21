"""A release: a frozen, citable copy of a project's data.

A person names a version (`v1`, `2026-thesis`), says what it is (title,
description, authors, licence, an optional DOI) and what it covers (the whole
project, some collections, or the records a query lists). civex writes a
bundle of exactly that (`domain/bundle.py`, the one exporter), keeps it in the
object store like any file, and records a manifest: the content hash, counts,
the history position it was taken at and the civex that made it.

The **content hash** is over what the bundle holds, never the zip's bytes (a
zip carries the time it was written, so two exports of the same data differ):
`sha256:` + the sha256 of, in order, a header line, the schemas and
collections (canonical JSON, collections by name), each record line's own
sha256 in record-id order, then the stored files carried (by name, which is
their content hash, and checked against their bytes) and the workflows and
plugins (name and sha256 of their bytes), each sorted. Canonical JSON is
`sort_keys`, no spaces, UTF-8. The release's own members (`release.json`,
`CITATION.cff`, written after the hash) are not part of it. Identical data
gives the identical hash however many times it is exported.

This module is pure: the rules for a release's words, the hash, and the
citation forms. `services/release_service.py` makes and keeps releases.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterable

from civex.domain import bundle as spec
from civex.domain.exceptions import ValidationError

HASH_PREFIX = "sha256:"
# Bumped only if what the hash covers changes; written into the header line, so
# an old hash can never be mistaken for one over different contents.
HASH_VERSION = 1

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

# What a release *is*: fixed once made. Everything else is citation metadata a
# person may correct (each correction is in history), plus the withdrawal.
CONTENT_FIELDS = frozenset(
    {
        "id",
        "name",
        "scope",
        "include_files",
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
METADATA_FIELDS = ("title", "description", "authors", "licence", "doi")


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
        if isinstance(raw, str):
            raw = [a for a in raw.split(";")]
        if not isinstance(raw, list):
            raise ValidationError("Authors are a list of names")
        authors = [str(a).strip() for a in raw if str(a or "").strip()]
        if len(authors) > MAX_AUTHORS:
            raise ValidationError(f"At most {MAX_AUTHORS} authors")
        out["authors"] = authors
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


# -- the content hash ----------------------------------------------------------


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


@dataclass
class HashResult:
    """A bundle's content hash, and what was wrong with its contents (a file
    whose bytes don't match its name, a line that can't be read)."""

    content_hash: str
    problems: list[str] = field(default_factory=list)
    records: int = 0
    files: int = 0


def hash_bundle(zf: zipfile.ZipFile, check_files: bool = True) -> HashResult:
    """The content hash of an open bundle (see the module docstring). One pass
    over the records (a page in memory is one line) and, with `check_files`,
    over every carried file's bytes."""
    problems: list[str] = []
    names = zf.namelist()
    try:
        manifest = json.loads(zf.read(spec.MANIFEST))
    except (KeyError, json.JSONDecodeError):
        return HashResult("", ["The bundle has no readable bundle.json"])
    schemas = sorted(manifest.get("schemas") or [], key=lambda s: str(s.get("name")))
    collections = sorted(
        manifest.get("collections") or [], key=lambda c: str(c.get("name"))
    )
    lines: list[tuple[str, bytes]] = []
    if spec.RECORDS in names:
        with zf.open(spec.RECORDS) as f:
            for raw in f:
                text = raw.decode("utf-8").strip()
                if not text:
                    continue
                try:
                    line = json.loads(text)
                except json.JSONDecodeError:
                    problems.append("A line of records.jsonl is not JSON")
                    continue
                if isinstance(line, dict) and isinstance(line.get("data"), dict):
                    line["data"] = spec.plain_data(line["data"])
                lines.append(
                    (
                        str(line.get("id") if isinstance(line, dict) else ""),
                        hashlib.sha256(canonical(line)).digest(),
                    )
                )
    files = sorted(
        n[len(spec.FILES_DIR) :]
        for n in names
        if n.startswith(spec.FILES_DIR) and len(n) > len(spec.FILES_DIR)
    )
    if check_files:
        for sha in files:
            if _sha_of(zf, spec.FILES_DIR + sha) != sha:
                problems.append(f"The file {sha[:12]}… does not match its hash")
    members = sorted(
        (n, _sha_of(zf, n))
        for n in names
        if n.startswith((spec.WORKFLOWS_DIR, spec.PLUGINS_DIR)) and not n.endswith("/")
    )
    h = hashlib.sha256(f"civex-release-content/{HASH_VERSION}\n".encode())
    h.update(canonical({"schemas": schemas, "collections": collections}))
    h.update(b"\nrecords\n")
    for _, digest in sorted(lines):
        h.update(digest)
    h.update(b"\nfiles\n")
    for sha in files:
        h.update(sha.encode() + b"\n")
    h.update(b"members\n")
    for name, sha in members:
        h.update(canonical([name, sha]) + b"\n")
    return HashResult(HASH_PREFIX + h.hexdigest(), problems, len(lines), len(files))


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
    authors: list[str]
    year: str
    date: str  # YYYY-MM-DD
    content_hash: str
    licence: str | None = None
    doi: str | None = None
    description: str | None = None
    project: str | None = None


def _author_list(authors: Iterable[str]) -> str:
    names = list(authors)
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
        f"{_author_list(c.authors)} ({c.year}). {c.title} (Version {c.name}) "
        "[Data set]."
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
    first = re.sub(r"[^A-Za-z0-9]", "", (c.authors[0].split()[-1] if c.authors else ""))
    version = re.sub(r"[^A-Za-z0-9]", "", c.name)
    return f"{first or 'data'}{c.year}{version}"


def bibtex(c: CitationFacts) -> str:
    fields = [
        ("title", _bib_escape(c.title)),
        ("author", " and ".join(_bib_escape(a) for a in c.authors) or "Anonymous"),
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
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields)
    return f"@misc{{{bibtex_key(c)},\n{body}\n}}\n"


def _yaml(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a JSON string is valid YAML


def _cff_person(name: str) -> list[str]:
    if "," in name:
        family, _, given = name.partition(",")
    else:
        given, _, family = name.rpartition(" ")
    if not given.strip():
        return [f"  - name: {_yaml(name)}"]
    return [
        f"  - family-names: {_yaml(family.strip())}",
        f"    given-names: {_yaml(given.strip())}",
    ]


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
    for author in c.authors or ["Anonymous"]:
        lines += _cff_person(author)
    if c.description:
        lines.append(f"abstract: {_yaml(c.description)}")
    if c.licence:
        lines.append(f"license: {_yaml(c.licence)}")
    if c.doi:
        lines.append(f"doi: {_yaml(c.doi)}")
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
