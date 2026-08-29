"""The Excel workbook: one sheet per thing you would want to filter or pivot."""

from __future__ import annotations

from typing import Dict, List

from repograph_core.model import ScanResult

from .xlsx import SEVERITY_STYLE, STYLE_MONO, Sheet, write


def build(result: ScanResult, path: str) -> None:
    sheets: List[Sheet] = [
        _summary(result),
        _findings(result),
        _dependencies(result),
        _endpoints(result),
        _systems(result),
        _applications(result),
        _components(result),
        _edges(result),
        _infrastructure(result),
        _env(result),
        _files(result),
    ]
    write(path, [s for s in sheets if s.rows or s.headers],
          title=f"{result.meta.repo_name} — repograph")


def _summary(result: ScanResult) -> Sheet:
    metrics = result.metrics
    summary = result.summary
    sheet = Sheet(name="Summary", headers=["Metric", "Value"], widths=[36, 90], autofilter=False)
    rows = [
        ("Repository", result.meta.repo_name),
        ("Scanned path", result.meta.root),
        ("Generated", result.meta.generated_at),
        ("repograph version", result.meta.version),
        ("Advisory lookup", "OSV.dev (online)" if result.meta.online else "skipped (offline)"),
        ("Purpose", summary.get("purpose", "")),
        ("Shape", summary.get("shape", "")),
        ("Architecture style(s)", ", ".join(summary.get("architecture_styles", []))),
        ("Primary languages", ", ".join(summary.get("primary_languages", []))),
        ("Applications", metrics.apps),
        ("Components", metrics.components),
        ("Files scanned", metrics.scanned_files),
        ("Lines of code", metrics.loc),
        ("Significant lines", metrics.sloc),
        ("Endpoints", metrics.endpoints),
        ("Dependencies", metrics.dependencies),
        ("External systems", metrics.external_systems),
        ("Findings", sum(metrics.findings_by_severity.values())),
        ("Risk level", summary.get("risk_level", "")),
        ("Risk score", summary.get("risk_score", 0)),
        ("Test files", metrics.test_files),
        ("Test file ratio", metrics.test_ratio),
        ("Documentation files", metrics.doc_files),
        ("Dependency cycles", metrics.cycles),
        ("Unresolved imports", summary.get("unresolved_imports", 0)),
        ("Data stores", ", ".join(summary.get("data_stores", []))),
        ("Integrations", ", ".join(summary.get("integrations", []))),
        ("Has CI", summary.get("has_ci")),
        ("Has containers", summary.get("has_containers")),
        ("Has infrastructure as code", summary.get("has_iac")),
        ("Git commits", result.git.commits),
        ("Git contributors", result.git.contributors),
        ("Git active period", f"{result.git.first_commit} .. {result.git.last_commit}"),
        ("Scan duration (s)", metrics.duration_seconds),
    ]
    for label, value in rows:
        sheet.add([label, value])
    sheet.add(["", ""])
    sheet.add(["Findings by severity", ""])
    for severity, count in metrics.findings_by_severity.items():
        sheet.add([f"  {severity}", count])
    sheet.add(["", ""])
    sheet.add(["Lines of code by language", ""])
    for language, loc in list(metrics.languages.items())[:25]:
        sheet.add([f"  {language}", loc])
    return sheet


def _findings(result: ScanResult) -> Sheet:
    sheet = Sheet(
        name="Findings",
        headers=["Severity", "Category", "Title", "Identifier", "CWE", "File", "Line", "Package",
                 "Version", "Fixed in", "Confidence", "Application", "Remediation", "Snippet",
                 "References"],
        widths=[11, 12, 52, 18, 11, 46, 7, 22, 14, 14, 11, 18, 60, 46, 40],
    )
    for finding in result.findings:
        sheet.add([finding.severity, finding.category, finding.title, finding.identifier,
                   finding.cwe, finding.file, finding.line or "", finding.package, finding.version,
                   finding.fixed_version, finding.confidence, finding.app, finding.remediation,
                   finding.snippet, " ".join(finding.references)],
                  style=SEVERITY_STYLE.get(finding.severity))
    return sheet


def _dependencies(result: ScanResult) -> Sheet:
    sheet = Sheet(
        name="Dependencies",
        headers=["Package", "Version", "Ecosystem", "Scope", "Direct", "Declared", "Used",
                 "Used by (files)", "Declared in", "Applications", "PURL"],
        widths=[34, 16, 12, 10, 8, 9, 7, 14, 40, 22, 42],
    )
    for dep in result.dependencies:
        sheet.add([dep.name, dep.version, dep.ecosystem, dep.scope, dep.direct, dep.declared,
                   dep.used, len(dep.used_by), "; ".join(dep.declared_in[:3]), "; ".join(dep.apps),
                   dep.purl])
    return sheet


def _endpoints(result: ScanResult) -> Sheet:
    sheet = Sheet(
        name="Endpoints",
        headers=["Kind", "Method", "Path", "Handler", "Framework", "Application", "Component",
                 "File", "Line", "Notes"],
        widths=[10, 9, 44, 26, 16, 20, 24, 44, 7, 34],
    )
    for endpoint in result.endpoints:
        sheet.add([endpoint.kind, endpoint.method, endpoint.path, endpoint.handler,
                   endpoint.framework, endpoint.app, endpoint.component, endpoint.file,
                   endpoint.line or "", endpoint.description])
    return sheet


def _systems(result: ScanResult) -> Sheet:
    sheet = Sheet(
        name="External systems",
        headers=["System", "Kind", "Technology", "Direction", "Applications", "References",
                 "Evidence 1", "Evidence 2", "Description"],
        widths=[28, 14, 20, 12, 26, 11, 40, 40, 46],
    )
    for system in result.external_systems:
        evidence = [f"{ev.file}:{ev.line}" for ev in system.evidence[:2]]
        sheet.add([system.name, system.kind, system.technology, system.direction,
                   "; ".join(system.apps), len(system.evidence),
                   evidence[0] if evidence else "", evidence[1] if len(evidence) > 1 else "",
                   system.description])
    return sheet


def _applications(result: ScanResult) -> Sheet:
    sheet = Sheet(
        name="Applications",
        headers=["Application", "Kind", "Root", "Languages", "Frameworks", "Files", "LOC",
                 "Components", "Endpoints", "Architecture style", "Entrypoints", "Description"],
        widths=[26, 12, 30, 24, 30, 8, 10, 12, 11, 34, 30, 60],
    )
    endpoints: Dict[str, int] = {}
    for endpoint in result.endpoints:
        endpoints[endpoint.app] = endpoints.get(endpoint.app, 0) + 1
    for app in result.apps:
        sheet.add([app.name, app.kind, app.root or ".", "; ".join(app.languages),
                   "; ".join(app.frameworks), app.files, app.loc, len(app.components),
                   endpoints.get(app.id, 0), app.architecture_style, "; ".join(app.entrypoints[:4]),
                   app.description])
    return sheet


def _components(result: ScanResult) -> Sheet:
    sheet = Sheet(
        name="Components",
        headers=["Component", "Application", "Path", "Kind", "Languages", "Files", "LOC", "Layer"],
        widths=[30, 22, 46, 10, 22, 8, 10, 8],
    )
    app_names = {a.id: a.name for a in result.apps}
    for component in result.components:
        sheet.add([component.name, app_names.get(component.app, component.app), component.path,
                   component.kind, "; ".join(component.languages), component.files, component.loc,
                   result.layers.get(component.id, "")])
    return sheet


def _edges(result: ScanResult) -> Sheet:
    sheet = Sheet(name="Dependencies graph",
                  headers=["Source", "Target", "Kind", "Weight", "Label", "Evidence"],
                  widths=[40, 40, 12, 9, 22, 46])
    names = {c.id: c.name for c in result.components}
    names.update({a.id: a.name for a in result.apps})
    names.update({s.id: s.name for s in result.external_systems})
    for edge in result.edges:
        evidence = f"{edge.evidence[0].file}:{edge.evidence[0].line}" if edge.evidence else ""
        sheet.add([names.get(edge.source, edge.source), names.get(edge.target, edge.target),
                   edge.kind, edge.weight, edge.label, evidence])
    return sheet


def _infrastructure(result: ScanResult) -> Sheet:
    infra = result.infrastructure or {}
    sheet = Sheet(name="Infrastructure",
                  headers=["Type", "Name", "Detail", "Ports / provider", "File"],
                  widths=[16, 30, 44, 22, 40])
    for container in infra.get("containers") or []:
        sheet.add(["compose service", container.get("name"),
                   container.get("image") or f"build {container.get('build', '')}",
                   ", ".join(container.get("ports", [])), container.get("file")])
    for dockerfile in infra.get("dockerfiles") or []:
        sheet.add(["dockerfile", dockerfile.get("file"),
                   ", ".join(dockerfile.get("base_images", [])),
                   ", ".join(str(p) for p in dockerfile.get("ports", [])), dockerfile.get("file")])
    for workload in infra.get("kubernetes") or []:
        sheet.add([f"k8s {workload.get('kind')}", workload.get("name"),
                   ", ".join(workload.get("images", [])), ", ".join(workload.get("ports", [])),
                   workload.get("file")])
    for resource in infra.get("terraform") or []:
        sheet.add([f"terraform {resource.get('block')}", resource.get("name"),
                   resource.get("type"), resource.get("provider"), resource.get("file")])
    for pipeline in infra.get("ci") or []:
        sheet.add(["ci pipeline", pipeline.get("name"), pipeline.get("system"),
                   ", ".join(pipeline.get("triggers", [])), pipeline.get("file")])
    for function in infra.get("serverless") or []:
        for entry in function.get("functions", []):
            sheet.add(["serverless function", entry.get("name"), entry.get("handler"),
                       ", ".join(entry.get("events", [])), function.get("file")])
    return sheet


def _env(result: ScanResult) -> Sheet:
    env_vars = (result.infrastructure or {}).get("env_vars") or {}
    sheet = Sheet(name="Configuration", headers=["Variable", "Kind", "Used in files"],
                  widths=[38, 16, 80])
    for name, info in env_vars.items():
        sheet.add([name, info.get("kind", ""), "; ".join(info.get("files", [])[:6])])
    return sheet


def _files(result: ScanResult) -> Sheet:
    sheet = Sheet(name="Files",
                  headers=["Path", "Language", "Kind", "LOC", "SLOC", "Bytes", "Application",
                           "Component", "Symbols"],
                  widths=[64, 14, 10, 8, 8, 10, 22, 28, 9])
    for info in sorted(result.files, key=lambda f: -f.loc)[:5000]:
        sheet.add([info.path, info.language, info.kind, info.loc, info.sloc, info.size,
                   info.app, info.component, info.symbols], style=STYLE_MONO)
    return sheet
