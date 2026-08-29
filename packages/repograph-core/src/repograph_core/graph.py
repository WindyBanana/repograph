"""Graph construction and analysis over the resolved edges."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .model import Edge


def aggregate(edges: Sequence[Edge], mapping: Dict[str, str], kind: str = "imports",
              drop_self: bool = True) -> List[Edge]:
    """Lift file-level edges to component/app level, summing weights."""
    merged: Dict[Tuple[str, str], Edge] = {}
    for edge in edges:
        source = mapping.get(edge.source, "")
        target = mapping.get(edge.target, "")
        if not source or not target:
            continue
        if drop_self and source == target:
            continue
        key = (source, target)
        existing = merged.get(key)
        if existing is None:
            merged[key] = Edge(source=source, target=target, kind=kind, weight=edge.weight,
                               evidence=list(edge.evidence[:3]))
        else:
            existing.weight += edge.weight
            if len(existing.evidence) < 6:
                existing.evidence.extend(edge.evidence[:1])
    return sorted(merged.values(), key=lambda e: (-e.weight, e.source, e.target))


def adjacency(edges: Iterable[Edge]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        out[edge.source].add(edge.target)
    return out


def find_cycles(edges: Sequence[Edge], limit: int = 50) -> List[List[str]]:
    """Strongly connected components with more than one node (Tarjan, iterative)."""
    graph = adjacency(edges)
    nodes = set(graph) | {t for targets in graph.values() for t in targets}
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    stack: List[str] = []
    counter = 0
    components: List[List[str]] = []

    for root in sorted(nodes):
        if root in index:
            continue
        work: List[Tuple[str, List[str]]] = [(root, sorted(graph.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            node, successors = work[-1]
            progressed = False
            while successors:
                nxt = successors.pop(0)
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack[nxt] = True
                    work.append((nxt, sorted(graph.get(nxt, ()))))
                    progressed = True
                    break
                if on_stack.get(nxt):
                    low[node] = min(low[node], index[nxt])
            if progressed:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while stack:
                    top = stack.pop()
                    on_stack[top] = False
                    component.append(top)
                    if top == node:
                        break
                if len(component) > 1:
                    components.append(sorted(component))
                    if len(components) >= limit:
                        return components
    return components


def layer_nodes(nodes: Sequence[str], edges: Sequence[Edge]) -> Dict[str, int]:
    """Assign a layer to each node: 0 = depends on nothing else in the graph."""
    outgoing: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        if edge.source != edge.target:
            outgoing[edge.source].add(edge.target)
    layers: Dict[str, int] = {}
    visiting: Set[str] = set()

    def depth(node: str, guard: int = 0) -> int:
        if node in layers:
            return layers[node]
        if node in visiting or guard > 64:
            return 0
        visiting.add(node)
        children = [c for c in outgoing.get(node, ()) if c != node]
        value = 1 + max((depth(c, guard + 1) for c in children), default=-1)
        visiting.discard(node)
        layers[node] = value
        return value

    for node in nodes:
        depth(node)
    return layers


def fan(edges: Sequence[Edge]) -> Tuple[Dict[str, int], Dict[str, int]]:
    fan_in: Dict[str, int] = defaultdict(int)
    fan_out: Dict[str, int] = defaultdict(int)
    for edge in edges:
        if edge.source == edge.target:
            continue
        fan_out[edge.source] += 1
        fan_in[edge.target] += 1
    return dict(fan_in), dict(fan_out)


def instability(fan_in: Dict[str, int], fan_out: Dict[str, int], node: str) -> float:
    """Martin's instability metric: 0 = stable (only depended upon), 1 = unstable."""
    ce = fan_out.get(node, 0)
    ca = fan_in.get(node, 0)
    total = ce + ca
    return round(ce / total, 3) if total else 0.0


def orphans(nodes: Sequence[str], edges: Sequence[Edge]) -> List[str]:
    touched = {e.source for e in edges} | {e.target for e in edges}
    return sorted(n for n in nodes if n not in touched)


def transitive_dependents(edges: Sequence[Edge], target: str, max_depth: int = 6) -> List[str]:
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        reverse[edge.target].add(edge.source)
    seen: Set[str] = set()
    frontier = {target}
    for _ in range(max_depth):
        nxt: Set[str] = set()
        for node in frontier:
            for source in reverse.get(node, ()):
                if source not in seen and source != target:
                    seen.add(source)
                    nxt.add(source)
        if not nxt:
            break
        frontier = nxt
    return sorted(seen)


def rank_nodes(nodes: Sequence[str], edges: Sequence[Edge], damping: float = 0.85,
               iterations: int = 30) -> Dict[str, float]:
    """PageRank over the dependency graph: which components matter most."""
    if not nodes:
        return {}
    outgoing: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source].append(edge.target)
    count = len(nodes)
    rank = {node: 1.0 / count for node in nodes}
    node_set = set(nodes)
    for _ in range(iterations):
        nxt = {node: (1 - damping) / count for node in nodes}
        for node in nodes:
            targets = [t for t in outgoing.get(node, ()) if t in node_set]
            if not targets:
                share = damping * rank[node] / count
                for other in nodes:
                    nxt[other] += share
                continue
            share = damping * rank[node] / len(targets)
            for target in targets:
                nxt[target] += share
        rank = nxt
    total = sum(rank.values()) or 1.0
    return {node: round(value / total, 6) for node, value in rank.items()}


def dedupe_edges(edges: Sequence[Edge]) -> List[Edge]:
    merged: Dict[str, Edge] = {}
    for edge in edges:
        existing = merged.get(edge.key)
        if existing is None:
            merged[edge.key] = edge
        else:
            existing.weight += edge.weight
            for ev in edge.evidence:
                if len(existing.evidence) < 8:
                    existing.evidence.append(ev)
    return list(merged.values())
