"""JavaScript / TypeScript / Vue / Svelte analyzer (regex based, no parser needed)."""

from __future__ import annotations

import re
from typing import List

from ..model import Endpoint, Symbol
from .base import Analysis, ImportRef, each_match, normalise_route, register, strip_block_comments

FRAMEWORK_MARKERS = {
    "React": (r"from\s+['\"]react['\"]", r"React\."),
    "Next.js": (r"from\s+['\"]next[/'\"]", r"next/server"),
    "Vue": (r"from\s+['\"]vue['\"]",),
    "Angular": (r"@angular/",),
    "Svelte": (r"from\s+['\"]svelte",),
    "Express": (r"from\s+['\"]express['\"]", r"require\(['\"]express['\"]\)"),
    "NestJS": (r"@nestjs/",),
    "Fastify": (r"['\"]fastify['\"]",),
    "Koa": (r"['\"]koa['\"]",),
    "Hapi": (r"@hapi/",),
    "tRPC": (r"@trpc/",),
    "GraphQL": (r"graphql", r"apollo"),
    "Prisma": (r"@prisma/", r"PrismaClient"),
    "TypeORM": (r"typeorm",),
    "Sequelize": (r"sequelize",),
    "Mongoose": (r"mongoose",),
    "Socket.IO": (r"socket\.io",),
    "Jest": (r"['\"]jest['\"]", r"\bdescribe\(", ),
    "Vitest": (r"['\"]vitest['\"]",),
    "Playwright": (r"@playwright/",),
    "AWS SDK": (r"aws-sdk", r"@aws-sdk/"),
    "Electron": (r"['\"]electron['\"]",),
    "Redux": (r"['\"]redux['\"]", r"@reduxjs/"),
    "Tailwind": (r"tailwind",),
}

_IMPORT_FROM = re.compile(
    r"""^\s*(?:import|export)\s+(?:type\s+)?(?:[\w*{},\s\n]+?\s+from\s+)?['"]([^'"]+)['"]""",
    re.M,
)
_IMPORT_SIDE = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.M)
_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_DYNAMIC = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")

_EXPORT_FN = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.M)
_EXPORT_CLASS = re.compile(r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)", re.M)
_EXPORT_CONST = re.compile(r"^\s*export\s+(?:const|let|var)\s+(\w+)", re.M)
_EXPORT_TYPE = re.compile(r"^\s*export\s+(?:interface|type|enum)\s+(\w+)", re.M)
_LOCAL_CLASS = re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)", re.M)
_LOCAL_FN = re.compile(r"^\s*(?:async\s+)?function\s+(\w+)", re.M)

_ROUTE_CALL = re.compile(
    r"""\b(?:app|router|server|api|fastify|route[rs]?)\w*\.(get|post|put|patch|delete|head|options|all|use)\s*\(\s*[`'"]([^`'"]+)[`'"]""",
)
_NEST_CONTROLLER = re.compile(r"""@Controller\(\s*[`'"]?([^`'")]*)[`'"]?\s*\)""")
_NEST_METHOD = re.compile(
    r"""@(Get|Post|Put|Patch|Delete|Options|Head|All|Sse)\(\s*[`'"]?([^`'")]*)[`'"]?\s*\)\s*(?:async\s+)?(\w+)?""",
)
_NEST_EVENT = re.compile(r"""@(EventPattern|MessagePattern|SubscribeMessage|Cron|Interval)\(\s*[`'"]?([^`'")]*)""")
_TRPC_PROC = re.compile(r"""^\s*(\w+)\s*:\s*(?:publicProcedure|protectedProcedure|t\.procedure)""", re.M)
_LAMBDA = re.compile(r"""^\s*(?:export\s+const|exports?\.)\s*(handler|main)\b""", re.M)
_GRAPHQL_OP = re.compile(r"""^\s*(?:type\s+)?(Query|Mutation|Subscription)\s*[:{]""", re.M)


@register("JavaScript", "TypeScript", "Vue", "Svelte")
def analyze_js(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)

    for name, patterns in FRAMEWORK_MARKERS.items():
        if any(re.search(p, body) for p in patterns):
            result.frameworks.append(name)

    seen = set()
    for pattern in (_IMPORT_FROM, _IMPORT_SIDE, _REQUIRE, _DYNAMIC):
        for m, line in each_match(pattern, body):
            module = m.group(1)
            if (module, line) in seen:
                continue
            seen.add((module, line))
            result.imports.append(
                ImportRef(
                    module=module,
                    line=line,
                    raw=m.group(0).strip()[:120],
                    relative=module.startswith("."),
                )
            )

    for pattern, kind in (
        (_EXPORT_FN, "function"),
        (_EXPORT_CLASS, "class"),
        (_EXPORT_CONST, "const"),
        (_EXPORT_TYPE, "interface"),
    ):
        for m, line in each_match(pattern, body):
            result.symbols.append(Symbol(name=m.group(1), kind=kind, file=rel, line=line, exported=True))
    exported = {s.name for s in result.symbols}
    for pattern, kind in ((_LOCAL_CLASS, "class"), (_LOCAL_FN, "function")):
        for m, line in each_match(pattern, body):
            if m.group(1) not in exported:
                result.symbols.append(
                    Symbol(name=m.group(1), kind=kind, file=rel, line=line, exported=False)
                )

    _http_routes(rel, body, result)
    _nest(rel, body, result)
    _file_routes(rel, body, result)

    for m, line in each_match(_TRPC_PROC, body):
        result.endpoints.append(
            Endpoint(kind="http", method="RPC", path=m.group(1), handler=m.group(1),
                     file=rel, line=line, framework="tRPC")
        )
    for m, line in each_match(_LAMBDA, body):
        result.endpoints.append(
            Endpoint(kind="function", method="INVOKE", path=rel, handler=m.group(1),
                     file=rel, line=line, framework="Serverless")
        )
        result.entrypoint = True

    if re.search(r"^\s*(?:#!.*node|require\(['\"]yargs|commander)", body, re.M):
        result.entrypoint = True
    return result


def _http_routes(rel: str, body: str, result: Analysis) -> None:
    for m, line in each_match(_ROUTE_CALL, body):
        method, path = m.group(1), m.group(2)
        if method == "use" and not path.startswith("/"):
            continue
        if not path.startswith("/") and "*" not in path:
            continue
        result.endpoints.append(
            Endpoint(
                kind="http",
                method="ANY" if method in ("use", "all") else method.upper(),
                path=normalise_route("", path),
                file=rel,
                line=line,
                framework=_first(result.frameworks, ("Express", "Fastify", "Koa", "Hapi")) or "Node HTTP",
            )
        )


def _nest(rel: str, body: str, result: Analysis) -> None:
    controller = _NEST_CONTROLLER.search(body)
    if controller is None and "@nestjs/" not in body:
        return
    base = controller.group(1) if controller else ""
    for m, line in each_match(_NEST_METHOD, body):
        result.endpoints.append(
            Endpoint(
                kind="http",
                method=m.group(1).upper(),
                path=normalise_route(base, m.group(2)),
                handler=m.group(3) or "",
                file=rel,
                line=line,
                framework="NestJS",
            )
        )
    for m, line in each_match(_NEST_EVENT, body):
        result.endpoints.append(
            Endpoint(kind="event", method=m.group(1).upper(), path=m.group(2) or rel,
                     file=rel, line=line, framework="NestJS")
        )


_NEXT_METHOD_EXPORT = re.compile(
    r"^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.M)


def _file_routes(rel: str, body: str, result: Analysis) -> None:
    """Next.js / SvelteKit / Nuxt file-system routing."""
    lower = rel.lower()
    if "/pages/api/" in "/" + lower or lower.startswith("pages/api/"):
        route = re.sub(r".*?pages/api", "/api", lower)
        route = re.sub(r"\.(js|ts|jsx|tsx)$", "", route)
        route = re.sub(r"/index$", "", route) or "/api"
        result.endpoints.append(
            Endpoint(kind="http", method="ANY", path=route, file=rel, line=1, framework="Next.js")
        )
        return
    if re.search(r"(^|/)app/.*/route\.[jt]sx?$", rel):
        route = re.sub(r".*?(^|/)app", "", rel)
        route = re.sub(r"/route\.[jt]sx?$", "", route) or "/"
        route = re.sub(r"/\((\w+)\)", "", route)
        methods = [m.group(1) for m in _NEXT_METHOD_EXPORT.finditer(body)] or ["ANY"]
        for method in methods:
            result.endpoints.append(
                Endpoint(kind="http", method=method, path=route or "/", file=rel, line=1, framework="Next.js")
            )
        return
    if re.search(r"\+server\.[jt]s$", rel):
        route = re.sub(r".*?routes", "", rel)
        route = re.sub(r"/\+server\.[jt]s$", "", route) or "/"
        methods = [m.group(1) for m in _NEXT_METHOD_EXPORT.finditer(body)] or ["ANY"]
        for method in methods:
            result.endpoints.append(
                Endpoint(kind="http", method=method, path=route, file=rel, line=1, framework="SvelteKit")
            )


def _first(items: List[str], preferred) -> str:
    for p in preferred:
        if p in items:
            return p
    return ""
