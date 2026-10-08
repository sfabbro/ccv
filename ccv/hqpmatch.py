"""Match publication authors to supervised trainees (NSERC HQP '(*)' rule).

The old rule compared surname + first initial on author strings that had
already been reduced to initials, so 'Murray, Calum' inherited the asterisk
of a former intern 'Christopher Murray'.  This module compares full given
names whenever both sides have them, accepts compound surnames, and only
marks papers from the year before supervision started onward.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .bibtex_io import parse_name
from .text import strip_latex

_MARK_RE = re.compile(r"\s*\(\*\)\s*|\s*\*\s*$")


def norm(text: str) -> str:
    """Lower-case, accent-free, punctuation-free form of a name fragment."""
    text = unicodedata.normalize("NFKD", strip_latex(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s\-]", "", text.lower())
    return " ".join(text.replace("-", " ").split())


# Papers from a trainee's project often appear after supervision ends; allow
# this many years before a namesake is assumed instead.
PUBLICATION_LAG_YEARS = 4


@dataclass(frozen=True)
class Trainee:
    name: str
    start_year: int | None = None
    end_year: int | None = None

    @property
    def tokens(self) -> list[str]:
        raw = self.name
        if "," in raw:  # "Surname, Given"
            last, _, given = raw.partition(",")
            return norm(given).split() + norm(last).split()
        return norm(raw).split()


def _given_compatible(author_given: str, trainee_given: list[str]) -> bool:
    a_tokens = norm(author_given).split()
    if not a_tokens or not trainee_given:
        # No given name to compare: too ambiguous to mark.
        return False
    a_first, t_first = a_tokens[0], trainee_given[0]
    if len(a_first) > 1 and len(t_first) > 1:
        # Full names on both sides: allow Chris/Christopher, not Calum/Christopher.
        return a_first.startswith(t_first) or t_first.startswith(a_first)
    return a_first[0] == t_first[0]


def author_matches(author: str, trainee: Trainee, year: int | None = None) -> bool:
    """True when *author* (BibTeX or CCV form, may carry '(*)') is *trainee*."""
    clean = _MARK_RE.sub(" ", author or "").strip().strip(",")
    if not clean or clean in ("...", "&"):
        return False
    last, given = parse_name(clean)
    surname = norm(last).split()
    tokens = trainee.tokens
    if not surname or len(tokens) < 1:
        return False
    if len(surname) > len(tokens) or tokens[-len(surname):] != surname:
        return False
    trainee_given = tokens[: len(tokens) - len(surname)]
    if not _given_compatible(given, trainee_given):
        return False
    if year and trainee.start_year and year < trainee.start_year - 1:
        return False
    if year and trainee.end_year and year > trainee.end_year + PUBLICATION_LAG_YEARS:
        return False
    return True


def find_trainee(author: str, trainees: list[Trainee], year: int | None = None) -> Trainee | None:
    for trainee in trainees:
        if author_matches(author, trainee, year):
            return trainee
    return None


def trainees_from_names(names: list[str]) -> list[Trainee]:
    return [Trainee(n.strip()) for n in names if n.strip()]


def is_marked(author: str) -> bool:
    return "*" in author


def unmark(author: str) -> str:
    return _MARK_RE.sub("", author).rstrip()
