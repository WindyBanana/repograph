"""Application and component discovery.

A repository is not automatically one application. This module finds the units
that are actually built and deployed separately (npm workspaces, Go modules,
Maven modules, .NET projects, ``apps/*`` conventions) and keeps them apart, then
splits each one into components so the diagrams have a readable granularity.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .manifests import Manifest
from .model import App, Component, Evidence
from .util import slug, title_case
from .walker import ScanFile

# Directory names that are conventionally containers of several apps.
MONOREPO_CONTAINERS = ("apps", "packages", "services", "projects", "modules", "libs",
                       "components", "functions", "workers", "cmd", "microservices", "src/apps")

# Directory names that hint at what an app is.
KIND_HINTS = (
    (re.compile(r"(^|/)(web|frontend|ui|client|www|site|portal|dashboard)($|/)", re.I), "frontend"),
    (re.compile(r"(^|/)(api|service|svc|server|backend|gateway)($|/)", re.I), "service"),
    (re.compile(r"(^|/)(cli|cmd|tools?|scripts?)($|/)", re.I), "cli"),
    (re.compile(r"(^|/)(worker|jobs?|cron|consumer|scheduler|batch)($|/)", re.I), "job"),
    (re.compile(r"(^|/)(lib|libs|packages?|shared|common|core|sdk)($|/)", re.I), "library"),
    (re.compile(r"(^|/)(infra|infrastructure|deploy|terraform|k8s|charts?|ops)($|/)", re.I), "infra"),
    (re.compile(r"(^|/)(docs?|documentation|website)($|/)", re.I), "docs"),
)

SOURCE_ROOTS = ("src", "lib", "app", "internal", "pkg", "source", "sources", "src/main/java",
                "src/main/kotlin", "src/main/scala", "cmd", "server", "client")

_STYLE_SIGNALS = {
    "Layered (controller / service / repository)": (
        ("controller", "controllers", "handler", "handlers"),
        ("service", "services", "usecase", "usecases"),
        ("repository", "repositories", "dao", "store", "stores"),
    ),
    "Hexagonal / Ports & Adapters": (
        ("domain",), ("application", "app"), ("adapters", "adapter", "ports", "infrastructure"),
    ),
    "Clean architecture": (
        ("entities", "domain"), ("usecases", "use_cases", "interactors"), ("interfaces", "gateways", "adapters"),
    ),
    "MVC": (("models", "model"), ("views", "view", "templates"), ("controllers", "controller")),
    "CQRS": (("commands", "command"), ("queries", "query"), ()),
    "Feature-sliced / modular": (("features", "modules"), (), ()),
    "Event-driven": (("events", "consumers", "producers", "subscribers", "listeners"), (), ()),
}


def _dirname(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _is_under(path: str, root: str) -> bool:
    if not root:
        return True
    return path == root or path.startswith(root + "/")


def expand_workspace_globs(root: str, patterns: Sequence[str], all_dirs: Iterable[str]) -> List[str]:
    """Resolve ``packages/*`` style workspace patterns against real directories."""
    out: List[str] = []
    dirs = list(all_dirs)
    for pattern in patterns:
        pattern = pattern.strip().strip("./")
        if not pattern:
            continue
        full = f"{root}/{pattern}" if root else pattern
        full = full.replace("/**", "/*")
        if "*" in full:
            out.extend(d for d in dirs if fnmatch.fnmatch(d, full) and not fnmatch.fnmatch(d, full + "/*"))
        else:
            full = full.rsplit("/", 1)[0] if full.endswith(("pom.xml", "package.json", "build.gradle")) else full
            if full in dirs:
                out.append(full)
    return sorted(set(out))


WEB_FRAMEWORKS = {
    "FastAPI", "Flask", "Django", "Starlette", "aiohttp", "Sanic", "Tornado", "Express",
    "NestJS", "Fastify", "Koa", "Hapi", "Spring", "Spring Boot", "JAX-RS", "Micronaut",
    "Quarkus", "Ktor", "ASP.NET Core", "ASP.NET Minimal API", "Gin", "Echo", "Chi", "Fiber",
    "Actix", "Axum", "Rocket", "Ruby on Rails", "Sinatra", "Laravel", "Symfony", "Phoenix",
}
FRONTEND_FRAMEWORKS = {"React", "Vue", "Angular", "Svelte", "Next.js", "Nuxt", "SwiftUI", "Flutter"}
JOB_FRAMEWORKS = {"Celery", "Sidekiq", "BullMQ", "Airflow", "Temporal"}


def infer_kind(path: str, manifest: Optional[Manifest], frameworks: Sequence[str],
               has_endpoints: bool, has_dockerfile: bool) -> str:
    """Evidence from the code outranks a manifest hint: a package that declares a
    console script but serves HTTP routes is a service, not a CLI."""
    fw = set(frameworks)
    if fw & FRONTEND_FRAMEWORKS:
        return "frontend"
    if has_endpoints and fw & WEB_FRAMEWORKS:
        return "service"
    if fw & JOB_FRAMEWORKS and not has_endpoints:
        return "job"
    if manifest is not None and manifest.kind_hint:
        return manifest.kind_hint
    for pattern, kind in KIND_HINTS:
        if pattern.search("/" + path):
            return kind
    if has_endpoints or has_dockerfile:
        return "service"
    return "application"


def infer_architecture_style(dir_names: Sequence[str], frameworks: Sequence[str],
                             endpoint_kinds: Sequence[str]) -> str:
    names = {d.lower() for d in dir_names}
    scores: List[Tuple[int, str]] = []
    for style, groups in _STYLE_SIGNALS.items():
        hits = sum(1 for group in groups if group and (names & set(group)))
        required = sum(1 for group in groups if group)
        if hits and hits >= max(1, required - 1):
            scores.append((hits, style))
    styles = [s for _, s in sorted(scores, reverse=True)]
    fw = set(frameworks)
    if "serverless" in names or fw & {"Serverless"}:
        styles.append("Serverless / function-per-endpoint")
    if fw & {"Django", "Ruby on Rails", "Laravel"}:
        styles.append("Framework MVC (batteries included)")
    if "graphql" in {k.lower() for k in endpoint_kinds}:
        styles.append("GraphQL API")
    if not styles:
        return "Unclassified (flat or ad-hoc layout)"
    seen, out = set(), []
    for style in styles:
        if style not in seen:
            seen.add(style)
            out.append(style)
    return " + ".join(out[:2])


class AppBuilder:
    def __init__(self, root: str, files: List[ScanFile], manifests: List[Manifest],
                 repo_name: str) -> None:
        self.root = root
        self.files = files
        self.manifests = manifests
        self.repo_name = repo_name
        self.dirs = sorted({_dirname(f.rel) for f in files if "/" in f.rel})
        self.dirs_set = set(self.dirs)

    # ------------------------------------------------------------------ apps
    def detect_app_roots(self) -> List[Tuple[str, Optional[Manifest]]]:
        roots: Dict[str, Optional[Manifest]] = {}
        workspace_members: List[str] = []

        for m in self.manifests:
            if m.workspaces:
                workspace_members.extend(expand_workspace_globs(m.dir, m.workspaces, self.dirs))

        for member in workspace_members:
            roots.setdefault(member, None)

        for m in self.manifests:
            if m.workspaces and not m.dependencies:
                continue  # pure workspace/aggregator manifest
            if m.path.rsplit("/", 1)[-1].lower() in ("pnpm-workspace.yaml", "lerna.json", "go.work"):
                continue
            roots.setdefault(m.dir, m)

        # Convention based: apps/<x>, services/<x> ... even without a manifest.
        for container in MONOREPO_CONTAINERS:
            for d in self.dirs:
                parent, _, name = d.rpartition("/")
                if parent == container and name and self._has_sources(d):
                    roots.setdefault(d, None)

        if not roots:
            roots[""] = None

        # Attach the best manifest to each root that lacks one.
        by_dir = {m.dir: m for m in self.manifests}
        resolved = []
        for path in sorted(roots):
            manifest = roots[path] or by_dir.get(path)
            resolved.append((path, manifest))

        return self._prune_roots(resolved)

    def _prune_roots(self, roots: List[Tuple[str, Optional[Manifest]]]) -> List[Tuple[str, Optional[Manifest]]]:
        """Drop parents that only exist to contain other app roots, and drop
        nested roots that carry no source of their own."""
        paths = [p for p, _ in roots]
        keep: List[Tuple[str, Optional[Manifest]]] = []
        for path, manifest in roots:
            children = [p for p in paths if p != path and _is_under(p, path)]
            own = self._own_source_count(path, children)
            if children and own < 3 and path != "":
                continue
            if children and own == 0 and path == "" and len(children) >= 1:
                continue
            if not children and not self._has_sources(path) and manifest is None:
                continue
            keep.append((path, manifest))
        if not keep:
            keep = [("", None)]
        return keep

    def _own_source_count(self, root: str, children: Sequence[str]) -> int:
        count = 0
        for f in self.files:
            if f.kind not in ("source", "test"):
                continue
            if not _is_under(f.rel, root):
                continue
            if any(_is_under(f.rel, c) for c in children):
                continue
            count += 1
        return count

    def _has_sources(self, root: str) -> bool:
        return any(f.kind == "source" and _is_under(f.rel, root) for f in self.files)

    def assign_files(self, app_roots: Sequence[str]) -> Dict[str, str]:
        """Map every file to the deepest matching app root."""
        ordered = sorted(app_roots, key=len, reverse=True)
        mapping: Dict[str, str] = {}
        for f in self.files:
            for root in ordered:
                if _is_under(f.rel, root):
                    mapping[f.rel] = root
                    break
            else:
                # A file above every application root belongs to the repository,
                # not to whichever application happens to sort last.
                mapping[f.rel] = "" if ordered and ordered[-1] else (ordered[-1] if ordered else "")
        return mapping

    # ------------------------------------------------------------ components
    def components_for(self, app: App, files: List[ScanFile], target_size: int = 0,
                       max_components: int = 40) -> List[Component]:
        """Split an app into components by descending the directory tree until
        each part is small enough to be a readable box in a diagram."""
        root = app.root
        # Aim for roughly 10-25 components: enough structure to be useful,
        # few enough that the diagrams stay readable.
        target_size = target_size or int(max(6, min(60, len(files) / 12)))
        tree: Dict[str, List[ScanFile]] = {}
        for f in files:
            inner = f.rel[len(root) + 1 :] if root and f.rel.startswith(root + "/") else f.rel
            directory = inner.rsplit("/", 1)[0] if "/" in inner else ""
            tree.setdefault(directory, []).append(f)

        groups = self._split("", tree, target_size, depth=0)
        components: List[Component] = []
        for key, members in sorted(groups.items()):
            langs: Dict[str, int] = {}
            for f in members:
                if f.is_code:
                    langs[f.language] = langs.get(f.language, 0) + 1
            path = "/".join(p for p in (root, key) if p)
            kinds = {f.kind for f in members}
            if kinds <= {"test"}:
                kind = "test"
            elif kinds <= {"infra", "config", "build"}:
                kind = "infra"
            elif kinds <= {"docs"}:
                kind = "docs"
            else:
                kind = "module"
            segments = [p for p in key.split("/") if p]
            display = "/".join(segments[-2:]) if segments else (
                root.rsplit("/", 1)[-1] if root else app.name
            )
            components.append(
                Component(
                    id=slug("c", path or app.id),
                    name=display,
                    path=path,
                    app=app.id,
                    kind=kind,
                    languages=[l for l, _ in sorted(langs.items(), key=lambda kv: -kv[1])][:3],
                    files=len(members),
                )
            )
        return self._merge_small(components, limit=max_components)

    def _split(self, prefix: str, tree: Dict[str, List[ScanFile]], target: int,
               depth: int) -> Dict[str, List[ScanFile]]:
        """Return {component path -> files} for everything under ``prefix``."""
        under = {d: fs for d, fs in tree.items() if d == prefix or (prefix == "" or d.startswith(prefix + "/"))}
        if prefix:
            under = {d: fs for d, fs in tree.items() if d == prefix or d.startswith(prefix + "/")}
        total = sum(len(fs) for fs in under.values())
        if not under:
            return {}
        if depth >= 3 or (total <= target and not (depth == 0 and total > 12)):
            return {prefix: [f for fs in under.values() for f in fs]}

        own = under.get(prefix, [])
        children: Dict[str, Dict[str, List[ScanFile]]] = {}
        for directory, fs in under.items():
            if directory == prefix:
                continue
            rest = directory[len(prefix) + 1 :] if prefix else directory
            head = rest.split("/", 1)[0]
            child_prefix = f"{prefix}/{head}" if prefix else head
            children.setdefault(child_prefix, {})[directory] = fs

        if not children:
            return {prefix: own}

        out: Dict[str, List[ScanFile]] = {}
        if own:
            out[prefix] = own
        # Walking through a directory that only contains one other directory is
        # not a structural decision, so it must not use up a depth level.
        next_depth = depth + 1 if len(children) > 1 else depth
        for child_prefix, subtree in children.items():
            out.update(self._split(child_prefix, subtree, target, next_depth))
        return out

    def _component_key(self, root: str, rel: str) -> str:
        inner = rel[len(root) + 1 :] if root and rel.startswith(root + "/") else rel
        parts = inner.split("/")
        return parts[0] if len(parts) > 1 else ""

    @staticmethod
    def _merge_small(components: List[Component], limit: int) -> List[Component]:
        if len(components) <= limit:
            return components
        components.sort(key=lambda c: -c.files)
        keep = components[: limit - 1]
        rest = components[limit - 1 :]
        merged = Component(
            id=slug("c", keep[0].app, "other"), name="(other)", path="", app=keep[0].app,
            kind="module", files=sum(c.files for c in rest),
            description=f"{len(rest)} smaller directories merged for readability",
        )
        keep.append(merged)
        return keep


SOURCE_ROOTS_SET = set(SOURCE_ROOTS) | {"src/main", "test", "tests", "spec"}


def readme_summary(text: str, max_chars: int = 400) -> str:
    """First real paragraph of a README, badges and headings removed."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith(("#", ">", "---", "===", "|", "<!--")):
            continue
        if re.fullmatch(r"[\[!\]\(\)\w\s/:.\-=?&+#]*", line) and line.count("](") >= 2:
            continue  # badge row
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"[*_`]", "", line)
        if line.strip():
            lines.append(line.strip())
        if sum(len(l) for l in lines) > max_chars:
            break
    text = " ".join(lines).strip()
    return (text[: max_chars - 1] + "…") if len(text) > max_chars else text


def build_apps(root: str, files: List[ScanFile], manifests: List[Manifest], repo_name: str,
               readmes: Dict[str, str], dockerfiles: Sequence[str],
               frameworks_by_file: Dict[str, List[str]],
               endpoint_files: Dict[str, List[str]]) -> Tuple[List[App], List[Component], Dict[str, str]]:
    builder = AppBuilder(root, files, manifests, repo_name)
    roots = builder.detect_app_roots()
    file_app = builder.assign_files([r for r, _ in roots])

    apps: List[App] = []
    components: List[Component] = []
    app_of_file: Dict[str, str] = {}

    for app_root, manifest in roots:
        members = [f for f in files if file_app.get(f.rel) == app_root]
        if not members:
            continue
        name = (manifest.name if manifest and manifest.name else "") or (
            app_root.rsplit("/", 1)[-1] if app_root else repo_name
        )
        app_id = slug("app", app_root or name)
        frameworks: Dict[str, int] = {}
        for f in members:
            for fw in frameworks_by_file.get(f.rel, []):
                frameworks[fw] = frameworks.get(fw, 0) + 1
        ranked_fw = [fw for fw, _ in sorted(frameworks.items(), key=lambda kv: -kv[1])]
        langs: Dict[str, int] = {}
        for f in members:
            if f.is_code:
                langs[f.language] = langs.get(f.language, 0) + 1
        has_dockerfile = any(_is_under(d, app_root) for d in dockerfiles)
        has_endpoints = any(f.rel in endpoint_files for f in members)
        dir_names = {p for f in members for p in f.rel.split("/")[:-1]}

        readme_key = next(
            (k for k in (f"{app_root}/README.md" if app_root else "README.md",
                         f"{app_root}/readme.md" if app_root else "readme.md") if k in readmes),
            "",
        )
        description = readme_summary(readmes[readme_key]) if readme_key else ""
        if not description and manifest is not None:
            description = manifest.description

        app = App(
            id=app_id,
            name=title_case(name) if not manifest or not manifest.name else name,
            root=app_root,
            kind=infer_kind(app_root or name, manifest, ranked_fw, has_endpoints, has_dockerfile),
            languages=[l for l, _ in sorted(langs.items(), key=lambda kv: -kv[1])],
            frameworks=ranked_fw[:12],
            manifests=[manifest.path] if manifest else [],
            files=len(members),
            description=description,
            architecture_style=infer_architecture_style(sorted(dir_names), ranked_fw, []),
        )
        if manifest is not None:
            app.entrypoints = [e for e in manifest.entrypoints if e][:6]
            app.evidence.append(Evidence(file=manifest.path, note="package manifest"))
        if readme_key:
            app.evidence.append(Evidence(file=readme_key, note="README"))
        for f in members:
            app_of_file[f.rel] = app_id
        app_components = builder.components_for(app, members)
        app.components = [c.id for c in app_components]
        components.extend(app_components)
        apps.append(app)

    return apps, components, app_of_file


# --------------------------------------------------------------- purpose

_STOP_SEGMENTS = {
    "api", "apis", "v1", "v2", "v3", "graphql", "rest", "rpc", "health", "healthz", "ready",
    "readyz", "live", "livez", "metrics", "status", "ping", "docs", "swagger", "openapi",
    "static", "assets", "public", "index", "root", "web", "app", "internal", "admin", "auth",
    "callback", "webhook", "webhooks", "_next", "favicon.ico",
}
_GENERIC_TYPES = {
    "config", "settings", "base", "main", "app", "application", "client", "server", "handler",
    "handlers", "service", "services", "repository", "manager", "helper", "helpers", "utils",
    "util", "error", "errors", "exception", "test", "tests", "mock", "factory", "builder",
    "request", "response", "options", "result", "context", "logger", "middleware", "router",
}
_CRUD_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _singular(word: str) -> str:
    lowered = word.lower()
    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"
    if lowered.endswith("ses") or lowered.endswith("xes"):
        return lowered[:-2]
    if lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def domain_nouns(endpoints: Sequence, symbols: Sequence, limit: int = 6) -> List[str]:
    """The subjects this application actually deals with.

    Route segments and entity type names beat a README, because they cannot go
    stale without the code changing too.
    """
    counts: Dict[str, int] = {}

    def bump(word: str, weight: int) -> None:
        # "fulfil_order" and "OrderLine" are two nouns each, not one.
        for token in re.split(r"[^a-zA-Z]+|(?<=[a-z0-9])(?=[A-Z])", str(word)):
            if len(token) < 3:
                continue
            noun = _singular(token)
            if noun in _STOP_SEGMENTS or noun in _GENERIC_TYPES:
                continue
            counts[noun] = counts.get(noun, 0) + weight

    for endpoint in endpoints:
        for segment in str(getattr(endpoint, "path", "")).split("/"):
            if not segment or segment.startswith(("{", ":", "<", "*", "$")):
                continue
            bump(segment, 3)
        handler = str(getattr(endpoint, "handler", ""))
        for part in re.split(r"[._]|(?<=[a-z])(?=[A-Z])", handler):
            bump(part, 1)

    for symbol in symbols:
        if symbol.kind in ("class", "struct", "record", "table", "message", "interface", "entity"):
            name = symbol.name.rsplit(".", 1)[-1]
            for suffix in ("Controller", "Service", "Repository", "Handler", "Model", "Entity",
                           "Dto", "DTO", "Schema", "Resource", "Manager"):
                if name.endswith(suffix) and len(name) > len(suffix):
                    name = name[: -len(suffix)]
                    break
            for part in re.split(r"(?<=[a-z0-9])(?=[A-Z])|_", name):
                bump(part, 2)

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [noun for noun, weight in ranked if weight > 1][:limit]


def infer_purpose(app: App, endpoints: Sequence, symbols: Sequence,
                  systems: Sequence, dependent_names: Sequence[str] = (),
                  depends_on_names: Sequence[str] = ()) -> str:
    """A one-paragraph description derived only from code, for when there is no
    README — or when the README no longer matches what the code does."""
    nouns = domain_nouns(endpoints, symbols)
    http = [e for e in endpoints if e.kind in ("http", "graphql", "grpc", "websocket")]
    events = [e for e in endpoints if e.kind in ("event", "cron")]
    commands = [e for e in endpoints if e.kind == "cli"]
    stores = [s.name for s in systems if s.kind in ("database", "cache", "storage", "search")]
    integrations = [s.name for s in systems if s.kind in ("api", "queue", "payment", "auth",
                                                          "mail", "ai")]

    role = {
        "service": "Backend service", "frontend": "User interface", "job": "Background worker",
        "library": "Shared library", "cli": "Command line tool", "infra": "Infrastructure code",
        "docs": "Documentation",
    }.get(app.kind, "Application")

    sentences: List[str] = []
    subject = ", ".join(nouns[:4]) if nouns else ""
    opening = f"{role} written in {app.languages[0]}" if app.languages else role
    if app.frameworks:
        opening += f" using {', '.join(app.frameworks[:2])}"
    if subject:
        opening += f", built around {subject}"
    sentences.append(opening + ".")

    if http:
        methods = {e.method for e in http}
        shape = "CRUD-style" if methods & _CRUD_METHODS and "GET" in methods else "read-oriented"
        sentences.append(f"Exposes {len(http)} {shape} endpoint(s)"
                         + (f" over {', '.join(nouns[:3])}" if nouns else "") + ".")
    if events:
        sentences.append(f"Reacts to {len(events)} event or scheduled trigger(s).")
    if commands:
        sentences.append(f"Provides {len(commands)} command line entrypoint(s).")
    if not (http or events or commands) and app.kind == "library":
        sentences.append("Has no entrypoints of its own; it is consumed by other code"
                         + (f" ({', '.join(dependent_names[:3])})" if dependent_names else "") + ".")
    if stores:
        sentences.append(f"Persists or caches data in {', '.join(dict.fromkeys(stores))[:120]}.")
    if integrations:
        sentences.append(f"Talks to {', '.join(dict.fromkeys(integrations))[:140]}.")
    if depends_on_names:
        sentences.append(f"Uses {', '.join(dict.fromkeys(depends_on_names))[:120]} from this repository.")
    if dependent_names and app.kind != "library":
        sentences.append(f"Depended on by {', '.join(dependent_names[:4])}.")
    return " ".join(sentences)
