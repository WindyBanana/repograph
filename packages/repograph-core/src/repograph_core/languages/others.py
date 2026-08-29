"""Analyzers for the remaining languages. Regex based and deliberately lenient."""

from __future__ import annotations

import re

from ..model import Endpoint, Symbol
from .base import Analysis, ImportRef, each_match, normalise_route, register, strip_block_comments

# --------------------------------------------------------------------------- Go

_GO_IMPORT_BLOCK = re.compile(r"import\s*\(([^)]*)\)", re.S)
_GO_IMPORT_ONE = re.compile(r"""^\s*import\s+(?:\w+\s+)?"([^"]+)\"""", re.M)
_GO_IMPORT_LINE = re.compile(r"""^\s*(?:[\w.]+\s+)?"([^"]+)\"""", re.M)
_GO_FUNC = re.compile(r"^func\s+(?:\(\s*\w+\s+\*?(\w+)\s*\)\s*)?(\w+)\s*\(", re.M)
_GO_TYPE = re.compile(r"^type\s+(\w+)\s+(struct|interface)\b", re.M)
_GO_ROUTE = re.compile(
    r"""\b(?:\w+)\.(HandleFunc|Handle|GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete|Any)\s*\(\s*"([^"]+)"(?:\s*,\s*"([^"]+)")?""",
)
_GO_FRAMEWORKS = {
    "Gin": "gin-gonic", "Echo": "labstack/echo", "Chi": "go-chi/chi", "Fiber": "gofiber",
    "gorilla/mux": "gorilla/mux", "gRPC": "google.golang.org/grpc", "GORM": "gorm.io",
    "sqlx": "jmoiron/sqlx", "Cobra": "spf13/cobra", "Kafka": "segmentio/kafka-go",
}


@register("Go")
def analyze_go(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for block in _GO_IMPORT_BLOCK.finditer(body):
        start_line = body.count("\n", 0, block.start()) + 1
        for m in _GO_IMPORT_LINE.finditer(block.group(1)):
            result.imports.append(
                ImportRef(module=m.group(1), line=start_line + block.group(1).count("\n", 0, m.start()))
            )
    for m, line in each_match(_GO_IMPORT_ONE, body):
        result.imports.append(ImportRef(module=m.group(1), line=line))
    for m, line in each_match(_GO_FUNC, body):
        receiver, name = m.group(1), m.group(2)
        result.symbols.append(
            Symbol(name=f"{receiver}.{name}" if receiver else name,
                   kind="method" if receiver else "function",
                   file=rel, line=line, exported=name[:1].isupper())
        )
        if name == "main":
            result.entrypoint = True
    for m, line in each_match(_GO_TYPE, body):
        result.symbols.append(Symbol(name=m.group(1), kind=m.group(2), file=rel, line=line,
                                     exported=m.group(1)[:1].isupper()))
    for name, needle in _GO_FRAMEWORKS.items():
        if needle in body:
            result.frameworks.append(name)
    for m, line in each_match(_GO_ROUTE, body):
        verb, first, second = m.group(1), m.group(2), m.group(3)
        if verb in ("HandleFunc", "Handle") and second:
            method, path = first.upper(), second
        elif verb in ("HandleFunc", "Handle"):
            method, path = "ANY", first
        else:
            method, path = verb.upper(), first
        if not path.startswith("/"):
            continue
        result.endpoints.append(
            Endpoint(kind="http", method=method, path=path, file=rel, line=line,
                     framework=result.frameworks[0] if result.frameworks else "net/http")
        )
    return result


# ------------------------------------------------------------------ JVM family

_JVM_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)", re.M)
_JVM_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)", re.M)
_JVM_TYPE = re.compile(r"^\s*(?:public\s+|private\s+|internal\s+|open\s+|final\s+|abstract\s+|sealed\s+|data\s+)*"
                       r"(class|interface|enum|record|object|trait)\s+(\w+)", re.M)
_SPRING_MAPPING = re.compile(
    r"""@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[{\s]*["']([^"']*)["']?""",
)
_SPRING_CLASS = re.compile(r"""@RequestMapping\s*\(\s*(?:value\s*=\s*)?["']([^"']+)["']""")
_JAXRS_PATH = re.compile(r"""@Path\s*\(\s*["']([^"']+)["']\s*\)""")
_JAXRS_METHOD = re.compile(r"@(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b")
_JVM_FRAMEWORKS = {
    "Spring Boot": "org.springframework.boot", "Spring": "org.springframework",
    "Jakarta EE": "jakarta.", "JAX-RS": "javax.ws.rs", "Hibernate": "org.hibernate",
    "JPA": "javax.persistence", "Kafka": "org.apache.kafka", "Micronaut": "io.micronaut",
    "Quarkus": "io.quarkus", "Ktor": "io.ktor", "JUnit": "org.junit", "Lombok": "lombok",
    "Reactor": "reactor.core", "Android": "android.",
}


@register("Java", "Kotlin", "Scala", "Groovy")
def analyze_jvm(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    pkg = _JVM_PACKAGE.search(body)
    for m, line in each_match(_JVM_IMPORT, body):
        result.imports.append(ImportRef(module=m.group(1), line=line))
    for m, line in each_match(_JVM_TYPE, body):
        result.symbols.append(
            Symbol(name=f"{pkg.group(1)}.{m.group(2)}" if pkg else m.group(2),
                   kind=m.group(1), file=rel, line=line)
        )
    for name, needle in _JVM_FRAMEWORKS.items():
        if needle in body:
            result.frameworks.append(name)
    if re.search(r"(fun|void|static\s+void)\s+main\s*\(", body):
        result.entrypoint = True

    base = ""
    class_map = _SPRING_CLASS.search(body)
    if class_map and "@RestController" in body or class_map and "@Controller" in body:
        base = class_map.group(1)
    for m, line in each_match(_SPRING_MAPPING, body):
        verb = m.group(1)
        path = m.group(2)
        if class_map and m.start() == class_map.start():
            continue
        method = "ANY" if verb == "Request" else verb.upper()
        result.endpoints.append(
            Endpoint(kind="http", method=method, path=normalise_route(base, path),
                     file=rel, line=line, framework="Spring")
        )
    if _JAXRS_METHOD.search(body):
        paths = [m.group(1) for m in _JAXRS_PATH.finditer(body)]
        root = paths[0] if paths else ""
        for m, line in each_match(_JAXRS_METHOD, body):
            result.endpoints.append(
                Endpoint(kind="http", method=m.group(1), path=normalise_route(root, ""),
                         file=rel, line=line, framework="JAX-RS")
            )
    return result


# ------------------------------------------------------------------------- C#

_CS_USING = re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", re.M)
_CS_TYPE = re.compile(r"^\s*(?:public|internal|private|protected|sealed|abstract|static|partial|\s)*"
                      r"(class|interface|record|struct|enum)\s+(\w+)", re.M)
_CS_ATTR_ROUTE = re.compile(r"""\[Route\(\s*["']([^"']+)["']""")
_CS_HTTP = re.compile(r"""\[Http(Get|Post|Put|Patch|Delete|Head|Options)(?:\(\s*["']([^"']*)["'])?""")
_CS_MINIMAL = re.compile(r"""\bapp\.Map(Get|Post|Put|Patch|Delete|Group)\s*\(\s*["']([^"']+)["']""")
_CS_FRAMEWORKS = {
    "ASP.NET Core": "Microsoft.AspNetCore", "Entity Framework": "Microsoft.EntityFrameworkCore",
    "Dapper": "Dapper", "MediatR": "MediatR", "Serilog": "Serilog", "xUnit": "Xunit",
    "Azure SDK": "Azure.", "MassTransit": "MassTransit", "Blazor": "Microsoft.AspNetCore.Components",
}


@register("C#")
def analyze_csharp(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for m, line in each_match(_CS_USING, body):
        result.imports.append(ImportRef(module=m.group(1), line=line))
    for m, line in each_match(_CS_TYPE, body):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
    for name, needle in _CS_FRAMEWORKS.items():
        if needle in body:
            result.frameworks.append(name)
    base_match = _CS_ATTR_ROUTE.search(body)
    base = base_match.group(1).replace("[controller]", _controller_name(rel)) if base_match else ""
    for m, line in each_match(_CS_HTTP, body):
        result.endpoints.append(
            Endpoint(kind="http", method=m.group(1).upper(),
                     path=normalise_route(base, m.group(2) or ""), file=rel, line=line,
                     framework="ASP.NET Core")
        )
    for m, line in each_match(_CS_MINIMAL, body):
        result.endpoints.append(
            Endpoint(kind="http", method=m.group(1).upper(), path=m.group(2), file=rel, line=line,
                     framework="ASP.NET Minimal API")
        )
    return result


def _controller_name(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return name[: -len("Controller")] if name.endswith("Controller") else name


# ----------------------------------------------------------------------- Ruby

_RB_REQUIRE = re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.M)
_RB_CLASS = re.compile(r"^\s*(class|module)\s+([\w:]+)", re.M)
_RB_DEF = re.compile(r"^\s*def\s+([\w.?!]+)", re.M)
_RB_ROUTE = re.compile(r"""^\s*(get|post|put|patch|delete|resources?|namespace|root)\s+['":]([^'",\s]+)""", re.M)


@register("Ruby")
def analyze_ruby(rel: str, text: str) -> Analysis:
    result = Analysis()
    for m, line in each_match(_RB_REQUIRE, text):
        result.imports.append(ImportRef(module=m.group(1), line=line,
                                        relative="require_relative" in m.group(0)))
    for m, line in each_match(_RB_CLASS, text):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
    for m, line in each_match(_RB_DEF, text):
        result.symbols.append(Symbol(name=m.group(1), kind="method", file=rel, line=line))
    if "Rails" in text or "rails" in text:
        result.frameworks.append("Ruby on Rails")
    if "sinatra" in text:
        result.frameworks.append("Sinatra")
    if rel.endswith("routes.rb") or "sinatra" in text:
        for m, line in each_match(_RB_ROUTE, text):
            verb, path = m.group(1), m.group(2)
            result.endpoints.append(
                Endpoint(kind="http",
                         method="ANY" if verb in ("resources", "resource", "namespace", "root")
                         else verb.upper(),
                         path=normalise_route("", path), file=rel, line=line,
                         framework="Rails" if rel.endswith("routes.rb") else "Sinatra")
            )
    return result


# ------------------------------------------------------------------------ PHP

_PHP_USE = re.compile(r"^\s*use\s+([\w\\]+)", re.M)
_PHP_REQUIRE = re.compile(r"""(?:require|include)(?:_once)?\s*\(?\s*['"]([^'"]+)['"]""")
_PHP_CLASS = re.compile(r"^\s*(?:final\s+|abstract\s+)?(class|interface|trait|enum)\s+(\w+)", re.M)
_PHP_FN = re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)", re.M)
_PHP_ROUTE = re.compile(r"""Route::(get|post|put|patch|delete|any|match)\s*\(\s*['"]([^'"]+)['"]""")
_PHP_ATTR_ROUTE = re.compile(r"""#\[Route\(\s*['"]([^'"]+)['"](?:.*?methods\s*:\s*\[['"](\w+)['"])?""", re.S)


@register("PHP")
def analyze_php(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for m, line in each_match(_PHP_USE, body):
        result.imports.append(ImportRef(module=m.group(1).replace("\\", "/"), line=line))
    for m, line in each_match(_PHP_REQUIRE, body):
        result.imports.append(ImportRef(module=m.group(1), line=line, relative=True))
    for m, line in each_match(_PHP_CLASS, body):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
    for m, line in each_match(_PHP_FN, body):
        result.symbols.append(Symbol(name=m.group(1), kind="function", file=rel, line=line))
    if "Illuminate\\" in text or "Laravel" in text:
        result.frameworks.append("Laravel")
    if "Symfony\\" in text:
        result.frameworks.append("Symfony")
    for m, line in each_match(_PHP_ROUTE, body):
        result.endpoints.append(
            Endpoint(kind="http", method=m.group(1).upper(), path=normalise_route("", m.group(2)),
                     file=rel, line=line, framework="Laravel")
        )
    for m, line in each_match(_PHP_ATTR_ROUTE, body):
        result.endpoints.append(
            Endpoint(kind="http", method=(m.group(2) or "ANY").upper(),
                     path=normalise_route("", m.group(1)), file=rel, line=line, framework="Symfony")
        )
    return result


# ----------------------------------------------------------------------- Rust

_RS_USE = re.compile(r"^\s*(?:pub\s+)?use\s+([\w:{}, *]+)\s*;", re.M)
_RS_MOD = re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", re.M)
_RS_ITEM = re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(fn|struct|enum|trait|impl)\s+(\w+)", re.M)
_RS_ATTR_ROUTE = re.compile(r"""#\[(get|post|put|patch|delete|head)\(\s*["']([^"']+)["']""")
_RS_AXUM = re.compile(r"""\.route\(\s*["']([^"']+)["']\s*,\s*(\w+)\(""")


@register("Rust")
def analyze_rust(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for m, line in each_match(_RS_USE, body):
        result.imports.append(ImportRef(module=m.group(1).split("::")[0].strip(), line=line,
                                        raw=m.group(0).strip()[:120],
                                        relative=m.group(1).startswith(("crate", "self", "super"))))
    for m, line in each_match(_RS_MOD, body):
        result.imports.append(ImportRef(module=m.group(1), line=line, relative=True))
    for m, line in each_match(_RS_ITEM, body):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
        if m.group(2) == "main":
            result.entrypoint = True
    for name, needle in {"Actix": "actix_web", "Axum": "axum", "Rocket": "rocket",
                         "Tokio": "tokio", "Serde": "serde", "SQLx": "sqlx",
                         "Diesel": "diesel"}.items():
        if needle in body:
            result.frameworks.append(name)
    for m, line in each_match(_RS_ATTR_ROUTE, body):
        result.endpoints.append(Endpoint(kind="http", method=m.group(1).upper(), path=m.group(2),
                                         file=rel, line=line, framework="Actix"))
    for m, line in each_match(_RS_AXUM, body):
        result.endpoints.append(Endpoint(kind="http", method=m.group(2).upper(), path=m.group(1),
                                         file=rel, line=line, framework="Axum"))
    return result


# --------------------------------------------------------------------- Elixir

_EX_IMPORT = re.compile(r"^\s*(?:import|alias|use|require)\s+([\w.]+)", re.M)
_EX_DEF = re.compile(r"^\s*(defmodule|def|defp)\s+([\w.?!]+)", re.M)
_EX_ROUTE = re.compile(r"""^\s*(get|post|put|patch|delete|live)\s+"([^"]+)\"""", re.M)


@register("Elixir")
def analyze_elixir(rel: str, text: str) -> Analysis:
    result = Analysis()
    for m, line in each_match(_EX_IMPORT, text):
        result.imports.append(ImportRef(module=m.group(1), line=line))
    for m, line in each_match(_EX_DEF, text):
        result.symbols.append(
            Symbol(name=m.group(2), kind="module" if m.group(1) == "defmodule" else "function",
                   file=rel, line=line, exported=m.group(1) != "defp")
        )
    if "Phoenix" in text:
        result.frameworks.append("Phoenix")
        for m, line in each_match(_EX_ROUTE, text):
            result.endpoints.append(Endpoint(kind="http", method=m.group(1).upper(), path=m.group(2),
                                             file=rel, line=line, framework="Phoenix"))
    return result


# ------------------------------------------------------------- C / C++ / Swift

_C_INCLUDE = re.compile(r"""^\s*#\s*include\s*[<"]([^>"]+)[>"]""", re.M)
_C_FUNC = re.compile(r"^[\w:*&<>\s]+?\b(\w+)\s*\([^;{]*\)\s*\{", re.M)
_C_TYPE = re.compile(r"^\s*(?:typedef\s+)?(struct|class|enum|union)\s+(\w+)", re.M)


@register("C", "C++", "Objective-C", "Objective-C++")
def analyze_c(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for m, line in each_match(_C_INCLUDE, body):
        result.imports.append(ImportRef(module=m.group(1), line=line,
                                        relative=m.group(0).strip().endswith('"')))
    for m, line in each_match(_C_TYPE, body):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
    for m, line in each_match(_C_FUNC, body):
        if m.group(1) in ("if", "for", "while", "switch", "catch", "return"):
            continue
        result.symbols.append(Symbol(name=m.group(1), kind="function", file=rel, line=line))
        if m.group(1) == "main":
            result.entrypoint = True
    return result


_SWIFT_IMPORT = re.compile(r"^\s*import\s+(\w+)", re.M)
_SWIFT_TYPE = re.compile(
    r"^\s*(?:public\s+|open\s+|internal\s+|final\s+)*(class|struct|enum|protocol|extension)\s+(\w+)",
    re.M)
_SWIFT_FUNC = re.compile(r"^\s*(?:public\s+|private\s+|static\s+|override\s+)*func\s+(\w+)", re.M)


@register("Swift")
def analyze_swift(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for m, line in each_match(_SWIFT_IMPORT, body):
        result.imports.append(ImportRef(module=m.group(1), line=line))
    for m, line in each_match(_SWIFT_TYPE, body):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
    for m, line in each_match(_SWIFT_FUNC, body):
        result.symbols.append(Symbol(name=m.group(1), kind="function", file=rel, line=line))
    if "SwiftUI" in body:
        result.frameworks.append("SwiftUI")
    if "Vapor" in body:
        result.frameworks.append("Vapor")
    return result


# --------------------------------------------------------------- Dart / Shell

_DART_IMPORT = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.M)
_DART_TYPE = re.compile(r"^\s*(?:abstract\s+)?(class|mixin|enum)\s+(\w+)", re.M)


@register("Dart")
def analyze_dart(rel: str, text: str) -> Analysis:
    result = Analysis()
    body = strip_block_comments(text)
    for m, line in each_match(_DART_IMPORT, body):
        result.imports.append(ImportRef(module=m.group(1), line=line, relative=not m.group(1).startswith("package:")))
    for m, line in each_match(_DART_TYPE, body):
        result.symbols.append(Symbol(name=m.group(2), kind=m.group(1), file=rel, line=line))
    if "flutter" in body:
        result.frameworks.append("Flutter")
    return result


_SH_SOURCE = re.compile(r"^\s*(?:source|\.)\s+([\w./$-]+)", re.M)
_SH_FUNC = re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{", re.M)


@register("Shell")
def analyze_shell(rel: str, text: str) -> Analysis:
    result = Analysis()
    for m, line in each_match(_SH_SOURCE, text):
        result.imports.append(ImportRef(module=m.group(1), line=line, relative=True))
    for m, line in each_match(_SH_FUNC, text):
        result.symbols.append(Symbol(name=m.group(1), kind="function", file=rel, line=line))
    result.entrypoint = text.startswith("#!")
    return result


# --------------------------------------------------------- SQL / proto / gql

_SQL_TABLE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW|MATERIALIZED\s+VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?([\w.]+)", re.I)
_SQL_PROC = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?(FUNCTION|PROCEDURE)\s+[\"`\[]?([\w.]+)", re.I)


@register("SQL")
def analyze_sql(rel: str, text: str) -> Analysis:
    result = Analysis()
    for m, line in each_match(_SQL_TABLE, text):
        result.symbols.append(Symbol(name=m.group(2), kind="table", file=rel, line=line))
    for m, line in each_match(_SQL_PROC, text):
        result.symbols.append(Symbol(name=m.group(2), kind="procedure", file=rel, line=line))
    return result


_PROTO_SERVICE = re.compile(r"^\s*service\s+(\w+)", re.M)
_PROTO_RPC = re.compile(r"^\s*rpc\s+(\w+)\s*\(([^)]*)\)\s*returns\s*\(([^)]*)\)", re.M)
_PROTO_MESSAGE = re.compile(r"^\s*message\s+(\w+)", re.M)
_PROTO_IMPORT = re.compile(r"""^\s*import\s+["']([^"']+)["']""", re.M)


@register("Protobuf")
def analyze_proto(rel: str, text: str) -> Analysis:
    result = Analysis()
    for m, line in each_match(_PROTO_IMPORT, text):
        result.imports.append(ImportRef(module=m.group(1), line=line, relative=True))
    service = ""
    for m, line in each_match(_PROTO_SERVICE, text):
        service = m.group(1)
        result.symbols.append(Symbol(name=service, kind="service", file=rel, line=line))
    for m, line in each_match(_PROTO_MESSAGE, text):
        result.symbols.append(Symbol(name=m.group(1), kind="message", file=rel, line=line))
    for m, line in each_match(_PROTO_RPC, text):
        result.endpoints.append(
            Endpoint(kind="grpc", method="RPC", path=f"{service}/{m.group(1)}" if service else m.group(1),
                     handler=m.group(1), file=rel, line=line, framework="gRPC",
                     description=f"{m.group(2).strip()} -> {m.group(3).strip()}")
        )
    return result


_GQL_TYPE = re.compile(r"^\s*(type|input|enum|interface|union)\s+(\w+)", re.M)
_GQL_FIELD = re.compile(r"^\s{2,}(\w+)\s*(\([^)]*\))?\s*:", re.M)


@register("GraphQL")
def analyze_graphql(rel: str, text: str) -> Analysis:
    result = Analysis()
    current = ""
    for line_no, line in enumerate(text.splitlines(), 1):
        tm = _GQL_TYPE.match(line)
        if tm:
            current = tm.group(2)
            result.symbols.append(Symbol(name=current, kind=tm.group(1), file=rel, line=line_no))
            continue
        if current in ("Query", "Mutation", "Subscription"):
            fm = _GQL_FIELD.match(line)
            if fm:
                result.endpoints.append(
                    Endpoint(kind="graphql", method=current.upper(), path=fm.group(1),
                             handler=fm.group(1), file=rel, line=line_no, framework="GraphQL")
                )
    return result
