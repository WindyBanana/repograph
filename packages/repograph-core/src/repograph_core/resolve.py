"""Import resolution.

Turns raw import strings into either an internal file (an edge in the graph) or
an external package (a dependency). Everything the tool says about missing or
unused dependencies comes from here, so resolution is deliberately conservative:
when we cannot resolve something we say so rather than guessing.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from .manifests import Manifest
from .parsers import load_json
from .walker import ScanFile

JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".vue", ".svelte", ".json")
JS_INDEX = tuple(f"/index{ext}" for ext in JS_EXTENSIONS)

NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http",
    "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream", "string_decoder", "sys",
    "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm", "wasi", "worker_threads",
    "zlib", "test",
}

GO_STDLIB = {
    "fmt", "os", "io", "net", "time", "strings", "strconv", "errors", "context", "sync",
    "encoding", "bytes", "bufio", "sort", "math", "regexp", "path", "reflect", "runtime",
    "testing", "log", "flag", "database", "crypto", "hash", "html", "text", "unicode",
    "container", "compress", "archive", "mime", "embed", "expvar", "go", "image", "index",
    "plugin", "debug", "signal", "syscall", "unsafe", "slices", "maps", "cmp",
}

JVM_STDLIB_PREFIXES = ("java.", "javax.", "jakarta.annotation", "kotlin.", "kotlinx.coroutines",
                       "scala.", "sun.", "jdk.", "android.")
DOTNET_STDLIB_PREFIXES = ("System", "Microsoft.Extensions", "Microsoft.Win32", "Windows.")

# ``sys.stdlib_module_names`` only exists from 3.10, so 3.9 gets a static list —
# without it every ``import os`` would be reported as an undeclared dependency.
_STDLIB_FALLBACK = {
    "__future__", "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "bz2", "calendar", "cgi", "cmath", "cmd", "codecs", "collections", "colorsys",
    "concurrent", "configparser", "contextlib", "contextvars", "copy", "copyreg", "csv", "ctypes",
    "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis", "doctest", "email",
    "encodings", "enum", "errno", "faulthandler", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "imaplib", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "linecache", "locale", "logging", "lzma",
    "mailbox", "marshal", "math", "mimetypes", "mmap", "multiprocessing", "netrc", "numbers",
    "operator", "os", "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
    "plistlib", "poplib", "posixpath", "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
    "queue", "quopri", "random", "re", "readline", "reprlib", "resource", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtplib",
    "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "symtable", "sys", "sysconfig", "syslog", "tarfile", "telnetlib",
    "tempfile", "termios", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle", "types",
    "typing", "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "wsgiref", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "zoneinfo",
}

PY_STDLIB = (set(getattr(sys, "stdlib_module_names", ())) or _STDLIB_FALLBACK) | {
    "typing_extensions", "dataclasses", "__future__",
}

# npm package name from an import specifier: "lodash/get" -> lodash, "@a/b/c" -> @a/b
_NPM_NAME = re.compile(r"^(@[^/]+/[^/]+|[^/@][^/]*)")


@dataclass
class ResolvedImport:
    source_file: str
    raw: str
    line: int
    internal_file: str = ""
    external_package: str = ""
    ecosystem: str = ""
    unresolved: bool = False
    stdlib: bool = False


@dataclass
class ResolveIndex:
    by_rel: Dict[str, str] = field(default_factory=dict)
    py_modules: Dict[str, str] = field(default_factory=dict)
    go_packages: Dict[str, List[str]] = field(default_factory=dict)
    jvm_types: Dict[str, str] = field(default_factory=dict)
    dotnet_namespaces: Dict[str, List[str]] = field(default_factory=dict)
    npm_packages: Dict[str, str] = field(default_factory=dict)  # package name -> dir
    py_dists: Dict[str, str] = field(default_factory=dict)      # distribution name -> dir
    aliases: List[Tuple[str, str]] = field(default_factory=list)  # (prefix, target dir)
    go_module: str = ""
    rust_crates: Dict[str, str] = field(default_factory=dict)


class Resolver:
    def __init__(self, files: Sequence[ScanFile], manifests: Sequence[Manifest],
                 tsconfigs: Dict[str, str]) -> None:
        self.files = list(files)
        self.rel_set = {f.rel for f in self.files}
        self.index = ResolveIndex()
        self._build_index(manifests, tsconfigs)

    # ---------------------------------------------------------------- index
    def _build_index(self, manifests: Sequence[Manifest], tsconfigs: Dict[str, str]) -> None:
        idx = self.index
        for f in self.files:
            idx.by_rel[f.rel] = f.rel
            if f.language == "Python":
                self._index_python(f)
            elif f.language == "Go":
                idx.go_packages.setdefault(f.rel.rsplit("/", 1)[0] if "/" in f.rel else "", []).append(f.rel)
            elif f.language in ("Java", "Kotlin", "Scala", "Groovy"):
                self._index_jvm(f)
            elif f.language == "C#":
                self._index_dotnet(f)
            elif f.language == "Rust":
                crate_dir = f.rel.rsplit("/src/", 1)[0] if "/src/" in f.rel else ""
                if crate_dir:
                    idx.rust_crates.setdefault(crate_dir.rsplit("/", 1)[-1].replace("-", "_"), crate_dir)

        for m in manifests:
            if m.ecosystem == "npm" and m.name:
                idx.npm_packages[m.name] = m.dir
            elif m.ecosystem == "pypi" and m.name:
                idx.py_dists[m.name.replace("_", "-").lower()] = m.dir
            elif m.ecosystem == "go" and m.module_path:
                if not idx.go_module or len(m.dir) < len(idx.go_module):
                    idx.go_module = m.module_path
                idx.go_packages.setdefault("__modules__", []).append(f"{m.module_path}\t{m.dir}")
            elif m.ecosystem == "cargo" and m.name:
                idx.rust_crates.setdefault(m.name.replace("-", "_"), m.dir)

        for path, text in tsconfigs.items():
            self._index_ts_aliases(path, text)

    def _index_python(self, f: ScanFile) -> None:
        rel = f.rel[:-3] if f.rel.endswith(".py") else f.rel.rsplit(".", 1)[0]
        parts = rel.split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            return
        for start in range(len(parts)):
            module = ".".join(parts[start:])
            if module:
                self.index.py_modules.setdefault(module, f.rel)

    def _index_jvm(self, f: ScanFile) -> None:
        name = f.rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        segments = f.rel.split("/")
        for marker in ("java", "kotlin", "scala", "groovy"):
            if marker in segments:
                pkg = ".".join(segments[segments.index(marker) + 1 : -1])
                if pkg:
                    self.index.jvm_types.setdefault(f"{pkg}.{name}", f.rel)
                    self.index.jvm_types.setdefault(f"{pkg}.*", f.rel)
                return
        self.index.jvm_types.setdefault(name, f.rel)

    def _index_dotnet(self, f: ScanFile) -> None:
        self.index.dotnet_namespaces.setdefault(f.rel.rsplit("/", 1)[-1].rsplit(".", 1)[0], []).append(f.rel)

    def _index_ts_aliases(self, path: str, text: str) -> None:
        data = load_json(text)
        if not isinstance(data, dict):
            return
        options = data.get("compilerOptions") if isinstance(data.get("compilerOptions"), dict) else {}
        base = options.get("baseUrl") or "."
        base_dir = os.path.normpath(os.path.join(path.rsplit("/", 1)[0] if "/" in path else "", base))
        base_dir = "" if base_dir == "." else base_dir.replace(os.sep, "/")
        paths = options.get("paths")
        if isinstance(paths, dict):
            for pattern, targets in paths.items():
                if not isinstance(targets, list) or not targets:
                    continue
                target = str(targets[0]).replace("*", "").rstrip("/")
                prefix = pattern.replace("*", "")
                resolved = os.path.normpath(os.path.join(base_dir, target)).replace(os.sep, "/")
                self.index.aliases.append((prefix, "" if resolved == "." else resolved))
        elif base_dir:
            self.index.aliases.append(("~/", base_dir))
            self.index.aliases.append(("@/", base_dir))

    # -------------------------------------------------------------- resolve
    def resolve(self, f: ScanFile, module: str, line: int, relative: bool) -> ResolvedImport:
        out = ResolvedImport(source_file=f.rel, raw=module, line=line)
        lang = f.language
        if not module:
            out.unresolved = True
            return out
        if lang == "Python":
            return self._resolve_python(f, module, out, relative)
        if lang in ("JavaScript", "TypeScript", "Vue", "Svelte"):
            return self._resolve_js(f, module, out)
        if lang == "Go":
            return self._resolve_go(f, module, out)
        if lang in ("Java", "Kotlin", "Scala", "Groovy"):
            return self._resolve_jvm(f, module, out)
        if lang == "C#":
            return self._resolve_dotnet(f, module, out)
        if lang == "Rust":
            return self._resolve_rust(f, module, out)
        if lang in ("Ruby", "PHP", "Shell", "C", "C++", "Elixir", "Dart", "Swift", "Protobuf"):
            return self._resolve_pathlike(f, module, out, relative)
        out.unresolved = True
        return out

    # -- python
    def _resolve_python(self, f: ScanFile, module: str, out: ResolvedImport, relative: bool) -> ResolvedImport:
        if module.startswith("."):
            depth = len(module) - len(module.lstrip("."))
            base = f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""
            parts = base.split("/") if base else []
            up = parts[: len(parts) - (depth - 1)] if depth > 1 else parts
            tail = module.lstrip(".").replace(".", "/")
            candidate = "/".join([p for p in up if p] + ([tail] if tail else []))
            for suffix in (".py", "/__init__.py", ".pyi"):
                if candidate + suffix in self.rel_set:
                    out.internal_file = candidate + suffix
                    return out
            out.unresolved = True
            return out
        top = module.split(".")[0]
        hit = self._py_lookup(module)
        if hit:
            out.internal_file = hit
            return out
        if top in PY_STDLIB:
            out.stdlib = True
            return out
        out.external_package = top
        out.ecosystem = "pypi"
        return out

    def _py_lookup(self, module: str) -> str:
        parts = module.split(".")
        while parts:
            candidate = ".".join(parts)
            hit = self.index.py_modules.get(candidate)
            if hit:
                return hit
            parts.pop()
        return ""

    # -- javascript
    def _resolve_js(self, f: ScanFile, module: str, out: ResolvedImport) -> ResolvedImport:
        if module.startswith("."):
            base = f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""
            target = os.path.normpath(os.path.join(base, module)).replace(os.sep, "/")
            hit = self._js_file(target)
            if hit:
                out.internal_file = hit
            else:
                out.unresolved = True
            return out
        for prefix, target_dir in sorted(self.index.aliases, key=lambda a: -len(a[0])):
            if prefix and module.startswith(prefix):
                target = os.path.normpath(os.path.join(target_dir, module[len(prefix) :])).replace(os.sep, "/")
                hit = self._js_file(target)
                if hit:
                    out.internal_file = hit
                    return out
        match = _NPM_NAME.match(module)
        name = match.group(1) if match else module
        if name in self.index.npm_packages:
            pkg_dir = self.index.npm_packages[name]
            entry = self._js_package_entry(pkg_dir)
            if entry:
                out.internal_file = entry
                return out
        if module.startswith("node:") or name in NODE_BUILTINS:
            out.stdlib = True
            return out
        if module.startswith(("http://", "https://", "/")):
            out.unresolved = True
            return out
        out.external_package = name
        out.ecosystem = "npm"
        return out

    def _js_file(self, target: str) -> str:
        if target in self.rel_set:
            return target
        for ext in JS_EXTENSIONS:
            if target + ext in self.rel_set:
                return target + ext
        for idx in JS_INDEX:
            if target + idx in self.rel_set:
                return target + idx
        return ""

    def _js_package_entry(self, pkg_dir: str) -> str:
        for candidate in ("src/index.ts", "src/index.js", "index.ts", "index.js", "src/main.ts",
                          "src/index.tsx", "lib/index.js"):
            full = f"{pkg_dir}/{candidate}" if pkg_dir else candidate
            if full in self.rel_set:
                return full
        prefix = pkg_dir + "/" if pkg_dir else ""
        for rel in self.rel_set:
            if rel.startswith(prefix) and rel.endswith((".ts", ".js", ".tsx")):
                return rel
        return ""

    # -- go
    def _resolve_go(self, f: ScanFile, module: str, out: ResolvedImport) -> ResolvedImport:
        modules = self.index.go_packages.get("__modules__", [])
        for entry in sorted(modules, key=len, reverse=True):
            mod_path, _, mod_dir = entry.partition("\t")
            if module == mod_path or module.startswith(mod_path + "/"):
                sub = module[len(mod_path) :].strip("/")
                pkg_dir = f"{mod_dir}/{sub}".strip("/") if mod_dir else sub
                hits = self.index.go_packages.get(pkg_dir)
                if hits:
                    out.internal_file = hits[0]
                    return out
                out.unresolved = True
                return out
        if "." not in module.split("/")[0]:
            out.stdlib = module.split("/")[0] in GO_STDLIB or True
            return out
        parts = module.split("/")
        out.external_package = "/".join(parts[:3]) if len(parts) >= 3 else module
        out.ecosystem = "go"
        return out

    # -- jvm
    def _resolve_jvm(self, f: ScanFile, module: str, out: ResolvedImport) -> ResolvedImport:
        hit = self.index.jvm_types.get(module)
        if hit:
            out.internal_file = hit
            return out
        if module.endswith(".*"):
            prefix = module[:-1]
            for key, rel in self.index.jvm_types.items():
                if key.startswith(prefix):
                    out.internal_file = rel
                    return out
        if module.startswith(JVM_STDLIB_PREFIXES):
            out.stdlib = True
            return out
        parts = module.split(".")
        out.external_package = ".".join(parts[:3]) if len(parts) >= 3 else module
        out.ecosystem = "maven"
        return out

    # -- dotnet
    def _resolve_dotnet(self, f: ScanFile, module: str, out: ResolvedImport) -> ResolvedImport:
        last = module.split(".")[-1]
        hits = self.index.dotnet_namespaces.get(last)
        if hits:
            out.internal_file = hits[0]
            return out
        if module.startswith(DOTNET_STDLIB_PREFIXES):
            out.stdlib = True
            return out
        out.external_package = module
        out.ecosystem = "nuget"
        return out

    # -- rust
    def _resolve_rust(self, f: ScanFile, module: str, out: ResolvedImport) -> ResolvedImport:
        if module in ("crate", "self", "super", "std", "core", "alloc"):
            out.stdlib = module in ("std", "core", "alloc")
            out.unresolved = not out.stdlib
            return out
        crate_dir = self.index.rust_crates.get(module)
        if crate_dir:
            for candidate in (f"{crate_dir}/src/lib.rs", f"{crate_dir}/src/main.rs"):
                if candidate in self.rel_set:
                    out.internal_file = candidate
                    return out
        base = f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""
        for candidate in (f"{base}/{module}.rs", f"{base}/{module}/mod.rs"):
            if candidate in self.rel_set:
                out.internal_file = candidate
                return out
        out.external_package = module
        out.ecosystem = "cargo"
        return out

    # -- generic path-like (ruby, php, shell, c, ...)
    def _resolve_pathlike(self, f: ScanFile, module: str, out: ResolvedImport, relative: bool) -> ResolvedImport:
        base = f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""
        candidates = []
        cleaned = module.strip("./")
        if relative or module.startswith("."):
            candidates.append(os.path.normpath(os.path.join(base, module)).replace(os.sep, "/"))
        candidates.append(cleaned)
        exts = {"Ruby": (".rb",), "PHP": (".php",), "Shell": (".sh", ""), "C": (".h", ".c"),
                "C++": (".h", ".hpp", ".cpp"), "Elixir": (".ex",), "Dart": (".dart",),
                "Swift": (".swift",), "Protobuf": (".proto",)}.get(f.language, ("",))
        for candidate in candidates:
            for ext in exts:
                if candidate + ext in self.rel_set:
                    out.internal_file = candidate + ext
                    return out
            matches = [r for r in self.rel_set if r.endswith("/" + candidate) or
                       any(r.endswith("/" + candidate + e) for e in exts)]
            if len(matches) == 1:
                out.internal_file = matches[0]
                return out
        if f.language == "Ruby":
            out.external_package, out.ecosystem = module.split("/")[0], "rubygems"
        elif f.language == "PHP":
            out.external_package, out.ecosystem = "/".join(module.split("/")[:2]), "composer"
        elif f.language == "Dart":
            out.external_package = module.replace("package:", "").split("/")[0]
            out.ecosystem = "pub"
        else:
            out.unresolved = True
        return out


def normalise_package(name: str, ecosystem: str) -> str:
    if ecosystem == "pypi":
        return name.replace("_", "-").lower()
    if ecosystem == "maven":
        return name.split(":")[-1] if ":" in name else name
    return name
