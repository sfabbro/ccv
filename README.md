# ccv

Fetch your publications from **NASA ADS** and **Google Scholar**, merge and
de-duplicate them, and build an updated **Canadian Common CV (CCV)** XML file
ready to import at <https://ccv-cvc.ca/> (Utilities → Import CV XML).

This repo is self-contained: it includes the `ccv` package (originally based on
[ijiraq/CCV](https://github.com/ijiraq/CCV)) plus a high-level `ccv-update`
wrapper that adds:

1. **Automated retrieval** — ADS via the official ADS API, Google Scholar via
   `scholarly` (best-effort) or a Scholar export file.
2. **Merging + de-duplication** — sources are combined into one BibTeX stream;
   cross-source duplicates are dropped by **DOI and normalized title** (ADS
   first, so richer ADS metadata wins). Greek/LaTeX title variants (e.g. `Ω`
   vs `\Omega`) are folded together.
3. **Template repair** — real CCV exports often omit empty sections (e.g. Book
   Chapters). The wrapper injects any missing managed publication template so
   `build` works, then strips leftover empty templates from the output.
4. **NSERC helpers** — six-year window, HQP `(*)` marking, and auto-fill of
   empty Contribution Role / Percentage on preserved base records.

## Install

With [pixi](https://pixi.sh/) (recommended):

```bash
git clone https://github.com/sfabbro/ccv.git
cd ccv
pixi install
```

Or with pip / a venv:

```bash
git clone https://github.com/sfabbro/ccv.git
cd ccv
python3 -m venv .venv
.venv/bin/pip install -e .
```

Both install the `ccv` and `ccv-update` console scripts.

## Usage

**Full career** (no year cutoff) — ADS ORCID + Scholar scrape:

```bash
export ADS_API_TOKEN=...   # ADS → Settings → API Token
pixi run ccv-update \
    --base      CCV-export.xml \
    --out       CCV-updated.xml \
    --surname   Fabbro \
    --ads-orcid 0000-0003-2239-7988 \
    --gs-author "Sebastien Fabbro" \
    --gs-timeout 120 \
    --preserve-extra --hqp-from-base --no-percentage \
    --validate --summarize
```

**NSERC Discovery window** (Jan 1 of six years prior through now):

```bash
pixi run ccv-update \
    --base      CCV-export.xml \
    --out       CCV-nserc.xml \
    --surname   Fabbro \
    --ads-orcid 0000-0003-2239-7988 \
    --gs-author "Sebastien Fabbro" \
    --last-years 6 \
    --preserve-extra --hqp-from-base --no-percentage \
    --validate --summarize
```

Prefer `--ads-orcid` over a broad `--ads-author` when you have an ORCID (cleaner
match set). For reliable Scholar input without scraping, use
`--gs-bib ~/scholar-export.bib` instead of `--gs-author`.

Lower-level CLI:

```bash
pixi run ccv build --base CCV-export.xml --bib papers.bib --out CCV-built.xml
pixi run ccv summarize --base CCV-built.xml
pixi run python check_gs_authors.py   # self-check: Scholar authors + dedupe
```

Without pixi, call `ccv-update` / `ccv` from the venv (or
`python -m ccv.update ...` / `python ccv_update.py ...` from the repo root).

### Publication sources (combine freely; ADS wins on duplicates)

| Flag | Meaning |
|---|---|
| `--ads-token` / `$ADS_API_TOKEN` | ADS API token (ADS → Settings → API Token) |
| `--ads-orcid` | ORCID iD (recommended) |
| `--ads-author`, `--ads-query`, `--ads-bibcodes` | ADS search alternatives. `--ads-author` takes phrases like `"Fabbro, S"` (initials stay glued to the surname; a second comma-separated surname adds an OR, e.g. `"Fabbro, Kavelaars"`) |
| `--ads-bib FILE` | skip the API; use an existing ADS BibTeX export |
| `--gs-author NAME` | scrape Google Scholar (best-effort, throttled; use a generous `--gs-timeout`) |
| `--gs-bib FILE` | Scholar export file (My Library → Export → BibTeX) — reliable |
| `--bib FILE` | any other local `.bib` file |

Yearless Scholar snippets are skipped (CCV/NSERC need a Year). Prefer ADS for
authoritative metadata; Scholar mainly fills gaps ADS missed.

### Build options

- `--since YYYY[-MM]` — only include entries on/after the cutoff
- `--last-years N` — keep only the last N years; NSERC validates Contributions
  back to Jan 1 six years prior, so use `--last-years 6` for Discovery
- `--surname` — your surname(s); used to mark first/last authorship (default `Fabbro`)
- `--no-name-check` — allow a family-name mismatch (default: **abort**)
- `--preserve-extra` — keep base-CV publications absent from the BibTeX
  (otherwise they are removed). With `--since` / `--last-years`, preserved
  rows outside the window are dropped. Empty Contribution Role on preserved
  rows is filled from authorship heuristics.
- `--no-percentage` — leave **Contribution Percentage** blank (do not apply
  first/last/co heuristic bands). Role is still filled. Use this when % varies
  by field practice and you prefer to set it in the CCV UI.
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
section and **aborts before any network fetch** when `--surname`, `--ads-author`,
`--ads-query`, or `--gs-author` disagree with it:

```
error: name mismatch with base CCV — refusing to fetch (would risk writing someone else's publications)
  base CCV Family Name: Fabbro
  - --ads-author 'Kavelaars, J' searches surnames ['kavelaars'] but the base CCV Family Name is 'Fabbro'
  If intentional, pass --no-name-check.
```

CCVs without a Family Name field skip the check silently. To update someone
else's CV on purpose, pass `--no-name-check`.

```bash
# Preview HQP asterisks without writing:
pixi run ccv-update \
    --base CCV-export.xml --out CCV-updated.xml --surname Fabbro \
    --ads-bib ~/ads-export.bib --hqp-from-base --hqp-dry-run
```

### Checks

- `--validate` — report publications missing core CCV fields (Year, Authors,
  Journal/Conference, Contribution Role, Refereed?). Contribution Percentage
  is optional and not flagged.
- `--validate-max N` — limit the number of issues printed (default 25)
- `--strict` — exit non-zero when `--validate` finds issues
- `--summarize` — print section counts + Discovery-oriented metrics

## Import / verify on ccv-cvc.ca

There is no offline CCV UI preview. To see the result:

1. Sign in at <https://ccv-cvc.ca/>.
2. **Utilities → Export** — save a backup of your current CV.
3. **Utilities → Import CV XML** — upload the generated file (e.g. `CCV-updated.xml`).
4. Prefer replacing **Publications** (and related contribution sections) first
   if you want a cautious merge.
5. Open **Contributions → Publications** and spot-check years, HQP `(*)`, and
   Contribution Role / Percentage.
6. For NSERC, link this CCV in the Research Portal and confirm the six-year
   filter does not flag errors (use a `--last-years 6` build for that attach).

If the import looks wrong, re-import the backup from step 2.

## Notes

- **Schema verified.** Field IDs and LOV IDs in the `ccv` package were
  cross-checked against the official CCV schema and a real user export. Re-run:
  `python check_schema.py CCV-export.xml . /path/to/dataset-cv-lov.xml`.
- **Google Scholar has no official API.** The `scholarly` scrape works from
  residential IPs but is often throttled/blocked from cloud hosts. Prefer
  `--gs-bib` or ADS-only for automation.
- The merged BibTeX that produced the output is written next to `--out` as
  `<out>.sources.bib` for inspection/backup.

## Requirements

- Python 3.10+ (see `pyproject.toml`; installed by `pixi install` or `pip install -e .`)
- A CCV account, an ADS API token (for `--ads-*` API mode), and/or BibTeX exports
