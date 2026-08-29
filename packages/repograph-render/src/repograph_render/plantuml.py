"""PlantUML sources: C4-PlantUML views, a component view and an ArchiMate view."""

from __future__ import annotations

import re
from typing import Dict, List

from repograph_core.model import App, Flow, ScanResult

from . import relevance

C4_INCLUDE = "!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/"
ARCHIMATE_INCLUDE = "!include <archimate/Archimate>"

_ID = re.compile(r"[^A-Za-z0-9_]")


def pid(value: str) -> str:
    cleaned = _ID.sub("_", value).strip("_") or "n"
    return ("n_" + cleaned) if cleaned[0].isdigit() else cleaned[:60]


def esc(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split()).replace('"', "'")
    return text[: limit - 1] + "…" if len(text) > limit else text


def c4_context(result: ScanResult) -> str:
    lines = ["@startuml C4_Context", f"{C4_INCLUDE}C4_Context.puml", "",
             f'title System context — {esc(result.meta.repo_name, 60)}', ""]
    for element in result.c4.elements:
        if element.level == "person":
            lines.append(f'Person({pid(element.id)}, "{esc(element.name, 40)}", "{esc(element.description)}")')
    system = pid("sys_" + result.meta.repo_name)
    lines.append(f'System({system}, "{esc(result.meta.repo_name, 40)}", '
                 f'"{esc(result.summary.get("purpose", ""), 110)}")')
    for element in result.c4.elements:
        if element.level == "database":
            lines.append(f'SystemDb_Ext({pid(element.id)}, "{esc(element.name, 40)}", "{esc(element.technology, 40)}")')
        elif element.level == "system_ext":
            lines.append(f'System_Ext({pid(element.id)}, "{esc(element.name, 40)}", "{esc(element.technology, 40)}")')
    lines.append("")
    for element in result.c4.elements:
        if element.level == "person":
            lines.append(f'Rel({pid(element.id)}, {system}, "Uses")')
    for element in result.c4.elements:
        if element.level in ("system_ext", "database"):
            lines.append(f'Rel({system}, {pid(element.id)}, "{esc(element.technology or "uses", 30)}")')
    lines.append("")
    lines.append("SHOW_LEGEND()")
    lines.append("@enduml")
    return "\n".join(lines)


def c4_container(result: ScanResult) -> str:
    lines = ["@startuml C4_Container", f"{C4_INCLUDE}C4_Container.puml", "",
             f'title Containers — {esc(result.meta.repo_name, 60)}', ""]
    for element in result.c4.elements:
        if element.level == "person":
            lines.append(f'Person({pid(element.id)}, "{esc(element.name, 40)}", "{esc(element.description)}")')
    lines.append(f'System_Boundary(repo, "{esc(result.meta.repo_name, 40)}") {{')
    for app in result.apps:
        tech = esc(" · ".join(app.languages[:2] + app.frameworks[:2]), 40)
        macro = "ContainerDb" if app.kind == "database" else "Container"
        lines.append(f'  {macro}({pid(app.id)}, "{esc(app.name, 36)}", "{tech}", '
                     f'"{esc(app.description or app.kind, 90)}")')
    lines.append("}")
    for system in result.external_systems:
        if system.kind in ("database", "cache", "storage", "search"):
            lines.append(f'ContainerDb_Ext({pid(system.id)}, "{esc(system.name, 36)}", '
                         f'"{esc(system.technology, 30)}", "")')
        else:
            lines.append(f'System_Ext({pid(system.id)}, "{esc(system.name, 36)}", "{esc(system.technology, 30)}")')
    lines.append("")
    for edge in result.edges:
        if edge.kind in ("depends", "db", "cache", "queue", "storage", "http", "deploy"):
            lines.append(f'Rel({pid(edge.source)}, {pid(edge.target)}, "{esc(edge.label or edge.kind, 30)}")')
    lines.append("SHOW_LEGEND()")
    lines.append("@enduml")
    return "\n".join(lines)


def c4_component(result: ScanResult, app: App, limit: int = 30) -> str:
    components = sorted([c for c in result.components if c.app == app.id], key=lambda c: -c.files)[:limit]
    ids = {c.id for c in components}
    lines = ["@startuml C4_Component", f"{C4_INCLUDE}C4_Component.puml", "",
             f'title Components — {esc(app.name, 50)}', "",
             f'Container_Boundary(app, "{esc(app.name, 40)}") {{']
    for component in components:
        lines.append(f'  Component({pid(component.id)}, "{esc(component.name, 36)}", '
                     f'"{esc(", ".join(component.languages[:2]), 24)}", '
                     f'"{component.files} files, {component.loc} LOC")')
    lines.append("}")
    for system in result.external_systems:
        if app.id in system.apps:
            lines.append(f'System_Ext({pid(system.id)}, "{esc(system.name, 36)}", "{esc(system.technology, 30)}")')
    for edge in result.edges:
        if edge.kind == "imports" and edge.source in ids and edge.target in ids:
            lines.append(f'Rel({pid(edge.source)}, {pid(edge.target)}, "uses")')
    lines.append("@enduml")
    return "\n".join(lines)


def component_view(result: ScanResult, limit: int = 60) -> str:
    components = sorted(result.components, key=lambda c: -c.files)[:limit]
    ids = {c.id for c in components}
    by_app: Dict[str, List] = {}
    for component in components:
        by_app.setdefault(component.app, []).append(component)
    app_names = {a.id: a.name for a in result.apps}
    lines = ["@startuml components", "skinparam componentStyle rectangle",
             "skinparam shadowing false", "left to right direction", ""]
    for app_id, members in by_app.items():
        lines.append(f'package "{esc(app_names.get(app_id, app_id), 40)}" {{')
        for component in members:
            lines.append(f'  [{esc(component.name, 36)}] as {pid(component.id)}')
        lines.append("}")
    for edge in result.edges:
        if edge.kind == "imports" and edge.source in ids and edge.target in ids:
            lines.append(f"{pid(edge.source)} --> {pid(edge.target)}")
    lines.append("@enduml")
    return "\n".join(lines)


def archimate_view(result: ScanResult, limit: int = 60) -> str:
    lines = ["@startuml archimate", ARCHIMATE_INCLUDE, "skinparam shadowing false",
             "left to right direction", ""]
    macro = {
        "BusinessActor": "Business_Actor", "BusinessService": "Business_Service",
        "BusinessProcess": "Business_Process", "ApplicationComponent": "Application_Component",
        "ApplicationService": "Application_Service", "DataObject": "Application_DataObject",
        "TechnologyService": "Technology_Service", "Node": "Technology_Node",
        "SystemSoftware": "Technology_SystemSoftware",
    }
    included = set()
    for element in result.archimate.elements[:limit]:
        fn = macro.get(element.type, "Application_Component")
        lines.append(f'{fn}({pid(element.id)}, "{esc(element.name, 44)}")')
        included.add(element.id)
    lines.append("")
    arrows = {"Composition": "*-->", "Serving": "-->", "Access": "..>", "Realization": "..|>",
              "Triggering": "-->", "Association": "--"}
    for relation in result.archimate.relations:
        if relation.source in included and relation.target in included:
            arrow = arrows.get(relation.type, "-->")
            label = f' : {esc(relation.name, 24)}' if relation.name else ""
            lines.append(f"{pid(relation.source)} {arrow} {pid(relation.target)}{label}")
    lines.append("@enduml")
    return "\n".join(lines)


def activity(flow: Flow) -> str:
    """PlantUML activity diagram with swimlanes, decisions and end events."""
    lines = ["@startuml activity", "skinparam shadowing false", f"title {esc(flow.name, 60)}", "start"]
    outgoing: Dict[str, List] = {}
    for edge in flow.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    nodes = {n.id: n for n in flow.nodes}
    visited = set()

    def emit(node_id: str, depth: int = 0) -> None:
        if node_id in visited or depth > 40:
            return
        visited.add(node_id)
        node = nodes.get(node_id)
        if node is None:
            return
        if node.lane:
            lines.append(f"|{esc(node.lane, 24)}|")
        if node.kind == "decision":
            lines.append(f"if ({esc(node.label, 44)}) then (yes)")
            branches = outgoing.get(node_id, [])
            yes = [e for e in branches if e.label != "no"]
            no = [e for e in branches if e.label == "no"]
            for edge in yes:
                emit(edge.target, depth + 1)
            lines.append("else (no)")
            for edge in no:
                target = nodes.get(edge.target)
                if target is not None:
                    lines.append(f":{esc(target.label, 44)};")
                    visited.add(edge.target)
            lines.append("stop")
            lines.append("endif")
            return
        if node.kind == "end":
            lines.append(f":{esc(node.label, 44)};")
            return
        if node.kind != "start":
            lines.append(f":{esc(node.label, 44)};")
        for edge in outgoing.get(node_id, []):
            emit(edge.target, depth + 1)

    start = next((n.id for n in flow.nodes if n.kind == "start"), flow.nodes[0].id if flow.nodes else "")
    if start:
        emit(start)
    lines.append("stop")
    lines.append("@enduml")
    return "\n".join(lines)


def build_all(result: ScanResult, max_flows: int = 10) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if relevance.wants(result, "c4-context"):
        out["c4-context"] = c4_context(result)
    if relevance.wants(result, "c4-container"):
        out["c4-container"] = c4_container(result)
    if relevance.wants(result, "c4-component"):
        out["components"] = component_view(result)
        for app in result.apps:
            out[f"c4-component-{app.id}"] = c4_component(result, app)
    if relevance.wants(result, "archimate"):
        out["archimate"] = archimate_view(result)
    if relevance.wants(result, "flows"):
        for flow in result.flows[:relevance.max_flows(result, max_flows)]:
            out[f"activity-{flow.id}"] = activity(flow)
    return out
