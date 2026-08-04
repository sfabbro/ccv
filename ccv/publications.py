"""Build CCV Publications records from BibTeX entries."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable

from . import xmlutil
from .bibtex_io import (
    author_position,
    clean_title,
    contributor_count,
    dedupe_entries,
    entry_keys,
    format_authors_for_ccv,
    journal_name,
    month_number,
    normalize_title_key,
    parse_name,
)
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
) -> dict[str, str | None]:
    """Map CCV field labels to string/LOV labels for one BibTeX entry."""
    n_contributors = contributor_count(entry)
    role, is_first, is_last = contribution_role(entry, author_surnames)
    position = 0 if is_first else (-1 if is_last else None)

    refereed = REFEREED_BY_ENTRYTYPE.get(entrytype, True)
    if overrides.refereed(entry) is not None:
        refereed = bool(overrides.refereed(entry))

    invited = overrides.invited(entry)
    invited = bool(invited) if invited is not None else False

    status = overrides.status(entry) or "Published"
    conf_type = overrides.conference_type(entry) or "Abstract"
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

    conf_name = entry.get("booktitle") or entry.get("journal") or ""
    conf_name = conf_name.replace("Abstract", "").strip()

    return {
        "Article Title": clean_title(entry),
        "Chapter Title": clean_title(entry),
        "Publication Title": clean_title(entry),
        "Book Title": entry.get("booktitle", ""),
        "Conference Name": conf_name,
        "Conference Location": "",
        "Published In": entry.get("series") or entry.get("booktitle") or "",
        "Journal": journal_name(entry),
        "Volume": entry.get("volume", ""),
        "Issue": entry.get("number", ""),
        "Page Range": entry.get("pages", ""),
        "Year": str(entry.get("year", "")),
        "Publisher": entry.get("publisher", ""),
        "Publication Location": "",
        "Description / Contribution Value": "",
        "DOI": entry.get("doi", "") or "",
        "URL": entry.get("adsurl") or entry.get("url") or "",
        "Authors": format_authors_for_ccv(entry),
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
) -> None:
    known_fields = FIELDS_BY_ENTRYTYPE[entrytype]
    values = field_value_map(
        entry,
        entrytype=entrytype,
        author_surnames=author_surnames,
        overrides=overrides,
        fill_percentage=fill_percentage,
    )
    xmlutil.strip_record_id(record)
    if assign_record_id:
        record.set("recordId", xmlutil.new_record_id())

    for field in xmlutil.fields_of(record):
        label = field.get("label")
        if label not in known_fields or label not in values:
            continue
        raw = values[label]
        if raw is None:
            # Drop template-copied percentage when --no-percentage.
            if label == "Contribution Percentage" and not fill_percentage:
                xmlutil.clear_lov(field)
            continue

        if label in LOV_FIELD_LABELS:
            if raw in LOV_IDS:
                xmlutil.set_lov(field, raw, LOV_IDS[raw])
            continue

        xmlutil.set_value_text(field, str(raw))


def entry_passes_since(entry: dict[str, Any], since: tuple[int, int] | None) -> bool:
    if since is None:
        return True
    year = int(entry.get("year") or 0)
    month = month_number(entry, default=1)
    return (year, month) >= since


def record_key(record) -> str:
    """Primary identity of a CCV publication record (DOI, else title)."""
    keys = record_keys(record)
    return keys[0] if keys else ""


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
    author_surnames: tuple[str, ...] = ("Fabbro",),
    since: tuple[int, int] | None = None,
    assign_record_ids: bool = False,
    overrides: Overrides | None = None,
    preserve_extra: bool = False,
    fill_percentage: bool = True,
    on_skip: Callable[[dict[str, Any], str], None] | None = None,
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

    entries, dup_skips = dedupe_entries(entries)
    for key, reason in dup_skips:
        if on_skip:
            on_skip({"ID": key}, reason)

    # key -> full key-set for the base record that owns it (so a title hit
    # also clears that record's DOI key, and vice versa).
    base_key_set: dict[str, set[str]] = {label: set() for label in MANAGED_PUBLICATION_LABELS}
    base_key_groups: dict[str, dict[str, frozenset[str]]] = {
        label: {} for label in MANAGED_PUBLICATION_LABELS
    }
    for label, records in base_records.items():
        for _element, keys in records:
            group = frozenset(k for k in keys if k)
            if not group:
                continue
            base_key_set[label].update(group)
            for k in group:
                base_key_groups[label][k] = group

    counts = {label: 0 for label in MANAGED_PUBLICATION_LABELS}
    added: list[str] = []
    updated: list[str] = []
    label_for_type = {
        "article": "Journal Articles",
        "inproceedings": "Conference Publications",
        "inbook": "Book Chapters",
    }
    for entry in entries:
        entrytype = entry.get("ENTRYTYPE", "").lower()
        label = label_for_type.get(entrytype)
        if label is None:
            if on_skip:
                on_skip(entry, f"unsupported ENTRYTYPE {entrytype!r}")
            continue
        if overrides.skip(entry):
            if on_skip:
                on_skip(entry, "excluded by --overrides skip rule")
            continue
        if not str(entry.get("year") or "").strip():
            if on_skip:
                on_skip(entry, "missing year (required for CCV/NSERC)")
            continue
        if not entry_passes_since(entry, since):
            if on_skip:
                on_skip(entry, "before --since cutoff")
            continue
        keys = entry_keys(entry)
        matched_group: frozenset[str] | None = None
        for k in keys:
            matched_group = base_key_groups[label].get(k)
            if matched_group is not None:
                break
        if matched_group is not None:
            for k in matched_group:
                base_key_set[label].discard(k)
                base_key_groups[label].pop(k, None)
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
        )
        publications.append(record)
        counts[label] += 1

    kept: list[str] = []
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
                    publications.append(element)
                    kept.append(keys[0] if keys else "<unkeyed>")
                else:
                    removed.append(keys[0] if keys else "<unkeyed>")
            # else: matched and replaced by a fresh record (counted as updated)
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
    }
