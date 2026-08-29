# The output folder

One scan writes one folder. Nothing outside it is touched.

| File | For | What it is |
|---|---|---|
| `index.html` | humans | The main report: overview, architecture views, 2D and 3D dependency graphs, applications, process flows, endpoints, dependencies, vulnerabilities, external systems, infrastructure, files. Self-contained — open it from disk, no server, no network. |
| `AI-REPORT.md` | agents | The same analysis as dense structured text with `path:line` on every claim and an explicit limits section. |
| `report.pdf` | print / review | Cover, executive summary, vector diagrams and paginated tables. |
| `presentation.pptx` | meetings | Cover, summary, diagrams as editable shapes, tables, method and limits. |
| `report.xlsx` | security / planning | Sheets: Summary, Findings (severity-coloured), Dependencies, Endpoints, External systems, Applications, Components, Dependency graph, Infrastructure, Configuration, Files. |
| `report.md` | wikis / PRs | Markdown with embedded Mermaid — renders on GitHub. |
| `repograph.json` | tooling | The complete model. Feed it back with `repograph render`. |
| `MANIFEST.json` | pipelines | Everything written plus headline numbers, easy to assert on in CI. |
| `sbom.cdx.json` / `sbom.spdx.json` | compliance | CycloneDX 1.5 and SPDX 2.3, including vulnerabilities when `--online` was used. |
| `data/*.csv` | spreadsheets, diffing | findings, dependencies, endpoints, external_systems, applications, components, edges, files, symbols, environment_variables. |
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
