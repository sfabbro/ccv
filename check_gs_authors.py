#!/usr/bin/env python3
"""Self-checks for Scholar author parsing and ADS↔Scholar title dedupe."""
from xml.etree import ElementTree as ET

from ccv import schema, xmlutil
from ccv.bibtex_io import (
    dedupe_entries,
    entry_has_surname,
    is_shortened_title,
    normalize_title_key,
    titles_equivalent,
)
from ccv.publications import replace_publications
from ccv.text import strip_latex
from ccv.update import _gs_author_field, _pub_to_bibtex

assert _gs_author_field(["S Fabbro", "K M Yi"]) == "S Fabbro and K M Yi"
assert _gs_author_field("A Smith, B Jones, ...") == "A Smith and B Jones"
block = _pub_to_bibtex(
    {"bib": {"title": "Demo", "author": ["S Fabbro", "T OBriain"], "year": "2024", "venue": "ApJ"}}
)
assert block is not None
assert "author = {S Fabbro and T OBriain}" in block
assert "['S Fabbro'" not in block
assert _pub_to_bibtex({"bib": {"title": "No Year", "author": ["A"]}}) is None

# ADS LaTeX Omega ↔ Scholar Unicode Ω
ads = strip_latex(r"Measurements of \ensuremath{\Omega} and \ensuremath{\Lambda} from 42")
sch = "Measurements of Ω and Λ from 42"
assert normalize_title_key(ads) == normalize_title_key(sch), (
    normalize_title_key(ads),
    normalize_title_key(sch),
)

kept, skipped = dedupe_entries(
    [
        {
            "ID": "ads1",
            "ENTRYTYPE": "article",
            "title": ads,
            "doi": "10.1086/307221",
            "year": "1999",
        },
        {"ID": "Scholar1", "ENTRYTYPE": "article", "title": sch, "year": "1999"},
    ]
)
assert len(kept) == 1 and len(skipped) == 1, (kept, skipped)

# Title-only match must clear the whole base-record key group (DOI+title),
# otherwise --preserve-extra would keep a duplicate.
NS = schema.NS
root = ET.Element(f"{{{NS}}}generic-cv")
pubs = ET.SubElement(root, f"{{{NS}}}section")
pubs.set("label", "Publications")
pubs.set("id", schema.SECTION_IDS["Publications"])


def _mk_record(label: str, title: str, doi: str = "", year: str = "2024") -> ET.Element:
    fields = {
        "Journal Articles": schema.ARTICLE_FIELDS,
        "Conference Publications": schema.PROCEEDINGS_FIELDS,
        "Book Chapters": schema.CHAPTER_FIELDS,
    }[label]
    title_field = {
        "Journal Articles": "Article Title",
        "Conference Publications": "Publication Title",
        "Book Chapters": "Chapter Title",
    }[label]
    rec = ET.SubElement(pubs, f"{{{NS}}}section")
    rec.set("label", label)
    rec.set("id", schema.SECTION_IDS[label])
    for fname, fid in fields.items():
        field = ET.SubElement(rec, f"{{{NS}}}field")
        field.set("label", fname)
        field.set("id", fid)
        value = ET.SubElement(field, f"{{{NS}}}value")
        value.set("type", "String")
        if fname == title_field:
            value.text = title
        elif fname == "DOI":
            value.text = doi
        elif fname == "Year":
            value.text = year
        elif fname == "Authors":
            value.text = "Other, A.\n&\nFabbro, S."
        elif fname == "Journal":
            value.text = "ApJ"
        elif fname == "Conference Name":
            value.text = "SPIE"
        elif fname == "Book Title":
            value.text = "Book"
    return rec


for label in schema.MANAGED_PUBLICATION_LABELS:
    _mk_record(label, "Template Only", year="")
_mk_record("Journal Articles", "Unique Paper", doi="10.1234/unique", year="2024")

tree = ET.ElementTree(root)
result = replace_publications(
    tree,
    [
        {
            "ID": "bib1",
            "ENTRYTYPE": "article",
            "title": "Unique Paper",
            "author": "A Other and S Fabbro",
            "year": "2024",
            "journal": "ApJ",
        }
    ],
    author_surnames=("Fabbro",),
    since=(2024, 1),
    preserve_extra=True,
)
assert len(result["updated"]) == 1, result
titles = [
    xmlutil.value_text(xmlutil.field_by_label(r, "Article Title"))
    for r in xmlutil.child_sections(pubs)
    if r.get("label") == "Journal Articles"
]
assert titles.count("Unique Paper") == 1, titles
assert all(t != "Template Only" for t in titles), titles

# New LOV nodes must be unprefixed, matching official CCV exports.
# Prefixed <generic-cv:lov> is dropped on import (Contribution Role came back blank).
field = ET.Element("field")
xmlutil.set_lov(field, "Co-Author", "00000000000000000000000100002102")
blob = ET.tostring(field, encoding="unicode")
assert "<lov " in blob and "generic-cv:lov" not in blob, blob

# Wording changes that used to leave the old CCV row beside the ADS row.
_EQUIV = [
    (
        "StarUnLink: identifying and mitigating signals from communication satellites in stellar spectral surveys",
        "StarUnLink: Identifying and mitigating signals from communications satellites in stellar spectral surveys",
    ),
    (
        "Dependence of Type Ia supernova luminosities on their local environment",
        "The Dependence of Type Ia Supernova Luminosities on Their Local Environment",
    ),
    (
        "The ESO's VLT type Ia supernova spectral set of the final two years of SNLS",
        "The ESO-VLT Type Ia supernova spectral set of the final two years of SNLS",
    ),
    (
        "The Canada-France Imaging Survey: Reconstructing the Milky Way Star Formation History from Its White Dwarf Population",
        "The Canada-France Imaging Survey: Reconstructing the Milky Way Star Formation History from its White Dwarf",
    ),
    (
        "The Astropy Project: Building an Open-science Project and Status of the v2.0 Core Package",
        "The Astropy Project: Building an inclusive, open-science project and status of the v2.0 core package",
    ),
    (
        "Toward a Cosmological Hubble Diagram for Type II-P Supernovae",
        "Toward a Cosmological Hubble Diagram for Type II-P Supernovae., 645 (2): 841–850",
    ),
]
for left, right in _EQUIV:
    assert titles_equivalent(left, right), (left, right)
assert not titles_equivalent(
    "CANFAR: the Canadian advanced network for astronomical research",
    "The Canadian Advanced Network For Astronomical Research",
)
assert not titles_equivalent(
    "Lensing the darkness: the matter density profile in cosmic voids from UNIONS",
    "Lensing without mass: The matter density profile in cosmic voids from UNIONS",
)
assert is_shortened_title(
    "Detecting ringed seal vocalizations using deep learning",
    "Detecting ringed seal vocalizations in multiple environments using deep learning",
)
assert not is_shortened_title(
    "An application of deep learning in the analysis of stellar spectra",
    "StarNet: An application of deep learning in the analysis of stellar spectra",
)
assert not titles_equivalent("mass estimates from ugriz", "masses estimates from ugriz")
assert entry_has_surname(
    {"author": "K Zammit and S Fabbro and W Halliday"}, ("Fabbro",)
)
assert not entry_has_surname({"author": "K Zammit and W Halliday"}, ("Fabbro",))

# A near-duplicate base title is replaced, not kept beside the new row.
_mk_record(
    "Journal Articles",
    "StarUnLink: Identifying and mitigating signals from communications satellites in stellar spectral surveys",
    year="2023",
)
_mk_record(
    "Journal Articles",
    "StarUnLink: identifying and mitigating signals from communication satellites in stellar spectral surveys",
    doi="10.1093/mnras/stad1889",
    year="2023",
)
_mk_record(
    "Journal Articles",
    "Detecting ringed seal vocalizations in multiple environments using deep learning",
    year="2024",
)
_mk_record("Conference Publications", "Conf Keep", year="2024")
_mk_record("Book Chapters", "Chapter Keep", year="2024")
result = replace_publications(
    tree,
    [
        {
            "ID": "ads-star",
            "ENTRYTYPE": "article",
            "title": "StarUnLink: identifying and mitigating signals from communication satellites in stellar spectral surveys",
            "author": "S Fabbro and A Other",
            "year": "2023",
            "journal": "MNRAS",
            "doi": "10.1093/mnras/stad1889",
        },
        {
            "ID": "seal-short",
            "ENTRYTYPE": "article",
            "title": "Detecting ringed seal vocalizations using deep learning",
            "author": "K Zammit and W Halliday",
            "year": "2026",
            "journal": "JASA Express",
        },
        {
            "ID": "seal-middle",
            "ENTRYTYPE": "article",
            "title": "Detecting ringed seal vocalizations in multiple environments",
            "author": "K Zammit and S Fabbro and W Halliday",
            "year": "2026",
            "journal": "JASA",
        },
    ],
    author_surnames=("Fabbro",),
    since=(2023, 1),
    preserve_extra=True,
)
titles = [
    xmlutil.value_text(xmlutil.field_by_label(r, "Article Title"))
    for r in xmlutil.child_sections(pubs)
    if r.get("label") == "Journal Articles"
]
assert titles.count("Unique Paper") == 1, titles
assert sum("StarUnLink" in t for t in titles) == 1, titles
assert not any(t.startswith("Detecting ringed seal vocalizations using deep") for t in titles)
assert any(t == "Detecting ringed seal vocalizations in multiple environments" for t in titles), titles
print("ok")
