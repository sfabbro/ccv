"""High-level CCV build operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import xmlutil
from .bibtex_io import load_bibtex
from .overrides import Overrides, load as load_overrides
from .publications import replace_publications


def parse_since(value: str | None) -> tuple[int, int] | None:
    """Parse YYYY or YYYY-MM into (year, month)."""
    if not value:
        return None
    parts = value.strip().split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    return year, month


def since_from_years(last_years: int | None) -> tuple[int, int] | None:
    """Convert --last-years N into a (year, month) cutoff.

    N = 6 covers the current year plus the previous five, the window NSERC
    Discovery reviewers typically consider.
    """
    if not last_years or last_years <= 0:
        return None
    current = datetime.now().year
    return (current - last_years + 1, 1)


def build_from_base(
    base_path: str | Path,
    bib_path: str | Path,
    out_path: str | Path,
    *,
    author_surnames: tuple[str, ...] = ("Fabbro",),
    since: str | None = None,
    last_years: int | None = None,
    assign_record_ids: bool = False,
    overrides: Overrides | str | Path | None = None,
    preserve_extra: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Load *base_path*, replace publications from *bib_path*, write *out_path*."""
    tree = xmlutil.load_ccv(base_path)
    entries = load_bibtex(bib_path)
    skipped: list[tuple[str, str]] = []

    def on_skip(entry: dict[str, Any], reason: str) -> None:
        key = entry.get("ID") or entry.get("title") or "?"
        skipped.append((str(key), reason))

    cutoff = parse_since(since) or since_from_years(last_years)
    result = replace_publications(
        tree,
        entries,
        author_surnames=author_surnames,
        since=cutoff,
        assign_record_ids=assign_record_ids,
        overrides=load_overrides(overrides),
        preserve_extra=preserve_extra,
        on_skip=on_skip if (verbose or preserve_extra) else None,
    )
    xmlutil.write_ccv(tree, out_path)
    result.update(
        {
            "written": str(out_path),
            "bib_entries": len(entries),
            "skipped": skipped,
            "summary": xmlutil.summarize(tree),
        }
    )
    return result
