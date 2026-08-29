"""Dependency risk.

Two independent passes:

* **Offline hygiene** — always runs. Unpinned ranges, missing lockfiles,
  dependencies that are declared but never imported, imports that are never
  declared, and packages known to be deprecated.
* **Advisories** — opt-in (``--online``). Queries the OSV.dev API, which is the
  same data GitHub, Google and the Go vulnerability database publish, and caches
  responses locally so repeated scans are fast and reproducible.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..model import Dependency, Finding
from ..util import chunked, slug
from .cvss import score_and_severity

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"

OSV_ECOSYSTEM = {
    "npm": "npm", "pypi": "PyPI", "go": "Go", "maven": "Maven", "nuget": "NuGet",
    "cargo": "crates.io", "rubygems": "RubyGems", "composer": "Packagist",
    "pub": "Pub", "hex": "Hex",
}

# Packages whose upstream has stopped: still installable, no longer maintained.
DEPRECATED = {
    "npm": {
        "request": "Deprecated in 2020; use undici, axios or fetch.",
        "left-pad": "Trivial package; use String.prototype.padStart.",
        "node-uuid": "Renamed to uuid.",
        "istanbul": "Superseded by nyc / c8.",
        "tslint": "Deprecated; use ESLint with typescript-eslint.",
        "gulp-util": "Deprecated by the gulp team.",
        "babel-eslint": "Renamed to @babel/eslint-parser.",
        "moment": "In maintenance mode; consider date-fns, dayjs or Temporal.",
        "core-js@2": "Version 2 is unmaintained.",
        "npmlog": "Deprecated by npm.",
        "querystringify": "Superseded by URLSearchParams.",
    },
    "pypi": {
        "nose": "Unmaintained; use pytest.",
        "distribute": "Merged back into setuptools years ago.",
        "pycrypto": "Unmaintained and vulnerable; use pycryptodome or cryptography.",
        "python-dateutil<2": "Ancient release line.",
        "sklearn": "Placeholder package; depend on scikit-learn.",
        "django-rest-swagger": "Deprecated; use drf-spectacular.",
        "flask-script": "Deprecated; use Flask's built-in CLI.",
    },
    "rubygems": {"therubyracer": "Unmaintained; use mini_racer."},
    "maven": {"log4j:log4j": "1.x is end of life; migrate to log4j2 or logback."},
}

_UNPINNED = ("*", "latest", "", "x", "^", "~", ">=", ">", "master", "main", "HEAD")


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(base, "repograph", "osv")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------- offline

def hygiene_findings(dependencies: Sequence[Dependency], lockfiles: Sequence[str],
                     ecosystems: Iterable[str]) -> List[Finding]:
    findings: List[Finding] = []
    lock_by_ecosystem = {
        "npm": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "bun.lockb"),
        "pypi": ("poetry.lock", "Pipfile.lock", "requirements.txt", "uv.lock", "pdm.lock"),
        "cargo": ("Cargo.lock",), "go": ("go.sum",), "composer": ("composer.lock",),
        "rubygems": ("Gemfile.lock",), "pub": ("pubspec.lock",), "nuget": ("packages.lock.json",),
    }
    lock_names = {os.path.basename(p) for p in lockfiles}
    # The missing file has no path, so point at the manifest that declares the
    # dependencies instead: a finding nobody can navigate to is not actionable.
    manifest_for: Dict[str, str] = {}
    for dep in dependencies:
        if dep.declared_in and dep.ecosystem not in manifest_for:
            manifest_for[dep.ecosystem] = dep.declared_in[0]
    for ecosystem in sorted(set(ecosystems)):
        expected = lock_by_ecosystem.get(ecosystem)
        if not expected:
            continue
        if not any(name in lock_names for name in expected):
            manifest = manifest_for.get(ecosystem, "")
            where = os.path.dirname(manifest) or "the project root"
            findings.append(
                Finding(
                    id=slug("dep", "nolock", ecosystem),
                    title=f"No lockfile for the {ecosystem} dependencies",
                    severity="low",
                    category="dependency",
                    file=manifest,
                    identifier="RG-DEP-NOLOCK",
                    confidence="high",
                    remediation=f"Commit one of {', '.join(expected)} next to {manifest or 'the manifest'} "
                                f"in {where}, so builds are reproducible and vulnerability scanning can "
                                f"see resolved versions.",
                )
            )

    for dep in dependencies:
        if dep.scope in ("dev", "test") and dep.ecosystem == "npm":
            continue
        version = (dep.version or "").strip()
        if dep.declared and (version in _UNPINNED or version.startswith(("*", "x"))):
            findings.append(
                Finding(
                    id=slug("dep", "unpinned", dep.ecosystem, dep.name),
                    title=f"Dependency '{dep.name}' is not version-pinned",
                    severity="low",
                    category="dependency",
                    package=dep.name,
                    version=version or "(any)",
                    file=dep.declared_in[0] if dep.declared_in else "",
                    identifier="RG-DEP-UNPINNED",
                    confidence="high",
                    remediation="Pin a version range you have actually tested; an open range makes every "
                                "install a different build.",
                )
            )
        note = DEPRECATED.get(dep.ecosystem, {}).get(dep.name)
        if note:
            findings.append(
                Finding(
                    id=slug("dep", "deprecated", dep.ecosystem, dep.name),
                    title=f"Dependency '{dep.name}' is deprecated or unmaintained",
                    severity="medium",
                    category="dependency",
                    package=dep.name,
                    version=version,
                    file=dep.declared_in[0] if dep.declared_in else "",
                    identifier="RG-DEP-DEPRECATED",
                    confidence="high",
                    remediation=note,
                )
            )
    return findings


def usage_findings(dependencies: Sequence[Dependency], undeclared: Dict[str, Dict[str, object]]) -> List[Finding]:
    """Declared-but-unused and used-but-undeclared packages."""
    findings: List[Finding] = []
    for dep in dependencies:
        if not dep.declared or dep.used or not dep.direct:
            continue
        if dep.scope in ("dev", "test", "build", "optional", "peer"):
            continue
        if dep.ecosystem == "maven" and ":" in dep.name:
            continue  # transitive-heavy ecosystems produce noise here
        findings.append(
            Finding(
                id=slug("dep", "unused", dep.ecosystem, dep.name),
                title=f"Declared dependency '{dep.name}' is never imported",
                severity="info",
                category="dependency",
                package=dep.name,
                version=dep.version,
                file=dep.declared_in[0] if dep.declared_in else "",
                identifier="RG-DEP-UNUSED",
                confidence="low",
                remediation="Remove it, or confirm it is loaded indirectly (plugin, CLI, runtime hook).",
            )
        )
    for name, info in sorted(undeclared.items()):
        files = info.get("files") or []
        findings.append(
            Finding(
                id=slug("dep", "missing", str(info.get("ecosystem", "")), name),
                title=f"Imported package '{name}' is not declared in any manifest",
                severity="medium",
                category="dependency",
                package=name,
                file=files[0] if files else "",
                identifier="RG-DEP-MISSING",
                confidence="medium" if len(files) > 1 else "low",
                remediation="Add it to the dependency manifest — an undeclared import breaks a clean install "
                            "and hides the package from vulnerability scanning.",
            )
        )
    return findings


# ----------------------------------------------------------------- online

class OsvClient:
    def __init__(self, timeout: float = 20.0, use_cache: bool = True, ttl_hours: int = 24) -> None:
        self.timeout = timeout
        self.use_cache = use_cache
        self.ttl = ttl_hours * 3600
        self.errors: List[str] = []

    def _post(self, url: str, payload: dict) -> Optional[dict]:
        data = json.dumps(payload).encode()
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json",
                                     "User-Agent": "repograph/0.1 (+https://github.com/WindyBanana/repograph)"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self.errors.append(f"{url}: {exc}")
            return None

    def _get(self, url: str) -> Optional[dict]:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "repograph/0.1"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self.errors.append(f"{url}: {exc}")
            return None

    def _cached_vuln(self, vuln_id: str) -> Optional[dict]:
        if not self.use_cache:
            return None
        path = os.path.join(cache_dir(), f"{vuln_id}.json")
        try:
            if os.path.exists(path) and time.time() - os.path.getmtime(path) < self.ttl * 30:
                with open(path) as fh:
                    return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        return None

    def _store_vuln(self, vuln_id: str, data: dict) -> None:
        if not self.use_cache:
            return
        try:
            with open(os.path.join(cache_dir(), f"{vuln_id}.json"), "w") as fh:
                json.dump(data, fh)
        except OSError:
            pass

    def query(self, deps: Sequence[Dependency]) -> Dict[str, List[dict]]:
        """Map ``name@version`` to the OSV advisories affecting it."""
        queries: List[dict] = []
        keys: List[str] = []
        for dep in deps:
            ecosystem = OSV_ECOSYSTEM.get(dep.ecosystem)
            version = _osv_version(dep)
            if not ecosystem or not version or not dep.name:
                continue
            name = dep.name
            if dep.ecosystem == "go":
                ecosystem = "Go"
            queries.append({"package": {"name": name, "ecosystem": ecosystem}, "version": version})
            keys.append(f"{dep.name}@{version}")

        found: Dict[str, List[str]] = {}
        for batch_keys, batch in zip(chunked(keys, 200), chunked(queries, 200)):
            response = self._post(OSV_BATCH_URL, {"queries": list(batch)})
            if not response:
                continue
            for key, result in zip(batch_keys, response.get("results", [])):
                ids = [v.get("id") for v in (result.get("vulns") or []) if v.get("id")]
                if ids:
                    found.setdefault(key, []).extend(ids)

        details: Dict[str, dict] = {}
        for ids in found.values():
            for vuln_id in ids:
                if vuln_id in details:
                    continue
                cached = self._cached_vuln(vuln_id)
                if cached is None:
                    cached = self._get(OSV_VULN_URL + vuln_id)
                    if cached:
                        self._store_vuln(vuln_id, cached)
                if cached:
                    details[vuln_id] = cached

        return {key: [details[i] for i in ids if i in details] for key, ids in found.items()}


def _osv_version(dep: Dependency) -> str:
    version = (dep.version or "").strip()
    version = version.lstrip("=^~v ").strip()
    if not version or any(c in version for c in "*<>|,^~ "):
        return ""
    return version


def advisory_findings(deps: Sequence[Dependency], results: Dict[str, List[dict]]) -> List[Finding]:
    by_key: Dict[str, Dependency] = {}
    for dep in deps:
        version = _osv_version(dep)
        if version:
            by_key.setdefault(f"{dep.name}@{version}", dep)

    findings: List[Finding] = []
    for key, vulns in sorted(results.items()):
        dep = by_key.get(key)
        for vuln in vulns:
            severity, score = _severity_of(vuln)
            fixed = _fixed_version(vuln, dep.name if dep else "")
            aliases = [a for a in vuln.get("aliases", []) if a.startswith("CVE")]
            identifier = aliases[0] if aliases else vuln.get("id", "")
            summary = (vuln.get("summary") or vuln.get("details", "")[:160] or "Known vulnerability").strip()
            findings.append(
                Finding(
                    id=slug("vuln", vuln.get("id", ""), key),
                    title=f"{key.split('@')[0]}: {summary}",
                    severity=severity,
                    category="dependency",
                    package=dep.name if dep else key.split("@")[0],
                    version=key.split("@")[-1],
                    fixed_version=fixed,
                    identifier=identifier,
                    cwe=", ".join(vuln.get("database_specific", {}).get("cwe_ids", []) or []),
                    confidence="high",
                    file=dep.declared_in[0] if dep and dep.declared_in else "",
                    remediation=(f"Upgrade to {fixed} or later." if fixed
                                 else "No fixed version published — evaluate mitigations or replace the package."),
                    references=[r.get("url", "") for r in (vuln.get("references") or [])][:4]
                    + ([f"https://osv.dev/vulnerability/{vuln.get('id')}"] if vuln.get("id") else []),
                )
            )
            if score is not None:
                findings[-1].title = f"{findings[-1].title} (CVSS {score})"
    return findings


def _severity_of(vuln: dict) -> Tuple[str, Optional[float]]:
    for entry in vuln.get("severity") or []:
        if entry.get("type", "").startswith("CVSS") and entry.get("score"):
            score, severity = score_and_severity(str(entry["score"]))
            if score is not None:
                return severity, score
    database = vuln.get("database_specific") or {}
    label = str(database.get("severity", "")).lower()
    if label in ("critical", "high", "moderate", "medium", "low"):
        return {"moderate": "medium"}.get(label, label), None
    return "medium", None


def _fixed_version(vuln: dict, package: str) -> str:
    for affected in vuln.get("affected") or []:
        name = (affected.get("package") or {}).get("name", "")
        if package and name and name.lower() != package.lower():
            continue
        for rng in affected.get("ranges") or []:
            for event in rng.get("events") or []:
                if event.get("fixed"):
                    return str(event["fixed"])
    return ""
