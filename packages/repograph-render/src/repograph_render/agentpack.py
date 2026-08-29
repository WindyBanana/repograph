"""The agent pack: everything a coding agent needs to enrich a scan.

The scan is the source of truth for facts. The agent's job is the part a scanner
cannot do — intent, judgement, business meaning — written back in a typed form
that repograph validates before it believes any of it.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Dict, List, Optional, Sequence, Tuple

from repograph_core import enrich
from repograph_core.model import ScanResult

# tool key -> (display name, executable, how to run it with a prompt file)
AGENT_TOOLS: Dict[str, Tuple[str, str, str]] = {
    "claude": ("Claude Code", "claude", 'claude -p "$(cat {instructions})"'),
    "codex": ("OpenAI Codex CLI", "codex", 'codex exec "$(cat {instructions})"'),
    "gemini": ("Gemini CLI", "gemini", 'gemini -p "$(cat {instructions})"'),
    "aider": ("Aider", "aider", 'aider --message "$(cat {instructions})"'),
    "cursor": ("Cursor CLI", "cursor-agent", 'cursor-agent -p "$(cat {instructions})"'),
    "opencode": ("OpenCode", "opencode", 'opencode run "$(cat {instructions})"'),
    "amp": ("Amp", "amp", 'amp -x "$(cat {instructions})"'),
    "qwen": ("Qwen Code", "qwen", 'qwen -p "$(cat {instructions})"'),
}


def detect_tools() -> List[Tuple[str, str, str]]:
    """Which agent CLIs are actually installed, as (key, display name, path)."""
    found = []
    for key, (label, executable, _) in AGENT_TOOLS.items():
        path = shutil.which(executable)
        if path:
            found.append((key, label, path))
    return found


def display_path(path: str, base: str) -> str:
    """Relative when that is shorter and stays inside the base, absolute otherwise."""
    try:
        relative = os.path.relpath(path, base)
    except ValueError:
        return path
    return path if relative.startswith("..") else relative


def command_for(key: str, output_dir: str, repo_root: str) -> str:
    label_command = AGENT_TOOLS.get(key, AGENT_TOOLS["claude"])[2]
    instructions = display_path(os.path.join(output_dir, "AGENT-INSTRUCTIONS.md"), repo_root)
    return label_command.format(instructions=instructions)


def write(result: ScanResult, output_dir: str, repo_root: str) -> List[str]:
    """Write the agent pack; returns the paths written."""
    agent_dir = os.path.join(output_dir, "agent")
    os.makedirs(agent_dir, exist_ok=True)
    written: List[str] = []

    def emit(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        written.append(path)

    request = enrich.build_request(result)
    emit(os.path.join(agent_dir, "enrichment-request.json"), json.dumps(request, indent=2))
    emit(os.path.join(agent_dir, "enrichment.schema.json"),
         json.dumps(enrich.response_schema(), indent=2))
    emit(os.path.join(agent_dir, "enrichment.example.json"),
         json.dumps(enrich.example_enrichment(), indent=2))
    emit(os.path.join(output_dir, "AGENT-INSTRUCTIONS.md"),
         instructions(result, request, output_dir, repo_root))
    return written


def instructions(result: ScanResult, request: Dict[str, object], output_dir: str,
                 repo_root: str) -> str:
    rel_out = display_path(output_dir, repo_root)
    questions = request.get("questions") or []
    top = "\n".join(
        f"{index + 1}. **[{q['id']}]** {q['question']}"
        + (f"\n   - why: {q['why_it_matters']}" if q.get("why_it_matters") else "")
        + (f"\n   - look at: {', '.join('`' + p + '`' for p in q['look_at'])}"
           if q.get("look_at") else "")
        + (f"\n   - the scan currently says: _{q['current_answer']}_"
           if q.get("current_answer") else "")
        for index, q in enumerate(questions)  # type: ignore[index]
    )
    counts = result.metrics.findings_by_severity
    severity_line = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "none"

    return f"""# Enrich this repository analysis

You are working in **{result.meta.repo_name}**. A deterministic scan of this repository has
already been produced by repograph and lives in `{rel_out}/`. Your job is **not** to redo it.

## What already exists (do not repeat it)

`{rel_out}/AI-REPORT.md` contains, as verified facts with `path:line` citations:

- {result.metrics.apps} application(s) and {result.metrics.components} components, with
  languages, frameworks and entrypoints
- the component and application dependency graph, its cycles and layering
- {result.metrics.endpoints} endpoints (HTTP, GraphQL, gRPC, events, CLI)
- {result.metrics.external_systems} external systems (databases, queues, storage, APIs)
- {result.metrics.dependencies} dependencies, including undeclared and unused ones
- {sum(counts.values())} findings ({severity_line})
- infrastructure: containers, orchestration, IaC and CI

**Read that file first.** It is dense and complete; it exists so you do not have to read the
whole codebase.

## What you are adding

The things static analysis cannot produce: intent, meaning, judgement and priority.

## How to work

1. Read `{rel_out}/AI-REPORT.md`.
2. Read `{rel_out}/agent/enrichment-request.json` — the open questions, each with the files
   worth opening.
3. Open **only** the source files a question actually needs. Prefer the `look_at` list. This is
   a review, not a re-read of the repository.
4. Write your answers to `{rel_out}/agent/enrichment.json`, following
   `{rel_out}/agent/enrichment.schema.json`. There is a filled-in example beside it in
   `enrichment.example.json`.
5. Run `repograph enrich {rel_out}` (or `./bin/repograph enrich {rel_out}`) to validate and merge
   your answers into every report.

## Rules

- **Cite or stay silent.** Every summary, risk and assessment needs `path:line` evidence from
  this repository. Anything without evidence is rejected on merge.
- **Do not guess.** If a question cannot be answered from the code, put its id in `unanswered`.
  That is a useful answer; an invented one is not.
- **Use the ids you were given.** `enrichment-request.json` contains an `ids` map for
  applications, components, flows and findings. Ids that do not appear there are rejected.
- **Be short.** Two or three sentences per summary. The reports have limited room and readers
  have limited patience.
- **Do not modify the repository.** Write only inside `{rel_out}/agent/`.
- **Judge the findings honestly.** `false_positive` with a reason is more valuable than agreeing
  with the scanner. Say `needs_review` when you are unsure.
- Prefer business language over restating the code: "takes payment before persisting the order,
  so a crash loses the charge" beats "calls stripe.Charge.create then repository.save".

## Open questions

{top}

## When you are done

```bash
repograph enrich {rel_out}
```

That validates your file, merges what passes, reports what it rejected and why, and re-renders
the HTML report, the PDF, the deck, the workbook and `AI-REPORT.md` with your contributions
clearly labelled as model-generated.
"""


MARKER_START = "<!-- repograph:start -->"
MARKER_END = "<!-- repograph:end -->"


def agents_md_block(result: ScanResult, output_dir: str, repo_root: str) -> str:
    """A short pointer for agent files (AGENTS.md, CLAUDE.md) so any agent opening
    this repository finds the analysis instead of re-deriving it."""
    rel_out = display_path(output_dir, repo_root)
    metrics = result.metrics
    return f"""{MARKER_START}
## Repository analysis (generated by repograph)

Before exploring this codebase, read `{rel_out}/AI-REPORT.md`. It is a generated, machine-derived
map of the repository and it is cheaper and more reliable than reading files at random. It covers:

- the {metrics.apps} application(s) and {metrics.components} components, with languages,
  frameworks, entrypoints and architecture style
- the dependency graph between them, its cycles and layering
- all {metrics.endpoints} endpoints (HTTP, GraphQL, gRPC, events, scheduled jobs, CLI)
- the {metrics.external_systems} external systems this code talks to, each with file:line evidence
- {metrics.dependencies} dependencies, including undeclared imports and unused declarations
- {sum(metrics.findings_by_severity.values())} security and quality findings with locations
- infrastructure: containers, orchestration, IaC and CI

Diagrams (C4, flows, dependency graph) are in `{rel_out}/diagrams/mermaid/` as Mermaid sources.
The complete model is `{rel_out}/repograph.json`.

Refresh it with `repograph scan .`, and if you are asked to review the architecture, follow
`{rel_out}/AGENT-INSTRUCTIONS.md` and write your findings back with `repograph enrich {rel_out}`.
{MARKER_END}"""


def write_agents_md(result: ScanResult, output_dir: str, repo_root: str,
                    filename: str = "AGENTS.md") -> Tuple[str, str]:
    """Add or refresh the repograph block in an agent instruction file.

    Returns (path, action) where action is created, updated or unchanged. Only the
    block between the markers is ever touched.
    """
    path = os.path.join(repo_root, filename)
    block = agents_md_block(result, output_dir, repo_root)
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()

    if MARKER_START in existing and MARKER_END in existing:
        head, _, rest = existing.partition(MARKER_START)
        _, _, tail = rest.partition(MARKER_END)
        updated = head + block + tail
        action = "unchanged" if updated == existing else "updated"
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block + "\n"
        action = "updated"
    else:
        updated = f"# Agent notes for {result.meta.repo_name}\n\n" + block + "\n"
        action = "created"

    if action != "unchanged":
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(updated)
    return path, action


def panel_html(result: ScanResult, output_dir: str, repo_root: str,
               tools: Optional[Sequence[Tuple[str, str, str]]] = None) -> str:
    """The 'enrich this with an agent' panel shown in the HTML report."""
    import html

    def e(text: object) -> str:
        return html.escape(str(text), quote=True)

    tools = list(tools if tools is not None else detect_tools())
    rel_out = display_path(output_dir, repo_root)

    if tools:
        rows = "".join(
            f"<li><b>{e(label)}</b> — <code>{e(command_for(key, output_dir, repo_root))}</code></li>"
            for key, label, _path in tools
        )
        detected = f"<p class='small muted'>Detected on this machine:</p><ul class='small'>{rows}</ul>"
    else:
        detected = (
            "<p class='small muted'>No agent CLI was detected on the machine that ran the scan. "
            "Install one (Claude Code, Codex CLI, Gemini CLI, Aider…) or open this folder in "
            "your agent of choice and point it at <code>AGENT-INSTRUCTIONS.md</code>.</p>"
        )

    return f"""<div class="panel">
<h3 style="color:var(--ink);text-transform:none;font-size:15px">Optional: enrich this with an AI agent</h3>
<p class="small">Everything above was produced without a model. If you want intent, business
meaning and a judgement on each finding, open a terminal in
<code>{e(repo_root)}</code> and run any coding agent against
<code>{e(rel_out)}/AGENT-INSTRUCTIONS.md</code>. The agent reads the report rather than the whole
codebase, answers a fixed list of questions, and writes
<code>{e(rel_out)}/agent/enrichment.json</code>. Then run
<code>repograph enrich {e(rel_out)}</code> and these reports regenerate with its contributions
labelled separately from the scan's facts.</p>
{detected}
<p class="small muted">Nothing leaves your machine unless the agent you choose sends it. repograph
itself never calls a model.</p>
</div>"""
