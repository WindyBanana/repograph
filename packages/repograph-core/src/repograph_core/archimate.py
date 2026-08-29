"""ArchiMate 3.2 model construction.

Layers used: business (actors, processes, services), application (components,
services, data objects) and technology (nodes, system software, technology
services). The renderer turns this into Open Exchange XML that Archi imports.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .model import (
    App,
    ArchimateElement,
    ArchimateModel,
    ArchimateRelation,
    Component,
    Edge,
    Endpoint,
    ExternalSystem,
    Flow,
)
from .util import slug, title_case

TECH_KINDS = {"database": "TechnologyService", "cache": "TechnologyService",
              "queue": "TechnologyService", "storage": "TechnologyService",
              "search": "TechnologyService"}


def build(repo_name: str, apps: Sequence[App], components: Sequence[Component],
          app_edges: Sequence[Edge], component_edges: Sequence[Edge],
          systems: Sequence[ExternalSystem], endpoints: Sequence[Endpoint],
          system_edges: Sequence[Edge], flows: Sequence[Flow],
          infrastructure: Dict[str, Any]) -> ArchimateModel:
    model = ArchimateModel()
    seen: set = set()

    def add(element: ArchimateElement) -> None:
        if element.id in seen:
            return
        seen.add(element.id)
        model.elements.append(element)

    def relate(source: str, target: str, rel_type: str, name: str = "") -> None:
        if source in seen and target in seen:
            model.relations.append(ArchimateRelation(source=source, target=target,
                                                     type=rel_type, name=name))

    # -- business layer
    add(ArchimateElement(id="biz-actor-user", name="End user", type="BusinessActor", layer="business"))
    add(ArchimateElement(id="biz-service", name=f"{title_case(repo_name)} service",
                         type="BusinessService", layer="business",
                         documentation="Business capability delivered by this repository"))
    relate("biz-actor-user", "biz-service", "Serving", "uses")

    for flow in flows:
        if not flow.nodes:
            continue
        fid = f"biz-proc-{flow.id}"
        add(ArchimateElement(id=fid, name=flow.name, type="BusinessProcess", layer="business",
                             documentation=flow.description))
        relate(fid, "biz-service", "Realization", "realises")

    # -- application layer
    for app in apps:
        aid = f"app-{app.id}"
        add(ArchimateElement(id=aid, name=app.name, type="ApplicationComponent", layer="application",
                             documentation=(app.description or f"{app.kind}; {app.files} files; "
                                            f"{', '.join(app.languages[:3])}")))
        relate(aid, "biz-service", "Serving", "supports")
        for component in components:
            if component.app != app.id or component.files < 2:
                continue
            cid = f"comp-{component.id}"
            add(ArchimateElement(id=cid, name=f"{app.name} / {component.name}",
                                 type="ApplicationComponent", layer="application",
                                 documentation=f"{component.files} files, {', '.join(component.languages[:2])}"))
            relate(aid, cid, "Composition", "contains")

    grouped: Dict[str, List[Endpoint]] = {}
    for endpoint in endpoints:
        key = f"{endpoint.app}:{endpoint.kind}"
        grouped.setdefault(key, []).append(endpoint)
    for key, members in grouped.items():
        app_id, _, kind = key.partition(":")
        sid = f"app-svc-{slug(key)}"
        add(ArchimateElement(id=sid, name=f"{kind.upper()} interface ({len(members)} operations)",
                             type="ApplicationService", layer="application",
                             documentation="; ".join(sorted({f"{m.method} {m.path}" for m in members})[:20])))
        relate(f"app-{app_id}", sid, "Realization", "exposes")
        relate(sid, "biz-service", "Serving", "serves")

    # -- technology layer
    for system in systems:
        tid = f"tech-{system.id}"
        element_type = TECH_KINDS.get(system.kind, "ApplicationComponent" if system.kind == "api" else "Node")
        layer = "technology" if element_type != "ApplicationComponent" else "application"
        add(ArchimateElement(id=tid, name=system.name, type=element_type, layer=layer,
                             documentation=system.description))
        if system.kind in ("database", "storage", "search"):
            did = f"data-{system.id}"
            add(ArchimateElement(id=did, name=f"{system.name} data", type="DataObject",
                                 layer="application"))
            relate(tid, did, "Access", "stores")

    for container in infrastructure.get("containers", []) or []:
        nid = f"tech-node-{slug(str(container.get('name', '')))}"
        add(ArchimateElement(id=nid, name=f"Container: {container.get('name', '')}", type="Node",
                             layer="technology",
                             documentation=f"image={container.get('image') or container.get('build', '')}"))
    for workload in infrastructure.get("kubernetes", []) or []:
        if workload.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet", "CronJob"):
            continue
        nid = f"tech-k8s-{slug(str(workload.get('name', '')))}"
        add(ArchimateElement(id=nid, name=f"{workload.get('kind')}: {workload.get('name')}",
                             type="Node", layer="technology",
                             documentation=", ".join(workload.get("images", []))))

    for edge in app_edges:
        relate(f"app-{edge.source}", f"app-{edge.target}", "Serving", edge.label or "depends on")
    for edge in component_edges:
        relate(f"comp-{edge.source}", f"comp-{edge.target}", "Serving", "uses")
    for edge in system_edges:
        target = f"tech-{edge.target}"
        relate(f"app-{edge.source}", target, "Access" if edge.kind in ("db", "storage") else "Serving",
               edge.label or edge.kind)
    return model
