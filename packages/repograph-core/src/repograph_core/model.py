"""Data model for a repository scan.

Everything the scanners produce ends up in :class:`ScanResult`, which is a plain
tree of dataclasses that serialises to JSON without any third party helpers.
The JSON document (``repograph.json``) is the single source of truth every
renderer reads, so a new output format never has to re-scan anything.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "1.0"


class Severity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[self.value]


SEVERITY_ORDER = [s.value for s in Severity]


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


@dataclass
class Evidence:
    """Where a fact came from, so a human can verify anything we claim."""

    file: str = ""
    line: int = 0
    snippet: str = ""
    note: str = ""


@dataclass
class FileInfo:
    path: str
    language: str = "unknown"
    kind: str = "source"  # source | test | config | infra | docs | build | data | generated
    loc: int = 0
    sloc: int = 0
    size: int = 0
    app: str = ""
    component: str = ""
    imports: List[str] = field(default_factory=list)
    symbols: int = 0


@dataclass
class Symbol:
    name: str
    kind: str  # class | function | method | interface | struct | enum | const
    file: str
    line: int = 0
    app: str = ""
    component: str = ""
    signature: str = ""
    doc: str = ""
    exported: bool = True


@dataclass
class Component:
    """A cohesive unit inside an app: a package, module tree or service part."""

    id: str
    name: str
    path: str
    app: str = ""
    kind: str = "module"  # module | package | service | library | frontend | job | test | infra
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    files: int = 0
    loc: int = 0
    description: str = ""


@dataclass
class AiProvenance:
    """Who produced an enrichment, so a reader can weigh it."""

    tool: str = ""            # claude-code | codex | gemini-cli | manual | ...
    model: str = ""
    generated_at: str = ""
    request_version: str = ""
    notes: str = ""


@dataclass
class AiInsight:
    id: str
    kind: str = "observation"  # risk | observation | recommendation | answer
    title: str = ""
    detail: str = ""
    severity: str = "info"
    confidence: str = "medium"
    targets: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)


@dataclass
class AiEnrichment:
    """Optional layer written by an AI agent on top of the deterministic scan.

    Kept in its own branch of the model, and every field it fills is labelled in
    the reports, so the machine-checked facts and the model's judgement are never
    confused with one another.
    """

    present: bool = False
    provenance: AiProvenance = field(default_factory=AiProvenance)
    insights: List[AiInsight] = field(default_factory=list)
    unanswered: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)
    answered_questions: int = 0
    diagram_captions: Dict[str, str] = field(default_factory=dict)


@dataclass
class App:
    """A deployable/publishable unit. A monorepo has several; a plain repo one."""

    id: str
    name: str
    root: str
    kind: str = "application"  # application | service | library | frontend | cli | job | infra | docs
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    manifests: List[str] = field(default_factory=list)
    entrypoints: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    files: int = 0
    loc: int = 0
    description: str = ""
    purpose: str = ""
    architecture_style: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    ai_summary: str = ""
    ai_responsibilities: List[str] = field(default_factory=list)


@dataclass
class Edge:
    """A directed relationship between two nodes of any kind."""

    source: str
    target: str
    kind: str = "imports"  # imports | depends | http | db | queue | cache | storage | build | deploy | data
    weight: int = 1
    label: str = ""
    evidence: List[Evidence] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source}␟{self.target}␟{self.kind}"


@dataclass
class Dependency:
    name: str
    version: str = ""
    ecosystem: str = ""  # npm | pypi | go | maven | nuget | cargo | rubygems | composer | ...
    scope: str = "runtime"  # runtime | dev | test | optional | peer | build
    declared_in: List[str] = field(default_factory=list)
    apps: List[str] = field(default_factory=list)
    used_by: List[str] = field(default_factory=list)
    direct: bool = True
    declared: bool = True
    used: bool = False
    purl: str = ""
    license: str = ""


@dataclass
class Endpoint:
    kind: str = "http"  # http | graphql | grpc | websocket | event | cli | cron | function
    method: str = ""
    path: str = ""
    handler: str = ""
    file: str = ""
    line: int = 0
    app: str = ""
    component: str = ""
    framework: str = ""
    auth: str = ""
    description: str = ""


@dataclass
class ExternalSystem:
    id: str
    name: str
    # database | cache | queue | storage | api | auth | mail | payment |
    # observability | ai | search | external
    kind: str = "external"
    technology: str = ""
    direction: str = "outbound"  # outbound | inbound | bidirectional
    apps: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    description: str = ""


@dataclass
class Finding:
    id: str
    title: str
    severity: str = Severity.MEDIUM.value
    category: str = "code"  # secret | dependency | code | config | infra | license | quality
    file: str = ""
    line: int = 0
    snippet: str = ""
    cwe: str = ""
    package: str = ""
    version: str = ""
    fixed_version: str = ""
    identifier: str = ""  # CVE / GHSA / rule id
    confidence: str = "medium"  # high | medium | low
    remediation: str = ""
    references: List[str] = field(default_factory=list)
    app: str = ""
    ai_assessment: str = ""   # true_positive | false_positive | needs_review
    ai_reasoning: str = ""


@dataclass
class FlowNode:
    id: str
    label: str
    kind: str = "task"  # start | end | task | decision | event | datastore | external | subprocess | gateway
    lane: str = ""
    file: str = ""
    line: int = 0


@dataclass
class FlowEdge:
    source: str
    target: str
    label: str = ""
    kind: str = "sequence"  # sequence | conditional | message | data


@dataclass
class Flow:
    id: str
    name: str
    app: str = ""
    description: str = ""
    lanes: List[str] = field(default_factory=list)
    nodes: List[FlowNode] = field(default_factory=list)
    edges: List[FlowEdge] = field(default_factory=list)
    entrypoint: str = ""
    ai_narrative: str = ""


@dataclass
class C4Element:
    id: str
    name: str
    level: str = "container"  # person | system | system_ext | container | component | database
    technology: str = ""
    description: str = ""
    parent: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class C4Relation:
    source: str
    target: str
    description: str = ""
    technology: str = ""


@dataclass
class C4Model:
    elements: List[C4Element] = field(default_factory=list)
    relations: List[C4Relation] = field(default_factory=list)


@dataclass
class ArchimateElement:
    id: str
    name: str
    type: str  # ApplicationComponent, TechnologyService, DataObject, BusinessProcess, ...
    layer: str = "application"  # business | application | technology | motivation
    documentation: str = ""


@dataclass
class ArchimateRelation:
    source: str
    target: str
    type: str = "Serving"  # Serving | Access | Composition | Flow | Association | Triggering
    name: str = ""


@dataclass
class ArchimateModel:
    elements: List[ArchimateElement] = field(default_factory=list)
    relations: List[ArchimateRelation] = field(default_factory=list)


@dataclass
class GitInfo:
    is_repo: bool = False
    remote: str = ""
    branch: str = ""
    head: str = ""
    commits: int = 0
    first_commit: str = ""
    last_commit: str = ""
    contributors: int = 0
    top_authors: List[Dict[str, Any]] = field(default_factory=list)
    hotspots: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Metrics:
    files: int = 0
    scanned_files: int = 0
    loc: int = 0
    sloc: int = 0
    languages: Dict[str, int] = field(default_factory=dict)
    language_files: Dict[str, int] = field(default_factory=dict)
    apps: int = 0
    components: int = 0
    endpoints: int = 0
    dependencies: int = 0
    external_systems: int = 0
    findings_by_severity: Dict[str, int] = field(default_factory=dict)
    test_files: int = 0
    test_ratio: float = 0.0
    doc_files: int = 0
    max_component_fan_in: int = 0
    max_component_fan_out: int = 0
    cycles: int = 0
    duration_seconds: float = 0.0


@dataclass
class ScanMeta:
    tool: str = "repograph"
    version: str = "0.1.0"
    schema_version: str = SCHEMA_VERSION
    generated_at: str = ""
    root: str = ""
    repo_name: str = ""
    command: str = ""
    host_os: str = ""
    python: str = ""
    online: bool = False
    profile: str = "default"
    warnings: List[str] = field(default_factory=list)


@dataclass
class ScanResult:
    meta: ScanMeta = field(default_factory=ScanMeta)
    git: GitInfo = field(default_factory=GitInfo)
    metrics: Metrics = field(default_factory=Metrics)
    apps: List[App] = field(default_factory=list)
    components: List[Component] = field(default_factory=list)
    files: List[FileInfo] = field(default_factory=list)
    symbols: List[Symbol] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    endpoints: List[Endpoint] = field(default_factory=list)
    external_systems: List[ExternalSystem] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    flows: List[Flow] = field(default_factory=list)
    c4: C4Model = field(default_factory=C4Model)
    archimate: ArchimateModel = field(default_factory=ArchimateModel)
    cycles: List[List[str]] = field(default_factory=list)
    layers: Dict[str, int] = field(default_factory=dict)
    infrastructure: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    business: Dict[str, Any] = field(default_factory=dict)
    ai: AiEnrichment = field(default_factory=AiEnrichment)

    # -- convenience lookups -------------------------------------------------
    def app_by_id(self, app_id: str) -> Optional[App]:
        return next((a for a in self.apps if a.id == app_id), None)

    def component_by_id(self, cid: str) -> Optional[Component]:
        return next((c for c in self.components if c.id == cid), None)

    def edges_of_kind(self, *kinds: str) -> List[Edge]:
        return [e for e in self.edges if e.kind in kinds]

    def findings_by_severity(self, severity: str) -> List[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def finding_by_id(self, finding_id: str) -> Optional[Finding]:
        return next((f for f in self.findings if f.id == finding_id), None)

    def flow_by_id(self, flow_id: str) -> Optional[Flow]:
        return next((f for f in self.flows if f.id == flow_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    def to_json(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False, ensure_ascii=False)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> ScanResult:
        return _from_dict(ScanResult, data)


# -- deserialisation ---------------------------------------------------------

def _from_dict(cls: Any, data: Any) -> Any:
    if not dataclasses.is_dataclass(cls) or not isinstance(data, dict):
        return data
    kwargs: Dict[str, Any] = {}
    hints = {f.name: f for f in dataclasses.fields(cls)}
    for name, f in hints.items():
        if name not in data:
            continue
        kwargs[name] = _coerce(f.type, data[name])
    return cls(**kwargs)


def _coerce(type_hint: Any, value: Any) -> Any:
    text = type_hint if isinstance(type_hint, str) else getattr(type_hint, "__name__", str(type_hint))
    for name, klass in _DATACLASSES.items():
        if text == name:
            return _from_dict(klass, value)
        if text.startswith(f"List[{name}]") and isinstance(value, list):
            return [_from_dict(klass, v) for v in value]
    return value


_DATACLASSES: Dict[str, Any] = {
    k: v
    for k, v in list(globals().items())
    if dataclasses.is_dataclass(v) and isinstance(v, type)
}


def merge_evidence(items: Iterable[Evidence], limit: int = 8) -> List[Evidence]:
    """De-duplicate evidence, keeping at most ``limit`` entries."""
    seen = set()
    out: List[Evidence] = []
    for ev in items:
        key = (ev.file, ev.line, ev.snippet[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
        if len(out) >= limit:
            break
    return out
