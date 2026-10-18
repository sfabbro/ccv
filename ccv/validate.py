"""Validation and Discovery-oriented summary of a CCV document."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import xmlutil
from .schema import MANAGED_PUBLICATION_LABELS

_TITLE_FIELD_BY_LABEL = {
    "Journal Articles": "Article Title",
    "Conference Publications": "Publication Title",
    "Book Chapters": "Chapter Title",
}

_REQUIRED_TEXT_FIELDS = {
    "Journal Articles": ("Article Title", "Authors", "Year", "Journal"),
    "Conference Publications": ("Publication Title", "Authors", "Year", "Conference Name"),
    "Book Chapters": ("Chapter Title", "Authors", "Year", "Book Title"),
}

_REQUIRED_LOV_FIELDS = {
    "Journal Articles": ("Contribution Role", "Refereed?"),
    "Conference Publications": (
        "Contribution Role",
        "Refereed?",
    ),
    "Book Chapters": ("Contribution Role", "Refereed?"),
}


def iter_publication_records(tree):
    """Yield (label, section_element) for every managed publication record.

    In CCV exports each record is a direct child <section> of the
    Publications section, labelled by its publication type.
    """
    root = tree.getroot()
    publications = xmlutil.find_section(root, "Publications")
    if publications is None:
        return
    for child in xmlutil.child_sections(publications):
        label = child.get("label")
        if label in MANAGED_PUBLICATION_LABELS:
            yield label, child


def validate_publications(tree, surnames: tuple[str, ...] = ()) -> list[dict[str, str]]:
    """Return a list of issues found in the Publications section.

    Each issue: {"label", "title", "field", "message"}.  Besides missing
    required fields, flags data-quality problems reviewers would see: the
    CV owner absent from the author list, truncated ("…") venues, links
    that are not http(s), and preprints marked refereed or published.
    """
    issues: list[dict[str, str]] = []

    def add(label: str, title: str, field_name: str, message: str) -> None:
        issues.append({"label": label, "title": title, "field": field_name,
                       "message": f"{label}: '{title}' {message}"})

    for label, record in iter_publication_records(tree):
        title_field = _TITLE_FIELD_BY_LABEL[label]
        title = xmlutil.value_text(xmlutil.field_by_label(record, title_field))
        authors = _record_value(record, "Authors")
        if surnames and authors and not any(
            s.lower() in authors.lower() for s in surnames
        ):
            add(label, title, "Authors", "does not list you among the authors")
        venue_field = "Journal" if label == "Journal Articles" else (
            "Conference Name" if label == "Conference Publications" else "Book Title")
        venue = _record_value(record, venue_field)
        if "\u2026" in venue or venue.rstrip().endswith("..."):
            add(label, title, venue_field, f"has a truncated {venue_field!r}: {venue!r}")
        url = _record_value(record, "URL").strip()
        if url and not url.lower().startswith(("http://", "https://")):
            add(label, title, "URL", f"has an invalid URL {url!r}")
        if label == "Journal Articles" and "arxiv" in venue.lower():
            if _record_lov(record, "Refereed?") == "Yes":
                add(label, title, "Refereed?", "is an arXiv preprint marked refereed")
            if _record_lov(record, "Publishing Status") == "Published":
                add(label, title, "Publishing Status",
                    "is an arXiv preprint marked Published (use Submitted)")
        for field_name in _REQUIRED_TEXT_FIELDS[label]:
            value = xmlutil.value_text(xmlutil.field_by_label(record, field_name))
            if not value.strip():
                issues.append(
                    {
                        "label": label,
                        "title": title,
                        "field": field_name,
                        "message": f"{label}: '{title}' is missing required field {field_name!r}",
                    }
                )
        for field_name in _REQUIRED_LOV_FIELDS[label]:
            field = xmlutil.field_by_label(record, field_name)
            label_now = xmlutil.lov_label(field)
            if not label_now:
                issues.append(
                    {
                        "label": label,
                        "title": title,
                        "field": field_name,
                        "message": f"{label}: '{title}' has no value set for {field_name!r}",
                    }
                )
    return issues


def _record_value(record, field_name) -> str:
    return xmlutil.value_text(xmlutil.field_by_label(record, field_name))


def _record_lov(record, field_name) -> str:
    return xmlutil.lov_label(xmlutil.field_by_label(record, field_name))


def discovery_metrics(tree) -> dict[str, Any]:
    """Metrics of interest for an NSERC Discovery-style review."""
    metrics: dict[str, Any] = {
        "refereed_journal_articles": 0,
        "non_refereed_journal_articles": 0,
        "first_author_journal_articles": 0,
        "last_author_journal_articles": 0,
        "refereed_conference_publications": 0,
        "invited_conference_publications": 0,
        "accepted_or_in_press": 0,
        "by_year": {},
    }
    current_year = datetime.now().year
    for label, record in iter_publication_records(tree):
        year_text = _record_value(record, "Year")
        year = 0
        try:
            year = int(year_text)
        except (TypeError, ValueError):
            pass
        if year:
            metrics["by_year"][year] = metrics["by_year"].get(year, 0) + 1

        role = _record_lov(record, "Contribution Role")
        refereed = _record_lov(record, "Refereed?")
        status = _record_lov(record, "Publishing Status")
        invited = _record_lov(record, "Invited?")

        if status in ("Accepted", "In Press"):
            metrics["accepted_or_in_press"] += 1
        if label == "Journal Articles":
            if refereed == "Yes":
                metrics["refereed_journal_articles"] += 1
            else:
                metrics["non_refereed_journal_articles"] += 1
            if role == "First Listed Author":
                metrics["first_author_journal_articles"] += 1
            if role == "Last Author":
                metrics["last_author_journal_articles"] += 1
        if label == "Conference Publications":
            if refereed == "Yes":
                metrics["refereed_conference_publications"] += 1
            if invited == "Yes":
                metrics["invited_conference_publications"] += 1

    recent_start = current_year - 6  # same window as --last-years 6
    metrics["last_6_years"] = sum(
        n for year, n in metrics["by_year"].items() if year >= recent_start
    )
    return metrics


def summarize_tree(tree) -> dict[str, Any]:
    """Combine section counts with Discovery metrics for the summarize command."""
    summary = xmlutil.summarize(tree)
    summary["_discovery"] = discovery_metrics(tree)
    return summary
