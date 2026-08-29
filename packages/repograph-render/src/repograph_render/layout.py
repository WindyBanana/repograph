"""Diagram layout.

Positions are computed here, in Python, so every output format (SVG, PDF,
PowerPoint, the interactive HTML views) draws the *same* diagram. Three
algorithms cover everything the tool draws: a layered DAG layout for dependency
and C4 views, a swimlane layout for process flows, and a force-directed layout
for the free-form graph views.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

CHAR_WIDTH = 0.58  # average Helvetica advance as a fraction of font size


@dataclass
class Node:
    id: str
    label: str
    sublabel: str = ""
    kind: str = "component"
    group: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 160.0
    h: float = 56.0
    weight: float = 1.0
    meta: Dict[str, object] = field(default_factory=dict)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    kind: str = "depends"
    weight: float = 1.0
    points: List[Tuple[float, float]] = field(default_factory=list)
    dashed: bool = False


@dataclass
class Group:
    id: str
    label: str
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    kind: str = "app"


@dataclass
class Diagram:
    title: str
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)
    width: float = 1200
    height: float = 800
    subtitle: str = ""
    legend: List[Tuple[str, str]] = field(default_factory=list)
    kind: str = "graph"
    lanes: List[str] = field(default_factory=list)
    lane_height: float = 150.0

    def node(self, node_id: str) -> Optional[Node]:
        return next((n for n in self.nodes if n.id == node_id), None)


def text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * CHAR_WIDTH


def wrap(text: str, width: float, font_size: float, max_lines: int = 3) -> List[str]:
    """Greedy word wrap that also breaks very long unbroken tokens."""
    max_chars = max(6, int(width / (font_size * CHAR_WIDTH)))
    words: List[str] = []
    for token in text.split():
        while len(token) > max_chars:
            words.append(token[: max_chars - 1] + "-")
            token = token[max_chars - 1 :]
        words.append(token)
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return [text[:max_chars]]
    if len(lines) == max_lines:
        consumed = sum(len(l.split()) for l in lines)
        if consumed < len(words):
            lines[-1] = lines[-1][: max_chars - 1] + "…"
    return lines


def size_node(node: Node, font_size: float = 12.0, min_w: float = 120.0, max_w: float = 240.0,
              padding: float = 18.0) -> None:
    label_w = text_width(node.label, font_size) + padding * 2
    sub_w = text_width(node.sublabel, font_size - 2) + padding * 2 if node.sublabel else 0
    node.w = max(min_w, min(max_w, max(label_w, sub_w)))
    lines = len(wrap(node.label, node.w - padding, font_size))
    node.h = 34 + lines * (font_size + 4) + (16 if node.sublabel else 0)


# --------------------------------------------------------------- layered DAG

def layered_layout(nodes: List[Node], edges: List[Edge], *, node_sep: float = 46.0,
                   layer_sep: float = 110.0, margin: float = 48.0, horizontal: bool = False,
                   max_per_layer: int = 8) -> Tuple[float, float]:
    """Sugiyama-style layering with barycentre crossing reduction."""
    if not nodes:
        return 400, 200
    by_id = {n.id: n for n in nodes}
    valid = [e for e in edges if e.source in by_id and e.target in by_id and e.source != e.target]

    layer = _assign_layers(list(by_id), valid)
    buckets: Dict[int, List[Node]] = {}
    for node in nodes:
        buckets.setdefault(layer.get(node.id, 0), []).append(node)

    # Split over-full layers so wide graphs stay readable.
    ordered_layers = sorted(buckets)
    expanded: List[List[Node]] = []
    for index in ordered_layers:
        members = buckets[index]
        if len(members) <= max_per_layer:
            expanded.append(members)
            continue
        for start in range(0, len(members), max_per_layer):
            expanded.append(members[start : start + max_per_layer])

    order = {node.id: (row, col) for row, members in enumerate(expanded)
             for col, node in enumerate(members)}
    for _ in range(4):
        expanded = _barycentre(expanded, valid, order)
        order = {node.id: (row, col) for row, members in enumerate(expanded)
                 for col, node in enumerate(members)}

    x = margin
    y = margin
    width = 0.0
    height = 0.0
    for members in expanded:
        if horizontal:
            column_width = max((n.w for n in members), default=120)
            cursor = margin
            for node in members:
                node.x = x
                node.y = cursor
                cursor += node.h + node_sep
            height = max(height, cursor)
            x += column_width + layer_sep
            width = x
        else:
            row_height = max((n.h for n in members), default=56)
            cursor = margin
            for node in members:
                node.x = cursor
                node.y = y
                cursor += node.w + node_sep
            width = max(width, cursor)
            y += row_height + layer_sep
            height = y
    _route(nodes, valid, horizontal)
    return width + margin, height + margin


def _assign_layers(node_ids: Sequence[str], edges: Sequence[Edge]) -> Dict[str, int]:
    outgoing: Dict[str, List[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source, []).append(edge.target)
    layer: Dict[str, int] = {}
    visiting: set = set()

    def depth(node: str, guard: int = 0) -> int:
        if node in layer:
            return layer[node]
        if node in visiting or guard > 48:
            return 0
        visiting.add(node)
        value = 1 + max((depth(child, guard + 1) for child in outgoing.get(node, ())
                         if child != node), default=-1)
        visiting.discard(node)
        layer[node] = value
        return value

    for node in node_ids:
        depth(node)
    if not layer:
        return {node: 0 for node in node_ids}
    deepest = max(layer.values())
    return {node: deepest - value for node, value in layer.items()}


def _barycentre(layers: List[List[Node]], edges: Sequence[Edge],
                order: Dict[str, Tuple[int, int]]) -> List[List[Node]]:
    incoming: Dict[str, List[str]] = {}
    outgoing: Dict[str, List[str]] = {}
    for edge in edges:
        incoming.setdefault(edge.target, []).append(edge.source)
        outgoing.setdefault(edge.source, []).append(edge.target)

    new_layers: List[List[Node]] = []
    for members in layers:
        def key(node: Node) -> float:
            neighbours = incoming.get(node.id, []) + outgoing.get(node.id, [])
            positions = [order[n][1] for n in neighbours if n in order]
            return sum(positions) / len(positions) if positions else order.get(node.id, (0, 0))[1]

        new_layers.append(sorted(members, key=key))
    return new_layers


def _route(nodes: Sequence[Node], edges: Sequence[Edge], horizontal: bool) -> None:
    by_id = {n.id: n for n in nodes}
    for edge in edges:
        source = by_id.get(edge.source)
        target = by_id.get(edge.target)
        if source is None or target is None:
            continue
        if horizontal:
            start = (source.x + source.w, source.cy)
            end = (target.x, target.cy)
            mid_x = (start[0] + end[0]) / 2
            edge.points = [start, (mid_x, start[1]), (mid_x, end[1]), end]
        else:
            going_down = target.cy > source.cy
            start = (source.cx, source.y + source.h if going_down else source.y)
            end = (target.cx, target.y if going_down else target.y + target.h)
            mid_y = (start[1] + end[1]) / 2
            edge.points = [start, (start[0], mid_y), (end[0], mid_y), end]


# ------------------------------------------------------------- grouped grid

def grouped_layout(nodes: List[Node], edges: List[Edge], groups: List[Group], *,
                   columns: int = 3, padding: float = 26.0, gap: float = 44.0,
                   margin: float = 48.0, header: float = 34.0) -> Tuple[float, float]:
    """Each group is a container box; nodes are gridded inside it."""
    by_group: Dict[str, List[Node]] = {}
    for node in nodes:
        by_group.setdefault(node.group, []).append(node)

    cursor_x = margin
    cursor_y = margin
    row_height = 0.0
    width = margin
    placed = 0

    for group in groups:
        members = by_group.get(group.id, [])
        if not members:
            continue
        per_row = max(1, min(columns, int(math.ceil(math.sqrt(len(members))))))
        col_w = max((n.w for n in members), default=140)
        rows = int(math.ceil(len(members) / per_row))
        row_h = max((n.h for n in members), default=56)
        group.w = per_row * col_w + (per_row - 1) * 18 + padding * 2
        group.h = header + rows * row_h + (rows - 1) * 18 + padding

        if placed and cursor_x + group.w > margin + 1500:
            cursor_x = margin
            cursor_y += row_height + gap
            row_height = 0.0
        group.x = cursor_x
        group.y = cursor_y
        for index, node in enumerate(members):
            col = index % per_row
            row = index // per_row
            node.x = group.x + padding + col * (col_w + 18)
            node.y = group.y + header + padding / 2 + row * (row_h + 18)
            node.w = col_w
            node.h = row_h
        cursor_x += group.w + gap
        row_height = max(row_height, group.h)
        width = max(width, cursor_x)
        placed += 1

    height = cursor_y + row_height + margin
    _route_straight(nodes, edges)
    return width + margin, height


def _route_straight(nodes: Sequence[Node], edges: Sequence[Edge]) -> None:
    by_id = {n.id: n for n in nodes}
    for edge in edges:
        source = by_id.get(edge.source)
        target = by_id.get(edge.target)
        if source is None or target is None:
            continue
        edge.points = _anchor(source, target)


def _anchor(source: Node, target: Node) -> List[Tuple[float, float]]:
    dx = target.cx - source.cx
    dy = target.cy - source.cy
    if abs(dx) > abs(dy):
        start = (source.x + source.w, source.cy) if dx > 0 else (source.x, source.cy)
        end = (target.x, target.cy) if dx > 0 else (target.x + target.w, target.cy)
    else:
        start = (source.cx, source.y + source.h) if dy > 0 else (source.cx, source.y)
        end = (target.cx, target.y) if dy > 0 else (target.cx, target.y + target.h)
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    return [start, mid, end]


# ---------------------------------------------------------------- swimlanes

def swimlane_layout(nodes: List[Node], edges: List[Edge], lanes: Sequence[str], *,
                    lane_height: float = 150.0, col_sep: float = 62.0, margin: float = 40.0,
                    label_width: float = 132.0) -> Tuple[float, float]:
    """Left-to-right process layout with one horizontal band per lane."""
    lane_index = {lane: index for index, lane in enumerate(lanes)}
    columns: Dict[str, int] = {}
    incoming: Dict[str, List[str]] = {n.id: [] for n in nodes}
    for edge in edges:
        if edge.target in incoming:
            incoming[edge.target].append(edge.source)

    # longest-path column assignment following sequence edges
    outgoing: Dict[str, List[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source, []).append(edge.target)
    visiting: set = set()

    def column(node_id: str, guard: int = 0) -> int:
        if node_id in columns:
            return columns[node_id]
        if node_id in visiting or guard > 64:
            return 0
        visiting.add(node_id)
        parents = incoming.get(node_id, [])
        value = 0 if not parents else 1 + max(column(p, guard + 1) for p in parents)
        visiting.discard(node_id)
        columns[node_id] = value
        return value

    for node in nodes:
        column(node.id)

    by_column: Dict[int, List[Node]] = {}
    for node in nodes:
        by_column.setdefault(columns.get(node.id, 0), []).append(node)

    x = margin + label_width
    for index in sorted(by_column):
        members = by_column[index]
        col_w = max((n.w for n in members), default=150)
        used: Dict[int, int] = {}
        for node in members:
            row = lane_index.get(node.group, 0)
            offset = used.get(row, 0)
            used[row] = offset + 1
            node.x = x + (col_w - node.w) / 2
            node.y = margin + row * lane_height + 26 + offset * (node.h + 10)
        x += col_w + col_sep

    width = x + margin
    height = margin + max(1, len(lanes)) * lane_height + margin
    _route_straight(nodes, edges)
    return width, height


# ------------------------------------------------------------ force layout

def force_layout(nodes: List[Node], edges: List[Edge], *, width: float = 1400,
                 height: float = 900, iterations: int = 320, seed: int = 7) -> Tuple[float, float]:
    """Fruchterman-Reingold; deterministic thanks to a fixed seed."""
    if not nodes:
        return width, height
    rng = random.Random(seed)
    count = len(nodes)
    area = width * height
    k = math.sqrt(area / count) * 0.85
    positions = {
        node.id: [width / 2 + rng.uniform(-width / 3, width / 3),
                  height / 2 + rng.uniform(-height / 3, height / 3)]
        for node in nodes
    }
    index = {node.id: node for node in nodes}
    valid = [(e.source, e.target, e.weight) for e in edges
             if e.source in positions and e.target in positions and e.source != e.target]
    temperature = width / 8

    ids = list(positions)
    for _step in range(iterations):
        disp = {node_id: [0.0, 0.0] for node_id in positions}
        for i in range(count):
            for j in range(i + 1, count):
                a, b = ids[i], ids[j]
                dx = positions[a][0] - positions[b][0]
                dy = positions[a][1] - positions[b][1]
                dist = math.hypot(dx, dy) or 0.01
                force = (k * k) / dist
                fx, fy = dx / dist * force, dy / dist * force
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy
        for source, target, weight in valid:
            dx = positions[source][0] - positions[target][0]
            dy = positions[source][1] - positions[target][1]
            dist = math.hypot(dx, dy) or 0.01
            force = (dist * dist) / k * min(2.5, 0.6 + weight * 0.15)
            fx, fy = dx / dist * force, dy / dist * force
            disp[source][0] -= fx
            disp[source][1] -= fy
            disp[target][0] += fx
            disp[target][1] += fy
        for node_id, (dx, dy) in disp.items():
            dist = math.hypot(dx, dy) or 0.01
            limit = min(dist, temperature)
            positions[node_id][0] += dx / dist * limit
            positions[node_id][1] += dy / dist * limit
            positions[node_id][0] = min(width - 60, max(60, positions[node_id][0]))
            positions[node_id][1] = min(height - 40, max(40, positions[node_id][1]))
        temperature *= 0.955

    for node_id, (x, y) in positions.items():
        node = index[node_id]
        node.x = x - node.w / 2
        node.y = y - node.h / 2
    _route_straight(nodes, edges)
    return width, height


def normalise(diagram: Diagram, margin: float = 40.0) -> None:
    """Shift a diagram so it starts at the margin and set its bounding box."""
    if not diagram.nodes and not diagram.groups:
        return
    xs = [n.x for n in diagram.nodes] + [g.x for g in diagram.groups]
    ys = [n.y for n in diagram.nodes] + [g.y for g in diagram.groups]
    max_x = max([n.x + n.w for n in diagram.nodes] + [g.x + g.w for g in diagram.groups])
    max_y = max([n.y + n.h for n in diagram.nodes] + [g.y + g.h for g in diagram.groups])
    dx = margin - min(xs)
    dy = margin - min(ys)
    for node in diagram.nodes:
        node.x += dx
        node.y += dy
    for group in diagram.groups:
        group.x += dx
        group.y += dy
    for edge in diagram.edges:
        edge.points = [(x + dx, y + dy) for x, y in edge.points]
    diagram.width = max_x + dx + margin
    diagram.height = max_y + dy + margin
