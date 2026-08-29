"""Process-flow inference.

There is no AI here: a flow is reconstructed by walking the import graph out
from an entrypoint (an HTTP route, a queue consumer, a CLI command), sorting the
files it reaches into architectural lanes, and attaching the datastores and
external systems those files touch. Guard clauses and error handling in the
entry file become decision diamonds, which is what makes the output read like a
BPMN process rather than a call tree.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .model import App, Edge, Endpoint, ExternalSystem, Flow, FlowEdge, FlowNode
from .util import slug, title_case

LANES = ["Client", "Interface", "Application", "Domain", "Data", "External"]

_LANE_RULES: List[Tuple[str, str]] = [
    (r"(^|/)(controllers?|handlers?|routes?|api|endpoints?|resources?|views?|graphql|rpc|web|http|"
     r"presentation|delivery|transport)(/|$)", "Interface"),
    (r"(^|/)(services?|usecases?|use_cases|application|app|interactors?|commands?|queries|"
     r"workflows?|orchestrat\w*|jobs?|tasks?|workers?|consumers?|producers?)(/|$)", "Application"),
    (r"(^|/)(domain|models?|entities|core|business|logic|aggregates?|value_objects?)(/|$)", "Domain"),
    (r"(^|/)(repositor(y|ies)|dao|store|stores|persistence|db|database|data|migrations?|schema|"
     r"orm|queries|infrastructure/db)(/|$)", "Data"),
    (r"(^|/)(clients?|integrations?|adapters?|gateways?|external|providers?|connectors?|sdk)(/|$)", "External"),
    (r"(^|/)(components?|pages?|screens?|ui|frontend|templates?|static|assets)(/|$)", "Client"),
]

_FILE_HINTS: List[Tuple[str, str]] = [
    (r"(controller|handler|router|route|resolver|endpoint)", "Interface"),
    (r"(service|usecase|use_case|interactor|manager|orchestrator|processor)", "Application"),
    (r"(model|entity|domain|schema|dto|aggregate)", "Domain"),
    (r"(repository|repo|dao|store|db|database|query|migration)", "Data"),
    (r"(client|gateway|adapter|integration|provider|connector|api_client)", "External"),
]

_DECISION_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)\b(?:if\s+not\s+\w*auth|unauthorized|forbidden|401|403|require_?auth|is_authenticated|"
     r"@login_required|authorize|permission)", "Authenticated & authorised?"),
    (r"(?i)\b(?:validate|is_valid|schema\.parse|ValidationError|400|BadRequest|zod\.|pydantic)", "Input valid?"),
    (r"(?i)\b(?:if\s+err\s*!=\s*nil|except\s+\w+|catch\s*\(|rescue|try\s*\{|\.catch\()", "Operation succeeded?"),
    (r"(?i)\b(?:cache\.get|cached|from_cache|redis\.get)", "Cache hit?"),
    (r"(?i)\b(?:exists|find_by|get_or_404|NotFound|404)", "Record found?"),
    (r"(?i)\b(?:rate_?limit|throttle|quota)", "Within rate limit?"),
    (r"(?i)\b(?:idempoten|already_processed|duplicate)", "Already processed?"),
]

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def classify_lane(rel: str, default: str = "Application") -> str:
    lowered = "/" + rel.lower()
    for pattern, lane in _LANE_RULES:
        if re.search(pattern, lowered):
            return lane
    name = rel.rsplit("/", 1)[-1].lower()
    for pattern, lane in _FILE_HINTS:
        if re.search(pattern, name):
            return lane
    return default


class FlowBuilder:
    def __init__(self, apps: Sequence[App], endpoints: Sequence[Endpoint],
                 file_edges: Sequence[Edge], file_app: Dict[str, str],
                 systems_by_file: Dict[str, List[str]],
                 systems: Sequence[ExternalSystem], file_text_probe=None) -> None:
        self.apps = list(apps)
        self.endpoints = list(endpoints)
        self.file_app = file_app
        self.systems_by_file = systems_by_file
        self.systems = {s.id: s for s in systems}
        self.probe = file_text_probe or (lambda rel: "")
        self.out_edges: Dict[str, List[str]] = defaultdict(list)
        for edge in file_edges:
            self.out_edges[edge.source].append(edge.target)

    # ------------------------------------------------------------- helpers
    def _reachable(self, start: str, max_depth: int = 4, max_nodes: int = 60) -> List[Tuple[str, int]]:
        seen: Set[str] = {start}
        order: List[Tuple[str, int]] = []
        frontier = [(start, 0)]
        while frontier and len(order) < max_nodes:
            node, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            for target in self.out_edges.get(node, []):
                if target in seen:
                    continue
                seen.add(target)
                order.append((target, depth + 1))
                frontier.append((target, depth + 1))
        return order

    def _systems_for(self, files: Iterable[str]) -> List[str]:
        found: List[str] = []
        for rel in files:
            for sid in self.systems_by_file.get(rel, []):
                if sid not in found:
                    found.append(sid)
        return found

    def _decisions(self, rel: str, method: str) -> List[str]:
        text = self.probe(rel) or ""
        found = []
        for pattern, label in _DECISION_PATTERNS:
            if re.search(pattern, text):
                found.append(label)
        if method in _WRITE_METHODS and "Input valid?" not in found:
            found.insert(0, "Input valid?")
        return found[:3]

    # --------------------------------------------------------------- flows
    def build(self, max_flows_per_app: int = 8) -> List[Flow]:
        flows: List[Flow] = []
        by_app: Dict[str, List[Endpoint]] = defaultdict(list)
        for endpoint in self.endpoints:
            by_app[endpoint.app].append(endpoint)

        for app in self.apps:
            endpoints = by_app.get(app.id, [])
            groups = self._group(endpoints)
            for name, members in list(groups.items())[:max_flows_per_app]:
                flow = self._endpoint_flow(app, name, members)
                if flow is not None:
                    flows.append(flow)
            overview = self._app_overview(app, endpoints)
            if overview is not None:
                flows.insert(len(flows) - len(groups), overview) if groups else flows.append(overview)
        return flows

    @staticmethod
    def _group(endpoints: Sequence[Endpoint]) -> Dict[str, List[Endpoint]]:
        groups: Dict[str, List[Endpoint]] = defaultdict(list)
        for endpoint in endpoints:
            if endpoint.kind in ("event", "cli", "cron", "function"):
                key = f"{endpoint.kind}:{endpoint.path.split('/')[0][:40] or endpoint.handler}"
            else:
                parts = [p for p in endpoint.path.split("/") if p and not p.startswith(("{", ":", "<"))]
                key = parts[0] if parts else "root"
                if key in ("api", "v1", "v2", "graphql") and len(parts) > 1:
                    key = parts[1]
            groups[key].append(endpoint)
        return dict(sorted(groups.items(), key=lambda kv: -len(kv[1])))

    def _endpoint_flow(self, app: App, name: str, endpoints: Sequence[Endpoint]) -> Optional[Flow]:
        primary = endpoints[0]
        if not primary.file:
            return None
        kind = primary.kind
        flow = Flow(
            id=slug("flow", app.id, kind, name),
            name=f"{title_case(name)} {'process' if kind in ('event', 'cli') else 'request flow'}",
            app=app.id,
            description=(
                f"Reconstructed from {len(endpoints)} {kind} entrypoint(s) in {app.name}: "
                + ", ".join(sorted({f"{e.method} {e.path}" for e in endpoints})[:6])
            ),
            entrypoint=primary.file,
            lanes=[],
        )
        nodes: List[FlowNode] = []
        edges: List[FlowEdge] = []
        lanes_used: List[str] = []

        def add_node(node: FlowNode) -> FlowNode:
            nodes.append(node)
            if node.lane and node.lane not in lanes_used:
                lanes_used.append(node.lane)
            return node

        trigger_lane = "Client" if kind in ("http", "graphql", "websocket") else "External"
        trigger_label = {
            "http": "Client sends request", "graphql": "GraphQL operation received",
            "websocket": "Socket message received", "event": "Message / event received",
            "cli": "Command invoked", "cron": "Schedule fires", "function": "Function invoked",
            "grpc": "gRPC call received", "rpc": "RPC call received",
        }.get(kind, "Request received")
        start = add_node(FlowNode(id="start", label=trigger_label, kind="start", lane=trigger_lane))

        entry = add_node(FlowNode(
            id="entry",
            label=_endpoint_label(endpoints),
            kind="task",
            lane=classify_lane(primary.file, "Interface"),
            file=primary.file,
            line=primary.line,
        ))
        edges.append(FlowEdge(source=start.id, target=entry.id))

        previous = entry
        for index, label in enumerate(self._decisions(primary.file, primary.method)):
            decision = add_node(FlowNode(id=f"d{index}", label=label, kind="decision",
                                         lane=entry.lane, file=primary.file))
            edges.append(FlowEdge(
                source=previous.id, target=decision.id,
                label="yes" if previous.kind == "decision" else "",
                kind="conditional" if previous.kind == "decision" else "sequence",
            ))
            reject = add_node(FlowNode(id=f"d{index}-no", label=_reject_label(label), kind="end",
                                       lane=entry.lane))
            edges.append(FlowEdge(source=decision.id, target=reject.id, label="no", kind="conditional"))
            previous = decision
        pending_yes = previous

        reachable = self._reachable(primary.file)
        by_lane: Dict[str, List[str]] = defaultdict(list)
        for rel, _depth in reachable:
            if self.file_app.get(rel) not in (app.id, None) and self.file_app.get(rel) != app.id:
                lane = "External"
            else:
                lane = classify_lane(rel)
            if lane == entry.lane and len(by_lane[lane]) == 0:
                continue
            if len(by_lane[lane]) < 2:
                by_lane[lane].append(rel)

        step_index = 0
        for lane in ("Application", "Domain", "Data", "External"):
            for rel in by_lane.get(lane, []):
                step_index += 1
                node = add_node(FlowNode(
                    id=f"s{step_index}",
                    label=_file_label(rel),
                    kind="subprocess" if lane in ("Application", "Domain") else "task",
                    lane=lane,
                    file=rel,
                ))
                edges.append(FlowEdge(source=pending_yes.id, target=node.id,
                                      label="yes" if pending_yes.kind == "decision" else "",
                                      kind="conditional" if pending_yes.kind == "decision" else "sequence"))
                pending_yes = node

        touched = [primary.file] + [rel for rel, _ in reachable]
        for sid in self._systems_for(touched)[:5]:
            system = self.systems.get(sid)
            if system is None:
                continue
            store_kind = "datastore" if system.kind in ("database", "cache", "storage", "search") else "external"
            node = add_node(FlowNode(id=slug("sys", sid), label=system.name, kind=store_kind,
                                     lane="Data" if store_kind == "datastore" else "External"))
            edges.append(FlowEdge(source=pending_yes.id, target=node.id,
                                  label="read/write" if store_kind == "datastore" else "call",
                                  kind="data" if store_kind == "datastore" else "message"))

        end = add_node(FlowNode(id="end", label=_end_label(kind), kind="end", lane=trigger_lane))
        edges.append(FlowEdge(source=pending_yes.id, target=end.id,
                              label="yes" if pending_yes.kind == "decision" else ""))

        flow.nodes = nodes
        flow.edges = _dedupe_edges(edges)
        flow.lanes = [lane for lane in LANES if lane in lanes_used]
        return flow

    def _app_overview(self, app: App, endpoints: Sequence[Endpoint]) -> Optional[Flow]:
        systems = self._systems_for([rel for rel in self.systems_by_file if self.file_app.get(rel) == app.id])
        if not endpoints and not systems:
            return None
        flow = Flow(
            id=slug("flow", app.id, "overview"),
            name=f"{app.name} — end-to-end overview",
            app=app.id,
            description=f"High level path through {app.name}: entrypoints, processing and the systems it touches.",
            lanes=["Client", "Interface", "Application", "Data", "External"],
        )
        nodes = [
            FlowNode(id="start", label="Actor / caller", kind="start", lane="Client"),
            FlowNode(id="entry", label=_entry_summary(endpoints, app), kind="task", lane="Interface"),
            FlowNode(id="process", label=f"{app.name} processing", kind="subprocess", lane="Application"),
        ]
        edges = [FlowEdge(source="start", target="entry"), FlowEdge(source="entry", target="process")]
        for index, sid in enumerate(systems[:8]):
            system = self.systems.get(sid)
            if system is None:
                continue
            is_store = system.kind in ("database", "cache", "storage", "search")
            nodes.append(FlowNode(id=f"sys{index}", label=system.name,
                                  kind="datastore" if is_store else "external",
                                  lane="Data" if is_store else "External"))
            edges.append(FlowEdge(source="process", target=f"sys{index}",
                                  label="read/write" if is_store else "call",
                                  kind="data" if is_store else "message"))
        nodes.append(FlowNode(id="end", label="Response / result", kind="end", lane="Client"))
        edges.append(FlowEdge(source="process", target="end"))
        flow.nodes = nodes
        flow.edges = edges
        return flow


def _dedupe_edges(edges: Sequence[FlowEdge]) -> List[FlowEdge]:
    seen: Set[Tuple[str, str, str]] = set()
    out: List[FlowEdge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.label)
        if key in seen or edge.source == edge.target:
            continue
        seen.add(key)
        out.append(edge)
    return out


def _endpoint_label(endpoints: Sequence[Endpoint]) -> str:
    primary = endpoints[0]
    if len(endpoints) == 1:
        return f"{primary.method} {primary.path}".strip()
    methods = sorted({e.method for e in endpoints})
    return f"{'/'.join(methods[:4])} {primary.path.rsplit('/', 1)[0] or primary.path}"


def _file_label(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return title_case(name)[:48] or rel


def _reject_label(question: str) -> str:
    return {
        "Authenticated & authorised?": "Reject 401 / 403",
        "Input valid?": "Reject 400 (validation error)",
        "Operation succeeded?": "Return error response",
        "Cache hit?": "Serve cached result",
        "Record found?": "Return 404",
        "Within rate limit?": "Reject 429",
        "Already processed?": "Skip (idempotent)",
    }.get(question, "Alternative path")


def _end_label(kind: str) -> str:
    return {
        "http": "Response returned", "graphql": "Result returned", "event": "Message acknowledged",
        "cli": "Command finished", "cron": "Run complete", "function": "Invocation complete",
    }.get(kind, "Done")


def _entry_summary(endpoints: Sequence[Endpoint], app: App) -> str:
    if not endpoints:
        return f"{app.name} entrypoint"
    kinds = sorted({e.kind for e in endpoints})
    return f"{len(endpoints)} {'/'.join(kinds)} endpoint(s)"
