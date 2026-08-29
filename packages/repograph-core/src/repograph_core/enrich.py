"""The optional AI layer.

repograph never needs a model to produce its facts. What a model *can* add is
judgement: what a component is for, whether a finding matters in context, what a
process means in business terms. This module defines that contract in both
directions:

* :func:`build_request` turns the gaps the scanner knows it has into a list of
  specific, answerable questions, each pointing at the files worth reading.
* :func:`load_enrichment` and :func:`apply` validate an agent's answers and merge
  them into the model, keeping them in their own branch so machine-checked facts
  and model judgement are never mixed up.

Anything the agent returns that does not match a known id, or that is missing
evidence, is rejected and reported rather than quietly accepted.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from .model import AiEnrichment, AiInsight, AiProvenance, ScanResult
from .util import truncate

REQUEST_VERSION = "1"
ENRICHMENT_SCHEMA = "repograph-enrichment/1"

_GENERIC_NAMES = {
    "utils", "util", "common", "core", "shared", "lib", "libs", "helpers", "misc",
    "base", "internal", "src", "app", "main", "root", "(other)",
}
_VALID_ASSESSMENTS = {"true_positive", "false_positive", "needs_review"}
_VALID_KINDS = {"risk", "observation", "recommendation", "answer"}
_VALID_SEVERITY = {"critical", "high", "medium", "low", "info"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


# --------------------------------------------------------------- the request

def _files_for_app(result: ScanResult, app_id: str, limit: int = 6) -> List[str]:
    """The files most worth reading to understand an application."""
    entry_files = [e.file for e in result.endpoints if e.app == app_id and e.file]
    app = result.app_by_id(app_id)
    ranked = sorted(
        (f for f in result.files if f.app == app_id and f.kind == "source"),
        key=lambda f: -f.loc,
    )
    picks: List[str] = []
    for candidate in entry_files + [f.path for f in ranked]:
        if candidate not in picks:
            picks.append(candidate)
        if len(picks) >= limit:
            break
    if app is not None:
        for manifest in app.manifests:
            if manifest not in picks:
                picks.append(manifest)
    return picks


def _diagram_applies(result: ScanResult, name: str) -> bool:
    artifacts = (result.profile or {}).get("artifacts") or {}
    entry = artifacts.get(name)
    return True if not isinstance(entry, dict) else bool(entry.get("include", True))


def build_request(result: ScanResult, max_questions: int = 40) -> Dict[str, Any]:
    """The open questions this scan could not answer on its own."""
    questions: List[Dict[str, Any]] = []

    def ask(qid: str, kind: str, target: str, question: str, why: str,
            look_at: Sequence[str], current: str = "", priority: int = 5) -> None:
        questions.append({
            "id": qid,
            "kind": kind,
            "target": target,
            "question": question,
            "why_it_matters": why,
            "look_at": [p for p in look_at if p][:8],
            "current_answer": truncate(current, 240) if current else "",
            "priority": priority,
        })

    for app in result.apps:
        documented = bool(app.description and app.description != app.purpose)
        ask(f"app-summary-{app.id}", "application", app.id,
            f"In two or three sentences, what is '{app.name}' for, in business terms?",
            "The scan can name the technology and the domain nouns, but not the intent.",
            _files_for_app(result, app.id),
            current=app.description or app.purpose,
            priority=2 if not documented else 5)
        ask(f"app-responsibilities-{app.id}", "application", app.id,
            f"List the three to five things '{app.name}' is responsible for.",
            "Responsibilities are what a newcomer needs before touching the code.",
            _files_for_app(result, app.id, limit=4),
            priority=3)

    interesting = [
        c for c in result.components
        if c.name.split("/")[-1].lower() in _GENERIC_NAMES or c.files >= 8
    ]
    for component in sorted(interesting, key=lambda c: -c.files)[:10]:
        app = result.app_by_id(component.app)
        ask(f"component-{component.id}", "component", component.id,
            f"What does the component '{component.name}' in "
            f"{app.name if app else 'this repository'} actually do?",
            "Directory names are not always honest about their contents.",
            [f.path for f in sorted((f for f in result.files if f.component == component.id),
                                    key=lambda f: -f.loc)[:5]],
            current=component.description,
            priority=4)

    for flow in result.flows[:6]:
        if flow.id.endswith("overview"):
            continue
        ask(f"flow-{flow.id}", "flow", flow.id,
            f"Describe the '{flow.name}' process as a business process: what triggers it, "
            f"what it decides, what it changes and what can go wrong.",
            "The scan reconstructs the code path; it cannot tell you what the process means.",
            [flow.entrypoint] + [n.file for n in flow.nodes if n.file][:4],
            current=flow.description,
            priority=4)

    uncertain = [f for f in result.findings
                 if f.confidence in ("low", "medium") and f.category in ("code", "secret", "config")]
    for finding in sorted(uncertain, key=lambda f: (f.severity, f.file))[:12]:
        ask(f"finding-{finding.id}", "finding", finding.id,
            f"Is this a real problem in context? {finding.title} at "
            f"{finding.file}:{finding.line}",
            "Pattern matching cannot see the surrounding control flow or trust boundary.",
            [finding.file],
            current=f"{finding.severity} / confidence {finding.confidence}: {finding.snippet}",
            priority=1 if finding.severity in ("critical", "high") else 3)

    thin = [s for s in result.external_systems if len(s.evidence) <= 1]
    if thin:
        ask("systems-thin-evidence", "external_systems", "",
            "Which of these detected external systems are genuinely used, and which are "
            "incidental mentions? " + ", ".join(s.name for s in thin[:12]),
            "A single reference may be a real integration or a leftover comment.",
            [ev.file for s in thin[:6] for ev in s.evidence[:1]],
            priority=3)

    unresolved = int(result.summary.get("unresolved_imports", 0) or 0)
    if unresolved:
        ask("unresolved-imports", "graph", "",
            f"{unresolved} import statements could not be resolved to a file or package. "
            f"Are there dynamic imports, generated code or path aliases the scanner missed?",
            "Unresolved imports mean missing edges in every dependency view.",
            [], priority=3)

    for name in ("c4-context", "c4-container", "dependency-graph", "application-landscape",
                 "external-systems", "deployment"):
        if not _diagram_applies(result, name):
            continue
        ask(f"diagram-{name}", "diagram", name,
            f"In one sentence a non-engineer could follow, what does the '{name}' diagram of this "
            f"system show, and what should the reader take away from it?",
            "A diagram without a caption makes the reader guess what they are looking at.",
            ["AI-REPORT.md"], priority=4)

    ask("repo-risks", "repository", "",
        "What are the three biggest architectural or operational risks in this repository, "
        "and what would you fix first?",
        "A ranked opinion is the thing a scanner cannot produce.",
        ["AI-REPORT.md"], priority=2)
    ask("repo-onboarding", "repository", "",
        "What conventions would a new engineer have to learn that are not obvious from the "
        "structure (naming, layering rules, generated code, deployment quirks)?",
        "Tacit knowledge is invisible to static analysis.",
        ["AI-REPORT.md"], priority=3)
    ask("repo-single-points", "repository", "",
        "If each external system went down in turn, what would break, and is anything a single "
        "point of failure?",
        "Blast radius follows from the graph but needs judgement to state.",
        ["AI-REPORT.md"], priority=3)

    questions.sort(key=lambda q: (q["priority"], q["id"]))
    questions = questions[:max_questions]

    return {
        "schema": f"repograph-request/{REQUEST_VERSION}",
        "repository": result.meta.repo_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scan": {
            "applications": result.metrics.apps,
            "components": result.metrics.components,
            "files": result.metrics.scanned_files,
            "loc": result.metrics.loc,
            "endpoints": result.metrics.endpoints,
            "findings": result.metrics.findings_by_severity,
        },
        "how_to_answer": (
            "Read AI-REPORT.md first — it already contains the inventory, the graph, the API "
            "surface and the findings. Only open source files when a question needs them, and "
            "prefer the files listed in 'look_at'. Answer with facts you can cite as path:line; "
            "if you cannot answer a question from the code, list its id in 'unanswered' rather "
            "than guessing. Write the result to agent/enrichment.json following "
            "agent/enrichment.schema.json."
        ),
        "questions": questions,
        "ids": {
            "applications": {a.id: a.name for a in result.apps},
            "components": {c.id: c.name for c in result.components},
            "flows": {f.id: f.name for f in result.flows},
            "findings": {f.id: f.title for f in result.findings},
            "diagrams": [name for name in
                         ("c4-context", "c4-container", "dependency-graph",
                          "application-landscape", "external-systems", "deployment")
                         if _diagram_applies(result, name)],
        },
    }


def response_schema() -> Dict[str, Any]:
    """A JSON Schema for what an agent should write back."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "repograph enrichment",
        "type": "object",
        "required": ["schema", "generated_by"],
        "properties": {
            "schema": {"const": ENRICHMENT_SCHEMA},
            "generated_by": {
                "type": "object",
                "required": ["tool"],
                "properties": {
                    "tool": {"type": "string",
                             "description": "claude-code, codex, gemini-cli, aider, manual, ..."},
                    "model": {"type": "string"},
                    "generated_at": {"type": "string", "description": "ISO 8601"},
                    "notes": {"type": "string"},
                },
            },
            "applications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "summary"],
                    "properties": {
                        "id": {"type": "string", "description": "must match an id from ids.applications"},
                        "summary": {"type": "string", "maxLength": 1200},
                        "responsibilities": {"type": "array", "items": {"type": "string"}},
                        "evidence": {"type": "array", "items": {"type": "string"},
                                     "description": "references supporting the summary: "
                                                    "path, path:line, path:start-end or "
                                                    "path:12,48"},
                    },
                },
            },
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "summary"],
                    "properties": {
                        "id": {"type": "string"},
                        "summary": {"type": "string", "maxLength": 600},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "flows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "narrative"],
                    "properties": {
                        "id": {"type": "string"},
                        "narrative": {"type": "string", "maxLength": 2000},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "assessment", "reasoning"],
                    "properties": {
                        "id": {"type": "string"},
                        "assessment": {"enum": sorted(_VALID_ASSESSMENTS)},
                        "reasoning": {"type": "string", "maxLength": 1200},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "diagrams": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "caption"],
                    "properties": {
                        "id": {"type": "string",
                               "description": "a diagram name from ids.diagrams"},
                        "caption": {"type": "string", "maxLength": 400,
                                    "description": "one sentence a non-engineer could follow"},
                    },
                },
            },
            "insights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "kind"],
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"enum": sorted(_VALID_KINDS)},
                        "title": {"type": "string", "maxLength": 200},
                        "detail": {"type": "string", "maxLength": 2000},
                        "severity": {"enum": sorted(_VALID_SEVERITY)},
                        "confidence": {"enum": sorted(_VALID_CONFIDENCE)},
                        "targets": {"type": "array", "items": {"type": "string"}},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "unanswered": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ids of questions you could not answer from the code",
            },
        },
    }


def example_enrichment() -> Dict[str, Any]:
    return {
        "schema": ENRICHMENT_SCHEMA,
        "generated_by": {"tool": "claude-code", "model": "<model id>",
                         "generated_at": "2026-01-01T12:00:00Z"},
        "applications": [{
            "id": "app-apps-api",
            "summary": "Order intake service for the web shop. Accepts orders from the "
                       "storefront, takes payment, then publishes an event the worker picks up.",
            "responsibilities": ["Validate and persist orders", "Take payment",
                                 "Publish order events"],
            "evidence": ["apps/api/app/routers/orders.py:24",
                         "apps/api/app/services/order_service.py:28"],
        }],
        "findings": [{
            "id": "<finding id from ids.findings>",
            "assessment": "true_positive",
            "reasoning": "The value reaches the query unescaped from a request parameter.",
            "evidence": ["apps/api/app/db.py:14"],
        }],
        "insights": [{
            "kind": "risk",
            "title": "Payment and order persistence are not transactional",
            "detail": "A failure between charging and saving leaves a paid order unrecorded.",
            "severity": "high",
            "confidence": "medium",
            "targets": ["app-apps-api"],
            "evidence": ["apps/api/app/services/order_service.py:30"],
        }],
        "unanswered": [],
    }


# ------------------------------------------------------------- the response

# path, path:line, path:start-end and path:12,48 are all valid citations — a
# reviewer pointing at a block of code should not have to pick one line from it.
_EVIDENCE_RE = re.compile(r"^[\w./\\@+-]+(?::\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)?$")


def _clean_evidence(values: Any, limit: int = 8) -> List[str]:
    if not isinstance(values, list):
        return []
    out = []
    for value in values:
        text = str(value).strip()
        if text and _EVIDENCE_RE.match(text) and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def load_enrichment(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("enrichment file must contain a JSON object")
    return data


def apply(result: ScanResult, data: Dict[str, Any], *, require_evidence: bool = True
          ) -> Tuple[AiEnrichment, List[str]]:
    """Merge an agent's answers into the model, rejecting anything unverifiable."""
    rejected: List[str] = []
    enrichment = AiEnrichment(present=True)

    schema = str(data.get("schema", ""))
    if schema and schema != ENRICHMENT_SCHEMA:
        rejected.append(f"unexpected schema '{schema}' (expected '{ENRICHMENT_SCHEMA}')")

    source = data.get("generated_by") if isinstance(data.get("generated_by"), dict) else {}
    enrichment.provenance = AiProvenance(
        tool=str(source.get("tool", "unknown"))[:60],
        model=str(source.get("model", ""))[:80],
        generated_at=str(source.get("generated_at", ""))[:40]
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        request_version=REQUEST_VERSION,
        notes=truncate(str(source.get("notes", "")), 400),
    )

    answered = 0

    for entry in data.get("applications") or []:
        if not isinstance(entry, dict):
            continue
        app = result.app_by_id(str(entry.get("id", "")))
        summary = truncate(str(entry.get("summary", "")).strip(), 1200)
        if app is None:
            rejected.append(f"application id '{entry.get('id')}' does not exist in this scan")
            continue
        if not summary:
            rejected.append(f"application '{app.name}' had an empty summary")
            continue
        app.ai_summary = summary
        responsibilities = entry.get("responsibilities")
        if isinstance(responsibilities, list):
            app.ai_responsibilities = [truncate(str(r), 200) for r in responsibilities[:8] if str(r).strip()]
        answered += 1

    for entry in data.get("components") or []:
        if not isinstance(entry, dict):
            continue
        component = result.component_by_id(str(entry.get("id", "")))
        summary = truncate(str(entry.get("summary", "")).strip(), 600)
        if component is None:
            rejected.append(f"component id '{entry.get('id')}' does not exist in this scan")
            continue
        if summary:
            component.ai_summary = summary
            answered += 1

    for entry in data.get("flows") or []:
        if not isinstance(entry, dict):
            continue
        flow = result.flow_by_id(str(entry.get("id", "")))
        narrative = truncate(str(entry.get("narrative", "")).strip(), 2000)
        if flow is None:
            rejected.append(f"flow id '{entry.get('id')}' does not exist in this scan")
            continue
        if narrative:
            flow.ai_narrative = narrative
            answered += 1

    for entry in data.get("findings") or []:
        if not isinstance(entry, dict):
            continue
        finding = result.finding_by_id(str(entry.get("id", "")))
        assessment = str(entry.get("assessment", "")).strip().lower()
        reasoning = truncate(str(entry.get("reasoning", "")).strip(), 1200)
        if finding is None:
            rejected.append(f"finding id '{entry.get('id')}' does not exist in this scan")
            continue
        if assessment not in _VALID_ASSESSMENTS:
            rejected.append(f"finding '{finding.id}' had assessment '{assessment}', "
                            f"expected one of {sorted(_VALID_ASSESSMENTS)}")
            continue
        if not reasoning:
            rejected.append(f"finding '{finding.id}' was assessed without reasoning")
            continue
        finding.ai_assessment = assessment
        finding.ai_reasoning = reasoning
        answered += 1

    for index, entry in enumerate(data.get("insights") or []):
        if not isinstance(entry, dict):
            continue
        title = truncate(str(entry.get("title", "")).strip(), 200)
        if not title:
            rejected.append("an insight had no title")
            continue
        evidence = _clean_evidence(entry.get("evidence"))
        kind = str(entry.get("kind", "observation")).lower()
        if kind not in _VALID_KINDS:
            kind = "observation"
        if require_evidence and kind == "risk" and not evidence:
            rejected.append(f"risk '{title}' was dropped: no path:line evidence")
            continue
        severity = str(entry.get("severity", "info")).lower()
        confidence = str(entry.get("confidence", "medium")).lower()
        targets = [str(t) for t in (entry.get("targets") or []) if str(t).strip()][:8]
        known = ({a.id for a in result.apps} | {c.id for c in result.components}
                 | {f.id for f in result.flows} | {f.id for f in result.findings}
                 | {s.id for s in result.external_systems})
        unknown = [t for t in targets if t not in known]
        if unknown:
            rejected.append(f"insight '{title}' referenced unknown id(s): {', '.join(unknown[:3])}")
            targets = [t for t in targets if t in known]
        enrichment.insights.append(AiInsight(
            id=str(entry.get("id") or f"ai-{index + 1}"),
            kind=kind,
            title=title,
            detail=truncate(str(entry.get("detail", "")), 2000),
            severity=severity if severity in _VALID_SEVERITY else "info",
            confidence=confidence if confidence in _VALID_CONFIDENCE else "medium",
            targets=targets,
            evidence=evidence,
        ))
        answered += 1

    for entry in data.get("diagrams") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("id", "")).strip()
        caption = truncate(str(entry.get("caption", "")).strip(), 400)
        if not name or not caption:
            continue
        if not _diagram_applies(result, name):
            rejected.append(f"caption for diagram '{name}', which this scan did not produce")
            continue
        enrichment.diagram_captions[name] = caption
        answered += 1

    unanswered = data.get("unanswered")
    if isinstance(unanswered, list):
        enrichment.unanswered = [str(u)[:120] for u in unanswered[:60]]

    enrichment.answered_questions = answered
    enrichment.rejected = rejected
    result.ai = enrichment
    return enrichment, rejected


def request_path(output_dir: str) -> str:
    return os.path.join(output_dir, "agent", "enrichment-request.json")


def enrichment_path(output_dir: str) -> str:
    return os.path.join(output_dir, "agent", "enrichment.json")
