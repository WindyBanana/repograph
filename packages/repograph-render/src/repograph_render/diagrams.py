"""Turn a ScanResult into laid-out diagrams."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from repograph_core.model import App, Flow, ScanResult
from repograph_core.narrative import plural

from . import relevance, theme
from .layout import (
    Diagram,
    Edge,
    Group,
    Node,
    force_layout,
    grouped_layout,
    layered_layout,
    normalise,
    size_node,
    swimlane_layout,
)

STORE_KINDS = ("database", "cache", "storage", "search", "queue")


def _tech(app: App) -> str:
    bits = app.languages[:2] + app.frameworks[:2]
    return " · ".join(dict.fromkeys(bits))[:52]


def system_context(result: ScanResult) -> Diagram:
    """C4 level 1 — the system, its users and everything it talks to."""
    diagram = Diagram(title=f"System context — {result.meta.repo_name}", kind="c4-context",
                      subtitle="Who uses this system and which external systems it depends on")
    persons = [e for e in result.c4.elements if e.level == "person"]
    externals = [e for e in result.c4.elements if e.level in ("system_ext", "database")]

    system_node = Node(id="__system__", label=result.meta.repo_name, kind="system",
                       sublabel=f"{len(result.apps)} app(s) · "
                                f"{', '.join(result.summary.get('primary_languages', [])[:3])}")
    nodes = [system_node]
    edges: List[Edge] = []
    for person in persons:
        node = Node(id=person.id, label=person.name, kind="person", sublabel=person.description[:44])
        nodes.append(node)
        edges.append(Edge(person.id, "__system__", label="uses"))
    shown = externals[:16]
    for element in shown:
        node = Node(id=element.id, label=element.name, kind=_ext_kind(element.tags),
                    sublabel=element.technology[:40])
        nodes.append(node)
        edges.append(Edge("__system__", element.id, label=_ext_label(element.tags)))
    if len(externals) > len(shown):
        rest = len(externals) - len(shown)
        nodes.append(Node(id="__more__", label=f"+{rest} more external systems",
                          kind="external", sublabel="see the external systems table"))
        edges.append(Edge("__system__", "__more__"))

    for node in nodes:
        size_node(node, min_w=140, max_w=230)
    system_node.w = max(system_node.w, 240)
    system_node.h = max(system_node.h, 80)
    width, height = layered_layout(nodes, edges, node_sep=40, layer_sep=120, max_per_layer=6)
    diagram.nodes, diagram.edges, diagram.width, diagram.height = nodes, edges, width, height
    diagram.legend = [("Person", theme.KINDS["person"][0]), ("This system", theme.KINDS["system"][0]),
                      ("Datastore", theme.KINDS["database"][0]), ("External system", theme.KINDS["external"][0])]
    normalise(diagram)
    return diagram


def _ext_kind(tags: Sequence[str]) -> str:
    for tag in tags:
        if tag in ("database", "cache", "storage", "search"):
            return "database"
        if tag == "queue":
            return "queue"
    return "external"


def _ext_label(tags: Sequence[str]) -> str:
    for tag in tags:
        if tag in ("database", "cache", "storage", "search"):
            return "reads/writes"
        if tag == "queue":
            return "publishes/consumes"
    return "calls"


def container_diagram(result: ScanResult) -> Diagram:
    """C4 level 2 — the deployable units and the stores they use."""
    diagram = Diagram(title=f"Containers — {result.meta.repo_name}", kind="c4-container",
                      subtitle="Deployable/publishable units, their technology and their data stores")
    nodes: List[Node] = []
    edges: List[Edge] = []
    for app in result.apps:
        nodes.append(Node(id=app.id, label=app.name, kind=_app_kind(app.kind),
                          sublabel=f"{_tech(app)} · {app.files} files",
                          meta={"kind": app.kind, "loc": app.loc}))
    for system in result.external_systems:
        if system.kind in STORE_KINDS or len(system.apps) > 0:
            nodes.append(Node(id=system.id, label=system.name,
                              kind="database" if system.kind in ("database", "cache", "storage", "search")
                              else ("queue" if system.kind == "queue" else "external"),
                              sublabel=system.technology[:40]))
    known = {n.id for n in nodes}
    for edge in result.edges:
        if edge.source in known and edge.target in known and edge.kind in ("depends", "db", "cache",
                                                                          "queue", "storage", "http", "deploy"):
            edges.append(Edge(edge.source, edge.target, label=edge.label or edge.kind,
                              weight=edge.weight, kind=edge.kind))
    for node in nodes:
        size_node(node, min_w=150, max_w=250)
    width, height = layered_layout(nodes, edges, node_sep=44, layer_sep=118, max_per_layer=6)
    diagram.nodes, diagram.edges, diagram.width, diagram.height = nodes, edges, width, height
    diagram.legend = [("Application", theme.KINDS["app"][0]), ("Frontend", theme.KINDS["frontend"][0]),
                      ("Datastore", theme.KINDS["database"][0]), ("External", theme.KINDS["external"][0])]
    normalise(diagram)
    return diagram


def _app_kind(kind: str) -> str:
    return kind if kind in theme.KINDS else "app"


def component_diagram(result: ScanResult, app: App, max_nodes: int = 40) -> Optional[Diagram]:
    """C4 level 3 — inside one application."""
    components = [c for c in result.components if c.app == app.id]
    if not components:
        return None
    components = sorted(components, key=lambda c: -c.files)[:max_nodes]
    ids = {c.id for c in components}
    nodes = [Node(id=c.id, label=c.name, kind="component",
                  sublabel=f"{c.files} files · {c.loc} LOC" + (f" · {c.languages[0]}" if c.languages else ""),
                  meta={"path": c.path}) for c in components]
    edges = [Edge(e.source, e.target, weight=e.weight, label=str(e.weight) if e.weight > 4 else "")
             for e in result.edges if e.kind == "imports" and e.source in ids and e.target in ids]
    systems = [s for s in result.external_systems if app.id in s.apps][:10]
    for system in systems:
        nodes.append(Node(id=f"{app.id}-{system.id}", label=system.name,
                          kind="database" if system.kind in ("database", "cache", "storage", "search")
                          else "external", sublabel=system.technology[:36]))
    for node in nodes:
        size_node(node, min_w=140, max_w=230)
    width, height = layered_layout(nodes, edges, node_sep=38, layer_sep=104, max_per_layer=7)
    diagram = Diagram(title=f"Components — {app.name}", kind="c4-component",
                      subtitle=f"{len(components)} components · {app.architecture_style}",
                      nodes=nodes, edges=edges, width=width, height=height)
    normalise(diagram)
    return diagram


def dependency_graph(result: ScanResult, max_nodes: int = 120) -> Diagram:
    """Force-directed view of every component, grouped by application."""
    components = sorted(result.components, key=lambda c: -c.files)[:max_nodes]
    ids = {c.id for c in components}
    app_names = {a.id: a.name for a in result.apps}
    nodes = [Node(id=c.id, label=c.name, kind="component", group=c.app,
                  sublabel=app_names.get(c.app, ""), weight=max(1, c.files),
                  meta={"files": c.files, "loc": c.loc, "app": app_names.get(c.app, "")})
             for c in components]
    edges = [Edge(e.source, e.target, weight=e.weight)
             for e in result.edges if e.kind == "imports" and e.source in ids and e.target in ids]
    for node in nodes:
        size_node(node, min_w=110, max_w=190, font_size=11)
    width, height = force_layout(nodes, edges, width=1500, height=950)
    diagram = Diagram(title=f"Component dependency graph — {result.meta.repo_name}", kind="graph",
                      subtitle=f"{len(nodes)} components · {len(edges)} dependencies",
                      nodes=nodes, edges=edges, width=width, height=height)
    normalise(diagram)
    return diagram


def app_landscape(result: ScanResult) -> Diagram:
    """Applications as containers with their components inside."""
    groups = [Group(id=a.id, label=f"{a.name} ({a.kind})", kind="app") for a in result.apps]
    nodes: List[Node] = []
    for app in result.apps:
        for component in sorted([c for c in result.components if c.app == app.id],
                                key=lambda c: -c.files)[:12]:
            nodes.append(Node(id=component.id, label=component.name, kind="component",
                              group=app.id, sublabel=f"{component.files} files"))
    ids = {n.id for n in nodes}
    edges = [Edge(e.source, e.target, weight=e.weight)
             for e in result.edges if e.kind == "imports" and e.source in ids and e.target in ids]
    for node in nodes:
        size_node(node, min_w=130, max_w=190, font_size=11)
    width, height = grouped_layout(nodes, edges, groups)
    diagram = Diagram(title=f"Application landscape — {result.meta.repo_name}", kind="landscape",
                      subtitle=f"{len(result.apps)} application(s), top components each",
                      nodes=nodes, edges=edges, groups=groups, width=width, height=height)
    normalise(diagram)
    return diagram


def integration_map(result: ScanResult) -> Diagram:
    """Every external dependency of the repository, by category."""
    nodes = [Node(id="__repo__", label=result.meta.repo_name, kind="system",
                  sublabel="this repository")]
    edges: List[Edge] = []
    for system in result.external_systems:
        kind = system.kind if system.kind in theme.KINDS else "external"
        nodes.append(Node(id=system.id, label=system.name, kind=kind,
                          sublabel=f"{system.technology} · {len(system.evidence)} refs"))
        edges.append(Edge("__repo__", system.id, label=system.kind, weight=len(system.evidence)))
    for node in nodes:
        size_node(node, min_w=140, max_w=210, font_size=11.5)
    width, height = force_layout(nodes, edges, width=1300, height=850, seed=11)
    diagram = Diagram(title=f"External systems — {result.meta.repo_name}", kind="integrations",
                      subtitle=f"{len(result.external_systems)} systems detected from code and configuration",
                      nodes=nodes, edges=edges, width=width, height=height)
    normalise(diagram)
    return diagram


def deployment_diagram(result: ScanResult) -> Optional[Diagram]:
    infra = result.infrastructure or {}
    containers = infra.get("containers") or []
    workloads = [k for k in (infra.get("kubernetes") or [])
                 if k.get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "CronJob", "Service", "Ingress")]
    if not containers and not workloads:
        return None
    nodes: List[Node] = []
    edges: List[Edge] = []
    for container in containers:
        name = str(container.get("name", ""))
        nodes.append(Node(id=f"ct-{name}", label=name, kind="container",
                          sublabel=(container.get("image") or f"build {container.get('build','')}")[:44]))
    for container in containers:
        for target in container.get("depends_on", []):
            edges.append(Edge(f"ct-{container.get('name')}", f"ct-{target}", label="depends on", dashed=True))
    for workload in workloads:
        wid = f"k8s-{workload.get('kind')}-{workload.get('name')}"
        nodes.append(Node(id=wid, label=f"{workload.get('name')}", kind="infra",
                          sublabel=f"{workload.get('kind')} · {', '.join(workload.get('images', []))[:36]}"))
    for node in nodes:
        size_node(node, min_w=150, max_w=240)
    width, height = layered_layout(nodes, edges, node_sep=40, layer_sep=100, max_per_layer=5)
    diagram = Diagram(title=f"Deployment view — {result.meta.repo_name}", kind="deployment",
                      subtitle=f"{len(containers)} compose service(s), {len(workloads)} Kubernetes object(s)",
                      nodes=nodes, edges=edges, width=width, height=height)
    normalise(diagram)
    return diagram


def flow_diagram(flow: Flow) -> Diagram:
    lanes = flow.lanes or sorted({n.lane for n in flow.nodes if n.lane}) or ["Process"]
    nodes = [Node(id=n.id, label=n.label, kind=n.kind, group=n.lane or lanes[0],
                  sublabel=(n.file.rsplit("/", 1)[-1] if n.file else ""))
             for n in flow.nodes]
    for node in nodes:
        size_node(node, min_w=128, max_w=200, font_size=11.5)
        if node.kind == "decision":
            node.w = max(node.w, 150)
            node.h = max(node.h, 78)
    edges = [Edge(e.source, e.target, label=e.label, kind=e.kind,
                  dashed=e.kind in ("message", "data")) for e in flow.edges]
    width, height = swimlane_layout(nodes, edges, lanes, lane_height=155)
    diagram = Diagram(title=flow.name, kind="flow", subtitle=flow.description[:150],
                      nodes=nodes, edges=edges, width=width, height=height,
                      lanes=list(lanes), lane_height=155)
    diagram.legend = [("Start", theme.KINDS["start"][0]), ("Task", theme.KINDS["task"][0]),
                      ("Decision", theme.KINDS["decision"][0]), ("Data store", theme.KINDS["database"][0]),
                      ("End", theme.KINDS["end"][0])]
    return diagram


def layer_diagram(result: ScanResult, max_nodes: int = 60) -> Diagram:
    """Components stacked by dependency depth — the de facto layering."""
    layers = result.layers or {}
    components = sorted(result.components, key=lambda c: (-layers.get(c.id, 0), -c.files))[:max_nodes]
    ids = {c.id for c in components}
    nodes = [Node(id=c.id, label=c.name, kind="module", sublabel=f"layer {layers.get(c.id, 0)}")
             for c in components]
    edges = [Edge(e.source, e.target, weight=e.weight)
             for e in result.edges if e.kind == "imports" and e.source in ids and e.target in ids]
    for node in nodes:
        size_node(node, min_w=130, max_w=200, font_size=11.5)
    width, height = layered_layout(nodes, edges, node_sep=34, layer_sep=90, max_per_layer=8)
    diagram = Diagram(title="Dependency layers", kind="layers",
                      subtitle="Layer 0 depends on nothing else in the repository",
                      nodes=nodes, edges=edges, width=width, height=height)
    normalise(diagram)
    return diagram


def describe(name: str, diagram: Diagram, result: ScanResult) -> Dict[str, str]:
    """What a diagram shows, and the one thing worth noticing in it.

    The "notice" line is computed from the same graph the diagram was drawn from,
    so it points at something real rather than restating the caption.
    """
    metrics = result.metrics
    edges = [e for e in result.edges if e.kind == "imports"]
    fan_in: Dict[str, int] = {}
    for edge in edges:
        fan_in[edge.target] = fan_in.get(edge.target, 0) + 1
    names = {c.id: c.name for c in result.components}

    def busiest_component() -> str:
        if not fan_in:
            return ""
        target, count = max(fan_in.items(), key=lambda kv: kv[1])
        return (f"{names.get(target, target)} is depended on by "
                f"{plural(count, 'other component')} — changes there reach furthest.")

    def busiest_system() -> str:
        systems = sorted(result.external_systems, key=lambda s: -len(s.apps))
        if not systems or not systems[0].apps:
            return ""
        top = systems[0]
        if len(top.apps) < 2:
            return ""
        return f"{top.name} is used by {len(top.apps)} of the {metrics.apps} applications, so an " \
               f"outage there is felt in several places."

    what, notice = "", ""
    if name == "c4-context":
        persons = sum(1 for el in result.c4.elements if el.level == "person")
        what = (f"The whole repository as a single box, the {plural(persons, 'kind')} of user "
                f"around it, and the {plural(metrics.external_systems, 'system')} outside it that "
                f"it depends on. Read it to see what is outside your control.")
        kinds = sorted({s.kind for s in result.external_systems})
        notice = (f"The external systems fall into {len(kinds)} categories: {', '.join(kinds)}."
                  if kinds else "Nothing external was detected — this repository stands alone.")
    elif name == "c4-container":
        what = (f"The {plural(metrics.apps, 'separately built or deployed piece')} of software "
                f"and the stores and services each one talks to.")
        notice = busiest_system() or "Each application has its own set of backing systems."
    elif name.startswith("components-"):
        app = next((a for a in result.apps if name.endswith(a.id)), None)
        what = (f"Inside {app.name if app else 'one application'}: its components and the imports "
                f"between them, plus the external systems it reaches.")
        notice = (f"Its architecture reads as: {app.architecture_style}." if app else "")
    elif name == "application-landscape":
        what = ("Every application as a container, with its largest components inside, and the "
                "dependencies that cross application boundaries.")
        crossing = len([e for e in result.edges if e.kind == "depends"])
        notice = (f"{plural(crossing, 'dependency', 'dependencies')} cross application "
                  f"boundaries — those are the places a change in one app can break another."
                  if crossing else "No application depends on another; they are independent.")
    elif name == "dependency-graph":
        what = (f"All {plural(len(diagram.nodes), 'component')} laid out by how they pull on "
                f"each other. Bigger circles hold more files; thicker lines mean more imports.")
        notice = busiest_component() or "No component dominates the graph."
    elif name == "dependency-layers":
        what = ("The same components stacked by depth: layer 0 depends on nothing else here, and "
                "each layer above depends on the ones below.")
        notice = (f"{plural(metrics.cycles, 'cycle')} found; a cycle means the layering is not "
                  f"actually respected." if metrics.cycles
                  else "No cycles: the dependencies form a clean hierarchy.")
    elif name == "external-systems":
        what = ("Every database, queue, store and third-party service this code refers to, "
                "grouped by what it is for.")
        notice = busiest_system() or "Each system is used by a single application."
    elif name == "deployment":
        infra = result.infrastructure or {}
        what = (f"How this is packaged and run: "
                f"{plural(len(infra.get('containers') or []), 'composed service')} and "
                f"{plural(len(infra.get('kubernetes') or []), 'Kubernetes object')}.")
        notice = "Arrows are declared start-up dependencies, not runtime traffic."
    elif name.startswith("flow-"):
        flow_id = name[len("flow-"):]
        flow = result.flow_by_id(flow_id)
        what = ("One process from its trigger to its end, with each step in the architectural "
                "layer it belongs to.")
        if flow is not None:
            decisions = [n.label for n in flow.nodes if n.kind == "decision"]
            stores = [n.label for n in flow.nodes if n.kind == "datastore"]
            notice = ("The diamonds are guard clauses found in the entry file: "
                      + "; ".join(decisions) + "." if decisions else
                      "No guard clauses were found in the entry file — this path has no explicit "
                      "validation or error handling.")
            if stores:
                notice += f" It reaches {', '.join(stores)}."
    else:
        what = diagram.subtitle
    return {"what": what, "notice": notice}


def build_all(result: ScanResult, max_flows: int = 14) -> Dict[str, Diagram]:
    """Every diagram this repository actually warrants, keyed by file-safe name.

    A repository of markdown guides gets no container diagram; a single library
    gets no application landscape. The scan decides (see repograph_core.profile)
    and records why.
    """
    out: Dict[str, Diagram] = {}
    builders = (
        ("c4-context", lambda: system_context(result)),
        ("c4-container", lambda: container_diagram(result)),
        ("dependency-graph", lambda: dependency_graph(result)),
        ("application-landscape", lambda: app_landscape(result)),
        ("external-systems", lambda: integration_map(result)),
        ("dependency-layers", lambda: layer_diagram(result)),
        ("deployment", lambda: deployment_diagram(result)),
    )
    for name, builder in builders:
        if not relevance.wants(result, name):
            continue
        diagram = builder()
        if diagram is not None and diagram.nodes:
            out[name] = diagram

    if relevance.wants(result, "c4-component"):
        for app in result.apps:
            diagram = component_diagram(result, app)
            if diagram is not None and diagram.nodes:
                out[f"components-{app.id}"] = diagram

    if relevance.wants(result, "flows"):
        for flow in result.flows[:relevance.max_flows(result, max_flows)]:
            out[f"flow-{flow.id}"] = flow_diagram(flow)
    return out
