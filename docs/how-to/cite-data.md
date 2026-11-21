# Cite the data in a paper

**Goal:** a paper (or thesis, or deposit) that says exactly which data it
used, and a way to get that data back later.

1. Make sure the data is as you want it, and on a synced project, that it has
   synced.
2. Make a release: **Releases → New release**, or

    ```bash
    civex release create v1 --title "Grey seal survey 2026" \
        --author "Ada Lovelace|0000-0002-1825-0097" --licence CC-BY-4.0
    ```

    The files the records cite are kept where they are, not copied, so this
    is quick however much data there is.

3. Copy the citation from the release's page (text or BibTeX), or

    ```bash
    civex release cite v1 -f bibtex >> references.bib
    ```

    It names the version and the content hash, so a reader can tell whether
    the data they have is the data you used.

4. If you deposit the data (Zenodo, a university repository), make a folder
   of it (**Open as a folder**, or `civex release export v1`): the files laid
   out by record, with `manifest-sha256.txt`, `release.json` and
   `CITATION.cff`. Upload that and the release's bundle (**Download**) and,
   once you have a DOI, add it:
   `civex release correct v1 --doi 10.5281/zenodo.123456`.

Later, `civex release verify v1` checks the release still holds exactly that
data (`--deep` reads every file back too), and `civex release diff v1` compares it with the data now (records added, changed and removed). To work
with the data as it was, import the bundle into a new project
(`civex bundle import release-v1.civex.zip`). See [Releases](../guides/releases.md).
