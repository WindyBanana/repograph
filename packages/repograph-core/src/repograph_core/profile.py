"""What kind of repository is this, and what is worth producing for it?

A repository of markdown guides does not need a deployment diagram, a BPMN
process or a C4 container view. A library does not need a deployment view. A
monorepo of services needs all of it. This module makes that judgement from the
scan itself, records the reason for every decision, and lets the renderers skip
work honestly instead of emitting empty boxes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .model import ScanResult

# Every artifact the renderers can produce, and what it needs to be worth making.
ARTIFACTS = (
    "business-overview", "c4-context", "c4-container", "c4-component",
    "application-landscape", "dependency-layers", "dependency-graph", "external-systems",
    "deployment", "flows", "bpmn", "archimate", "sequence", "entity-relationship",
    "endpoints-section", "dependencies-section", "security-section", "infrastructure-section",
    "quality-section", "deck", "pdf", "workbook",
)


@dataclass
class Decision:
    include: bool
    reason: str


@dataclass
class RepoProfile:
    kind: str = "mixed"
    label: str = "Software repository"
    summary: str = ""
    audiences: List[str] = field(default_factory=lambda: ["technical"])
    signals: List[str] = field(default_factory=list)
    artifacts: Dict[str, Decision] = field(default_factory=dict)
    max_flows: int = 14
    forced: bool = False

    def wants(self, name: str) -> bool:
        decision = self.artifacts.get(name)
        return True if decision is None else decision.include

    def reason(self, name: str) -> str:
        decision = self.artifacts.get(name)
        return decision.reason if decision else ""

    def skipped(self) -> List[Tuple[str, str]]:
        return [(name, d.reason) for name, d in sorted(self.artifacts.items()) if not d.include]

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "label": self.label,
            "summary": self.summary,
            "audiences": list(self.audiences),
            "signals": list(self.signals),
            "max_flows": self.max_flows,
            "forced": self.forced,
            "artifacts": {name: {"include": d.include, "reason": d.reason}
                          for name, d in sorted(self.artifacts.items())},
        }


def classify(result: ScanResult) -> Tuple[str, str, List[str]]:
    """Return (kind, human label, the signals that decided it)."""
    metrics = result.metrics
    files = result.files
    total = len(files) or 1
    by_kind: Dict[str, int] = {}
    for info in files:
        by_kind[info.kind] = by_kind.get(info.kind, 0) + 1
    source = by_kind.get("source", 0)
    docs = by_kind.get("docs", 0)
    infra = by_kind.get("infra", 0)
    signals: List[str] = []

    code_loc = sum(i.loc for i in files if i.kind == "source")
    doc_ratio = docs / total
    infra_ratio = infra / total

    if source == 0 and metrics.loc == 0:
        return "empty", "Empty or unreadable repository", ["no readable files were found"]

    if doc_ratio >= 0.55 and source <= max(5, total * 0.1):
        signals.append(f"{docs} of {total} files are documentation, {source} are source")
        return "documentation", "Documentation / content repository", signals

    if infra_ratio >= 0.4 and source <= total * 0.25:
        signals.append(f"{infra} of {total} files are infrastructure definitions")
        return "infrastructure", "Infrastructure-as-code repository", signals

    notebooks = sum(1 for i in files if i.language in ("Jupyter",))
    if notebooks and notebooks >= source * 0.5:
        signals.append(f"{notebooks} notebooks dominate the source files")
        return "data", "Data science / notebook repository", signals

    kinds = [app.kind for app in result.apps]
    if metrics.apps > 1:
        signals.append(f"{metrics.apps} separately built applications")
        if len({k for k in kinds}) > 1:
            signals.append("they are of different kinds: " + ", ".join(sorted(set(kinds))))
        return "monorepo", "Monorepo of several applications", signals

    single = kinds[0] if kinds else "application"
    if single == "library" and metrics.endpoints == 0:
        signals.append("one publishable unit with no entrypoints of its own")
        return "library", "Library / package", signals
    if single == "frontend":
        signals.append("frontend frameworks and no server endpoints of note")
        return "frontend", "Front-end application", signals
    if single == "cli":
        signals.append("command line entrypoints and no HTTP surface")
        return "cli", "Command line tool", signals
    if metrics.endpoints or result.external_systems:
        signals.append(f"{metrics.endpoints} endpoints and "
                       f"{metrics.external_systems} external systems")
        return "service", "Backend service", signals

    signals.append(f"{source} source files, {code_loc} lines, no clear entrypoints")
    return "mixed", "General software repository", signals


def build_profile(result: ScanResult, force_all: bool = False) -> RepoProfile:
    kind, label, signals = classify(result)
    profile = RepoProfile(kind=kind, label=label, signals=signals, forced=force_all)

    metrics = result.metrics
    has_components = metrics.components > 1
    import_edges = [e for e in result.edges if e.kind == "imports"]
    has_graph = bool(import_edges)
    has_systems = bool(result.external_systems)
    infra = result.infrastructure or {}
    has_deployment = bool(infra.get("containers") or infra.get("kubernetes"))
    has_infra = has_deployment or bool(infra.get("terraform") or infra.get("ci")
                                       or infra.get("dockerfiles"))
    has_flows = bool(result.flows)
    has_endpoints = bool(result.endpoints)
    has_findings = bool(result.findings)
    has_deps = bool(result.dependencies)
    multi_app = metrics.apps > 1
    tables = [s for s in result.symbols if s.kind == "table"]

    def decide(name: str, include: bool, reason_yes: str, reason_no: str) -> None:
        profile.artifacts[name] = Decision(
            include=True if force_all else include,
            reason=reason_yes if (include or force_all) else reason_no,
        )

    documentation_like = kind in ("documentation", "empty")

    decide("business-overview", not documentation_like or bool(result.apps),
           "explains the repository for a non-technical reader",
           "there is no application to explain")
    decide("c4-context", not documentation_like,
           "shows who uses the system and what it depends on",
           "a documentation repository has no runtime context to draw")
    decide("c4-container", not documentation_like and (multi_app or has_systems or has_endpoints),
           "there is more than one deployable unit or backing system",
           "a single unit with no backing systems is fully described by its component view")
    decide("c4-component", has_components,
           "the code splits into components worth drawing",
           "too few components to make a diagram worth reading")
    decide("application-landscape", multi_app,
           "several applications share this repository",
           "there is only one application, so the landscape adds nothing")
    decide("dependency-graph", has_graph,
           "there are internal dependencies to explore",
           "no internal imports were resolved, so the graph would be empty")
    decide("dependency-layers", has_graph and metrics.components > 3,
           "enough components to show a layering",
           "not enough internal structure to layer")
    decide("external-systems", has_systems,
           "external systems were detected",
           "no external systems were detected")
    decide("deployment", has_deployment,
           "containers or Kubernetes objects describe how this runs",
           "no container or orchestration definitions were found")
    decide("flows", has_flows,
           "entrypoints could be traced into processes",
           "no entrypoints were found to trace")
    decide("bpmn", has_flows and (kind in ("service", "monorepo", "mixed") or has_endpoints),
           "the processes are worth exporting to process tooling",
           "there are no processes worth exporting to BPMN")
    decide("sequence", has_flows, "processes span more than one layer",
           "no processes to sequence")
    decide("archimate", not documentation_like and (multi_app or has_systems),
           "there is an application and technology landscape to model",
           "too little landscape to justify an enterprise-architecture model")
    decide("entity-relationship", bool(tables),
           f"{len(tables)} table definitions were found",
           "no SQL table definitions were found")
    decide("endpoints-section", has_endpoints,
           "the code exposes an API surface",
           "no endpoints, jobs or commands were detected")
    decide("dependencies-section", has_deps,
           "third-party dependencies are declared",
           "no dependency manifests were found")
    decide("security-section", True,
           "findings are always reported, including when there are none"
           if has_findings else "reported as clean so the absence is explicit",
           "")
    decide("infrastructure-section", has_infra,
           "containers, IaC or CI configuration were found",
           "no infrastructure or CI configuration was found")
    decide("quality-section", has_graph or metrics.test_files > 0,
           "there is structure and test coverage to report on",
           "nothing measurable to report")
    decide("deck", not documentation_like and bool(result.apps),
           "there is an architecture worth presenting",
           "a slide deck of a documentation repository would be empty")
    decide("pdf", True, "the printable report always makes sense", "")
    decide("workbook", has_findings or has_deps or has_endpoints,
           "there are tables worth filtering and pivoting",
           "there is nothing tabular to put in a workbook")

    if kind == "documentation":
        profile.max_flows = 0
    elif kind in ("library", "frontend", "cli"):
        profile.max_flows = 6
    elif kind == "monorepo":
        profile.max_flows = 14
    else:
        profile.max_flows = 10
    if force_all:
        profile.max_flows = max(profile.max_flows, 14)

    profile.audiences = ["business", "technical"] if kind in (
        "service", "monorepo", "frontend", "mixed") else ["technical"]
    profile.summary = _summarise(result, profile)
    return profile


def _summarise(result: ScanResult, profile: RepoProfile) -> str:
    included = sum(1 for d in profile.artifacts.values() if d.include)
    skipped = len(profile.artifacts) - included
    base = f"{profile.label}. "
    if profile.forced:
        return base + "All artifacts were produced because --everything was requested."
    if skipped:
        return (base + f"{included} artifact types were produced and {skipped} skipped as "
                       f"not applicable to this repository.")
    return base + f"All {included} artifact types applied to this repository."
