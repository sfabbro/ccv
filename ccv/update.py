#!/usr/bin/env python3
"""ccv-update — fetch papers from NASA ADS + Google Scholar and build an
updated Canadian Common CV (CCV) XML.

Part of the `ccv` package. Inspired by https://github.com/ijiraq/CCV.
Adds:

  1. Automated retrieval of your publications:
       - NASA ADS          via the official ADS API (needs an API token)
       - Google Scholar    via the `scholarly` package (best-effort) or a
                           Scholar "My Library -> Export -> BibTeX" file
  2. A single merged + de-duplicated BibTeX stream from every source.
  3. Auto-injection of any managed publication template (e.g. Book Chapters)
     that is missing from your base CCV export, so `build` works on real
     exports that omit empty sections.

Output is a CCV XML file ready for "Utilities -> Import CV XML" at
https://ccv-cvc.ca/ — plus a record of the merged BibTeX that produced it.

Example:
    ccv-update \\
        --base      CCV-export.xml \\
        --out       CCV-updated.xml \\
        --surname   Smith \\
        --ads-token "$ADS_API_TOKEN" --ads-orcid 0000-0001-0000-0000 \\
        --last-years 6 --hqp-from-base --preserve-extra --validate
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from bibtexparser import bparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bwriter import BibTexWriter

import ccv.bibtex_io as bibtex_io
import ccv.builder as builder
import ccv.fetch_ads as fetch_ads
import ccv.publications as publications
import ccv.schema as schema
import ccv.validate as validate
import ccv.xmlutil as xmlutil
from ccv.bibtex_io import (
    clean_title,
    entry_keys,
    is_truncated_text,
    normalize_arxiv,
    titles_equivalent,
    venue_entrytype,
)
from ccv.fetch_ads import split_ads_authors
from ccv.hqpmatch import Trainee, find_trainee, is_marked, trainees_from_names, unmark
from ccv.publications import _preserved_problem, _record_is_scholar


# ---------------------------------------------------------------------------
# Google Scholar retrieval (best-effort; Scholar throttles aggressively).
# ---------------------------------------------------------------------------


def _timeout(seconds: int):
    """Abort the current thread's work after *seconds* (POSIX only)."""

    def handler(signum, frame):  # pragma: no cover - signal plumbing
        raise TimeoutError(f"timed out after {seconds}s")

    old = signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    return old


def _cancel_timeout(old) -> None:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def _gs_entrytype(venue: str) -> str:
    """Type a Scholar snippet from its venue: workshops, meetings and
    proceedings become conference publications (they used to be filed as
    journal articles); arXiv stays an article and is marked Submitted."""
    return venue_entrytype(venue)


def _gs_bibtex_id(pub: dict[str, Any], title: str) -> str:
    cluster = str(pub.get("cluster_id") or pub.get("id") or "")
    if cluster and cluster.isdigit():
        return "Scholar" + cluster
    return "Scholar" + re.sub(r"[^A-Za-z0-9]+", "", title)[:48]


def _gs_author_field(author: Any) -> str:
    """Scholar author list/string -> BibTeX 'A and B and C'.

    scholarly.search_pubs often returns bib.author as a list; str(list) would
    produce "['A', 'B']" in the BibTeX and corrupt CCV Authors fields.
    """
    if not author:
        return ""
    if isinstance(author, (list, tuple)):
        parts = [str(p).strip() for p in author if str(p).strip()]
    else:
        text = str(author).strip()
        if "..." in text:
            text = text.split("...")[0]
        parts = [p.strip() for p in text.split(",") if p.strip()]
    return " and ".join(parts)


def _gs_year(bib: dict[str, Any], pub: dict[str, Any]) -> str:
    """Best-effort year from a scholarly snippet (often missing)."""
    for key in ("year", "pub_year", "pubyear"):
        for src in (bib, pub):
            raw = src.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            m = re.search(r"(19|20)\d{2}", text)
            if m:
                return m.group(0)
    venue = str(bib.get("venue") or pub.get("venue") or "")
    m = re.search(r"(19|20)\d{2}", venue)
    return m.group(0) if m else ""


def _pub_to_bibtex(pub: dict[str, Any]) -> str | None:
    """Build a minimal BibTeX entry from a scholarly search_pubs snippet."""
    bib = pub.get("bib") or pub
    title = str(bib.get("title") or pub.get("title") or "").strip()
    author = _gs_author_field(bib.get("author") or pub.get("author"))
    year = _gs_year(bib if isinstance(bib, dict) else {}, pub)
    venue = str(bib.get("venue") or pub.get("venue") or "").strip()
    if not title or not author:
        return None
    # Year is required for CCV/NSERC; skip yearless Scholar rows (ADS covers most).
    if not year:
        return None
    entry_type = _gs_entrytype(venue)
    key = _gs_bibtex_id(pub, title)
    lines = [f"@{entry_type}{{{key},", f"  author = {{{author}}},",
             f"  title = {{{title}}},"]
    if venue and not is_truncated_text(venue):  # Scholar cuts venues with "…"
        field = "booktitle" if entry_type == "inproceedings" else "journal"
        lines.append(f"  {field} = {{{venue}}},")
    lines.append(f"  year = {{{year}}},")
    url = str(pub.get("eprint_url") or pub.get("pub_url") or "")
    if url.lower().startswith(("http://", "https://")):  # not javascript:void(0)
        lines.append(f"  url = {{{url}}},")
        if "arxiv.org" in url.lower() and normalize_arxiv(url.rsplit("/", 1)[-1]):
            lines.append(f"  eprint = {{{normalize_arxiv(url.rsplit('/', 1)[-1])}}},")
    lines.append("}")
    return "\n".join(lines)


def fetch_google_scholar(author_query: str, max_pubs: int = 200, timeout: int = 45) -> tuple[list[str], str]:
    """Return (bibtex_blocks, status_message).

    Uses scholarly.search_pubs, which returned results from this host while
    search_author did not.  The scrape is flaky (Google throttles/blocking),
    so failures degrade gracefully instead of aborting the run.
    """
    from scholarly import scholarly  # installed into the venv

    blocks: list[str] = []
    try:
        old = _timeout(timeout)
        try:
            search = scholarly.search_pubs(f'author:"{author_query}"')
            for _ in range(max_pubs):
                try:
                    pub = next(search)
                except StopIteration:
                    break
                text = _pub_to_bibtex(dict(pub))
                if text and text not in blocks:
                    blocks.append(text)
        finally:
            _cancel_timeout(old)
    except TimeoutError:
        return blocks, f"Google Scholar timed out after {timeout}s ({len(blocks)} fetched)"
    except Exception as exc:  # noqa: BLE001 - Scholar errors are unpredictable
        return blocks, f"Google Scholar failed: {type(exc).__name__}: {exc}"
    if not blocks:
        return blocks, f"Google Scholar returned no publications for {author_query!r}"
    return blocks, f"Google Scholar: {len(blocks)} publications"


# ---------------------------------------------------------------------------
# Template injection: make real CCV exports buildable.
# ---------------------------------------------------------------------------


# Title-like field per publication type, used to detect empty records.
_TITLE_FIELD_BY_LABEL = {
    "Journal Articles": "Article Title",
    "Conference Publications": "Publication Title",
    "Book Chapters": "Chapter Title",
}


def ensure_publication_templates(tree: ET.ElementTree) -> list[str]:
    """Add an empty template record for every managed publication type the
    base CCV is missing (e.g. Book Chapters).  Returns the labels added.

    Real exports routinely omit sections that hold no records; the upstream
    `ccv build` refuses to run without a template for each type.
    """
    fields_by_label = {
        "Journal Articles": schema.ARTICLE_FIELDS,
        "Conference Publications": schema.PROCEEDINGS_FIELDS,
        "Book Chapters": schema.CHAPTER_FIELDS,
    }
    root = tree.getroot()
    pubs = xmlutil.find_section(root, "Publications")
    if pubs is None:
        raise SystemExit("error: base CCV has no Publications section")

    present = {child.get("label") for child in xmlutil.child_sections(pubs)}
    added: list[str] = []
    for label in schema.MANAGED_PUBLICATION_LABELS:
        if label in present:
            continue
        section = ET.SubElement(pubs, xmlutil.child_tag(pubs, "section"))
        section.set("label", label)
        section.set("id", schema.SECTION_IDS[label])
        for field_name, field_id in fields_by_label[label].items():
            field = ET.SubElement(section, xmlutil.child_tag(section, "field"))
            field.set("label", field_name)
            field.set("id", field_id)
            if field_name in schema.LOV_FIELD_LABELS:
                ET.SubElement(field, xmlutil.child_tag(field, "lov"))
            else:
                value = ET.SubElement(field, xmlutil.child_tag(field, "value"))
                value.set("type", "String")
        added.append(label)
    return added


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NSERC-specific adaptations.
# ---------------------------------------------------------------------------
#
# NSERC rules (nserc-crsng.gc.ca, "How to complete NSERC's version of the
# Canadian Common CV" + the CCV FAQ):
#
#   1. HQP asterisk rule — every Highly Qualified Personnel (student /
#      postdoc) you supervised or co-supervised must be marked with an
#      asterisk in publication author lists.  The CCV convention is to append
#      " (*)" to the author name (e.g. "Carter, Sam (*)").
#
#   2. Six-year limit — NSERC validates the Contributions section back to
#      Jan 1 of the first permissible year (six years prior to the current
#      application year).  Use --last-years 6 to match this window.

_HQP_SECTION_HINTS = ("Supervisory Activities", "Students and Postdoctoral Fellows")


def load_trainees(base_tree: ET.ElementTree) -> list[Trainee]:
    """Collect supervised trainees (name, supervision start and end years)
    from the base CCV's Supervisory Activities / HQP section.

    The years let the HQP rule skip papers by namesakes written long before
    or after the supervision.
    """
    root = base_tree.getroot()
    trainees: dict[str, Trainee] = {}
    for section in xmlutil.iter_sections(root):
        label = (section.get("label") or "")
        if not any(hint.lower() in label.lower() for hint in _HQP_SECTION_HINTS):
            continue
        for record in xmlutil.child_sections(section):
            name = xmlutil.value_text(xmlutil.field_by_label(record, "Student Name"))
            if not name.strip():
                name = xmlutil.value_text(xmlutil.field_by_label(record, "Name"))
            name = name.strip()
            if not name:
                continue
            start = xmlutil.value_text(
                xmlutil.field_by_label(record, "Supervision Start Date")
            )
            m = re.match(r"(\d{4})", start.strip())
            year = int(m.group(1)) if m else None
            end = xmlutil.value_text(
                xmlutil.field_by_label(record, "Supervision End Date")
            )
            m = re.match(r"(\d{4})", end.strip())
            end_year = int(m.group(1)) if m else None
            previous = trainees.get(name)
            if previous is not None:
                # Same person supervised at several levels: span all of them.
                starts = [y for y in (previous.start_year, year) if y]
                ends = [y for y in (previous.end_year, end_year) if y]
                year = min(starts) if starts else None
                end_year = max(ends) if ends and len(ends) == 2 else None
            trainees[name] = Trainee(name, year, end_year)
    return list(trainees.values())


def _split_authors(text: str) -> list[str]:
    """Split a CCV author list into entries.

    Handles native CCV entries (",\n" separators with "&\n" before the last),
    web-import style (' and ' separators) and hand-typed ';' lists.
    """
    if ";" in text and ",\n" not in text:
        return [p.strip() for p in text.split(";") if p.strip()]
    return [p.strip() for p in re.split(r",\n|\band\b|&\n?", text) if p.strip()]


def _join_authors(original: str, parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if ";" in original and ",\n" not in original:
        return "; ".join(parts)
    if " and " in original and ",\n" not in original:
        return " and ".join(parts)  # keep web-import style
    return ",\n".join(parts[:-1]) + ",\n&\n" + parts[-1]


def _record_year(record) -> int | None:
    text = xmlutil.value_text(xmlutil.field_by_label(record, "Year")).strip()
    return int(text[:4]) if text[:4].isdigit() else None


def _hqp_changes(record, trainees) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """(new author list, [(author, trainee)] added, [author] unmarked) for one record."""
    field = xmlutil.field_by_label(record, "Authors")
    text = xmlutil.value_text(field)
    if not text:
        return [], [], []
    year = _record_year(record)
    out: list[str] = []
    added: list[tuple[str, str]] = []
    removed: list[str] = []
    for part in _split_authors(text):
        if part in ("...", "\u2026") or part.count(",") > 1:
            # Ellipsis, or a hand-typed "A, B, C, D" run we cannot split safely.
            out.append(part)
            continue
        if is_marked(part):
            # Stale marks (e.g. a former trainee's namesake) are removed.
            if find_trainee(unmark(part), trainees, year) is None:
                out.append(unmark(part))
                removed.append(part)
            else:
                out.append(part)
            continue
        hit = find_trainee(part, trainees, year)
        if hit is not None:
            out.append(f"{part} (*)")
            added.append((part, hit.name))
        else:
            out.append(part)
    return out, added, removed


def plan_hqp_marks(tree: ET.ElementTree, hqp_names, records=None) -> list[dict[str, str]]:
    """Report the '(*)' marks that would be added to and removed from *records*
    (default: every managed publication).  Read-only.

    *hqp_names* may be names or ccv.hqpmatch.Trainee objects.
    """
    trainees = [h if isinstance(h, Trainee) else Trainee(h) for h in hqp_names]
    marks: list[dict[str, str]] = []
    if not trainees:
        return marks
    if records is None:
        pubs = xmlutil.find_section(tree.getroot(), "Publications")
        records = [] if pubs is None else xmlutil.child_sections(pubs)
    for record in records:
        label = record.get("label")
        if label not in schema.MANAGED_PUBLICATION_LABELS:
            continue
        title = xmlutil.value_text(
            xmlutil.field_by_label(record, _TITLE_FIELD_BY_LABEL.get(label, "Article Title"))
        ).strip()
        _out, added, removed = _hqp_changes(record, trainees)
        for author, hqp in added:
            marks.append({"label": label, "title": title, "author": author,
                          "hqp": hqp, "action": "add"})
        for author in removed:
            marks.append({"label": label, "title": title, "author": author,
                          "hqp": "", "action": "remove"})
    return marks


def mark_hqp_authors(tree: ET.ElementTree, hqp_names, records=None) -> int:
    """Apply the NSERC HQP rule to *records* (default: all publications):
    append ' (*)' to trainees and remove '(*)' from authors who match no
    trainee.  Mutates the tree; returns the number of marks added.
    """
    trainees = [h if isinstance(h, Trainee) else Trainee(h) for h in hqp_names]
    if not trainees:
        return 0
    if records is None:
        pubs = xmlutil.find_section(tree.getroot(), "Publications")
        records = [] if pubs is None else xmlutil.child_sections(pubs)
    marked = 0
    for record in records:
        if record.get("label") not in schema.MANAGED_PUBLICATION_LABELS:
            continue
        field = xmlutil.field_by_label(record, "Authors")
        text = xmlutil.value_text(field)
        out, added, removed = _hqp_changes(record, trainees)
        if added or removed:
            xmlutil.set_value_text(field, _join_authors(text, out))
        marked += len(added)
    return marked


def fetch_ads_for_base_artefacts(
    base_tree: ET.ElementTree, token: str, surnames: tuple[str, ...]
) -> tuple[str, list[str]]:
    """ADS BibTeX for base-CV rows that look like Google Scholar artefacts."""
    pubs = xmlutil.find_section(base_tree.getroot(), "Publications")
    if pubs is None:
        return "", []
    titles: list[str] = []
    for record in xmlutil.child_sections(pubs):
        label = record.get("label")
        if label not in schema.MANAGED_PUBLICATION_LABELS:
            continue
        if _preserved_problem(record, surnames) or _record_is_scholar(record):
            title = xmlutil.value_text(xmlutil.field_by_label(record, _TITLE_FIELD_BY_LABEL[label]))
            if title.strip():
                titles.append(title.strip())
    if not titles:
        return "", []
    found = fetch_ads.lookup_titles(token, titles, surnames)
    docs = list({d["bibcode"]: d for d in found.values()}.values())
    if not docs:
        return "", [f"ADS lookup: none of {len(titles)} Scholar-artefact rows found"]
    text = fetch_ads.annotate_bibtex(
        fetch_ads.export_bibtex(token, [d["bibcode"] for d in docs]), docs
    )
    return text, [f"ADS lookup replaced Scholar-artefact row: {t[:70]}" for t in found]


def enrich_scholar_from_ads(
    scholar_text: str, ads_text: str, token: str, surnames: tuple[str, ...]
) -> tuple[str, str, list[str]]:
    """Replace Google Scholar snippets by their ADS records when ADS has them.

    Scholar search results carry abbreviated author lists and venues; the
    ADS record of the same paper has the full metadata.  Returns
    (extra ADS BibTeX, remaining Scholar BibTeX, report lines).
    """
    def parse(text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        parser = bparser.BibTexParser(common_strings=True)
        parser.ignore_nonstandard_types = False
        return list(parser.parse(text).get_entry_list())

    ads_entries = parse(ads_text)
    ads_keys = {k for e in ads_entries for k in entry_keys(e)}
    ads_titles = [clean_title(e) for e in ads_entries]
    scholar = parse(scholar_text)
    missing = [
        e for e in scholar
        if not (set(entry_keys(e)) & ads_keys)
        and not any(titles_equivalent(clean_title(e), t) for t in ads_titles)
    ]
    report: list[str] = []
    if not missing:
        return "", scholar_text, report
    found = fetch_ads.lookup_titles(token, [clean_title(e) for e in missing], surnames)
    replaced_titles = set(found)
    docs = list({d["bibcode"]: d for d in found.values()}.values())
    extra = ""
    if docs:
        extra = fetch_ads.annotate_bibtex(
            fetch_ads.export_bibtex(token, [d["bibcode"] for d in docs]), docs
        )
    for title in sorted(replaced_titles):
        report.append(f"Scholar -> ADS: {title[:70]}")
    remaining = [e for e in scholar if clean_title(e) not in replaced_titles]
    db = BibDatabase()
    db.entries = remaining
    writer = BibTexWriter()
    return extra, writer.write(db) if remaining else "", report


def strip_empty_templates(tree: ET.ElementTree) -> list[str]:
    """Remove injected empty template records left behind by --preserve-extra.

    When a base CCV lacks a managed section (e.g. Book Chapters), we inject an
    empty template so `replace_publications` can build records.  Under
    --preserve-extra that empty template has an empty dedupe key and is
    re-appended as a blank record.  Records that are real always have either a
    recordId (preserved from the base) or a filled title (rebuilt from
    BibTeX), so removing sections that have neither is safe.
    """
    root = tree.getroot()
    pubs = xmlutil.find_section(root, "Publications")
    if pubs is None:
        return []
    removed: list[str] = []
    for child in list(pubs):
        label = child.get("label")
        if label not in schema.MANAGED_PUBLICATION_LABELS:
            continue
        title_field = _TITLE_FIELD_BY_LABEL.get(label)
        title = xmlutil.value_text(xmlutil.field_by_label(child, title_field)).strip()
        if not child.get("recordId") and not title:
            pubs.remove(child)
            removed.append(label)
    return removed


def _read_bib_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}") from exc
    if not text.strip():
        raise SystemExit(f"error: BibTeX file {path} is empty")
    return text


def merge_bibtex(blocks: list[str], out_path: Path) -> int:
    """Write all *blocks* into one .bib file; return entry count."""
    text = "\n\n".join(b for b in blocks if b and b.strip())
    out_path.write_text(text + "\n", encoding="utf-8")
    return len(re.findall(r"@\w+", text))


# ---------------------------------------------------------------------------
# Name-mismatch safeguard.
# ---------------------------------------------------------------------------
# The base CCV records the owner's Family Name. --surname and the ADS/Scholar
# selectors must agree with it, or the run would import someone else's papers.


def detect_family_name(tree: ET.ElementTree) -> str:
    """Return the Family Name recorded in the base CCV (Personal Information)."""
    root = tree.getroot()
    personal = xmlutil.find_section(root, "Personal Information")
    if personal is None:
        return ""
    identification = xmlutil.find_section(personal, "Identification")
    if identification is None:
        return ""
    return xmlutil.value_text(
        xmlutil.field_by_label(identification, "Family Name")
    ).strip()


def _norm_name(raw: str) -> str:
    """Case- and accent-insensitive form of a name for comparison.

    'Martínez' and 'Martinez' compare equal.
    """
    decomposed = unicodedata.normalize("NFD", raw)
    ascii_ish = "".join(c for c in decomposed if not unicodedata.combining(c))
    return ascii_ish.lower()


def _author_selectors_mismatch(args: argparse.Namespace, family_name: str) -> list[str]:
    """Return human-readable mismatch messages, or [] when everything agrees."""
    fn = _norm_name(family_name)
    problems: list[str] = []

    # --surname (first/last authorship detection).
    surnames = [_norm_name(s) for s in args.surname.split(",") if s.strip()]
    if surnames and fn not in surnames:
        problems.append(
            f"--surname is {args.surname!r} but the base CCV Family Name is "
            f"{family_name!r} (used to mark first/last authorship)"
        )

    # --ads-author (ADS 'Surname, Initials' phrases).
    if args.ads_author:
        ads_surnames = [_norm_name(a.split(",", 1)[0])
                        for a in split_ads_authors(args.ads_author)]
        if ads_surnames and fn not in ads_surnames:
            problems.append(
                f"--ads-author {args.ads_author!r} searches surnames "
                f"{ads_surnames} but the base CCV Family Name is {family_name!r}"
            )

    # --ads-query (raw ADS query).  Only meaningful for author-style queries:
    # an orcid:/bibcode: query legitimately never mentions the surname.
    if args.ads_query and "author:" in args.ads_query.lower() \
            and fn not in _norm_name(args.ads_query):
        problems.append(
            f"--ads-query does not mention the base CCV Family Name "
            f"{family_name!r}: {args.ads_query!r}"
        )

    # --gs-author (Google Scholar name; check the surname appears).
    if args.gs_author and fn not in _norm_name(args.gs_author):
        problems.append(
            f"--gs-author {args.gs_author!r} does not contain the base CCV "
            f"Family Name {family_name!r}"
        )

    return problems


def check_name_mismatch(args: argparse.Namespace, base_tree: ET.ElementTree) -> list[str]:
    """Abort when --surname/--ads-*/--gs-* disagree with the base CCV Family Name.

    Returns the mismatch messages (empty when OK). Skipped entirely when
    --no-name-check is given or the CCV has no Family Name. Otherwise a
    mismatch prints to stderr and raises SystemExit.
    """
    if args.no_name_check:
        return []
    family_name = detect_family_name(base_tree)
    if not family_name:
        return []
    problems = _author_selectors_mismatch(args, family_name)
    if problems:
        print("error: name mismatch with base CCV — refusing to fetch "
              "(would risk writing someone else's publications)", file=sys.stderr)
        print(f"  base CCV Family Name: {family_name}", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("  If intentional, pass --no-name-check.", file=sys.stderr)
        raise SystemExit(2)
    return problems


def run(args: argparse.Namespace) -> int:
    base = Path(args.base).resolve()
    out = Path(args.out).resolve()
    if not base.exists():
        raise SystemExit(f"error: base CCV not found: {base}")

    # Abort early (before any network fetch) when --surname / --ads-* / --gs-*
    # disagree with the Family Name recorded in the base CCV.
    try:
        base_tree = xmlutil.load_ccv(base)
    except ET.ParseError as exc:
        raise SystemExit(f"error: {base} is not valid XML: {exc}") from exc
    check_name_mismatch(args, base_tree)

    sources: list[str] = []  # BibTeX blocks, ADS first (richer metadata wins dedupe)
    statuses: list[str] = []

    # ---- NASA ADS ---------------------------------------------------------
    if args.ads_bib:
        sources.append(_read_bib_text(Path(args.ads_bib)))
        statuses.append(f"ADS (file): {args.ads_bib}")
    elif args.ads_author or args.ads_orcid or args.ads_query or args.ads_bibcodes:
        ads_authors = split_ads_authors(args.ads_author) if args.ads_author else None
        if args.ads_author and not ads_authors:
            raise SystemExit(f"error: --ads-author {args.ads_author!r} contains no names")
        token = args.ads_token or os.environ.get("ADS_API_TOKEN")
        if not token:
            raise SystemExit(
                "error: ADS retrieval needs an API token: set ADS_API_TOKEN or pass "
                "--ads-token (ADS > Settings > API Token).\n"
                "       Alternatively provide an existing export with --ads-bib FILE."
            )
        fd, tmp = tempfile.mkstemp(suffix=".bib", prefix="ads-")
        os.close(fd)
        try:
            info = fetch_ads.fetch_bibtex_file(
                tmp,
                token=token,
                authors=ads_authors,
                orcid=args.ads_orcid,
                bibcodes=[b.strip() for b in args.ads_bibcodes.split(",")] if args.ads_bibcodes else None,
                query=args.ads_query,
                max_rows=args.ads_max,
                since_year=args.ads_since_year,
            )
            if info["bibcodes"] == 0:
                statuses.append("ADS (API): 0 papers matched; check --ads-author/--ads-orcid spelling")
            else:
                sources.append(_read_bib_text(Path(tmp)))
                statuses.append(f"ADS (API): {info['bibcodes']} papers")
        except fetch_ads.AdsError as exc:
            raise SystemExit(f"error: {exc}") from exc
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ---- Google Scholar ---------------------------------------------------
    scholar_texts: list[str] = []
    if args.gs_bib:
        scholar_texts.append(_read_bib_text(Path(args.gs_bib)))
        statuses.append(f"Google Scholar (file): {args.gs_bib}")
    if args.gs_author:
        blocks, message = fetch_google_scholar(args.gs_author, args.gs_max, args.gs_timeout)
        if blocks:
            scholar_texts.append("\n\n".join(blocks))
        statuses.append(message)
    surnames = tuple(s.strip() for s in args.surname.split(",") if s.strip())
    ads_token = args.ads_token or os.environ.get("ADS_API_TOKEN")
    for scholar_text in scholar_texts:
        if ads_token and not args.no_scholar_ads_lookup:
            # Scholar snippets have truncated authors/venues: swap in ADS records.
            try:
                extra, scholar_text, report = enrich_scholar_from_ads(
                    scholar_text, "\n\n".join(sources), ads_token, surnames
                )
            except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
                extra, report = "", [f"Scholar -> ADS lookup failed: {exc}"]
            if extra:
                sources.append(extra)
            statuses.extend(report)
        if scholar_text.strip():
            sources.append(scholar_text)

    if ads_token and args.preserve_extra and not args.no_scholar_ads_lookup:
        # Rows that earlier Scholar imports left on the CV (truncated authors or
        # venue) are replaced by their ADS records when ADS has them; otherwise
        # the build drops or repairs them.
        try:
            extra, report = fetch_ads_for_base_artefacts(
                xmlutil.load_ccv(base), ads_token, surnames
            )
        except Exception as exc:  # noqa: BLE001 - best-effort
            extra, report = "", [f"ADS lookup for Scholar artefacts failed: {exc}"]
        if extra:
            sources.append(extra)
        statuses.extend(report)

    if args.bib:
        sources.append(_read_bib_text(Path(args.bib)))
        statuses.append(f"extra (file): {args.bib}")

    if not sources:
        detail = " " + statuses[0] if statuses else ""
        raise SystemExit(
            "error: no publication sources yielded entries (use --ads-*, --gs-*, "
            "--ads-bib, --gs-bib, and/or --bib. See --help.)" + detail
        )

    merged = out.with_name(out.stem + ".sources.bib")
    entry_count = merge_bibtex(sources, merged)

    # ---- Build -------------------------------------------------------------
    tree = xmlutil.load_ccv(base)
    injected = ensure_publication_templates(tree)

    entries = bibtex_io.load_bibtex(merged)
    skipped: list[tuple[str, str]] = []

    def on_skip(entry: dict[str, Any], reason: str) -> None:
        key = entry.get("ID") or entry.get("title") or "?"
        skipped.append((str(key), reason))

    try:
        since_cutoff = builder.parse_since(args.since)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc
    if since_cutoff is None and args.last_years:
        since_cutoff = builder.since_from_years(args.last_years)

    trainees = []
    if args.hqp_names:
        trainees = trainees_from_names(args.hqp_names.split(","))
    elif args.hqp_from_base:
        trainees = load_trainees(xmlutil.load_ccv(base))

    result = publications.replace_publications(
        tree,
        entries,
        author_surnames=surnames,
        since=since_cutoff,
        assign_record_ids=args.assign_record_ids,
        overrides=builder.load_overrides(args.overrides),
        preserve_extra=args.preserve_extra,
        fill_percentage=not args.no_percentage,
        on_skip=on_skip if (args.verbose or args.preserve_extra) else None,
        trainees=trainees,
        drop_unverified_scholar=args.drop_unverified_scholar,
    )
    built_marks = result["hqp_marks"]
    kept_records = result["kept_records"]

    if args.hqp_dry_run:
        # Preview only: report exactly which authors would be marked, then stop
        # before writing the output file.
        if not trainees:
            print("HQP dry run: no supervised names loaded (use --hqp-names or "
                  "--hqp-from-base); nothing would be marked")
        else:
            kept_marks = plan_hqp_marks(tree, trainees, records=kept_records)
            adds = [m for m in kept_marks if m["action"] == "add"]
            removes = [m for m in kept_marks if m["action"] == "remove"]
            print(f"HQP dry run: {len(built_marks) + len(adds)} author mark(s) would be "
                  f"added and {len(removes)} stale mark(s) removed (matching "
                  f"{len(trainees)} supervised name(s)); output NOT written")
            for m in built_marks + adds:
                print(f"  + {m['author']} (*)  -- matches supervised name {m['hqp']!r}")
                print(f"      in: {m['title'] or '(untitled)'}")
            for m in removes:
                print(f"  - {m['author']}  -- matches no supervised name; '(*)' removed")
                print(f"      in: {m['title'] or '(untitled)'}")
        print(f"Note: merged BibTeX still written to {merged}; CCV output, "
              "and --validate/--summarize are skipped in dry-run mode")
        return 0

    if trainees:
        # Rebuilt records were marked from full BibTeX names; fix kept rows.
        stale = [m for m in plan_hqp_marks(tree, trainees, records=kept_records)
                 if m["action"] == "remove"]
        marked = len(built_marks) + mark_hqp_authors(tree, trainees, records=kept_records)
        if marked:
            print(f"HQP asterisks added: {marked} author mark(s)")
        for m in stale:
            print(f"HQP stale mark removed: {m['author']} in {m['title'][:60]}")

    stripped = strip_empty_templates(tree)
    if stripped:
        print(f"Removed empty templates: {', '.join(stripped)}")
    xmlutil.write_ccv(tree, out)

    # ---- Report -------------------------------------------------------------
    print(f"Merged BibTeX:      {merged} ({entry_count} entries)")
    for status in statuses:
        print(f"  source: {status}")
    if injected:
        print(f"Added missing templates: {', '.join(injected)}")
    counts = result["publication_counts"]
    print(f"Wrote:              {out}")
    print(f"Publications: {sum(counts.values())} "
          f"(journal {counts.get('Journal Articles', 0)}, "
          f"conference {counts.get('Conference Publications', 0)}, "
          f"book chapters {counts.get('Book Chapters', 0)})")
    print(f"Changes: added {len(result['added'])}, updated {len(result['updated'])}"
          f"{', kept ' + str(len(result['kept'])) if args.preserve_extra else ''}, "
          f"removed {len(result['removed'])}")
    if result["duplicates"]:
        print(f"Duplicates dropped: {len(result['duplicates'])}")
    for title, reason in result.get("dropped_preserved", []):
        print(f"Dropped from CV: {title[:70]} ({reason})")
    if result.get("scholar_dropped"):
        print(f"Scholar entries dropped (owner not in truncated author list): "
              f"{len(result['scholar_dropped'])} (use -v for details, "
              "rerun without --drop-unverified-scholar to keep)")
    if skipped:
        print(f"Skipped: {len(skipped)} entry/entries")
        if args.verbose:
            for key, reason in skipped:
                print(f"  skip: {key}: {reason}")

    # ---- Post-build checks --------------------------------------------------
    if args.validate or args.summarize:
        tree = xmlutil.load_ccv(out)
        if args.summarize:
            summary = validate.summarize_tree(tree)
            print("Summary:")
            for key in sorted(summary):
                if key.startswith("_"):
                    continue
                print(f"  {summary[key]:4d}  {key}")
        if args.validate:
            issues = validate.validate_publications(tree, surnames)
            if issues:
                print(f"Validation: {len(issues)} issue(s) found:")
                for issue in issues[: args.validate_max]:
                    print(f"  [{issue['label']}] {issue['message']}")
                if len(issues) > args.validate_max:
                    print(f"  ... and {len(issues) - args.validate_max} more")
                if args.strict:
                    return 1
            else:
                print("Validation: no issues found in the Publications section")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccv-update",
        description="Fetch your publications from NASA ADS + Google Scholar, "
                    "merge them, and build an updated Canadian Common CV XML.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base", required=True, help="Existing CCV XML export (the structural base)")
    parser.add_argument("--out", required=True, help="Output CCV XML path")
    parser.add_argument("--surname", required=True,
                        help="Comma-separated surnames used to detect first/last "
                        "authorship (the run aborts if it disagrees with the "
                        "base CCV Family Name)")
    parser.add_argument("--no-name-check", action="store_true",
                        help="Allow --surname/--ads-*/--gs-* to disagree with "
                        "the base CCV Family Name (default: abort on mismatch)")
    parser.add_argument("--since", default=None, help="Only include entries on/after YYYY or YYYY-MM")
    parser.add_argument("--overrides", type=Path, default=None,
                        help="YAML overrides file (invited/refereed/status/percentage rules)")
    parser.add_argument("--preserve-extra", action="store_true",
                        help="Keep base publications absent from the merged BibTeX instead of deleting")
    parser.add_argument("--no-percentage", action="store_true",
                        help="Leave Contribution Percentage blank (skip authorship "
                        "heuristic bands; fill Role only). Recommended when field "
                        "norms vary and you set %% by hand in the CCV UI.")
    parser.add_argument("--assign-record-ids", action="store_true",
                        help="Assign new recordId attributes to rebuilt records")
    parser.add_argument("--last-years", type=int, default=None,
                        help="NSERC-style window: keep only the last N years "
                        "(NSERC validates back to Jan 1 six years prior; use 6)")

    nserc = parser.add_argument_group("NSERC-specific")
    hqp = nserc.add_mutually_exclusive_group()
    hqp.add_argument("--hqp-names", default=None,
                     help="Comma-separated student/postdoc names to mark with "
                     "'(*)' in author lists (NSERC HQP rule)")
    hqp.add_argument("--hqp-from-base", action="store_true",
                     help="Read supervised-student names from the base CCV's "
                     "Supervisory Activities section and mark them '(*)'")
    nserc.add_argument("--hqp-dry-run", action="store_true",
                       help="Preview which authors would be marked '(*)' and "
                       "exit without writing the output file")

    ads = parser.add_argument_group("NASA ADS source (pick one: file or API)")
    ads.add_argument("--ads-bib", type=Path, default=None,
                     help="Existing ADS BibTeX export file")
    ads.add_argument("--ads-token", default=None, help="ADS API token (default: $ADS_API_TOKEN)")
    ads.add_argument("--ads-author", default=None,
                     help="ADS author phrase(s), e.g. 'Smith, J'. Multiple "
                     "surnames: 'Smith, Jones' (initials stay glued to "
                     "their surname).")
    ads.add_argument("--ads-orcid", default=None, help="ORCID iD, e.g. 0000-0001-0000-0000")
    ads.add_argument("--ads-bibcodes", default=None, help="Comma-separated ADS bibcodes")
    ads.add_argument("--ads-query", default=None,
                     help="Raw ADS search query (used only when --ads-author/"
                     "--ads-orcid/--ads-bibcodes are not given)")
    ads.add_argument("--ads-max", type=int, default=1000, help="Max papers to fetch from ADS")
    ads.add_argument("--ads-since-year", type=int, default=None, help="Keep only papers from this year onward")

    gs = parser.add_argument_group("Google Scholar source")
    gs.add_argument("--gs-bib", type=Path, default=None,
                    help="Scholar export file (My Library -> Export -> BibTeX). Reliable; recommended.")
    gs.add_argument("--gs-author", default=None,
                    help="Scholar author name to scrape (best-effort, subject to throttling)")
    gs.add_argument("--gs-max", type=int, default=200, help="Max publications to fetch from Scholar")
    gs.add_argument("--gs-timeout", type=int, default=45, help="Seconds before giving up on Scholar")
    gs.add_argument("--no-scholar-ads-lookup", action="store_true",
                    help="Do not replace Scholar-only papers by their ADS records "
                    "(looked up by title; needs an ADS token)")
    gs.add_argument("--drop-unverified-scholar", action="store_true",
                    help="Drop Scholar snippets, and preserved Scholar rows, whose "
                    "truncated author list lacks your surname (default: keep them "
                    "and report them with --validate)")

    parser.add_argument("--bib", type=Path, default=None, help="Any extra local .bib file to include")
    parser.add_argument("--validate", action="store_true", help="Validate the output Publications section")
    parser.add_argument("--validate-max", type=int, default=25, help="Max validation issues to print")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero when --validate finds issues")
    parser.add_argument("--summarize", action="store_true", help="Print section counts of the output")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
