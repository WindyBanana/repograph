# Roadmap

Ordered by how much they would change day-to-day use.

## Multi-repository

Scan several repositories and produce one landscape: which system calls which, which shared
libraries are used where, and which services would be affected by a change. The model already
carries stable ids and external system identities, so the work is a `repograph landscape` command
over several `repograph.json` files plus cross-repo matching of API clients to API providers.

## Incremental scans

Cache per-file analysis keyed by content hash so a re-scan only reprocesses what changed, and
`repograph diff` can show what moved between two scans (new endpoints, new dependencies, new
findings, changed architecture).

## Project rules file

`.repograph.toml` for project-specific conventions: extra ignore patterns, custom component
grouping, additional external-system signatures, severity overrides and finding suppressions with
a reason.

## Deeper analysis

- Call-graph-level flows for Python and TypeScript, not just import-level.
- Database schema extraction (migrations → ER diagram) and ORM model mapping.
- OpenAPI/AsyncAPI ingestion, and generation of an OpenAPI skeleton from detected routes.
- Data-flow tracing for taint-style findings, replacing today's pattern matching for the rules that
  need it.

## More outputs

- Structurizr DSL, draw.io and Excalidraw exports.
- A Word (.docx) report alongside the PDF.
- A single-file HTML bundle that also embeds the PDF and workbook for easy sharing.

## Ecosystem

- A GitHub Action that comments the architecture delta on a pull request.
- A pre-commit hook for the secret and misconfiguration rules only.
- Optional native rendering of Mermaid and PlantUML sources when those tools are installed.
