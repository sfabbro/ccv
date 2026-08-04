#!/usr/bin/env python3
"""Cross-check the field ids and LOV ids the `ccv` package hardcodes against a
real CCV export and the official CCV schema.

Usage:
    python check_schema.py [CCV-export.xml] [path/to/ijiraq-CCV] [path/to/dataset-cv-lov.xml]

Defaults:
    CCV-export.xml       -> ./CCV-export.xml
    ijiraq-CCV checkout  -> ../ijiraq-CCV
    dataset-cv-lov.xml   -> /tmp/ccv-schema/dataset-cv-lov.xml (download from
                            https://ccv-cvc.ca/schema/dataset-cv-lov.xml)

A wrong field/LOV id would silently corrupt a CCV import, so this checks the
package's expectations against your own export (which is authoritative for the
agency template you use).
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "ijiraq-CCV"))
import ccv.schema as schema  # noqa: E402

USER_CCV = sys.argv[1] if len(sys.argv) > 1 else "CCV-export.xml"
LOV_FILE = sys.argv[3] if len(sys.argv) > 3 else "/tmp/ccv-schema/dataset-cv-lov.xml"


def local(tag):
    return tag.rsplit("}", 1)[-1]


tree = ET.parse(USER_CCV)
root = tree.getroot()

# Find the Publications section, then collect field-label->id per child type.
pubs = None
for el in root.iter():
    if local(el.tag) == "section" and el.get("label") == "Publications":
        pubs = el
        break

if pubs is None:
    print(f"error: no Publications section in {USER_CCV}")
    sys.exit(1)

type_field_ids = {}  # type label -> {field label: id}
for child in pubs:
    if local(child.tag) != "section":
        continue
    tlabel = child.get("label")
    if tlabel not in ("Journal Articles", "Conference Publications", "Book Chapters"):
        continue
    for field in child:
        if local(field.tag) != "field":
            continue
        type_field_ids.setdefault(tlabel, {})[field.get("label")] = field.get("id")

print(f"=== Per-type field id comparison (schema.py vs {USER_CCV}) ===")
schema_maps = {
    "Journal Articles": schema.ARTICLE_FIELDS,
    "Conference Publications": schema.PROCEEDINGS_FIELDS,
    "Book Chapters": schema.CHAPTER_FIELDS,
}
for tlabel, smap in schema_maps.items():
    actual = type_field_ids.get(tlabel, {})
    if not actual:
        print(f"  {tlabel}: (no records in user export)")
        continue
    print(f"  {tlabel}:")
    ok = bad = missing = 0
    for fname, fid in sorted(smap.items()):
        a = actual.get(fname)
        if a is None:
            missing += 1
        elif a == fid:
            ok += 1
        else:
            bad += 1
            print(f"      {fname}: schema {fid} != user {a}")
    print(f"      -> {ok} match, {bad} MISMATCH, {missing} absent")

print("\n=== LOV ids (fixed table-aware check) ===")
lov_tree = ET.parse(LOV_FILE)
official = {}
for table in lov_tree.getroot().iter():
    if local(table.tag) != "table":
        continue
    for code in table:
        if local(code.tag) != "code":
            continue
        official.setdefault(code.get("englishName"), []).append(
            (table.get("englishName"), code.get("id"))
        )

for value, lov_id in schema.LOV_IDS.items():
    cands = official.get(value, [])
    if any(cid == lov_id for _, cid in cands):
        print(f"  {value}: OK")
    else:
        print(f"  {value}: *** schema {lov_id} matches none of {cands}")
