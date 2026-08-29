"""Mermaid diagram sources.

Mermaid is the lingua franca for diagrams in Markdown, GitHub and most AI
tooling, so every structural view is emitted as Mermaid text as well as SVG.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from repograph_core.model import App, Flow, ScanResult

from . import relevance

_ID_RE = re.compile(r"[^A-Za-z0-9_]")
# Words Mermaid parses as syntax; a node called "end" silently closes a subgraph.
_RESERVED = {"end", "graph", "subgraph", "class", "classDef", "click", "style", "direction",
             "flowchart", "state", "note", "link", "call", "default", "linkStyle"}


def mid(value: str) -> str:
    cleaned = _ID_RE.sub("_", value).strip("_")
    if not cleaned:
        cleaned = "n"
    if cleaned[0].isdigit() or cleaned in _RESERVED:
        cleaned = "n_" + cleaned
    return cleaned[:60]


def q(text: str, limit: int = 70) -> str:
    text = " ".join(str(text).split())
    text = text.replace('"', "'").replace("[", "(").replace("]", ")")
    text = text.replace("{", "(").replace("}", ")")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def flowchart(flow: Flow, direction: str = "LR") -> str:
    lines = [f"flowchart {direction}"]
    lanes: Dict[str, List[str]] = {}
    for node in flow.nodes:
        shape = _shape(node.kind, q(node.label))
        lanes.setdefault(node.lane or "Process", []).append(f"    {mid(node.id)}{shape}")
    for lane, entries in lanes.items():
        lines.append(f'  subgraph {mid("lane_" + lane)}["{q(lane, 40)}"]')
        lines.append("    direction TB")
        lines.extend(entries)
        lines.append("  end")
    for edge in flow.edges:
        arrow = "-.->" if edge.kind in ("message", "data") else "-->"
        label = f'|"{q(edge.label, 32)}"|' if edge.label else ""
        lines.append(f"  {mid(edge.source)} {arrow}{label} {mid(edge.target)}")
    lines.extend(_class_defs())
    for node in flow.nodes:
        lines.append(f"  class {mid(node.id)} {_class_for(node.kind)};")
    return "\n".join(lines)


def _shape(kind: str, label: str) -> str:
    if kind == "decision":
        return f'{{"{label}"}}'
    if kind in ("start",):
        return f'(["{label}"])'
    if kind == "end":
        return f'(["{label}"])'
    if kind in ("datastore", "database"):
        return f'[("{label}")]'
    if kind == "event":
        return f'>"{label}"]'
    if kind == "external":
        return f'[["{label}"]]'
    if kind == "subprocess":
        return f'[["{label}"]]'
    return f'["{label}"]'


def _class_defs() -> List[str]:
    return [
        "  classDef start fill:#f0fdf4,stroke:#16a34a,color:#0f172a;",
        "  classDef finish fill:#fef2f2,stroke:#dc2626,color:#0f172a;",
        "  classDef decision fill:#fffbeb,stroke:#d97706,color:#0f172a;",
        "  classDef store fill:#ecfeff,stroke:#0891b2,color:#0f172a;",
        "  classDef ext fill:#fff7ed,stroke:#ea580c,color:#0f172a;",
        "  classDef task fill:#f8fafc,stroke:#2563eb,color:#0f172a;",
        "  classDef app fill:#eff6ff,stroke:#2563eb,color:#0f172a;",
    ]


def _class_for(kind: str) -> str:
    return {
        "start": "start", "end": "finish", "decision": "decision",
        "datastore": "store", "database": "store", "external": "ext",
    }.get(kind, "task")


def c4_context(result: ScanResult) -> str:
    lines = ["C4Context", f'  title System context — {q(result.meta.repo_name, 60)}']
    for element in result.c4.elements:
        if element.level == "person":
            lines.append(f'  Person({mid(element.id)}, "{q(element.name, 40)}", "{q(element.description, 60)}")')
    lines.append(f'  System({mid("sys_" + result.meta.repo_name)}, "{q(result.meta.repo_name, 40)}", '
                 f'"{q(result.summary.get("purpose", ""), 80)}")')
    for element in result.c4.elements:
        if element.level in ("system_ext", "database"):
            macro = "SystemDb_Ext" if element.level == "database" else "System_Ext"
            lines.append(f'  {macro}({mid(element.id)}, "{q(element.name, 40)}", "{q(element.technology, 50)}")')
    system_id = mid("sys_" + result.meta.repo_name)
    for relation in result.c4.relations:
        source = mid(relation.source)
        if any(e.id == relation.source and e.level == "person" for e in result.c4.elements):
            lines.append(f'  Rel({source}, {system_id}, "{q(relation.description, 40)}")')
    seen = set()
    for element in result.c4.elements:
        if element.level in ("system_ext", "database") and element.id not in seen:
            seen.add(element.id)
            lines.append(f'  Rel({system_id}, {mid(element.id)}, "uses")')
    return "\n".join(lines)


def c4_container(result: ScanResult) -> str:
    lines = ["C4Container", f'  title Containers — {q(result.meta.repo_name, 60)}']
    for element in result.c4.elements:
        if element.level == "person":
            lines.append(f'  Person({mid(element.id)}, "{q(element.name, 40)}", "{q(element.description, 50)}")')
    lines.append(f'  System_Boundary(b1, "{q(result.meta.repo_name, 40)}") {{')
    for app in result.apps:
        tech = q(" · ".join(app.languages[:2] + app.frameworks[:2]), 40)
        lines.append(f'    Container({mid(app.id)}, "{q(app.name, 36)}", "{tech}", '
                     f'"{q(app.description or app.kind, 60)}")')
    lines.append("  }")
    for system in result.external_systems:
        if system.kind in ("database", "cache", "storage", "search"):
            lines.append(f'  ContainerDb_Ext({mid(system.id)}, "{q(system.name, 36)}", '
                         f'"{q(system.technology, 30)}", "")')
        else:
            lines.append(f'  System_Ext({mid(system.id)}, "{q(system.name, 36)}", "{q(system.technology, 40)}")')
    for edge in result.edges:
        if edge.kind in ("depends", "db", "cache", "queue", "storage", "http", "deploy"):
            lines.append(f'  Rel({mid(edge.source)}, {mid(edge.target)}, "{q(edge.label or edge.kind, 30)}")')
    for element in result.c4.elements:
        if element.level == "person":
            for app in result.apps:
                if app.kind in ("frontend", "service", "application", "cli"):
                    lines.append(f'  Rel({mid(element.id)}, {mid(app.id)}, "uses")')
                    break
    return "\n".join(lines)


def c4_component(result: ScanResult, app: App, limit: int = 30) -> str:
    components = sorted([c for c in result.components if c.app == app.id], key=lambda c: -c.files)[:limit]
    ids = {c.id for c in components}
    lines = ["C4Component", f'  title Components — {q(app.name, 50)}',
             f'  Container_Boundary(b1, "{q(app.name, 40)}") {{']
    for component in components:
        lines.append(f'    Component({mid(component.id)}, "{q(component.name, 36)}", '
                     f'"{q(", ".join(component.languages[:2]), 24)}", "{component.files} files")')
    lines.append("  }")
    for system in result.external_systems:
        if app.id in system.apps:
            lines.append(f'  System_Ext({mid(system.id)}, "{q(system.name, 36)}", "{q(system.technology, 30)}")')
    for edge in result.edges:
        if edge.kind == "imports" and edge.source in ids and edge.target in ids:
            lines.append(f'  Rel({mid(edge.source)}, {mid(edge.target)}, "uses")')
    return "\n".join(lines)


def dependency_graph(result: ScanResult, limit: int = 60) -> str:
    components = sorted(result.components, key=lambda c: -c.files)[:limit]
    ids = {c.id for c in components}
    by_app: Dict[str, List] = {}
    for component in components:
        by_app.setdefault(component.app, []).append(component)
    app_names = {a.id: a.name for a in result.apps}
    lines = ["flowchart LR"]
    for app_id, members in by_app.items():
        lines.append(f'  subgraph {mid("app_" + app_id)}["{q(app_names.get(app_id, app_id), 40)}"]')
        for component in members:
            lines.append(f'    {mid(component.id)}["{q(component.name, 40)}<br/>{component.files} files"]')
        lines.append("  end")
    for edge in result.edges:
        if edge.kind == "imports" and edge.source in ids and edge.target in ids:
            label = f'|"{edge.weight}"|' if edge.weight > 3 else ""
            lines.append(f"  {mid(edge.source)} -->{label} {mid(edge.target)}")
    return "\n".join(lines)


def app_dependencies(result: ScanResult) -> str:
    lines = ["flowchart TD"]
    for app in result.apps:
        lines.append(f'  {mid(app.id)}["{q(app.name, 40)}<br/><small>{q(app.kind, 20)}</small>"]')
    for system in result.external_systems:
        shape = f'[("{q(system.name, 34)}")]' if system.kind in ("database", "cache", "storage", "search") \
            else f'[["{q(system.name, 34)}"]]'
        lines.append(f"  {mid(system.id)}{shape}")
    for edge in result.edges:
        if edge.kind in ("depends", "db", "cache", "queue", "storage", "http", "deploy"):
            lines.append(f'  {mid(edge.source)} -->|"{q(edge.label or edge.kind, 24)}"| {mid(edge.target)}')
    lines.extend(_class_defs())
    for app in result.apps:
        lines.append(f"  class {mid(app.id)} app;")
    for system in result.external_systems:
        lines.append(f"  class {mid(system.id)} "
                     f"{'store' if system.kind in ('database', 'cache', 'storage', 'search') else 'ext'};")
    return "\n".join(lines)


def sequence_for_flow(flow: Flow) -> str:
    lines = ["sequenceDiagram", "  autonumber"]
    participants: List[str] = []
    for node in flow.nodes:
        lane = node.lane or "Process"
        if lane not in participants:
            participants.append(lane)
    for lane in participants:
        lines.append(f'  participant {mid(lane)} as {q(lane, 24)}')
    lane_of = {n.id: (n.lane or "Process") for n in flow.nodes}
    label_of = {n.id: n.label for n in flow.nodes}
    for edge in flow.edges:
        source = lane_of.get(edge.source)
        target = lane_of.get(edge.target)
        if not source or not target:
            continue
        arrow = "-->>" if edge.kind in ("message", "data") else "->>"
        text = q(edge.label or label_of.get(edge.target, ""), 46)
        lines.append(f"  {mid(source)}{arrow}{mid(target)}: {text}")
    return "\n".join(lines)


def entity_relationship(result: ScanResult, limit: int = 40) -> Optional[str]:
    tables = [s for s in result.symbols if s.kind == "table"][:limit]
    if not tables:
        return None
    lines = ["erDiagram"]
    for table in tables:
        lines.append(f"  {mid(table.name.upper())} {{")
        lines.append(f'    string id "from {q(table.file, 40)}"')
        lines.append("  }")
    return "\n".join(lines)


def repo_mindmap(result: ScanResult, limit: int = 8) -> str:
    lines = ["mindmap", f"  root(({q(result.meta.repo_name, 30)}))"]
    for app in result.apps[:limit]:
        lines.append(f"    {q(app.name, 30)}")
        lines.append(f"      {q(app.kind, 24)}")
        for language in app.languages[:3]:
            lines.append(f"      {q(language, 20)}")
        for component in sorted([c for c in result.components if c.app == app.id],
                                key=lambda c: -c.files)[:5]:
            lines.append(f"      {q(component.name, 26)}")
    if result.external_systems:
        lines.append("    External systems")
        for system in result.external_systems[:8]:
            lines.append(f"      {q(system.name, 26)}")
    return "\n".join(lines)


def language_pie(result: ScanResult, limit: int = 8) -> str:
    lines = ['pie showData', '  title Lines of code by language']
    for language, loc in list(result.metrics.languages.items())[:limit]:
        lines.append(f'  "{q(language, 24)}" : {loc}')
    return "\n".join(lines)


def severity_pie(result: ScanResult) -> Optional[str]:
    counts = result.metrics.findings_by_severity
    if not counts:
        return None
    lines = ["pie showData", "  title Findings by severity"]
    for severity in ("critical", "high", "medium", "low", "info"):
        if counts.get(severity):
            lines.append(f'  "{severity.title()}" : {counts[severity]}')
    return "\n".join(lines)


def build_all(result: ScanResult, max_flows: int = 14) -> Dict[str, str]:
    out: Dict[str, str] = {
        "mindmap": repo_mindmap(result),
        "languages-pie": language_pie(result),
    }
    if relevance.wants(result, "c4-context"):
        out["c4-context"] = c4_context(result)
    if relevance.wants(result, "c4-container"):
        out["c4-container"] = c4_container(result)
    if relevance.wants(result, "dependency-graph"):
        out["dependency-graph"] = dependency_graph(result)
        out["application-dependencies"] = app_dependencies(result)
    severity = severity_pie(result)
    if severity:
        out["findings-pie"] = severity
    if relevance.wants(result, "entity-relationship"):
        er = entity_relationship(result)
        if er:
            out["entity-relationship"] = er
    if relevance.wants(result, "c4-component"):
        for app in result.apps:
            out[f"c4-component-{app.id}"] = c4_component(result, app)
    if relevance.wants(result, "flows"):
        for flow in result.flows[:relevance.max_flows(result, max_flows)]:
            out[f"flow-{flow.id}"] = flowchart(flow)
            if relevance.wants(result, "sequence"):
                out[f"sequence-{flow.id}"] = sequence_for_flow(flow)
    return out
