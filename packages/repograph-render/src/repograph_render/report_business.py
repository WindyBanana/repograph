"""The business-facing document: what this software is, in plain language."""

from __future__ import annotations

from typing import Dict, List, Sequence

from repograph_core.model import ScanResult


def _points(items: Sequence[Dict[str, object]], with_detail: bool = True) -> str:
    if not items:
        return "_Nothing to report here._\n"
    lines: List[str] = []
    for point in items:
        lines.append(f"- **{point.get('title', '')}** — {point.get('plain', '')}")
        if with_detail and point.get("detail"):
            lines.append(f"  <sub>{point['detail']}</sub>")
        evidence = point.get("evidence") or []
        if with_detail and evidence:
            lines.append("  <sub>" + " · ".join(f"`{x}`" for x in evidence) + "</sub>")
    return "\n".join(lines) + "\n"


def render(result: ScanResult) -> str:
    business = result.business or {}
    metrics = result.metrics
    reviewed = " Reviewed by an AI agent; its contributions are marked in the full report." \
        if result.ai.present else ""

    return f"""# {business.get('headline', result.meta.repo_name)}

_A plain-language summary of what this software is, produced by reading the code itself on
{result.meta.generated_at[:10]}.{reviewed}_

{business.get('what_it_is', '')}

| | |
|---|---|
| Separate pieces of software | {metrics.apps} |
| Ways in (screens, APIs, jobs, commands) | {metrics.endpoints} |
| Other systems it needs | {metrics.external_systems} |
| Issues found by automated checks | {sum(metrics.findings_by_severity.values())} |
| Size | {metrics.loc:,} lines across {metrics.scanned_files} files |

## What it lets people do

{_points(business.get('capabilities'))}

## Who uses it

{_points(business.get('users'))}

## Where its data lives

{_points(business.get('data'))}

## What it depends on

If one of these is unavailable, the part of the service that uses it stops working.

{_points(business.get('dependencies'))}

## How it runs

{_points(business.get('operations'))}

## What could hurt

{_points(business.get('risks'))}

## How healthy it looks

{_points(business.get('health'))}

## What this report cannot tell you

{chr(10).join('- ' + str(u) for u in (business.get('unknowns') or [])) or '- Nothing of note.'}

---

_{business.get('audience_note', '')} The technical views — architecture diagrams, dependency
graphs, API inventory and the full findings list — are in `index.html` and `report.pdf` beside
this file._
"""
