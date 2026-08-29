"""ArchiMate 3.1 Open Exchange XML — imports straight into Archi."""

from __future__ import annotations

import re
from typing import List
from xml.sax.saxutils import escape

from repograph_core.model import ScanResult

_ID = re.compile(r"[^A-Za-z0-9_\-]")

VALID_ELEMENTS = {
    "BusinessActor", "BusinessRole", "BusinessProcess", "BusinessService", "BusinessObject",
    "ApplicationComponent", "ApplicationService", "ApplicationInterface", "DataObject",
    "Node", "Device", "SystemSoftware", "TechnologyService", "Artifact", "CommunicationNetwork",
}
VALID_RELATIONS = {
    "Composition", "Aggregation", "Assignment", "Realization", "Serving", "Access",
    "Influence", "Triggering", "Flow", "Specialization", "Association",
}


def _identifier(value: str) -> str:
    cleaned = _ID.sub("-", str(value)).strip("-") or "x"
    return f"id-{cleaned}"[:120]


def export(result: ScanResult) -> str:
    lines: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.opengroup.org/xsd/archimate/3.0/ '
        'http://www.opengroup.org/xsd/archimate/3.1/archimate3_Model.xsd" '
        f'identifier="{_identifier("model-" + result.meta.repo_name)}">'
    )
    lines.append(f'  <name xml:lang="en">{escape(result.meta.repo_name)} architecture</name>')
    lines.append(f'  <documentation xml:lang="en">{escape(str(result.summary.get("purpose", ""))[:900])}'
                 f'</documentation>')

    lines.append("  <elements>")
    known = set()
    for element in result.archimate.elements:
        element_type = element.type if element.type in VALID_ELEMENTS else "ApplicationComponent"
        identifier = _identifier(element.id)
        known.add(element.id)
        lines.append(f'    <element identifier="{identifier}" xsi:type="{element_type}">')
        lines.append(f'      <name xml:lang="en">{escape(element.name)}</name>')
        if element.documentation:
            lines.append(f'      <documentation xml:lang="en">'
                         f'{escape(element.documentation[:500])}</documentation>')
        lines.append("    </element>")
    lines.append("  </elements>")

    lines.append("  <relationships>")
    for index, relation in enumerate(result.archimate.relations):
        if relation.source not in known or relation.target not in known:
            continue
        relation_type = relation.type if relation.type in VALID_RELATIONS else "Association"
        lines.append(
            f'    <relationship identifier="{_identifier(f"rel-{index}")}" '
            f'source="{_identifier(relation.source)}" target="{_identifier(relation.target)}" '
            f'xsi:type="{relation_type}">'
        )
        if relation.name:
            lines.append(f'      <name xml:lang="en">{escape(relation.name)}</name>')
        lines.append("    </relationship>")
    lines.append("  </relationships>")

    lines.append("  <organizations>")
    for layer in ("business", "application", "technology"):
        members = [e for e in result.archimate.elements if e.layer == layer]
        if not members:
            continue
        lines.append("    <item>")
        lines.append(f'      <label xml:lang="en">{layer.title()} layer</label>')
        for element in members:
            lines.append(f'      <item identifierRef="{_identifier(element.id)}"/>')
        lines.append("    </item>")
    lines.append("  </organizations>")
    lines.append("</model>")
    return "\n".join(lines)
