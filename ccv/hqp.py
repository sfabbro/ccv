"""Update the Students and Postdoctoral Fellows (HQP) section of a CCV.

Training of highly qualified personnel is one of the two evaluation
criteria for NSERC Discovery Grants, so keeping this section current
matters as much as the publication list.

The section schema (field ids, LOV tables) varies between CV templates,
so this module is driven entirely by the base CCV: the first child record
of the target section is used as a template for every new record, and only
fields whose *label* appears in the YAML input are filled.

students.yaml:

    records:
      - "Name": "Jane Doe"
        "Student Type": "Doctoral Student"
        "Supervisor Role": "Principal Supervisor"
        "Institution": "University of Victoria"
        "Period From": "2022-09"
        "Period To": "2026-08"
        "Status": "In Progress"
      - "Name": "Bob Smith"
        "Student Type": "Post-doctoral Student"
        "Supervisor Role": "Principal Supervisor"
        "Institution": "NRC Herzberg"
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from . import xmlutil
from .schema import LOV_IDS

# Labels used to locate the section when the exact label varies by template.
_SECTION_HINTS = ("Students and Postdoctoral Fellows", "Students", "HQP", "Personnel")


def find_hqp_section(root) -> Any | None:
    exact = xmlutil.find_section(root, "Students and Postdoctoral Fellows")
    if exact is not None:
        return exact
    for section in xmlutil.iter_sections(root):
        label = (section.get("label") or "").lower()
        if any(hint.lower() in label for hint in _SECTION_HINTS):
            return section
    return None


def update_hqp(
    tree,
    input_path: str | Path,
    *,
    section_label: str | None = None,
    mode: str = "replace",
    assign_record_ids: bool = False,
) -> dict[str, Any]:
    root = tree.getroot()
    if section_label:
        section = xmlutil.find_section(root, section_label)
    else:
        section = find_hqp_section(root)
    if section is None:
        raise ValueError(
            "Base CCV has no HQP section (looked for 'Students and Postdoctoral "
            "Fellows'). Pass --section to name it."
        )

    with open(input_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    records_in = data.get("records") or []
    if not isinstance(records_in, list) or not records_in:
        raise ValueError("input YAML has no 'records' list")

    template = None
    for child in xmlutil.child_sections(section):
        template = deepcopy(child)
        break
    if template is None:
        raise ValueError(
            f"HQP section {section.get('label')!r} has no record template to copy"
        )

    if mode == "replace":
        for child in list(section):
            section.remove(child)

    written = 0
    for record_data in records_in:
        if not isinstance(record_data, dict):
            continue
        record = deepcopy(template)
        xmlutil.strip_record_id(record)
        if assign_record_ids:
            record.set("recordId", xmlutil.new_record_id())
        for field in xmlutil.fields_of(record):
            label = field.get("label")
            if label not in record_data:
                continue
            value = record_data[label]
            if value is None:
                continue
            text = str(value)
            is_lov = xmlutil.lov_label(field) != "" or any(
                c.tag.endswith("lov") for c in field
            )
            if is_lov and text in LOV_IDS:
                xmlutil.set_lov(field, text, LOV_IDS[text])
            else:
                xmlutil.set_value_text(field, text)
        section.append(record)
        written += 1

    return {"written": written, "section": section.get("label")}
