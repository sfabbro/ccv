# ccv_update

Fetch your publications from **NASA ADS** and **Google Scholar**, merge and
de-duplicate them, and build an updated **Canadian Common CV (CCV)** XML file
ready to import at <https://ccv-cvc.ca/> (Utilities → Import CV XML).

This is a thin, clean wrapper around the `ccv` package from
[github.com/ijiraq/CCV](https://github.com/ijiraq/CCV), which must be checked
out as a sibling directory (it already is: `../ijiraq-CCV`). It adds:

1. **Automated retrieval** — ADS via the official ADS API, Google Scholar via
   `scholarly` (best-effort) or a Scholar export file.
2. **Merging + de-duplication** — all sources are combined into one BibTeX
   stream; cross-source duplicates (by DOI, then title) are dropped, with ADS
   entries taking precedence.
3. **Template repair** — real CCV exports often omit empty sections (e.g. Book
   Chapters). The wrapper injects any missing managed publication template so
   `ccv build` works, then strips the leftover empty template from the output.

## Install

```bash
git clone https://github.com/ijiraq/CCV            # sibling dir (done here)
cd ijiraq-CCV && python3 -m venv .venv
uv pip install --python .venv/bin/python scholarly
```

## Usage

```bash
ijiraq-CCV/.venv/bin/python ccv_update.py \
    --base      CCV-export.xml \
    --out       CCV-updated.xml \
    --surname   Fabbro \
    --ads-token "$ADS_API_TOKEN" --ads-author "Fabbro, S" \
    --gs-bib    ~/google-scholar-export.bib \
    --since     2020-01 \
    --preserve-extra --validate --summarize
```

### Publication sources (combine freely; ADS wins on duplicates)

| Flag | Meaning |
|---|---|
| `--ads-token` / `$ADS_API_TOKEN` | ADS API token (ADS → Settings → API Token) |
| `--ads-author`, `--ads-orcid`, `--ads-query`, `--ads-bibcodes` | what to search ADS for. `--ads-author` takes ADS phrases like `"Fabbro, S"` (initials stay glued to the surname; a second comma-separated surname adds an OR, e.g. `"Fabbro, Kavelaars"`) |
| `--ads-bib FILE` | skip the API; use an existing ADS BibTeX export |
| `--gs-author NAME` | scrape Google Scholar (best-effort, throttled; use a short `--gs-timeout`) |
| `--gs-bib FILE` | Scholar export file (My Library → Export → BibTeX) — reliable, recommended |
| `--bib FILE` | any other local `.bib` file |

### Build options (from ijiraq/CCV)

- `--since YYYY[-MM]` — only include entries on/after the cutoff
- `--last-years N` — keep only the last N years; NSERC validates the
  Contributions section back to Jan 1 six years prior, so use `--last-years 6`
  for a Discovery application
- `--surname` — your surname(s); used to mark first/last authorship (default `Fabbro`)
- `--no-name-check` — skip the family-name mismatch warning (see below)
- `--preserve-extra` — keep base-CV publications absent from the BibTeX
  (otherwise they are removed, as the upstream tool intends)
- `--overrides FILE` — YAML rules for invited/refereed/status/percentage

### NSERC-specific options

NSERC requires that every student/postdoc you supervise(d) be marked with an
asterisk in publication author lists (the "HQP rule"). The CCV convention is
`Name (*)` (e.g. `Ferreira, A. (*)`).

- `--hqp-from-base` — read supervised-student names from the base CCV's
  "Supervisory Activities" section and append ` (*)` to matching authors in
  all publication records (new and preserved)
- `--hqp-names "Name1, Name2"` — same, but from an explicit list
- `--hqp-dry-run` — **preview only**: print exactly which authors would be
  marked (per paper, with the supervised name matched) and exit *without*
  writing the output file. Combine with either `--hqp-from-base` or
  `--hqp-names`.

Matching is conservative: surname + given-name initial, case-insensitive.
Authors already carrying a `*` are never double-marked.

### Name-mismatch safeguard

The wrapper reads the **Family Name** from your base CCV's Personal Information
section and warns — *before* any network fetch — when `--surname`, `--ads-author`,
`--ads-query`, or `--gs-author` disagree with it:

```
WARNING: name mismatch with base CCV — the run may be fetching someone else's publications!
  base CCV Family Name: Fabbro
  - --ads-author 'Kavelaars, J' searches surnames ['kavelaars'] but the base CCV Family Name is 'Fabbro'
```

This catches the most damaging mistake (searching the wrong person's name). The
warning does **not** stop the run; if you are deliberately updating someone
else's CV, pass `--no-name-check`. CCVs without a Family Name field skip the
check silently.

```bash
# See exactly which authors would be marked, then decide:
ijiraq-CCV/.venv/bin/python ccv_update.py \
    --base CCV-export.xml --out CCV-updated.xml --surname Fabbro \
    --ads-bib ~/ads-export.bib --hqp-from-base --hqp-dry-run
```

### Checks

- `--validate` — report publications missing CCV-required fields
- `--validate-max N` — limit the number of issues printed (default 25)
- `--strict` — exit non-zero when `--validate` finds issues
- `--summarize` — print section counts of the output

## Notes

- **Validation flags are pre-existing.** A `--validate` report mostly flags
  empty Contribution Role/Percentage on records that were already in your base
  CCV export; the wrapper does not introduce them. Fill these in the CCV UI.
- **Schema verified.** All field IDs and LOV IDs used by the underlying `ccv`
  package were cross-checked against the official CCV schema
  (`ccv-cvc.ca/schema/dataset-cv.xml`, `dataset-cv-lov.xml`) and against the
  user's own export — all match. Re-run with:
  `python check_schema.py CCV-export.xml ../ijiraq-CCV /path/to/dataset-cv-lov.xml`.
- **Google Scholar has no official API.** The `scholarly` scrape works from
  residential IPs but is often throttled/blocked from cloud hosts. For reliable
  automation use `--gs-bib` with a Scholar export, or use ADS only.
- The merged BibTeX that produced the output is written next to `--out` as
  `<out>.sources.bib` for inspection/backup.

## Requirements

- Python 3.10+ with `bibtexparser`, `PyYAML` (from ijiraq/CCV's requirements)
  and `scholarly` (for `--gs-author` only)
- A CCV account, an ADS API token (for `--ads-*` API mode), and/or BibTeX exports
