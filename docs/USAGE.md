# Usage

## Commands

| Command | What it does |
|---|---|
| `repograph scan [path]` | Scan a repository and write the output folder |
| `repograph tui [path]` | Browse a scan in the terminal (scans first if there is no result yet) |
| `repograph serve [dir]` | Serve an output folder over http and open a browser |
| `repograph summary [dir]` | Print the headline numbers of an existing scan |
| `repograph render <json>` | Re-render outputs from an existing `repograph.json` |

## scan

```
repograph scan [path]
  -o, --output DIR        output folder (default: <repo>/repograph-out)
  --online                query OSV.dev for dependency advisories
  --format LIST           all, html, json, markdown, ai, svg, mermaid, plantuml, dot,
                          bpmn, archimate, csv, xlsx, pptx, pdf, sbom
  --ignore GLOB           extra ignore pattern (repeatable)
  --no-tests              exclude test files from the scan
  --no-git                skip git history (authors, hotspots)
  --no-gitignore          do not honour .gitignore
  --max-file-size BYTES   skip files larger than this (default 2 MB)
  --max-flows N           maximum process flows to render (default 14)
  --open                  open the HTML report when finished
  --json                  print the summary as JSON instead of text
  -q, --quiet             only print errors
```

Exit code is `0` on success, `2` for a bad path, `130` if interrupted. repograph does **not** fail
the build on findings — assert on `MANIFEST.json` if you want that.

## Terminal UI keys

| Key | Action |
|---|---|
| `↑ ↓` or `j k` | move |
| `PgUp PgDn` or `b f` | page |
| `g` / `G` | first / last |
| `← →` or `h l` or `Tab` | previous / next view |
| `1`–`0` | jump to a view |
| `/` | filter the current view (`Esc` clears) |
| `d` | toggle the detail pane |
| `?` | help |
| `q` | quit |

## Performance

A single pass, one read per file. Roughly 5,000–15,000 files per minute on a laptop, depending on
file size and language mix. Nothing is written outside the output folder, and the scan never
executes repository code.

To speed up a very large repository:

```bash
repograph scan . --no-git --max-file-size 500000 --ignore 'docs/**' --format html,json
```

## Privacy

Offline by default. `--online` is the only mode that leaves the machine, and it sends **package
names and versions only** to OSV.dev — never source code. Advisory responses are cached under
`~/.cache/repograph/osv`.

Secrets found during a scan are redacted before being written to any report.
