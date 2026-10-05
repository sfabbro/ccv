"""BibTeX loading and field helpers."""

from __future__ import annotations

import re
import unicodedata
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


def entry_has_surname(entry: dict[str, Any], surnames: tuple[str, ...]) -> bool:
    """True if any author is one of *surnames*, not only first or last."""
    return any(is_author(author, surnames) for author in parse_author_list(entry.get("author") or ""))


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


# Fold Greek letters / common LaTeX leftovers so ADS "Omega" matches Scholar "Ω".
_TITLE_FOLDS = (
    ("omega", "omega"),
    ("lambda", "lambda"),
    ("alpha", "alpha"),
    ("beta", "beta"),
    ("gamma", "gamma"),
    ("delta", "delta"),
    ("μ", "mu"),
    ("Ω", "omega"),
    ("ω", "omega"),
    ("Λ", "lambda"),
    ("λ", "lambda"),
    ("α", "alpha"),
    ("β", "beta"),
    ("γ", "gamma"),
    ("δ", "delta"),
)


def _title_text(title: str) -> str:
    text = strip_latex(title)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    for src, dst in _TITLE_FOLDS:
        text = text.replace(src, dst)
    return re.sub(r"ensuremath", "", text)


def normalize_title_key(title: str) -> str:
    """ASCII-ish title fingerprint for cross-source dedupe (ADS ↔ Scholar)."""
    return re.sub(r"[^a-z0-9]+", "", _title_text(title))


def _title_words(title: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _title_text(title))
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1].isdigit():
        words.pop()
    return words


def titles_equivalent(a: str, b: str) -> bool:
    """True when two titles are the same paper under a small wording change.

    Matches a leading 'The', one inserted word ('inclusive', 'Population'),
    a trailing plural, or a volume/page tail glued onto the title
    ('..., 645 (2): 841-850'). An extra word at the front ('CANFAR:',
    'StarNet:') does not match: that is often a different record.
    """
    wa, wb = _title_words(a), _title_words(b)
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    if abs(len(wa) - len(wb)) == 1:
        short, long = (wa, wb) if len(wa) < len(wb) else (wb, wa)
        for i in range(1, len(long)):  # not a new first word
            if long[:i] + long[i + 1 :] == short:
                return True
        return False
    if len(wa) == len(wb):
        diffs = [(x, y) for x, y in zip(wa, wb) if x != y]
        if len(diffs) == 1:
            x, y = diffs[0]
            return x + "s" == y or y + "s" == x
    return False


def is_shortened_title(short: str, long: str, max_extra: int = 4) -> bool:
    """True when *short* is *long* with a few words dropped, same opening.

    'Detecting ringed seal vocalizations using deep learning' is the
    Scholar shortening of '... in multiple environments using deep learning'.
    """
    a, b = _title_words(short), _title_words(long)
    extra = len(b) - len(a)
    # One extra word is titles_equivalent (keep the incoming row). This is
    # only the case of several dropped words, and only when *short* is shorter.
    if len(a) < 6 or extra < 2 or extra > max_extra or a[:4] != b[:4]:
        return False
    i = 0
    for word in b:
        if i < len(a) and word == a[i]:
            i += 1
    return i == len(a)


def entry_key(entry: dict[str, Any]) -> str:
    """Primary identity: DOI if present, else normalized title, else ID."""
    keys = entry_keys(entry)
    return keys[0] if keys else ""


def entry_keys(entry: dict[str, Any]) -> list[str]:
    """All identities for one entry (DOI and title), for cross-source dedupe.

    ADS rows usually have a DOI; Scholar snippets rarely do. Indexing both
    keys means a Scholar title still collapses onto the earlier ADS row.
    """
    keys: list[str] = []
    doi = str(entry.get("doi") or "").strip().lower().rstrip("/")
    if doi:
        keys.append(f"doi:{doi}")
    title = normalize_title_key(clean_title(entry))
    if title:
        keys.append(f"title:{title}")
    if not keys:
        ident = str(entry.get("ID") or "").strip()
        if ident:
            keys.append(f"id:{ident}")
    return keys


def dedupe_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Drop duplicate BibTeX entries (same DOI or title), keeping the first."""
    seen: set[str] = set()
    accepted_titles: list[str] = []
    unique: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    for entry in entries:
        keys = entry_keys(entry)
        title = clean_title(entry)
        label = entry.get("ID") or entry.get("title") or "?"
        hit = next((k for k in keys if k in seen), None)
        if hit is None and any(titles_equivalent(title, prev) for prev in accepted_titles):
            hit = "title:~"
        if hit:
            skipped.append((str(label), f"duplicate of existing key {hit}"))
            continue
        for key in keys:
            seen.add(key)
        accepted_titles.append(title)
        unique.append(entry)
    return unique, skipped
