"""Composes the PDF report: cover, summary, vector diagrams and paginated tables."""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

from repograph_core.model import ScanResult

from . import theme
from .layout import Diagram, Node
from .pdf import Document, Page, text_width, wrap_text

MARGIN = 46.0
FOOT = 34.0


class ReportBuilder:
    def __init__(self, result: ScanResult, diagrams: Dict[str, Diagram]) -> None:
        self.result = result
        self.diagrams = diagrams
        self.doc = Document(title=f"{result.meta.repo_name} — architecture report")
        self.page_number = 0

    # ------------------------------------------------------------ chrome
    def _page(self, landscape: bool = False, title: str = "", subtitle: str = "") -> Page:
        page = self.doc.add_page(landscape=landscape)
        self.page_number += 1
        page.rect(0, 0, page.width, 26, fill="#f8fafc")
        page.text(MARGIN, 17, self.result.meta.repo_name, size=8.5, colour=theme.MUTED)
        page.text(page.width - MARGIN - 120, 17, f"repograph · page {self.page_number}",
                  size=8.5, colour=theme.MUTED, align="right", width=120)
        page.line(0, 26, page.width, 26, colour=theme.GRID, width=0.6)
        y = 62.0
        if title:
            page.text(MARGIN, y, title, size=18, bold=True, colour=theme.INK)
            y += 16
        if subtitle:
            page.text(MARGIN, y, subtitle, size=9.5, colour=theme.MUTED)
        return page

    def _content_top(self, has_title: bool = True) -> float:
        return 92.0 if has_title else 50.0

    # ------------------------------------------------------------- pieces
    def cover(self) -> None:
        page = self.doc.add_page()
        self.page_number += 1
        result = self.result
        page.rect(0, 0, page.width, 230, fill="#0f172a")
        page.text(MARGIN, 92, "ARCHITECTURE REPORT", size=10, bold=True, colour="#93c5fd")
        page.text(MARGIN, 132, result.meta.repo_name[:38], size=30, bold=True, colour="#ffffff")
        purpose = str(result.summary.get("purpose", ""))[:400]
        page.paragraph(MARGIN, 156, page.width - MARGIN * 2 - 20, purpose, size=10.5,
                       colour="#cbd5e1", max_lines=4)

        stats = [
            (f"{result.metrics.apps}", "Applications"),
            (f"{result.metrics.components}", "Components"),
            (f"{result.metrics.loc:,}", "Lines of code"),
            (f"{result.metrics.endpoints}", "Endpoints"),
            (f"{result.metrics.dependencies}", "Dependencies"),
            (f"{result.metrics.external_systems}", "External systems"),
            (f"{sum(result.metrics.findings_by_severity.values())}", "Findings"),
            (f"{result.metrics.scanned_files}", "Files scanned"),
        ]
        y = 268.0
        width = (page.width - MARGIN * 2 - 24) / 4
        for index, (value, label) in enumerate(stats):
            column = index % 4
            row = index // 4
            bx = MARGIN + column * (width + 8)
            by = y + row * 74
            page.rect(bx, by, width, 64, fill="#f8fafc", stroke=theme.GRID, radius=8)
            page.text(bx + 12, by + 30, value, size=19, bold=True)
            page.text(bx + 12, by + 48, label, size=8.5, colour=theme.MUTED)

        y = 430.0
        risk = str(result.summary.get("risk_level", "unknown"))
        page.rect(MARGIN, y, page.width - MARGIN * 2, 58, fill=theme.SEVERITY_BG.get(risk, "#f8fafc"),
                  stroke=theme.severity_color(risk), radius=8)
        page.text(MARGIN + 16, y + 24, f"Overall risk: {risk.upper()}", size=13, bold=True,
                  colour=theme.severity_color(risk))
        counts = result.metrics.findings_by_severity
        page.text(MARGIN + 16, y + 42,
                  " · ".join(f"{k}: {v}" for k, v in counts.items()) or "no findings",
                  size=9.5, colour=theme.MUTED)

        y += 84
        facts = [
            ("Repository", result.meta.root),
            ("Shape", str(result.summary.get("shape", ""))),
            ("Languages", ", ".join(result.summary.get("primary_languages", [])[:6])),
            ("Architecture", ", ".join(result.summary.get("architecture_styles", []))[:110]),
            ("Data stores", ", ".join(result.summary.get("data_stores", []))[:110] or "none detected"),
            ("Integrations", ", ".join(result.summary.get("integrations", [])[:8])[:110] or "none detected"),
            ("Git", f"{result.git.commits} commits, {result.git.contributors} contributors"
                    if result.git.is_repo else "not a git repository"),
            ("Generated", f"{result.meta.generated_at} · repograph {result.meta.version}"),
            ("Method", "Deterministic static analysis. No AI, no code execution."
                       + (" OSV advisories checked." if result.meta.online else " Offline: no advisory lookup.")),
        ]
        for label, value in facts:
            page.text(MARGIN, y, label, size=9, bold=True, colour=theme.MUTED)
            y = page.paragraph(MARGIN + 110, y, page.width - MARGIN * 2 - 110, value, size=9.5)
            y += 6

    def business_page(self) -> None:
        """The page you can hand to someone who does not read code."""
        business = self.result.business or {}
        page = self._page(title="What this is",
                          subtitle="In plain language, read out of the code itself")
        y = self._content_top()
        width = page.width - MARGIN * 2
        y = page.paragraph(MARGIN, y, width, str(business.get("what_it_is", "")), size=11.5,
                           max_lines=8)
        y += 16

        sections = [
            ("What it lets people do", business.get("capabilities")),
            ("Who uses it", business.get("users")),
            ("Where its data lives", business.get("data")),
            ("What it depends on", business.get("dependencies")),
            ("How it runs", business.get("operations")),
            ("What could hurt", business.get("risks")),
            ("How healthy it looks", business.get("health")),
        ]
        for title, points in sections:
            points = list(points or [])
            if not points:
                continue
            if y > page.height - FOOT - 70:
                page = self._page(title="What this is (continued)")
                y = self._content_top()
            page.text(MARGIN, y, title, size=11, bold=True)
            y += 15
            for point in points[:5]:
                if y > page.height - FOOT - 34:
                    page = self._page(title="What this is (continued)")
                    y = self._content_top()
                page.rect(MARGIN, y - 7, 2.5, 12, fill=theme.KINDS["app"][0])
                page.text(MARGIN + 10, y, str(point.get("title", ""))[:90], size=9.5, bold=True)
                y = page.paragraph(MARGIN + 10, y + 12, width - 10,
                                   str(point.get("plain", "")), size=9, max_lines=4)
                y += 10
            y += 8

        unknowns = business.get("unknowns") or []
        if unknowns and y < page.height - FOOT - 60:
            page.text(MARGIN, y, "What this report cannot tell you", size=11, bold=True)
            y += 15
            for item in unknowns[:5]:
                y = page.paragraph(MARGIN + 10, y, width - 10, "— " + str(item), size=9,
                                   colour=theme.MUTED, max_lines=3)
                y += 6

    def summary_page(self) -> None:
        result = self.result
        page = self._page(title="Executive summary",
                          subtitle="What this repository contains and where the risk sits")
        y = self._content_top()
        width = page.width - MARGIN * 2

        y = self._section(page, y, "Purpose", str(result.summary.get("purpose", "")))
        y = self._section(page, y, "Shape and style",
                          f"{result.summary.get('shape', 'unknown')} · "
                          f"{', '.join(result.summary.get('architecture_styles', [])) or 'unclassified'}")

        y += 6
        page.text(MARGIN, y, "Lines of code by language", size=10, bold=True)
        y += 12
        y = self._bar_chart(page, MARGIN, y, width * 0.62,
                            [(k, v) for k, v in list(result.metrics.languages.items())[:8]])
        y += 14
        page.text(MARGIN, y, "Findings by severity", size=10, bold=True)
        y += 12
        y = self._severity_bar(page, MARGIN, y, width * 0.62, result.metrics.findings_by_severity)

        y += 18
        page.text(MARGIN, y, "Applications", size=10, bold=True)
        y += 10
        rows = [[a.name[:26], a.kind, ", ".join(a.languages[:2]), f"{a.files}", f"{a.loc:,}",
                 a.architecture_style[:34]] for a in result.apps[:14]]
        y = self._table(page, MARGIN, y, width,
                        ["Application", "Kind", "Languages", "Files", "LOC", "Style"],
                        rows, [0.22, 0.12, 0.18, 0.08, 0.10, 0.30])

        top = [f for f in result.findings if f.severity in ("critical", "high")][:6]
        if top and y < page.height - 200:
            y += 16
            page.text(MARGIN, y, "Highest severity findings", size=10, bold=True)
            y += 12
            for finding in top:
                if y > page.height - FOOT - 40:
                    break
                colour = theme.severity_color(finding.severity)
                page.rect(MARGIN, y - 8, 3, 26, fill=colour)
                page.text(MARGIN + 10, y, f"{finding.severity.upper()} · {finding.title}"[:96],
                          size=9, bold=True)
                page.text(MARGIN + 10, y + 12,
                          f"{finding.file}:{finding.line}" if finding.file else "repository-wide",
                          size=8, mono=True, colour=theme.MUTED)
                y += 30

    def _section(self, page: Page, y: float, title: str, body: str) -> float:
        page.text(MARGIN, y, title, size=10, bold=True)
        y += 13
        y = page.paragraph(MARGIN, y, page.width - MARGIN * 2, body or "—", size=10, max_lines=8)
        return y + 12

    def _bar_chart(self, page: Page, x: float, y: float, width: float,
                   items: Sequence[Tuple[str, float]]) -> float:
        if not items:
            page.text(x, y, "no data", size=9, colour=theme.FAINT)
            return y + 14
        top = max(v for _, v in items) or 1
        label_w = 96.0
        bar_area = width - label_w - 54
        for index, (label, value) in enumerate(items):
            row_y = y + index * 17
            page.text(x, row_y + 8, str(label)[:18], size=8.5)
            bar = max(2.0, bar_area * value / top)
            page.rect(x + label_w, row_y, bar, 10, fill=theme.series_color(index), radius=2)
            page.text(x + label_w + bar + 6, row_y + 8, f"{int(value):,}", size=8,
                      colour=theme.MUTED)
        return y + len(items) * 17

    def _severity_bar(self, page: Page, x: float, y: float, width: float,
                      counts: Dict[str, int]) -> float:
        order = [s for s in ("critical", "high", "medium", "low", "info") if counts.get(s)]
        total = sum(counts.get(s, 0) for s in order)
        if not total:
            page.text(x, y, "no findings", size=9, colour=theme.FAINT)
            return y + 16
        cursor = x
        gap = 2.0
        usable = width - gap * (len(order) - 1)
        for severity in order:
            segment = usable * counts[severity] / total
            page.rect(cursor, y, max(segment, 2), 16, fill=theme.severity_color(severity), radius=3)
            if segment > 30:
                page.text(cursor + 5, y + 11, str(counts[severity]), size=8.5, bold=True,
                          colour="#ffffff")
            cursor += segment + gap
        y += 24
        cursor = x
        for severity in order:
            page.rect(cursor, y - 7, 8, 8, fill=theme.severity_color(severity), radius=2)
            label = f"{severity} {counts[severity]}"
            page.text(cursor + 12, y, label, size=8, colour=theme.MUTED)
            cursor += 22 + text_width(label, 8)
        return y + 8

    # ---------------------------------------------------------- diagrams
    def diagram_page(self, diagram: Diagram, caption: Optional[Dict[str, str]] = None) -> None:
        landscape = diagram.width >= diagram.height
        page = self._page(landscape=landscape, title=diagram.title[:70],
                          subtitle=diagram.subtitle[:120])
        top = self._content_top()
        if caption and (caption.get("what") or caption.get("notice")):
            top = page.paragraph(MARGIN, top - 4, page.width - MARGIN * 2,
                                 str(caption.get("what", "")), size=9, colour=theme.MUTED,
                                 max_lines=3)
            if caption.get("notice"):
                top = page.paragraph(MARGIN, top + 2, page.width - MARGIN * 2,
                                     "Notice: " + str(caption["notice"]), size=9,
                                     colour=theme.INK, max_lines=3)
            top += 12
        available_w = page.width - MARGIN * 2
        available_h = page.height - top - FOOT
        scale = min(available_w / max(diagram.width, 1), available_h / max(diagram.height, 1), 1.6)
        offset_x = MARGIN + (available_w - diagram.width * scale) / 2
        offset_y = top

        def tx(x: float) -> float:
            return offset_x + x * scale

        def ty(y: float) -> float:
            return offset_y + y * scale

        for index, lane in enumerate(diagram.lanes):
            lane_y = ty(40 + index * diagram.lane_height)
            lane_h = diagram.lane_height * scale - 6
            page.rect(tx(24), lane_y, (diagram.width - 48) * scale, lane_h,
                      fill=theme.LANE_TINTS[index % 2], stroke=theme.GRID, line_width=0.5)
            page.text(tx(34), lane_y + lane_h / 2, lane[:18], size=8.5, bold=True, colour=theme.MUTED)

        for group in diagram.groups:
            stroke, fill, _ = theme.kind_colors(group.kind)
            page.rect(tx(group.x), ty(group.y), group.w * scale, group.h * scale, fill=fill,
                      stroke=stroke, line_width=0.8, radius=8)
            page.text(tx(group.x) + 10, ty(group.y) + 16, group.label[:40], size=9, bold=True,
                      colour=stroke)

        for edge in diagram.edges:
            if not edge.points:
                continue
            points = [(tx(x), ty(y)) for x, y in edge.points]
            page.polyline(points, colour=theme.EDGE,
                          width=min(2.4, 0.5 + math.log1p(edge.weight) * 0.4) * max(scale, 0.4),
                          dash=(3, 2) if edge.dashed else None)
            if len(points) >= 2:
                x1, y1 = points[-2]
                x2, y2 = points[-1]
                angle = math.atan2(-(y2 - y1), x2 - x1)
                page.arrow_head(x2, y2, angle, size=5.0, colour=theme.EDGE_STRONG)
            if edge.label:
                mid = points[len(points) // 2]
                page.text(mid[0] - 12, mid[1] - 3, edge.label[:16], size=6.5, colour=theme.MUTED)

        for node in diagram.nodes:
            self._draw_node(page, node, tx, ty, scale)

        if diagram.legend:
            cursor = MARGIN
            legend_y = page.height - FOOT + 6
            for label, colour in diagram.legend[:8]:
                page.rect(cursor, legend_y - 7, 8, 8, fill=colour, radius=2)
                page.text(cursor + 12, legend_y, label, size=7.5, colour=theme.MUTED)
                cursor += 26 + text_width(label, 7.5)

    def _draw_node(self, page: Page, node: Node, tx, ty, scale: float) -> None:
        stroke, fill, ink = theme.kind_colors(node.kind)
        x, y = tx(node.x), ty(node.y)
        w, h = node.w * scale, node.h * scale
        if node.kind in ("database", "datastore", "cache", "storage"):
            ry = min(8.0, h / 6)
            page.rect(x, y + ry, w, h - ry * 2, fill=fill, stroke=stroke, line_width=0.9)
            page.ellipse(x + w / 2, y + ry, w / 2, ry, fill=fill, stroke=stroke, line_width=0.9)
            page.ellipse(x + w / 2, y + h - ry, w / 2, ry, fill=fill, stroke=stroke, line_width=0.9)
        elif node.kind == "decision":
            page.polygon([(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)],
                         fill=fill, stroke=stroke, line_width=0.9)
        elif node.kind in ("start", "end", "event"):
            page.rect(x, y, w, h, fill=fill, stroke=stroke, line_width=1.1, radius=min(h / 2, 14))
        elif node.kind == "person":
            page.rect(x, y + 8, w, h - 8, fill=fill, stroke=stroke, line_width=0.9, radius=6)
            page.ellipse(x + w / 2, y + 7, 8, 8, fill=fill, stroke=stroke, line_width=0.9)
        else:
            page.rect(x, y, w, h, fill=fill, stroke=stroke, line_width=0.9, radius=6)

        font_size = max(5.5, min(9.5, 8.6 * max(scale, 0.55)))
        lines = wrap_text(node.label, w - 8, font_size, bold=True)[:3]
        total = len(lines) * font_size * 1.25 + (font_size if node.sublabel else 0)
        centre = y + h / 2 + (5 if node.kind == "person" else 0)
        start_y = centre - total / 2 + font_size
        for index, line in enumerate(lines):
            page.text(x, start_y + index * font_size * 1.25, line, size=font_size, bold=True,
                      colour=ink, align="center", width=w)
        if node.sublabel:
            sub = wrap_text(node.sublabel, w - 8, font_size - 1)[0]
            page.text(x, start_y + len(lines) * font_size * 1.25, sub, size=font_size - 1.2,
                      colour=theme.MUTED, align="center", width=w)

    # ------------------------------------------------------------ tables
    def table_pages(self, title: str, subtitle: str, headers: Sequence[str],
                    rows: Sequence[Sequence[str]], weights: Sequence[float],
                    landscape: bool = True, row_colours: Optional[Sequence[str]] = None) -> None:
        if not rows:
            page = self._page(landscape=landscape, title=title, subtitle=subtitle)
            page.text(MARGIN, self._content_top(), "None found.", size=10, colour=theme.MUTED)
            return
        index = 0
        first = True
        colours = list(row_colours or [""] * len(rows))
        while index < len(rows):
            page = self._page(landscape=landscape, title=title if first else f"{title} (continued)",
                              subtitle=subtitle if first else "")
            first = False
            y = self._content_top()
            width = page.width - MARGIN * 2
            consumed = self._table(page, MARGIN, y, width, headers, rows[index:], weights,
                                   max_y=page.height - FOOT, row_colours=colours[index:])
            index += consumed

    def _table(self, page: Page, x: float, y: float, width: float, headers: Sequence[str],
               rows: Sequence[Sequence[str]], weights: Sequence[float], max_y: float = 0,
               font_size: float = 8.0, row_colours: Optional[Sequence[str]] = None) -> int:
        max_y = max_y or (page.height - FOOT)
        columns = [width * w for w in weights]
        page.rect(x, y - 10, width, 18, fill="#1e293b", radius=3)
        cursor = x + 6
        for header, column_width in zip(headers, columns):
            page.text(cursor, y + 2, str(header)[:40], size=font_size, bold=True, colour="#ffffff")
            cursor += column_width
        y += 14

        drawn = 0
        for row_index, row in enumerate(rows):
            cells = []
            height = font_size * 1.5
            for value, column_width in zip(row, columns):
                lines = wrap_text(str(value), column_width - 10, font_size)[:3]
                cells.append(lines)
                height = max(height, len(lines) * font_size * 1.32 + 6)
            if y + height > max_y:
                break
            if row_index % 2 == 0:
                page.rect(x, y - 8, width, height, fill="#f8fafc")
            accent = (row_colours or [])[row_index] if row_colours and row_index < len(row_colours) else ""
            if accent:
                page.rect(x, y - 8, 2.5, height, fill=accent)
            cursor = x + 6
            for lines, column_width in zip(cells, columns):
                for line_index, line in enumerate(lines):
                    page.text(cursor, y + 2 + line_index * font_size * 1.32, line, size=font_size)
                cursor += column_width
            y += height
            drawn += 1
        page.line(x, y - 6, x + width, y - 6, colour=theme.GRID, width=0.5)
        return drawn

    def text_page(self, title: str, subtitle: str, blocks: Sequence[Tuple[str, str]]) -> None:
        page = self._page(title=title, subtitle=subtitle)
        y = self._content_top()
        for heading, body in blocks:
            if y > page.height - FOOT - 40:
                page = self._page(title=f"{title} (continued)")
                y = self._content_top()
            if heading:
                page.text(MARGIN, y, heading, size=10.5, bold=True)
                y += 14
            y = page.paragraph(MARGIN, y, page.width - MARGIN * 2, body, size=9.5, max_lines=60)
            y += 14


def build(result: ScanResult, diagrams: Dict[str, Diagram], path: str,
          max_diagrams: int = 24, captions: Optional[Dict[str, Dict[str, str]]] = None) -> None:
    captions = captions or {}
    builder = ReportBuilder(result, diagrams)
    builder.cover()
    if (result.profile or {}).get("artifacts", {}).get(
            "business-overview", {"include": True}).get("include", True):
        builder.business_page()
    builder.summary_page()

    order = ["c4-context", "c4-container", "application-landscape", "dependency-layers",
             "external-systems", "deployment", "dependency-graph"]
    rendered = 0
    for key in order:
        if key in diagrams:
            builder.diagram_page(diagrams[key], caption=captions.get(key))
            rendered += 1
    for key, diagram in diagrams.items():
        if key.startswith("components-") and rendered < max_diagrams:
            builder.diagram_page(diagram, caption=captions.get(key))
            rendered += 1
    for key, diagram in diagrams.items():
        if key.startswith("flow-") and rendered < max_diagrams:
            builder.diagram_page(diagram, caption=captions.get(key))
            rendered += 1

    builder.table_pages(
        "Applications", "Every unit built, deployed or published on its own",
        ["Application", "Kind", "Root", "Languages", "Frameworks", "Files", "LOC", "Style"],
        [[a.name, a.kind, a.root or ".", ", ".join(a.languages[:3]), ", ".join(a.frameworks[:3]),
          str(a.files), f"{a.loc:,}", a.architecture_style] for a in result.apps],
        [0.16, 0.08, 0.16, 0.13, 0.15, 0.06, 0.07, 0.19])

    builder.table_pages(
        "API surface", f"{len(result.endpoints)} endpoints and entrypoints",
        ["Kind", "Method", "Path", "Handler", "Framework", "Source"],
        [[e.kind, e.method, e.path, e.handler or "—", e.framework or "—", f"{e.file}:{e.line}"]
         for e in result.endpoints],
        [0.08, 0.08, 0.28, 0.16, 0.12, 0.28])

    builder.table_pages(
        "External systems", "Databases, queues, storage and third-party APIs, with evidence",
        ["System", "Kind", "Technology", "Used by", "Evidence"],
        [[s.name, s.kind, s.technology, ", ".join(s.apps) or "—",
          f"{s.evidence[0].file}:{s.evidence[0].line}" if s.evidence else "config"]
         for s in result.external_systems],
        [0.22, 0.12, 0.18, 0.18, 0.30])

    builder.table_pages(
        "Dependencies", f"{len(result.dependencies)} packages across "
                        f"{len({d.ecosystem for d in result.dependencies})} ecosystem(s)",
        ["Package", "Version", "Ecosystem", "Scope", "Direct", "Used", "Declared in"],
        [[d.name, d.version or "—", d.ecosystem, d.scope, "yes" if d.direct else "no",
          "yes" if d.used else "no", ", ".join(d.declared_in[:1])] for d in result.dependencies],
        [0.24, 0.12, 0.10, 0.08, 0.07, 0.07, 0.32])

    builder.table_pages(
        "Findings", f"{sum(result.metrics.findings_by_severity.values())} findings, "
                    f"highest severity first",
        ["Severity", "Finding", "Location", "Id", "CWE", "Fix"],
        [[f.severity, f.title, f"{f.file}:{f.line}" if f.file else "repository",
          f.identifier or "—", f.cwe or "—", f.remediation] for f in result.findings],
        [0.07, 0.24, 0.20, 0.10, 0.07, 0.32],
        row_colours=[theme.severity_color(f.severity) for f in result.findings])

    infra = result.infrastructure or {}
    if infra.get("containers") or infra.get("kubernetes") or infra.get("terraform"):
        rows = []
        for container in infra.get("containers") or []:
            rows.append(["compose", str(container.get("name")),
                         str(container.get("image") or container.get("build")),
                         ", ".join(container.get("ports", [])), str(container.get("file"))])
        for workload in infra.get("kubernetes") or []:
            rows.append([str(workload.get("kind")), str(workload.get("name")),
                         ", ".join(workload.get("images", [])), ", ".join(workload.get("ports", [])),
                         str(workload.get("file"))])
        for resource in infra.get("terraform") or []:
            rows.append([str(resource.get("block")), str(resource.get("name")),
                         str(resource.get("type")), str(resource.get("provider")),
                         str(resource.get("file"))])
        builder.table_pages("Infrastructure", "Containers, orchestration and infrastructure as code",
                            ["Kind", "Name", "Image / type", "Ports / provider", "File"], rows,
                            [0.12, 0.22, 0.26, 0.16, 0.24])

    builder.text_page(
        "Method and limits",
        "How these results were produced, and what they do not cover",
        [
            ("How this was produced",
             "repograph walks the repository, parses manifests and lockfiles, analyses source files "
             "per language for imports, symbols and endpoints, resolves each import to an internal "
             "file or an external package, and matches configuration and code against a signature "
             "table of external systems. Diagrams are laid out from that graph. No AI model was "
             "involved and no code was executed."),
            ("Import resolution",
             f"{result.summary.get('unresolved_imports', 0)} import statements could not be resolved "
             "to a file or package and are therefore missing from the dependency graph. Resolution is "
             "exact for Python, JavaScript/TypeScript, Go and JVM package layouts, and heuristic for "
             "other languages."),
            ("Dynamic behaviour",
             "Reflection, dependency injection containers, runtime plugin loading and string-built "
             "SQL or URLs are not traced. Process flows are reconstructed from static imports and "
             "guard clauses, so they show the intended path, not every runtime path."),
            ("External systems",
             "A signature match proves a reference exists in the code; it does not prove the system "
             "is used in production. Every detection carries the file and line it came from."),
            ("Vulnerabilities",
             "Advisory data comes from OSV.dev and is only fetched when the scan runs with --online. "
             + ("This report includes advisory data." if result.meta.online
                else "This report was produced offline, so published CVEs for dependencies are NOT covered.")),
            ("Warnings", "; ".join(result.meta.warnings) or "none"),
        ])
    builder.doc.save(path)
