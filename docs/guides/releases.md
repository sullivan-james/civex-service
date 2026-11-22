# Releases

A **release** is a frozen, citable copy of a project's data. A paper, a thesis
or a data deposit can say exactly which data it used ("release `v1`, content
hash `sha256:4f1c…`"), and that data can be had back later, however much the
project has changed since.

A release has:

- a **version** you choose (`v1`, `2026-thesis`): letters, digits, `.`, `_`
  and `-`; it can't be changed later;
- **citation details**: a title, a description, the authors in citation order
  (each with an ORCID and an affiliation if they have them), a licence (an
  SPDX id such as `CC-BY-4.0`, or any other), keywords and, if it has one, a
  DOI;
- what it **covers**: the whole project, some collections, a saved list, or
  records chosen in the explorer (each with the records above it, so it reads
  back whole);
- a small **bundle of records**: schemas, collections and records with their
  ids, workflows and plugins, plus a `release.json` manifest and a
  `CITATION.cff`;
- the **files** its records cite, which it keeps where they are. Nothing is
  copied: the release becomes one more owner of each file, like the records
  that use it.

Because only the records are written, making a release of a project with
terabytes of files across many drives takes moments, and needs none of those
drives plugged in.

## Making one

In the app: **Releases → New release**, or tick records in a collection's
explorer and press **Release these…**. The page has three steps:

1. **What**: the whole project, some collections, a saved list, or the
   records chosen, with how many records and files that is.
2. **Citation**: the version, title, description, authors, licence, DOI and
   keywords, with the citation shown as it will read (text, BibTeX or
   `CITATION.cff`) as you type.
3. **Review**: the records per collection, the files by drive, and where
   history is.

From the command line:

```bash
civex release create v1 --title "Grey seal survey 2026" \
    --author "Ada Lovelace|0000-0002-1825-0097|Analytical Society" \
    --author "Grace Hopper" --licence CC-BY-4.0 -k seals -k acoustics
civex release create north-only --title "North sites" -c north
civex release create picked --title "…" -r <record id> -r <record id>
civex release create v1 --title "…" --dry-run     # what it would hold
```

An author is `Name`, or `Name|ORCID|Affiliation` with either part left
blank.

Making a release needs permission to change the project's structure, as a
schema does: others depend on it.

On a project that syncs, a computer with changes the server hasn't got yet is
asked to sync first, so the release is taken at a point every copy of the
project shares (the server's feed number is recorded with it).

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
every file the records cite (sorted), and the workflows and plugins. A file
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

To get the files out, the release's page has the same ways as any export:

- **Open as a folder**: a folder on the drive holding most of the files,
  laid out as the records were (a folder per record);
- **Put on a drive…**: a folder of copies on the drive you choose;
- **Move to drive…**: put all the release's files on one drive (only the
  release's own copies move; records that use a file elsewhere keep theirs);
- **Download as a zip**: offered only while the release is small enough
  (2000 files, 500 MB); a larger one is made into a folder instead.

Each folder and zip also holds `manifest-sha256.txt` (BagIt: each file's
sha256 and its path), `release.json` and `CITATION.cff`, so it stands alone.

```bash
civex release export v1                       # a folder to open
civex release export v1 --mode copy --volume archive
civex release gather v1 --to archive
```

## Checking a release

**Verify** (on the release's page, or `civex release verify v1`) checks that:

- the bundle's bytes still match the sha256 it is kept under;
- every record's hash in `records.hashes` matches its record, hashed again;
- the content hash, recomputed, is the one it was made with;
- every file it cites is recorded on a drive here (on a computer that leaves
  files to the server, missing files are only noted).

It reads no file, so it is quick however large the release.

**Read every file back** (`civex release verify v1 --deep`) also reads every
file against its hash, with its progress in the status bar. A copy whose
bytes don't match is reported and removed, as a clean-up's check does.

## Citing it

The release's page has its citation as plain text, BibTeX and `CITATION.cff`,
each with a copy button. From the command line:

```bash
civex release cite v1                 # one paragraph
civex release cite v1 -f bibtex
civex release cite v1 -f cff > CITATION.cff
```

## What changed since

**Changed since** (or `civex release diff v1`) compares the release with the
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

```bash
civex release diff v1
civex release diff v1 --show removed
```

## Correcting, withdrawing and yanking

A release's content never changes. Its citation details can be corrected (a
typo in the title, a DOI issued later: **Edit details…** or
`civex release correct v1 --doi 10.1234/abcd`).

It can be **withdrawn** with a reason (**Withdraw…** or
`civex release withdraw v1 -r "calibration error"`): it says so wherever it
is shown, and keeps its data, so work that cited it can still be checked.

It can be **yanked** with a reason (**Yank…** or
`civex release yank v1 -r "consent withdrawn"`) when its data must go. It
stops keeping its files and its bundle, so the next clean-up removes whatever
nothing else uses. You are told first how many files that is, and how many
stay for the records that still use them. What is left is the release's
record: its name, content hash, citation, and who yanked it, when and why, so
a citation still finds it. A yank can't be undone.

Corrections, withdrawals and yanks are recorded in history, and on a project
that syncs they reach every copy.

## Getting the records back

Download the bundle (**Download**, or `civex release download v1`) and read
it into a **new** project with `civex bundle import` (or **Collections →
Bring in from another project…**). Records keep their ids and still name their files; put the
files beside them with the release's folder export.

```bash
mkdir restored && cd restored && civex init
civex bundle import ../release-v1.civex.zip
```

## On a project that syncs

The release syncs to every copy, and its bundle is sent to the server like a
record's file. The server keeps the files the release cites once the bundle
has arrived. Another computer keeps only the bundle (the server keeps the
files), and downloads it when the release is first verified or downloaded
there.
