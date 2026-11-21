"""The release content hash is over what a bundle holds, never its zip bytes."""

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
    one = _zip(
        [("bundle.json", MANIFEST), ("records.jsonl", R1 + R2), ("files/" + SHA, FILE)]
    )
    other_manifest = json.loads(MANIFEST)
    other_manifest["exported_at"] = "2027-05-05"
    other_manifest["schemas"].reverse()
    located = R1.replace(b'"size":10}', b'"size":10,"location":{"volume":"x"}}')
    two = _zip(
        [
            ("files/" + SHA, FILE),
            ("records.jsonl", R2 + located),
            ("bundle.json", json.dumps(other_manifest).encode()),
            (rules.CITATION_CFF, b"cff-version: 1.2.0\n"),
        ],
        date=(2030, 6, 6, 6, 6, 6),
    )
    a, b = rules.hash_bundle(one), rules.hash_bundle(two)
    assert a.content_hash == b.content_hash and not a.problems
    assert (a.records, a.files) == (2, 1)


def test_the_hash_changes_with_the_data_and_catches_a_bad_file():
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
    bad = rules.hash_bundle(
        _zip([("bundle.json", MANIFEST), ("files/" + SHA, b"other")])
    )
    assert bad.problems


def test_citation_forms():
    facts = rules.CitationFacts(
        name="v1",
        title="Seals & {stuff}",
        authors=["Ada Lovelace", "Hopper, Grace"],
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
    assert rules.check_metadata({"doi": "doi:10.1234/x"})["doi"] == "10.1234/x"
