"""The scan orchestrator: one pass over a repository, one ScanResult out."""

from __future__ import annotations

import os
import platform
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import apps as apps_mod
from . import archimate as archimate_mod
from . import c4 as c4_mod
from . import gitinfo, graph, narrative
from . import profile as profile_mod
from .evidence_quality import optional_import_names
from .flows import FlowBuilder
from .infra import InfraScanner
from .integrations import IntegrationScanner, classify_env_var
from .languages import analyze
from .manifests import Manifest, is_lockfile, is_manifest, parse_lockfile, parse_manifest
from .model import (
    App,
    Component,
    Dependency,
    Edge,
    Endpoint,
    Evidence,
    ExternalSystem,
    FileInfo,
    Finding,
    Metrics,
    ScanMeta,
    ScanResult,
    Symbol,
)
from .resolve import Resolver, normalise_package
from .security.advisories import OsvClient, advisory_findings, hygiene_findings, usage_findings
from .security.patterns import scan_patterns
from .security.secrets import scan_secrets
from .util import count_lines, dedupe, title_case, truncate
from .walker import ScanFile, Walker, load_text

VERSION = "0.1.0"

ProgressFn = Callable[[str, int, int], None]


@dataclass
class ScanOptions:
    root: str
    online: bool = False
    include_tests: bool = True
    max_file_size: int = 2_000_000
    extra_ignores: Sequence[str] = ()
    use_gitignore: bool = True
    git_history: bool = True
    max_symbols: int = 20000
    max_files_recorded: int = 20000
    profile: str = "default"
    everything: bool = False
    progress: Optional[ProgressFn] = None

    def notify(self, stage: str, done: int = 0, total: int = 0) -> None:
        if self.progress:
            self.progress(stage, done, total)


def scan(options: ScanOptions) -> ScanResult:
    started = time.time()
    root = os.path.abspath(options.root)
    result = ScanResult()
    repo_name = os.path.basename(root.rstrip(os.sep)) or "repository"

    result.meta = ScanMeta(
        version=VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        root=root,
        repo_name=repo_name,
        command=" ".join(sys.argv),
        host_os=f"{platform.system()} {platform.release()}",
        python=platform.python_version(),
        online=options.online,
        profile=options.profile,
    )

    # ------------------------------------------------------------- 1. walk
    options.notify("Scanning files", 0, 0)
    walker = Walker(root, extra_ignores=options.extra_ignores, max_file_size=options.max_file_size,
                    use_gitignore=options.use_gitignore)
    files = walker.walk()
    if not options.include_tests:
        files = [f for f in files if f.kind != "test"]
    total = len(files)
    if total == 0:
        result.meta.warnings.append("No files found to analyse — is the path correct?")

    # ------------------------------- 2. read, analyse, collect in one pass
    manifests: List[Manifest] = []
    lock_deps: List[Dependency] = []
    optional_imports: set = set()
    lockfile_paths: List[str] = []
    tsconfigs: Dict[str, str] = {}
    readmes: Dict[str, str] = {}
    dockerfiles: List[str] = []
    analyses: Dict[str, object] = {}
    frameworks_by_file: Dict[str, List[str]] = {}
    endpoint_files: Dict[str, List[str]] = {}
    entry_texts: Dict[str, str] = {}
    file_infos: Dict[str, FileInfo] = {}
    symbols: List[Symbol] = []
    endpoints: List[Endpoint] = []
    integrations = IntegrationScanner()
    infra = InfraScanner()
    findings: List[Finding] = []
    language_loc: Dict[str, int] = defaultdict(int)
    language_files: Dict[str, int] = defaultdict(int)

    for index, sf in enumerate(files):
        if index % 200 == 0:
            options.notify("Reading and analysing", index, total)
        text = load_text(sf)
        loc, sloc = count_lines(text, sf.comment_prefixes) if text else (0, 0)
        info = FileInfo(path=sf.rel, language=sf.language, kind=sf.kind, loc=loc, sloc=sloc,
                        size=sf.size)
        file_infos[sf.rel] = info
        language_loc[sf.language] += loc
        language_files[sf.language] += 1

        name = sf.name.lower()
        if is_manifest(sf.rel) and text:
            manifest = parse_manifest(sf.rel, text)
            if manifest is not None:
                manifests.append(manifest)
        if is_lockfile(sf.rel) and text:
            lockfile_paths.append(sf.rel)
            lock_deps.extend(parse_lockfile(sf.rel, text))
        if name in ("tsconfig.json", "jsconfig.json") and text:
            tsconfigs[sf.rel] = text
        if name.startswith("readme") and text:
            readmes[sf.rel] = text
        if name.startswith("dockerfile") or name.endswith(".dockerfile"):
            dockerfiles.append(sf.rel)

        if sf.kind in ("infra", "config", "build") or name.startswith("dockerfile"):
            infra.scan(sf.rel, text)

        if text and sf.is_code or sf.language in ("SQL", "Protobuf", "GraphQL"):
            analysis = analyze(sf.language, sf.rel, text)
            analyses[sf.rel] = analysis
            info.imports = [i.module for i in analysis.imports][:80]
            info.symbols = len(analysis.symbols)
            if analysis.frameworks:
                frameworks_by_file[sf.rel] = dedupe(analysis.frameworks)
            if len(symbols) < options.max_symbols:
                symbols.extend(analysis.symbols)
            if analysis.endpoints:
                endpoint_files[sf.rel] = [e.path for e in analysis.endpoints]
                endpoints.extend(analysis.endpoints)
                if len(entry_texts) < 400:
                    entry_texts[sf.rel] = text

        if text:
            optional_imports.update(optional_import_names(text))
            integrations.scan_file(sf.rel, text, "", sf.kind)
            findings.extend(scan_secrets(sf.rel, text))
            findings.extend(scan_patterns(sf.rel, text, sf.language))
        sf.text = None  # release memory

    # --------------------------------------------------- 3. apps/components
    options.notify("Grouping applications", 0, 0)
    app_list, components, app_of_file = apps_mod.build_apps(
        root, files, manifests, repo_name, readmes, dockerfiles, frameworks_by_file, endpoint_files
    )
    component_of_file = _map_files_to_components(files, components, app_of_file)

    for rel, info in file_infos.items():
        info.app = app_of_file.get(rel, "")
        info.component = component_of_file.get(rel, "")
    for symbol in symbols:
        symbol.app = app_of_file.get(symbol.file, "")
        symbol.component = component_of_file.get(symbol.file, "")
    for endpoint in endpoints:
        endpoint.app = app_of_file.get(endpoint.file, "")
        endpoint.component = component_of_file.get(endpoint.file, "")
    for finding in findings:
        finding.app = app_of_file.get(finding.file, "")

    for component in components:
        component.loc = sum(file_infos[rel].loc for rel, cid in component_of_file.items()
                            if cid == component.id and rel in file_infos)
    for app in app_list:
        app.loc = sum(info.loc for rel, info in file_infos.items() if info.app == app.id)

    # ------------------------------------------------- 4. resolve imports
    options.notify("Resolving imports", 0, 0)
    resolver = Resolver(files, manifests, tsconfigs)
    file_edges: List[Edge] = []
    external_usage: Dict[Tuple[str, str], Dict[str, object]] = {}
    unresolved_count = 0

    for sf in files:
        analysis = analyses.get(sf.rel)
        if analysis is None:
            continue
        for ref in analysis.imports:  # type: ignore[attr-defined]
            resolved = resolver.resolve(sf, ref.module, ref.line, ref.relative)
            if resolved.internal_file:
                file_edges.append(Edge(
                    source=sf.rel, target=resolved.internal_file, kind="imports",
                    evidence=[Evidence(file=sf.rel, line=ref.line, snippet=truncate(ref.raw or ref.module, 120))],
                ))
            elif resolved.external_package:
                key = (normalise_package(resolved.external_package, resolved.ecosystem), resolved.ecosystem)
                entry = external_usage.setdefault(key, {"files": [], "apps": set()})
                if len(entry["files"]) < 25:  # type: ignore[index]
                    entry["files"].append(sf.rel)  # type: ignore[union-attr]
                entry["apps"].add(app_of_file.get(sf.rel, ""))  # type: ignore[union-attr]
            elif resolved.unresolved:
                unresolved_count += 1

    file_edges = graph.dedupe_edges(file_edges)

    # ---------------------------------------------------- 5. dependencies
    options.notify("Reconciling dependencies", 0, 0)
    dependencies, undeclared = _reconcile_dependencies(manifests, lock_deps, external_usage, app_of_file)
    # An import wrapped in try/except ImportError is optional by construction:
    # the author already wrote the fallback. Asking them to declare it would
    # make the declaration a lie on the interpreters the fallback exists for.
    for name in list(undeclared):
        if name in optional_imports:
            del undeclared[name]

    # -------------------------------------------- 6. external integrations
    options.notify("Detecting external systems", 0, 0)
    for system in integrations.systems.values():
        system.apps = dedupe([app_of_file.get(ev.file, "") for ev in system.evidence if ev.file])
        system.apps = [a for a in system.apps if a]
    external_systems = integrations.finish()
    for system in infra.systems.values():
        existing = next((s for s in external_systems if s.name == system.name), None)
        if existing is None:
            external_systems.append(system)
        else:
            existing.evidence.extend(system.evidence[:3])
    for system in external_systems:
        if not system.apps:
            system.apps = dedupe([app_of_file.get(ev.file, "") for ev in system.evidence if ev.file])
            system.apps = [a for a in system.apps if a]

    _attribute_compose_systems(infra, external_systems, app_list)

    systems_by_file: Dict[str, List[str]] = defaultdict(list)
    for system in external_systems:
        for ev in system.evidence:
            if ev.file and system.id not in systems_by_file[ev.file]:
                systems_by_file[ev.file].append(system.id)

    # ----------------------------------------------------------- 7. graphs
    options.notify("Building graphs", 0, 0)
    component_edges = graph.aggregate(file_edges, component_of_file, kind="imports")
    app_edges = graph.aggregate(file_edges, app_of_file, kind="depends")
    system_edges: List[Edge] = []
    for system in external_systems:
        for app_id in system.apps:
            system_edges.append(Edge(
                source=app_id, target=system.id,
                kind={"database": "db", "cache": "cache", "queue": "queue", "storage": "storage"}.get(
                    system.kind, "http"),
                label=system.technology or system.kind,
                evidence=system.evidence[:2],
            ))
    infra_edges = _container_edges(infra, app_list)

    component_ids = [c.id for c in components]
    cycles = graph.find_cycles(component_edges)
    layers = graph.layer_nodes(component_ids, component_edges)
    ranks = graph.rank_nodes(component_ids, component_edges)
    fan_in, fan_out = graph.fan(component_edges)

    # -------------------------------------------------------- 8. security
    options.notify("Assessing dependencies", 0, 0)
    findings.extend(hygiene_findings(dependencies, lockfile_paths, {d.ecosystem for d in dependencies}))
    findings.extend(usage_findings(dependencies, undeclared))
    osv_errors: List[str] = []
    if options.online:
        options.notify("Querying OSV advisories", 0, 0)
        client = OsvClient()
        vulnerable = [d for d in dependencies if d.version]
        results = client.query(vulnerable)
        findings.extend(advisory_findings(vulnerable, results))
        osv_errors = client.errors
        if osv_errors:
            result.meta.warnings.append(
                f"OSV advisory lookup failed for {len(osv_errors)} request(s) — dependency CVEs are "
                f"incomplete or missing. First error: {osv_errors[0][:200]} "
                f"(repograph uses the standard HTTPS_PROXY/SSL_CERT_FILE environment variables)."
            )
    else:
        result.meta.warnings.append(
            "Advisory lookup skipped (offline mode). Re-run with --online to check dependencies against OSV.dev."
        )

    findings = _dedupe_findings(findings)

    # ------------------------------------------------- 8b. inferred purpose
    app_names = {a.id: a.name for a in app_list}
    for app in app_list:
        dependents = [app_names.get(e.source, "") for e in app_edges + infra_edges
                      if e.target == app.id]
        depends_on = [app_names.get(e.target, "") for e in app_edges + infra_edges
                      if e.source == app.id]
        app.purpose = apps_mod.infer_purpose(
            app,
            [e for e in endpoints if e.app == app.id],
            [s for s in symbols if s.app == app.id],
            [s for s in external_systems if app.id in s.apps],
            [name for name in dependents if name],
            [name for name in depends_on if name],
        )
        if not app.description:
            app.description = app.purpose

    # ----------------------------------------------------------- 9. models
    options.notify("Deriving flows and models", 0, 0)
    flow_builder = FlowBuilder(app_list, endpoints, file_edges, app_of_file, systems_by_file,
                               external_systems, lambda rel: entry_texts.get(rel, ""))
    flows = flow_builder.build()

    c4_model = c4_mod.build(repo_name, app_list, components, app_edges, component_edges,
                            external_systems, endpoints, system_edges)
    archimate_model = archimate_mod.build(repo_name, app_list, components, app_edges, component_edges,
                                          external_systems, endpoints, system_edges, flows,
                                          infra.to_dict())

    # ----------------------------------------------------------- 10. wrap up
    if options.git_history:
        options.notify("Reading git history", 0, 0)
        result.git = gitinfo.collect(root)

    result.apps = app_list
    result.components = components
    result.files = [file_infos[f.rel] for f in files[: options.max_files_recorded] if f.rel in file_infos]
    result.symbols = symbols[: options.max_symbols]
    result.edges = list(component_edges) + list(app_edges) + system_edges + infra_edges
    result.dependencies = dependencies
    result.endpoints = endpoints
    result.external_systems = external_systems
    result.findings = findings
    result.flows = flows
    result.c4 = c4_model
    result.archimate = archimate_model
    result.cycles = cycles
    result.layers = layers
    result.infrastructure = infra.to_dict()
    result.infrastructure["env_vars"] = {
        name: {"files": files_using, "kind": classify_env_var(name)}
        for name, files_using in sorted(integrations.env_vars.items())
    }
    result.infrastructure["file_graph"] = {
        "edges": [{"source": e.source, "target": e.target, "weight": e.weight} for e in file_edges[:20000]],
    }

    severity_counts: Dict[str, int] = defaultdict(int)
    for finding in findings:
        severity_counts[finding.severity] += 1

    result.metrics = Metrics(
        files=walker.stats.total_seen,
        scanned_files=len(files),
        loc=sum(i.loc for i in file_infos.values()),
        sloc=sum(i.sloc for i in file_infos.values()),
        languages=dict(sorted(language_loc.items(), key=lambda kv: -kv[1])),
        language_files=dict(sorted(language_files.items(), key=lambda kv: -kv[1])),
        apps=len(app_list),
        components=len(components),
        endpoints=len(endpoints),
        dependencies=len(dependencies),
        external_systems=len(external_systems),
        findings_by_severity=dict(severity_counts),
        test_files=sum(1 for f in files if f.kind == "test"),
        doc_files=sum(1 for f in files if f.kind == "docs"),
        max_component_fan_in=max(fan_in.values(), default=0),
        max_component_fan_out=max(fan_out.values(), default=0),
        cycles=len(cycles),
        duration_seconds=round(time.time() - started, 2),
    )
    source_files = sum(1 for f in files if f.kind == "source") or 1
    result.metrics.test_ratio = round(result.metrics.test_files / source_files, 3)

    result.summary = _summarise(result, ranks, fan_in, fan_out, readmes, unresolved_count,
                                walker.stats.vendor_dirs)
    result.profile = profile_mod.build_profile(result, force_all=options.everything).to_dict()
    result.business = narrative.build(result).to_dict()
    options.notify("Done", total, total)
    return result


# ------------------------------------------------------------------ helpers

def _map_files_to_components(files: Sequence[ScanFile], components: Sequence[Component],
                             app_of_file: Dict[str, str]) -> Dict[str, str]:
    by_app: Dict[str, List[Component]] = defaultdict(list)
    for component in components:
        by_app[component.app].append(component)
    for group in by_app.values():
        group.sort(key=lambda c: -len(c.path))

    mapping: Dict[str, str] = {}
    for sf in files:
        app_id = app_of_file.get(sf.rel, "")
        candidates = by_app.get(app_id, [])
        chosen = ""
        for component in candidates:
            path = component.path
            if path and (sf.rel == path or sf.rel.startswith(path + "/")):
                chosen = component.id
                break
        if not chosen and candidates:
            chosen = next((c.id for c in candidates if not c.path), candidates[-1].id)
        mapping[sf.rel] = chosen
    return mapping


def _reconcile_dependencies(manifests: Sequence[Manifest], lock_deps: Sequence[Dependency],
                            usage: Dict[Tuple[str, str], Dict[str, object]],
                            app_of_file: Dict[str, str]) -> Tuple[List[Dependency], Dict[str, Dict[str, object]]]:
    merged: Dict[Tuple[str, str], Dependency] = {}
    for manifest in manifests:
        for dep in manifest.dependencies:
            key = (normalise_package(dep.name, dep.ecosystem), dep.ecosystem)
            existing = merged.get(key)
            if existing is None:
                merged[key] = dep
            else:
                existing.declared_in = dedupe(existing.declared_in + dep.declared_in)
                if not existing.version:
                    existing.version = dep.version
                if dep.scope == "runtime":
                    existing.scope = "runtime"

    for dep in lock_deps:
        key = (normalise_package(dep.name, dep.ecosystem), dep.ecosystem)
        existing = merged.get(key)
        if existing is None:
            dep.direct = False
            merged[key] = dep
        elif not existing.version or any(c in existing.version for c in "^~>=<* "):
            existing.version = dep.version or existing.version
            existing.purl = dep.purl or existing.purl

    undeclared: Dict[str, Dict[str, object]] = {}
    for (name, ecosystem), info in usage.items():
        key = (name, ecosystem)
        dep = merged.get(key)
        if dep is None:
            dep = _match_loosely(merged, name, ecosystem)
        if dep is not None:
            dep.used = True
            dep.used_by = dedupe(list(dep.used_by) + [str(f) for f in info["files"]])[:25]  # type: ignore[index]
            dep.apps = dedupe([a for a in info["apps"] if a])  # type: ignore[index]
        else:
            undeclared[name] = {"ecosystem": ecosystem, "files": info["files"]}

    dependencies = sorted(merged.values(), key=lambda d: (d.ecosystem, d.name.lower()))
    return dependencies, undeclared


def _match_loosely(merged: Dict[Tuple[str, str], Dependency], name: str, ecosystem: str) -> Optional[Dependency]:
    """Import names and package names differ often enough to be worth a second look."""
    aliases = {
        "pypi": {"yaml": "pyyaml", "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn",
                 "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "jwt": "pyjwt",
                 "dateutil": "python-dateutil", "attr": "attrs", "OpenSSL": "pyopenssl",
                 "google": "google-api-python-client", "psycopg2": "psycopg2-binary",
                 "serial": "pyserial", "usb": "pyusb", "Crypto": "pycryptodome"},
        "npm": {},
    }
    alias = aliases.get(ecosystem, {}).get(name)
    if alias:
        hit = merged.get((alias, ecosystem))
        if hit:
            return hit
    lowered = name.lower().replace("_", "-")
    for (dep_name, dep_ecosystem), dep in merged.items():
        if dep_ecosystem != ecosystem:
            continue
        if dep_name.lower().replace("_", "-") == lowered:
            return dep
        if ecosystem == "maven" and dep_name.endswith(f":{name}"):
            return dep
        if ecosystem == "nuget" and name.startswith(dep_name):
            return dep
    return None


def _attribute_compose_systems(infra: InfraScanner, systems: Sequence[ExternalSystem],
                               apps: Sequence[App]) -> None:
    """A ``postgres:15`` service in compose belongs to the applications whose own
    services declare ``depends_on`` it — not to whichever app happens to sit
    closest to the compose file."""
    by_name = {c["name"]: c for c in infra.containers}
    app_by_dir = {a.root: a.id for a in apps if a.root}
    service_system: Dict[str, str] = {}
    for system in systems:
        for evidence in system.evidence:
            note = evidence.note or ""
            if note.startswith("service "):
                service_system[note[len("service "):].split(":")[0].strip()] = system.id
    if not service_system:
        return
    by_id = {s.id: s for s in systems}
    for container in infra.containers:
        build = str(container.get("build", "")).strip("./")
        app_id = app_by_dir.get(build)
        if not app_id:
            continue
        for target in container.get("depends_on", []):
            system_id = service_system.get(str(target))
            if not system_id and str(target) in by_name:
                continue
            system = by_id.get(system_id or "")
            if system is not None and app_id not in system.apps:
                system.apps.append(app_id)


def _container_edges(infra: InfraScanner, apps: Sequence[App]) -> List[Edge]:
    edges: List[Edge] = []
    by_name = {c["name"]: c for c in infra.containers}
    app_by_dir = {a.root: a.id for a in apps}
    for container in infra.containers:
        source_app = app_by_dir.get(str(container.get("build", "")).strip("./"), "")
        for target in container.get("depends_on", []):
            other = by_name.get(target)
            if other is None:
                continue
            target_app = app_by_dir.get(str(other.get("build", "")).strip("./"), "")
            if source_app and target_app:
                edges.append(Edge(source=source_app, target=target_app, kind="deploy",
                                  label="depends_on",
                                  evidence=[Evidence(file=str(container.get("file", "")),
                                                     note=f"{container['name']} -> {target}")]))
    return edges


def _dedupe_findings(findings: Sequence[Finding]) -> List[Finding]:
    seen = set()
    out: List[Finding] = []
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    for finding in findings:
        # Without a file, every finding from one rule shares a key and all but
        # the first are dropped — that silently swallowed the second missing
        # lockfile in any repository with two ecosystems. Fall back to the
        # finding's own id, which is unique by construction.
        key = ((finding.file, finding.line, finding.identifier) if finding.file
               else ("", 0, finding.id))
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    out.sort(key=lambda f: (order.get(f.severity, 5), f.category, f.file, f.line))
    return out


def _summarise(result: ScanResult, ranks: Dict[str, float], fan_in: Dict[str, int],
               fan_out: Dict[str, int], readmes: Dict[str, str], unresolved: int,
               vendor_dirs: Sequence[str]) -> Dict[str, object]:
    top_components = sorted(result.components, key=lambda c: -ranks.get(c.id, 0))[:10]
    primary_languages = list(result.metrics.languages)[:5]
    root_readme = readmes.get("README.md") or readmes.get("readme.md") or ""
    purpose = apps_mod.readme_summary(root_readme, 600) if root_readme else ""
    if not purpose and result.apps:
        largest = max(result.apps, key=lambda a: a.loc)
        purpose = largest.description or largest.purpose

    kinds = {app.kind for app in result.apps}
    if len(result.apps) > 1:
        shape = "monorepo"
    elif "frontend" in kinds and "service" in kinds:
        shape = "full-stack application"
    else:
        shape = next(iter(kinds), "application")

    data_stores = [s.name for s in result.external_systems
                   if s.kind in ("database", "cache", "storage", "search")]
    integrations = [s.name for s in result.external_systems if s.kind not in
                    ("database", "cache", "storage", "search")]

    severity = result.metrics.findings_by_severity
    risk_score = (severity.get("critical", 0) * 10 + severity.get("high", 0) * 5
                  + severity.get("medium", 0) * 2 + severity.get("low", 0))
    if severity.get("critical"):
        risk = "critical"
    elif severity.get("high", 0) >= 3:
        risk = "high"
    elif severity.get("high") or severity.get("medium", 0) >= 5:
        risk = "medium"
    else:
        risk = "low"

    return {
        "purpose": purpose or f"{title_case(result.meta.repo_name)} — purpose not documented in a README.",
        "shape": shape,
        "primary_languages": primary_languages,
        "architecture_styles": dedupe([a.architecture_style for a in result.apps if a.architecture_style]),
        "entrypoints": [
            {"app": app.name, "kind": app.kind, "entrypoints": app.entrypoints[:4]}
            for app in result.apps
        ],
        "top_components": [
            {"id": c.id, "name": c.name, "app": c.app, "files": c.files, "loc": c.loc,
             "rank": ranks.get(c.id, 0), "fan_in": fan_in.get(c.id, 0), "fan_out": fan_out.get(c.id, 0)}
            for c in top_components
        ],
        "data_stores": data_stores,
        "integrations": integrations,
        "risk_level": risk,
        "risk_score": risk_score,
        "unresolved_imports": unresolved,
        "vendored_directories": list(vendor_dirs)[:20],
        "test_coverage_proxy": result.metrics.test_ratio,
        "has_ci": bool(result.infrastructure.get("ci")),
        "has_containers": bool(result.infrastructure.get("dockerfiles") or result.infrastructure.get("containers")),
        "has_iac": bool(result.infrastructure.get("terraform") or result.infrastructure.get("kubernetes")),
    }
