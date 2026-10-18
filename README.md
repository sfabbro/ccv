# ccv

Build an updated **Canadian Common CV (CCV)** XML from your publication list,
ready to import at <https://ccv-cvc.ca/> (Utilities → Import CV XML).

`ccv-update` fetches your papers from **NASA ADS** and **Google Scholar**,
merges and de-duplicates them, and rebuilds the Publications sections of a CCV
export you provide as the base. It also handles NSERC-specific requirements:
the six-year window, the HQP `(*)` rule, and Contribution Role / Percentage.

Based on [ijiraq/CCV](https://github.com/ijiraq/CCV), now self-contained.

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

## Quick start

Export your current CV from ccv-cvc.ca (Utilities → Export) to use as the base,
then run **one full-career build** (ADS by ORCID + Scholar scrape):

```bash
export ADS_API_TOKEN=...   # ADS → Settings → API Token
pixi run ccv-update \
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
publication author lists (e.g. `Ferreira, A. (*)`):

- `--hqp-from-base` — read supervised names and supervision dates from the
  base CCV's Supervisory Activities section
- `--hqp-names "Name1, Name2"` — explicit list instead
- `--hqp-dry-run` — preview exactly which authors would be marked or unmarked,
  without writing the output file

Matching compares full given names before initials (a paper by `Murray, Calum`
is not your former student `Christopher Murray`), supports compound surnames,
and only marks papers written around the supervision period.

## Importing into the CCV

1. Sign in at <https://ccv-cvc.ca/>, **Utilities → Export** — save a backup.
2. **Utilities → Import CV XML** — upload the generated file (e.g.
   `CCV-updated.xml`).
3. Prefer replacing **Publications** first if you want a cautious merge.
4. Spot-check years, HQP `(*)`, and Contribution Role / Percentage.
5. If the import looks wrong, re-import the backup from step 1.

## Development

```bash
pixi run test
python check_schema.py CCV-export.xml . /path/to/dataset-cv-lov.xml
```

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

## License

MIT — see [LICENSE](LICENSE).
