# How repograph is built

repograph is a small monorepo of four Python packages with **no required third-party
dependencies**. That constraint is deliberate: the tool has to run on any machine with a Python
interpreter, including one with no network access.

```
packages/repograph-core     scanning and analysis          → produces a ScanResult
packages/repograph-render   layout, diagrams and documents → consumes a ScanResult
packages/repograph-cli      argparse CLI + terminal output
packages/repograph-tui      curses UI over a ScanResult
```

## The model is the contract

`repograph_core.model.ScanResult` is a tree of dataclasses that serialises to JSON. Everything the
scanners learn goes in; every renderer reads only from it. That is why `repograph render` can
regenerate every artefact from `repograph.json` without touching the source repository again, and
why adding an output format never requires touching the scanner.

## The scan pipeline

`repograph_core.scan.scan()` runs one pass over the repository:

1. **`walker.py`** — file discovery. Language detection by extension and filename, classification
   into source/test/config/infra/docs/build/data, `.gitignore` support, vendored-directory and
   generated-file exclusion.
2. **`languages/`** — one analyzer per language family. Python uses the real `ast` module; the
   others use targeted regexes. Each returns imports, symbols, endpoints and framework hints.
3. **`manifests/`** — manifest and lockfile parsers for ten ecosystems. Lockfiles matter because
   advisory matching needs resolved versions, not declared ranges.
4. **`apps.py`** — application discovery (workspaces, modules, conventions) and adaptive component
   splitting: descend the directory tree until each component is small enough to read.
5. **`resolve.py`** — turn each import into an internal file or an external package. Handles
   Python module paths, JS/TS extension and index resolution plus `tsconfig` aliases and workspace
   packages, Go module prefixes, JVM package layouts, .NET namespaces and Rust crates.
6. **`integrations.py` / `infra.py`** — signature matching for external systems, and parsing of
   Dockerfiles, Compose, Kubernetes, Terraform, Helm, serverless and CI configuration.
7. **`security/`** — secrets (pattern + entropy, with redaction), insecure patterns (CWE-tagged
   rules), dependency hygiene, optional OSV advisories, local CVSS v3 scoring, SBOM generation.
8. **`graph.py`** — aggregation of file edges to component and application level, Tarjan cycle
   detection, layering, fan-in/fan-out and PageRank.
9. **`flows.py`** — process reconstruction: walk out from each entrypoint, sort reached files into
   architectural lanes, turn guard clauses into decisions, attach the data stores touched.
10. **`c4.py` / `archimate.py`** — formal models built from the same graph.

## Rendering

`repograph_render.layout` computes positions **once** per diagram — a layered Sugiyama-style
layout for structural views, a swimlane layout for flows, a force-directed layout for graphs — and
every backend draws from that same geometry:

| Module | Output |
|---|---|
| `svg.py` | SVG (also inlined into the HTML report) |
| `pdf.py` + `pdfreport.py` | a vector PDF, written byte by byte (no dependency) |
| `pptx.py` + `deck.py` | PPTX with diagrams as native, editable DrawingML shapes |
| `xlsx.py` + `workbook.py` | XLSX written as OOXML directly |
| `mermaid.py`, `plantuml.py`, `dot.py`, `bpmn.py`, `archimate_xml.py` | text formats for other tools |
| `report_html.py` + `webassets.py` | the interactive report, including hand-written 2D and 3D canvas graph engines |
| `report_md.py`, `report_ai.py` | Markdown for people and for models |
| `charts.py` | bars, stacked bars, treemaps and stat tiles |

The 2D and 3D graph views are plain `<canvas>` with force-directed layouts written in the page.
There is no CDN and no bundled library, so a report opens from `file://` on a machine with no
network.

## Design rules we hold ourselves to

- **Deterministic.** The same repository produces the same output. Layout seeds are fixed.
- **Evidence or silence.** Anything asserted carries a file and line, or is reported as unknown.
- **Never crash a scan.** A broken file, an exotic YAML dialect or an unparseable manifest degrades
  to a warning, never an exception.
- **Zero required dependencies.** Optional libraries may make things faster; nothing may make them
  *possible*.
