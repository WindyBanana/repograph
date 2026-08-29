"""Shared plumbing for the per-language source analyzers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ..model import Endpoint, Symbol


@dataclass
class ImportRef:
    module: str
    line: int = 0
    raw: str = ""
    relative: bool = False
    names: List[str] = field(default_factory=list)
    is_type_only: bool = False


@dataclass
class Analysis:
    """Everything one source file contributes to the model."""

    imports: List[ImportRef] = field(default_factory=list)
    symbols: List[Symbol] = field(default_factory=list)
    endpoints: List[Endpoint] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    entrypoint: bool = False
    doc: str = ""

    def extend(self, other: Analysis) -> None:
        self.imports.extend(other.imports)
        self.symbols.extend(other.symbols)
        self.endpoints.extend(other.endpoints)
        self.frameworks.extend(other.frameworks)
        self.entrypoint = self.entrypoint or other.entrypoint
        self.doc = self.doc or other.doc


Analyzer = Callable[[str, str], Analysis]  # (relative path, text) -> Analysis

_REGISTRY: Dict[str, Analyzer] = {}


def register(*languages: str):
    def deco(fn: Analyzer) -> Analyzer:
        for lang in languages:
            _REGISTRY[lang] = fn
        return fn

    return deco


def get_analyzer(language: str) -> Optional[Analyzer]:
    return _REGISTRY.get(language)


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def strip_block_comments(text: str) -> str:
    """Remove /* */ blocks and line comments so regexes do not match dead code."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return text


def each_match(pattern: re.Pattern, text: str):
    for m in pattern.finditer(text):
        yield m, line_of(text, m.start())


HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "all", "any")


def normalise_route(base: str, path: str) -> str:
    base = (base or "").strip("\"'` ")
    path = (path or "").strip("\"'` ")
    if base and not base.startswith("/"):
        base = "/" + base
    if path and not path.startswith("/"):
        path = "/" + path
    joined = (base.rstrip("/") + path) if base else path
    return joined or "/"


def framework_hits(text: str, table: Dict[str, Tuple[str, ...]]) -> List[str]:
    found = []
    lowered = text
    for name, needles in table.items():
        if any(n in lowered for n in needles):
            found.append(name)
    return found
