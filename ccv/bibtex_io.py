"""BibTeX loading and field helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bibtexparser import bparser

from .schema import MONTH_NUMBERS
from .text import expand_journal, strip_latex


def load_bibtex(path: str | Path) -> list[dict[str, Any]]:
    parser = bparser.BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    with open(path, encoding="utf-8") as handle:
        database = parser.parse_file(handle)
    return list(database.get_entry_list())


def month_number(entry: dict[str, Any], default: int = 1) -> int:
    raw = entry.get("month", default)
    if isinstance(raw, int):
        return raw
    key = str(raw).strip().lower()
    if key.isdigit():
        return int(key)
    return MONTH_NUMBERS.get(key, default)


def parse_author_list(author_field: str) -> list[str]:
    """Split a BibTeX author field into individual author strings."""
    if not author_field:
        return []
    # BibTeX separates authors with " and "
    parts = [p.strip() for p in author_field.split(" and ")]
    return [p for p in parts if p]


def parse_name(raw: str) -> tuple[str, str]:
    """Parse one author into (last name, given names).

    Handles both BibTeX conventions:
      "Kavelaars, J. J."   -> ("Kavelaars", "J. J.")
      "J. J. Kavelaars"    -> ("Kavelaars", "J. J.")
    """
    raw = strip_latex(raw).strip()
    if not raw:
        return "", ""
    if "," in raw:
        parts = [p.strip() for p in raw.split(",")]
        return parts[0], (parts[1] if len(parts) > 1 else "")
    tokens = raw.split()
    if len(tokens) == 1:
        return raw, ""
    return tokens[-1], " ".join(tokens[:-1])


def format_author_name(raw: str) -> str:
    """Format one BibTeX author as 'Last, F. M.' for CCV Authors fields."""
    last, given = parse_name(raw)
    if not last:
        return ""
    initials: list[str] = []
    for token in given.split():
        token = token.strip()
        if not token:
            continue
        if token.endswith("."):
            initials.append(token)
        else:
            initials.append(token[0] + ".")
    return f"{last}, {' '.join(initials)}" if initials else last


def format_authors_for_ccv(entry: dict[str, Any], etal_after: int = 20) -> str:
    authors = [format_author_name(a) for a in parse_author_list(entry.get("author", ""))]
    authors = [a for a in authors if a]
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) > etal_after:
        head = authors[: etal_after - 1]
        return ",\n".join(head) + f",\n...\n{authors[-1]}"
    return ",\n".join(authors[:-1]) + f",\n&\n{authors[-1]}"


def contributor_count(entry: dict[str, Any]) -> int:
    return len(parse_author_list(entry.get("author", "")))


def is_author(raw: str, surnames: tuple[str, ...]) -> bool:
    """True if *raw* names one of *surnames* (exact word-boundary match)."""
    if not surnames:
        return False
    last, _ = parse_name(raw)
    last = last.lower().strip()
    if not last:
        return False
    for s in surnames:
        s = s.lower().strip()
        if not s:
            continue
        if re.search(r"(^|[\s\-])" + re.escape(s) + r"($|[\s\-])", last):
            return True
    return False


def author_position(entry: dict[str, Any], surnames: tuple[str, ...]) -> int | None:
    """Return 0 if the user is first author, -1 if last author, else None."""
    authors = parse_author_list(entry.get("author", ""))
    if not authors:
        return None
    if is_author(authors[0], surnames):
        return 0
    if len(authors) > 1 and is_author(authors[-1], surnames):
        return -1
    return None


def is_first_author(entry: dict[str, Any], surnames: tuple[str, ...]) -> bool:
    return author_position(entry, surnames) == 0


def clean_title(entry: dict[str, Any]) -> str:
    return strip_latex(entry.get("title", ""))


def journal_name(entry: dict[str, Any]) -> str:
    return strip_latex(expand_journal(entry.get("journal")))


def entry_key(entry: dict[str, Any]) -> str:
    """Stable identity for dedup: DOI first, then normalized title, then ID."""
    doi = str(entry.get("doi") or "").strip().lower().rstrip("/")
    if doi:
        return f"doi:{doi}"
    title = re.sub(r"[^a-z0-9]+", "", clean_title(entry).lower())
    if title:
        return f"title:{title}"
    ident = str(entry.get("ID") or "").strip()
    if ident:
        return f"id:{ident}"
    return ""


def dedupe_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Drop duplicate BibTeX entries (same DOI/title), keeping the first."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    for entry in entries:
        key = entry_key(entry)
        label = entry.get("ID") or entry.get("title") or "?"
        if key and key in seen:
            skipped.append((str(label), f"duplicate of existing key {key}"))
            continue
        if key:
            seen.add(key)
        unique.append(entry)
    return unique, skipped
