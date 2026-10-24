"""Latex / BibTeX text cleanup for CCV string fields.

Accented characters are converted to proper Unicode (café stays café, not
cafe), which matters because author names on an official CV must be exact.
"""

from __future__ import annotations

import re

from .schema import JOURNAL_MACROS

# Order matters: longer / more specific replacements first.
_LATEX_REPLACEMENTS = [
    ("\\textasciitilde", "\u223c"),
    ("\\sim", "\u223c"),
    ("\\textless", "<"),
    ("\\textgreater", ">"),
    # ADS writes some dashes as U+2500 (box drawing), e.g. "Black Hole─Halo".
    ("\u2500", "\u2013"),
    ("\\textendash", "\u2013"),
    ("\\textemdash", "\u2014"),
    ("{\\textemdash}", "\u2014"),
    ("{\\textendash}", "\u2013"),
    ("{\\mdash}", "\u2014"),
    ("{\\ndash}", "\u2013"),
    ("\\mdash", "\u2014"),
    ("\\ndash", "\u2013"),
    ("\\textquotedblleft", "\u201c"),
    ("\\textquotedblright", "\u201d"),
    ("\\textquoteleft", "\u2018"),
    ("\\textquoteright", "\u2019"),
    ("\\dots", "\u2026"),
    ("\\ldots", "\u2026"),
    ("\\copyright", "\u00a9"),
    ("\\pounds", "\u00a3"),
    ("\\dag", "\u2020"),
    ("\\ddag", "\u2021"),
    ("\\S", "\u00a7"),
    ("\\P", "\u00b6"),
    ("\\&", "&"),
    ("{\\&}", "&"),
    ("\\%", "%"),
    ("\\#", "#"),
    ("\\_", "_"),
    ("\\$", "$"),
]

# Accent command -> {base letter -> unicode}. Covers Latin-1 / Latin Extended-A.
_ACCENT_TABLES = {
    "'": {
        "a": "\u00e1", "e": "\u00e9", "i": "\u00ed", "o": "\u00f3", "u": "\u00fa",
        "y": "\u00fd", "c": "\u0107", "l": "\u013a", "n": "\u0144", "r": "\u0155",
        "s": "\u015b", "z": "\u017a", "g": "\u01f5", "k": "\u1e31",
        "A": "\u00c1", "E": "\u00c9", "I": "\u00cd", "O": "\u00d3", "U": "\u00da",
        "Y": "\u00dd", "C": "\u0106", "L": "\u0139", "N": "\u0143", "R": "\u0154",
        "S": "\u015a", "Z": "\u0179", "G": "\u01f4", "K": "\u1e30",
    },
    "`": {
        "a": "\u00e0", "e": "\u00e8", "i": "\u00ec", "o": "\u00f2", "u": "\u00f9",
        "A": "\u00c0", "E": "\u00c8", "I": "\u00cc", "O": "\u00d2", "U": "\u00d9",
    },
    "^": {
        "a": "\u00e2", "e": "\u00ea", "i": "\u00ee", "o": "\u00f4", "u": "\u00fb",
        "c": "\u0109", "g": "\u011d", "h": "\u0125", "j": "\u0135", "s": "\u015d",
        "w": "\u0175", "y": "\u0177",
        "A": "\u00c2", "E": "\u00ca", "I": "\u00ce", "O": "\u00d4", "U": "\u00db",
        "C": "\u0108", "G": "\u011c", "H": "\u0124", "J": "\u0134", "S": "\u015c",
        "W": "\u0174", "Y": "\u0176",
    },
    '"': {
        "a": "\u00e4", "e": "\u00eb", "i": "\u00ef", "o": "\u00f6", "u": "\u00fc",
        "y": "\u00ff",
        "A": "\u00c4", "E": "\u00cb", "I": "\u00cf", "O": "\u00d6", "U": "\u00dc",
        "Y": "\u0178",
    },
    "~": {
        "a": "\u00e3", "n": "\u00f1", "o": "\u00f5", "i": "\u0129", "u": "\u0169",
        "A": "\u00c3", "N": "\u00d1", "O": "\u00d5", "I": "\u0128", "U": "\u0168",
    },
    "=": {
        "a": "\u0101", "e": "\u0113", "i": "\u012b", "o": "\u014d", "u": "\u016b",
        "A": "\u0100", "E": "\u0112", "I": "\u012a", "O": "\u014c", "U": "\u016a",
    },
    ".": {
        "a": "\u0227", "c": "\u010b", "e": "\u0117", "g": "\u0121", "i": "\u0131",
        "o": "\u022f", "z": "\u017c",
        "A": "\u0226", "C": "\u010a", "E": "\u0116", "G": "\u0120", "O": "\u022e",
        "Z": "\u017b",
    },
    "c": {
        "c": "\u00e7", "s": "\u015f", "t": "\u0163",
        "C": "\u00c7", "S": "\u015e", "T": "\u0162",
    },
    "u": {
        "a": "\u0103", "e": "\u0115", "o": "\u014f", "g": "\u011f",
        "A": "\u0102", "E": "\u0114", "O": "\u014e", "G": "\u011e",
    },
    "v": {
        "c": "\u010d", "d": "\u010f", "e": "\u011b", "l": "\u013e",
        "n": "\u0148", "r": "\u0159", "s": "\u0161", "t": "\u0165",
        "z": "\u017e", "g": "\u01e7",
        "C": "\u010c", "D": "\u010e", "E": "\u011a", "L": "\u013d",
        "N": "\u0147", "R": "\u0158", "S": "\u0160", "T": "\u0164",
        "Z": "\u017d", "G": "\u01e6",
    },
    "H": {
        "o": "\u0151", "u": "\u0171",
        "O": "\u0150", "U": "\u0170",
    },
    "r": {
        "a": "\u00e5", "A": "\u00c5",
    },
    "k": {
        "a": "\u0105", "e": "\u0119", "i": "\u012f", "o": "\u01eb", "u": "\u0173",
        "A": "\u0104", "E": "\u0118", "I": "\u012e", "O": "\u01ea", "U": "\u0172",
    },
}

# Standalone letter macros -> unicode.
_LETTER_MACROS = {
    "ss": "\u00df", "SS": "\u1e9e",
    "o": "\u00f8", "O": "\u00d8",
    "l": "\u0142", "L": "\u0141",
    "aa": "\u00e5", "AA": "\u00c5",
    "ae": "\u00e6", "AE": "\u00c6",
    "oe": "\u0153", "OE": "\u0152",
    "i": "\u0131", "j": "\u0237",
    "dj": "\u0111", "DH": "\u00d0",
    "th": "\u00fe", "TH": "\u00de",
}

# {\'e}, {\"o}, {\c{c}}, {\H{o}}, ...  and  \'e, \'e (two forms)
_ACCENT_BRACED_RE = re.compile(r"\{\\([`'\"^~=.uvHckr])(\{([^{}]*)\}|([^{}]))}")
# Symbol accents (\'e, \"o, \^a) may be followed directly by their letter.
_ACCENT_PLAIN_RE = re.compile(r"\\([`'\"^~=.])\s*([A-Za-z])")
# Letter accents (\v, \c, \r, ...) only count with a braced or space-separated
# single letter: a bare "\r" followed by letters is another command
# (\raisebox used to become "åisebox").
_ACCENT_LETTER_RE = re.compile(
    r"\\([uvHckr])(?:\{([A-Za-z])\}|\s+([A-Za-z])(?![A-Za-z]))"
)
# Layout / formatting commands whose arguments are dropped or unwrapped.
_DROP_WITH_ARG_RE = re.compile(r"\\(?:raisebox|vspace|hspace|kern|label)\s*\{[^{}]*\}")
_UNWRAP_RE = re.compile(
    r"\\(?:textit|textbf|textrm|textsc|textsf|texttt|emph|mathrm|mathit|mathbf|"
    r"mbox|text|it|bf|rm|em|sc)(?![A-Za-z])\s*"
)
# {\ss}, {\o}, \ss, \o, \AA ...
_LETTER_BRACED_RE = re.compile(r"\{\\([A-Za-z]{1,2})\}")
_LETTER_PLAIN_RE = re.compile(r"\\([A-Za-z]{2})(?![A-Za-z])")


def _replace_accent(match: re.Match[str]) -> str:
    accent = match.group(1)
    letter = (match.group(3) or match.group(4) or "").strip()
    table = _ACCENT_TABLES.get(accent, {})
    return table.get(letter, letter)


def _replace_plain_accent(match: re.Match[str]) -> str:
    accent = match.group(1)
    letter = match.group(2)
    table = _ACCENT_TABLES.get(accent, {})
    return table.get(letter, letter)


def _replace_letter_accent(match: re.Match[str]) -> str:
    accent = match.group(1)
    letter = match.group(2) or match.group(3) or ""
    table = _ACCENT_TABLES.get(accent, {})
    return table.get(letter, letter)


def _replace_letter(match: re.Match[str]) -> str:
    return _LETTER_MACROS.get(match.group(1), match.group(1))


# ADS `pub` names. Keys are the short forms BibTeX and older CCV rows use.
_CANONICAL_JOURNALS = {
    "astronomical journal": "The Astronomical Journal",
    "the astronomical journal": "The Astronomical Journal",
    "astrophysical journal": "The Astrophysical Journal",
    "the astrophysical journal": "The Astrophysical Journal",
    "astrophysical journal letters": "The Astrophysical Journal Letters",
    "the astrophysical journal letters": "The Astrophysical Journal Letters",
    "astrophysical journal supplement": "The Astrophysical Journal Supplement Series",
    "astrophysical journal supplement series": "The Astrophysical Journal Supplement Series",
    "the astrophysical journal supplement series": "The Astrophysical Journal Supplement Series",
    "planetary science journal": "The Planetary Science Journal",
    "the planetary science journal": "The Planetary Science Journal",
    "physica scripta": "Physica Scripta",
    "physica scripta volume t": "Physica Scripta",
    "acoustical society of america journal": "The Journal of the Acoustical Society of America",
    "the journal of the acoustical society of america": "The Journal of the Acoustical Society of America",
    "jasa express letters": "JASA Express Letters",
    "journal of astronomical telescopes": (
        "Journal of Astronomical Telescopes, Instruments, and Systems"
    ),
    "journal of astronomical telescopes, instruments, and systems": (
        "Journal of Astronomical Telescopes, Instruments, and Systems"
    ),
    "new worlds in astroparticle physics": (
        "New Worlds in Astroparticle Physics: "
        "Proceedings of the Fifth International Workshop"
    ),
    "new worlds in astroparticle physics: proceedings of the fifth international workshop": (
        "New Worlds in Astroparticle Physics: "
        "Proceedings of the Fifth International Workshop"
    ),
}


def expand_journal(name: str | None) -> str:
    if not name:
        return ""
    name = name.strip()
    return JOURNAL_MACROS.get(name, JOURNAL_MACROS.get(name.lower(), name))


def canonical_journal(name: str | None) -> str:
    """ADS publication name for a journal string.

    Short macro expansions (``Astrophysical Journal``) and arXiv labels
    become the name ADS stores in ``pub``. Unknown names are unchanged.
    """
    cleaned = re.sub(r"\s+", " ", (name or "")).strip()
    if not cleaned:
        return ""
    key = cleaned.lower()
    if key.startswith("arxiv"):
        return "arXiv e-prints"
    return _CANONICAL_JOURNALS.get(key, cleaned)


def strip_latex(text: str | None) -> str:
    """Remove common BibTeX/LaTeX markup from a field value.

    Accented letters are mapped to Unicode (e.g. {\\'e} -> é). Unknown
    commands are dropped and remaining braces/backslashes removed.
    """
    if not text:
        return ""
    out = text
    # Longest macro first: replacing "\apj" before "\apjl" would leave
    # "Astrophysical Journall" from a braced {\apjl}.
    for macro, expanded in sorted(
        JOURNAL_MACROS.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        out = out.replace(macro, expanded)
    out = _DROP_WITH_ARG_RE.sub("", out)
    for src, dst in _LATEX_REPLACEMENTS:
        out = out.replace(src, dst)

    out = _ACCENT_BRACED_RE.sub(_replace_accent, out)
    out = _ACCENT_PLAIN_RE.sub(_replace_plain_accent, out)
    out = _ACCENT_LETTER_RE.sub(_replace_letter_accent, out)
    out = _UNWRAP_RE.sub("", out)
    out = _LETTER_BRACED_RE.sub(_replace_letter, out)
    out = _LETTER_PLAIN_RE.sub(_replace_letter, out)
    # BibTeX uses "~" as a tie (J.~J.). Do this after \~n so the accent survives.
    out = out.replace("~", " ")

    # \ensuremath{\Omega} / \Omega → keep the letter name for title matching.
    out = re.sub(r"\\ensuremath\s*\{([^{}]+)\}", r"\1", out)
    out = re.sub(r"\\(Omega|Lambda|alpha|beta|gamma|delta|mu)\b", r"\1", out)

    # Math-mode delimiters and leftover braces/backslashes.
    out = out.replace("$", "")
    out = out.replace("{", "").replace("}", "")
    out = out.replace("\\", "")
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()
