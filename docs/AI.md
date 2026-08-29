# AI: optional, and on your terms

repograph produces its entire report without a model. That is the point — facts about a codebase
should be reproducible, checkable and free. But there is a real ceiling to what static analysis
can say, and this document is about what sits above it.

## The line

| The scan can tell you | Only judgement can tell you |
|---|---|
| These 4 applications exist, in these languages | Which one is the heart of the product |
| This module is imported by 31 others | Whether that coupling is a problem |
| `execute("… %s" % name)` at `db.py:14` | Whether `name` is attacker-controlled here |
| This service talks to Stripe and Kafka | That payment is taken before the order is saved |
| These 6 endpoints exist | What the business process behind them is |
| This component is called `utils` | What is actually in it |

Everything on the left is measured. Everything on the right is an opinion — a useful one, worth
having, and worth labelling as such.

## Why "bring your own CLI", not "bring your own key"

An earlier design would have had repograph call an LLM API directly with a key you paste in. We
did not do that, deliberately:

- **Nothing to host.** There is no service, no proxy, no key vault, no bill. repograph stays a
  script you run.
- **You already pay for an agent.** Claude Code, Codex CLI, Gemini CLI, Aider — whichever you
  use, it is already authenticated and already allowed to read this repository.
- **The agent is better placed than we are.** It has file access, a tool loop and its own context
  management. A single API call from inside repograph would have to re-invent all of that badly.
- **Your code does not pass through us.** repograph never opens a network connection except the
  optional OSV lookup, which sends package names and versions only. What your agent sends is
  between you and your agent.
- **Model churn is not our problem.** New models and new CLIs arrive constantly. A file-based
  contract outlives all of them.

If you *do* want a direct API integration — for a CI job with no agent CLI available, say — the
extension point already exists: anything that can write a valid `enrichment.json` participates.
The contract is the integration surface, not our HTTP client.

## The loop

```bash
repograph scan .                  # 1. facts, no model involved
repograph agent repograph-out     # 2. prints the exact command for your agent
#    …the agent reads the report, answers the open questions, writes enrichment.json
repograph enrich repograph-out    # 3. validate, merge, re-render everything
```

Step 2 also writes the pack the agent works from:

```
repograph-out/
├── AGENT-INSTRUCTIONS.md          the prompt: what to do, what not to do, the rules
└── agent/
    ├── enrichment-request.json    the open questions, each with the files worth reading
    ├── enrichment.schema.json     the shape of a valid answer
    ├── enrichment.example.json    a filled-in example
    └── enrichment.json            ← what the agent writes
```

You can also skip `repograph agent` entirely and tell your agent, in its own session:

> Follow `repograph-out/AGENT-INSTRUCTIONS.md`.

## Where the model's words appear

Not as a wall of text at the end. The agent's contributions are threaded into the places they
help, each one labelled:

| Where | What the model adds |
|---|---|
| Overview | a plain-language summary of each application, next to the machine-derived one |
| Architecture | a one-sentence caption per diagram, under the computed "what this shows / notice" line |
| Process flows | a narrative for each reconstructed process |
| Vulnerabilities | an assessment column: true positive, false positive or needs review, with reasoning |
| Model contributions | the ranked risks and observations, with their evidence |

The scan's own captions stay either way: every diagram already carries a computed description and
a "notice" line derived from the graph (the component with the highest fan-in, whether the layering
has cycles, which external system is shared between applications).

## What the agent is asked

The questions are generated from the gaps the scanner *knows* it has, ranked so the valuable ones
come first:

1. Findings with low or medium confidence — "is this real in context?"
2. Applications with no description, or whose README may be stale
3. Components whose names say nothing (`utils`, `common`, `core`)
4. Reconstructed process flows — "what does this mean in business terms?"
5. External systems detected from a single reference — real integration, or a leftover mention?
6. Unresolved imports — dynamic loading the scanner could not follow
7. Repository-level: the top three risks, the onboarding traps, the blast radius of each
   dependency

Each question carries the specific files worth opening, so the agent reads a handful of files
rather than the whole repository. That keeps the run cheap and the answers grounded.

## What comes back, and what is refused

The agent writes typed answers. `repograph enrich` validates every one of them before it believes
anything:

| Rule | Why |
|---|---|
| Ids must exist in this scan | Stops answers about files or components that are not there |
| A risk must cite `path:line` | An unsupported risk is an opinion about nothing |
| A finding assessment must be `true_positive`, `false_positive` or `needs_review`, with reasoning | Makes disagreement explicit and reviewable |
| Evidence must look like a path | Filters "trust me" and marketing links |
| Unknown target ids are stripped, the insight survives | One bad reference should not lose a good observation |

Everything rejected is reported — in the terminal, in the HTML report and in `AI-REPORT.md` —
rather than silently dropped. You always see what the model tried to add.

## How it is presented

Merged contributions never mix with scan facts:

- HTML report: an **AI generated** badge on the model's summaries, a "Model contributions"
  section, and an "AI assessment" column in the findings table.
- `AI-REPORT.md`: a separate, explicitly fenced section headed *"not part of the deterministic
  scan"*.
- Markdown and PDF: their own labelled section.
- `repograph.json`: everything lives under `ai`, plus `ai_summary` / `ai_assessment` fields, so
  downstream tooling can include or ignore it with one check.

Delete `agent/enrichment.json` and re-run `repograph render` and you are back to a pure
machine-derived report.

## Asking follow-up questions

Enrichment answers a fixed list. `repograph ask` is for everything after that:

```bash
repograph ask --suggest                       # questions derived from this scan
repograph ask "where would I add refunds?"    # builds a prompt with the report as context
repograph ask "..." --run claude              # and runs it
```

The generated prompt gives the agent the headline facts inline, points it at `AI-REPORT.md`,
`repograph.json` and the CSVs, and tells it to cite `path:line` and to say when something is not
determinable. It is written to `agent/question.md`, so it also works with tools that take a file.

## Cost and repeatability

A run answers ~25-40 questions against a report that is already written, opening perhaps a dozen
files. That is a small agent session, not a codebase read. Re-scanning does not require re-running
the agent: `enrichment.json` is keyed by stable ids, so `repograph enrich` re-applies it after a
new scan, and anything that no longer matches is reported as rejected — which is itself a signal
that the architecture moved.

## Answering the obvious question

**Could repograph do all this without AI?** It already does; the model adds judgement, not facts.

**Should the AI part be required?** No. A tool that needs a model to tell you which files exist is
a tool you cannot trust in CI, cannot run offline, and cannot check.
