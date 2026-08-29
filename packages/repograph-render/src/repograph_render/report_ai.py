"""The agent-readable report.

Same facts as the human report, arranged for a model with a context window: a
stable section order, explicit counts, no prose padding, every claim carrying the
file and line it came from, and an explicit statement of what the scanner could
*not* determine so a reader does not fill the gap with guesses.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from repograph_core.model import ScanResult

SECTION = "\n" + "=" * 78 + "\n"


def _bullets(items: Iterable[str], limit: int = 60, indent: str = "- ") -> str:
    items = list(items)
    out = [f"{indent}{item}" for item in items[:limit]]
    if len(items) > limit:
        out.append(f"{indent}… {len(items) - limit} more (see repograph.json)")
    return "\n".join(out) if out else f"{indent}(none)"


def render(result: ScanResult, mermaid: Dict[str, str], *, include_mermaid: bool = True) -> str:
    meta = result.meta
    metrics = result.metrics
    summary = result.summary
    out: List[str] = []
    add = out.append
    severity_line = ", ".join(f"{k}={v}" for k, v in metrics.findings_by_severity.items()) or "none"
    advisory_note = ("Advisory data came from OSV.dev at scan time." if meta.online else
                     "No advisory lookup was performed (offline mode); dependency CVEs are NOT "
                     "covered by this run.")

    add(f"""# REPOSITORY ANALYSIS: {meta.repo_name}
# Produced by repograph {meta.version} (deterministic static analysis, no AI involved)
# Generated: {meta.generated_at}
# Source root: {meta.root}
# Advisory lookup: {"OSV.dev (online)" if meta.online else "skipped (offline mode)"}

READER NOTES
- Every fact below was derived from files in this repository; locations are given as path:line.
- Counts are exact for what was scanned; the scanned set excludes vendored directories,
  build output and anything ignored by .gitignore.
- Confidence markers: findings carry high/medium/low. Import resolution is exact for
  Python/JS/TS/Go internal modules and heuristic elsewhere.
- Where a fact could not be determined, this document says so explicitly rather than guessing.""")

    add(SECTION + "1. SUMMARY")
    add(f"""purpose: {summary.get('purpose', 'unknown')}
shape: {summary.get('shape', 'unknown')}
architecture_styles: {', '.join(summary.get('architecture_styles', [])) or 'unclassified'}
primary_languages: {', '.join(summary.get('primary_languages', [])) or 'unknown'}
applications: {metrics.apps}
components: {metrics.components}
files_scanned: {metrics.scanned_files} (of {metrics.files} seen)
lines_of_code: {metrics.loc}
endpoints: {metrics.endpoints}
external_systems: {metrics.external_systems}
dependencies: {metrics.dependencies}
findings: {sum(metrics.findings_by_severity.values())} ({severity_line})
risk_level: {summary.get('risk_level')} (score {summary.get('risk_score')})
test_file_ratio: {metrics.test_ratio}
dependency_cycles: {metrics.cycles}
has_ci: {summary.get('has_ci')} | has_containers: {summary.get('has_containers')} | has_iac: {summary.get('has_iac')}
scan_duration_seconds: {metrics.duration_seconds}""")

    if result.git.is_repo:
        add(f"""git_remote: {result.git.remote or 'none'}
git_branch: {result.git.branch or 'unknown'}
git_commits: {result.git.commits} by {result.git.contributors} contributor(s)
git_active_period: {result.git.first_commit} .. {result.git.last_commit}""")

    add(SECTION + "2. APPLICATIONS (deployable or publishable units)")
    for app in result.apps:
        components = [c for c in result.components if c.app == app.id]
        endpoints = [e for e in result.endpoints if e.app == app.id]
        systems = [s for s in result.external_systems if app.id in s.apps]
        depends = [result.app_by_id(e.target) for e in result.edges
                   if e.kind == "depends" and e.source == app.id]
        dependents = [result.app_by_id(e.source) for e in result.edges
                      if e.kind == "depends" and e.target == app.id]
        add(f"""
## {app.name} [id={app.id}]
root: {app.root or '.'}
kind: {app.kind}
architecture_style: {app.architecture_style}
languages: {', '.join(app.languages) or 'unknown'}
frameworks: {', '.join(app.frameworks) or 'none detected'}
size: {app.files} files, {app.loc} lines, {len(components)} components
manifests: {', '.join(app.manifests) or 'none'}
entrypoints: {', '.join(app.entrypoints) or 'none declared'}
description (from README or manifest): {app.description or 'not documented'}
inferred_purpose (derived from code, independent of any README): {app.purpose or 'n/a'}
endpoints: {len(endpoints)}
depends_on_apps: {', '.join(a.name for a in depends if a) or 'none'}
depended_on_by: {', '.join(a.name for a in dependents if a) or 'none'}
external_systems: {', '.join(s.name for s in systems) or 'none'}
components:
{_bullets(f'{c.name} ({c.files} files, {c.loc} LOC, {", ".join(c.languages[:2]) or "mixed"}) at {c.path}'
          for c in sorted(components, key=lambda x: -x.files))}""")

    add(SECTION + "3. INTERNAL DEPENDENCY STRUCTURE")
    names = {c.id: f"{c.name}" for c in result.components}
    app_names = {a.id: a.name for a in result.apps}
    imports = [e for e in result.edges if e.kind == "imports"]
    add(f"component_dependency_edges: {len(imports)}")
    add(_bullets(f"{names.get(e.source, e.source)} -> {names.get(e.target, e.target)} "
                 f"({e.weight} import{'s' if e.weight > 1 else ''})"
                 for e in sorted(imports, key=lambda x: -x.weight)))
    app_edges = [e for e in result.edges if e.kind == "depends"]
    add(f"\napplication_dependency_edges: {len(app_edges)}")
    add(_bullets(f"{app_names.get(e.source, e.source)} -> {app_names.get(e.target, e.target)} "
                 f"({e.weight})" for e in app_edges))
    add(f"\ndependency_cycles: {len(result.cycles)}")
    add(_bullets((" -> ".join(names.get(n, n) for n in cycle) for cycle in result.cycles), limit=20))
    if result.layers:
        by_layer: Dict[int, List[str]] = defaultdict(list)
        for cid, layer in result.layers.items():
            by_layer[layer].append(names.get(cid, cid))
        add("\nlayering (layer 0 depends on nothing else in the repo):")
        add("\n".join(f"- layer {layer}: {', '.join(sorted(members)[:25])}"
                      for layer, members in sorted(by_layer.items())))

    add(SECTION + "4. API SURFACE / ENTRYPOINTS")
    by_kind: Dict[str, List] = defaultdict(list)
    for endpoint in result.endpoints:
        by_kind[endpoint.kind].append(endpoint)
    if not by_kind:
        add("(no endpoints detected)")
    for kind, members in sorted(by_kind.items()):
        add(f"\n{kind} ({len(members)}):")
        add(_bullets(f"{m.method} {m.path} -> {m.handler or 'unnamed handler'} "
                     f"[{m.framework or 'unknown framework'}] at {m.file}:{m.line}"
                     for m in sorted(members, key=lambda x: x.path)))

    add(SECTION + "5. EXTERNAL SYSTEMS AND DATA STORES")
    if not result.external_systems:
        add("(none detected)")
    for system in result.external_systems:
        evidence = "; ".join(f"{ev.file}:{ev.line}" for ev in system.evidence[:4] if ev.file)
        add(f"- {system.name} | kind={system.kind} | tech={system.technology} | "
            f"direction={system.direction} | "
            f"used_by={', '.join(app_names.get(a, a) for a in system.apps) or 'unknown'} | "
            f"evidence={evidence or 'configuration only'}")

    add(SECTION + "6. DEPENDENCIES")
    by_ecosystem: Dict[str, List] = defaultdict(list)
    for dep in result.dependencies:
        by_ecosystem[dep.ecosystem].append(dep)
    for ecosystem, deps in sorted(by_ecosystem.items()):
        direct = [d for d in deps if d.direct]
        add(f"\n{ecosystem}: {len(deps)} total, {len(direct)} direct")
        add(_bullets((f"{d.name}{'@' + d.version if d.version else ''} "
                      f"[{d.scope}{', unused' if not d.used and d.direct else ''}]"
                      for d in sorted(direct, key=lambda x: x.name)), limit=80))
    missing = [f for f in result.findings if f.identifier == "RG-DEP-MISSING"]
    if missing:
        add(f"\nimported_but_not_declared ({len(missing)}):")
        add(_bullets(f"{f.package} (first seen {f.file})" for f in missing))

    add(SECTION + "7. SECURITY FINDINGS")
    add(f"total: {sum(metrics.findings_by_severity.values())}")
    for severity in ("critical", "high", "medium", "low", "info"):
        items = [f for f in result.findings if f.severity == severity]
        if not items:
            continue
        add(f"\n{severity.upper()} ({len(items)}):")
        for finding in items[:60]:
            location = f"{finding.file}:{finding.line}" if finding.file else "repository-wide"
            add(f"- [{finding.identifier or 'n/a'}] {finding.title}\n"
                f"  where: {location}\n"
                f"  category: {finding.category} | cwe: {finding.cwe or 'n/a'} | "
                f"confidence: {finding.confidence}"
                + (f" | package: {finding.package}@{finding.version}"
                   f"{' -> fixed in ' + finding.fixed_version if finding.fixed_version else ''}"
                   if finding.package else "")
                + (f"\n  code: {finding.snippet}" if finding.snippet else "")
                + f"\n  fix: {finding.remediation}")
        if len(items) > 60:
            add(f"… {len(items) - 60} more {severity} findings in findings.csv / repograph.json")

    add(SECTION + "8. PROCESS FLOWS (reconstructed from entrypoints)")
    if not result.flows:
        add("(no flows reconstructed)")
    for flow in result.flows:
        add(f"\n## {flow.name} [app={app_names.get(flow.app, flow.app)}]")
        add(f"description: {flow.description}")
        add(f"lanes: {', '.join(flow.lanes)}")
        node_labels = {n.id: f"{n.label} [{n.kind}]" for n in flow.nodes}
        add("steps:")
        add(_bullets((f"{n.lane or 'process'}: {n.label} ({n.kind})"
                      + (f" — {n.file}" if n.file else "") for n in flow.nodes), limit=40))
        add("transitions:")
        add(_bullets((f"{node_labels.get(e.source, e.source)} --{e.label or e.kind}--> "
                      f"{node_labels.get(e.target, e.target)}" for e in flow.edges), limit=40))

    add(SECTION + "9. INFRASTRUCTURE AND CONFIGURATION")
    infra = result.infrastructure or {}
    add(f"dockerfiles: {len(infra.get('dockerfiles') or [])}")
    add(_bullets(f"{d.get('file')} — base={', '.join(d.get('base_images', []))}, "
                 f"user={d.get('user')}, ports={d.get('ports')}, multistage={d.get('multistage')}"
                 for d in (infra.get("dockerfiles") or [])))
    add(f"\ncompose_services: {len(infra.get('containers') or [])}")
    add(_bullets(f"{c.get('name')} — image={c.get('image') or 'built from ' + str(c.get('build'))}, "
                 f"ports={c.get('ports')}, depends_on={c.get('depends_on')}"
                 for c in (infra.get("containers") or [])))
    add(f"\nkubernetes_objects: {len(infra.get('kubernetes') or [])}")
    add(_bullets(f"{k.get('kind')} {k.get('name')} — images={k.get('images')}"
                 for k in (infra.get("kubernetes") or [])))
    add(f"\nterraform_resources: {len(infra.get('terraform') or [])}")
    add(_bullets(f"{t.get('block')} {t.get('type')}.{t.get('name')} ({t.get('file')})"
                 for t in (infra.get("terraform") or [])))
    add(f"\nci_pipelines: {len(infra.get('ci') or [])}")
    add(_bullets(f"{c.get('system')}: {c.get('name')} triggers={c.get('triggers')} "
                 f"jobs={[j.get('name') for j in (c.get('jobs') or [])][:8]}"
                 for c in (infra.get("ci") or [])))
    env_vars = infra.get("env_vars") or {}
    add(f"\nenvironment_variables_referenced: {len(env_vars)}")
    add(_bullets(f"{name} ({info.get('kind')}) used in {len(info.get('files', []))} file(s)"
                 for name, info in env_vars.items()))

    add(SECTION + "10. CODE MAP (where to look)")
    add("largest components:")
    add(_bullets(f"{c['name']} — {c['files']} files, {c['loc']} LOC, rank {c['rank']:.4f}, "
                 f"fan-in {c['fan_in']}, fan-out {c['fan_out']}"
                 for c in summary.get("top_components", [])))
    add("\nchange hotspots (most edited files):")
    add(_bullets(f"{h.get('file')} ({h.get('changes')} commits)" for h in (result.git.hotspots or [])))
    add("\nlargest files:")
    add(_bullets(f"{f.path} ({f.loc} LOC, {f.language})"
                 for f in sorted(result.files, key=lambda x: -x.loc)[:25]))

    if include_mermaid:
        add(SECTION + "11. DIAGRAMS (Mermaid source — render or read directly)")
        for key in ("c4-context", "c4-container", "application-dependencies", "dependency-graph"):
            if key in mermaid:
                add(f"\n### {key}\n```mermaid\n{mermaid[key]}\n```")
        for key, source in mermaid.items():
            if key.startswith("flow-"):
                add(f"\n### {key}\n```mermaid\n{source}\n```")

    add(SECTION + "12. LIMITS OF THIS ANALYSIS")
    add(f"""- Import resolution: {summary.get('unresolved_imports', 0)} import statements could not be
  resolved to a file or a package; those relationships are missing from the graph.
- Dynamic behaviour (reflection, DI containers, runtime plugin loading, string-built SQL or URLs)
  is not traced; flows are reconstructed from static imports and may be incomplete.
- External system detection is signature based: a match proves a reference exists in the code,
  not that the system is used in production. Every claim carries its evidence location.
- {advisory_note}
- Vendored directories were skipped: {', '.join(summary.get('vendored_directories', [])) or 'none found'}.
- Scanner warnings: {'; '.join(meta.warnings) or 'none'}""")

    add(SECTION + "END OF REPORT")
    return "\n".join(out) + "\n"
