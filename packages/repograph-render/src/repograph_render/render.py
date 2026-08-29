"""Writes every artefact for one scan into a single output folder."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from repograph_core.model import ScanResult
from repograph_core.security.sbom import cyclonedx, spdx

from . import (
    archimate_xml,
    bpmn,
    csv_export,
    deck,
    dot,
    mermaid,
    pdfreport,
    plantuml,
    report_ai,
    report_html,
    report_md,
    svg,
    workbook,
)
from . import diagrams as diagram_mod

ALL_FORMATS = ("html", "json", "markdown", "ai", "svg", "mermaid", "plantuml", "dot", "bpmn",
               "archimate", "csv", "xlsx", "pptx", "pdf", "sbom")
DEFAULT_FORMATS = ALL_FORMATS

ProgressFn = Callable[[str], None]


@dataclass
class RenderResult:
    output_dir: str
    files: List[str] = field(default_factory=list)
    skipped: Dict[str, str] = field(default_factory=dict)
    duration: float = 0.0

    def relative(self) -> List[str]:
        return sorted(os.path.relpath(p, self.output_dir).replace(os.sep, "/") for p in self.files)


def _write(path: str, content: str, results: RenderResult) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    results.files.append(path)


def render_all(result: ScanResult, output_dir: str, formats: Sequence[str] = DEFAULT_FORMATS,
               progress: Optional[ProgressFn] = None, max_flows: int = 14) -> RenderResult:
    started = time.time()
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    out = RenderResult(output_dir=output_dir)
    wanted = set(formats)

    def note(message: str) -> None:
        if progress:
            progress(message)

    note("Laying out diagrams")
    layouts = diagram_mod.build_all(result, max_flows=max_flows)
    note("Generating Mermaid sources")
    mermaid_sources = mermaid.build_all(result, max_flows=max_flows)

    if "svg" in wanted:
        note("Writing SVG diagrams")
        for name, diagram in layouts.items():
            _write(os.path.join(output_dir, "diagrams", f"{name}.svg"),
                   svg.wrap_document(svg.render_diagram(diagram)), out)

    if "mermaid" in wanted:
        note("Writing Mermaid diagrams")
        for name, source in mermaid_sources.items():
            _write(os.path.join(output_dir, "diagrams", "mermaid", f"{name}.mmd"), source, out)

    if "plantuml" in wanted:
        note("Writing PlantUML diagrams")
        for name, source in plantuml.build_all(result, max_flows=max_flows).items():
            _write(os.path.join(output_dir, "diagrams", "plantuml", f"{name}.puml"), source, out)

    if "dot" in wanted:
        note("Writing Graphviz sources")
        for name, source in dot.build_all(result).items():
            _write(os.path.join(output_dir, "diagrams", "dot", f"{name}.dot"), source, out)

    if "bpmn" in wanted and result.flows:
        note("Writing BPMN processes")
        for name, source in bpmn.build_all(result.flows, max_flows=max_flows).items():
            _write(os.path.join(output_dir, "diagrams", "bpmn", f"{name}.bpmn"), source, out)

    if "archimate" in wanted:
        note("Writing ArchiMate model")
        _write(os.path.join(output_dir, "models", "archimate.xml"), archimate_xml.export(result), out)

    ai_report = ""
    if "ai" in wanted:
        note("Writing agent report")
        ai_report = report_ai.render(result, mermaid_sources)
        _write(os.path.join(output_dir, "AI-REPORT.md"), ai_report, out)

    if "markdown" in wanted:
        note("Writing Markdown report")
        _write(os.path.join(output_dir, "report.md"), report_md.render(result, mermaid_sources), out)

    if "json" in wanted:
        note("Writing JSON model")
        _write(os.path.join(output_dir, "repograph.json"), result.to_json(), out)

    if "sbom" in wanted:
        note("Writing SBOM")
        _write(os.path.join(output_dir, "sbom.cdx.json"),
               json.dumps(cyclonedx(result), indent=2), out)
        _write(os.path.join(output_dir, "sbom.spdx.json"), json.dumps(spdx(result), indent=2), out)

    if "csv" in wanted:
        note("Writing CSV exports")
        out.files.extend(csv_export.write_all(result, os.path.join(output_dir, "data")))

    if "xlsx" in wanted:
        note("Writing Excel workbook")
        path = os.path.join(output_dir, "report.xlsx")
        try:
            workbook.build(result, path)
            out.files.append(path)
        except Exception as exc:
            out.skipped["xlsx"] = f"{type(exc).__name__}: {exc}"

    if "pptx" in wanted:
        note("Writing PowerPoint deck")
        path = os.path.join(output_dir, "presentation.pptx")
        try:
            deck.build(result, layouts, path)
            out.files.append(path)
        except Exception as exc:
            out.skipped["pptx"] = f"{type(exc).__name__}: {exc}"

    if "pdf" in wanted:
        note("Writing PDF report")
        path = os.path.join(output_dir, "report.pdf")
        try:
            pdfreport.build(result, layouts, path)
            out.files.append(path)
        except Exception as exc:
            out.skipped["pdf"] = f"{type(exc).__name__}: {exc}"

    if "html" in wanted:
        note("Writing interactive HTML report")
        svg_sources = {name: svg.render_diagram(diagram) for name, diagram in layouts.items()}
        listing = sorted(os.path.relpath(p, output_dir).replace(os.sep, "/") for p in out.files)
        _write(os.path.join(output_dir, "index.html"),
               report_html.render(result, svg_sources, mermaid_sources, ai_report, listing), out)

    _write(os.path.join(output_dir, "README.md"), _folder_readme(result, out), out)
    _write(os.path.join(output_dir, "MANIFEST.json"),
           json.dumps(_manifest(result, out), indent=2), out)
    out.duration = round(time.time() - started, 2)
    return out


def _manifest(result: ScanResult, out: RenderResult) -> Dict[str, object]:
    return {
        "tool": "repograph",
        "version": result.meta.version,
        "generated_at": result.meta.generated_at,
        "repository": result.meta.repo_name,
        "root": result.meta.root,
        "online": result.meta.online,
        "summary": {
            "applications": result.metrics.apps,
            "components": result.metrics.components,
            "files": result.metrics.scanned_files,
            "loc": result.metrics.loc,
            "endpoints": result.metrics.endpoints,
            "dependencies": result.metrics.dependencies,
            "external_systems": result.metrics.external_systems,
            "findings": result.metrics.findings_by_severity,
            "risk_level": result.summary.get("risk_level"),
        },
        "files": out.relative(),
        "skipped": out.skipped,
    }


def _folder_readme(result: ScanResult, out: RenderResult) -> str:
    listing = out.relative()
    diagrams = [f for f in listing if f.startswith("diagrams/") and f.endswith(".svg")]
    advisory_note = (", advisories checked against OSV.dev" if result.meta.online
                     else ", offline (no advisory lookup)")
    return f"""# {result.meta.repo_name} — repograph output

Generated {result.meta.generated_at} by repograph {result.meta.version}.
Everything in this folder was derived from the repository at `{result.meta.root}` by static
analysis — no AI, no code execution{advisory_note}.

## Start here

| If you are… | Open |
|---|---|
| a human wanting the full picture | `index.html` (interactive: 2D + 3D graph, all diagrams, sortable tables) |
| an AI agent or a tool | `AI-REPORT.md` (dense, structured, every claim carries file:line) |
| presenting to people | `presentation.pptx` or `report.pdf` |
| doing security or compliance work | `report.xlsx`, `data/findings.csv`, `sbom.cdx.json` |
| wiring this into another tool | `repograph.json` (the complete model) |

## What is here

- `index.html` — interactive report: overview, architecture views, 2D and 3D dependency graphs,
  applications, process flows, endpoints, dependencies, findings, infrastructure.
- `report.pdf` — printable report with vector diagrams and paginated tables.
- `presentation.pptx` — slide deck; diagrams are editable shapes, not images.
- `report.xlsx` — workbook: findings, dependencies, endpoints, systems, components, edges, files.
- `report.md` — Markdown report with embedded Mermaid diagrams (renders on GitHub).
- `AI-REPORT.md` — the same analysis written for a model to read.
- `repograph.json` — the full scan model (schema version {result.meta.schema_version}).
- `MANIFEST.json` — what was written, plus headline numbers.
- `sbom.cdx.json`, `sbom.spdx.json` — CycloneDX 1.5 and SPDX 2.3 bills of materials.
- `data/*.csv` — one CSV per entity for spreadsheets, dashboards and diffing.
- `diagrams/*.svg` — {len(diagrams)} rendered diagrams.
- `diagrams/mermaid/*.mmd` — Mermaid sources (paste anywhere).
- `diagrams/plantuml/*.puml` — C4-PlantUML and ArchiMate sources.
- `diagrams/dot/*.dot` — Graphviz sources (`dot -Tsvg`).
- `diagrams/bpmn/*.bpmn` — BPMN 2.0 processes with layout (open in bpmn.io / Camunda).
- `models/archimate.xml` — ArchiMate 3.1 Open Exchange model (import into Archi).

## Headline numbers

- {result.metrics.apps} application(s), {result.metrics.components} components,
  {result.metrics.loc:,} lines across {result.metrics.scanned_files} files
- {result.metrics.endpoints} endpoints · {result.metrics.external_systems} external systems ·
  {result.metrics.dependencies} dependencies
- Findings: {', '.join(f'{k}={v}' for k, v in result.metrics.findings_by_severity.items()) or 'none'}
- Overall risk: **{result.summary.get('risk_level', 'unknown')}**

## Caveats

{chr(10).join('- ' + w for w in result.meta.warnings) or '- none recorded'}
"""
