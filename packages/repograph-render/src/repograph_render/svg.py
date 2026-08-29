"""SVG rendering of laid-out diagrams."""

from __future__ import annotations

import hashlib
import html
import math
from typing import List, Optional, Sequence, Tuple

from . import theme
from .layout import Diagram, Node, wrap


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def diagram_uid(diagram: Diagram) -> str:
    """Stable per-diagram id suffix.

    Several diagrams are inlined into one HTML page, so marker and filter ids
    must be unique: a duplicate id resolves to the first match, which may sit in
    a hidden tab and then renders as nothing.
    """
    seed = f"{diagram.kind}:{diagram.title}:{len(diagram.nodes)}"
    return hashlib.sha1(seed.encode(), usedforsecurity=False).hexdigest()[:8]


def _defs(uid: str) -> str:
    return f"""<defs>
  <marker id="arrow-{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
          orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{theme.EDGE_STRONG}"/></marker>
  <marker id="arrow-open-{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
          orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="{theme.EDGE_STRONG}"
          stroke-width="1.6"/></marker>
  <filter id="soft-{uid}" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="1.5" stdDeviation="2.2" flood-color="#0f172a" flood-opacity="0.10"/>
  </filter>
</defs>"""


def path_from(points: Sequence[Tuple[float, float]], smooth: bool = True) -> str:
    if not points:
        return ""
    if len(points) == 2 or not smooth:
        return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)
    parts = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for index in range(1, len(points) - 1):
        cx, cy = points[index]
        nx, ny = points[index + 1]
        mx, my = (cx + nx) / 2, (cy + ny) / 2
        parts.append(f"Q {cx:.1f} {cy:.1f} {mx:.1f} {my:.1f}")
    parts.append(f"L {points[-1][0]:.1f} {points[-1][1]:.1f}")
    return " ".join(parts)


def node_shape(node: Node, stroke: str, fill: str) -> str:
    x, y, w, h = node.x, node.y, node.w, node.h
    kind = node.kind
    if kind in ("database", "datastore", "cache", "storage"):
        ry = min(12.0, h / 6)
        return (
            f'<path d="M {x} {y+ry} a {w/2} {ry} 0 0 1 {w} 0 v {h-2*ry} a {w/2} {ry} 0 0 1 {-w} 0 z" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            f'<path d="M {x} {y+ry} a {w/2} {ry} 0 0 0 {w} 0" fill="none" stroke="{stroke}" '
            f'stroke-width="1.2" opacity="0.7"/>'
        )
    if kind == "decision":
        cx, cy = node.cx, node.cy
        return (f'<path d="M {cx} {y} L {x+w} {cy} L {cx} {y+h} L {x} {cy} z" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="1.5"/>')
    if kind in ("start", "end"):
        r = min(h / 2, 26)
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{2.4 if kind == "end" else 1.6}"/>')
    if kind == "event":
        r = min(h / 2, 24)
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="6 3"/>')
    if kind == "person":
        head = 12
        return (
            f'<rect x="{x}" y="{y+head}" width="{w}" height="{h-head}" rx="8" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>'
            f'<circle cx="{node.cx}" cy="{y+head-2}" r="{head-2}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.5"/>'
        )
    if kind == "queue":
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="1.5"/>'
                f'<line x1="{x+12}" y1="{y}" x2="{x+12}" y2="{y+h}" stroke="{stroke}" opacity="0.5"/>'
                f'<line x1="{x+w-12}" y1="{y}" x2="{x+w-12}" y2="{y+h}" stroke="{stroke}" opacity="0.5"/>')
    if kind == "subprocess":
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="1.5"/>'
                f'<line x1="{x+8}" y1="{y}" x2="{x+8}" y2="{y+h}" stroke="{stroke}" opacity="0.55"/>'
                f'<line x1="{x+w-8}" y1="{y}" x2="{x+w-8}" y2="{y+h}" stroke="{stroke}" opacity="0.55"/>')
    radius = 10 if kind in ("app", "container", "system") else 8
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>')


def node_text(node: Node, colour: str, font_size: float = 12.5) -> str:
    lines = wrap(node.label, node.w - 20, font_size, max_lines=3)
    has_sub = bool(node.sublabel)
    total = len(lines) * (font_size + 3) + (font_size if has_sub else 0)
    # A person shape carries a head above the body; the label lives in the body.
    centre = node.cy + (7 if node.kind == "person" else 0)
    start_y = centre - total / 2 + font_size
    parts = []
    for index, line in enumerate(lines):
        parts.append(
            f'<text x="{node.cx:.1f}" y="{start_y + index * (font_size + 3):.1f}" text-anchor="middle" '
            f'font-family="{theme.FONT}" font-size="{font_size}" font-weight="600" fill="{colour}">{esc(line)}</text>'
        )
    if has_sub:
        sub_lines = wrap(node.sublabel, node.w - 16, font_size - 2.5, max_lines=1)
        parts.append(
            f'<text x="{node.cx:.1f}" y="{start_y + len(lines) * (font_size + 3) + 2:.1f}" '
            f'text-anchor="middle" font-family="{theme.FONT}" font-size="{font_size - 2.5}" '
            f'fill="{theme.MUTED}">{esc(sub_lines[0])}</text>'
        )
    return "".join(parts)


def render_diagram(diagram: Diagram, *, background: str = theme.BG, title: bool = True,
                   lanes: Optional[Sequence[str]] = None, lane_height: Optional[float] = None,
                   label_width: float = 132.0) -> str:
    lanes = diagram.lanes if lanes is None else lanes
    lane_height = diagram.lane_height if lane_height is None else lane_height
    uid = diagram_uid(diagram)
    width = max(320.0, diagram.width)
    height = max(220.0, diagram.height)
    header = 58 if title and diagram.title else 0
    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height + header:.0f}" '
        f'width="{width:.0f}" height="{height + header:.0f}" role="img" '
        f'aria-label="{esc(diagram.title)}">',
        _defs(uid),
        f'<rect width="100%" height="100%" fill="{background}"/>',
    ]
    if header:
        parts.append(
            f'<text x="28" y="34" font-family="{theme.FONT}" font-size="18" font-weight="700" '
            f'fill="{theme.INK}">{esc(diagram.title)}</text>'
        )
        if diagram.subtitle:
            parts.append(
                f'<text x="28" y="50" font-family="{theme.FONT}" font-size="11.5" '
                f'fill="{theme.MUTED}">{esc(diagram.subtitle)}</text>'
            )
    parts.append(f'<g transform="translate(0,{header})">')

    for index, lane in enumerate(lanes):
        y = 40 + index * lane_height
        tint = theme.LANE_TINTS[index % len(theme.LANE_TINTS)]
        parts.append(
            f'<rect x="24" y="{y}" width="{width - 48:.0f}" height="{lane_height - 8}" fill="{tint}" '
            f'stroke="{theme.GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{34}" y="{y + lane_height / 2}" font-family="{theme.FONT}" font-size="12.5" '
            f'font-weight="700" fill="{theme.MUTED}" dominant-baseline="middle">{esc(lane)}</text>'
        )
        parts.append(
            f'<line x1="{24 + label_width - 12}" y1="{y}" x2="{24 + label_width - 12}" '
            f'y2="{y + lane_height - 8}" stroke="{theme.GRID}"/>'
        )

    for group in diagram.groups:
        stroke, fill, _ = theme.kind_colors(group.kind)
        parts.append(
            f'<rect x="{group.x}" y="{group.y}" width="{group.w}" height="{group.h}" rx="14" '
            f'fill="{fill}" fill-opacity="0.45" stroke="{stroke}" stroke-width="1.3" '
            f'stroke-dasharray="7 4"/>'
        )
        parts.append(
            f'<text x="{group.x + 16}" y="{group.y + 24}" font-family="{theme.FONT}" font-size="13" '
            f'font-weight="700" fill="{stroke}">{esc(group.label)}</text>'
        )

    for edge in diagram.edges:
        if not edge.points:
            continue
        stroke_width = min(3.4, 1.1 + math.log1p(edge.weight) * 0.5)
        dash = ' stroke-dasharray="6 4"' if edge.dashed or edge.kind in ("conditional", "message") else ""
        colour = theme.EDGE_STRONG if edge.weight > 3 else theme.EDGE
        parts.append(
            f'<path d="{path_from(edge.points)}" fill="none" stroke="{colour}" '
            f'stroke-width="{stroke_width:.2f}"{dash} marker-end="url(#arrow-{uid})" opacity="0.85"/>'
        )
        if edge.label:
            mid = edge.points[len(edge.points) // 2]
            label_w = len(edge.label) * 6.0 + 10
            parts.append(
                f'<rect x="{mid[0] - label_w / 2:.1f}" y="{mid[1] - 9:.1f}" width="{label_w:.1f}" height="16" '
                f'rx="8" fill="{background}" opacity="0.92"/>'
                f'<text x="{mid[0]:.1f}" y="{mid[1] + 3:.1f}" text-anchor="middle" font-family="{theme.FONT}" '
                f'font-size="10.5" fill="{theme.MUTED}">{esc(edge.label)}</text>'
            )

    for node in diagram.nodes:
        stroke, fill, text_colour = theme.kind_colors(node.kind)
        parts.append(f'<g filter="url(#soft-{uid})">{node_shape(node, stroke, fill)}</g>')
        parts.append(node_text(node, text_colour))

    if diagram.legend:
        parts.append(_legend(diagram.legend, width, height))
    parts.append("</g></svg>")
    return "\n".join(parts)


def _legend(entries: Sequence[Tuple[str, str]], width: float, height: float) -> str:
    parts = [f'<g transform="translate(24,{height - 30:.0f})">']
    x = 0.0
    for label, colour in entries[:8]:
        parts.append(
            f'<rect x="{x}" y="-10" width="12" height="12" rx="3" fill="{colour}" opacity="0.85"/>'
            f'<text x="{x + 18}" y="0" font-family="{theme.FONT}" font-size="11" '
            f'fill="{theme.MUTED}">{esc(label)}</text>'
        )
        x += 30 + len(label) * 6.2
    parts.append("</g>")
    return "".join(parts)


def wrap_document(svg: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg
