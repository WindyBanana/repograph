"""Terminal UI for browsing a scan (curses; Linux and macOS)."""

from __future__ import annotations

import curses
import json
import os
import webbrowser
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from repograph_core.model import ScanResult
from repograph_core.scan import ScanOptions, scan

PAIR_HEADER = 1
PAIR_ACCENT = 2
PAIR_MUTED = 3
PAIR_CRITICAL = 4
PAIR_HIGH = 5
PAIR_MEDIUM = 6
PAIR_LOW = 7
PAIR_OK = 8
PAIR_SELECT = 9

SEVERITY_PAIR = {
    "critical": PAIR_CRITICAL, "high": PAIR_HIGH, "medium": PAIR_MEDIUM,
    "low": PAIR_LOW, "info": PAIR_MUTED,
}


@dataclass
class Row:
    label: str
    detail: List[str] = field(default_factory=list)
    colour: int = 0
    meta: str = ""


@dataclass
class View:
    key: str
    title: str
    build: Callable[[ScanResult], List[Row]]


def _fmt(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


# ------------------------------------------------------------------- views

def view_overview(result: ScanResult) -> List[Row]:
    summary = result.summary
    metrics = result.metrics
    rows = [
        Row(f"Purpose: {str(summary.get('purpose', ''))[:110]}", colour=PAIR_ACCENT),
        Row(f"Shape: {summary.get('shape', '')}  ·  style: "
            f"{', '.join(summary.get('architecture_styles', [])) or 'unclassified'}"),
        Row(f"Languages: {', '.join(summary.get('primary_languages', [])[:6]) or 'unknown'}"),
        Row(""),
        Row(f"Applications        {_fmt(metrics.apps)}"),
        Row(f"Components          {_fmt(metrics.components)}  ({metrics.cycles} cycles)"),
        Row(f"Files / lines       {_fmt(metrics.scanned_files)} / {_fmt(metrics.loc)}"),
        Row(f"Endpoints           {_fmt(metrics.endpoints)}"),
        Row(f"Dependencies        {_fmt(metrics.dependencies)}"),
        Row(f"External systems    {_fmt(metrics.external_systems)}"),
        Row(f"Test file ratio     {metrics.test_ratio:.0%}"),
        Row(""),
        Row("Findings", colour=PAIR_ACCENT),
    ]
    for severity in ("critical", "high", "medium", "low", "info"):
        count = metrics.findings_by_severity.get(severity, 0)
        if count:
            rows.append(Row(f"  {severity.title():<10} {count}", colour=SEVERITY_PAIR[severity]))
    if result.git.is_repo:
        rows.extend([
            Row(""),
            Row("Git", colour=PAIR_ACCENT),
            Row(f"  {result.git.commits} commits · {result.git.contributors} contributors · "
                f"{result.git.first_commit} → {result.git.last_commit}"),
        ])
    if result.meta.warnings:
        rows.append(Row(""))
        rows.append(Row("Notes", colour=PAIR_ACCENT))
        for warning in result.meta.warnings:
            rows.append(Row(f"  {warning}", colour=PAIR_MEDIUM))
    return rows


def view_apps(result: ScanResult) -> List[Row]:
    rows = []
    endpoints: Dict[str, int] = {}
    for endpoint in result.endpoints:
        endpoints[endpoint.app] = endpoints.get(endpoint.app, 0) + 1
    for app in result.apps:
        systems = [s.name for s in result.external_systems if app.id in s.apps]
        rows.append(Row(
            f"{app.name[:34]:<34} {app.kind:<12} {app.files:>5} files  {app.loc:>8,} loc",
            detail=[
                f"root: {app.root or '.'}",
                f"style: {app.architecture_style}",
                f"languages: {', '.join(app.languages) or 'unknown'}",
                f"frameworks: {', '.join(app.frameworks) or 'none detected'}",
                f"endpoints: {endpoints.get(app.id, 0)}",
                f"entrypoints: {', '.join(app.entrypoints[:4]) or 'none declared'}",
                f"external systems: {', '.join(systems) or 'none'}",
                "",
                app.description or "no description found",
            ],
            colour=PAIR_ACCENT))
    return rows


def view_components(result: ScanResult) -> List[Row]:
    app_names = {a.id: a.name for a in result.apps}
    rows = []
    for component in sorted(result.components, key=lambda c: -c.files):
        rows.append(Row(
            f"{component.name[:38]:<38} {app_names.get(component.app, '')[:16]:<16} "
            f"{component.files:>5} files {component.loc:>8,} loc  layer "
            f"{result.layers.get(component.id, '-')}",
            detail=[f"path: {component.path}", f"kind: {component.kind}",
                    f"languages: {', '.join(component.languages)}"]))
    return rows


def view_endpoints(result: ScanResult) -> List[Row]:
    rows = []
    for endpoint in sorted(result.endpoints, key=lambda e: (e.kind, e.path)):
        rows.append(Row(
            f"{endpoint.method:<7} {endpoint.path[:52]:<52} {endpoint.framework[:16]:<16} "
            f"{endpoint.kind}",
            detail=[f"handler: {endpoint.handler or 'unnamed'}",
                    f"source: {endpoint.file}:{endpoint.line}",
                    f"application: {endpoint.app}"]))
    return rows


def view_dependencies(result: ScanResult) -> List[Row]:
    rows = []
    for dep in result.dependencies:
        flags = []
        if not dep.used and dep.direct:
            flags.append("unused?")
        if not dep.version:
            flags.append("unpinned")
        rows.append(Row(
            f"{dep.name[:36]:<36} {(dep.version or '-')[:14]:<14} {dep.ecosystem:<10} "
            f"{dep.scope:<8} {' '.join(flags)}",
            detail=[f"declared in: {', '.join(dep.declared_in[:3])}",
                    f"used by {len(dep.used_by)} file(s)",
                    f"purl: {dep.purl}"],
            colour=PAIR_MEDIUM if flags else 0))
    return rows


def view_findings(result: ScanResult) -> List[Row]:
    rows = []
    for finding in result.findings:
        location = f"{finding.file}:{finding.line}" if finding.file else "repository"
        rows.append(Row(
            f"{finding.severity.upper():<9} {finding.title[:58]:<58} {location[:40]}",
            detail=[f"identifier: {finding.identifier or 'n/a'}   cwe: {finding.cwe or 'n/a'}",
                    f"category: {finding.category}   confidence: {finding.confidence}",
                    f"where: {location}",
                    f"code: {finding.snippet}" if finding.snippet else "",
                    "", f"fix: {finding.remediation}"],
            colour=SEVERITY_PAIR.get(finding.severity, 0)))
    return rows


def view_systems(result: ScanResult) -> List[Row]:
    rows = []
    for system in result.external_systems:
        rows.append(Row(
            f"{system.name[:32]:<32} {system.kind:<14} {system.technology[:22]:<22} "
            f"{len(system.evidence)} refs",
            detail=[f"direction: {system.direction}",
                    f"used by: {', '.join(system.apps) or 'unknown'}",
                    "evidence:"] +
                   [f"  {ev.file}:{ev.line}  {ev.snippet[:70]}" for ev in system.evidence[:8]],
            colour=PAIR_OK))
    return rows


def view_flows(result: ScanResult) -> List[Row]:
    rows = []
    for flow in result.flows:
        rows.append(Row(
            f"{flow.name[:60]:<60} {len(flow.nodes)} steps",
            detail=[flow.description, f"lanes: {', '.join(flow.lanes)}", ""] +
                   [f"  {node.lane or 'process':<12} {node.kind:<11} {node.label}"
                    for node in flow.nodes],
            colour=PAIR_ACCENT))
    return rows


def view_infra(result: ScanResult) -> List[Row]:
    infra = result.infrastructure or {}
    rows: List[Row] = []
    for container in infra.get("containers") or []:
        rows.append(Row(f"compose   {str(container.get('name'))[:24]:<24} "
                        f"{str(container.get('image') or container.get('build'))[:40]}",
                        detail=[f"ports: {container.get('ports')}",
                                f"depends on: {container.get('depends_on')}",
                                f"file: {container.get('file')}"]))
    for dockerfile in infra.get("dockerfiles") or []:
        rows.append(Row(f"docker    {str(dockerfile.get('file'))[:60]}",
                        detail=[f"base: {', '.join(dockerfile.get('base_images', []))}",
                                f"user: {dockerfile.get('user')}",
                                f"ports: {dockerfile.get('ports')}",
                                f"entrypoint: {dockerfile.get('entrypoint')}"]))
    for workload in infra.get("kubernetes") or []:
        rows.append(Row(f"k8s       {str(workload.get('kind'))[:14]:<14} {workload.get('name')}",
                        detail=[f"images: {workload.get('images')}",
                                f"file: {workload.get('file')}"]))
    for resource in infra.get("terraform") or []:
        rows.append(Row(f"terraform {str(resource.get('type'))[:28]:<28} {resource.get('name')}",
                        detail=[f"file: {resource.get('file')}:{resource.get('line')}"]))
    for pipeline in infra.get("ci") or []:
        rows.append(Row(f"ci        {str(pipeline.get('system'))[:16]:<16} {pipeline.get('name')}",
                        detail=[f"triggers: {pipeline.get('triggers')}",
                                f"jobs: {[j.get('name') for j in (pipeline.get('jobs') or [])]}",
                                f"file: {pipeline.get('file')}"]))
    env_vars = infra.get("env_vars") or {}
    for name, info in list(env_vars.items())[:300]:
        rows.append(Row(f"env       {name[:30]:<30} {info.get('kind', '')}",
                        detail=[f"files: {', '.join(info.get('files', [])[:6])}"],
                        colour=PAIR_MUTED))
    return rows


def view_files(result: ScanResult) -> List[Row]:
    rows = []
    for info in sorted(result.files, key=lambda f: -f.loc)[:1500]:
        rows.append(Row(f"{info.path[:70]:<70} {info.language[:12]:<12} {info.loc:>7,} loc",
                        detail=[f"kind: {info.kind}", f"application: {info.app}",
                                f"component: {info.component}", f"symbols: {info.symbols}"]))
    return rows


VIEWS = [
    View("overview", "Overview", view_overview),
    View("apps", "Applications", view_apps),
    View("components", "Components", view_components),
    View("endpoints", "Endpoints", view_endpoints),
    View("dependencies", "Dependencies", view_dependencies),
    View("findings", "Findings", view_findings),
    View("systems", "External systems", view_systems),
    View("flows", "Process flows", view_flows),
    View("infra", "Infrastructure", view_infra),
    View("files", "Files", view_files),
]


class Tui:
    def __init__(self, result: ScanResult, output_dir: str = "") -> None:
        self.result = result
        self.output_dir = output_dir
        self.view_index = 0
        self.cursor = 0
        self.offset = 0
        self.search = ""
        self.search_mode = False
        self.show_detail = True
        self.rows_cache: Dict[str, List[Row]] = {}
        self.message = ""

    # ------------------------------------------------------------ helpers
    def rows(self) -> List[Row]:
        view = VIEWS[self.view_index]
        if view.key not in self.rows_cache:
            self.rows_cache[view.key] = view.build(self.result)
        rows = self.rows_cache[view.key]
        if self.search:
            needle = self.search.lower()
            rows = [r for r in rows
                    if needle in r.label.lower() or any(needle in d.lower() for d in r.detail)]
        return rows

    def run(self, stdscr) -> None:
        curses.curs_set(0)
        stdscr.nodelay(False)
        stdscr.keypad(True)
        self._init_colours()
        while True:
            self._draw(stdscr)
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                return
            if self.search_mode:
                if key in (curses.KEY_ENTER, 10, 13):
                    self.search_mode = False
                elif key in (27,):
                    self.search_mode = False
                    self.search = ""
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    self.search = self.search[:-1]
                elif 32 <= key <= 126:
                    self.search += chr(key)
                self.cursor = 0
                self.offset = 0
                continue
            if key in (ord("q"), 27):
                return
            self._handle(key, stdscr)

    def _handle(self, key: int, stdscr) -> None:
        self.message = ""
        rows = self.rows()
        height = max(4, stdscr.getmaxyx()[0] - 8)
        if key in (curses.KEY_DOWN, ord("j")):
            self.cursor = min(len(rows) - 1, self.cursor + 1)
        elif key in (curses.KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
        elif key in (curses.KEY_NPAGE, ord("f")):
            self.cursor = min(len(rows) - 1, self.cursor + height)
        elif key in (curses.KEY_PPAGE, ord("b")):
            self.cursor = max(0, self.cursor - height)
        elif key in (curses.KEY_HOME, ord("g")):
            self.cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            self.cursor = max(0, len(rows) - 1)
        elif key in (curses.KEY_RIGHT, ord("l"), ord("\t")):
            self.view_index = (self.view_index + 1) % len(VIEWS)
            self.cursor = self.offset = 0
        elif key in (curses.KEY_LEFT, ord("h"), curses.KEY_BTAB):
            self.view_index = (self.view_index - 1) % len(VIEWS)
            self.cursor = self.offset = 0
        elif ord("1") <= key <= ord("9") and key - ord("1") < len(VIEWS):
            self.view_index = key - ord("1")
            self.cursor = self.offset = 0
        elif key == ord("0") and len(VIEWS) >= 10:
            self.view_index = 9
            self.cursor = self.offset = 0
        elif key == ord("/"):
            self.search_mode = True
            self.search = ""
        elif key == ord("d"):
            self.show_detail = not self.show_detail
        elif key == ord("o"):
            self._open_report()
        elif key == ord("?"):
            self._help(stdscr)

    def _open_report(self) -> None:
        """Hand the full graphical report to whatever can display it."""
        index = os.path.join(self.output_dir, "index.html") if self.output_dir else ""
        if not index or not os.path.isfile(index):
            self.message = "no rendered report alongside this scan — run: repograph scan <path>"
            return
        try:
            opened = webbrowser.open(f"file://{os.path.abspath(index)}")
        except Exception:
            opened = False
        self.message = (f"opened {index}" if opened
                        else f"could not open a browser — the report is at {index}")

    def _init_colours(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(PAIR_HEADER, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(PAIR_ACCENT, curses.COLOR_CYAN, -1)
        curses.init_pair(PAIR_MUTED, curses.COLOR_WHITE, -1)
        curses.init_pair(PAIR_CRITICAL, curses.COLOR_RED, -1)
        curses.init_pair(PAIR_HIGH, curses.COLOR_MAGENTA, -1)
        curses.init_pair(PAIR_MEDIUM, curses.COLOR_YELLOW, -1)
        curses.init_pair(PAIR_LOW, curses.COLOR_BLUE, -1)
        curses.init_pair(PAIR_OK, curses.COLOR_GREEN, -1)
        curses.init_pair(PAIR_SELECT, curses.COLOR_BLACK, curses.COLOR_CYAN)

    def _add(self, stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = stdscr.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        try:
            stdscr.addnstr(y, x, text, max(0, width - x - 1), attr)
        except curses.error:
            pass

    def _draw(self, stdscr) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        metrics = self.result.metrics
        title = (f" repograph · {self.result.meta.repo_name} · {metrics.apps} app(s) · "
                 f"{metrics.scanned_files} files · {metrics.loc:,} loc · "
                 f"{sum(metrics.findings_by_severity.values())} findings ")
        self._add(stdscr, 0, 0, title.ljust(width - 1), curses.color_pair(PAIR_HEADER) | curses.A_BOLD)

        tab_x = 0
        for index, view in enumerate(VIEWS):
            label = f" {index + 1}:{view.title} "
            attr = curses.A_REVERSE if index == self.view_index else curses.color_pair(PAIR_MUTED)
            self._add(stdscr, 1, tab_x, label, attr)
            tab_x += len(label) + 1
            if tab_x > width - 12:
                break

        rows = self.rows()
        detail_height = 0
        selected = rows[self.cursor] if rows and self.cursor < len(rows) else None
        if self.show_detail and selected and selected.detail:
            detail_height = min(12, len(selected.detail) + 2)
        list_height = max(3, height - 4 - detail_height)

        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + list_height:
            self.offset = self.cursor - list_height + 1

        for line, row in enumerate(rows[self.offset:self.offset + list_height]):
            index = self.offset + line
            attr = curses.color_pair(row.colour) if row.colour else 0
            if index == self.cursor:
                attr = curses.color_pair(PAIR_SELECT) | curses.A_BOLD
            prefix = "▸ " if index == self.cursor else "  "
            self._add(stdscr, 3 + line, 0, prefix + row.label, attr)

        if not rows:
            self._add(stdscr, 3, 2, "(nothing here)", curses.color_pair(PAIR_MUTED))

        if detail_height and selected:
            separator = "─" * (width - 1)
            self._add(stdscr, 3 + list_height, 0, separator, curses.color_pair(PAIR_MUTED))
            for line, text in enumerate(selected.detail[: detail_height - 1]):
                self._add(stdscr, 4 + list_height + line, 2, text, curses.color_pair(PAIR_MUTED))

        if self.message:
            status = f" {self.message}"
        elif self.search_mode:
            status = f" /{self.search}"
        elif self.search:
            status = (f" filter:{self.search}  {len(rows)} match(es)  "
                      f"[{self.cursor + 1}/{len(rows)}]  / search  d detail  q quit")
        else:
            status = (f" {VIEWS[self.view_index].title}  [{self.cursor + 1 if rows else 0}/{len(rows)}]"
                      f"  ←/→ views  / search  d detail  o report  ? help  q quit")
        if self.output_dir and not self.message:
            status += f"  ·  {self.output_dir}"
        self._add(stdscr, height - 1, 0, status.ljust(width - 1),
                  curses.color_pair(PAIR_HEADER))
        stdscr.refresh()

    def _help(self, stdscr) -> None:
        lines = [
            "repograph terminal UI",
            "",
            "  ↑/↓ or j/k     move",
            "  PgUp/PgDn      page (also b / f)",
            "  g / G          first / last",
            "  ←/→ or h/l     previous / next view",
            "  1..0           jump to a view",
            "  /              filter the current view (Esc clears)",
            "  d              toggle the detail pane",
            "  o              open the full graphical report in a browser",
            "  ?              this help",
            "  q              quit",
            "",
            "Everything shown was produced by a static scan — press q to return.",
        ]
        stdscr.erase()
        for index, line in enumerate(lines):
            self._add(stdscr, 2 + index, 4, line,
                      curses.A_BOLD if index == 0 else curses.color_pair(PAIR_MUTED))
        stdscr.refresh()
        stdscr.getch()


def load_or_scan(path: str, online: bool = False) -> Tuple[ScanResult, str]:
    path = os.path.abspath(path)
    if os.path.isfile(path) and path.endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            return ScanResult.from_dict(json.load(fh)), os.path.dirname(path)
    candidate = os.path.join(path, "repograph.json")
    if os.path.isfile(candidate):
        with open(candidate, encoding="utf-8") as fh:
            return ScanResult.from_dict(json.load(fh)), path
    nested = os.path.join(path, "repograph-out", "repograph.json")
    if os.path.isfile(nested):
        with open(nested, encoding="utf-8") as fh:
            return ScanResult.from_dict(json.load(fh)), os.path.dirname(nested)

    def progress(stage: str, done: int, total: int) -> None:
        message = f"{stage} … {done}/{total}" if total else f"{stage} …"
        print(f"\r\033[2K  {message}", end="", flush=True)

    print(f"scanning {path} (no previous scan found)")
    result = scan(ScanOptions(root=path, online=online, progress=progress))
    print("\r\033[2K", end="")
    return result, ""


def run(path: str = ".", online: bool = False) -> int:
    try:
        result, output_dir = load_or_scan(path, online=online)
    except KeyboardInterrupt:
        return 130
    try:
        curses.wrapper(Tui(result, output_dir).run)
    except curses.error as exc:
        print(f"terminal too small or unsupported: {exc}")
        return 1
    return 0
