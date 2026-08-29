"""Config-format parsers.

The tool must run from a bare Python install, so YAML and TOML have small
built-in fallbacks. If PyYAML or ``tomllib`` are present we use them instead.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

try:  # Python 3.11+
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    try:
        import tomli as _tomllib  # type: ignore
    except ModuleNotFoundError:
        _tomllib = None  # type: ignore

try:
    import yaml as _pyyaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    _pyyaml = None  # type: ignore


# --------------------------------------------------------------------- JSON

def load_json(text: str) -> Any:
    """Tolerant JSON: strips comments and trailing commas (tsconfig, jsonc)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    cleaned = re.sub(r"(^|\s)//[^\n]*", r"\1", cleaned)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------- TOML

_TOML_KEY = re.compile(r"^\s*((?:[\w.\-]+|\"[^\"]+\"|'[^']+')(?:\s*\.\s*(?:[\w.\-]+|\"[^\"]+\"))*)\s*=\s*(.+?)\s*$")


def load_toml(text: str) -> Dict[str, Any]:
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except Exception:
            pass
    return _mini_toml(text)


def _toml_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"""') or raw.startswith("'''"):
        return raw.strip("\"'")
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.startswith("["):
        inner = raw[1:-1] if raw.endswith("]") else raw[1:]
        items = _split_top(inner)
        return [_toml_value(i) for i in items if i.strip()]
    if raw.startswith("{"):
        inner = raw[1:-1] if raw.endswith("}") else raw[1:]
        out: Dict[str, Any] = {}
        for part in _split_top(inner):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip().strip("\"'")] = _toml_value(v)
        return out
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _split_top(text: str) -> List[str]:
    parts, depth, buf, quote = [], 0, [], ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _mini_toml(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    current = root
    buffer = ""
    for raw_line in text.splitlines():
        line = raw_line.split("#")[0].rstrip() if not raw_line.strip().startswith("#") else ""
        if not line.strip():
            continue
        if buffer:
            buffer += " " + line.strip()
            if buffer.count("[") <= buffer.count("]") and buffer.count("{") <= buffer.count("}"):
                line, buffer = buffer, ""
            else:
                continue
        if line.strip().startswith("[["):
            name = line.strip().strip("[]")
            current = _descend(root, name.split("."), array=True)
            continue
        if line.strip().startswith("["):
            name = line.strip().strip("[]")
            current = _descend(root, name.split("."))
            continue
        m = _TOML_KEY.match(line)
        if not m:
            continue
        key, value = m.group(1).strip().strip("\"'"), m.group(2)
        if value.count("[") > value.count("]") or value.count("{") > value.count("}"):
            buffer = line
            continue
        target = current
        if "." in key:
            *path, key = [p.strip().strip("\"'") for p in key.split(".")]
            target = _descend(current, path)
        target[key] = _toml_value(value)
    return root


def _descend(root: Dict[str, Any], path: List[str], array: bool = False) -> Dict[str, Any]:
    node: Dict[str, Any] = root
    for i, part in enumerate(path):
        part = part.strip().strip("\"'")
        last = i == len(path) - 1
        if last and array:
            node.setdefault(part, [])
            if not isinstance(node[part], list):
                node[part] = [node[part]]
            fresh: Dict[str, Any] = {}
            node[part].append(fresh)
            return fresh
        nxt = node.get(part)
        if isinstance(nxt, list) and nxt and isinstance(nxt[-1], dict):
            node = nxt[-1]
        elif isinstance(nxt, dict):
            node = nxt
        else:
            node[part] = {}
            node = node[part]
    return node


# --------------------------------------------------------------------- YAML

def load_yaml(text: str) -> Any:
    docs = load_yaml_all(text)
    return docs[0] if docs else None


def load_yaml_all(text: str) -> List[Any]:
    if _pyyaml is not None:
        try:
            return [d for d in _pyyaml.safe_load_all(text) if d is not None]
        except Exception:
            pass
    return [d for d in _mini_yaml_all(text) if d is not None]


def _mini_yaml_all(text: str) -> List[Any]:
    docs: List[Any] = []
    current: List[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            docs.append(_mini_yaml("\n".join(current)))
            current = []
            continue
        current.append(line)
    docs.append(_mini_yaml("\n".join(current)))
    return docs


def _yaml_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in "\"'" and raw[-1] == raw[0] and len(raw) > 1:
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        return [_yaml_scalar(p) for p in _split_top(raw[1:-1]) if p.strip()]
    if raw.startswith("{") and raw.endswith("}"):
        out = {}
        for part in _split_top(raw[1:-1]):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip().strip("\"'")] = _yaml_scalar(v)
        return out
    low = raw.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d*\.\d+", raw):
        return float(raw)
    return raw


def _mini_yaml(text: str) -> Any:
    """Indentation-driven YAML subset: maps, lists, scalars, block scalars."""
    lines: List[Tuple[int, str]] = []
    block_indent: Optional[int] = None
    block_lines: List[str] = []
    pending_key: Optional[Tuple[int, str]] = None

    raw_lines = text.split("\n")
    i = 0
    while i < len(raw_lines):
        raw = raw_lines[i]
        i += 1
        if block_indent is not None:
            indent = len(raw) - len(raw.lstrip()) if raw.strip() else block_indent + 1
            if raw.strip() and indent <= block_indent:
                lines.append((pending_key[0], f"{pending_key[1]}: {' '.join(block_lines).strip()[:400]}"))
                block_indent, block_lines, pending_key = None, [], None
                i -= 1
                continue
            block_lines.append(raw.strip())
            continue
        stripped = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip())
        content = stripped.strip()
        m = re.match(r"^([\w.\-/\"'@ ]+):\s*([|>][-+]?)\s*$", content)
        if m:
            block_indent = indent
            pending_key = (indent, m.group(1).strip())
            block_lines = []
            continue
        lines.append((indent, content))
    if pending_key is not None:
        lines.append((pending_key[0], f"{pending_key[1]}: {' '.join(block_lines).strip()[:400]}"))

    value, _ = _yaml_block(lines, 0, 0)
    return value


def _yaml_block(lines: List[Tuple[int, str]], pos: int, indent: int) -> Tuple[Any, int]:
    if pos >= len(lines):
        return None, pos
    is_list = lines[pos][1].startswith("- ") or lines[pos][1] == "-"
    if is_list:
        items: List[Any] = []
        while pos < len(lines):
            cur_indent, content = lines[pos]
            if cur_indent < indent or not (content.startswith("- ") or content == "-"):
                break
            rest = content[2:].strip() if content.startswith("- ") else ""
            pos += 1
            if not rest:
                child, pos = _yaml_block(lines, pos, cur_indent + 1)
                items.append(child)
            elif re.match(r"^[\w.\-/\"'@ ]+:(\s|$)", rest):
                sub_lines = [(cur_indent + 2, rest)]
                while pos < len(lines) and lines[pos][0] > cur_indent:
                    sub_lines.append((lines[pos][0], lines[pos][1]))
                    pos += 1
                child, _ = _yaml_block(sub_lines, 0, cur_indent + 2)
                items.append(child)
            else:
                items.append(_yaml_scalar(rest))
        return items, pos

    mapping: Dict[str, Any] = {}
    while pos < len(lines):
        cur_indent, content = lines[pos]
        if cur_indent < indent:
            break
        if content.startswith("- "):
            break
        m = re.match(r"^([^:]+?):\s*(.*)$", content)
        if not m:
            pos += 1
            continue
        key = m.group(1).strip().strip("\"'")
        rest = m.group(2).strip()
        pos += 1
        if rest:
            mapping[key] = _yaml_scalar(rest)
            continue
        if pos < len(lines) and (lines[pos][0] > cur_indent or lines[pos][1].startswith("- ")):
            child, pos = _yaml_block(lines, pos, cur_indent + 1 if lines[pos][0] > cur_indent else cur_indent)
            mapping[key] = child
        else:
            mapping[key] = None
    return mapping, pos


# ---------------------------------------------------------------------- XML

def load_xml(text: str):
    import xml.etree.ElementTree as ET

    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


# --------------------------------------------------------------------- .env

def load_dotenv(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip().removeprefix("export ").strip()] = value.strip().strip("\"'")
    return out
