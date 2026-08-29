"""repograph command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from typing import List, Optional, Sequence

from repograph_core.model import ScanResult
from repograph_core.scan import VERSION, ScanOptions, scan
from repograph_render.render import ALL_FORMATS, DEFAULT_FORMATS, render_all

from .console import SEVERITY_COLOUR, Console

BANNER = r"""
                                     _
  _ __ ___ _ __   ___   __ _ _ __ __ _ _ __ | |__
 | '__/ _ \ '_ \ / _ \ / _` | '__/ _` | '_ \| '_ \
 | | |  __/ |_) | (_) | (_| | | | (_| | |_) | | | |
 |_|  \___| .__/ \___/ \__, |_|  \__,_| .__/|_| |_|
          |_|          |___/          |_|
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repograph",
        description="Scan a repository and produce architecture diagrams, reports and "
                    "vulnerability findings. Deterministic: no AI, no code execution.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  repograph scan .                          scan the current repository
  repograph scan ~/code/app -o ./out        choose an output folder
  repograph scan . --online                 also check dependencies against OSV.dev
  repograph scan . --format html,pdf,xlsx   only produce some formats
  repograph scan . --open                   open the HTML report when finished
  repograph tui                             browse the last scan in the terminal
  repograph serve ./repograph-out           serve the report over http
  repograph summary ./repograph-out         print the headline numbers again
""",
    )
    parser.add_argument("--version", action="version", version=f"repograph {VERSION}")
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="scan a repository and write reports")
    scan_parser.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    scan_parser.add_argument("-o", "--output", default="", metavar="DIR",
                             help="output folder (default: <repo>/repograph-out)")
    scan_parser.add_argument("--online", action="store_true",
                             help="query OSV.dev for dependency advisories (network access)")
    scan_parser.add_argument("--format", default="all", metavar="LIST",
                             help=f"comma separated: all,{','.join(ALL_FORMATS)}")
    scan_parser.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                             help="extra ignore pattern (repeatable)")
    scan_parser.add_argument("--no-tests", action="store_true", help="exclude test files")
    scan_parser.add_argument("--no-git", action="store_true", help="skip git history analysis")
    scan_parser.add_argument("--no-gitignore", action="store_true",
                             help="do not honour .gitignore")
    scan_parser.add_argument("--max-file-size", type=int, default=2_000_000, metavar="BYTES",
                             help="skip files larger than this (default: 2000000)")
    scan_parser.add_argument("--max-flows", type=int, default=14, metavar="N",
                             help="maximum process flows to render (default: 14)")
    scan_parser.add_argument("--open", action="store_true", dest="open_report",
                             help="open the HTML report when finished")
    scan_parser.add_argument("--json", action="store_true", dest="json_out",
                             help="print the scan summary as JSON to stdout")
    scan_parser.add_argument("-q", "--quiet", action="store_true", help="only print errors")

    tui_parser = sub.add_parser("tui", help="browse a scan in a terminal UI")
    tui_parser.add_argument("path", nargs="?", default=".",
                            help="repository root or an existing repograph.json / output folder")
    tui_parser.add_argument("--online", action="store_true", help="scan with advisory lookup")

    serve_parser = sub.add_parser("serve", help="serve an output folder over http")
    serve_parser.add_argument("path", nargs="?", default="repograph-out")
    serve_parser.add_argument("-p", "--port", type=int, default=8000)
    serve_parser.add_argument("--no-open", action="store_true")

    summary_parser = sub.add_parser("summary", help="print the summary of an existing scan")
    summary_parser.add_argument("path", nargs="?", default="repograph-out",
                                help="output folder or repograph.json")

    render_parser = sub.add_parser("render", help="re-render outputs from an existing repograph.json")
    render_parser.add_argument("json_path", help="path to repograph.json")
    render_parser.add_argument("-o", "--output", default="", help="output folder")
    render_parser.add_argument("--format", default="all")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "tui":
        return cmd_tui(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "summary":
        return cmd_summary(args)
    if args.command == "render":
        return cmd_render(args)
    parser.print_help()
    return 1


def _formats(value: str) -> List[str]:
    if not value or value.strip() in ("all", "*"):
        return list(DEFAULT_FORMATS)
    wanted = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = [item for item in wanted if item not in ALL_FORMATS]
    if unknown:
        raise SystemExit(f"unknown format(s): {', '.join(unknown)}. "
                         f"Valid: all, {', '.join(ALL_FORMATS)}")
    return wanted


def cmd_scan(args) -> int:
    console = Console(quiet=args.quiet)
    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        console.write(console.paint(f"error: {root} is not a directory", "red"))
        return 2
    output_dir = os.path.abspath(args.output) if args.output else os.path.join(root, "repograph-out")
    formats = _formats(args.format)

    if not args.quiet:
        console.write(console.paint(BANNER, "bright_blue"))
        console.write(f"  {console.paint('repograph', 'white', bold=True)} "
                      f"{console.paint(VERSION, 'grey')} — scanning "
                      f"{console.paint(root, 'cyan')}")
        console.write(f"  output → {console.paint(output_dir, 'cyan')}")
        console.write()

    def progress(stage: str, done: int, total: int) -> None:
        if total:
            console.status(f"{stage} … {done}/{total}")
        else:
            console.status(f"{stage} …")

    options = ScanOptions(
        root=root,
        online=args.online,
        include_tests=not args.no_tests,
        max_file_size=args.max_file_size,
        extra_ignores=tuple(args.ignore),
        use_gitignore=not args.no_gitignore,
        git_history=not args.no_git,
        progress=progress,
    )
    try:
        result = scan(options)
    except KeyboardInterrupt:
        console.clear_status()
        console.write(console.paint("\ninterrupted", "yellow"))
        return 130
    console.clear_status()

    rendered = render_all(result, output_dir, formats=formats,
                          progress=lambda message: console.status(message),
                          max_flows=args.max_flows)
    console.clear_status()

    if args.json_out:
        print(json.dumps({
            "output_dir": rendered.output_dir,
            "files": rendered.relative(),
            "summary": result.summary,
            "metrics": {
                "apps": result.metrics.apps, "components": result.metrics.components,
                "files": result.metrics.scanned_files, "loc": result.metrics.loc,
                "endpoints": result.metrics.endpoints,
                "dependencies": result.metrics.dependencies,
                "external_systems": result.metrics.external_systems,
                "findings": result.metrics.findings_by_severity,
            },
        }, indent=2))
    else:
        print_summary(console, result, rendered.output_dir, rendered)

    if args.open_report:
        index = os.path.join(rendered.output_dir, "index.html")
        if os.path.exists(index):
            webbrowser.open(f"file://{index}")
    return 0


def print_summary(console: Console, result: ScanResult, output_dir: str, rendered=None) -> None:
    metrics = result.metrics
    summary = result.summary

    console.rule(f"{result.meta.repo_name}")
    console.write(f"  {console.paint(str(summary.get('purpose', ''))[:180], 'white')}")
    console.write()
    console.item("Shape", str(summary.get("shape", "unknown")))
    console.item("Architecture", ", ".join(summary.get("architecture_styles", [])) or "unclassified")
    console.item("Languages", ", ".join(summary.get("primary_languages", [])[:6]) or "unknown")
    console.item("Scanned", f"{metrics.scanned_files} files · {metrics.loc:,} lines · "
                            f"{metrics.duration_seconds}s")
    console.item("Applications", str(metrics.apps))
    console.item("Components", f"{metrics.components} ({metrics.cycles} cycle(s))")
    console.item("Endpoints", str(metrics.endpoints))
    console.item("Dependencies", str(metrics.dependencies))
    console.item("External systems", str(metrics.external_systems))

    if result.apps:
        console.header("Applications")
        console.table(
            ["name", "kind", "languages", "files", "loc", "style"],
            [[a.name[:28], a.kind, ", ".join(a.languages[:2]), str(a.files), f"{a.loc:,}",
              a.architecture_style[:30]] for a in result.apps[:12]],
            aligns=["l", "l", "l", "r", "r", "l"])

    counts = metrics.findings_by_severity
    if counts:
        console.header("Findings")
        for severity in ("critical", "high", "medium", "low", "info"):
            if counts.get(severity):
                console.item(severity.title(), str(counts[severity]),
                             SEVERITY_COLOUR.get(severity, ""))
        top = [f for f in result.findings if f.severity in ("critical", "high")][:6]
        if top:
            console.write()
            for finding in top:
                location = f"{finding.file}:{finding.line}" if finding.file else "repository"
                console.bullet(f"{finding.title}  {console.paint(location, 'grey')}",
                               SEVERITY_COLOUR.get(finding.severity, ""))

    if result.external_systems:
        console.header("External systems")
        by_kind: dict = {}
        for system in result.external_systems:
            by_kind.setdefault(system.kind, []).append(system.name)
        for kind, names in sorted(by_kind.items()):
            console.item(kind, ", ".join(names[:6]) + (f" (+{len(names) - 6})" if len(names) > 6 else ""))

    if result.meta.warnings:
        console.header("Notes")
        for warning in result.meta.warnings:
            console.bullet(warning, "yellow")

    console.header("Output", output_dir)
    console.item("Interactive report", os.path.join(output_dir, "index.html"))
    console.item("Agent report", os.path.join(output_dir, "AI-REPORT.md"))
    console.item("PDF / deck / workbook", "report.pdf · presentation.pptx · report.xlsx")
    if rendered is not None:
        console.item("Files written", str(len(rendered.files)))
        for name, reason in (rendered.skipped or {}).items():
            console.bullet(f"skipped {name}: {reason}", "yellow")
    console.write()


def cmd_tui(args) -> int:
    try:
        from repograph_tui.app import run
    except ImportError as exc:
        print(f"the terminal UI is not available: {exc}", file=sys.stderr)
        return 1
    return run(args.path, online=args.online)


def cmd_serve(args) -> int:
    import http.server
    import socketserver
    import threading

    directory = os.path.abspath(args.path)
    if not os.path.isdir(directory):
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2

    handler = lambda *handler_args, **kwargs: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *handler_args, directory=directory, **kwargs)
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/index.html"
        print(f"serving {directory} at {url}  (ctrl-c to stop)")
        if not args.no_open:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


def load_result(path: str) -> ScanResult:
    path = os.path.abspath(path)
    if os.path.isdir(path):
        candidate = os.path.join(path, "repograph.json")
        if os.path.exists(candidate):
            path = candidate
        else:
            raise SystemExit(f"no repograph.json in {path} — run a scan first")
    with open(path, encoding="utf-8") as fh:
        return ScanResult.from_dict(json.load(fh))


def cmd_summary(args) -> int:
    result = load_result(args.path)
    console = Console()
    print_summary(console, result, os.path.dirname(os.path.abspath(args.path)))
    return 0


def cmd_render(args) -> int:
    result = load_result(args.json_path)
    output_dir = os.path.abspath(args.output) if args.output else os.path.dirname(
        os.path.abspath(args.json_path))
    console = Console()
    rendered = render_all(result, output_dir, formats=_formats(args.format),
                          progress=lambda message: console.status(message))
    console.clear_status()
    console.write(f"wrote {len(rendered.files)} files to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
