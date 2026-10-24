"""CCV field IDs, LOV codes, and BibTeX <-> CCV publication mappings.

IDs are taken from official CCV XML exports and cross-checked against the
public CCV schema published by the Canadian Common CV:

    https://ccv-cvc.ca/schema/dataset-cv.xml        (field -> lookupId)
    https://ccv-cvc.ca/schema/dataset-cv-lov.xml    (lookupId -> values)
"""

from __future__ import annotations

NS = "http://www.cihr-irsc.gc.ca/generic-cv/1.0.0"
NSMAP = {"ccv": NS}

# Top-level / nesting section IDs used when assembling a CV.
SECTION_IDS = {
    "Personal Information": "f589cbc028c64fdaa783da01647e5e3c",
    "Education": "0d82220f95f043e0bc9608bbb6bf413a",
    "User Profile": "5c6aca5ad9da4e3d90e5a4d4d876d2b8",
    "Employment": "94b1e26073ae476da13ede5baf1f1cc0",
    "Research Funding History": "aaedc5454412483d9131f7619d10279e",
    "Activities": "95c29504d0aa4b51b84659cafaf2b38d",
    "Memberships": "ee130288917f4e23adcc800a94ae355c",
    "Contributions": "047ec63e32fe450e943cb678339e8102",
    "Publications": "46e8f57e67db48b29d84dda77cf0ef51",
    "Journal Articles": "9a34d6b273914f18b2273e8de7c48fd6",
    "Conference Publications": "4b9f909503cd4c8aa8d826c87d6d874d",
    "Book Chapters": "fd8f2ffe3f5c43db8b5c3f72d8ffd994",
}

# ---------------------------------------------------------------------------
# List-of-values tables, verified against the official CCV LOV dataset.
# ---------------------------------------------------------------------------

# lookupId 00000000000000000000000000120000 : Yes / No
LOV_IDS = {
    "Yes": "00000000000000000000000000000400",
    "No": "00000000000000000000000000000401",
}

# lookupId 00000000000000000000000100002100 : Contribution Role
ROLE_LOV_IDS = {
    "First Listed Author": "00000000000000000000000100002100",
    "First Listed Editor": "00000000000000000000000100002101",
    "Co-Author": "00000000000000000000000100002102",
    "Co-Editor": "00000000000000000000000100002103",
    "Last Author": "f6f1d34952c44f7c884ac56036b3ba4d",
}
LOV_IDS.update(ROLE_LOV_IDS)

# lookupId 00000000000000000000000100001700 : Publishing Status
PUBLISHING_STATUS_LOV_IDS = {
    "Submitted": "00000000000000000000000100001700",
    "Revision Requested": "00000000000000000000000100001701",
    "Accepted": "00000000000000000000000100001702",
    "In Press": "00000000000000000000000100001703",
    "Published": "00000000000000000000000100001704",
}
LOV_IDS.update(PUBLISHING_STATUS_LOV_IDS)

# lookupId 00000000000000000000000100007000 : Conference Publication Type
CONFERENCE_TYPE_LOV_IDS = {
    "Paper": "00000000000000000000000100007000",
    "Abstract": "00000000000000000000000100007001",
    "Poster": "00000000000000000000000100007002",
}
LOV_IDS.update(CONFERENCE_TYPE_LOV_IDS)

# lookupId 2f859939bc4f4faaa9829ccde7ed73a8 : Contribution Percentage bands
CONTRIBUTION_PERCENTAGE_LOV_IDS = {
    "0-10": "2f859939bc4f4faaa9829ccde7ed73b8",
    "11-20": "33a9ceed2e054a4e9ed2ae3ffaa8857d",
    "21-30": "d5fd41e01458447a859c336e7b831c34",
    "31-40": "b12e128e6d40478aa669da832455ca71",
    "41-50": "2cbfd4e8561644bba03193fd09fee146",
    "51-60": "dce97f1497984093bfd8c3e6989f8507",
    "61-70": "c66dd3e8ed4e464b821f49ea6a3a162a",
    "71-80": "dcb5deacd63249f59eb764756dffefe5",
    "81-90": "e6044311ff214d00953a804327044692",
    "91-100": "c888d41ce9e048d0a2a19750481555d1",
}
LOV_IDS.update(CONTRIBUTION_PERCENTAGE_LOV_IDS)

# lookupId 00000000000000000000000100001800 : HQP / student type
STUDENT_TYPE_LOV_IDS = {
    "Master's Student": "00000000000000000000000100001800",
    "Doctoral Student": "00000000000000000000000100001801",
    "Post-doctoral Student": "00000000000000000000000100001802",
    "Researcher": "00000000000000000000000100001803",
}
LOV_IDS.update(STUDENT_TYPE_LOV_IDS)

# lookupId 00000000000000000000000100002900 : supervision role
SUPERVISOR_ROLE_LOV_IDS = {
    "Principal Supervisor": "00000000000000000000000100002900",
    "Co-Supervisor": "00000000000000000000000100002901",
    "Academic Advisor": "00000000000000000000000100002902",
}
LOV_IDS.update(SUPERVISOR_ROLE_LOV_IDS)

# The role stored for a publication depends on the author's position in the
# author list. CCV has no "Sole Author" value; a sole-authored paper is a
# First Listed Author.
ROLE_FIRST = "First Listed Author"
ROLE_LAST = "Last Author"
ROLE_CO = "Co-Author"

# Default Contribution Percentage bands, per authorship position. These are
# heuristics: override per paper with the --overrides file.
PERCENTAGE_DEFAULTS = {
    "first": "81-90",
    "last": "71-80",
    "co": "31-40",
    "sole": "91-100",
}

# ---------------------------------------------------------------------------
# BibTeX <-> CCV publication mapping
# ---------------------------------------------------------------------------

BIB_TO_CCV = {
    "article": "Journal Articles",
    "inproceedings": "Conference Publications",
    "inbook": "Book Chapters",
}

CCV_TO_BIB = {v: k for k, v in BIB_TO_CCV.items()}

# Which publication types we regenerate from BibTeX (others in the base CCV
# are kept).
MANAGED_PUBLICATION_LABELS = tuple(BIB_TO_CCV.values())

# Publication fields stored as CCV <lov> (not free-text <value>).
LOV_FIELD_LABELS = frozenset({
    "Publishing Status",
    "Refereed?",
    "Open Access?",
    "Synthesis?",
    "Contribution Role",
    "Invited?",
    "Conference Publication Type",
    "Contribution Percentage",
})

REFEREED_BY_ENTRYTYPE = {
    "article": True,
    "inproceedings": False,
    "inbook": True,
}

ARTICLE_FIELDS = {
    "Article Title": "f3fd4878d47c4e83aef6959620ba4870",
    "Journal": "5c04ea4dae464499807d0b40b4cad049",
    "Volume": "0a826c656ff34e579dfcbfb373771260",
    "Issue": "cc1d9e14945b4e8496641dbe22b3448a",
    "Page Range": "00ba1799ece344dc8d0779a3f05a4df8",
    "Publishing Status": "3b56e4362d6a495aa5d22a1de5914741",
    "Year": "6fafe258e19e49a7884428cb49d75424",
    "Publisher": "4ad593960aba4a21bf154fa8daf37f9f",
    "Publication Location": "4c3bc805ceaa42259f014514fc4905f8",
    "Description / Contribution Value": "1167905d079c4400ae7a4a76a203a445",
    "DOI": "375a0e2ea0914291b05b0529c4755aa7",
    "URL": "478545acac5340c0a73b7e0d2a4bee06",
    "Refereed?": "2089ff1a86844b6c9a10fc63469f9a9d",
    "Open Access?": "51b7eaff05444990af823b9d80924f5b",
    "Synthesis?": "b779cc6478bd4b09b516c6d55e938583",
    "Contribution Role": "289c8814fff141d89b12569d49aa2cb3",
    "Number of Contributors": "dc7922dfa04348a3a83c9afb5bbaa24a",
    "Authors": "bc3b428d99384b04bb749311bb804e1d",
    "Editors": "707a6e0ca58341a5a82fb923b2842530",
    "Funding Organization": "e4c319e25b3a40fa888cf26ef90a3267",
    "Contribution Percentage": "9afd9e28df47464faf3f9ee2c4809e25",
    "Description of Contribution Role": "9f2e163dfcbf4abdb73e9d5c4daf03c4",
}

CHAPTER_FIELDS = {
    "Chapter Title": "52a699a6b0fe42a4851a7d5ae355360b",
    "Book Title": "b864a9512e89482487f83ed22c454e9d",
    "Volume": "c250eee732d34fd9831f858c39785624",
    "Page Range": "45b9d02a4bb04ec782357741b53dc135",
    "Year": "c114eabcd4674f3c9467b2bf6820cbd6",
    "Publisher": "51a088349c1442238d5d0331d95f3205",
    "Publication Location": "1581a489c30d46f1b5a8c2f2863eaf45",
    "Description / Contribution Value": "959146d3ae8d4e4f9747bc0697adb5f5",
    "Refereed?": "51bd72e89f85442a9ae199e75fe5e765",
    "Contribution Role": "5d2f8073935a4e66b39fb99366889ded",
    "Contribution Percentage": "23abe2286ff7411badeadfa661dc678d",
    "Description of Contribution Role": "a6452d277ddf4bb2a6bd8ed75da72a58",
    "Number of Contributors": "aea26d37a8e449aea1da8da9c2b37fb2",
    "URL": "6f1c66fc402d4b0db3d9987e2c5d49e8",
    "Authors": "5bc7b0b361f843d296e0e035b4b87176",
    "Editors": "dcb27492e1554fc9838992ba7c70f416",
    "DOI": "3ec2cafffd764171a325a26dd707b819",
}

PROCEEDINGS_FIELDS = {
    "Conference Publication Type": "81ef87c09ded47ae8880b8d79e83406f",
    "Conference Name": "b3c8a60c053a405597b92899d95765a3",
    "Conference Location": "5813833859a64bb58ee55e4f55aff29b",
    "Publication Title": "8e6ee535c95e42ec866b777c7472bafb",
    "Published In": "1a1b39e861054ee59d270e66271a4ead",
    "Page Range": "684ccb1fcdd7421f89b304ff5c40579d",
    "Publishing Status": "080301b1f1c0464bba7fcfa1fa8fe182",
    "Year": "0318d139f3e0479083188ff8319a97b2",
    "Publisher": "0c357193a93f4137a87394401ac81958",
    "Description / Contribution Value": "a6e901e5f0cf48a3a7d674bf1e6fcd7f",
    "Refereed?": "560a2ce08e14497ba575af760eb12ba9",
    "Invited?": "06295e65f66b4c6aa286d08bd9fac59b",
    "Contribution Role": "b101f8f057db434ba4fdee3a86c387cc",
    "Number of Contributors": "1a66ad40654a45c9a0119b19d7cf20a6",
    "DOI": "49e5507889954743b104959e62d9e496",
    "Contribution Percentage": "575eaa1383ac49ed9d78b5a970a76eb8",
    "Description of Contribution Role": "890336779db441d8a38e7709f6866d15",
    "URL": "61690b466fb748d99ed29b340c0ee60b",
    "Authors": "3cc54d9bb92d421da46548979048396f",
    "Editors": "018e656a0f824b1f91a6a2cb33ac61dd",
}

FIELDS_BY_ENTRYTYPE = {
    "article": ARTICLE_FIELDS,
    "inproceedings": PROCEEDINGS_FIELDS,
    "inbook": CHAPTER_FIELDS,
}

MONTH_NUMBERS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

# ADS / AASTeX journal macros commonly found in astronomy BibTeX.
JOURNAL_MACROS = {
    "\\aj": "The Astronomical Journal",
    "\\apj": "The Astrophysical Journal",
    "\\apjl": "The Astrophysical Journal Letters",
    "\\apjs": "The Astrophysical Journal Supplement Series",
    "\\psj": "The Planetary Science Journal",
    "\\icarus": "Icarus",
    "\\mnras": "Monthly Notices of the Royal Astronomical Society",
    "\\aap": "Astronomy and Astrophysics",
    "\\aapl": "Astronomy and Astrophysics Letters",
    "\\aapr": "Astronomy and Astrophysics Review",
    "\\nat": "Nature",
    "\\nature": "Nature",
    "\\sci": "Science",
    "\\pasp": "Publications of the Astronomical Society of the Pacific",
    "\\ssr": "Space Science Reviews",
    "\\prd": "Physical Review D",
    "\\pra": "Physical Review A",
    "\\prb": "Physical Review B",
    "\\prc": "Physical Review C",
    "\\pre": "Physical Review E",
    "\\prl": "Physical Review Letters",
    "\\araa": "Annual Review of Astronomy and Astrophysics",
    "\\apss": "Astrophysics and Space Science",
    "\\baas": "Bulletin of the American Astronomical Society",
    "\\cjaa": "Chinese Journal of Astronomy and Astrophysics",
    "\\jcap": "Journal of Cosmology and Astroparticle Physics",
    "\\jgr": "Journal of Geophysical Research",
    "\\grl": "Geophysical Research Letters",
    "\\gca": "Geochimica et Cosmochimica Acta",
    "\\gji": "Geophysical Journal International",
    "\\pasa": "Publications of the Astronomical Society of Australia",
    "\\pasj": "Publications of the Astronomical Society of Japan",
    "\\pnas": "Proceedings of the National Academy of Science",
    "\\rmxaa": "Revista Mexicana de Astronomia y Astrofisica",
    "\\njp": "New Journal of Physics",
    "\\physrep": "Physics Reports",
    "\\planss": "Planetary and Space Science",
    "\\solphys": "Solar Physics",
    "\\aipconf": "AIP Conference Proceedings",
    "\\aspconf": "Astronomical Society of the Pacific Conference Series",
    "\\jast": "Journal of Astronomical Instrumentation",
    "\\memsai": "Memorie della Societa Astronomica Italiana",
    "\\nar": "New Astronomy Reviews",
    "\\intjmps": "International Journal of Modern Physics Supplement",
    "\\ijmpd": "International Journal of Modern Physics D",
    "\\sciadv": "Science Advances",
    "\\natast": "Nature Astronomy",
    "\\natphys": "Nature Physics",
    "\\natgeo": "Nature Geoscience",
    "\\natcomm": "Nature Communications",
    "\\epsl": "Earth and Planetary Science Letters",
    "\\geol": "Geology",
    "\\maps": "Meteoritics and Planetary Science",
    "\\ssci": "Solar System Science",
    "\\trends": "Trends in Ecology and Evolution",
    "\\zap": "Zeitschrift fuer Astrophysik",
    "\\uag": "Undergraduate Research in Astronomy",
    "\\mexaa": "Memorie della Societa Astronomica Italiana Supplement",
    "\\qjras": "Quarterly Journal of the Royal Astronomical Society",
    "\\arXiv": "arXiv e-prints",
    "\\jcat": "Journal of Classification",
}
