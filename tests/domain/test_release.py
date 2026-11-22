"""A release's hashes: each record's comparison hash (by field id, so a rename
changes nothing), and the content hash over the structure, the records'
hashes (`records.hashes`, checked against the lines) and the files they cite
(no file is read), never the zip's bytes."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

from civex.domain import release as rules


def _zip(
    members: list[tuple[str, bytes]], date=(2026, 1, 1, 0, 0, 0)
) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(zipfile.ZipInfo(name, date), data)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


FILE = b"some bytes"
SHA = hashlib.sha256(FILE).hexdigest()
SID, CID, X, F, CALC = "s-1", "c-1", "f-x", "f-f", "f-calc"
STRUCTURE = {
    "schemas": [
        {
            "id": SID,
            "name": "site",
            "parent_id": None,
            "fields": [
                {"id": X, "name": "x", "type": "integer"},
                {"id": F, "name": "f", "type": "file"},
                {"id": CALC, "name": "calc", "type": "formula"},
            ],
        }
    ],
    "collections": [{"id": CID, "name": "c"}],
}


def _line(rid: str, **data) -> bytes:
    line = {"id": rid, "collection": "c", "schema": "site", "parent": None}
    return json.dumps(line | {"data": data}).encode() + b"\n"


R1 = _line("1", x=1, f={"sha256": SHA, "size": 10}, calc=99)
R2 = _line("2", x=2)


def _bundle(
    lines: bytes, structure=STRUCTURE, date=(2026, 1, 1, 0, 0, 0), sidecar=None
):
    """A bundle with its records.hashes worked out from `lines` (or given)."""
    members = [
        (rules.STRUCTURE_JSON, json.dumps(structure).encode()),
        ("records.jsonl", lines),
    ]
    if sidecar is None:
        hashes, _, problems = rules.line_hashes(_zip(members), structure)
        assert not problems
        sidecar = rules.hashes_text(hashes).encode()
    return _zip(members + [(rules.RECORD_HASHES, sidecar)], date)


def test_a_record_hash_is_by_field_id_and_ignores_what_is_not_stored():
    one = rules.record_hash("1", CID, SID, None, {X: 1, "other": 5}, {X})
    assert one == rules.record_hash("1", CID, SID, None, {X: 1, F: None}, {X, F})
    located = {"sha256": SHA, "size": 1, "location": {"volume": "a"}}
    plain = {"sha256": SHA, "size": 1}
    assert rules.record_hash("1", CID, SID, None, {F: located}, {F}) == (
        rules.record_hash("1", CID, SID, None, {F: plain}, {F})
    )
    assert one != rules.record_hash("1", CID, SID, None, {X: 2}, {X})
    assert one != rules.record_hash("1", "c-2", SID, None, {X: 1}, {X})
    assert one != rules.record_hash("1", CID, SID, "p", {X: 1}, {X})


def test_renaming_a_field_changes_no_line_hash():
    renamed = json.loads(json.dumps(STRUCTURE))
    renamed["schemas"][0]["fields"][0].update(name="count", label="Count")
    a, _, _ = rules.line_hashes(_bundle(R1), STRUCTURE)
    b, _, _ = rules.line_hashes(
        _bundle(R1.replace(b'"x"', b'"count"'), renamed), renamed
    )
    assert a == b
    assert rules.structure_changes(STRUCTURE, renamed) == [
        {
            "kind": "field",
            "change": "changed",
            "name": "count",
            "schema": "site",
            "what": ["name", "label"],
        }
    ]


def test_a_release_from_before_kinds_had_charts_reads_as_having_none():
    # Its structure has no `charts` key at all: a kind with none now is the
    # same; one given charts since has changed.
    none = {"schemas": [STRUCTURE["schemas"][0] | {"charts": None}]}
    assert rules.structure_changes(STRUCTURE, none) == []
    some = {"schemas": [STRUCTURE["schemas"][0] | {"charts": [{"id": "a"}]}]}
    assert [c["what"] for c in rules.structure_changes(STRUCTURE, some)] == [
        ["charts"]
    ]


def test_the_hash_ignores_times_order_and_what_a_read_adds():
    one = _bundle(R1 + R2)
    located = R1.replace(b'"size": 10}', b'"size": 10, "location": {"volume": "x"}}')
    assert located != R1
    two = _bundle(R2 + located, date=(2030, 6, 6, 6, 6, 6))
    a, b = rules.hash_bundle(one), rules.hash_bundle(two)
    assert a.content_hash == b.content_hash and not a.problems
    assert a.records == 2 and a.cited == [SHA]


def test_the_hash_changes_with_the_data_and_with_a_cited_file():
    base = rules.hash_bundle(_bundle(R1))
    edited = rules.hash_bundle(_bundle(_line("1", x=3)))
    assert base.content_hash != edited.content_hash
    other = hashlib.sha256(b"other bytes").hexdigest()
    swapped = rules.hash_bundle(_bundle(R1.replace(SHA.encode(), other.encode())))
    assert swapped.content_hash != base.content_hash and swapped.cited == [other]


def test_a_sidecar_that_does_not_match_the_lines_is_a_problem():
    good = _bundle(R1 + R2)
    sidecar = good.read(rules.RECORD_HASHES)
    edited = _bundle(R1 + _line("2", x=7), sidecar=sidecar)
    result = rules.hash_bundle(edited)
    assert result.content_hash == rules.hash_bundle(good).content_hash
    assert result.problems == ["records.hashes does not match the records (1 differ)"]
    assert rules.hash_bundle(_zip([("records.jsonl", R1)])).problems


def test_citation_forms():
    facts = rules.CitationFacts(
        name="v1",
        title="Seals & {stuff}",
        authors=[
            {"name": "Ada Lovelace", "orcid": "0000-0002-1825-0097"},
            {"name": "Hopper, Grace", "affiliation": "Navy"},
        ],
        keywords=["seals"],
        year="2026",
        date="2026-11-21",
        content_hash="sha256:abc",
        doi="10.1234/x",
    )
    assert rules.citation_text(facts).startswith("Ada Lovelace & Hopper, Grace (2026).")
    bib = rules.bibtex(facts)
    assert (
        "Seals \\& \\{stuff\\}" in bib
        and "author = {Ada Lovelace and Hopper, Grace}" in bib
    )
    cff = rules.citation_cff(facts)
    assert 'family-names: "Hopper"' in cff and 'given-names: "Grace"' in cff
    assert 'orcid: "https://orcid.org/0000-0002-1825-0097"' in cff
    assert 'affiliation: "Navy"' in cff and 'keywords:\n  - "seals"' in cff
    assert rules.check_metadata({"doi": "doi:10.1234/x"})["doi"] == "10.1234/x"


def test_authors_and_keywords_are_tidied():
    meta = rules.check_metadata(
        {
            "authors": [
                "Ada Lovelace",
                {"name": " ", "orcid": "x"},
                {
                    "name": "Bo",
                    "orcid": "orcid.org/0000-0002-1825-009x",
                    "affiliation": "",
                },
            ],
            "keywords": [" seals ", "seals", ""],
        }
    )
    assert meta["authors"] == [
        {"name": "Ada Lovelace"},
        {"name": "Bo", "orcid": "0000-0002-1825-009X"},
    ]
    assert meta["keywords"] == ["seals"]
