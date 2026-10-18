# ccv

Update the Publications section of a [Canadian Common CV](https://ccv-cvc.ca/)
from NASA ADS and Google Scholar, then import that XML back into the CCV.

Inspired by [JJ Kavelaars' CCV](https://github.com/ijiraq/CCV).

`ccv-update` reads an export you already have, replaces the publication
records, and leaves the rest of the CV as it was. For NSERC it can also apply
the six-year window, the HQP `(*)` mark, and Contribution Role.

## Install

```bash
git clone https://github.com/sfabbro/ccv.git
cd ccv
python3 -m venv .venv
.venv/bin/pip install -e .
```

That installs the `ccv` and `ccv-update` commands in `.venv/bin`.

If you use [pixi](https://pixi.sh/), `pixi install` does the same thing, and
`pixi run ccv-update` replaces `.venv/bin/ccv-update` below.

## 1. Export the XML

1. Sign in at <https://ccv-cvc.ca/>.
2. Open **Utilities → Export**.
3. Click **Download** and save the file, for example `CCV-export.xml`.
4. Keep that file. It is the backup you re-import if something looks wrong.

That file is `--base`.

## 2. Build an updated XML

One full-career build (ADS by ORCID, plus a Scholar scrape):

```bash
export ADS_API_TOKEN=...   # ADS → Settings → API Token
.venv/bin/ccv-update \
    --base CCV-export.xml \
    --out CCV-updated.xml \
    --surname Smith \
    --ads-orcid 0000-0001-0000-0000 \
    --gs-author "Ada Smith" \
    --preserve-extra --hqp-from-base --no-percentage \
    --validate --summarize
```

For an **NSERC Discovery** attachment, add `--last-years 6` and write to a
separate file (e.g. `CCV-nserc.xml`): that keeps only entries from Jan 1 six
years back, matching NSERC's window.

Prefer `--ads-orcid` over `--ads-author` when you have an ORCID (cleaner match
set). For reliable Scholar input without scraping, use `--gs-bib
~/scholar-export.bib` (My Library → Export → BibTeX) instead of `--gs-author`.
`ccv-update --help` lists everything; the lower-level `ccv` CLI
(`build`, `summarize`, `validate`, `fetch`, `hqp`) is documented there too.

## 3. Import the XML back

1. Sign in at <https://ccv-cvc.ca/>.
2. Open **Utilities → Import CV XML**.
3. Choose `CCV-updated.xml`, complete the captcha, and upload.
4. Replace **Publications**, or replace the whole CV. Everything except the
   publication records is what you exported in step 1.
5. Confirm the overwrite warning.
6. Open Publications and check a few rows: year, authors, `(*)`, and
   Contribution Role.
7. If the import looks wrong, import `CCV-export.xml` the same way.

## Publication sources

Combine freely — on duplicates, ADS wins (richer metadata):

| Flag | Meaning |
|---|---|
| `--ads-token` / `$ADS_API_TOKEN` | ADS API token (ADS → Settings → API Token) |
| `--ads-orcid` | ORCID iD (recommended) |
| `--ads-author`, `--ads-query`, `--ads-bibcodes` | ADS search alternatives; `--ads-author` takes phrases like `"Smith, J"` |
| `--ads-bib FILE` | skip the API; use an existing ADS BibTeX export |
| `--gs-author NAME` | scrape Google Scholar (best-effort, throttled; use `--gs-timeout`) |
| `--gs-bib FILE` | Scholar export file — reliable, recommended |
| `--bib FILE` | any other local `.bib` file |

Yearless Scholar snippets are skipped (CCV/NSERC need a Year). Scholar results
carry truncated author lists and venues, so with an ADS token every
Scholar-only paper is looked up in ADS by title and replaced by the full ADS
record. Snippets whose truncated author list lacks your surname are kept and
flagged by `--validate` (`--drop-unverified-scholar` drops them).

## Useful options

- `--surname NAMES` — surnames used to detect first/last authorship
  (**required**). The run aborts if they disagree with the Family Name in the
  base CCV, so you cannot accidentally import someone else's papers;
  `--no-name-check` overrides this.
- `--since YYYY[-MM]` / `--last-years N` — publication cutoff.
- `--preserve-extra` — keep base-CV publications absent from the BibTeX
  (otherwise they are removed); empty Contribution Role is filled from
  authorship heuristics.
- `--no-percentage` — leave Contribution Percentage blank (set it by hand in
  the CCV UI); Role is still filled.
- `--overrides FILE` — YAML rules for invited / refereed / status / percentage /
  skip, matched by bibcode, DOI, title or venue glob (format documented in
  `ccv/overrides.py`).
- `--validate` / `--strict` — flag missing fields, rows that do not list you,
  truncated venues, invalid URLs, and preprints marked refereed or published.
- `--summarize` — section counts plus Discovery-oriented metrics.

## NSERC HQP rule

Every student or postdoc you supervised must be marked with `(*)` in
publication author lists (e.g. `Nguyen, A. (*)`):

- `--hqp-from-base` — read supervised names and supervision dates from the
  base CCV's Supervisory Activities section
- `--hqp-names "Name1, Name2"` — explicit list instead
- `--hqp-dry-run` — preview exactly which authors would be marked or unmarked,
  without writing the output file

Matching compares full given names before initials (a paper by `Lee, Colin`
is not your former student `Christopher Lee`), supports compound surnames,
and only marks papers written around the supervision period.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
python check_schema.py CCV-export.xml . /path/to/dataset-cv-lov.xml
```

With pixi, `pixi run test` runs the same pytest.

Field and LOV ids in `ccv/schema.py` are cross-checked against the official
CCV schema (<https://ccv-cvc.ca/schema/dataset-cv.xml>) and real exports with
`check_schema.py` — a wrong id would silently corrupt an import.

## Notes

- **Google Scholar has no official API.** The `scholarly` scrape works from
  residential IPs but is often blocked from cloud hosts; it uses signal-based
  timeouts (macOS/Linux, not Windows). Prefer `--gs-bib` or ADS-only for
  automation.
- The merged BibTeX behind each output is kept next to `--out` as
  `<out>.sources.bib`, for inspection and backup.
- From a source checkout, `python -m ccv.update ...` and `python
  ccv_update.py ...` work without the console scripts.
- NSERC's own guidance: [How to complete NSERC's version of the Canadian Common
  CV](https://nserc-crsng.canada.ca/en/funding/online-application-systems-and-tools/online-services/research-portal/instructions/how).
  `scripts/fetch-nserc-instructions.sh` saves the current page locally. It is
  not stored in this repo.
