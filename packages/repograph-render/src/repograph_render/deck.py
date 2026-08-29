"""The PowerPoint deck: the version you present.

Diagrams become native shapes (movable, recolourable) rather than images.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from repograph_core.model import ScanResult

from . import theme
from .layout import Diagram
from .pptx import SLIDE_H, SLIDE_W, Slide, write

PAGE_W = SLIDE_W / 9525.0   # 1280 px
PAGE_H = SLIDE_H / 9525.0   # 720 px
MARGIN = 56.0
TITLE_Y = 44.0
BODY_Y = 118.0


def _title(slide: Slide, title: str, subtitle: str = "") -> None:
    slide.text(MARGIN, TITLE_Y, PAGE_W - MARGIN * 2, 44,
               [(title, 28, True, theme.INK)])
    if subtitle:
        slide.text(MARGIN, TITLE_Y + 38, PAGE_W - MARGIN * 2, 26,
                   [(subtitle, 13, False, theme.MUTED)])
    slide.box(MARGIN, TITLE_Y + (68 if subtitle else 46), 54, 3, fill="#2563eb", line="#2563eb",
              shape="rect")


def cover(result: ScanResult) -> Slide:
    slide = Slide()
    slide.box(0, 0, PAGE_W, 300, fill="#0f172a", line="#0f172a", shape="rect")
    slide.text(MARGIN, 96, PAGE_W - MARGIN * 2, 26, [("ARCHITECTURE REVIEW", 12, True, "#93c5fd")])
    slide.text(MARGIN, 126, PAGE_W - MARGIN * 2, 70, [(result.meta.repo_name[:40], 40, True, "#ffffff")])
    purpose = str(result.summary.get("purpose", ""))[:220]
    slide.text(MARGIN, 200, PAGE_W - MARGIN * 2 - 60, 60, [(purpose, 14, False, "#cbd5e1")])
    stats = [
        (str(result.metrics.apps), "Applications"),
        (str(result.metrics.components), "Components"),
        (f"{result.metrics.loc:,}", "Lines of code"),
        (str(result.metrics.endpoints), "Endpoints"),
        (str(result.metrics.external_systems), "External systems"),
        (str(sum(result.metrics.findings_by_severity.values())), "Findings"),
    ]
    width = (PAGE_W - MARGIN * 2 - 10 * 5) / 6
    for index, (value, label) in enumerate(stats):
        x = MARGIN + index * (width + 10)
        slide.box(x, 350, width, 92, fill="#f8fafc", line="#e2e8f0")
        slide.text(x + 14, 372, width - 20, 34, [(value, 24, True, theme.INK)])
        slide.text(x + 14, 404, width - 20, 22, [(label, 10.5, False, theme.MUTED)])
    slide.text(MARGIN, 490, PAGE_W - MARGIN * 2, 60, [
        (f"Generated {result.meta.generated_at} by repograph {result.meta.version} — "
         f"deterministic static analysis, no AI.", 11, False, theme.MUTED),
    ])
    return slide


def summary_slide(result: ScanResult) -> Slide:
    slide = Slide()
    _title(slide, "Executive summary", "What this repository is, and where the risk sits")
    summary = result.summary
    bullets = [
        f"Shape: {summary.get('shape', 'unknown')} — "
        f"{', '.join(summary.get('architecture_styles', [])) or 'unclassified layout'}",
        f"Languages: {', '.join(summary.get('primary_languages', [])[:5]) or 'unknown'}",
        f"{result.metrics.apps} application(s), {result.metrics.components} components, "
        f"{result.metrics.loc:,} lines of code",
        f"{result.metrics.endpoints} endpoints across "
        f"{len({e.kind for e in result.endpoints})} interface type(s)",
        f"Data stores: {', '.join(summary.get('data_stores', [])[:6]) or 'none detected'}",
        f"Integrations: {', '.join(summary.get('integrations', [])[:6]) or 'none detected'}",
        f"Risk level: {summary.get('risk_level', 'unknown')} "
        f"({sum(result.metrics.findings_by_severity.values())} findings)",
        f"Test files: {result.metrics.test_files} ({result.metrics.test_ratio:.0%} of source files)"
        f" · dependency cycles: {result.metrics.cycles}",
    ]
    slide.bullets(MARGIN, BODY_Y + 20, PAGE_W * 0.54, 400, bullets, size=14)

    x = PAGE_W * 0.62
    slide.text(x, BODY_Y + 12, 380, 22, [("Findings by severity", 13, True, theme.INK)])
    counts = result.metrics.findings_by_severity
    total = sum(counts.values()) or 1
    y = BODY_Y + 44
    for severity in ("critical", "high", "medium", "low", "info"):
        value = counts.get(severity, 0)
        if not value:
            continue
        width = max(12.0, (PAGE_W - x - MARGIN - 70) * value / total)
        slide.text(x, y, 70, 20, [(severity.title(), 11, False, theme.MUTED)])
        slide.box(x + 74, y, width, 18, fill=theme.severity_color(severity),
                  line=theme.severity_color(severity), text=str(value), text_size=9.5,
                  text_colour="#ffffff")
        y += 26
    return slide


def diagram_slide(diagram: Diagram, *, max_nodes: int = 34) -> Optional[Slide]:
    nodes = diagram.nodes[:max_nodes]
    if not nodes:
        return None
    keep = {n.id for n in nodes}
    slide = Slide()
    _title(slide, diagram.title[:64], diagram.subtitle[:110])

    top = BODY_Y + 16
    available_w = PAGE_W - MARGIN * 2
    available_h = PAGE_H - top - 40
    scale = min(available_w / max(diagram.width, 1), available_h / max(diagram.height, 1))
    offset_x = MARGIN + (available_w - diagram.width * scale) / 2
    offset_y = top

    def tx(value: float) -> float:
        return offset_x + value * scale

    def ty(value: float) -> float:
        return offset_y + value * scale

    for index, lane in enumerate(diagram.lanes):
        lane_y = ty(40 + index * diagram.lane_height)
        slide.box(tx(24), lane_y, (diagram.width - 48) * scale,
                  diagram.lane_height * scale - 6, fill=theme.LANE_TINTS[index % 2],
                  line="#e2e8f0", shape="rect", text=lane, text_size=10, text_colour=theme.MUTED,
                  bold=True)

    for group in diagram.groups:
        stroke, fill, _ = theme.kind_colors(group.kind)
        slide.box(tx(group.x), ty(group.y), group.w * scale, group.h * scale, fill=fill,
                  line=stroke, dash=True, fill_alpha=40000)
        slide.text(tx(group.x) + 12, ty(group.y) + 8, group.w * scale - 20, 20,
                   [(group.label[:40], 11, True, stroke)])

    for edge in diagram.edges:
        if edge.source not in keep or edge.target not in keep or not edge.points:
            continue
        points = edge.points
        start, end = points[0], points[-1]
        slide.line(tx(start[0]), ty(start[1]), tx(end[0]), ty(end[1]),
                   colour=theme.EDGE, width=min(2.5, 0.8 + math.log1p(edge.weight) * 0.4),
                   dash=edge.dashed)

    for node in nodes:
        stroke, fill, ink = theme.kind_colors(node.kind)
        shape = {
            "decision": "diamond", "database": "flowChartMagneticDrum", "datastore": "flowChartMagneticDrum",
            "cache": "flowChartMagneticDrum", "storage": "flowChartMagneticDrum",
            "start": "roundRect", "end": "roundRect", "person": "roundRect",
        }.get(node.kind, "roundRect")
        slide.box(tx(node.x), ty(node.y), node.w * scale, node.h * scale, fill=fill, line=stroke,
                  text=node.label[:44], subtitle=node.sublabel[:36], text_size=max(8.0, 10 * scale),
                  text_colour=ink, shape=shape)

    if len(diagram.nodes) > max_nodes:
        slide.text(MARGIN, PAGE_H - 34, PAGE_W - MARGIN * 2, 20,
                   [(f"Showing {max_nodes} of {len(diagram.nodes)} nodes — the full diagram is in "
                     f"the HTML report and the SVG export.", 10, False, theme.MUTED)])
    return slide


def table_slide(title: str, subtitle: str, headers: Sequence[str], rows: Sequence[Sequence[str]],
                weights: Sequence[float], *, limit: int = 12, note: str = "") -> Slide:
    slide = Slide()
    _title(slide, title, subtitle)
    width = PAGE_W - MARGIN * 2
    slide.table(MARGIN, BODY_Y + 16, width, headers, [list(r) for r in rows[:limit]],
                col_widths=[w * width for w in weights], row_height=26, font_size=10)
    if len(rows) > limit or note:
        message = note or f"Showing {limit} of {len(rows)} rows — the full list is in the workbook and CSVs."
        slide.text(MARGIN, PAGE_H - 44, width, 24, [(message, 10, False, theme.MUTED)])
    return slide


def build(result: ScanResult, diagrams: Dict[str, Diagram], path: str) -> None:
    slides: List[Slide] = [cover(result), summary_slide(result)]

    for key in ("c4-context", "c4-container", "application-landscape", "external-systems",
                "deployment", "dependency-layers"):
        diagram = diagrams.get(key)
        if diagram is not None:
            slide = diagram_slide(diagram)
            if slide is not None:
                slides.append(slide)

    slides.append(table_slide(
        "Applications", "Units built or deployed separately",
        ["Application", "Kind", "Languages", "Files", "LOC", "Architecture style"],
        [[a.name, a.kind, ", ".join(a.languages[:2]), str(a.files), f"{a.loc:,}",
          a.architecture_style[:38]] for a in result.apps],
        [0.24, 0.11, 0.19, 0.08, 0.10, 0.28]))

    if result.endpoints:
        slides.append(table_slide(
            "API surface", f"{len(result.endpoints)} endpoints and entrypoints",
            ["Kind", "Method", "Path", "Framework", "Source"],
            [[e.kind, e.method, e.path[:52], e.framework or "—", f"{e.file}:{e.line}"]
             for e in result.endpoints],
            [0.10, 0.10, 0.38, 0.15, 0.27]))

    if result.external_systems:
        slides.append(table_slide(
            "External systems", "What this code depends on outside its own repository",
            ["System", "Kind", "Technology", "Used by", "Evidence"],
            [[s.name, s.kind, s.technology, ", ".join(s.apps)[:26] or "—",
              f"{s.evidence[0].file}:{s.evidence[0].line}" if s.evidence else "config"]
             for s in result.external_systems],
            [0.24, 0.13, 0.20, 0.18, 0.25]))

    findings = [f for f in result.findings if f.severity in ("critical", "high", "medium")]
    if findings:
        slides.append(table_slide(
            "Top findings", "Highest severity first; every row names a file and line",
            ["Severity", "Finding", "Location", "Fix"],
            [[f.severity, f.title[:58], f"{f.file}:{f.line}" if f.file else "repository",
              f.remediation[:64]] for f in findings],
            [0.10, 0.34, 0.24, 0.32],
            note=f"{sum(result.metrics.findings_by_severity.values())} findings in total — "
                 f"full detail in findings.csv and the workbook."))

    risky = [d for d in result.dependencies if not d.version or not d.used][:12]
    if risky:
        slides.append(table_slide(
            "Dependency hygiene", "Unpinned or apparently unused direct dependencies",
            ["Package", "Version", "Ecosystem", "Scope", "Used"],
            [[d.name, d.version or "(unpinned)", d.ecosystem, d.scope, "yes" if d.used else "no"]
             for d in risky],
            [0.32, 0.20, 0.16, 0.14, 0.18]))

    flow_keys = [k for k in diagrams if k.startswith("flow-")][:3]
    for key in flow_keys:
        slide = diagram_slide(diagrams[key])
        if slide is not None:
            slides.append(slide)

    method = Slide()
    _title(method, "Method and limits", "How to read this deck")
    method.bullets(MARGIN, BODY_Y + 20, PAGE_W - MARGIN * 2, 420, [
        "Everything here was derived by static analysis: file walk, manifest and lockfile parsing, "
        "per-language import and endpoint extraction, and signature matching for external systems.",
        "No AI model was involved, and no code was executed.",
        f"{result.summary.get('unresolved_imports', 0)} imports could not be resolved and are "
        "missing from the graph.",
        "Reflection, dependency injection and runtime plugin loading are not traced, so process "
        "flows show the intended path rather than every runtime path.",
        "A detected external system proves a reference exists in the code, not that it is used in "
        "production; every detection carries a file and line.",
        ("Dependency advisories were checked against OSV.dev." if result.meta.online
         else "This scan ran offline: published CVEs for dependencies were NOT checked. "
              "Re-run with --online for advisory data."),
    ], size=13)
    slides.append(method)

    write(path, slides, title=f"{result.meta.repo_name} — architecture review")
