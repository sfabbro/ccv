#!/usr/bin/env python3
"""ccv-update — fetch papers from NASA ADS + Google Scholar and build an
updated Canadian Common CV (CCV) XML.

Part of the `ccv` package (originally based on https://github.com/ijiraq/CCV).
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
    pixi run ccv-update \\
        --base      CCV-export.xml \\
        --out       CCV-updated.xml \\
        --surname   Fabbro \\
        --ads-token "$ADS_API_TOKEN" --ads-author "Fabbro, S" \\
        --last-years 6 --hqp-from-base --preserve-extra --validate
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import signal
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Repo root when running from a source checkout (parent of the ccv/ package).
REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_ccv(repo: str | Path | None = None) -> Path:
    """Ensure the `ccv` package is importable; return the repo/source root used."""
    if repo:
        root = Path(repo).resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    try:
        import ccv  # noqa: F401
        import ccv.bibtex_io  # noqa: F401
        import ccv.fetch_ads  # noqa: F401
        import ccv.publications  # noqa: F401
        import ccv.schema  # noqa: F401
        import ccv.validate  # noqa: F401
        import ccv.xmlutil  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "error: ccv package is not importable — install with "
            "`pixi install` or `pip install -e .` "
            f"({exc})"
        ) from exc
    # Prefer an explicit --repo; otherwise the source tree next to this file
    # (editable installs) or the installed package location.
    if repo:
        return Path(repo).resolve()
    pkg_dir = Path(ccv.__file__).resolve().parent
    if (pkg_dir.parent / "pyproject.toml").exists():
        return pkg_dir.parent
    return pkg_dir.parent


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


def _gs_entrytype(_venue: str) -> str:
    # ponytail: treat arXiv/preprints as journal articles so they land in
    # Contributions; ceiling = NSERC may want these as "Submitted" — upgrade
    # via --overrides status rules when needed.
    return "article"


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
    if venue:
        lines.append(f"  journal = {{{venue}}},")
    lines.append(f"  year = {{{year}}},")
    if pub.get("eprint_url"):
        lines.append(f"  url = {{{pub['eprint_url']}}},")
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
    import ccv.schema as schema
    import ccv.xmlutil as xmlutil

    fields_by_label = {
        "Journal Articles": schema.ARTICLE_FIELDS,
        "Conference Publications": schema.PROCEEDINGS_FIELDS,
        "Book Chapters": schema.CHAPTER_FIELDS,
    }
    ns = schema.NS
    root = tree.getroot()
    pubs = xmlutil.find_section(root, "Publications")
    if pubs is None:
        raise SystemExit("error: base CCV has no Publications section")

    present = {child.get("label") for child in xmlutil.child_sections(pubs)}
    added: list[str] = []
    for label in schema.MANAGED_PUBLICATION_LABELS:
        if label in present:
            continue
        section = ET.SubElement(pubs, f"{{{ns}}}section")
        section.set("label", label)
        section.set("id", schema.SECTION_IDS[label])
        for field_name, field_id in fields_by_label[label].items():
            field = ET.SubElement(section, f"{{{ns}}}field")
            field.set("label", field_name)
            field.set("id", field_id)
            if field_name in schema.LOV_FIELD_LABELS:
                ET.SubElement(field, f"{{{ns}}}lov")
            else:
                value = ET.SubElement(field, f"{{{ns}}}value")
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
#      " (*)" to the author name (e.g. "Bialek, Spencer (*)").
#
#   2. Six-year limit — NSERC validates the Contributions section back to
#      Jan 1 of the first permissible year (six years prior to the current
#      application year).  Use --last-years 6 to match this window.

_HQP_SECTION_HINTS = ("Supervisory Activities", "Students and Postdoctoral Fellows")


def load_hqp_names(base_tree: ET.ElementTree) -> list[str]:
    """Collect supervised-student names from the base CCV (Student Name
    fields under the Supervisory Activities / HQP section).

    Returns full names as stored in the CV, e.g. "Ashley Ferreira".  These
    are used to apply the NSERC HQP asterisk rule to rebuilt publications.
    """
    import ccv.xmlutil as xmlutil

    root = base_tree.getroot()
    names: list[str] = []
    for section in xmlutil.iter_sections(root):
        label = (section.get("label") or "")
        if not any(hint.lower() in label.lower() for hint in _HQP_SECTION_HINTS):
            continue
        for record in xmlutil.child_sections(section):
            name = xmlutil.value_text(xmlutil.field_by_label(record, "Student Name"))
            if not name.strip():
                name = xmlutil.value_text(xmlutil.field_by_label(record, "Name"))
            if name.strip():
                names.append(name.strip())
    # de-dup, preserve order
    return list(dict.fromkeys(names))


def _name_parts(raw: str) -> tuple[str, str]:
    """Split a name into (surname, given) from either CCV convention:
    'Ferreira, Ashley' or 'Ashley Ferreira'."""
    raw = raw.strip()
    if "," in raw:
        last, _, given = raw.partition(",")
        return last.strip(), given.strip()
    tokens = raw.split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[-1], " ".join(tokens[:-1])


def _initial(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    return token[0].upper()


def _author_matches(author: str, hqp: str) -> bool:
    """True if *author* names the same person as *hqp* (surname + given
    initial), ignoring punctuation/case.  Author may carry '(*)' already."""
    clean = re.sub(r"\*\(\)|\*|\s+", " ", author).strip()
    a_last, a_given = _name_parts(clean)
    h_last, h_given = _name_parts(hqp)
    if not a_last or not h_last:
        return False
    if a_last.lower() != h_last.lower():
        return False
    if h_given and _initial(a_given) != _initial(h_given):
        return False
    return True


def _split_authors(text: str) -> list[str]:
    """Split a CCV author list into entries.

    Handles both conventions: native CCV entries (",\n" separators with "&\n"
    before the last) and web-import style (' and ' separators).
    """
    return [p.strip() for p in re.split(r",\n|\band\b|&\n?", text) if p.strip()]


def plan_hqp_marks(tree: ET.ElementTree, hqp_names: list[str]) -> list[dict[str, str]]:
    """Report which authors would gain ' (*)' under the NSERC HQP rule.

    Read-only: does not mutate *tree*.  Returns one dict per mark:
    {label, title, author, hqp} where *author* is the author string that would
    get ' (*)' appended and *hqp* is the supervised name it matched.
    """
    import ccv.schema as schema
    import ccv.xmlutil as xmlutil

    marks: list[dict[str, str]] = []
    if not hqp_names:
        return marks
    root = tree.getroot()
    pubs = xmlutil.find_section(root, "Publications")
    if pubs is None:
        return marks
    for record in xmlutil.child_sections(pubs):
        label = record.get("label")
        if label not in schema.MANAGED_PUBLICATION_LABELS:
            continue
        title_field = _TITLE_FIELD_BY_LABEL.get(label, "Article Title")
        title = xmlutil.value_text(xmlutil.field_by_label(record, title_field)).strip()
        field = xmlutil.field_by_label(record, "Authors")
        if field is None:
            continue
        text = xmlutil.value_text(field)
        if not text:
            continue
        for part in _split_authors(text):
            if "*" in part:  # already marked
                continue
            for hqp in hqp_names:
                if _author_matches(part, hqp):
                    marks.append({"label": label, "title": title,
                                  "author": part, "hqp": hqp})
                    break
    return marks


def mark_hqp_authors(tree: ET.ElementTree, hqp_names: list[str]) -> int:
    """Append ' (*)' to publication authors that match a supervised HQP name.

    Mutates the tree in place and returns the number of author marks added.
    """
    import ccv.schema as schema
    import ccv.xmlutil as xmlutil

    if not hqp_names:
        return 0
    root = tree.getroot()
    pubs = xmlutil.find_section(root, "Publications")
    if pubs is None:
        return 0
    marked = 0
    for record in xmlutil.child_sections(pubs):
        if record.get("label") not in schema.MANAGED_PUBLICATION_LABELS:
            continue
        field = xmlutil.field_by_label(record, "Authors")
        if field is None:
            continue
        text = xmlutil.value_text(field)
        if not text:
            continue
        parts = _split_authors(text)
        out: list[str] = []
        changed = False
        for part in parts:
            if "*" in part:  # already marked (e.g. "Name (*)" or "Name *")
                out.append(part)
                continue
            if any(_author_matches(part, h) for h in hqp_names):
                out.append(f"{part} (*)")
                changed = True
                marked += 1
            else:
                out.append(part)
        if changed:
            if len(out) == 1:
                xmlutil.set_value_text(field, out[0])
            elif " and " in text and ",\n" not in text:
                # Preserve web-import style rather than normalizing it.
                xmlutil.set_value_text(field, " and ".join(out))
            else:
                xmlutil.set_value_text(field, ",\n".join(out[:-1]) + ",\n&\n" + out[-1])
    return marked


def strip_empty_templates(tree: ET.ElementTree) -> list[str]:
    """Remove injected empty template records left behind by --preserve-extra.

    When a base CCV lacks a managed section (e.g. Book Chapters), we inject an
    empty template so `replace_publications` can build records.  Under
    --preserve-extra that empty template has an empty dedupe key and is
    re-appended as a blank record.  Records that are real always have either a
    recordId (preserved from the base) or a filled title (rebuilt from
    BibTeX), so removing sections that have neither is safe.
    """
    import ccv.schema as schema
    import ccv.xmlutil as xmlutil

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


def _split_ads_authors(raw: str) -> list[str]:
    """Delegate to ccv.fetch_ads.split_ads_authors (single implementation)."""
    from ccv.fetch_ads import split_ads_authors

    return split_ads_authors(raw)


def _read_bib_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
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
# The base CCV records the owner's Family Name.  --surname and the ADS/GS
# author selectors should agree with it; if they don't, the run is very likely
# fetching (and marking) someone else's publications — which is exactly what
# happened with the earlier Kavelaars-on-a-Fabbro run.


def detect_family_name(tree: ET.ElementTree) -> str:
    """Return the Family Name recorded in the base CCV (Personal Information)."""
    import ccv.xmlutil as xmlutil

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

    'Martínez' and 'Martinez' compare equal; so do 'Sébastien' and 'Sebastien'.
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
                        for a in _split_ads_authors(args.ads_author)]
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
    mismatch prints to stderr and raises SystemExit — this is the known
    failure mode that once fetched Kavelaars papers into a Fabbro CV.
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
    import ccv.bibtex_io as bibtex_io
    import ccv.builder as builder
    import ccv.fetch_ads as fetch_ads
    import ccv.publications as publications
    import ccv.validate as validate
    import ccv.xmlutil as xmlutil

    base = Path(args.base).resolve()
    out = Path(args.out).resolve()
    if not base.exists():
        raise SystemExit(f"error: base CCV not found: {base}")

    # Abort early (before any network fetch) when --surname / --ads-* / --gs-*
    # disagree with the Family Name recorded in the base CCV.
    check_name_mismatch(args, xmlutil.load_ccv(base))

    sources: list[str] = []  # BibTeX blocks, ADS first (richer metadata wins dedupe)
    statuses: list[str] = []

    # ---- NASA ADS ---------------------------------------------------------
    if args.ads_bib:
        sources.append(_read_bib_text(Path(args.ads_bib)))
        statuses.append(f"ADS (file): {args.ads_bib}")
    elif args.ads_author or args.ads_orcid or args.ads_query or args.ads_bibcodes:
        ads_authors = _split_ads_authors(args.ads_author) if args.ads_author else None
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
                # "Kavelaars, J" -> author:"Kavelaars, J"; several surnames
                # "Kavelaars, Gladman" -> author:"Kavelaars" OR author:"Gladman".
                # A naive split(",") on "Kavelaars, J" would emit author:"J"
                # and match thousands of unrelated papers whose (corrupted)
                # surname is the single letter "J" (see _split_ads_authors).
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
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ---- Google Scholar ---------------------------------------------------
    if args.gs_bib:
        sources.append(_read_bib_text(Path(args.gs_bib)))
        statuses.append(f"Google Scholar (file): {args.gs_bib}")
    if args.gs_author:
        blocks, message = fetch_google_scholar(args.gs_author, args.gs_max, args.gs_timeout)
        if blocks:
            sources.append("\n\n".join(blocks))
        statuses.append(message)

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

    surnames = tuple(s.strip() for s in args.surname.split(",") if s.strip())
    entries = bibtex_io.load_bibtex(merged)
    skipped: list[tuple[str, str]] = []

    def on_skip(entry: dict[str, Any], reason: str) -> None:
        key = entry.get("ID") or entry.get("title") or "?"
        skipped.append((str(key), reason))

    since_cutoff = builder.parse_since(args.since)
    if since_cutoff is None and args.last_years:
        since_cutoff = builder.since_from_years(args.last_years)

    result = publications.replace_publications(
        tree,
        entries,
        author_surnames=surnames,
        since=since_cutoff,
        assign_record_ids=args.assign_record_ids,
        overrides=builder.load_overrides(args.overrides),
        preserve_extra=args.preserve_extra,
        on_skip=on_skip if (args.verbose or args.preserve_extra) else None,
    )

    # NSERC HQP asterisk rule: mark supervised students/postdocs in author lists.
    hqp_names: list[str] = []
    if args.hqp_names:
        hqp_names = [n.strip() for n in args.hqp_names.split(",") if n.strip()]
    elif args.hqp_from_base:
        hqp_names = load_hqp_names(xmlutil.load_ccv(base))

    if args.hqp_dry_run:
        # Preview only: report exactly which authors would be marked, then stop
        # before writing the output file.
        if not hqp_names:
            print("HQP dry run: no supervised names loaded (use --hqp-names or "
                  "--hqp-from-base); nothing would be marked")
        else:
            marks = plan_hqp_marks(tree, hqp_names)
            print(f"HQP dry run: {len(marks)} author mark(s) would be added "
                  f"(matching {len(hqp_names)} supervised name(s)); output NOT written")
            for m in marks:
                print(f"  [{m['label']}] {m['author']} (*)  -- matches supervised "
                      f"name {m['hqp']!r}")
                print(f"      in: {m['title'] or '(untitled)'}")
        print(f"Note: merged BibTeX still written to {merged}; CCV output, "
              "marking, and --validate/--summarize are skipped in dry-run mode")
        return 0

    if hqp_names:
        marked = mark_hqp_authors(tree, hqp_names)
        if marked:
            print(f"HQP asterisks added: {marked} author mark(s)")

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
            issues = validate.validate_publications(tree)
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
    parser.add_argument("--repo", default=None,
                        help="Optional source tree to prepend on sys.path before "
                        "importing ccv (default: installed package)")
    parser.add_argument("--surname", default="Fabbro",
                        help="Comma-separated surnames used to detect first/last authorship; "
                        "warned against if it disagrees with the base CCV Family Name")
    parser.add_argument("--no-name-check", action="store_true",
                        help="Allow --surname/--ads-*/--gs-* to disagree with "
                        "the base CCV Family Name (default: abort on mismatch)")
    parser.add_argument("--since", default=None, help="Only include entries on/after YYYY or YYYY-MM")
    parser.add_argument("--overrides", type=Path, default=None,
                        help="YAML overrides file (invited/refereed/status/percentage rules)")
    parser.add_argument("--preserve-extra", action="store_true",
                        help="Keep base publications absent from the merged BibTeX instead of deleting")
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
                     help="ADS author phrase(s), e.g. 'Fabbro, S'. Multiple "
                     "surnames: 'Fabbro, Kavelaars' (initials stay glued to "
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
    _import_ccv(args.repo)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
