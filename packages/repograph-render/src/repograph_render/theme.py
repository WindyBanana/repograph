"""One palette, shared by every renderer, so the SVG, PDF, deck and web views
look like one product."""

from __future__ import annotations

from typing import Dict, Tuple

FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace"

INK = "#111827"
MUTED = "#6b7280"
FAINT = "#9ca3af"
BG = "#ffffff"
PANEL = "#f8fafc"
GRID = "#e5e7eb"
EDGE = "#94a3b8"
EDGE_STRONG = "#64748b"

# node kind -> (stroke, fill, text)
KINDS: Dict[str, Tuple[str, str, str]] = {
    "system":      ("#1d4ed8", "#dbeafe", "#0f172a"),
    "app":         ("#2563eb", "#eff6ff", "#0f172a"),
    "container":   ("#2563eb", "#eff6ff", "#0f172a"),
    "component":   ("#7c3aed", "#f5f3ff", "#0f172a"),
    "module":      ("#7c3aed", "#faf5ff", "#0f172a"),
    "database":    ("#0891b2", "#ecfeff", "#0f172a"),
    "datastore":   ("#0891b2", "#ecfeff", "#0f172a"),
    "cache":       ("#0d9488", "#f0fdfa", "#0f172a"),
    "queue":       ("#ca8a04", "#fefce8", "#0f172a"),
    "storage":     ("#0369a1", "#f0f9ff", "#0f172a"),
    "search":      ("#7c2d12", "#fff7ed", "#0f172a"),
    "external":    ("#ea580c", "#fff7ed", "#0f172a"),
    "system_ext":  ("#ea580c", "#fff7ed", "#0f172a"),
    "api":         ("#ea580c", "#fff7ed", "#0f172a"),
    "auth":        ("#be185d", "#fdf2f8", "#0f172a"),
    "payment":     ("#be185d", "#fdf2f8", "#0f172a"),
    "mail":        ("#9333ea", "#faf5ff", "#0f172a"),
    "observability": ("#0f766e", "#f0fdfa", "#0f172a"),
    "ai":          ("#4f46e5", "#eef2ff", "#0f172a"),
    "person":      ("#475569", "#f1f5f9", "#0f172a"),
    "start":       ("#16a34a", "#f0fdf4", "#0f172a"),
    "end":         ("#dc2626", "#fef2f2", "#0f172a"),
    "decision":    ("#d97706", "#fffbeb", "#0f172a"),
    "task":        ("#2563eb", "#f8fafc", "#0f172a"),
    "subprocess":  ("#4338ca", "#eef2ff", "#0f172a"),
    "event":       ("#0891b2", "#ecfeff", "#0f172a"),
    "gateway":     ("#d97706", "#fffbeb", "#0f172a"),
    "test":        ("#65a30d", "#f7fee7", "#0f172a"),
    "infra":       ("#475569", "#f1f5f9", "#0f172a"),
    "docs":        ("#0284c7", "#f0f9ff", "#0f172a"),
    "library":     ("#7c3aed", "#f5f3ff", "#0f172a"),
    "frontend":    ("#db2777", "#fdf2f8", "#0f172a"),
    "service":     ("#2563eb", "#eff6ff", "#0f172a"),
    "cli":         ("#0f766e", "#f0fdfa", "#0f172a"),
    "job":         ("#ca8a04", "#fefce8", "#0f172a"),
    "application": ("#2563eb", "#eff6ff", "#0f172a"),
}

# Status palette — reserved for severity, never reused as a categorical series.
SEVERITY: Dict[str, str] = {
    "critical": "#991b1b",
    "high": "#c2410c",
    "medium": "#a16207",
    "low": "#1d4ed8",
    "info": "#64748b",
}

SEVERITY_BG: Dict[str, str] = {
    "critical": "#fef2f2",
    "high": "#fff7ed",
    "medium": "#fffbeb",
    "low": "#eff6ff",
    "info": "#f8fafc",
}

LANE_TINTS = ["#f8fafc", "#f1f5f9"]

# Categorical series, in fixed order — validated for CVD separation, chroma and
# contrast in both light and dark surfaces. Never cycled: anything past the last
# slot folds into an explicit "Other" bucket.
SERIES = [
    "#2563eb", "#ea580c", "#0891b2", "#db2777", "#7c3aed", "#16a34a", "#b45309", "#0d9488",
]
OTHER = "#94a3b8"


def kind_colors(kind: str) -> Tuple[str, str, str]:
    return KINDS.get(kind, KINDS["component"])


def severity_color(severity: str) -> str:
    return SEVERITY.get(severity, SEVERITY["info"])


def series_color(index: int) -> str:
    """Fixed-order categorical hue; anything past the palette is 'Other' grey."""
    return SERIES[index] if index < len(SERIES) else OTHER
