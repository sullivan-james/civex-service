# Releases

A **release** is a frozen, citable copy of a project's data. A paper, a thesis
or a data deposit can say exactly which data it used ("release `v1`, content
hash `sha256:4f1c…`"), and that data can be had back later, however much the
project has changed since.

!!! note "Releases are published on a civex hub"
    A release made on a personal computer would be neither authentic nor
    reachable by anyone else, so **a release is made, kept and shared by a host
    (a civex hub), and is never synced**. Only a host switches it on (the
    `releases` feature); the app on your computer has no Releases pages, and
    `civex release` only says so: there is no command to create, list, read or
    export one here. A bundle (`civex bundle export`) is the free, local copy;
    a release is the hub's layer over it: a permanent name, frozen content, a
    citation, a public page and access control. To take a hub's release, use
    `civex clone <repo-url> --release NAME` (see below). Releases an older civex
    made on a computer are no longer shown there.

A release has:

- a **version** you choose (`v1`, `2026-thesis`): letters, digits, `.`, `_`
  and `-`; it can't be changed later;
- **citation details**: a title, a description, the authors in citation order
  (each with an ORCID and an affiliation if they have them), a licence (an
  SPDX id such as `CC-BY-4.0`, or any other), keywords and, if it has one, a
  DOI;
- what it **covers**: the whole project, some collections, a saved list, or
  records chosen in the explorer (each with the records above it and everything inside it, so an encounter comes with its recordings and it reads
  back whole);
- a small **bundle of records**: schemas, collections and records with their
  ids (and, only if you tick **Include workflows and plugins**, their code:
  it is left out by default, since code may not be yours to publish), plus a
  `release.json` manifest and a
  `CITATION.cff`;
- the **files** its records cite, which it keeps where they are. Nothing is
  copied: the release becomes one more owner of each file, like the records
  that use it.

Because only the records are written, making a release of a project with
terabytes of files across many drives takes moments, and needs none of those
drives plugged in.

## Making one

On a host that offers releases (a civex hub), in the app: **Releases → New release**, or tick records in a collection's
explorer and press **Release these…**. The page has three steps:

1. **What**: the whole project, some collections, a saved list, or the
   records chosen, with how many records and files that is.
2. **Citation**: the version, title, description, authors, licence, DOI and
   keywords, with the citation shown as it will read (text, BibTeX or
   `CITATION.cff`) as you type.
3. **Review**: the records per collection, the files by drive, and where
   history is.

There is no command that makes one: `civex release create` was removed, and
`civex release` says "Releases are published on a civex hub".

Making, correcting, withdrawing and yanking a release need the **release**
permission (`release`). A role that could change the project's structure
(`change_structure`) has it too, unless the host withholds it, so a
self-hosted authority that enables the feature behaves as it did.

## The content hash

Each record in a release has a hash of its own: of its id, its collection,
its kind, the record it sits inside and its values, with each value keyed by
the field's id rather than its name. Renaming a field or changing its name
on screen changes no record's hash. The release keeps these, sorted by
record id, in `records.hashes`, beside `structure.json` (its schemas, fields
and collections with their ids).

The content hash is a sha256 over what the release **holds**, not over the
zip's bytes (a zip records the time it was written). It covers, in a fixed
order: the structure, every record's hash (by record id), the sha256 of
every file the records cite (sorted), and any workflows and plugins it
was made with. A file
is covered by its own hash, so no file is read to make or check it. Making a
release of the same data again gives the same hash; changing one value, or
the file a record cites, gives a different one.

## Its files

A release keeps every file its records cite, so a clean-up never removes one
while the release exists, even after the records have let it go. A file's
details (**More details** on a file, or `civex store where`) name the
releases keeping it, and permanently deleting a record says which releases
keep its files.

When files move between drives, a release goes with its records: emptying a
drive moves everything on it, and gathering a collection onto another drive
moves the release's copy too once every record using that copy has moved. A
release never holds a copy back on its own; if some record still uses the
copy where it was, the release stays with that one.

To get a release out, its page has one button, **Export…**, with the same
two ways as any export:

- **Save to a folder**: any folder of this computer (**Choose…**), with the
  files laid out as the records were (a folder per record). The folder also
  holds the release's records as one file, which **Bring in from another
  project…** (or `civex bundle import`) reads;
- **Download a zip**: offered only while the release is small enough
  (2000 files, 500 MB).

Each folder and zip also holds `manifest-sha256.txt` (BagIt: each file's
sha256 and its path), `release.json` and `CITATION.cff`, so it stands alone.

The page's menu has the two things that are not an export: **Copy to another
project…** (the records alone, as one file) and **Change storage drive…**
(which drive civex itself keeps the release's files on; only the release's
own copies move).


## Checking a release

**Verify** (on the release's page) checks that:

- the bundle's bytes still match the sha256 it is kept under;
- every record's hash in `records.hashes` matches its record, hashed again;
- the content hash, recomputed, is the one it was made with;
- every file it cites is recorded on a drive here (on a computer that leaves
  files to the server, missing files are only noted).

It reads no file, so it is quick however large the release.

**Read every file back** (the deep check) also reads every
file against its hash, with its progress in the status bar. A copy whose
bytes don't match is reported and removed, as a clean-up's check does.

## Citing it

The release's page has its citation as plain text, BibTeX and `CITATION.cff`,
each with a copy button.

## What changed since

**Changed since** compares the release with the
data now, record by record: each record it holds is hashed again as it is
now and compared with its hash in the release. For each collection it counts
the records:

- **added**: in what the release covers now, and not in the release;
- **changed**: in both, with a different value or in a different place;
- **removed**: in the release, and deleted or permanently deleted since.

A record is in only one of these. An edit that was undone counts as
unchanged, and every computer gives the same answer, since history is not
read. Schemas and fields added, removed or changed since (a rename among
them) are listed separately. Deleting a field since makes the records that
held a value for it count as changed.

Each number opens the records it means; a changed record shows which fields
differ, with the value in the release and the value now. A large release is
compared in the background, with its progress in the status bar.


## Correcting, withdrawing and yanking

A release's content never changes. Its citation details can be corrected (a
typo in the title, a DOI issued later: **Edit details…**).

It can be **withdrawn** with a reason (**Withdraw…**): it says so wherever it
is shown, and keeps its data, so work that cited it can still be checked.

It can be **yanked** with a reason (**Yank…**) when its data must go. It
stops keeping its files and its bundle, so the next clean-up removes whatever
nothing else uses. You are told first how many files that is, and how many
stay for the records that still use them. What is left is the release's
record: its name, content hash, citation, and who yanked it, when and why, so
a citation still finds it. A yank can't be undone.

Corrections, withdrawals and yanks are recorded in history.

## Getting the records back

A host serves each release as one bundle **with its files**
(`GET /releases/{name}/bundle`, built on disk and streamed). Over plain HTTPS
that is a download you read into a new project with `civex bundle import`; or
let civex do both:

```bash
civex clone https://hub.example.org/ada/seals/data --release v1
```

This makes a new project from the release: nothing is joined or synced, and
it starts **read-only** (a copy to read and cite; `--writable` allows
changes). A private repository needs the host's token (`--token`, or
`CIVEX_TOKEN`). Workflows and plugins in the bundle are not installed.


## On a project that syncs

**Releases are never synced** (sync protocol 6). A device does not send them,
the authority does not feed or snapshot them and refuses one it is sent (the
refusal code is `not_synced`), and the files a release keeps are not something
a device sends or fetches. The files a release keeps stay on the host that
made it (it owns them in its catalogue, so they are never cleaned up while the
release is not yanked).
