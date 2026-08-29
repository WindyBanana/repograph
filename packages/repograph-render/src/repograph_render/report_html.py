"""The interactive HTML report — the main human-facing artefact."""

from __future__ import annotations

import html
import json
from typing import Dict, Iterable, Optional, Sequence, Tuple

from repograph_core.model import ScanResult

from . import charts, theme
from .webassets import CSS, JS


def e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _link(result: ScanResult, path: str, line: int = 0) -> str:
    """Link a file to its remote if we know one, otherwise show the path."""
    remote = (result.git.remote or "").strip()
    label = e(path) + (f":{line}" if line else "")
    if remote.startswith("git@"):
        remote = "https://" + remote[4:].replace(":", "/", 1)
    if remote.endswith(".git"):
        remote = remote[:-4]
    branch = result.git.branch or "HEAD"
    if remote.startswith("https://") and ("github.com" in remote or "gitlab.com" in remote):
        anchor = f"#L{line}" if line else ""
        return f'<a class="mono" href="{e(remote)}/blob/{e(branch)}/{e(path)}{anchor}">{label}</a>'
    return f'<span class="mono">{label}</span>'


def _table(table_id: str, headers: Sequence[Tuple[str, bool]], rows: Iterable[Sequence[str]],
           row_attrs: Optional[Sequence[str]] = None) -> str:
    head = "".join(
        f'<th data-numeric="{1 if numeric else 0}">{e(label)}</th>' for label, numeric in headers
    )
    body = []
    rows = list(rows)
    attrs = row_attrs or [""] * len(rows)
    for row, attr in zip(rows, attrs):
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr {attr}>{cells}</tr>")
    return (
        f'<div class="table-wrap"><table data-sortable id="{table_id}">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _search(table_id: str, placeholder: str) -> str:
    return (f'<div class="toolbar"><input type="search" data-filter="{table_id}" '
            f'placeholder="{e(placeholder)}"><span class="muted small" id="{table_id}-count"></span></div>')


def _cards(items: Sequence[Tuple[str, str]]) -> str:
    return '<div class="cards">' + "".join(
        f'<div class="card"><div class="value">{e(value)}</div><div class="label">{e(label)}</div></div>'
        for value, label in items
    ) + "</div>"


def _graph_payload(result: ScanResult, max_nodes: int = 260) -> Dict[str, object]:
    app_names = {a.id: a.name for a in result.apps}
    components = sorted(result.components, key=lambda c: -c.files)[:max_nodes]
    ids = {c.id for c in components}
    nodes = [{
        "id": c.id, "label": c.name, "kind": "component", "app": c.app,
        "size": max(1, c.files),
        "detail": f"{app_names.get(c.app, '')} · {c.files} files · {c.loc} LOC"
                  f"<br><span class='mono'>{e(c.path)}</span>",
    } for c in components]
    for system in result.external_systems:
        nodes.append({
            "id": system.id, "label": system.name, "kind": system.kind, "app": "",
            "size": max(2, len(system.evidence) * 2),
            "detail": f"{e(system.technology)} · {system.kind} · {len(system.evidence)} reference(s)",
        })
        ids.add(system.id)
    links = [{"source": edge.source, "target": edge.target, "weight": edge.weight}
             for edge in result.edges
             if edge.source in ids and edge.target in ids]
    for edge in result.edges:
        if edge.kind in ("db", "cache", "queue", "storage", "http") and edge.target in ids:
            for component in components:
                if component.app == edge.source:
                    links.append({"source": component.id, "target": edge.target, "weight": 1})
                    break
    colors = {kind: value[0] for kind, value in theme.KINDS.items()}
    return {"nodes": nodes, "links": links, "colors": colors}


def render(result: ScanResult, diagrams: Dict[str, str], mermaid: Dict[str, str],
           ai_report: str = "", output_files: Sequence[str] = (),
           agent_panel: str = "") -> str:
    meta = result.meta
    summary = result.summary

    tabs = [
        ("overview", "Overview"), ("architecture", "Architecture"), ("graph2d", "Graph 2D"),
        ("graph3d", "Graph 3D"), ("apps", "Applications"), ("flows", "Process flows"),
        ("endpoints", "APIs & endpoints"), ("dependencies", "Dependencies"),
        ("security", "Vulnerabilities"), ("integrations", "External systems"),
        ("infrastructure", "Infrastructure"), ("files", "Files & hotspots"),
        ("ai", "AI report"),
    ]
    nav = "".join(f'<button data-tab="{key}" role="tab">{e(label)}</button>' for key, label in tabs)

    sections = [
        _overview(result),
        _architecture(result, diagrams, mermaid),
        _graph_section("graph2d", "Dependency graph (2D)",
                       "Drag to pan, scroll to zoom, click a node to isolate its neighbourhood.",
                       result, controls=True),
        _graph_section("graph3d", "Dependency graph (3D)",
                       "Drag to orbit, scroll to zoom. Node size follows file count, colour follows type.",
                       result, controls=False),
        _apps(result, diagrams, mermaid),
        _flows(result, diagrams, mermaid),
        _endpoints(result),
        _dependencies(result),
        _security(result),
        _integrations(result),
        _infrastructure(result),
        _files(result),
        _ai(ai_report, output_files, agent_panel, result),
    ]

    payload = json.dumps({"graph": _graph_payload(result), "colors":
                          {kind: value[0] for kind, value in theme.KINDS.items()}},
                         separators=(",", ":"))
    risk = str(summary.get("risk_level", "unknown"))
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(meta.repo_name)} — architecture report</title>
<meta name="generator" content="repograph {e(meta.version)}">
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <h1>{e(meta.repo_name)}</h1>
  <span class="badge {e(risk)}">{e(risk)} risk</span>
  <span class="meta">{result.metrics.scanned_files} files · {result.metrics.loc:,} LOC ·
   {result.metrics.apps} app(s) · scanned {e(meta.generated_at)} · repograph {e(meta.version)}</span>
</header>
<nav class="tabs" role="tablist">{nav}</nav>
<main>{''.join(sections)}</main>
<footer>Generated by repograph — deterministic, no AI, no network unless <code>--online</code> was
passed. Every finding links to the file and line it came from.</footer>
<script>window.__REPOGRAPH__ = {payload};</script>
<script>{JS}</script>
</body></html>"""


# ------------------------------------------------------------------ sections

def _overview(result: ScanResult) -> str:
    summary = result.summary
    metrics = result.metrics
    languages = charts.bar_chart(charts.fold_other(list(metrics.languages.items())),
                                 title="Lines of code by language", width=520)
    severity_chart = charts.severity_bar(metrics.findings_by_severity,
                                         title="Findings by severity", width=520)
    component_sizes = charts.treemap(
        charts.fold_other([(c.name, c.loc or c.files) for c in result.components], 14),
        title="Code volume by component", width=640, height=280)
    apps_chart = charts.bar_chart(
        [(a.name, a.loc or a.files) for a in sorted(result.apps, key=lambda x: -(x.loc or x.files))[:10]],
        title="Lines of code by application", width=520)

    styles = summary.get("architecture_styles") or []
    stores = summary.get("data_stores") or []
    integrations = summary.get("integrations") or []
    top_findings = [f for f in result.findings if f.severity in ("critical", "high")][:8]

    findings_html = "".join(
        f'<div class="finding {e(f.severity)}"><b>{e(f.title)}</b> '
        f'<span class="badge {e(f.severity)}">{e(f.severity)}</span><br>'
        f'<span class="where">{e(f.file)}{":" + str(f.line) if f.line else ""}</span>'
        f'<div class="small muted">{e(f.remediation)}</div></div>'
        for f in top_findings
    ) or '<p class="muted">No critical or high severity findings.</p>'

    return f"""<section data-tab="overview" hidden>
<h2>What this repository is</h2>
<p class="lede">{e(summary.get('purpose', ''))}</p>
<div class="pill-row">
  <span class="tag">shape: {e(summary.get('shape', ''))}</span>
  {''.join(f'<span class="tag">{e(s)}</span>' for s in styles)}
  {''.join(f'<span class="tag">{e(l)}</span>' for l in (summary.get('primary_languages') or [])[:4])}
</div>
{_cards([
    (f"{result.metrics.apps}", "Applications"),
    (f"{result.metrics.components}", "Components"),
    (f"{result.metrics.loc:,}", "Lines of code"),
    (f"{result.metrics.endpoints}", "Endpoints"),
    (f"{result.metrics.dependencies}", "Dependencies"),
    (f"{result.metrics.external_systems}", "External systems"),
    (f"{sum(result.metrics.findings_by_severity.values())}", "Findings"),
    (f"{result.metrics.test_ratio:.0%}", "Test-file ratio"),
])}
<div class="grid2" style="margin-top:16px">
  <div class="panel">{languages}</div>
  <div class="panel">{severity_chart}</div>
</div>
<div class="grid2">
  <div class="panel">{apps_chart}</div>
  <div class="panel">{component_sizes}</div>
</div>
<h2>Highest severity findings</h2>
{findings_html}
<h2>At a glance</h2>
<div class="panel"><dl class="kv">
  <dt>Data stores</dt><dd>{e(', '.join(stores) or 'none detected')}</dd>
  <dt>External integrations</dt><dd>{e(', '.join(integrations[:20]) or 'none detected')}</dd>
  <dt>CI / CD</dt><dd>{'yes' if summary.get('has_ci') else 'not detected'}</dd>
  <dt>Containers</dt><dd>{'yes' if summary.get('has_containers') else 'not detected'}</dd>
  <dt>Infrastructure as code</dt><dd>{'yes' if summary.get('has_iac') else 'not detected'}</dd>
  <dt>Dependency cycles</dt><dd>{result.metrics.cycles}</dd>
  <dt>Unresolved imports</dt><dd>{summary.get('unresolved_imports', 0)}</dd>
  <dt>Git history</dt><dd>{_git_line(result)}</dd>
</dl></div>
{_warnings(result)}
</section>"""


def _git_line(result: ScanResult) -> str:
    git = result.git
    if not git.is_repo:
        return "not a git repository"
    return (f"{git.commits} commits · {git.contributors} contributor(s) · "
            f"{e(git.first_commit)} → {e(git.last_commit)} · branch {e(git.branch or 'n/a')}")


def _warnings(result: ScanResult) -> str:
    if not result.meta.warnings:
        return ""
    items = "".join(f"<li>{e(w)}</li>" for w in result.meta.warnings)
    return f'<h2>Scan notes</h2><div class="panel"><ul class="small muted">{items}</ul></div>'


def _diagram_block(name: str, svg: str, mermaid_source: str = "") -> str:
    details = ""
    if mermaid_source:
        details = (f'<details><summary>Mermaid source — paste into any Markdown or AI tool</summary>'
                   f'<pre>{e(mermaid_source)}</pre></details>')
    return f'<h3>{e(name)}</h3><div class="diagram">{svg}</div>{details}'


def _architecture(result: ScanResult, diagrams: Dict[str, str], mermaid: Dict[str, str]) -> str:
    blocks = []
    order = [
        ("c4-context", "C4 level 1 — system context"),
        ("c4-container", "C4 level 2 — containers"),
        ("application-landscape", "Application landscape"),
        ("dependency-layers", "Dependency layers"),
        ("external-systems", "External systems map"),
        ("deployment", "Deployment view"),
        ("dependency-graph", "Component dependency graph"),
    ]
    for key, title in order:
        if key in diagrams:
            blocks.append(_diagram_block(title, diagrams[key], mermaid.get(key, "")))
    return f'<section data-tab="architecture" hidden><h2>Architecture views</h2>' \
           f'<p class="lede">Generated from the code itself: every box is a directory, package or ' \
           f'detected external system, and every arrow is an import, a call or a declared dependency.</p>' \
           f'{"".join(blocks)}</section>'


def _graph_section(tab: str, title: str, description: str, result: ScanResult,
                   controls: bool) -> str:
    options = "".join(f'<option value="{e(a.id)}">{e(a.name)}</option>' for a in result.apps)
    toolbar = ""
    if controls:
        toolbar = f"""<div class="toolbar">
  <select id="graph2d-app"><option value="">All applications</option>{options}</select>
  <input type="search" id="graph2d-search" placeholder="Highlight components…">
  <button class="ghost" id="graph2d-relayout">Re-run layout</button>
</div>"""
    else:
        toolbar = '<div class="toolbar"><button class="ghost" id="graph3d-rotate">Pause rotation</button></div>'
    legend = "".join(
        f'<span><span class="dot" style="background:{theme.KINDS[k][0]}"></span>{e(label)}</span>'
        for k, label in [("component", "Component"), ("database", "Database"), ("queue", "Queue"),
                         ("external", "External API"), ("auth", "Auth"), ("observability", "Observability")]
    )
    return f"""<section data-tab="{tab}" hidden>
<h2>{e(title)}</h2>
<p class="lede">{e(description)}</p>
{toolbar}
<div class="canvas-wrap"><canvas id="{tab}"></canvas><div class="tooltip" id="tip{tab[-2:]}"></div></div>
<div class="legend">{legend}</div>
</section>"""


def _apps(result: ScanResult, diagrams: Dict[str, str], mermaid: Dict[str, str]) -> str:
    blocks = []
    endpoints_by_app: Dict[str, int] = {}
    for endpoint in result.endpoints:
        endpoints_by_app[endpoint.app] = endpoints_by_app.get(endpoint.app, 0) + 1
    for app in result.apps:
        components = [c for c in result.components if c.app == app.id]
        systems = [s for s in result.external_systems if app.id in s.apps]
        # "depends" comes from imports, "deploy" from compose depends_on — both
        # are real relationships between applications.
        kinds = ("depends", "deploy")
        depends = [e_.target for e_ in result.edges if e_.kind in kinds and e_.source == app.id]
        depended = [e_.source for e_ in result.edges if e_.kind in kinds and e_.target == app.id]
        names = {a.id: a.name for a in result.apps}
        diagram = diagrams.get(f"components-{app.id}", "")
        diagram_block = (f'<details><summary>Component diagram</summary>'
                         f'<div class="diagram">{diagram}</div></details>') if diagram else ""
        ai_block = ""
        if app.ai_summary:
            responsibilities = ""
            if app.ai_responsibilities:
                items = "".join(f"<li>{e(r)}</li>" for r in app.ai_responsibilities)
                responsibilities = f'<ul class="small">{items}</ul>'
            ai_block = (f'<div class="panel" style="margin:8px 0"><span class="tag">AI generated'
                        f'</span> <span class="small">{e(app.ai_summary)}</span>'
                        f'{responsibilities}</div>')
        purpose_block = ""
        if app.purpose and app.purpose != app.description:
            purpose_block = (f'<p class="small muted"><b>Read from the code:</b> '
                             f'{e(app.purpose)}</p>')
        blocks.append(f"""<div class="panel">
<h3 style="color:var(--ink);text-transform:none;font-size:15px">{e(app.name)}
 <span class="tag">{e(app.kind)}</span></h3>
<p class="small">{e(app.description or 'No description found in a README or manifest.')}</p>
{purpose_block}
{ai_block}
<dl class="kv small">
  <dt>Root</dt><dd class="mono">{e(app.root or '.')}</dd>
  <dt>Architecture style</dt><dd>{e(app.architecture_style)}</dd>
  <dt>Languages</dt><dd>{e(', '.join(app.languages[:6]) or '—')}</dd>
  <dt>Frameworks</dt><dd>{e(', '.join(app.frameworks[:8]) or '—')}</dd>
  <dt>Size</dt><dd>{app.files} files · {app.loc:,} LOC · {len(components)} components</dd>
  <dt>Endpoints</dt><dd>{endpoints_by_app.get(app.id, 0)}</dd>
  <dt>Entrypoints</dt><dd class="mono">{e(', '.join(app.entrypoints[:4]) or '—')}</dd>
  <dt>Depends on</dt><dd>{e(', '.join(names.get(d, d) for d in depends) or '—')}</dd>
  <dt>Depended on by</dt><dd>{e(', '.join(names.get(d, d) for d in depended) or '—')}</dd>
  <dt>External systems</dt><dd>{e(', '.join(s.name for s in systems) or '—')}</dd>
</dl>
{diagram_block}
</div>""")
    return f'<section data-tab="apps" hidden><h2>Applications in this repository</h2>' \
           f'<p class="lede">Each unit that is built, deployed or published on its own.</p>' \
           f'{"".join(blocks)}</section>'


def _flows(result: ScanResult, diagrams: Dict[str, str], mermaid: Dict[str, str]) -> str:
    if not result.flows:
        return '<section data-tab="flows" hidden><h2>Process flows</h2>' \
               '<p class="muted">No entrypoints were found to build process flows from.</p></section>'
    blocks = []
    for flow in result.flows:
        svg = diagrams.get(f"flow-{flow.id}", "")
        mmd = mermaid.get(f"flow-{flow.id}", "")
        seq = mermaid.get(f"sequence-{flow.id}", "")
        extra = ""
        if seq:
            extra = f'<details><summary>Sequence diagram (Mermaid)</summary><pre>{e(seq)}</pre></details>'
        blocks.append(f"""<div class="panel">
<h3 style="color:var(--ink);text-transform:none;font-size:15px">{e(flow.name)}</h3>
<p class="small muted">{e(flow.description)}</p>
<div class="diagram">{svg}</div>
<details><summary>Mermaid flowchart source</summary><pre>{e(mmd)}</pre></details>
{extra}</div>""")
    return f'<section data-tab="flows" hidden><h2>Process flows</h2>' \
           f'<p class="lede">Reconstructed by following each entrypoint through the import graph. ' \
           f'Lanes are architectural layers; diamonds are guard clauses found in the entry file.</p>' \
           f'{"".join(blocks)}</section>'


def _endpoints(result: ScanResult) -> str:
    rows = []
    for endpoint in sorted(result.endpoints, key=lambda x: (x.kind, x.path, x.method)):
        rows.append([
            f'<span class="tag">{e(endpoint.kind)}</span>',
            f"<b>{e(endpoint.method)}</b>",
            f'<span class="mono">{e(endpoint.path)}</span>',
            e(endpoint.handler or "—"),
            e(endpoint.framework or "—"),
            e(_app_name(result, endpoint.app)),
            _link(result, endpoint.file, endpoint.line),
        ])
    headers = [("Kind", False), ("Method", False), ("Path", False), ("Handler", False),
               ("Framework", False), ("Application", False), ("Source", False)]
    return f"""<section data-tab="endpoints" hidden>
<h2>APIs and entrypoints ({len(result.endpoints)})</h2>
<p class="lede">Every HTTP route, GraphQL operation, gRPC method, queue consumer, scheduled job and
CLI command found in the code.</p>
{_search('endpoints-table', 'Filter endpoints…')}
{_table('endpoints-table', headers, rows)}
</section>"""


def _app_name(result: ScanResult, app_id: str) -> str:
    app = result.app_by_id(app_id)
    return app.name if app else "—"


def _dependencies(result: ScanResult) -> str:
    rows = []
    attrs = []
    for dep in result.dependencies:
        status = []
        if not dep.used and dep.direct and dep.scope == "runtime":
            status.append('<span class="tag">unused?</span>')
        if not dep.declared:
            status.append('<span class="tag">undeclared</span>')
        if not dep.version:
            status.append('<span class="tag">unpinned</span>')
        rows.append([
            f"<b>{e(dep.name)}</b>",
            f'<span class="mono">{e(dep.version or "—")}</span>',
            e(dep.ecosystem),
            e(dep.scope),
            "direct" if dep.direct else "transitive",
            f'<span class="mono small">{e(", ".join(dep.declared_in[:2]))}</span>',
            str(len(dep.used_by)),
            "".join(status) or "—",
        ])
        attrs.append(f'data-ecosystem="{e(dep.ecosystem)}"')
    headers = [("Package", False), ("Version", False), ("Ecosystem", False), ("Scope", False),
               ("Kind", False), ("Declared in", False), ("Used by", True), ("Notes", False)]
    missing = [f for f in result.findings if f.identifier == "RG-DEP-MISSING"]
    missing_html = ""
    if missing:
        items = "".join(
            f'<li><b>{e(f.package)}</b> — imported in <span class="mono">{e(f.file)}</span> '
            f"but not declared in any manifest</li>" for f in missing[:40]
        )
        missing_html = f'<h3>Missing dependency declarations ({len(missing)})</h3><ul class="small">{items}</ul>'
    return f"""<section data-tab="dependencies" hidden>
<h2>Dependencies ({len(result.dependencies)})</h2>
<p class="lede">Declared in manifests, resolved through lockfiles where present, and cross-checked
against what the code actually imports.</p>
{missing_html}
{_search('deps-table', 'Filter dependencies…')}
{_table('deps-table', headers, rows, attrs)}
</section>"""


def _security(result: ScanResult) -> str:
    rows = []
    assessed = any(f.ai_assessment for f in result.findings)
    for finding in result.findings:
        references = " ".join(f'<a href="{e(url)}">ref</a>' for url in finding.references[:2] if url)
        assessment = ""
        if finding.ai_assessment:
            label = finding.ai_assessment.replace("_", " ")
            assessment = (f'<span class="tag">{e(label)}</span>'
                          f'<div class="small muted">{e(finding.ai_reasoning)}</div>')
        rows.append([
            f'<span class="badge {e(finding.severity)}">{e(finding.severity)}</span>',
            e(finding.category),
            f"<b>{e(finding.title)}</b><div class='small muted'>{e(finding.remediation)}</div>",
            e(finding.identifier or "—"),
            e(finding.cwe or "—"),
            _link(result, finding.file, finding.line) if finding.file else "—",
            e(finding.confidence),
            references or "—",
        ] + ([assessment or "—"] if assessed else []))
    headers = [("Severity", False), ("Category", False), ("Finding", False), ("Id", False),
               ("CWE", False), ("Location", False), ("Confidence", False), ("Refs", False)]
    if assessed:
        headers.append(("AI assessment", False))
    counts = result.metrics.findings_by_severity
    return f"""<section data-tab="security" hidden>
<h2>Vulnerabilities and risks ({sum(counts.values())})</h2>
<p class="lede">Secrets, insecure patterns, dependency hygiene and — when run with
<code>--online</code> — published advisories from OSV.dev. Every row points at a file and line.</p>
<div class="panel">{charts.severity_bar(counts, title="", width=560)}</div>
{_search('findings-table', 'Filter findings…')}
{_table('findings-table', headers, rows)}
</section>"""


def _integrations(result: ScanResult) -> str:
    rows = []
    for system in result.external_systems:
        evidence = "<br>".join(
            _link(result, ev.file, ev.line) for ev in system.evidence[:3] if ev.file
        ) or "—"
        rows.append([
            f"<b>{e(system.name)}</b>",
            f'<span class="tag">{e(system.kind)}</span>',
            e(system.technology or "—"),
            e(system.direction),
            e(", ".join(_app_name(result, a) for a in system.apps) or "—"),
            str(len(system.evidence)),
            evidence,
        ])
    headers = [("System", False), ("Kind", False), ("Technology", False), ("Direction", False),
               ("Used by", False), ("Refs", True), ("Evidence", False)]
    return f"""<section data-tab="integrations" hidden>
<h2>External systems ({len(result.external_systems)})</h2>
<p class="lede">Databases, queues, storage, identity providers and third-party APIs this code talks
to, each with the file and line that proves it.</p>
{_search('systems-table', 'Filter systems…')}
{_table('systems-table', headers, rows)}
</section>"""


def _infrastructure(result: ScanResult) -> str:
    infra = result.infrastructure or {}
    blocks = []

    containers = infra.get("containers") or []
    if containers:
        rows = [[f"<b>{e(c.get('name'))}</b>", e(c.get("image") or f"build {c.get('build','')}"),
                 e(", ".join(c.get("ports", []))), e(", ".join(c.get("depends_on", []))),
                 f'<span class="mono small">{e(c.get("file"))}</span>'] for c in containers]
        blocks.append("<h3>Compose services</h3>" + _table(
            "containers-table",
            [("Service", False), ("Image / build", False), ("Ports", False), ("Depends on", False),
             ("File", False)], rows))

    dockerfiles = infra.get("dockerfiles") or []
    if dockerfiles:
        rows = [[f'<span class="mono">{e(d.get("file"))}</span>',
                 e(", ".join(d.get("base_images", []))), e(", ".join(str(p) for p in d.get("ports", []))),
                 e(d.get("user")), "yes" if d.get("multistage") else "no",
                 f'<span class="mono small">{e(d.get("entrypoint"))}</span>'] for d in dockerfiles]
        blocks.append("<h3>Dockerfiles</h3>" + _table(
            "dockerfiles-table",
            [("File", False), ("Base images", False), ("Ports", False), ("User", False),
             ("Multi-stage", False), ("Entrypoint", False)], rows))

    workloads = infra.get("kubernetes") or []
    if workloads:
        rows = [[e(k.get("kind")), f"<b>{e(k.get('name'))}</b>", e(k.get("namespace") or "default"),
                 e(", ".join(k.get("images", []))), e(", ".join(k.get("ports", []))),
                 f'<span class="mono small">{e(k.get("file"))}</span>'] for k in workloads]
        blocks.append("<h3>Kubernetes objects</h3>" + _table(
            "k8s-table", [("Kind", False), ("Name", False), ("Namespace", False), ("Images", False),
                          ("Ports", False), ("File", False)], rows))

    terraform = infra.get("terraform") or []
    if terraform:
        rows = [[e(t.get("block")), f"<b>{e(t.get('type'))}</b>", e(t.get("name")),
                 e(t.get("provider")), f'<span class="mono small">{e(t.get("file"))}:{t.get("line")}</span>']
                for t in terraform]
        blocks.append("<h3>Terraform resources</h3>" + _table(
            "tf-table", [("Block", False), ("Type", False), ("Name", False), ("Provider", False),
                         ("File", False)], rows))

    ci = infra.get("ci") or []
    if ci:
        rows = []
        for pipeline in ci:
            jobs = ", ".join(str(j.get("name")) for j in (pipeline.get("jobs") or [])[:8])
            rows.append([e(pipeline.get("system")), e(pipeline.get("name")),
                         e(", ".join(pipeline.get("triggers", []))), e(jobs),
                         f'<span class="mono small">{e(pipeline.get("file"))}</span>'])
        blocks.append("<h3>CI / CD pipelines</h3>" + _table(
            "ci-table", [("System", False), ("Pipeline", False), ("Triggers", False), ("Jobs", False),
                         ("File", False)], rows))

    env_vars = infra.get("env_vars") or {}
    if env_vars:
        rows = [[f'<span class="mono">{e(name)}</span>', e(info.get("kind", "")),
                 str(len(info.get("files", []))),
                 f'<span class="mono small">{e(", ".join(info.get("files", [])[:2]))}</span>']
                for name, info in list(env_vars.items())[:400]]
        blocks.append(f"<h3>Configuration inputs ({len(env_vars)} environment variables)</h3>"
                      + _search("env-table", "Filter variables…")
                      + _table("env-table", [("Variable", False), ("Kind", False), ("Uses", True),
                                             ("Files", False)], rows))

    if not blocks:
        blocks.append('<p class="muted">No containers, orchestration, IaC or CI configuration found.</p>')
    return f'<section data-tab="infrastructure" hidden><h2>Infrastructure</h2>{"".join(blocks)}</section>'


def _files(result: ScanResult) -> str:
    largest = sorted(result.files, key=lambda f: -f.loc)[:400]
    rows = [[_link(result, f.path), e(f.language), e(f.kind), str(f.loc), str(f.sloc),
             e(_app_name(result, f.app)), str(f.symbols)] for f in largest]
    headers = [("File", False), ("Language", False), ("Kind", False), ("LOC", True), ("SLOC", True),
               ("Application", False), ("Symbols", True)]
    hotspots = result.git.hotspots or []
    hotspot_html = ""
    if hotspots:
        hs_rows = [[_link(result, h.get("file", "")), str(h.get("changes", 0))] for h in hotspots]
        hotspot_html = ("<h3>Change hotspots (most edited files)</h3>"
                        + _table("hotspots-table", [("File", False), ("Commits touching it", True)], hs_rows))
    cycles = ""
    if result.cycles:
        names = {c.id: c.name for c in result.components}
        items = "".join(f"<li>{e(' → '.join(names.get(n, n) for n in cycle))}</li>"
                        for cycle in result.cycles[:20])
        cycles = f"<h3>Dependency cycles ({len(result.cycles)})</h3><ul class='small'>{items}</ul>"
    return f"""<section data-tab="files" hidden>
<h2>Files</h2>
<p class="lede">The 400 largest files by line count, plus git change hotspots and any dependency
cycles found between components.</p>
{cycles}
{hotspot_html}
<h3>Largest files</h3>
{_search('files-table', 'Filter files…')}
{_table('files-table', headers, rows)}
</section>"""


def _ai(ai_report: str, output_files: Sequence[str], agent_panel: str,
        result: ScanResult) -> str:
    files = "".join(f'<li><a href="{e(f)}">{e(f)}</a></li>' for f in output_files)
    return f"""<section data-tab="ai" hidden>
<h2>AI: read it, or let one help</h2>
<p class="lede">Everything in this report was produced without a model. This tab is where AI is
allowed in — on your terms.</p>
{agent_panel}
{_ai_contributions(result)}
<h2>Agent-readable report</h2>
<p class="lede">The same analysis as a single dense Markdown document: paste it into any AI tool to
give it a full picture of this repository without letting it read the code.</p>
<div class="panel"><h3>Files in this output folder</h3><ul class="small">{files}</ul></div>
<pre>{e(ai_report)}</pre>
</section>"""


def _ai_contributions(result: ScanResult) -> str:
    ai = result.ai
    if not ai.present:
        return ""
    provenance = (f"{ai.provenance.tool}"
                  + (f" · {ai.provenance.model}" if ai.provenance.model else "")
                  + (f" · {ai.provenance.generated_at}" if ai.provenance.generated_at else ""))
    insights = "".join(
        f'<div class="finding {e(i.severity)}"><b>{e(i.title)}</b> '
        f'<span class="tag">{e(i.kind)}</span> '
        f'<span class="tag">confidence {e(i.confidence)}</span>'
        f'<div class="small">{e(i.detail)}</div>'
        f'<div class="where">{" · ".join(e(x) for x in i.evidence)}</div></div>'
        for i in ai.insights
    ) or '<p class="muted small">No insights were returned.</p>'
    rejected = ""
    if ai.rejected:
        items = "".join(f"<li>{e(r)}</li>" for r in ai.rejected[:20])
        rejected = (f'<details><summary>{len(ai.rejected)} contribution(s) rejected on merge'
                    f'</summary><ul class="small">{items}</ul></details>')
    unanswered = ""
    if ai.unanswered:
        items = "".join(f"<li>{e(u)}</li>" for u in ai.unanswered[:20])
        unanswered = (f'<details><summary>{len(ai.unanswered)} question(s) the agent could not '
                      f'answer</summary><ul class="small">{items}</ul></details>')
    return f"""<h2>Model contributions <span class="tag">AI generated</span></h2>
<p class="lede">Written by an agent, validated against the scan, and kept separate from it.
{e(ai.answered_questions)} contribution(s) merged from {e(provenance)}.</p>
{insights}
{rejected}
{unanswered}"""
