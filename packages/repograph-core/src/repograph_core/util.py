"""Small shared helpers. Standard library only, on purpose."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import unicodedata
from typing import Iterable, List, Optional, Sequence, Tuple

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slug(*parts: str, maxlen: int = 80) -> str:
    """Stable, readable identifier used for node ids across every renderer."""
    raw = "-".join(p for p in parts if p)
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    out = _SLUG_RE.sub("-", raw).strip("-").lower()
    if len(out) > maxlen:
        digest = hashlib.sha1(out.encode(), usedforsecurity=False).hexdigest()[:8]
        out = out[: maxlen - 9].rstrip("-") + "-" + digest
    return out or "n"


def read_text(path: str, limit: int = 4_000_000) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(limit)
    except OSError:
        return ""
    if b"\0" in raw[:4096]:
        return ""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def count_lines(text: str, comment_prefixes: Sequence[str] = ("#", "//", "--", "*", "%")) -> Tuple[int, int]:
    """Return (total lines, significant lines)."""
    loc = 0
    sloc = 0
    for line in text.splitlines():
        loc += 1
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in comment_prefixes):
            continue
        sloc += 1
    return loc, sloc


def truncate(text: str, length: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1] + "…"


def human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}" if unit != "B" else f"{int(num)}B"
        num /= 1024.0
    return f"{num:.1f}PB"


def human_number(num: float) -> str:
    for unit in ("", "k", "M", "B"):
        if abs(num) < 1000:
            return f"{num:.0f}{unit}" if unit == "" else f"{num:.1f}{unit}"
        num /= 1000.0
    return f"{num:.1f}T"


def run_git(root: str, *args: str, timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def rel_path(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path.replace(os.sep, "/")


def top_dir(rel: str) -> str:
    return rel.split("/", 1)[0] if "/" in rel else ""


def common_prefix_dir(paths: Iterable[str]) -> str:
    parts: Optional[List[str]] = None
    for p in paths:
        segments = p.split("/")[:-1]
        if parts is None:
            parts = segments
            continue
        keep = []
        for a, b in zip(parts, segments):
            if a != b:
                break
            keep.append(a)
        parts = keep
    return "/".join(parts or [])


def dedupe(seq: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in seq:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    import math

    length = len(text)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def title_case(name: str) -> str:
    cleaned = re.sub(r"[-_./]+", " ", name).strip()
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
    words = [w for w in cleaned.split() if w]
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words) or name


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def chunked(seq: Sequence, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
