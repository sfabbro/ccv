"""Build CCV Publications records from BibTeX entries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from . import xmlutil
from .bibtex_io import (
    author_position,
    clean_title,
    contributor_count,
    dedupe_entries,
    entry_key,
    format_authors_for_ccv,
    journal_name,
    month_number,
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
) -> None:
    known_fields = FIELDS_BY_ENTRYTYPE[entrytype]
    values = field_value_map(
        entry,
        entrytype=entrytype,
        author_surnames=author_surnames,
        overrides=overrides,
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
    """Stable identity of a CCV publication record, for change reporting."""
    label = record.get("label", "")
    title_field = _TITLE_FIELD_BY_LABEL.get(label, "Article Title")
    doi = xmlutil.value_text(xmlutil.field_by_label(record, "DOI")).strip().lower()
    if doi:
        return f"doi:{doi.rstrip('/')}"
    title = xmlutil.value_text(xmlutil.field_by_label(record, title_field))
    if title:
        import re

        return "title:" + re.sub(r"[^a-z0-9]+", "", title.lower())
    return ""


def replace_publications(
    tree,
    entries: list[dict[str, Any]],
    *,
    author_surnames: tuple[str, ...] = ("Fabbro",),
    since: tuple[int, int] | None = None,
    assign_record_ids: bool = False,
    overrides: Overrides | None = None,
    preserve_extra: bool = False,
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
    base_records: dict[str, list[tuple[Any, str]]] = {}
    for child in xmlutil.child_sections(publications):
        label = child.get("label")
        if label not in MANAGED_PUBLICATION_LABELS:
            continue
        if label not in templates:
            templates[label] = deepcopy(child)
            xmlutil.strip_record_id(templates[label])
        base_records.setdefault(label, []).append((child, record_key(child)))

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

    base_key_set = {
        label: {key for _, key in records if key} for label, records in base_records.items()
    }

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
        if not entry_passes_since(entry, since):
            if on_skip:
                on_skip(entry, "before --since cutoff")
            continue
        key = entry_key(entry)
        if key and key in base_key_set[label]:
            base_key_set[label].discard(key)
            updated.append(key or entry.get("ID") or "?")
        else:
            added.append(key or entry.get("ID") or "?")
        record = deepcopy(templates[label])
        fill_record(
            record,
            entry,
            entrytype=entrytype,
            author_surnames=author_surnames,
            overrides=overrides,
            assign_record_id=assign_record_ids,
        )
        publications.append(record)
        counts[label] += 1

    kept: list[str] = []
    removed: list[str] = []
    for label, records in base_records.items():
        for element, key in records:
            if key and key in base_key_set[label] or not key:
                # Not matched by the new BibTeX: keep (preserve-extra) or drop.
                if preserve_extra:
                    publications.append(element)
                    kept.append(key or "<unkeyed>")
                else:
                    removed.append(key or "<unkeyed>")
            # else: matched and replaced by a fresh record (counted as updated)
    return {
        "publication_counts": counts,
        "added": added,
        "updated": updated,
        "kept": kept,
        "removed": removed,
        "duplicates": [k for k, _ in dup_skips],
    }
