"""Build CCV Publications records from BibTeX entries."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable

from . import xmlutil
from .xmlutil import local_name
from .bibtex_io import (
    alphabetical_tail,
    arxiv_id,
    author_position,
    entry_venue,
    is_author,
    is_meeting_abstract,
    is_preprint,
    is_truncated_text,
    clean_title,
    entry_has_surname,
    contributor_count,
    dedupe_entries,
    entry_keys,
    format_authors_for_ccv,
    journal_name,
    month_number,
    is_shortened_title,
    normalize_title_key,
    parse_name,
    titles_equivalent,
    venue_entrytype,
)
from .hqpmatch import Trainee, find_trainee
from .text import canonical_journal, strip_latex
from .overrides import Overrides
from .schema import (
    FIELDS_BY_ENTRYTYPE,
    LOV_FIELD_LABELS,
    LOV_IDS,
    MANAGED_PUBLICATION_LABELS,
    PERCENTAGE_DEFAULTS,
    REFEREED_BY_ENTRYTYPE,
    ROLE_CO,
    ROLE_FIRST,
    ROLE_LAST,
)

_TITLE_FIELD_BY_LABEL = {
    "Journal Articles": "Article Title",
    "Conference Publications": "Publication Title",
    "Book Chapters": "Chapter Title",
}


def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"


def contribution_role(
    entry: dict[str, Any], author_surnames: tuple[str, ...]
) -> tuple[str, bool, bool]:
    """Return (role label, is_first, is_last) for one entry."""
    position = author_position(entry, author_surnames)
    if position == 0:
        return ROLE_FIRST, True, False
    if position == -1:
        return ROLE_LAST, False, True
    return ROLE_CO, False, False


def contribution_percentage(
    entry: dict[str, Any],
    *,
    position: int | None,
    n_contributors: int,
    defaults: dict[str, str],
) -> str:
    """Pick a CCV percentage band from authorship position heuristics."""
    if n_contributors <= 1:
        return defaults.get("sole", PERCENTAGE_DEFAULTS["sole"])
    if position == 0:
        return defaults.get("first", PERCENTAGE_DEFAULTS["first"])
    if position == -1:
        return defaults.get("last", PERCENTAGE_DEFAULTS["last"])
    return defaults.get("co", PERCENTAGE_DEFAULTS["co"])


def field_value_map(
    entry: dict[str, Any],
    *,
    entrytype: str,
    author_surnames: tuple[str, ...],
    overrides: Overrides,
    fill_percentage: bool = True,
    trainees: list[Trainee] | None = None,
    hqp_marks: list[dict[str, str]] | None = None,
) -> dict[str, str | None]:
    """Map CCV field labels to string/LOV labels for one BibTeX entry."""
    n_contributors = contributor_count(entry)
    role, is_first, is_last = contribution_role(entry, author_surnames)
    position = 0 if is_first else (-1 if is_last else None)

    refereed = REFEREED_BY_ENTRYTYPE.get(entrytype, True)
    # ADS knows which records are refereed; trust it over the entry type.
    ads_refereed = str(entry.get("adsrefereed") or "").strip().lower()
    if ads_refereed in ("yes", "no"):
        refereed = ads_refereed == "yes"
    preprint = is_preprint(entry)
    abstract = is_meeting_abstract(entry)
    if preprint or abstract:
        refereed = False
    if overrides.refereed(entry) is not None:
        refereed = bool(overrides.refereed(entry))

    invited = overrides.invited(entry)
    invited = bool(invited) if invited is not None else False

    # An arXiv-only record is not "Published"; NSERC accepts "Submitted".
    status = overrides.status(entry) or ("Submitted" if preprint else "Published")
    # Meeting abstracts are "Abstract"; a real conference paper is "Paper"
    # unless an override says otherwise. Defaulting every talk to Abstract
    # mislabels proceedings on the CV.
    conf_type = overrides.conference_type(entry) or ("Abstract" if abstract else "Paper")
    pct: str | None = None
    if fill_percentage:
        pct = overrides.percentage(entry)
        if not pct:
            pct = contribution_percentage(
                entry,
                position=position,
                n_contributors=n_contributors,
                defaults=overrides.percentage_defaults(),
            )

    open_access = overrides.open_access(entry)

    conf_name = strip_latex(entry.get("booktitle") or "") or journal_name(entry) or ""
    # ADS booktitles often end in "Abstracts". A raw replace of "Abstract"
    # turned that into "Meeting s".
    conf_name = re.sub(r"\s+abstracts?$", "", conf_name.strip(), flags=re.I).strip()
    conf_name = canonical_journal(conf_name)

    raw_journal = strip_latex(str(entry.get("journal") or ""))
    volume = str(entry.get("volume") or "")
    # ADS names the topical series "Physica Scripta Volume T" and puts 85 in
    # volume. The citation is Physica Scripta T85.
    if raw_journal.lower() == "physica scripta volume t" and volume.isdigit():
        volume = f"T{volume}"

    year_txt = str(entry.get("year") or "")
    year = int(year_txt) if year_txt.isdigit() else None
    title = clean_title(entry)

    def is_trainee(raw: str) -> bool:
        if not trainees:
            return False
        hit = find_trainee(raw, trainees, year)
        if hit is not None and hqp_marks is not None:
            hqp_marks.append({"title": title, "author": strip_latex(raw), "hqp": hit.name})
        return hit is not None

    authors = format_authors_for_ccv(
        entry,
        keep=lambda raw: is_author(raw, author_surnames),
        mark=is_trainee,
    )

    url = entry.get("adsurl") or entry.get("url") or ""
    if not str(url).lower().startswith(("http://", "https://")):
        url = ""  # Scholar snippets carry "javascript:void(0)"

    return {
        "Article Title": clean_title(entry),
        "Chapter Title": clean_title(entry),
        "Publication Title": clean_title(entry),
        "Book Title": entry.get("booktitle", ""),
        "Conference Name": conf_name,
        "Conference Location": "",
        "Published In": strip_latex(entry.get("series") or entry.get("booktitle") or ""),
        "Journal": journal_name(entry),
        "Volume": volume,
        "Issue": entry.get("number", ""),
        "Page Range": entry.get("pages", ""),
        "Year": str(entry.get("year", "")),
        "Publisher": entry.get("publisher", ""),
        "Publication Location": "",
        "Description / Contribution Value": "",
        "DOI": entry.get("doi", "") or "",
        "URL": url,
        "Authors": authors,
        "Editors": None,
        "Number of Contributors": str(n_contributors),
        "Funding Organization": "",
        "Publishing Status": status,
        "Conference Publication Type": conf_type,
        "Refereed?": _yes_no(refereed),
        "Open Access?": _yes_no(open_access) if open_access is not None else None,
        "Synthesis?": None,
        "Invited?": _yes_no(invited),
        "Contribution Role": role,
        "Description of Contribution Role": role,
        "Contribution Percentage": pct,
    }


def fill_record(
    record,
    entry: dict[str, Any],
    *,
    entrytype: str,
    author_surnames: tuple[str, ...],
    overrides: Overrides,
    assign_record_id: bool = False,
    fill_percentage: bool = True,
    trainees: list[Trainee] | None = None,
    hqp_marks: list[dict[str, str]] | None = None,
) -> None:
    known_fields = FIELDS_BY_ENTRYTYPE[entrytype]
    values = field_value_map(
        entry,
        entrytype=entrytype,
        author_surnames=author_surnames,
        overrides=overrides,
        fill_percentage=fill_percentage,
        trainees=trainees,
        hqp_marks=hqp_marks,
    )
    xmlutil.strip_record_id(record)
    if assign_record_id:
        record.set("recordId", xmlutil.new_record_id())

    # The record is a copy of an existing base record.  Every field this
    # entry does not set must be blanked, otherwise the template's values
    # leak into it (all rebuilt conference papers used to inherit the first
    # conference's "Conference Date 2024/6, Yokohama, Japan").
    for child in list(record):
        if local_name(child.tag) == "section":
            record.remove(child)
    for field in xmlutil.fields_of(record):
        label = field.get("label")
        if label == "Conference Date" and entrytype == "inproceedings":
            # Not in the schema map; use the meeting month ADS gives (year/month).
            year = str(entry.get("year") or "").strip()
            if year.isdigit() and entry.get("month"):
                xmlutil.set_typed_value(
                    field, f"{year}/{month_number(entry)}", "YearMonth", "yyyy/MM"
                )
            else:
                xmlutil.blank_field(field)
            continue
        raw = values.get(label) if label in known_fields else None
        if raw is None or raw == "":
            xmlutil.blank_field(field)
            continue
        if label in LOV_FIELD_LABELS:
            if raw in LOV_IDS:
                xmlutil.set_lov(field, raw, LOV_IDS[raw])
            else:
                xmlutil.blank_field(field)
            continue
        xmlutil.set_value_text(field, str(raw))


def entry_passes_since(entry: dict[str, Any], since: tuple[int, int] | None) -> bool:
    if since is None:
        return True
    raw = str(entry.get("year") or "").strip()
    if not raw.isdigit():
        return False
    month = month_number(entry, default=1)
    return (int(raw), month) >= since


def record_keys(record) -> list[str]:
    """DOI and/or title keys — same scheme as bibtex_io.entry_keys."""
    keys: list[str] = []
    doi = xmlutil.value_text(xmlutil.field_by_label(record, "DOI")).strip().lower()
    if doi:
        keys.append(f"doi:{doi.rstrip('/')}")
    label = record.get("label", "")
    title_field = _TITLE_FIELD_BY_LABEL.get(label, "Article Title")
    title = xmlutil.value_text(xmlutil.field_by_label(record, title_field))
    norm = normalize_title_key(title)
    if norm:
        keys.append(f"title:{norm}")
    url = xmlutil.value_text(xmlutil.field_by_label(record, "URL"))
    arxiv = arxiv_id({"doi": doi, "url": url})
    if arxiv:
        keys.append(f"arxiv:{arxiv}")
    return keys


def _ccv_author_position(authors_text: str, surnames: tuple[str, ...]) -> int | None:
    """Authorship position from a CCV Authors field (newline/&/, and separated)."""
    parts = [p.strip() for p in re.split(r",\n|\band\b|&\n?", authors_text or "") if p.strip()]
    cleaned: list[str] = []
    for part in parts:
        part = re.sub(r"\s*\(\*\)\s*|\*", "", part).strip().strip(",")
        if part and part not in {"&", "and", "..."}:
            cleaned.append(part)
    if not cleaned:
        return None

    def matches(author: str) -> bool:
        last = author.split(",", 1)[0].strip() if "," in author else parse_name(author)[0]
        return any(s.lower() == last.lower() for s in surnames)

    if matches(cleaned[0]):
        return 0
    if len(cleaned) > 1 and matches(cleaned[-1]):
        surnames_list = [
            (c.split(",", 1)[0] if "," in c else parse_name(c)[0]) for c in cleaned
        ]
        if len(cleaned) > 10 and alphabetical_tail(surnames_list):
            return None
        return -1
    return None


def fill_missing_contribution_fields(
    tree,
    author_surnames: tuple[str, ...],
    overrides: Overrides | None = None,
    *,
    fill_percentage: bool = True,
) -> int:
    """Fill empty Contribution Role (and optional Percentage) on preserved records.

    Base CCV exports often leave Role blank; NSERC cares more about role than
    about heuristic percentage bands.
    """
    overrides = overrides or Overrides()
    pubs = xmlutil.find_section(tree.getroot(), "Publications")
    if pubs is None:
        return 0
    filled = 0
    for record in xmlutil.child_sections(pubs):
        if record.get("label") not in MANAGED_PUBLICATION_LABELS:
            continue
        role_field = xmlutil.field_by_label(record, "Contribution Role")
        pct_field = xmlutil.field_by_label(record, "Contribution Percentage")
        n_field = xmlutil.field_by_label(record, "Number of Contributors")
        authors_txt = xmlutil.value_text(xmlutil.field_by_label(record, "Authors"))
        if n_field is not None and not xmlutil.value_text(n_field).strip() and authors_txt \
                and "..." not in authors_txt and "\u2026" not in authors_txt:
            names = [p for p in re.split(r",\n|\band\b|&\n?", authors_txt)
                     if p.strip() and p.strip() not in {"&", "and"}]
            if names:
                xmlutil.set_value_text(n_field, str(len(names)))
                filled += 1
        need_role = not xmlutil.lov_label(role_field)
        need_pct = fill_percentage and not xmlutil.lov_label(pct_field)
        if fill_percentage is False and pct_field is not None:
            xmlutil.clear_lov(pct_field)
        if not need_role and not need_pct:
            continue
        authors = xmlutil.value_text(xmlutil.field_by_label(record, "Authors"))
        position = _ccv_author_position(authors, author_surnames)
        n = max(1, len([p for p in re.split(r",\n|\band\b|&\n?", authors or "") if p.strip()]))
        if need_role and role_field is not None:
            if position == 0:
                role = ROLE_FIRST
            elif position == -1:
                role = ROLE_LAST
            else:
                role = ROLE_CO  # unknown → Co-Author
            xmlutil.set_lov(role_field, role, LOV_IDS[role])
            desc = xmlutil.field_by_label(record, "Description of Contribution Role")
            if desc is not None and not xmlutil.value_text(desc).strip():
                xmlutil.set_value_text(desc, role)
            filled += 1
        if need_pct and pct_field is not None:
            pct = contribution_percentage(
                {},
                position=position,
                n_contributors=n,
                defaults=overrides.percentage_defaults(),
            )
            if pct in LOV_IDS:
                xmlutil.set_lov(pct_field, pct, LOV_IDS[pct])
                filled += 1
    return filled


def replace_publications(
    tree,
    entries: list[dict[str, Any]],
    *,
    author_surnames: tuple[str, ...],
    since: tuple[int, int] | None = None,
    assign_record_ids: bool = False,
    overrides: Overrides | None = None,
    preserve_extra: bool = False,
    fill_percentage: bool = True,
    on_skip: Callable[[dict[str, Any], str], None] | None = None,
    trainees: list[Trainee] | None = None,
    drop_unverified_scholar: bool = False,
) -> dict[str, Any]:
    """Replace managed publication types in *tree* from BibTeX *entries*.

    Returns counts plus the lists of added / updated / kept / removed keys.
    """
    overrides = overrides or Overrides()
    root = tree.getroot()
    publications = xmlutil.find_section(root, "Publications")
    if publications is None:
        raise ValueError("Base CCV has no Publications section")

    templates: dict[str, Any] = {}
    base_records: dict[str, list[tuple[Any, list[str]]]] = {}
    for child in xmlutil.child_sections(publications):
        label = child.get("label")
        if label not in MANAGED_PUBLICATION_LABELS:
            continue
        if label not in templates:
            templates[label] = deepcopy(child)
            xmlutil.strip_record_id(templates[label])
        base_records.setdefault(label, []).append((child, record_keys(child)))

    missing = [label for label in MANAGED_PUBLICATION_LABELS if label not in templates]
    if missing:
        raise ValueError(
            "Base CCV is missing template records for: " + ", ".join(missing)
        )

    for child in list(publications):
        if child.get("label") in MANAGED_PUBLICATION_LABELS:
            publications.remove(child)

    entries = [dict(e) for e in entries]
    scholar_skips: list[tuple[dict[str, Any], str]] = []
    if drop_unverified_scholar:
        entries, scholar_skips = screen_scholar_entries(entries, author_surnames)
    for entry, reason in scholar_skips:
        if on_skip:
            on_skip(entry, reason)
    entries, dup_skips = dedupe_entries(entries)
    for key, reason in dup_skips:
        if on_skip:
            on_skip({"ID": key}, reason)

    def record_title(record) -> str:
        title_field = _TITLE_FIELD_BY_LABEL.get(record.get("label", ""), "Article Title")
        return xmlutil.value_text(xmlutil.field_by_label(record, title_field))

    # Scholar sometimes stores a shortened title and drops the surname.
    # Keep the fuller record already on the CV or earlier in the bib.
    kept_entries: list[dict[str, Any]] = []
    base_titles = [
        record_title(element)
        for records in base_records.values()
        for element, _keys in records
    ]
    for entry in entries:
        title = clean_title(entry)
        if not entry_has_surname(entry, author_surnames) and (
            any(is_shortened_title(title, other) for other in base_titles)
            or any(is_shortened_title(title, clean_title(other)) for other in kept_entries)
        ):
            if on_skip:
                on_skip(entry, "shortened title of an existing paper; surname absent")
            continue
        kept_entries.append(entry)
    entries = kept_entries

    # Keys still belonging to a base row. A title hit clears that row's DOI too.
    base_key_set: dict[str, set[str]] = {label: set() for label in MANAGED_PUBLICATION_LABELS}
    for label, records in base_records.items():
        for _element, keys in records:
            group = frozenset(k for k in keys if k)
            if group:
                base_key_set[label].update(group)

    counts = {label: 0 for label in MANAGED_PUBLICATION_LABELS}
    added: list[str] = []
    updated: list[str] = []
    label_for_type = {
        "article": "Journal Articles",
        "inproceedings": "Conference Publications",
        "inbook": "Book Chapters",
    }
    hqp_marks: list[dict[str, str]] = []
    for entry in entries:
        entrytype = effective_entrytype(entry)
        label = label_for_type.get(entrytype)
        if label is None:
            if on_skip:
                on_skip(entry, f"unsupported ENTRYTYPE {entrytype!r}")
            continue
        if overrides.skip(entry):
            if on_skip:
                on_skip(entry, "excluded by --overrides skip rule")
            continue
        if not str(entry.get("year") or "").strip().isdigit():
            if on_skip:
                on_skip(entry, "missing or non-numeric year (required for CCV/NSERC)")
            continue
        if not entry_passes_since(entry, since):
            if on_skip:
                on_skip(entry, "before --since cutoff")
            continue
        keys = entry_keys(entry)
        entry_title = clean_title(entry)
        # Find every base row that is this paper, including a second copy
        # whose title differs by one word, in *any* publication section: a
        # conference paper re-imported as a journal article (or vice versa)
        # used to survive next to its new copy.
        hits: list[tuple[str, Any, frozenset]] = []
        for base_label, records in base_records.items():
            for element, rec_keys in records:
                group = frozenset(k for k in rec_keys if k)
                if not group or not any(k in base_key_set[base_label] for k in group):
                    continue
                same = any(k in group for k in keys) or titles_equivalent(
                    entry_title, record_title(element)
                )
                if same:
                    hits.append((base_label, element, group))
        # A Google Scholar snippet never replaces a row already on the CV, and
        # an arXiv preprint never replaces the published version of a paper.
        if hits and (
            is_scholar_entry(entry)
            or (is_preprint(entry) and not all(_record_is_preprint(e) for _l, e, _g in hits))
        ):
            if on_skip:
                on_skip(entry, "already on the CV (kept the existing record)")
            continue
        matched = bool(hits)
        for base_label, _element, group in hits:
            for k in group:
                base_key_set[base_label].discard(k)
        if matched:
            updated.append(keys[0] if keys else entry.get("ID") or "?")
        else:
            added.append(keys[0] if keys else entry.get("ID") or "?")
        record = deepcopy(templates[label])
        fill_record(
            record,
            entry,
            entrytype=entrytype,
            author_surnames=author_surnames,
            overrides=overrides,
            assign_record_id=assign_record_ids,
            fill_percentage=fill_percentage,
            trainees=trainees,
            hqp_marks=hqp_marks,
        )
        publications.append(record)
        counts[label] += 1

    kept: list[str] = []
    kept_records: list[Any] = []
    dropped_preserved: list[tuple[str, str]] = []
    removed: list[str] = []
    for label, records in base_records.items():
        for element, keys in records:
            still = [k for k in keys if k in base_key_set[label]]
            if still or not keys:
                # Not matched by the new BibTeX: keep (preserve-extra) or drop.
                if preserve_extra:
                    # Drop preserved rows outside the NSERC window when --since set.
                    if since is not None:
                        year_txt = xmlutil.value_text(
                            xmlutil.field_by_label(element, "Year")
                        ).strip()
                        try:
                            year = int(year_txt)
                        except ValueError:
                            year = 0
                        if not year or (year, 1) < since:
                            removed.append(keys[0] if keys else "<unkeyed>")
                            continue
                    reason = _preserved_problem(element, author_surnames) if drop_unverified_scholar else ""
                    if reason:
                        removed.append(keys[0] if keys else "<unkeyed>")
                        dropped_preserved.append((record_title(element), reason))
                        continue
                    publications.append(element)
                    kept.append(keys[0] if keys else "<unkeyed>")
                    kept_records.append(element)
                else:
                    removed.append(keys[0] if keys else "<unkeyed>")
            # else: matched and replaced by a fresh record (counted as updated)
    # Preserved preprint/Scholar copies of a paper that is already on the CV
    # under its published title (any section) are duplicates.
    if kept_records:
        final_titles = [
            (record_title(r), r) for r in xmlutil.child_sections(publications)
            if r.get("label") in MANAGED_PUBLICATION_LABELS
        ]
        for element in list(kept_records):
            if not (_record_is_preprint(element) or _record_is_scholar(element)):
                continue
            title = record_title(element)
            twin = next((r for t2, r in final_titles if r is not element
                         and not _record_is_preprint(r)
                         and (titles_equivalent(title, t2)
                              or normalize_title_key(title) == normalize_title_key(t2))), None)
            if twin is not None:
                publications.remove(element)
                kept_records.remove(element)
                dropped_preserved.append((title, "preprint/Scholar duplicate of a record on the CV"))
                final_titles = [(t2, r) for t2, r in final_titles if r is not element]
        for element in kept_records:
            _repair_preserved(element)
    if preserve_extra or not fill_percentage:
        fill_missing_contribution_fields(
            tree, author_surnames, overrides, fill_percentage=fill_percentage
        )
    return {
        "publication_counts": counts,
        "added": added,
        "updated": updated,
        "kept": kept,
        "removed": removed,
        "duplicates": [k for k, _ in dup_skips],
        "scholar_dropped": [str(e.get("ID") or "?") for e, _ in scholar_skips],
        "kept_records": kept_records,
        "dropped_preserved": dropped_preserved,
        "hqp_marks": hqp_marks,
    }


# ---------------------------------------------------------------------------
# Entry screening and type correction.
# ---------------------------------------------------------------------------


def is_scholar_entry(entry: dict[str, Any]) -> bool:
    """Entries produced by the Google Scholar scrape (see update._gs_bibtex_id)."""
    return str(entry.get("ID") or "").startswith("Scholar")


def screen_scholar_entries(
    entries: list[dict[str, Any]], author_surnames: tuple[str, ...]
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    """Drop or clean Google Scholar snippets that would put bad data on the CV.

    Scholar search results abbreviate long author lists (so the CV owner and
    the true contributor count are often missing) and truncate venues with
    "…".  Entries without the owner's surname are dropped; truncated venues
    are blanked so --validate flags them instead of importing "… Society of
    the …".  ADS look-ups in ccv.update replace most of these beforehand.
    """
    kept: list[dict[str, Any]] = []
    skipped: list[tuple[dict[str, Any], str]] = []
    for entry in entries:
        if not is_scholar_entry(entry):
            kept.append(entry)
            continue
        if not entry_has_surname(entry, author_surnames):
            skipped.append((entry, "Scholar entry without your surname (truncated "
                                   "author list); not found in ADS"))
            continue
        if is_truncated_text(entry.get("author")):
            skipped.append((entry, "Scholar entry with a truncated author list"))
            continue
        for key in ("journal", "booktitle"):
            if is_truncated_text(entry.get(key)):
                entry[key] = "arXiv" if "arxiv" in str(entry[key]).lower() else ""
        url = str(entry.get("url") or "")
        if url and not url.lower().startswith(("http://", "https://")):
            entry.pop("url", None)
        kept.append(entry)
    return kept, skipped


def effective_entrytype(entry: dict[str, Any]) -> str:
    """BibTeX type after fixing misfiled records.

    Meeting abstracts filed as journal articles (ADS doctype 'abstract',
    JASA A-pages, AAS abstracts) become conference publications; Scholar
    snippets are typed from their venue.
    """
    entrytype = str(entry.get("ENTRYTYPE", "")).lower()
    if entrytype == "article" and is_meeting_abstract(entry):
        if not entry.get("booktitle"):
            entry["booktitle"] = entry_venue(entry)
        return "inproceedings"
    if entrytype == "article" and is_scholar_entry(entry):
        guessed = venue_entrytype(entry_venue(entry))
        if guessed == "inproceedings" and not entry.get("booktitle"):
            entry["booktitle"] = entry_venue(entry)
        return guessed
    return entrytype


# ---------------------------------------------------------------------------
# Preserved (--preserve-extra) base rows: drop Scholar artefacts, repair rest.
# ---------------------------------------------------------------------------


def _venue_of(record) -> str:
    for name in ("Journal", "Conference Name", "Book Title"):
        value = xmlutil.value_text(xmlutil.field_by_label(record, name))
        if value:
            return value
    return ""


def _record_is_preprint(record) -> bool:
    venue = _venue_of(record).lower()
    return "arxiv" in venue or "e-print" in venue or "preprint" in venue


def _record_is_scholar(record) -> bool:
    url = xmlutil.value_text(xmlutil.field_by_label(record, "URL")).strip()
    return is_truncated_text(_venue_of(record)) or (
        bool(url) and not url.lower().startswith(("http://", "https://"))
    )


def _preserved_problem(record, surnames: tuple[str, ...]) -> str:
    """Why a preserved base row should be dropped ('' to keep it).

    Earlier Google Scholar imports left rows with an abbreviated author list
    that omits the CV owner and a truncated venue.  They misstate the paper
    and are dropped; ADS supplies the real record when it has it.
    """
    authors = xmlutil.value_text(xmlutil.field_by_label(record, "Authors"))
    has_owner = any(s.lower() in authors.lower() for s in surnames if s)
    if not has_owner and (_record_is_scholar(record) or _record_is_preprint(record)):
        return "Scholar artefact: truncated author list without you"
    return ""


def _repair_preserved(record) -> None:
    """Fix what can be fixed on a kept base row without new metadata."""
    url_field = xmlutil.field_by_label(record, "URL")
    url = xmlutil.value_text(url_field).strip()
    if url and not url.lower().startswith(("http://", "https://")):
        xmlutil.set_value_text(url_field, "")
    for name in ("Journal", "Conference Name"):
        field = xmlutil.field_by_label(record, name)
        value = xmlutil.value_text(field)
        if field is not None and is_truncated_text(value):
            # "arXiv preprint arXiv …" is still known to be arXiv; anything
            # else is blanked so --validate asks for the real venue.
            xmlutil.set_value_text(field, "arXiv" if "arxiv" in value.lower() else "")
    if record.get("label") == "Journal Articles" and _record_is_preprint(record):
        ref = xmlutil.field_by_label(record, "Refereed?")
        if ref is not None:
            xmlutil.set_lov(ref, "No", LOV_IDS["No"])
        status = xmlutil.field_by_label(record, "Publishing Status")
        if status is not None and xmlutil.lov_label(status) == "Published":
            xmlutil.set_lov(status, "Submitted", LOV_IDS["Submitted"])
