"""Graphviz DOT exports (render with ``dot -Tsvg``)."""

from __future__ import annotations

import re
from typing import Dict, List

from repograph_core.model import ScanResult

from . import relevance, theme

_ID = re.compile(r"[^A-Za-z0-9_]")


def did(value: str) -> str:
    return '"' + str(value).replace('"', "'") + '"'


def _esc(text: str, limit: int = 60) -> str:
    text = " ".join(str(text).split()).replace('"', "'")
    return text[: limit - 1] + "…" if len(text) > limit else text


def components(result: ScanResult, limit: int = 150) -> str:
    items = sorted(result.components, key=lambda c: -c.files)[:limit]
    ids = {c.id for c in items}
    by_app: Dict[str, List] = {}
    for component in items:
        by_app.setdefault(component.app, []).append(component)
    app_names = {a.id: a.name for a in result.apps}

    lines = [
        "digraph components {",
        '  graph [rankdir=LR, splines=spline, bgcolor="white", fontname="Helvetica", pad=0.4];',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, '
        f'fillcolor="{theme.KINDS["component"][1]}", color="{theme.KINDS["component"][0]}"];',
        f'  edge [color="{theme.EDGE}", arrowsize=0.7];',
    ]
    for index, (app_id, members) in enumerate(by_app.items()):
        lines.append(f"  subgraph cluster_{index} {{")
        lines.append(f'    label="{_esc(app_names.get(app_id, app_id), 40)}"; fontsize=12; '
                     f'color="{theme.KINDS["app"][0]}"; style="rounded";')
        for component in members:
            lines.append(f'    {did(component.id)} [label="{_esc(component.name, 34)}\\n'
                         f'{component.files} files"];')
        lines.append("  }")
    for edge in result.edges:
        if edge.kind == "imports" and edge.source in ids and edge.target in ids:
            width = min(4.0, 0.7 + edge.weight * 0.12)
            lines.append(f"  {did(edge.source)} -> {did(edge.target)} [penwidth={width:.1f}];")
    lines.append("}")
    return "\n".join(lines)


def landscape(result: ScanResult) -> str:
    lines = [
        "digraph landscape {",
        '  graph [rankdir=LR, splines=spline, bgcolor="white", fontname="Helvetica", pad=0.4];',
        '  node [fontname="Helvetica", fontsize=11, style="rounded,filled"];',
    ]
    for app in result.apps:
        stroke, fill, _ = theme.kind_colors(app.kind if app.kind in theme.KINDS else "app")
        lines.append(f'  {did(app.id)} [shape=box, label="{_esc(app.name, 34)}\\n{app.kind}", '
                     f'fillcolor="{fill}", color="{stroke}"];')
    for system in result.external_systems:
        stroke, fill, _ = theme.kind_colors(system.kind if system.kind in theme.KINDS else "external")
        shape = "cylinder" if system.kind in ("database", "cache", "storage", "search") else "box3d"
        lines.append(f'  {did(system.id)} [shape={shape}, label="{_esc(system.name, 30)}", '
                     f'fillcolor="{fill}", color="{stroke}"];')
    for edge in result.edges:
        if edge.kind in ("depends", "db", "cache", "queue", "storage", "http", "deploy"):
            lines.append(f'  {did(edge.source)} -> {did(edge.target)} '
                         f'[label="{_esc(edge.label or edge.kind, 22)}", fontsize=9, '
                         f'color="{theme.EDGE_STRONG}"];')
    lines.append("}")
    return "\n".join(lines)


def build_all(result: ScanResult) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if relevance.wants(result, "dependency-graph"):
        out["components"] = components(result)
    if relevance.wants(result, "c4-container") or relevance.wants(result, "external-systems"):
        out["landscape"] = landscape(result)
    return out
