"""Follow-up questions: put the scan in front of an agent and ask it something.

The report answers "what is here". This builds the prompt for everything after
that — "where would I add X", "what breaks if Y goes down", "help me plan Z" —
so the agent starts from the map instead of grepping its way back to it.
"""

from __future__ import annotations

import os
from typing import List

from .model import ScanResult
from .util import truncate


def suggestions(result: ScanResult, limit: int = 10) -> List[str]:
    """Questions worth asking about *this* repository, derived from the scan."""
    out: List[str] = []
    metrics = result.metrics
    summary = result.summary or {}
    business = result.business or {}

    top = (summary.get("top_components") or [])
    stores = [s for s in result.external_systems
              if s.kind in ("database", "cache", "storage", "search")]
    shared = [s for s in result.external_systems if len(s.apps) > 1]
    capabilities = [c.get("title") for c in (business.get("capabilities") or [])
                    if c.get("title") not in ("Health and monitoring", "Background work")]
    critical = [f for f in result.findings if f.severity in ("critical", "high")]

    if capabilities:
        out.append(f"Where would I add a new operation on {str(capabilities[0]).lower()}, and "
                   f"what else would I have to change?")
    if shared:
        out.append(f"What would break if {shared[0].name} were unavailable, and how would the "
                   f"system behave while it was down?")
    elif stores:
        out.append(f"What would break if {stores[0].name} were unavailable?")
    if critical:
        out.append(f"Give me a fix plan for the {len(critical)} highest severity findings, "
                   f"ordered by risk and effort.")
    if top:
        out.append(f"If I changed {top[0]['name']}, what else would I have to test?")
    if metrics.cycles:
        out.append("How would I break the circular dependencies without a large refactor?")
    if metrics.test_files == 0:
        out.append("Where should the first tests go to get the most safety for the least work?")
    if metrics.apps > 1:
        out.append("Which of these applications could be extracted or retired first, and why?")
    if result.endpoints:
        out.append("Is the API surface consistent? Point out endpoints that break the pattern.")
    out.append("Explain this repository to a new engineer joining next week.")
    out.append("What would you build next here, and what would you leave alone?")
    return out[:limit]


def build_prompt(result: ScanResult, question: str, output_dir: str, repo_root: str) -> str:
    """The prompt handed to an agent for a follow-up question."""
    try:
        rel_out = os.path.relpath(output_dir, repo_root)
        if rel_out.startswith(".."):
            rel_out = output_dir
    except ValueError:
        rel_out = output_dir

    business = result.business or {}
    metrics = result.metrics
    apps = ", ".join(f"{a.name} ({a.kind})" for a in result.apps[:8]) or "none detected"
    stores = ", ".join(s.name for s in result.external_systems
                       if s.kind in ("database", "cache", "storage", "search")) or "none detected"
    integrations = ", ".join(s.name for s in result.external_systems
                             if s.kind not in ("database", "cache", "storage", "search")) or "none"
    findings = ", ".join(f"{k}: {v}" for k, v in metrics.findings_by_severity.items()) or "none"
    reviewed = ""
    if result.ai.present:
        reviewed = (f"\nAn agent has already reviewed this scan ({result.ai.provenance.tool}); its "
                    f"summaries and finding assessments are in the report, marked as model output.")

    return f"""# Question about {result.meta.repo_name}

{question}

## Before you answer

This repository has already been mapped. Do not re-derive it — read
`{rel_out}/AI-REPORT.md` first. It is a generated, verified inventory with `path:line` citations
covering the applications, the dependency graph, every endpoint, the external systems, the
dependencies and the findings.{reviewed}

The one-paragraph version:

- **What it is:** {truncate(str(business.get('what_it_is', '')), 400)}
- **Applications:** {apps}
- **Size:** {metrics.scanned_files} files, {metrics.loc:,} lines, {metrics.components} components
- **Entrypoints:** {metrics.endpoints}
- **Data stores:** {stores}
- **Integrations:** {integrations}
- **Findings:** {findings}

Useful files beside the report: `{rel_out}/repograph.json` (the full model, machine readable),
`{rel_out}/BUSINESS-OVERVIEW.md` (the plain-language version),
`{rel_out}/diagrams/mermaid/` (every diagram as Mermaid source),
`{rel_out}/data/*.csv` (endpoints, dependencies, findings, components as tables).

## How to answer

1. Start from the report. Open source files only where the question genuinely needs them.
2. Cite `path:line` for anything you assert about this code.
3. Say plainly when the answer is not determinable from the code, rather than guessing.
4. If the question asks for a change, name the files you would touch and what would have to be
   tested, before writing any code.
5. Keep it short enough to read in one sitting. Depth in the detail, not in the preamble.
"""


def prompt_path(output_dir: str) -> str:
    return os.path.join(output_dir, "agent", "question.md")
