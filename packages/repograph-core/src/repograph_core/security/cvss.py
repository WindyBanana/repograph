"""CVSS v3.x base score calculation (so we can rank advisories offline)."""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
_AC = {"L": 0.77, "H": 0.44}
_PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_C = {"N": 0.85, "L": 0.68, "H": 0.50}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}


def _roundup(value: float) -> float:
    scaled = int(value * 100000)
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (math.floor(scaled / 10000) + 1) / 10.0


def parse_vector(vector: str) -> Dict[str, str]:
    parts = {}
    for chunk in vector.strip().split("/"):
        if ":" in chunk:
            key, value = chunk.split(":", 1)
            parts[key.upper()] = value.upper()
    return parts


def base_score(vector: str) -> Optional[float]:
    """Return the CVSS v3 base score for a vector string, or None."""
    parts = parse_vector(vector)
    if not {"AV", "AC", "PR", "UI", "S", "C", "I", "A"} <= set(parts):
        return None
    try:
        scope_changed = parts["S"] == "C"
        conf, integ, avail = _CIA[parts["C"]], _CIA[parts["I"]], _CIA[parts["A"]]
        iss = 1 - ((1 - conf) * (1 - integ) * (1 - avail))
        impact = (
            7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if scope_changed else 6.42 * iss
        )
        privileges = (_PR_C if scope_changed else _PR_U)[parts["PR"]]
        exploitability = 8.22 * _AV[parts["AV"]] * _AC[parts["AC"]] * privileges * _UI[parts["UI"]]
    except KeyError:
        return None
    if impact <= 0:
        return 0.0
    total = min((1.08 * (impact + exploitability)) if scope_changed else (impact + exploitability), 10.0)
    return _roundup(total)


def severity_from_score(score: Optional[float]) -> str:
    if score is None:
        return "medium"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0:
        return "low"
    return "info"


def score_and_severity(vector: str) -> Tuple[Optional[float], str]:
    score = base_score(vector)
    return score, severity_from_score(score)
