"""Lockfile parsing.

Lockfiles give *resolved* versions, which is what vulnerability matching needs;
declared ranges in a manifest are not enough to say whether you are exposed.
"""

from __future__ import annotations

import re
from typing import Dict, List

from ..model import Dependency
from ..parsers import load_json, load_toml, load_yaml
from .manifest import ECOSYSTEM_PURL


def _mk(name: str, version: str, ecosystem: str, path: str, direct: bool = False,
        scope: str = "runtime") -> Dependency:
    return Dependency(
        name=name, version=version, ecosystem=ecosystem, scope=scope,
        declared_in=[path], direct=direct, declared=True,
        purl=f"pkg:{ECOSYSTEM_PURL.get(ecosystem, ecosystem)}/{name}@{version}" if version else "",
    )


def parse_package_lock(path: str, text: str) -> List[Dependency]:
    data = load_json(text)
    out: List[Dependency] = []
    if not isinstance(data, dict):
        return out
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, info in packages.items():
            if not key or not isinstance(info, dict):
                continue
            name = key.split("node_modules/")[-1]
            version = str(info.get("version", ""))
            if not name or not version:
                continue
            out.append(_mk(name, version, "npm", path,
                           scope="dev" if info.get("dev") else "runtime"))
        return out
    deps = data.get("dependencies")
    if isinstance(deps, dict):
        stack = [(name, info) for name, info in deps.items()]
        while stack:
            name, info = stack.pop()
            if not isinstance(info, dict):
                continue
            version = str(info.get("version", ""))
            if version:
                out.append(_mk(name, version, "npm", path,
                               scope="dev" if info.get("dev") else "runtime"))
            nested = info.get("dependencies")
            if isinstance(nested, dict):
                stack.extend(nested.items())
    return out


_YARN_ENTRY = re.compile(r"^\"?([^\s\"]+?)@[^\s\":]+[^\n]*:\n(?:.*\n)*?\s+version[:\s]+\"?([\w.\-+]+)", re.M)


def parse_yarn_lock(path: str, text: str) -> List[Dependency]:
    out: List[Dependency] = []
    current: str = ""
    for line in text.splitlines():
        if line and not line.startswith((" ", "\t", "#")) and line.rstrip().endswith(":"):
            spec = line.rstrip(":").split(",")[0].strip().strip('"')
            at = spec.rfind("@")
            current = spec[:at] if at > 0 else spec
        elif current and re.match(r"^\s+version[:\s]", line):
            version = line.split(":", 1)[-1].strip().strip('"') if ":" in line else line.split()[-1].strip('"')
            out.append(_mk(current, version, "npm", path))
            current = ""
    return out


def parse_pnpm_lock(path: str, text: str) -> List[Dependency]:
    out: List[Dependency] = []
    for match in re.finditer(r"^\s{2}/?((?:@[\w.\-]+/)?[\w.\-]+)[@/](\d[\w.\-+]*)\s*:", text, re.M):
        out.append(_mk(match.group(1), match.group(2), "npm", path))
    return out


def parse_poetry_lock(path: str, text: str) -> List[Dependency]:
    data = load_toml(text)
    out: List[Dependency] = []
    packages = data.get("package")
    if isinstance(packages, list):
        for pkg in packages:
            if isinstance(pkg, dict) and pkg.get("name"):
                out.append(_mk(str(pkg["name"]), str(pkg.get("version", "")), "pypi", path,
                               scope="dev" if pkg.get("category") == "dev" else "runtime"))
    return out


def parse_cargo_lock(path: str, text: str) -> List[Dependency]:
    data = load_toml(text)
    out: List[Dependency] = []
    packages = data.get("package")
    if isinstance(packages, list):
        for pkg in packages:
            if isinstance(pkg, dict) and pkg.get("name"):
                out.append(_mk(str(pkg["name"]), str(pkg.get("version", "")), "cargo", path))
    return out


def parse_gemfile_lock(path: str, text: str) -> List[Dependency]:
    out: List[Dependency] = []
    in_specs = False
    for line in text.splitlines():
        if line.strip() == "specs:":
            in_specs = True
            continue
        if in_specs and line and not line.startswith(" "):
            in_specs = False
        if in_specs:
            match = re.match(r"^\s{4}([\w.\-]+) \(([^)]+)\)", line)
            if match:
                out.append(_mk(match.group(1), match.group(2), "rubygems", path))
    return out


def parse_composer_lock(path: str, text: str) -> List[Dependency]:
    data = load_json(text)
    out: List[Dependency] = []
    if not isinstance(data, dict):
        return out
    for key, scope in (("packages", "runtime"), ("packages-dev", "dev")):
        for pkg in data.get(key) or []:
            if isinstance(pkg, dict) and pkg.get("name"):
                out.append(_mk(str(pkg["name"]), str(pkg.get("version", "")), "composer", path, scope=scope))
    return out


def parse_go_sum(path: str, text: str) -> List[Dependency]:
    seen: Dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("v"):
            version = parts[1].replace("/go.mod", "")
            seen.setdefault(parts[0], version)
    return [_mk(name, version, "go", path) for name, version in seen.items()]


def parse_packages_lock_json(path: str, text: str) -> List[Dependency]:
    data = load_json(text)
    out: List[Dependency] = []
    if not isinstance(data, dict):
        return out
    for _framework, packages in (data.get("dependencies") or {}).items():
        if not isinstance(packages, dict):
            continue
        for name, info in packages.items():
            if isinstance(info, dict) and info.get("resolved"):
                out.append(_mk(name, str(info["resolved"]), "nuget", path,
                               direct=info.get("type") == "Direct"))
    return out


def parse_pubspec_lock(path: str, text: str) -> List[Dependency]:
    data = load_yaml(text)
    out: List[Dependency] = []
    packages = data.get("packages") if isinstance(data, dict) else None
    if isinstance(packages, dict):
        for name, info in packages.items():
            if isinstance(info, dict):
                out.append(_mk(str(name), str(info.get("version", "")), "pub", path))
    return out


LOCK_PARSERS = {
    "package-lock.json": parse_package_lock,
    "npm-shrinkwrap.json": parse_package_lock,
    "yarn.lock": parse_yarn_lock,
    "pnpm-lock.yaml": parse_pnpm_lock,
    "poetry.lock": parse_poetry_lock,
    "cargo.lock": parse_cargo_lock,
    "gemfile.lock": parse_gemfile_lock,
    "composer.lock": parse_composer_lock,
    "go.sum": parse_go_sum,
    "packages.lock.json": parse_packages_lock_json,
    "pubspec.lock": parse_pubspec_lock,
}


def is_lockfile(rel: str) -> bool:
    return rel.rsplit("/", 1)[-1].lower() in LOCK_PARSERS


def parse_lockfile(rel: str, text: str) -> List[Dependency]:
    parser = LOCK_PARSERS.get(rel.rsplit("/", 1)[-1].lower())
    if parser is None:
        return []
    try:
        return parser(rel, text)
    except Exception:
        return []
