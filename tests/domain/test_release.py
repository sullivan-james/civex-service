"""The release content hash is over what a bundle holds, never its zip bytes:
its records and the hashes of the files they cite (no file is read)."""

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
MANIFEST = json.dumps(
    {
        "format": 1,
        "exported_at": "2026-01-01",
        "schemas": [{"name": "b"}, {"name": "a"}],
        "collections": [{"name": "c"}],
    }
).encode()
R1 = b'{"id":"1","data":{"x":1,"f":{"sha256":"' + SHA.encode() + b'","size":10}}}\n'
R2 = b'{"id":"2","data":{"x":2}}\n'


def test_the_hash_ignores_times_order_and_what_a_read_adds():
    one = _zip([("bundle.json", MANIFEST), ("records.jsonl", R1 + R2)])
    other_manifest = json.loads(MANIFEST)
    other_manifest["exported_at"] = "2027-05-05"
    other_manifest["schemas"].reverse()
    located = R1.replace(b'"size":10}', b'"size":10,"location":{"volume":"x"}}')
    two = _zip(
        [
            ("records.jsonl", R2 + located),
            ("bundle.json", json.dumps(other_manifest).encode()),
            (rules.CITATION_CFF, b"cff-version: 1.2.0\n"),
        ],
        date=(2030, 6, 6, 6, 6, 6),
    )
    a, b = rules.hash_bundle(one), rules.hash_bundle(two)
    assert a.content_hash == b.content_hash and not a.problems
    assert a.records == 2 and a.cited == [SHA]


def test_the_hash_changes_with_the_data_and_with_a_cited_file():
    base = rules.hash_bundle(_zip([("bundle.json", MANIFEST), ("records.jsonl", R1)]))
    edited = rules.hash_bundle(
        _zip(
            [
                ("bundle.json", MANIFEST),
                ("records.jsonl", R1.replace(b'"x":1', b'"x":3')),
            ]
        )
    )
    assert base.content_hash != edited.content_hash
    other = hashlib.sha256(b"other bytes").hexdigest()
    swapped = rules.hash_bundle(
        _zip(
            [
                ("bundle.json", MANIFEST),
                ("records.jsonl", R1.replace(SHA.encode(), other.encode())),
            ]
        )
    )
    assert swapped.content_hash != base.content_hash and swapped.cited == [other]


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
