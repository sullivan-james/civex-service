# Releases

A **release** is a frozen, citable copy of a project's data. A paper, a thesis
or a data deposit can say exactly which data it used ("release `v1`, content
hash `sha256:4f1c…`"), and that data can be got back later, however much the
project has changed since.

A release has:

- a **version** you choose (`v1`, `2026-thesis`): letters, digits, `.`, `_`
  and `-`; it can't be changed later;
- **citation details**: a title, a description, the authors in citation
  order, a licence (for example `CC-BY-4.0`) and, if it has one, a DOI;
- what it **covers**: the whole project, some collections, or the records a
  query lists (with the records above them, so it reads back whole);
- a **bundle**: the same file `civex bundle export` writes (schemas,
  collections, records with their ids, optionally the stored files, workflows
  and plugins), plus a `release.json` manifest and a `CITATION.cff`;
- a **manifest**: the content hash, what it holds, where history was when it
  was made, and the civex that made it.

## Making one

In the app: **Releases → New release**. The dialog asks for the version and
citation details, what it covers and whether to include the files, and shows
what the release will hold (records, collections, files and their size)
before anything is made.

From the command line:

```bash
civex release create v1 --title "Grey seal survey 2026" \
    --author "Ada Lovelace" --author "Grace Hopper" --licence CC-BY-4.0
civex release create north-only --title "North sites" -c north --no-files
civex release create v1 --title "…" --dry-run     # what it would hold
```

Making a release needs permission to change the project's structure, as a
schema does: others depend on it.

On a project that syncs, a computer with changes the server hasn't got yet is
asked to sync first, so the release is taken at a point every copy of the
project shares (the server's feed number is recorded with it).

## The content hash

The content hash is a sha256 over what the bundle **holds**, not over the zip
file's bytes (a zip records the time it was written, so two exports of the
same data are different files). It covers, in a fixed order: the schemas and
collections, every record line (by record id), the stored files carried (each
also checked against its own hash) and the workflows and plugins. Exporting
the same data again gives the same hash; changing one value gives a different
one.

## Checking a release

**Verify** (on the release's page, or `civex release verify v1`) reads the
stored bundle back, recomputes the content hash and checks each file against
its own hash. It says whether the bundle still holds exactly what the release
was made with.

## Citing it

The release's page has its citation as plain text, BibTeX and `CITATION.cff`,
each with a copy button. From the command line:

```bash
civex release cite v1                 # one paragraph
civex release cite v1 -f bibtex
civex release cite v1 -f cff > CITATION.cff
```

## What changed since

**Changed since** (or `civex release diff v1`) counts the records added,
changed and deleted per collection after the release was made, and any changes
to schemas, fields or collections, from the project's history.

## Correcting and withdrawing

A release's content never changes and a release is never deleted. Its citation
details can be corrected (a typo in the title, a DOI issued later: **Edit
details…** or `civex release correct v1 --doi 10.1234/abcd`), and it can be
withdrawn with a reason (**Withdraw…** or `civex release withdraw v1 -r
"calibration error"`). Both are recorded in history, so what it said before
stays on record; a withdrawn release keeps its bundle, so work that cited it
can still be checked.

## Getting the data back

Download the bundle (**Download**, or `civex release download v1`) and read it
into a **new** project with `civex bundle import` (or **Collections → Import
bundle…**). That is the whole restore: records keep their ids, and files come
with them if the release included them.

```bash
mkdir restored && cd restored && civex init
civex bundle import ../release-v1.civex.zip
```

## Where releases are kept

The bundle is kept in the project's storage like any file (on a drive, or in
the bucket), under its own sha256; clean-ups never remove it. On a project
that syncs, the release itself syncs to every copy and the bundle is sent to
the server like a record's file; another computer downloads the bundle when
it is first verified or downloaded there.
