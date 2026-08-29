"""Python analyzer. Uses the real ``ast`` module, falling back to regex."""

from __future__ import annotations

import ast
import re
from typing import List

from ..model import Endpoint, Symbol
from .base import Analysis, ImportRef, each_match, normalise_route, register

FRAMEWORK_MARKERS = {
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "Django": ("django",),
    "Starlette": ("starlette",),
    "aiohttp": ("aiohttp",),
    "Sanic": ("sanic",),
    "Tornado": ("tornado",),
    "Celery": ("celery",),
    "SQLAlchemy": ("sqlalchemy",),
    "Pydantic": ("pydantic",),
    "Click": ("click",),
    "Typer": ("typer",),
    "pytest": ("pytest",),
    "Pandas": ("pandas",),
    "Airflow": ("airflow",),
    "Boto3": ("boto3", "botocore"),
    "gRPC": ("grpc",),
    "Strawberry GraphQL": ("strawberry",),
    "Graphene": ("graphene",),
}

_ROUTE_DECORATORS = {"route", "get", "post", "put", "patch", "delete", "head", "options", "websocket"}
_TASK_DECORATORS = {"task", "shared_task", "celery_task", "periodic_task"}


def _decorator_call(node: ast.AST):
    if isinstance(node, ast.Call):
        return node
    return None


def _attr_chain(node: ast.AST) -> str:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _const_str(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _methods_from_keywords(call: ast.Call) -> List[str]:
    for kw in call.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            return [_const_str(e).upper() for e in kw.value.elts if _const_str(e)]
    return []


@register("Python")
def analyze_python(rel: str, text: str) -> Analysis:
    result = Analysis()
    lowered = text.lower()
    for name, needles in FRAMEWORK_MARKERS.items():
        if any(re.search(rf"\b{re.escape(n)}\b", lowered) for n in needles):
            result.frameworks.append(name)

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return _regex_fallback(rel, text, result)

    doc = ast.get_docstring(tree)
    if doc:
        result.doc = doc.strip().splitlines()[0][:300]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.imports.append(
                    ImportRef(module=alias.name, line=node.lineno, raw=f"import {alias.name}")
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * (node.level or 0)
            result.imports.append(
                ImportRef(
                    module=prefix + module,
                    line=node.lineno,
                    raw=f"from {prefix}{module} import ...",
                    relative=bool(node.level),
                    names=[a.name for a in node.names],
                )
            )

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: List[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            bases = [_attr_chain(b) for b in node.bases]
            result.symbols.append(
                Symbol(
                    name=node.name,
                    kind="class",
                    file=rel,
                    line=node.lineno,
                    signature=f"class {node.name}({', '.join(b for b in bases if b)})",
                    doc=(ast.get_docstring(node) or "").strip().splitlines()[0][:200]
                    if ast.get_docstring(node)
                    else "",
                    exported=not node.name.startswith("_"),
                )
            )
            self._decorators(node, node.name)
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def _function(self, node) -> None:
            qual = ".".join(self.stack + [node.name])
            args = [a.arg for a in node.args.args]
            result.symbols.append(
                Symbol(
                    name=qual,
                    kind="method" if self.stack else "function",
                    file=rel,
                    line=node.lineno,
                    signature=f"def {node.name}({', '.join(args)})",
                    doc=(ast.get_docstring(node) or "").strip().splitlines()[0][:200]
                    if ast.get_docstring(node)
                    else "",
                    exported=not node.name.startswith("_"),
                )
            )
            self._decorators(node, qual)
            self.generic_visit(node)

        visit_FunctionDef = _function  # noqa: N815
        visit_AsyncFunctionDef = _function  # noqa: N815

        def _decorators(self, node, qual: str) -> None:
            for dec in getattr(node, "decorator_list", []):
                call = _decorator_call(dec)
                target = call.func if call else dec
                chain = _attr_chain(target)
                if not chain:
                    continue
                last = chain.rsplit(".", 1)[-1]
                if last in _ROUTE_DECORATORS and call and call.args:
                    path = _const_str(call.args[0])
                    if not path:
                        continue
                    methods = _methods_from_keywords(call) or (
                        [last.upper()] if last != "route" else ["GET"]
                    )
                    if last == "websocket":
                        methods = ["WS"]
                    for method in methods:
                        result.endpoints.append(
                            Endpoint(
                                kind="websocket" if method == "WS" else "http",
                                method=method,
                                path=normalise_route("", path),
                                handler=qual,
                                file=rel,
                                line=node.lineno,
                                framework=_guess_framework(chain, result.frameworks),
                            )
                        )
                elif last in _TASK_DECORATORS:
                    result.endpoints.append(
                        Endpoint(
                            kind="event",
                            method="TASK",
                            path=qual,
                            handler=qual,
                            file=rel,
                            line=node.lineno,
                            framework="Celery",
                        )
                    )
                elif last in ("command", "group") and "click" in chain or "typer" in chain:
                    result.endpoints.append(
                        Endpoint(
                            kind="cli",
                            method="CMD",
                            path=qual,
                            handler=qual,
                            file=rel,
                            line=node.lineno,
                            framework="Click/Typer",
                        )
                    )

    Visitor().visit(tree)
    _django_urls(rel, tree, result)
    _add_route_calls(rel, text, result)

    if re.search(r"^if\s+__name__\s*==\s*[\"']__main__[\"']", text, re.M):
        result.entrypoint = True
    return result


def _guess_framework(chain: str, frameworks: List[str]) -> str:
    for fw in ("FastAPI", "Flask", "Sanic", "Starlette", "aiohttp"):
        if fw in frameworks:
            return fw
    return chain.split(".")[0]


def _django_urls(rel: str, tree: ast.AST, result: Analysis) -> None:
    if not rel.endswith("urls.py"):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = _attr_chain(node.func)
        if fname.rsplit(".", 1)[-1] not in ("path", "re_path", "url"):
            continue
        if not node.args:
            continue
        route = _const_str(node.args[0])
        handler = _attr_chain(node.args[1].func) if len(node.args) > 1 and isinstance(node.args[1], ast.Call) else (
            _attr_chain(node.args[1]) if len(node.args) > 1 else ""
        )
        result.endpoints.append(
            Endpoint(
                kind="http",
                method="ANY",
                path=normalise_route("", route),
                handler=handler,
                file=rel,
                line=node.lineno,
                framework="Django",
            )
        )


_ADD_ROUTE = re.compile(
    r"""(?:add_url_rule|add_route|router\.add_api_route|app\.add_api_route)\s*\(\s*["']([^"']+)["']"""
)
_AIOHTTP = re.compile(r"""(?:router|app)\.add_(get|post|put|patch|delete|route)\s*\(\s*["']([^"']+)["']""")


def _add_route_calls(rel: str, text: str, result: Analysis) -> None:
    for m, line in each_match(_ADD_ROUTE, text):
        result.endpoints.append(
            Endpoint(kind="http", method="ANY", path=normalise_route("", m.group(1)),
                     file=rel, line=line, framework="Python")
        )
    for m, line in each_match(_AIOHTTP, text):
        result.endpoints.append(
            Endpoint(kind="http", method=m.group(1).upper(), path=normalise_route("", m.group(2)),
                     file=rel, line=line, framework="aiohttp")
        )


_IMPORT_RE = re.compile(r"^\s*(?:from\s+([.\w]+)\s+import|import\s+([\w.]+))", re.M)


def _regex_fallback(rel: str, text: str, result: Analysis) -> Analysis:
    for m, line in each_match(_IMPORT_RE, text):
        module = m.group(1) or m.group(2) or ""
        if module:
            result.imports.append(
                ImportRef(module=module, line=line, raw=m.group(0).strip(), relative=module.startswith("."))
            )
    for m, line in each_match(re.compile(r"^\s*(?:async\s+)?def\s+(\w+)", re.M), text):
        result.symbols.append(Symbol(name=m.group(1), kind="function", file=rel, line=line))
    for m, line in each_match(re.compile(r"^\s*class\s+(\w+)", re.M), text):
        result.symbols.append(Symbol(name=m.group(1), kind="class", file=rel, line=line))
    return result
