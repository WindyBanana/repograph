"""Reading the scan's own judgement about what is worth producing."""

from __future__ import annotations

from typing import List, Tuple

from repograph_core.model import ScanResult


def wants(result: ScanResult, name: str, default: bool = True) -> bool:
    artifacts = (result.profile or {}).get("artifacts") or {}
    entry = artifacts.get(name)
    if not isinstance(entry, dict):
        return default
    return bool(entry.get("include", default))


def reason(result: ScanResult, name: str) -> str:
    artifacts = (result.profile or {}).get("artifacts") or {}
    entry = artifacts.get(name)
    return str(entry.get("reason", "")) if isinstance(entry, dict) else ""


def skipped(result: ScanResult) -> List[Tuple[str, str]]:
    artifacts = (result.profile or {}).get("artifacts") or {}
    return [(name, str(entry.get("reason", "")))
            for name, entry in sorted(artifacts.items())
            if isinstance(entry, dict) and not entry.get("include", True)]


def max_flows(result: ScanResult, default: int = 14) -> int:
    value = (result.profile or {}).get("max_flows")
    if isinstance(value, int) and value >= 0:
        return min(value, default) if default else value
    return default


def label(result: ScanResult) -> str:
    return str((result.profile or {}).get("label", "Software repository"))


def kind(result: ScanResult) -> str:
    return str((result.profile or {}).get("kind", "mixed"))


def profile_summary(result: ScanResult) -> str:
    return str((result.profile or {}).get("summary", ""))
