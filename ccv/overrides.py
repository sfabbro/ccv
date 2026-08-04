"""YAML overrides for the CCV build.

BibTeX cannot encode everything the CCV needs. The --overrides file supplies
the rest: invited-talk flags, refereed-status fixes for specific venues,
publishing status, conference publication type, per-paper contribution
percentage, and entries to skip entirely.

Example overrides.yaml:

    # Entries marked as invited talks (match on bibcode, DOI, or title).
    invited:
      - "2021LPICo2548.1000K"
      - "An invited review of the Kuiper belt"

    # Force refereed status for specific entries.
    refereed:
      - match: "2021LPICo2548.1000K"
        value: false

    # Venue rules: glob match on journal / booktitle / series.
    venue_refereed:
      - venue: "*Lunar and Planetary*"
        value: false
      - venue: "IAU Symposium*"
        value: true
      - venue: "ASP Conference Series*"
        value: true

    # Publishing status (Submitted / Accepted / In Press / Published).
    status:
      - match: "10.1051/0004-6361/2022"
        value: "In Press"

    # Conference publication type (Paper / Abstract / Poster).
    conference_type:
      - match: "AAS/Division for Planetary Sciences*"
        value: "Abstract"

    # Per-paper contribution percentage band.
    percentage:
      - match: "2021LPICo2548.1000K"
        value: "81-90"

    # Skip these entries entirely (match on bibcode/DOI/title).
    skip:
      - "The Astronomer's Telegram"

    # Default percentage bands by authorship position.
    percentage_defaults:
      first: "81-90"
      last: "71-80"
      co: "31-40"
      sole: "91-100"
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from . import schema

_VALID_STATUS = set(schema.PUBLISHING_STATUS_LOV_IDS)
_VALID_CONF_TYPE = set(schema.CONFERENCE_TYPE_LOV_IDS)
_VALID_PERCENTAGE = set(schema.CONTRIBUTION_PERCENTAGE_LOV_IDS)


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _entry_text(entry: dict[str, Any]) -> str:
    """All searchable text of a BibTeX entry, lowercased and normalized."""
    bits = [
        entry.get("ID", ""),
        entry.get("title", ""),
        entry.get("doi", ""),
        entry.get("bibcode", ""),
        entry.get("journal", ""),
        entry.get("booktitle", ""),
        entry.get("series", ""),
    ]
    return _norm(" ".join(str(b) for b in bits if b))


def _venue_text(entry: dict[str, Any]) -> str:
    return _norm(
        " ".join(
            str(entry.get(k) or "")
            for k in ("journal", "booktitle", "series", "organization")
            if entry.get(k)
        )
    )


class Overrides:
    """Lookup object wrapping a parsed overrides YAML document."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}

    @classmethod
    def load(cls, path: str | Path | None) -> "Overrides":
        if not path:
            return cls(None)
        with open(path, encoding="utf-8") as handle:
            return cls(yaml.safe_load(handle) or {})

    # -- helpers ---------------------------------------------------------

    def _first_hit(self, section: str, entry: dict[str, Any]) -> dict | None:
        rules = self.data.get(section) or []
        text = _entry_text(entry)
        for rule in rules:
            if isinstance(rule, str):
                if _norm(rule) in text:
                    return {"match": rule}
            elif isinstance(rule, dict) and _norm(str(rule.get("match") or "")) in text:
                return rule
        return None

    def _venue_first(self, section: str, entry: dict[str, Any]) -> dict | None:
        rules = self.data.get(section) or []
        venue = _venue_text(entry)
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            pat = str(rule.get("venue") or "")
            if not pat:
                continue
            if fnmatch.fnmatch(venue, _norm(pat)):
                return rule
            if _norm(pat) in venue:
                return rule
        return None

    # -- lookups ---------------------------------------------------------

    def skip(self, entry: dict[str, Any]) -> bool:
        return self._first_hit("skip", entry) is not None

    def invited(self, entry: dict[str, Any]) -> bool | None:
        """True/False from overrides, or None when unspecified."""
        if self._first_hit("invited", entry):
            return True
        # Heuristic: "invited" mentioned in title/note.
        haystack = _norm(
            f"{entry.get('title', '')} {entry.get('note', '')} {entry.get('series', '')}"
        )
        if "invited" in haystack:
            return True
        return None

    def refereed(self, entry: dict[str, Any]) -> bool | None:
        rule = self._first_hit("refereed", entry)
        if rule and "value" in rule:
            return bool(rule["value"])
        rule = self._venue_first("venue_refereed", entry)
        if rule and "value" in rule:
            return bool(rule["value"])
        return None

    def status(self, entry: dict[str, Any]) -> str | None:
        rule = self._first_hit("status", entry)
        if not rule:
            return None
        value = str(rule.get("value", ""))
        return value if value in _VALID_STATUS else None

    def conference_type(self, entry: dict[str, Any]) -> str | None:
        rule = self._first_hit("conference_type", entry)
        if not rule:
            return None
        value = str(rule.get("value", ""))
        return value if value in _VALID_CONF_TYPE else None

    def percentage(self, entry: dict[str, Any]) -> str | None:
        rule = self._first_hit("percentage", entry)
        if not rule:
            return None
        value = str(rule.get("value", ""))
        return value if value in _VALID_PERCENTAGE else None

    def open_access(self, entry: dict[str, Any]) -> bool | None:
        rule = self._first_hit("open_access", entry)
        if rule and "value" in rule:
            return bool(rule["value"])
        return None

    def percentage_defaults(self) -> dict[str, str]:
        defaults = dict(schema.PERCENTAGE_DEFAULTS)
        for key, value in (self.data.get("percentage_defaults") or {}).items():
            if key in defaults and value in _VALID_PERCENTAGE:
                defaults[key] = value
        return defaults


def load(overrides: "Overrides | str | Path | None") -> Overrides:
    if isinstance(overrides, Overrides):
        return overrides
    return Overrides.load(overrides)
