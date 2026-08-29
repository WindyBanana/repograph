"""repograph command line interface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from typing import List, Optional, Sequence

from repograph_core import ask as ask_mod
from repograph_core import enrich as enrich_mod
from repograph_core.model import ScanResult
from repograph_core.scan import VERSION, ScanOptions, scan
from repograph_render import agentpack
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
  repograph agent ./repograph-out           show how to enrich the scan with an AI agent
  repograph agent ./repograph-out --run claude   run the agent for you
  repograph enrich ./repograph-out          merge an agent's answers back into the reports
  repograph ask "where do I add refunds?"   ask an agent a question with the scan as context
  repograph ask --suggest                   questions worth asking about this repository
  repograph ui                              open the desktop UI in a browser
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
    scan_parser.add_argument("--everything", action="store_true",
                             help="produce every artifact even when it does not apply to this "
                                  "repository (by default repograph skips what would be empty)")
    scan_parser.add_argument("--open", action="store_true", dest="open_report",
                             help="open the HTML report when finished")
    scan_parser.add_argument("--json", action="store_true", dest="json_out",
                             help="print the scan summary as JSON to stdout")
    scan_parser.add_argument("-q", "--quiet", action="store_true", help="only print errors")

    ui_parser = sub.add_parser("ui", help="open the desktop UI (a local page in your browser)")
    ui_parser.add_argument("path", nargs="?", default="",
                           help="repository to pre-fill in the folder box")
    ui_parser.add_argument("-p", "--port", type=int, default=7373)
    ui_parser.add_argument("--no-open", action="store_true",
                           help="do not open a browser window automatically")
    ui_parser.add_argument("-q", "--quiet", action="store_true")

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

    agent_parser = sub.add_parser(
        "agent", help="enrich a scan with an AI agent (optional; nothing is sent anywhere by "
                      "repograph itself)")
    agent_parser.add_argument("path", nargs="?", default="repograph-out",
                              help="output folder from a previous scan")
    agent_parser.add_argument("--run", metavar="TOOL", default="",
                              help=f"launch an agent CLI: {', '.join(sorted(agentpack.AGENT_TOOLS))}")
    agent_parser.add_argument("--yes", action="store_true", help="do not ask before running")
    agent_parser.add_argument("--print-prompt", action="store_true",
                              help="print the instructions instead of the commands")
    agent_parser.add_argument("--write-agents-md", nargs="?", const="AGENTS.md", default="",
                              metavar="FILE",
                              help="add a pointer to the scan in the repository's agent file "
                                   "(default AGENTS.md; try CLAUDE.md) so any agent opening the "
                                   "repo finds the analysis")

    enrich_parser = sub.add_parser(
        "enrich", help="validate an agent's enrichment.json, merge it and re-render")
    enrich_parser.add_argument("path", nargs="?", default="repograph-out",
                               help="output folder, or a path to an enrichment.json")
    enrich_parser.add_argument("--format", default="all", help="formats to re-render")
    enrich_parser.add_argument("--no-render", action="store_true",
                               help="merge into repograph.json without re-rendering")
    enrich_parser.add_argument("--allow-unsupported", action="store_true",
                               help="accept risks that carry no file:line evidence")

    ask_parser = sub.add_parser(
        "ask", help="ask an AI agent a question with this scan as context")
    ask_parser.add_argument("question", nargs="*", help="your question, in plain words")
    ask_parser.add_argument("-o", "--output", default="repograph-out", metavar="DIR",
                            help="output folder from a previous scan")
    ask_parser.add_argument("--suggest", action="store_true",
                            help="list questions worth asking about this repository")
    ask_parser.add_argument("--run", metavar="TOOL", default="",
                            help="launch an agent CLI with the question")
    ask_parser.add_argument("--yes", action="store_true", help="do not ask before running")
    ask_parser.add_argument("--print-prompt", action="store_true",
                            help="print the full prompt to stdout and nothing else")

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
    if args.command == "ui":
        return cmd_ui(args)
    if args.command == "tui":
        return cmd_tui(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "summary":
        return cmd_summary(args)
    if args.command == "render":
        return cmd_render(args)
    if args.command == "agent":
        return cmd_agent(args)
    if args.command == "enrich":
        return cmd_enrich(args)
    if args.command == "ask":
        return cmd_ask(args)
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
        everything=args.everything,
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

    profile = result.profile or {}
    console.rule(f"{result.meta.repo_name}")
    console.write(f"  {console.paint(str(summary.get('purpose', ''))[:180], 'white')}")
    console.write()
    console.item("Reads as", str(profile.get("label", "software repository")))
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

    artifacts = (profile or {}).get("artifacts") or {}
    not_produced = [(name, str(entry.get("reason", "")))
                    for name, entry in sorted(artifacts.items())
                    if isinstance(entry, dict) and not entry.get("include", True)]
    if not_produced:
        console.header("Not produced", "these do not apply to this repository "
                                       "(use --everything to force them)")
        for name, why in not_produced[:12]:
            console.item(name, why or "not applicable")
        if len(not_produced) > 12:
            console.bullet(f"and {len(not_produced) - 12} more", "grey")

    if result.meta.warnings:
        console.header("Notes")
        for warning in result.meta.warnings:
            console.bullet(warning, "yellow")

    console.header("Output", output_dir)
    console.item("Interactive report", os.path.join(output_dir, "index.html"))
    console.item("Agent report", os.path.join(output_dir, "AI-REPORT.md"))
    if os.path.exists(os.path.join(output_dir, "AGENT-INSTRUCTIONS.md")):
        console.item("Optional AI pass", f"repograph agent {output_dir}")
    documents = [name for name in ("report.pdf", "presentation.pptx", "report.xlsx")
                 if os.path.exists(os.path.join(output_dir, name))]
    if documents:
        console.item("Documents", " · ".join(documents))
    if rendered is not None:
        console.item("Files written", str(len(rendered.files)))
        for name, reason in (rendered.skipped or {}).items():
            console.bullet(f"failed to write {name}: {reason}", "yellow")
    console.write()


def cmd_ui(args) -> int:
    try:
        from repograph_ui.server import serve
    except ImportError as exc:
        print(f"the desktop UI is not available: {exc}", file=sys.stderr)
        return 1
    return serve(args.path, port=args.port, open_browser=not args.no_open, quiet=args.quiet)


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


def _output_dir_of(path: str) -> str:
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return os.path.dirname(os.path.dirname(path)) if os.path.basename(
            os.path.dirname(path)) == "agent" else os.path.dirname(path)
    return path


def cmd_agent(args) -> int:
    console = Console()
    output_dir = _output_dir_of(args.path)
    try:
        result = load_result(output_dir)
    except SystemExit as exc:
        console.write(console.paint(str(exc), "red"))
        return 2

    repo_root = result.meta.root
    agentpack.write(result, output_dir, repo_root)
    instructions_path = os.path.join(output_dir, "AGENT-INSTRUCTIONS.md")

    if args.print_prompt:
        with open(instructions_path, encoding="utf-8") as handle:
            print(handle.read())
        return 0

    console.header("Enrich this scan with an AI agent",
                   "repograph never calls a model itself. You run the agent you already pay for, "
                   "on your machine.")
    console.write()
    console.write("  What it adds: intent, business meaning, a judgement on every finding,")
    console.write("  and a ranked view of the risks — the parts a scanner cannot produce.")
    console.write()
    console.item("Instructions", instructions_path)
    console.item("Open questions", os.path.join(output_dir, "agent", "enrichment-request.json"))
    console.item("Answer schema", os.path.join(output_dir, "agent", "enrichment.schema.json"))

    if args.write_agents_md:
        path, action = agentpack.write_agents_md(result, output_dir, repo_root,
                                                 args.write_agents_md)
        colour = "green" if action != "unchanged" else "grey"
        console.item(f"Agent file {action}", path, colour)

    detected = agentpack.detect_tools()
    console.header("Run one of these from " + repo_root)
    if detected:
        for key, label, _path in detected:
            console.write(f"  {console.paint(label.ljust(18), 'grey')} "
                          f"{console.paint(agentpack.command_for(key, output_dir, repo_root), 'cyan')}")
    else:
        console.write(console.paint("  No agent CLI found on this machine. Any of these work:",
                                    "grey"))
        for key, (label, _executable, _) in sorted(agentpack.AGENT_TOOLS.items()):
            console.write(f"  {console.paint(label.ljust(18), 'grey')} "
                          f"{console.paint(agentpack.command_for(key, output_dir, repo_root), 'cyan')}")
    console.write()
    console.write("  Or simply open your agent in the repository and tell it:")
    console.write(console.paint(f"    \"Follow {agentpack.display_path(instructions_path, repo_root)}\"",
                                "cyan"))
    console.header("When the agent is done")
    console.write(f"  {console.paint(f'repograph enrich {output_dir}', 'cyan')}")
    console.write("  Validates the answers, merges what passes, reports what it rejected,")
    console.write("  and re-renders every report with the model's contributions labelled.")
    console.write()

    if not args.run:
        return 0

    key = args.run.lower()
    if key not in agentpack.AGENT_TOOLS:
        console.write(console.paint(f"unknown agent '{args.run}'. Known: "
                                    f"{', '.join(sorted(agentpack.AGENT_TOOLS))}", "red"))
        return 2
    label, executable, _template = agentpack.AGENT_TOOLS[key]
    if not any(k == key for k, _, _ in detected):
        console.write(console.paint(f"{label} ({executable}) is not on PATH.", "red"))
        return 2
    command = agentpack.command_for(key, output_dir, repo_root)
    console.header("About to run", f"in {repo_root}")
    console.write(f"  {console.paint(command, 'cyan')}")
    console.write(console.paint("  This sends repository content to that tool's provider under "
                                "your own account.", "grey"))
    if not args.yes:
        try:
            answer = input("  continue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            console.write("  cancelled")
            return 0
    console.write()
    try:
        completed = subprocess.run(command, shell=True, cwd=repo_root, check=False)
    except OSError as exc:
        console.write(console.paint(f"could not start {executable}: {exc}", "red"))
        return 1
    if completed.returncode != 0:
        console.write(console.paint(f"{label} exited with code {completed.returncode}", "yellow"))
    enrichment = enrich_mod.enrichment_path(output_dir)
    if os.path.exists(enrichment):
        console.write(console.paint(f"\nfound {enrichment} — merging", "green"))
        return _merge(console, output_dir, enrichment, list(DEFAULT_FORMATS), True)
    console.write(console.paint(f"\nno {enrichment} was written; nothing to merge", "yellow"))
    return 0


def cmd_enrich(args) -> int:
    console = Console()
    path = os.path.abspath(args.path)
    if os.path.isfile(path):
        enrichment_file = path
        output_dir = _output_dir_of(path)
    else:
        output_dir = path
        enrichment_file = enrich_mod.enrichment_path(output_dir)
    if not os.path.exists(enrichment_file):
        console.write(console.paint(f"no enrichment file at {enrichment_file}", "red"))
        console.write(f"run  {console.paint(f'repograph agent {output_dir}', 'cyan')}  first")
        return 2
    formats = [] if args.no_render else _formats(args.format)
    return _merge(console, output_dir, enrichment_file, formats, not args.allow_unsupported)


def _merge(console: Console, output_dir: str, enrichment_file: str, formats: Sequence[str],
           require_evidence: bool) -> int:
    result = load_result(output_dir)
    try:
        data = enrich_mod.load_enrichment(enrichment_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        console.write(console.paint(f"could not read {enrichment_file}: {exc}", "red"))
        return 2

    enrichment, rejected = enrich_mod.apply(result, data, require_evidence=require_evidence)

    console.header("Enrichment merged", enrichment_file)
    console.item("Source", f"{enrichment.provenance.tool} {enrichment.provenance.model}".strip())
    console.item("Merged contributions", str(enrichment.answered_questions))
    console.item("Insights", str(len(enrichment.insights)))
    console.item("Rejected or corrected", str(len(rejected)), "yellow" if rejected else "")
    for reason in rejected[:10]:
        console.bullet(reason, "yellow")
    if enrichment.unanswered:
        console.item("Left unanswered", str(len(enrichment.unanswered)))

    if enrichment.answered_questions == 0 and not enrichment.insights:
        console.write(console.paint("\nnothing was merged — check the ids and the schema", "red"))
        return 1

    with open(os.path.join(output_dir, "repograph.json"), "w", encoding="utf-8") as handle:
        handle.write(result.to_json())

    if formats:
        rendered = render_all(result, output_dir, formats=formats,
                              progress=lambda message: console.status(message))
        console.clear_status()
        console.header("Re-rendered", output_dir)
        console.item("Files written", str(len(rendered.files)))
    console.write()
    return 0


def cmd_ask(args) -> int:
    console = Console()
    output_dir = _output_dir_of(args.output)
    try:
        result = load_result(output_dir)
    except SystemExit as exc:
        console.write(console.paint(str(exc), "red"))
        return 2
    repo_root = result.meta.root

    if args.suggest or not args.question:
        console.header(f"Questions worth asking about {result.meta.repo_name}",
                       "each one is derived from what the scan actually found")
        for index, question in enumerate(ask_mod.suggestions(result), start=1):
            console.write(f"  {console.paint(str(index) + '.', 'grey')} {question}")
        console.write()
        example = f'repograph ask "…" -o {output_dir}'
        console.write(f"  Ask one with:  {console.paint(example, 'cyan')}")
        console.write()
        return 0

    question = " ".join(args.question).strip()
    prompt = ask_mod.build_prompt(result, question, output_dir, repo_root)
    if args.print_prompt:
        print(prompt)
        return 0

    prompt_file = ask_mod.prompt_path(output_dir)
    os.makedirs(os.path.dirname(prompt_file), exist_ok=True)
    with open(prompt_file, "w", encoding="utf-8") as handle:
        handle.write(prompt)

    console.header("Question prepared", question)
    console.item("Prompt", prompt_file)
    console.write()
    console.write("  It points the agent at the scan first, so it answers from the map rather")
    console.write("  than reading the whole repository again.")

    detected = agentpack.detect_tools()
    console.header("Ask it from " + repo_root)
    tools = detected or [(key, label, "") for key, (label, _e, _t) in
                         sorted(agentpack.AGENT_TOOLS.items())]
    for key, label, _path in tools:
        command = agentpack.AGENT_TOOLS[key][2].format(
            instructions=agentpack.quoted_path(prompt_file, repo_root))
        console.write(f"  {console.paint(label.ljust(18), 'grey')} {console.paint(command, 'cyan')}")
    console.write()

    if not args.run:
        return 0
    key = args.run.lower()
    if key not in agentpack.AGENT_TOOLS:
        console.write(console.paint(f"unknown agent '{args.run}'", "red"))
        return 2
    if detected and not any(k == key for k, _, _ in detected):
        console.write(console.paint(f"{agentpack.AGENT_TOOLS[key][0]} is not on PATH", "red"))
        return 2
    command = agentpack.AGENT_TOOLS[key][2].format(
        instructions=agentpack.quoted_path(prompt_file, repo_root))
    console.header("About to run", f"in {repo_root}")
    console.write(f"  {console.paint(command, 'cyan')}")
    if not args.yes:
        try:
            answer = input("  continue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            console.write("  cancelled")
            return 0
    completed = subprocess.run(command, shell=True, cwd=repo_root, check=False)
    return completed.returncode


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
