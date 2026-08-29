"""C4 model construction (context, container and component levels)."""

from __future__ import annotations

from typing import Dict, List, Sequence

from .model import App, C4Element, C4Model, C4Relation, Component, Edge, Endpoint, ExternalSystem
from .util import slug

STORE_KINDS = {"database", "cache", "storage", "search", "queue"}


def _person_actors(apps: Sequence[App], endpoints: Sequence[Endpoint]) -> List[C4Element]:
    actors: List[C4Element] = []
    kinds = {e.kind for e in endpoints}
    if any(a.kind == "frontend" for a in apps) or "http" in kinds or "graphql" in kinds:
        actors.append(C4Element(id="person-user", name="End user", level="person",
                                description="Uses the system through its web or API surface"))
    if any(a.kind == "cli" for a in apps) or "cli" in kinds:
        actors.append(C4Element(id="person-operator", name="Operator / developer", level="person",
                                description="Runs the command line tooling"))
    if "cron" in kinds or any(e.method == "TASK" for e in endpoints):
        actors.append(C4Element(id="person-scheduler", name="Scheduler", level="person",
                                description="Triggers scheduled work"))
    if not actors:
        actors.append(C4Element(id="person-user", name="User", level="person"))
    return actors


def build(repo_name: str, apps: Sequence[App], components: Sequence[Component],
          app_edges: Sequence[Edge], component_edges: Sequence[Edge],
          systems: Sequence[ExternalSystem], endpoints: Sequence[Endpoint],
          system_edges: Sequence[Edge]) -> C4Model:
    model = C4Model()
    system_id = slug("sys", repo_name)
    model.elements.append(
        C4Element(id=system_id, name=repo_name, level="system",
                  description=f"{len(apps)} deployable unit(s) in this repository",
                  tags=["internal"])
    )
    model.elements.extend(_person_actors(apps, endpoints))

    endpoint_count: Dict[str, int] = {}
    for endpoint in endpoints:
        endpoint_count[endpoint.app] = endpoint_count.get(endpoint.app, 0) + 1

    for app in apps:
        technology = ", ".join(app.languages[:2] + app.frameworks[:2])
        model.elements.append(
            C4Element(
                id=app.id, name=app.name, level="container", parent=system_id,
                technology=technology or "unknown",
                description=(app.description or app.purpose or f"{app.kind} ({app.files} files)")[:300],
                tags=[app.kind],
            )
        )
        for component in components:
            if component.app != app.id or component.files < 2:
                continue
            model.elements.append(
                C4Element(id=component.id, name=component.name, level="component",
                          parent=app.id, technology=", ".join(component.languages[:2]),
                          description=component.description or f"{component.files} files",
                          tags=[component.kind])
            )

    for system in systems:
        level = "database" if system.kind in ("database", "cache", "storage", "search") else "system_ext"
        model.elements.append(
            C4Element(id=system.id, name=system.name, level=level,
                      technology=system.technology, description=system.description[:300],
                      tags=[system.kind])
        )

    for actor in model.elements:
        if actor.level != "person":
            continue
        for app in apps:
            if actor.id == "person-user" and app.kind in ("frontend", "service", "application"):
                model.relations.append(C4Relation(source=actor.id, target=app.id,
                                                  description="Uses", technology="HTTPS"))
            elif actor.id == "person-operator" and app.kind == "cli":
                model.relations.append(C4Relation(source=actor.id, target=app.id, description="Runs"))
            elif actor.id == "person-scheduler" and app.kind == "job":
                model.relations.append(C4Relation(source=actor.id, target=app.id, description="Triggers"))

    for edge in app_edges:
        model.relations.append(
            C4Relation(source=edge.source, target=edge.target,
                       description=edge.label or "Depends on",
                       technology=f"{edge.weight} import(s)" if edge.kind == "imports" else edge.kind)
        )
    for edge in system_edges:
        model.relations.append(
            C4Relation(source=edge.source, target=edge.target,
                       description=edge.label or "Reads from / writes to",
                       technology=edge.kind)
        )
    for edge in component_edges:
        model.relations.append(C4Relation(source=edge.source, target=edge.target,
                                          description="Uses", technology=f"{edge.weight} import(s)"))
    return model


def levels(model: C4Model) -> Dict[str, List[C4Element]]:
    grouped: Dict[str, List[C4Element]] = {}
    for element in model.elements:
        grouped.setdefault(element.level, []).append(element)
    return grouped
