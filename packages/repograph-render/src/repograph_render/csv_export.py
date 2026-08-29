"""CSV exports — the format that opens anywhere and diffs in git."""

from __future__ import annotations

import csv
import os
from typing import List, Sequence

from repograph_core.model import ScanResult


def _write(path: str, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if cell is None else cell for cell in row])


def write_all(result: ScanResult, directory: str) -> List[str]:
    os.makedirs(directory, exist_ok=True)
    written: List[str] = []

    def emit(name: str, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
        path = os.path.join(directory, name)
        _write(path, headers, rows)
        written.append(path)

    emit("findings.csv",
         ["severity", "category", "title", "identifier", "cwe", "file", "line", "package",
          "version", "fixed_version", "confidence", "application", "remediation", "snippet",
          "references"],
         [[f.severity, f.category, f.title, f.identifier, f.cwe, f.file, f.line, f.package,
           f.version, f.fixed_version, f.confidence, f.app, f.remediation, f.snippet,
           " ".join(f.references)] for f in result.findings])

    emit("dependencies.csv",
         ["name", "version", "ecosystem", "scope", "direct", "declared", "used", "purl",
          "declared_in", "used_by_count", "applications"],
         [[d.name, d.version, d.ecosystem, d.scope, d.direct, d.declared, d.used, d.purl,
           "; ".join(d.declared_in), len(d.used_by), "; ".join(d.apps)]
          for d in result.dependencies])

    emit("endpoints.csv",
         ["kind", "method", "path", "handler", "framework", "application", "component", "file",
          "line", "description"],
         [[e.kind, e.method, e.path, e.handler, e.framework, e.app, e.component, e.file, e.line,
           e.description] for e in result.endpoints])

    emit("external_systems.csv",
         ["id", "name", "kind", "technology", "direction", "applications", "evidence_count",
          "first_evidence"],
         [[s.id, s.name, s.kind, s.technology, s.direction, "; ".join(s.apps), len(s.evidence),
           f"{s.evidence[0].file}:{s.evidence[0].line}" if s.evidence else ""]
          for s in result.external_systems])

    emit("applications.csv",
         ["id", "name", "kind", "root", "languages", "frameworks", "files", "loc",
          "architecture_style", "components", "manifests", "description"],
         [[a.id, a.name, a.kind, a.root, "; ".join(a.languages), "; ".join(a.frameworks), a.files,
           a.loc, a.architecture_style, len(a.components), "; ".join(a.manifests), a.description]
          for a in result.apps])

    emit("components.csv",
         ["id", "name", "application", "path", "kind", "languages", "files", "loc", "layer"],
         [[c.id, c.name, c.app, c.path, c.kind, "; ".join(c.languages), c.files, c.loc,
           result.layers.get(c.id, "")] for c in result.components])

    emit("edges.csv", ["source", "target", "kind", "weight", "label"],
         [[e.source, e.target, e.kind, e.weight, e.label] for e in result.edges])

    emit("files.csv", ["path", "language", "kind", "loc", "sloc", "size", "application",
                       "component", "symbols"],
         [[f.path, f.language, f.kind, f.loc, f.sloc, f.size, f.app, f.component, f.symbols]
          for f in result.files])

    emit("symbols.csv", ["name", "kind", "file", "line", "application", "component", "signature"],
         [[s.name, s.kind, s.file, s.line, s.app, s.component, s.signature]
          for s in result.symbols])

    env_vars = (result.infrastructure or {}).get("env_vars") or {}
    emit("environment_variables.csv", ["name", "kind", "files"],
         [[name, info.get("kind", ""), "; ".join(info.get("files", []))]
          for name, info in env_vars.items()])

    return written
