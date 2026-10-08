"""Regression tests for the CV-cleaning fixes (one section per bug)."""

from __future__ import annotations

import datetime
from xml.etree import ElementTree as ET

import pytest

from ccv import builder, schema, xmlutil
from ccv.bibtex_io import (
    arxiv_id,
    author_position,
    entry_keys,
    format_authors_for_ccv,
    is_author,
    is_meeting_abstract,
    is_preprint,
    venue_entrytype,
)
from ccv.fetch_ads import annotate_bibtex
from ccv.hqpmatch import Trainee, author_matches
from ccv.publications import field_value_map, replace_publications
from ccv.overrides import Overrides
from ccv.text import strip_latex
from ccv.update import _pub_to_bibtex, mark_hqp_authors, plan_hqp_marks
from ccv.validate import validate_publications

NS = schema.NS
TITLE_FIELD = {
    "Journal Articles": "Article Title",
    "Conference Publications": "Publication Title",
    "Book Chapters": "Chapter Title",
}


def _tree():
    root = ET.Element(f"{{{NS}}}generic-cv")
    pubs = ET.SubElement(root, "section")
    pubs.set("label", "Publications")
    pubs.set("id", schema.SECTION_IDS["Publications"])
    return ET.ElementTree(root), pubs


def _record(pubs, label, title, *, authors="Other, A.,\n&\nFabbro, S.", year="2024",
            venue="ApJ", extra=None, record_id=None):
    fields = {
        "Journal Articles": schema.ARTICLE_FIELDS,
        "Conference Publications": schema.PROCEEDINGS_FIELDS,
        "Book Chapters": schema.CHAPTER_FIELDS,
    }[label]
    rec = ET.SubElement(pubs, "section")
    rec.set("label", label)
    rec.set("id", schema.SECTION_IDS[label])
    if record_id:
        rec.set("recordId", record_id)
    values = {TITLE_FIELD[label]: title, "Year": year, "Authors": authors,
              "Journal": venue, "Conference Name": venue, "Book Title": venue}
    values.update(extra or {})
    for name, fid in fields.items():
        field = ET.SubElement(rec, "field")
        field.set("label", name)
        field.set("id", fid)
        if name in schema.LOV_FIELD_LABELS:
            continue
        value = ET.SubElement(field, "value")
        value.set("type", "String")
        value.text = values.get(name, "")
    return rec


def _templates(pubs):
    for label in schema.MANAGED_PUBLICATION_LABELS:
        _record(pubs, label, "Template Only", year="", authors="")


def _records(pubs, label=None):
    return [r for r in xmlutil.child_sections(pubs)
            if r.get("label") in schema.MANAGED_PUBLICATION_LABELS
            and (label is None or r.get("label") == label)]


def _val(rec, name):
    return xmlutil.value_text(xmlutil.field_by_label(rec, name))


# 1. Long author lists keep the CV owner and trainees ------------------------

def test_long_author_list_keeps_owner_and_trainee():
    names = [f"Author{i:02d}, X." for i in range(40)]
    names[25] = "Fabbro, S\\'ebastien"
    names[31] = "Bialek, Spencer"
    entry = {"author": " and ".join(names)}
    text = format_authors_for_ccv(
        entry,
        keep=lambda raw: is_author(raw, ("Fabbro",)),
        mark=lambda raw: "Bialek" in raw,
    )
    parts = text.split(",\n")
    assert "Fabbro, S." in parts
    assert "Bialek, S. (*)" in parts
    assert parts[0] == "Author00, X." and text.endswith("&\nAuthor39, X.")
    assert text.count("...") == 3


def test_short_author_list_unchanged():
    entry = {"author": "A, B and Fabbro, S and C, D"}
    assert format_authors_for_ccv(entry) == "A, B.,\nFabbro, S.,\n&\nC, D."


# 2. Template fields do not leak into rebuilt records -------------------------

def test_conference_template_values_do_not_leak():
    tree, pubs = _tree()
    _templates(pubs)
    conf = _records(pubs, "Conference Publications")[0]
    date = ET.SubElement(conf, "field")
    date.set("label", "Conference Date")
    value = ET.SubElement(date, "value")
    value.set("format", "yyyy/MM")
    value.set("type", "YearMonth")
    value.text = "2024/6"
    city = ET.SubElement(conf, "field")
    city.set("label", "City")
    ET.SubElement(city, "value").text = "Yokohama"
    replace_publications(tree, [{
        "ID": "2012DPS....4421001F", "ENTRYTYPE": "inproceedings",
        "title": "Searching for KBO flyby targets", "author": "Fabbro, S. and Other, A.",
        "year": "2012", "booktitle": "AAS/Division for Planetary Sciences Meeting Abstracts",
    }], author_surnames=("Fabbro",))
    rec = _records(pubs, "Conference Publications")[0]
    assert _val(rec, "City") == ""
    assert xmlutil.field_by_label(rec, "Conference Date").find("value") is None


def test_conference_date_from_bibtex_month():
    tree, pubs = _tree()
    _templates(pubs)
    conf = _records(pubs, "Conference Publications")[0]
    date = ET.SubElement(conf, "field")
    date.set("label", "Conference Date")
    replace_publications(tree, [{
        "ID": "x", "ENTRYTYPE": "inproceedings", "title": "A talk", "month": "oct",
        "author": "Fabbro, S.", "year": "2012", "booktitle": "ADASS XXII",
    }], author_surnames=("Fabbro",))
    rec = _records(pubs, "Conference Publications")[0]
    assert _val(rec, "Conference Date") == "2012/10"


# 3. Preprints and abstracts are not refereed/published ----------------------

@pytest.mark.parametrize("entry", [
    {"journal": "arXiv e-prints"},
    {"journal": "arXiv preprint arXiv:2603.02400"},
    {"adsdoctype": "eprint", "journal": "anything"},
])
def test_preprint_detection(entry):
    assert is_preprint(entry)
    values = field_value_map({"ENTRYTYPE": "article", "title": "t", "author": "Fabbro, S",
                              "year": "2026", **entry},
                             entrytype="article", author_surnames=("Fabbro",),
                             overrides=Overrides())
    assert values["Refereed?"] == "No"
    assert values["Publishing Status"] == "Submitted"


def test_jasa_abstract_becomes_conference_abstract():
    tree, pubs = _tree()
    _templates(pubs)
    replace_publications(tree, [{
        "ID": "2024ASAJ..155A.276Z", "ENTRYTYPE": "article",
        "title": "Detecting ringed seal vocalizations in multiple environments",
        "author": "Zammit, K. and Fabbro, S.", "year": "2024",
        "journal": "Acoustical Society of America Journal", "pages": "A276",
        "adsrefereed": "no", "adsdoctype": "abstract",
    }], author_surnames=("Fabbro",))
    assert not _records(pubs, "Journal Articles")
    rec = _records(pubs, "Conference Publications")[0]
    assert xmlutil.lov_label(xmlutil.field_by_label(rec, "Refereed?")) == "No"
    assert xmlutil.lov_label(xmlutil.field_by_label(rec, "Conference Publication Type")) == "Abstract"
    assert _val(rec, "Conference Name") == "Acoustical Society of America Journal"


def test_ads_refereed_flag_wins():
    values = field_value_map({"ENTRYTYPE": "article", "title": "t", "author": "Fabbro, S",
                              "year": "2024", "journal": "Some Journal", "adsrefereed": "no"},
                             entrytype="article", author_surnames=("Fabbro",),
                             overrides=Overrides())
    assert values["Refereed?"] == "No"
    assert is_meeting_abstract({"journal": "Acoustical Society of America Journal",
                                "pages": "A276"})


def test_annotate_bibtex_adds_ads_properties():
    out = annotate_bibtex("@ARTICLE{2024A&A...1..1B,\n  title = {x},\n}",
                          [{"bibcode": "2024A&A...1..1B", "property": ["REFEREED"],
                            "doctype": "article"}])
    assert "adsrefereed = {yes}" in out and "adsdoctype = {article}" in out


# 4. Google Scholar snippets ------------------------------------------------------

def test_scholar_snippet_typing_and_urls():
    block = _pub_to_bibtex({"bib": {"title": "Interpreting stellar spectra",
                                    "author": ["T OBriain", "S Fabbro"], "year": "2020",
                                    "venue": "ICML Workshop on Interpretability"},
                            "eprint_url": "javascript:void(0)"})
    assert block.startswith("@inproceedings") and "booktitle" in block
    assert "javascript" not in block
    block = _pub_to_bibtex({"bib": {"title": "SKA Regional Centres", "author": ["S Fabbro"],
                                    "year": "2025", "venue": "… Society of the …"}})
    assert "journal" not in block
    block = _pub_to_bibtex({"bib": {"title": "C-19", "author": ["K Venn", "S Fabbro"],
                                    "year": "2026", "venue": "arXiv preprint"},
                            "eprint_url": "https://arxiv.org/pdf/2603.02400"})
    assert "eprint = {2603.02400}" in block
    assert venue_entrytype("American Astronomical Society Meeting Abstracts") == "inproceedings"
    assert venue_entrytype("Monthly Notices of the Royal Astronomical Society") == "article"


def test_scholar_entry_without_owner_is_dropped_and_never_replaces_base():
    tree, pubs = _tree()
    _templates(pubs)
    _record(pubs, "Conference Publications", "Interpreting Stellar Spectra with Unsupervised Domain Adaptation",
            authors="OBriain, T. (*),\n&\nFabbro, S.", year="2020", venue="ICML workshop",
            record_id="keep-me")
    result = replace_publications(tree, [
        {"ID": "ScholarC19", "ENTRYTYPE": "article", "title": "The primordial nature of C-19",
         "author": "K Venn and Z Yuan", "year": "2026", "journal": "arXiv preprint arXiv …"},
        {"ID": "ScholarInterp", "ENTRYTYPE": "article",
         "title": "Interpreting Stellar Spectra with Unsupervised Domain Adaptation",
         "author": "T OBriain and S Fabbro", "year": "2020", "journal": "arXiv preprint arXiv …"},
    ], author_surnames=("Fabbro",), preserve_extra=True)
    assert result["scholar_dropped"] == ["ScholarC19"]
    titles = [(r.get("label"), _val(r, TITLE_FIELD[r.get("label")])) for r in _records(pubs)]
    assert ("Conference Publications",
            "Interpreting Stellar Spectra with Unsupervised Domain Adaptation") in titles
    assert not any("Interpreting" in t for label, t in titles if label == "Journal Articles")


def test_preserved_scholar_artefacts_dropped_and_repaired():
    tree, pubs = _tree()
    _templates(pubs)
    _record(pubs, "Journal Articles", "Lensing without mass", record_id="r1",
            authors="Martin, H., Hudson, M., & Woodfinden, A.", venue="arXiv e …")
    _record(pubs, "Journal Articles", "CANFAR: A Community-Built Astronomy Platform",
            record_id="r2", authors="Major, B., Fabbro, S., & Kavelaars, J.",
            venue="… Society of the …", extra={"URL": "/scholar?output=instlink"})
    result = replace_publications(tree, [], author_surnames=("Fabbro",), preserve_extra=True)
    titles = [_val(r, "Article Title") for r in _records(pubs, "Journal Articles")]
    assert "Lensing without mass" not in titles
    canfar = next(r for r in _records(pubs) if _val(r, "Article Title").startswith("CANFAR"))
    assert _val(canfar, "Journal") == "" and _val(canfar, "URL") == ""
    assert any("Scholar artefact" in reason for _t, reason in result["dropped_preserved"])


# 5. Duplicates across sections ------------------------------------------------

def test_ads_article_retires_matching_conference_row():
    tree, pubs = _tree()
    _templates(pubs)
    _record(pubs, "Conference Publications", "Uncertainty-aware learning for CFHT image quality",
            record_id="c1")
    replace_publications(tree, [{
        "ID": "2022MNRAS.510..870G", "ENTRYTYPE": "article",
        "title": "Uncertainty-aware learning for CFHT image quality",
        "author": "Gilda, S. and Fabbro, S.", "year": "2022", "journal": "MNRAS",
        "doi": "10.1093/mnras/stab3243",
    }], author_surnames=("Fabbro",), preserve_extra=True)
    hits = [r for r in _records(pubs) if "Uncertainty-aware" in _val(r, TITLE_FIELD[r.get("label")])]
    assert len(hits) == 1 and hits[0].get("label") == "Journal Articles"


def test_arxiv_keys():
    assert arxiv_id({"eprint": "2507.12345", "archiveprefix": "arXiv"}) == "2507.12345"
    assert arxiv_id({"url": "https://arxiv.org/abs/2603.02400v2"}) == "2603.02400"
    assert arxiv_id({"doi": "10.48550/arXiv.2401.06087"}) == "2401.06087"
    assert "arxiv:2507.12345" in entry_keys({"title": "x", "eprint": "2507.12345"})


# 6. Trainee (*) marks -----------------------------------------------------------

def test_namesake_with_different_given_name_not_marked():
    christopher = Trainee("Christopher Murray", 2019, 2019)
    assert not author_matches("{Murray}, Calum", christopher, 2025)
    assert author_matches("{Murray}, Christopher", christopher, 2019)
    assert not author_matches("Murray, C.", christopher, 2026)  # long after supervision
    assert author_matches("Murray, C.", christopher, 2020)
    assert author_matches("Sanchez Tovar, Juan Camilo",
                          Trainee("Juan Camilo Sanchez Tovar", 2026), 2026)
    assert not author_matches("Bialek, Spencer", Trainee("Spencer Bialek", 2017, 2024), 2012)


def test_stale_marks_removed_and_hand_typed_lists_kept():
    tree, pubs = _tree()
    rec = _record(pubs, "Conference Publications", "SITELLE",
                  authors="Rhea, C (*); Rousseau-Nepton, L; Fabbro, S (*); Bialek, S (*)")
    trainees = [Trainee("Spencer Bialek", 2014, 2024)]
    plan = plan_hqp_marks(tree, trainees)
    assert {m["author"] for m in plan if m["action"] == "remove"} == {"Rhea, C (*)", "Fabbro, S (*)"}
    mark_hqp_authors(tree, trainees)
    assert _val(rec, "Authors") == "Rhea, C; Rousseau-Nepton, L; Fabbro, S; Bialek, S (*)"


def test_rebuilt_records_marked_from_full_names():
    tree, pubs = _tree()
    _templates(pubs)
    result = replace_publications(tree, [{
        "ID": "2025A&A...699A.201H", "ENTRYTYPE": "article", "title": "UNIONS intrinsic alignment",
        "author": "{Hervas Peters}, Fabian and {Murray}, Calum and {Fabbro}, S{\\'e}bastien",
        "year": "2025", "journal": "A&A",
    }], author_surnames=("Fabbro",), trainees=[Trainee("Christopher Murray", 2019, 2019)])
    rec = _records(pubs, "Journal Articles")[0]
    assert "(*)" not in _val(rec, "Authors")
    assert result["hqp_marks"] == []


# 7. LaTeX clean-up -------------------------------------------------------------

def test_latex_commands_not_read_as_accents():
    title = r"The Type Ia Supernova Rate at z\raisebox{-0.5ex}\textasciitilde0.5"
    assert strip_latex(title) == "The Type Ia Supernova Rate at z∼0.5"
    assert strip_latex("Black Hole─Halo") == "Black Hole–Halo"
    assert strip_latex(r"{\v{C}}ern{\'y} \v{s} \c c") == "Černý š ç"
    assert strip_latex(r"\textit{Gaia} DR3") == "Gaia DR3"


# 8. Six-year window ----------------------------------------------------------

def test_last_years_starts_six_years_back():
    assert builder.since_from_years(6) == (datetime.datetime.now().year - 6, 1)


# Extras: alphabetical tails and validation --------------------------------------

def test_last_in_alphabetical_tail_is_co_author():
    authors = ["Lead, A", "Second, B"] + [f"{c}name, Q" for c in "BCDEFGHIJ"] + ["Zfabbro, S"]
    entry = {"author": " and ".join(authors)}
    assert author_position(entry, ("Zfabbro",)) is None
    entry = {"author": " and ".join(["Lead, A", "Fabbro, S"])}
    assert author_position(entry, ("Fabbro",)) == -1


def test_validate_flags_reviewer_visible_problems():
    tree, pubs = _tree()
    _record(pubs, "Journal Articles", "Not mine", authors="Venn, K., & Yuan, Z.",
            venue="arXiv preprint arXiv …", extra={"URL": "javascript:void(0)"})
    messages = " ".join(i["message"] for i in validate_publications(tree, ("Fabbro",)))
    assert "does not list you" in messages
    assert "truncated" in messages
    assert "invalid URL" in messages


def test_scholar_snippets_replaced_by_ads_records(monkeypatch):
    import ccv.fetch_ads as fetch_ads
    from ccv.update import enrich_scholar_from_ads

    scholar = ("@article{ScholarC19,\n  author = {K Venn and Z Yuan},\n"
               "  title = {The primordial nature of the C-19 stellar stream},\n"
               "  journal = {arXiv preprint arXiv …},\n  year = {2026},\n}\n")
    doc = {"bibcode": "2026arXiv260302400V", "property": ["EPRINT_OPENACCESS"],
           "doctype": "eprint"}
    monkeypatch.setattr(fetch_ads, "lookup_titles",
                        lambda token, titles, surnames: {titles[0]: doc})
    monkeypatch.setattr(fetch_ads, "export_bibtex", lambda token, bibcodes: (
        "@ARTICLE{2026arXiv260302400V,\n  author = {{Venn}, Kim and {Fabbro}, S.},\n"
        "  title = {The primordial nature of the C-19 stellar stream},\n"
        "  journal = {arXiv e-prints},\n  year = {2026},\n}\n"))
    extra, remaining, report = enrich_scholar_from_ads(scholar, "", "token", ("Fabbro",))
    assert "2026arXiv260302400V" in extra and "adsdoctype = {eprint}" in extra
    assert remaining == "" and report
