"""A local desktop UI for repograph.

A small HTTP server bound to localhost, serving one page and a handful of JSON
endpoints. It exists so nobody has to open a terminal to scan a repository, and
so the packaged Windows/macOS/Linux applications have something to open.

Security: the server binds to 127.0.0.1 only, mints a random token per run that
every request must carry, and rejects cross-origin requests. Without that, any
web page open in the same browser could drive a local scanner.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import secrets
import socket
import socketserver
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from repograph_core import ask as ask_mod
from repograph_core.scan import VERSION, ScanOptions, scan
from repograph_render.render import DEFAULT_FORMATS, render_all

from .assets import page

MAX_LOG = 400


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "repograph")
    os.makedirs(path, exist_ok=True)
    return path


def history_path() -> str:
    return os.path.join(config_dir(), "history.json")


def load_history() -> List[Dict[str, str]]:
    try:
        with open(history_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return [e for e in data if isinstance(e, dict) and e.get("path")][:12]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def remember(path: str, output_dir: str) -> None:
    entries = [e for e in load_history() if e.get("path") != path]
    entries.insert(0, {
        "path": path,
        "output": output_dir,
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    })
    try:
        with open(history_path(), "w", encoding="utf-8") as handle:
            json.dump(entries[:12], handle, indent=2)
    except OSError:
        pass


@dataclass
class Job:
    state: str = "idle"          # idle | running | done | error
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str = ""
    output_dir: str = ""
    log: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    documents: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "state": self.state, "stage": self.stage, "done": self.done,
                "total": self.total, "error": self.error, "output_dir": self.output_dir,
                "log": list(self.log[-40:]), "summary": dict(self.summary),
                "documents": list(self.documents), "questions": list(self.questions),
            }

    def note(self, stage: str, done: int = 0, total: int = 0) -> None:
        with self.lock:
            self.stage = stage
            self.done = done
            self.total = total
            if not self.log or self.log[-1] != stage:
                self.log.append(stage)
                del self.log[:-MAX_LOG]


def run_scan(job: Job, request: Dict[str, Any]) -> None:
    try:
        root = os.path.abspath(os.path.expanduser(str(request.get("path", "")).strip()))
        if not os.path.isdir(root):
            raise ValueError(f"{root} is not a folder")
        output_dir = str(request.get("output", "")).strip()
        output_dir = os.path.abspath(os.path.expanduser(output_dir)) if output_dir \
            else os.path.join(root, "repograph-out")

        with job.lock:
            job.state = "running"
            job.error = ""
            job.log = []
            job.output_dir = output_dir
            job.summary = {}
            job.documents = []
            job.questions = []

        options = ScanOptions(
            root=root,
            online=bool(request.get("online")),
            git_history=not bool(request.get("no_git")),
            everything=bool(request.get("everything")),
            progress=lambda stage, done, total: job.note(stage, done, total),
        )
        result = scan(options)
        render_all(result, output_dir, formats=DEFAULT_FORMATS,
                   progress=lambda message: job.note(message))
        remember(root, output_dir)

        business = result.business or {}
        documents = [name for name in ("report.pdf", "presentation.pptx", "report.xlsx",
                                       "BUSINESS-OVERVIEW.md", "AI-REPORT.md")
                     if os.path.exists(os.path.join(output_dir, name))]
        with job.lock:
            job.state = "done"
            job.stage = "Done"
            job.documents = documents
            job.questions = ask_mod.suggestions(result, limit=6)
            job.summary = {
                "name": result.meta.repo_name,
                "label": (result.profile or {}).get("label", ""),
                "what_it_is": business.get("what_it_is", ""),
                "apps": result.metrics.apps,
                "endpoints": result.metrics.endpoints,
                "systems": result.metrics.external_systems,
                "findings": sum(result.metrics.findings_by_severity.values()),
                "files": result.metrics.scanned_files,
                "loc": result.metrics.loc,
            }
    except Exception as exc:  # a failed scan must not take the UI down
        with job.lock:
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"


COOKIE_NAME = "repograph_session"


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = f"repograph/{VERSION}"
    token = ""
    job: Job = Job()

    def log_message(self, fmt: str, *args) -> None:  # keep the terminal quiet
        return

    # ---------------------------------------------------------------- guards
    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                return urllib.parse.unquote(value)
        return ""

    def _authorised(self, query: Dict[str, List[str]], allow_cookie: bool = False) -> bool:
        # The report links to its own siblings with plain relative hrefs, so those
        # requests cannot carry the token in the query. A SameSite=Strict cookie is
        # never sent by another site, which is exactly the guarantee the token gives
        # here — but it is only honoured for reading already-rendered files, never
        # for the API or for starting a scan.
        supplied = (query.get("t") or [""])[0]
        if not secrets.compare_digest(supplied, self.token):
            if not (allow_cookie and secrets.compare_digest(self._cookie_token(), self.token)):
                return False
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
            return False
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "")

    def _send(self, code: int, body: bytes, content_type: str, cookie: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={urllib.parse.quote(cookie)}; Path=/; SameSite=Strict; HttpOnly",
            )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload: Dict[str, Any], code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    # ------------------------------------------------------------- requests
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send(200, page(VERSION, self.token).encode(), "text/html; charset=utf-8",
                       cookie=self.token)
            return
        if not self._authorised(query, allow_cookie=path.startswith("/report/")):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if path == "/api/status":
            self._json(self.job.snapshot())
            return
        if path == "/api/recent":
            self._json({"entries": load_history()})
            return
        if path == "/api/browse":
            self._json(self._browse((query.get("path") or [""])[0]))
            return
        if path.startswith("/report/"):
            self._serve_report(path[len("/report/"):])
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not self._authorised(query):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if parsed.path != "/api/scan":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid request"}, 400)
            return
        with self.job.lock:
            if self.job.state == "running":
                self._json({"error": "a scan is already running"}, 409)
                return
            self.job.state = "running"
            self.job.stage = "Starting"
        threading.Thread(target=run_scan, args=(self.job, request), daemon=True).start()
        self._json({"started": True})

    # -------------------------------------------------------------- helpers
    def _browse(self, path: str) -> Dict[str, Any]:
        path = os.path.abspath(os.path.expanduser(path)) if path.strip() \
            else os.path.expanduser("~")
        if not os.path.isdir(path):
            path = os.path.expanduser("~")
        entries = []
        try:
            for name in sorted(os.listdir(path)):
                if name.startswith("."):
                    continue
                child = os.path.join(path, name)
                if not os.path.isdir(child):
                    continue
                entries.append({
                    "name": name,
                    "path": child,
                    "repo": os.path.isdir(os.path.join(child, ".git")),
                })
        except PermissionError:
            entries = []
        parent = os.path.dirname(path.rstrip(os.sep))
        return {
            "path": path,
            "parent": parent if parent and parent != path else None,
            "entries": entries[:400],
        }

    def _serve_report(self, relative: str) -> None:
        output_dir = self.job.snapshot().get("output_dir") or ""
        if not output_dir:
            self._send(404, b"no report yet", "text/plain; charset=utf-8")
            return
        relative = urllib.parse.unquote(relative.split("?")[0])
        target = os.path.normpath(os.path.join(output_dir, relative))
        if not target.startswith(os.path.abspath(output_dir)) or not os.path.isfile(target):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        content_type, _ = mimetypes.guess_type(target)
        with open(target, "rb") as handle:
            body = handle.read()
        self._send(200, body, content_type or "application/octet-stream")


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def free_port(preferred: int) -> int:
    for candidate in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    return 0


def serve(path: str = "", port: int = 7373, open_browser: bool = True,
          quiet: bool = False) -> int:
    token = secrets.token_urlsafe(24)
    chosen = free_port(port)
    handler = type("BoundHandler", (Handler,), {"token": token, "job": Job()})
    url = f"http://127.0.0.1:{chosen}/?t={token}"

    with Server(("127.0.0.1", chosen), handler) as httpd:
        if not quiet:
            # flush: when the app is launched from a desktop, stdout is a pipe and
            # a buffered URL is a URL nobody ever sees.
            print(f"repograph {VERSION} — desktop UI", flush=True)
            print(f"  {url}", flush=True)
            print("  bound to localhost only; press ctrl-c to stop", flush=True)
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            if not quiet:
                print("\nstopped")
    return 0
