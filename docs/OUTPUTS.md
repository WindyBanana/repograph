# The output folder

One scan writes one folder. Nothing outside it is touched.

## What gets produced, and what does not

repograph classifies the repository before it renders anything, and skips artifacts that would be
empty or meaningless for that kind of repository. A documentation repository gets no container
diagram; a single library gets no application landscape; a project with no entrypoints gets no
process flows or BPMN.

Every decision is recorded with its reason — in the terminal, in this folder's `README.md`, and
under `not_applicable` in `MANIFEST.json`. That distinction matters in a pipeline: "we looked and
found nothing" is not the same as "we did not look".

Force the full set with `repograph scan . --everything`.

| File | For | What it is |
|---|---|---|
| `index.html` | humans | The main report: overview, architecture views, 2D and 3D dependency graphs, applications, process flows, endpoints, dependencies, vulnerabilities, external systems, infrastructure, files. Self-contained — open it from disk, no server, no network. |
| `AI-REPORT.md` | agents | The same analysis as dense structured text with `path:line` on every claim and an explicit limits section. |
| `report.pdf` | print / review | Cover, executive summary, vector diagrams and paginated tables. |
| `presentation.pptx` | meetings | Cover, summary, diagrams as editable shapes, tables, method and limits. |
| `report.xlsx` | security / planning | Sheets: Summary, Findings (severity-coloured), Dependencies, Endpoints, External systems, Applications, Components, Dependency graph, Infrastructure, Configuration, Files. |
| `BUSINESS-OVERVIEW.md` | non-technical readers | What the software is for, who uses it, what it depends on and what could hurt — in plain language, no jargon. |
| `report.md` | wikis / PRs | Markdown with embedded Mermaid — renders on GitHub. |
| `repograph.json` | tooling | The complete model. Feed it back with `repograph render`. |
| `MANIFEST.json` | pipelines | Everything written plus headline numbers, easy to assert on in CI. |
| `sbom.cdx.json` / `sbom.spdx.json` | compliance | CycloneDX 1.5 and SPDX 2.3, including vulnerabilities when `--online` was used. |
| `data/*.csv` | spreadsheets, diffing | findings, dependencies, endpoints, external_systems, applications, components, edges, files, symbols, environment_variables. |
| `AGENT-INSTRUCTIONS.md` | your AI agent | The prompt for the optional enrichment pass. |
| `agent/enrichment-request.json` | your AI agent | The open questions, each with the files worth reading. |
| `agent/enrichment.schema.json` | your AI agent | The shape of a valid answer; `enrichment.example.json` is a filled-in example. |
| `diagrams/*.svg` | anywhere | Rendered diagrams. |
| `diagrams/mermaid/*.mmd` | docs, chat, AI | Mermaid sources: C4, flowcharts, sequence diagrams, mindmap, pies. |
| `diagrams/plantuml/*.puml` | Confluence, IDEs | C4-PlantUML, component and ArchiMate views, activity diagrams. |
| `diagrams/dot/*.dot` | Graphviz | `dot -Tsvg diagrams/dot/components.dot -o components.svg` |
| `diagrams/bpmn/*.bpmn` | process tools | BPMN 2.0 **with layout** — opens positioned in bpmn.io, Camunda Modeler or Signavio. |
| `models/archimate.xml` | Archi | ArchiMate 3.1 Open Exchange: business, application and technology layers with relationships. |

## Diagram catalogue

| Name | Level | Shows |
|---|---|---|
| `c4-context` | C4 L1 | The system, its users and every external system it depends on |
| `c4-container` | C4 L2 | Applications, their technology and the stores they use |
| `components-<app>` | C4 L3 | Inside one application |
| `application-landscape` | — | Applications as containers with their components inside |
| `dependency-layers` | — | Components stacked by dependency depth (the de facto layering) |
| `dependency-graph` | — | Force-directed view of every component |
| `external-systems` | — | Every external dependency by category |
| `deployment` | — | Compose services and Kubernetes workloads |
| `flow-<id>` | — | One reconstructed process, with swimlanes and decisions |

## Choosing formats

```bash
repograph scan . --format html                 # just the interactive report
repograph scan . --format json,csv             # data only, for a pipeline
repograph scan . --format pdf,pptx,xlsx        # the meeting pack
repograph scan . --format ai,markdown,mermaid  # documentation and agent input
```

## In CI

```yaml
- run: ./bin/repograph scan . -o repograph-out --online --format json,csv,html,sbom
- run: |
    python - <<'PY'
    import json, sys
    manifest = json.load(open("repograph-out/MANIFEST.json"))
    findings = manifest["summary"]["findings"]
    if findings.get("critical"):
        sys.exit(f"{findings['critical']} critical finding(s)")
    PY
- uses: actions/upload-artifact@v4
  with: { name: repograph, path: repograph-out }
```
