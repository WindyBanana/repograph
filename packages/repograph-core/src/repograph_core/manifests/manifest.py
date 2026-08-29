"""Package manifest parsing: what a project is called and what it depends on."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..model import Dependency
from ..parsers import load_json, load_toml, load_xml, load_yaml, strip_ns

ECOSYSTEM_PURL = {
    "npm": "npm", "pypi": "pypi", "go": "golang", "maven": "maven", "nuget": "nuget",
    "cargo": "cargo", "rubygems": "gem", "composer": "composer", "pub": "pub", "hex": "hex",
}


@dataclass
class Manifest:
    path: str
    ecosystem: str
    name: str = ""
    version: str = ""
    description: str = ""
    license: str = ""
    private: bool = False
    kind_hint: str = ""
    workspaces: List[str] = field(default_factory=list)
    scripts: Dict[str, str] = field(default_factory=dict)
    entrypoints: List[str] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    module_path: str = ""  # go module path / maven groupId / package namespace

    @property
    def dir(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


def _dep(name: str, version: Any, ecosystem: str, scope: str, path: str) -> Dependency:
    ver = ""
    if isinstance(version, str):
        ver = version
    elif isinstance(version, dict):
        ver = str(version.get("version", "") or version.get("rev", "") or "")
    return Dependency(
        name=name.strip(),
        version=str(ver).strip(),
        ecosystem=ecosystem,
        scope=scope,
        declared_in=[path],
        purl=f"pkg:{ECOSYSTEM_PURL.get(ecosystem, ecosystem)}/{name.strip()}"
        + (f"@{clean_version(ver)}" if ver else ""),
    )


def clean_version(version: Any) -> str:
    return re.sub(r"^[\^~>=<\s\"'v]*", "", str(version)).strip().strip('"')


# ------------------------------------------------------------------ npm/node

def parse_package_json(path: str, text: str) -> Optional[Manifest]:
    data = load_json(text)
    if not isinstance(data, dict):
        return None
    m = Manifest(path=path, ecosystem="npm", name=str(data.get("name", "") or ""),
                 version=str(data.get("version", "") or ""),
                 description=str(data.get("description", "") or ""),
                 private=bool(data.get("private")),
                 license=str(data.get("license", "") or ""))
    workspaces = data.get("workspaces")
    if isinstance(workspaces, list):
        m.workspaces = [str(w) for w in workspaces]
    elif isinstance(workspaces, dict) and isinstance(workspaces.get("packages"), list):
        m.workspaces = [str(w) for w in workspaces["packages"]]
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        m.scripts = {str(k): str(v) for k, v in scripts.items()}
    for key in ("main", "module", "bin"):
        value = data.get(key)
        if isinstance(value, str):
            m.entrypoints.append(value)
        elif isinstance(value, dict):
            m.entrypoints.extend(str(v) for v in value.values() if isinstance(v, str))
    for field_name, scope in (
        ("dependencies", "runtime"), ("devDependencies", "dev"),
        ("peerDependencies", "peer"), ("optionalDependencies", "optional"),
    ):
        block = data.get(field_name)
        if isinstance(block, dict):
            for name, version in block.items():
                m.dependencies.append(_dep(str(name), version, "npm", scope, path))
    deps = {d.name for d in m.dependencies}
    if {"react", "vue", "svelte", "@angular/core", "next", "nuxt"} & deps:
        m.kind_hint = "frontend"
    elif {"express", "fastify", "@nestjs/core", "koa", "hapi"} & deps:
        m.kind_hint = "service"
    elif data.get("bin"):
        m.kind_hint = "cli"
    elif not m.private and data.get("main"):
        m.kind_hint = "library"
    return m


# -------------------------------------------------------------------- python

def parse_pyproject(path: str, text: str) -> Optional[Manifest]:
    data = load_toml(text)
    if not isinstance(data, dict):
        return None
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
    source = project or poetry
    m = Manifest(path=path, ecosystem="pypi",
                 name=str(source.get("name", "") or ""),
                 version=str(source.get("version", "") or ""),
                 description=str(source.get("description", "") or ""))
    lic = source.get("license")
    if isinstance(lic, str):
        m.license = lic
    elif isinstance(lic, dict):
        m.license = str(lic.get("text", "") or lic.get("file", ""))
    for raw in project.get("dependencies", []) or []:
        if isinstance(raw, str):
            name, version = split_pep508(raw)
            if name:
                m.dependencies.append(_dep(name, version, "pypi", "runtime", path))
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group, items in optional.items():
            for raw in items or []:
                if isinstance(raw, str):
                    name, version = split_pep508(raw)
                    if name:
                        scope = "dev" if group in ("dev", "test", "tests", "lint", "docs") else "optional"
                        m.dependencies.append(_dep(name, version, "pypi", scope, path))
    poetry_deps = poetry.get("dependencies")
    if isinstance(poetry_deps, dict):
        for name, spec in poetry_deps.items():
            if str(name).lower() == "python":
                continue
            m.dependencies.append(_dep(str(name), spec, "pypi", "runtime", path))
    group = poetry.get("group") if isinstance(poetry.get("group"), dict) else {}
    for gdata in group.values():
        deps = gdata.get("dependencies") if isinstance(gdata, dict) else None
        if isinstance(deps, dict):
            for name, spec in deps.items():
                m.dependencies.append(_dep(str(name), spec, "pypi", "dev", path))
    scripts = source.get("scripts") or {}
    if isinstance(scripts, dict) and scripts:
        m.scripts = {str(k): str(v) for k, v in scripts.items()}
        m.entrypoints.extend(str(v) for v in scripts.values())
        m.kind_hint = "cli"
    return m


def split_pep508(raw: str) -> tuple:
    raw = raw.split(";")[0].strip()
    match = re.match(r"^([A-Za-z0-9._\-]+)\s*(\[[^\]]*\])?\s*(.*)$", raw)
    if not match:
        return "", ""
    return match.group(1), match.group(3).strip()


def parse_requirements(path: str, text: str) -> Optional[Manifest]:
    scope = "dev" if re.search(r"(dev|test|lint|doc)", path.rsplit("/", 1)[-1], re.I) else "runtime"
    m = Manifest(path=path, ecosystem="pypi")
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        if line.startswith(("git+", "http")):
            m.dependencies.append(
                _dep(line.rsplit("/", 1)[-1].split(".git")[0], "", "pypi", scope, path)
            )
            continue
        name, version = split_pep508(line)
        if name:
            m.dependencies.append(_dep(name, version, "pypi", scope, path))
    return m if m.dependencies else None


def parse_setup_py(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="pypi")
    name = re.search(r"name\s*=\s*[\"']([^\"']+)[\"']", text)
    if name:
        m.name = name.group(1)
    version = re.search(r"version\s*=\s*[\"']([^\"']+)[\"']", text)
    if version:
        m.version = version.group(1)
    block = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.S)
    if block:
        for raw in re.findall(r"[\"']([^\"']+)[\"']", block.group(1)):
            dep_name, dep_version = split_pep508(raw)
            if dep_name:
                m.dependencies.append(_dep(dep_name, dep_version, "pypi", "runtime", path))
    return m


def parse_pipfile(path: str, text: str) -> Optional[Manifest]:
    data = load_toml(text)
    m = Manifest(path=path, ecosystem="pypi")
    for section, scope in (("packages", "runtime"), ("dev-packages", "dev")):
        block = data.get(section)
        if isinstance(block, dict):
            for name, spec in block.items():
                m.dependencies.append(_dep(str(name), spec, "pypi", scope, path))
    return m


# ------------------------------------------------------------------------ go

def parse_go_mod(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="go")
    module = re.search(r"^module\s+(\S+)", text, re.M)
    if module:
        m.module_path = module.group(1)
        m.name = module.group(1).rsplit("/", 1)[-1]
    in_block = False
    for line in text.splitlines():
        stripped = line.split("//")[0].strip()
        if stripped.startswith("require ("):
            in_block = True
            continue
        if in_block and stripped == ")":
            in_block = False
            continue
        target = stripped[len("require ") :].strip() if stripped.startswith("require ") else (
            stripped if in_block else ""
        )
        if not target:
            continue
        parts = target.split()
        if len(parts) >= 2 and parts[1].startswith("v"):
            dep = _dep(parts[0], parts[1], "go", "runtime", path)
            dep.direct = "// indirect" not in line
            m.dependencies.append(dep)
    return m


def parse_go_work(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="go", name="go-workspace")
    block = re.search(r"use\s*\(([^)]*)\)", text, re.S)
    if block:
        m.workspaces = [ln.strip() for ln in block.group(1).splitlines() if ln.strip()]
    for match in re.finditer(r"^use\s+(\S+)\s*$", text, re.M):
        m.workspaces.append(match.group(1))
    return m


# --------------------------------------------------------------------- maven

def parse_pom(path: str, text: str) -> Optional[Manifest]:
    root = load_xml(text)
    if root is None:
        return None
    m = Manifest(path=path, ecosystem="maven")

    def child(node, tag):
        return next((c for c in node if strip_ns(c.tag) == tag), None)

    artifact = child(root, "artifactId")
    group = child(root, "groupId")
    version = child(root, "version")
    name = child(root, "name")
    desc = child(root, "description")
    m.name = (name.text if name is not None and name.text else
              (artifact.text if artifact is not None and artifact.text else "")) or ""
    m.module_path = (group.text or "") if group is not None else ""
    m.version = (version.text or "") if version is not None else ""
    m.description = (desc.text or "").strip() if desc is not None and desc.text else ""
    modules = child(root, "modules")
    if modules is not None:
        m.workspaces = [c.text for c in modules if c.text]
    deps = child(root, "dependencies")
    if deps is not None:
        for d in deps:
            g = child(d, "groupId")
            a = child(d, "artifactId")
            v = child(d, "version")
            s = child(d, "scope")
            if a is None or not a.text:
                continue
            full = f"{g.text}:{a.text}" if g is not None and g.text else a.text
            m.dependencies.append(
                _dep(full, v.text if v is not None and v.text else "", "maven",
                     "test" if s is not None and s.text == "test" else "runtime", path)
            )
    return m


_GRADLE_DEP = re.compile(
    r"""^\s*(implementation|api|compile|runtimeOnly|testImplementation|testCompile|kapt|annotationProcessor)"""
    r"""\s*[\( ]\s*["']([^"':]+):([^"':]+)(?::([^"']+))?["']""",
    re.M,
)


def parse_gradle(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="maven")
    for match in _GRADLE_DEP.finditer(text):
        scope = "test" if match.group(1).startswith("test") else "runtime"
        m.dependencies.append(
            _dep(f"{match.group(2)}:{match.group(3)}", match.group(4) or "", "maven", scope, path)
        )
    return m


def parse_settings_gradle(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="maven")
    name = re.search(r"rootProject\.name\s*=\s*[\"']([^\"']+)[\"']", text)
    if name:
        m.name = name.group(1)
    for match in re.finditer(r"include\s*\(?\s*([^)\n]+)", text):
        for token in match.group(1).split(","):
            cleaned = token.strip().strip("'\"").lstrip(":").replace(":", "/")
            if cleaned:
                m.workspaces.append(cleaned)
    return m


# --------------------------------------------------------------------- nuget

def parse_csproj(path: str, text: str) -> Optional[Manifest]:
    root = load_xml(text)
    m = Manifest(path=path, ecosystem="nuget", name=path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    if root is None:
        return m
    for node in root.iter():
        tag = strip_ns(node.tag)
        if tag == "PackageReference":
            name = node.get("Include") or node.get("Update") or ""
            version = node.get("Version") or ""
            if not version:
                for c in node:
                    if strip_ns(c.tag) == "Version" and c.text:
                        version = c.text
            if name:
                m.dependencies.append(_dep(name, version, "nuget", "runtime", path))
        elif tag == "ProjectReference":
            include = node.get("Include") or ""
            if include:
                m.entrypoints.append(include.replace("\\", "/"))
        elif tag == "OutputType" and node.text:
            m.kind_hint = "cli" if node.text.strip().lower() == "exe" else "library"
    return m


def parse_sln(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="nuget", name=path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    m.workspaces = [p.replace("\\", "/").rsplit("/", 1)[0]
                    for p in re.findall(r"\"([^\"]+\.(?:cs|fs|vb)proj)\"", text)]
    return m


# --------------------------------------------------------------------- cargo

def parse_cargo(path: str, text: str) -> Optional[Manifest]:
    data = load_toml(text)
    if not isinstance(data, dict):
        return None
    package = data.get("package") if isinstance(data.get("package"), dict) else {}
    m = Manifest(path=path, ecosystem="cargo", name=str(package.get("name", "") or ""),
                 version=str(package.get("version", "") or ""),
                 description=str(package.get("description", "") or ""),
                 license=str(package.get("license", "") or ""))
    workspace = data.get("workspace")
    if isinstance(workspace, dict) and isinstance(workspace.get("members"), list):
        m.workspaces = [str(x) for x in workspace["members"]]
    for section, scope in (("dependencies", "runtime"), ("dev-dependencies", "dev"),
                           ("build-dependencies", "build")):
        block = data.get(section)
        if isinstance(block, dict):
            for name, spec in block.items():
                m.dependencies.append(_dep(str(name), spec, "cargo", scope, path))
    if isinstance(data.get("bin"), list):
        m.kind_hint = "cli"
    return m


# --------------------------------------------------------- ruby / php / other

def parse_gemfile(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="rubygems")
    for match in re.finditer(r"""^\s*gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""", text, re.M):
        m.dependencies.append(_dep(match.group(1), match.group(2) or "", "rubygems", "runtime", path))
    return m


def parse_gemspec(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="rubygems")
    name = re.search(r"\.name\s*=\s*[\"']([^\"']+)", text)
    if name:
        m.name = name.group(1)
    return m


def parse_composer(path: str, text: str) -> Optional[Manifest]:
    data = load_json(text)
    if not isinstance(data, dict):
        return None
    m = Manifest(path=path, ecosystem="composer", name=str(data.get("name", "") or ""),
                 description=str(data.get("description", "") or ""))
    lic = data.get("license")
    m.license = lic if isinstance(lic, str) else ", ".join(lic) if isinstance(lic, list) else ""
    for key, scope in (("require", "runtime"), ("require-dev", "dev")):
        block = data.get(key)
        if isinstance(block, dict):
            for name, version in block.items():
                if str(name).lower() == "php" or str(name).startswith("ext-"):
                    continue
                m.dependencies.append(_dep(str(name), version, "composer", scope, path))
    return m


def parse_pubspec(path: str, text: str) -> Optional[Manifest]:
    data = load_yaml(text)
    if not isinstance(data, dict):
        return None
    m = Manifest(path=path, ecosystem="pub", name=str(data.get("name", "") or ""),
                 version=str(data.get("version", "") or ""),
                 description=str(data.get("description", "") or ""))
    for key, scope in (("dependencies", "runtime"), ("dev_dependencies", "dev")):
        block = data.get(key)
        if isinstance(block, dict):
            for name, spec in block.items():
                m.dependencies.append(_dep(str(name), spec, "pub", scope, path))
    return m


def parse_mix(path: str, text: str) -> Optional[Manifest]:
    m = Manifest(path=path, ecosystem="hex")
    app = re.search(r"app:\s*:(\w+)", text)
    if app:
        m.name = app.group(1)
    for match in re.finditer(r"\{\s*:(\w+)\s*,\s*\"([^\"]+)\"", text):
        m.dependencies.append(_dep(match.group(1), match.group(2), "hex", "runtime", path))
    return m


def parse_workspace_yaml(path: str, text: str) -> Optional[Manifest]:
    data = load_yaml(text)
    m = Manifest(path=path, ecosystem="npm", name="workspace")
    if isinstance(data, dict) and isinstance(data.get("packages"), list):
        m.workspaces = [str(p) for p in data["packages"]]
    return m


def parse_lerna(path: str, text: str) -> Optional[Manifest]:
    data = load_json(text)
    m = Manifest(path=path, ecosystem="npm", name="workspace")
    if isinstance(data, dict) and isinstance(data.get("packages"), list):
        m.workspaces = [str(p) for p in data["packages"]]
    return m


PARSERS = {
    "package.json": parse_package_json,
    "pyproject.toml": parse_pyproject,
    "setup.py": parse_setup_py,
    "pipfile": parse_pipfile,
    "go.mod": parse_go_mod,
    "go.work": parse_go_work,
    "pom.xml": parse_pom,
    "build.gradle": parse_gradle,
    "build.gradle.kts": parse_gradle,
    "settings.gradle": parse_settings_gradle,
    "settings.gradle.kts": parse_settings_gradle,
    "cargo.toml": parse_cargo,
    "gemfile": parse_gemfile,
    "composer.json": parse_composer,
    "pubspec.yaml": parse_pubspec,
    "mix.exs": parse_mix,
    "pnpm-workspace.yaml": parse_workspace_yaml,
    "lerna.json": parse_lerna,
}


def parse_manifest(rel: str, text: str) -> Optional[Manifest]:
    name = rel.rsplit("/", 1)[-1].lower()
    parser = PARSERS.get(name)
    if parser is not None:
        try:
            return parser(rel, text)
        except Exception:
            return None
    try:
        if name.startswith("requirements") and name.endswith(".txt"):
            return parse_requirements(rel, text)
        if name.endswith((".csproj", ".fsproj", ".vbproj")):
            return parse_csproj(rel, text)
        if name.endswith(".sln"):
            return parse_sln(rel, text)
        if name.endswith(".gemspec"):
            return parse_gemspec(rel, text)
    except Exception:
        return None
    return None


def is_manifest(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1].lower()
    return (
        name in PARSERS
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.endswith((".csproj", ".fsproj", ".vbproj", ".sln", ".gemspec"))
    )
