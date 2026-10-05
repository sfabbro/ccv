"""XML helpers for CCV documents."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .schema import NS

ROOT = f"{{{NS}}}generic-cv"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def register_ccv_namespace() -> None:
    ET.register_namespace("generic-cv", NS)


def load_ccv(path: str | Path) -> ET.ElementTree:
    register_ccv_namespace()
    return ET.parse(path)


def write_ccv(tree: ET.ElementTree, path: str | Path) -> None:
    register_ccv_namespace()
    root = tree.getroot()
    root.set("dateTimeGenerated", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    tree.write(path, encoding="utf-8", xml_declaration=True)


def iter_sections(root: ET.Element, label: str | None = None) -> Iterator[ET.Element]:
    for el in root.iter():
        if local_name(el.tag) != "section":
            continue
        if label is None or el.get("label") == label:
            yield el


def find_section(root: ET.Element, label: str) -> ET.Element | None:
    return next(iter_sections(root, label), None)


def child_sections(parent: ET.Element) -> list[ET.Element]:
    return [c for c in parent if local_name(c.tag) == "section"]


def fields_of(section: ET.Element) -> list[ET.Element]:
    return [c for c in section if local_name(c.tag) == "field"]


def field_by_label(section: ET.Element, label: str) -> ET.Element | None:
    for field in fields_of(section):
        if field.get("label") == label:
            return field
    return None


def new_record_id() -> str:
    return uuid.uuid4().hex


def strip_record_id(section: ET.Element) -> None:
    if "recordId" in section.attrib:
        del section.attrib["recordId"]


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if local_name(child.tag) == name:
            return child
    return None


def child_tag(parent: ET.Element, name: str) -> str:
    """Tag for a new child, matching the parent's namespace.

    Official CCV exports namespace only the root (`generic-cv:generic-cv`).
    Every other element is unprefixed (`<lov>`, `<value>`, `<section>`).
    A prefixed `<generic-cv:lov>` is dropped on import, which is why
    Contribution Role came back blank after a round-trip.
    """
    tag = parent.tag
    if tag.startswith("{") and "}" in tag:
        return f"{{{tag[1:tag.index('}')]}}}{name}"
    return name


def set_value_text(field: ET.Element, text: str | None) -> None:
    """Set a <value> field, and mirror into bilingual/english when present."""
    if text is None:
        text = ""
    value = _find_child(field, "value")
    bilingual = _find_child(field, "bilingual")
    if value is None and bilingual is None:
        value = ET.SubElement(field, child_tag(field, "value"))
        value.set("type", "String")
    if value is not None:
        value.text = text
    if bilingual is not None:
        english = _find_child(bilingual, "english")
        if english is None:
            english = ET.SubElement(bilingual, child_tag(bilingual, "english"))
        english.text = text
        if _find_child(bilingual, "french") is None:
            ET.SubElement(bilingual, child_tag(bilingual, "french"))


def set_lov(field: ET.Element, label: str, lov_id: str) -> None:
    """Set a list-of-values field. Removes any stray <value> child first —
    LOV fields must not carry both (injected templates used to create that)."""
    for child in list(field):
        if local_name(child.tag) == "value":
            field.remove(child)
    lov = _find_child(field, "lov")
    if lov is None:
        lov = ET.SubElement(field, child_tag(field, "lov"))
    lov.set("id", lov_id)
    lov.text = label


def clear_lov(field: ET.Element | None) -> None:
    """Remove any <lov> child so the field is unset."""
    if field is None:
        return
    for child in list(field):
        if local_name(child.tag) == "lov":
            field.remove(child)


def value_text(field: ET.Element | None) -> str:
    """Read the string value of a field (value / bilingual/english)."""
    if field is None:
        return ""
    value = _find_child(field, "value")
    if value is not None and value.text:
        return value.text
    bilingual = _find_child(field, "bilingual")
    if bilingual is not None:
        english = _find_child(bilingual, "english")
        if english is not None and english.text:
            return english.text
    return ""


def lov_label(field: ET.Element | None) -> str:
    """Read the current LOV label of a field (empty if not a LOV field)."""
    if field is None:
        return ""
    lov = _find_child(field, "lov")
    if lov is not None and lov.text:
        return lov.text
    return ""


def summarize(tree: ET.ElementTree) -> dict[str, int]:
    """Count top-level sections and common nested record types."""
    root = tree.getroot()
    counts: dict[str, int] = {}
    for section in child_sections(root):
        label = section.get("label", "?")
        counts[label] = counts.get(label, 0) + 1
        for child in child_sections(section):
            clabel = f"{label} / {child.get('label')}"
            counts[clabel] = counts.get(clabel, 0) + 1
    pubs = find_section(root, "Publications")
    if pubs is not None:
        for child in child_sections(pubs):
            key = f"Publications / {child.get('label')}"
            counts[key] = counts.get(key, 0) + 1
    return counts
