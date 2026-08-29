"""Plain-language description of a repository, for readers who do not code.

Everything here is derived from the same scan the technical views use; it is a
translation, not a second analysis. Each statement keeps a technical detail line
and its evidence, so a business reader and an engineer can read the same page at
different depths.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .model import ScanResult
from .util import title_case

# what an external system means to someone who does not care which vendor it is
SYSTEM_MEANING: Dict[str, str] = {
    "database": "stores its data",
    "cache": "keeps recently used data close at hand for speed",
    "queue": "passes work to other systems in the background",
    "storage": "stores files and documents",
    "search": "powers search",
    "auth": "signs people in and checks who they are",
    "payment": "takes payments",
    "mail": "sends email and messages",
    "observability": "reports on its own health",
    "ai": "uses an AI service",
    "api": "talks to another system",
    "external": "talks to another system",
}

METHOD_VERB = {
    "GET": "look up", "POST": "create", "PUT": "replace", "PATCH": "update",
    "DELETE": "remove", "ANY": "work with", "HEAD": "check", "OPTIONS": "check",
}

_SEVERITY_MEANING = {
    "critical": "needs attention now",
    "high": "should be fixed soon",
    "medium": "worth planning in",
    "low": "minor",
    "info": "informational",
}

# how a finding reads to someone who is not going to open the file
FINDING_MEANING: Dict[str, str] = {
    "secret": "A password or access key is written directly into the code. Anyone who can read "
              "this repository can use it.",
    "dependency": "A third-party component this software depends on carries a known problem.",
    "config": "A configuration file contains values that should not be shared.",
    "infra": "The way this software is packaged or deployed leaves it more exposed than it "
             "needs to be.",
    "code": "The code contains a pattern that is a common cause of security incidents.",
    "quality": "This makes the code harder to change safely.",
    "license": "A dependency's licence may constrain how this software can be used.",
}


@dataclass
class Point:
    """One statement, at two depths."""

    title: str
    plain: str
    detail: str = ""
    evidence: List[str] = field(default_factory=list)


@dataclass
class BusinessOverview:
    headline: str = ""
    what_it_is: str = ""
    audience_note: str = ""
    capabilities: List[Point] = field(default_factory=list)
    users: List[Point] = field(default_factory=list)
    dependencies: List[Point] = field(default_factory=list)
    data: List[Point] = field(default_factory=list)
    operations: List[Point] = field(default_factory=list)
    risks: List[Point] = field(default_factory=list)
    health: List[Point] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        def points(items: Sequence[Point]) -> List[Dict[str, object]]:
            return [{"title": p.title, "plain": p.plain, "detail": p.detail,
                     "evidence": list(p.evidence)} for p in items]

        return {
            "headline": self.headline,
            "what_it_is": self.what_it_is,
            "audience_note": self.audience_note,
            "capabilities": points(self.capabilities),
            "users": points(self.users),
            "dependencies": points(self.dependencies),
            "data": points(self.data),
            "operations": points(self.operations),
            "risks": points(self.risks),
            "health": points(self.health),
            "unknowns": list(self.unknowns),
        }


_OPERATIONAL = {"health", "healthz", "ready", "readyz", "live", "livez", "ping", "status",
                "metrics", "version", "info", "favicon.ico", "robots.txt"}


def plural(count: int, singular: str, plural_form: str = "") -> str:
    """"1 test file" / "3 test files" — small thing, but the reports read better."""
    word = singular if count == 1 else (plural_form or singular + "s")
    return f"{count} {word}"


def verb(count: int, singular_form: str, plural_form: str) -> str:
    return singular_form if count == 1 else plural_form


def _resource_label(path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith(("{", ":", "<", "*"))]
    skip = {"api", "v1", "v2", "v3", "rest", "graphql", "public", "internal"}
    for part in parts:
        if part.lower() not in skip:
            return title_case(part)
    return title_case(parts[0]) if parts else "General"


def capabilities(result: ScanResult) -> List[Point]:
    """What the software lets someone do, grouped by subject rather than by route."""
    groups: Dict[str, List] = defaultdict(list)
    operational = 0
    for endpoint in result.endpoints:
        if endpoint.kind not in ("http", "graphql", "grpc", "websocket", "function"):
            continue
        label = _resource_label(endpoint.path)
        if label.lower() in _OPERATIONAL:
            operational += 1  # health checks are plumbing, not a capability
            continue
        groups[label].append(endpoint)

    points: List[Point] = []
    for label, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        verbs: List[str] = []
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            if any(m.method.upper() == method for m in members):
                verbs.append(METHOD_VERB[method])
        if not verbs:
            verbs = ["work with"]
        apps = {result.app_by_id(m.app).name for m in members
                if result.app_by_id(m.app) is not None}
        plain = f"People and other systems can {', '.join(verbs[:-1])}" \
                + (f" and {verbs[-1]}" if len(verbs) > 1 else verbs[0]) \
                + f" {label.lower()}."
        points.append(Point(
            title=label,
            plain=plain,
            detail=f"{plural(len(members), 'endpoint')} in "
                   f"{', '.join(sorted(apps)) or 'this repository'}: "
                   + ", ".join(sorted({f"{m.method} {m.path}" for m in members})[:6]),
            evidence=[f"{m.file}:{m.line}" for m in members[:3] if m.file],
        ))

    if operational:
        points.append(Point(
            title="Health and monitoring",
            plain="It reports whether it is running, so it can be watched automatically.",
            detail=plural(operational, "operational endpoint") + " (health, readiness, metrics).",
        ))

    events = [e for e in result.endpoints if e.kind in ("event", "cron")]
    if events:
        points.append(Point(
            title="Background work",
            plain="Some work happens on its own, triggered by events or on a schedule, rather "
                  "than by someone clicking something.",
            detail=plural(len(events), "handler") + ": "
                   + ", ".join(sorted({e.path or e.handler for e in events})[:6]),
            evidence=[f"{e.file}:{e.line}" for e in events[:3] if e.file],
        ))

    commands = [e for e in result.endpoints if e.kind == "cli"]
    if commands:
        points.append(Point(
            title="Operator commands",
            plain="Engineers can run this from a terminal to perform tasks by hand.",
            detail=plural(len(commands), "command") + ": "
                   + ", ".join(sorted({c.path or c.handler for c in commands})[:6]),
            evidence=[f"{c.file}:{c.line}" for c in commands[:3] if c.file],
        ))
    return points[:12]


def users(result: ScanResult) -> List[Point]:
    points: List[Point] = []
    kinds = {app.kind for app in result.apps}
    endpoint_kinds = {e.kind for e in result.endpoints}
    if "frontend" in kinds:
        frontends = [a.name for a in result.apps if a.kind == "frontend"]
        points.append(Point(
            title="People, through a screen",
            plain="There is a user interface, so people use this directly.",
            detail="Front end: " + ", ".join(frontends),
        ))
    if endpoint_kinds & {"http", "graphql", "grpc"}:
        points.append(Point(
            title="Other systems, through an interface",
            plain="Other software can connect to this and use it programmatically.",
            detail=plural(len([e for e in result.endpoints
                               if e.kind in ("http", "graphql", "grpc")]), "endpoint")
                   + " exposed.",
        ))
    if "cli" in kinds or "cli" in endpoint_kinds:
        points.append(Point(
            title="Engineers, from a terminal",
            plain="Parts of this are operated by hand by technical staff.",
        ))
    if "library" in kinds:
        libraries = [a.name for a in result.apps if a.kind == "library"]
        points.append(Point(
            title="Other teams' code",
            plain="Part of this project is shared code that other software builds on.",
            detail="Shared: " + ", ".join(libraries),
        ))
    if not points:
        points.append(Point(
            title="Not determined",
            plain="No user interface, API or command line entrypoint was found, so who uses this "
                  "could not be established from the code alone.",
        ))
    return points


def dependencies(result: ScanResult) -> List[Point]:
    grouped: Dict[str, List] = defaultdict(list)
    for system in result.external_systems:
        grouped[system.kind].append(system)
    points: List[Point] = []
    for kind, systems in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        if kind in ("database", "cache", "storage", "search"):
            continue  # covered by the data section
        meaning = SYSTEM_MEANING.get(kind, "is used by this software")
        names = sorted({s.name for s in systems})
        points.append(Point(
            title=", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else ""),
            plain=f"This software {meaning}. If it is unavailable, that part of the service stops "
                  f"working.",
            detail=f"{kind}: " + ", ".join(names),
            evidence=[f"{s.evidence[0].file}:{s.evidence[0].line}"
                      for s in systems[:3] if s.evidence],
        ))
    return points


def data(result: ScanResult) -> List[Point]:
    stores = [s for s in result.external_systems
              if s.kind in ("database", "cache", "storage", "search")]
    points: List[Point] = []
    for system in stores:
        points.append(Point(
            title=system.name,
            plain=f"This software {SYSTEM_MEANING.get(system.kind, 'stores data')} here.",
            detail=f"{system.technology or system.kind}; referenced "
                   f"{plural(len(system.evidence), 'time')} in the code and configuration.",
            evidence=[f"{ev.file}:{ev.line}" for ev in system.evidence[:3] if ev.file],
        ))
    tables = [s for s in result.symbols if s.kind == "table"]
    if tables:
        points.append(Point(
            title="Defined data structures",
            plain=f"The code defines {plural(len(tables), 'table')} of stored information.",
            detail=", ".join(sorted({t.name for t in tables})[:12]),
        ))
    if not points:
        points.append(Point(
            title="No data store detected",
            plain="Nothing in the code points at a database or file store, so this probably does "
                  "not keep data of its own.",
        ))
    return points


def operations(result: ScanResult) -> List[Point]:
    infra = result.infrastructure or {}
    points: List[Point] = []
    containers = infra.get("containers") or []
    dockerfiles = infra.get("dockerfiles") or []
    workloads = infra.get("kubernetes") or []
    ci = infra.get("ci") or []
    terraform = infra.get("terraform") or []

    if dockerfiles or containers:
        points.append(Point(
            title="Packaged to run anywhere",
            plain="This is packaged into containers, so it runs the same way on a laptop and in "
                  "production.",
            detail=f"{plural(len(dockerfiles), 'Dockerfile')}, "
                   f"{plural(len(containers), 'composed service')}.",
        ))
    if workloads:
        points.append(Point(
            title="Runs on Kubernetes",
            plain="It is deployed onto a cluster that keeps it running and can scale it.",
            detail=f"{plural(len(workloads), 'Kubernetes object')} defined in this repository.",
        ))
    if terraform:
        points.append(Point(
            title="Infrastructure is defined in code",
            plain="The cloud resources this needs are described alongside the code, so they can "
                  "be rebuilt from scratch.",
            detail=f"{plural(len(terraform), 'Terraform block')}.",
        ))
    if ci:
        names = ", ".join(sorted({str(c.get("system", "")) for c in ci}))
        points.append(Point(
            title="Automated checks on every change",
            plain="Changes are built and tested automatically before they are merged.",
            detail=f"{plural(len(ci), 'pipeline')} using {names}.",
        ))
    if not points:
        points.append(Point(
            title="No deployment definition found",
            plain="Nothing in this repository describes how the software is packaged or "
                  "deployed, so that happens somewhere else.",
        ))
    return points


def risks(result: ScanResult, limit: int = 6) -> List[Point]:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    ranked = sorted(result.findings, key=lambda f: (order.get(f.severity, 5), f.category))
    points: List[Point] = []
    for finding in ranked[:limit]:
        if finding.severity in ("low", "info") and points:
            break
        location = f"{finding.file}:{finding.line}" if finding.file else "across the repository"
        plain = FINDING_MEANING.get(finding.category, "This is a weakness worth reviewing.")
        if finding.ai_assessment == "false_positive":
            plain = f"Reviewed and dismissed: {finding.ai_reasoning}" if finding.ai_reasoning \
                else "A reviewer judged this not to be a real problem in context."
        points.append(Point(
            title=f"{finding.title} ({_SEVERITY_MEANING.get(finding.severity, finding.severity)})",
            plain=plain,
            detail=finding.remediation or finding.title,
            evidence=[location],
        ))
    if not points:
        points.append(Point(
            title="Nothing flagged",
            plain="The automated checks found no security or configuration problems worth "
                  "raising. That is not a guarantee — it means the known patterns did not match.",
        ))
    return points


def health(result: ScanResult) -> List[Point]:
    metrics = result.metrics
    points: List[Point] = []
    if metrics.test_files:
        points.append(Point(
            title="Automated tests exist",
            plain=f"About {metrics.test_ratio:.0%} as many test files as source files, which "
                  f"suggests changes can be made with some confidence.",
            detail=f"{plural(metrics.test_files, 'test file')}.",
        ))
    else:
        points.append(Point(
            title="No automated tests found",
            plain="Nothing here tests itself, so every change carries more risk than it needs to.",
        ))
    if metrics.cycles:
        points.append(Point(
            title="Parts of the code depend on each other in circles",
            plain=f"There {verb(metrics.cycles, 'is', 'are')} "
                  f"{plural(metrics.cycles, 'circular dependency', 'circular dependencies')} "
                  f"between parts of the code, which makes it harder to change one piece at a "
                  f"time.",
            detail="Circular imports between components.",
        ))
    if metrics.doc_files:
        points.append(Point(
            title="Written documentation exists",
            plain=f"There {verb(metrics.doc_files, 'is', 'are')} "
                  f"{plural(metrics.doc_files, 'documentation file')} alongside the code.",
        ))
    unused = [f for f in result.findings if f.identifier == "RG-DEP-UNUSED"]
    missing = [f for f in result.findings if f.identifier == "RG-DEP-MISSING"]
    if missing:
        points.append(Point(
            title="Some components are used without being declared",
            plain=f"{plural(len(missing), 'third-party component')} "
                  f"{verb(len(missing), 'is', 'are')} used but not listed, which can make a clean "
                  f"install fail and hides it from security scanning.",
            detail=", ".join(sorted({f.package for f in missing})[:8]),
        ))
    elif unused:
        points.append(Point(
            title="Some declared components are never used",
            plain=f"{plural(len(unused), 'declared dependency', 'declared dependencies')} "
                  f"{verb(len(unused), 'appears', 'appear')} unused — dead weight worth removing.",
        ))
    return points


def build(result: ScanResult) -> BusinessOverview:
    overview = BusinessOverview()
    summary = result.summary or {}
    profile = result.profile or {}
    apps = result.apps
    primary = max(apps, key=lambda a: a.loc) if apps else None

    name = result.meta.repo_name
    overview.headline = f"{title_case(name)} — {profile.get('label', 'software repository')}"

    documented = str(summary.get("purpose", "")).strip()
    derived = (primary.ai_summary or primary.purpose) if primary else ""
    if primary and primary.ai_summary:
        overview.what_it_is = primary.ai_summary
    elif documented and not documented.endswith("not documented in a README."):
        overview.what_it_is = documented
    else:
        overview.what_it_is = derived or "This repository's purpose is not documented anywhere, " \
                                         "and the code does not make it obvious."

    if len(apps) > 1:
        kinds = defaultdict(list)
        for app in apps:
            kinds[app.kind].append(app.name)
        parts = [f"{len(names)} {kind}{'s' if len(names) > 1 else ''} ({', '.join(names[:3])})"
                 for kind, names in sorted(kinds.items(), key=lambda kv: -len(kv[1]))]
        overview.what_it_is += (f" It holds {len(apps)} separate pieces of software: "
                                + "; ".join(parts) + ".")

    overview.audience_note = (
        "Everything on this page was read out of the code itself, not from documentation that "
        "may be out of date. Each point can be expanded for the technical detail behind it."
    )
    overview.capabilities = capabilities(result)
    overview.users = users(result)
    overview.dependencies = dependencies(result)
    overview.data = data(result)
    overview.operations = operations(result)
    overview.risks = risks(result)
    overview.health = health(result)

    unknowns: List[str] = []
    if not documented or documented.endswith("not documented in a README."):
        unknowns.append("No README describes what this is for, so the purpose above was inferred "
                        "from the code.")
    if not result.endpoints:
        unknowns.append("No entrypoints were found, so how this is used could not be determined.")
    if summary.get("unresolved_imports"):
        unknowns.append(f"{summary['unresolved_imports']} references between files could not be "
                        f"resolved, so some connections may be missing.")
    if not result.ai.present:
        unknowns.append("No reviewer has confirmed these findings; run the optional AI pass or "
                        "have an engineer read the technical views.")
    overview.unknowns = unknowns
    return overview
