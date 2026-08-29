"""Language analyzer registry."""

from __future__ import annotations

from . import javascript, others, python_lang  # noqa: F401,E402
from .base import Analysis, Analyzer, ImportRef, get_analyzer, register  # noqa: F401


def analyze(language: str, rel: str, text: str) -> Analysis:
    """Analyze one file; unknown languages yield an empty analysis."""
    fn = get_analyzer(language)
    if fn is None:
        return Analysis()
    try:
        return fn(rel, text)
    except Exception:  # a broken regex on odd input must never kill a scan
        return Analysis()


__all__ = ["analyze", "Analysis", "ImportRef", "get_analyzer", "register"]
