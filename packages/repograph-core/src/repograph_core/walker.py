"""File discovery: what is in the repository, in what language, and what for."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .util import read_text, rel_path

# extension -> (language, comment prefixes)
LANGUAGES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    ".py": ("Python", ("#",)),
    ".pyi": ("Python", ("#",)),
    ".ipynb": ("Jupyter", ("#",)),
    ".js": ("JavaScript", ("//", "*", "/*")),
    ".jsx": ("JavaScript", ("//", "*", "/*")),
    ".mjs": ("JavaScript", ("//", "*", "/*")),
    ".cjs": ("JavaScript", ("//", "*", "/*")),
    ".ts": ("TypeScript", ("//", "*", "/*")),
    ".tsx": ("TypeScript", ("//", "*", "/*")),
    ".mts": ("TypeScript", ("//", "*", "/*")),
    ".vue": ("Vue", ("//", "<!--")),
    ".svelte": ("Svelte", ("//", "<!--")),
    ".go": ("Go", ("//",)),
    ".rs": ("Rust", ("//",)),
    ".java": ("Java", ("//", "*", "/*")),
    ".kt": ("Kotlin", ("//", "*", "/*")),
    ".kts": ("Kotlin", ("//", "*", "/*")),
    ".scala": ("Scala", ("//", "*")),
    ".groovy": ("Groovy", ("//", "*")),
    ".cs": ("C#", ("//", "*")),
    ".fs": ("F#", ("//",)),
    ".vb": ("VB.NET", ("'",)),
    ".rb": ("Ruby", ("#",)),
    ".erb": ("Ruby", ("#", "<%#")),
    ".php": ("PHP", ("//", "#", "*")),
    ".c": ("C", ("//", "*")),
    ".h": ("C", ("//", "*")),
    ".cc": ("C++", ("//", "*")),
    ".cpp": ("C++", ("//", "*")),
    ".cxx": ("C++", ("//", "*")),
    ".hpp": ("C++", ("//", "*")),
    ".m": ("Objective-C", ("//", "*")),
    ".mm": ("Objective-C++", ("//", "*")),
    ".swift": ("Swift", ("//", "*")),
    ".dart": ("Dart", ("//", "*")),
    ".ex": ("Elixir", ("#",)),
    ".exs": ("Elixir", ("#",)),
    ".erl": ("Erlang", ("%",)),
    ".hs": ("Haskell", ("--",)),
    ".clj": ("Clojure", (";",)),
    ".lua": ("Lua", ("--",)),
    ".pl": ("Perl", ("#",)),
    ".r": ("R", ("#",)),
    ".jl": ("Julia", ("#",)),
    ".sh": ("Shell", ("#",)),
    ".bash": ("Shell", ("#",)),
    ".zsh": ("Shell", ("#",)),
    ".fish": ("Shell", ("#",)),
    ".ps1": ("PowerShell", ("#",)),
    ".sql": ("SQL", ("--",)),
    ".proto": ("Protobuf", ("//",)),
    ".graphql": ("GraphQL", ("#",)),
    ".gql": ("GraphQL", ("#",)),
    ".tf": ("Terraform", ("#",)),
    ".tfvars": ("Terraform", ("#",)),
    ".hcl": ("HCL", ("#",)),
    ".bicep": ("Bicep", ("//",)),
    ".yaml": ("YAML", ("#",)),
    ".yml": ("YAML", ("#",)),
    ".json": ("JSON", ()),
    ".jsonc": ("JSON", ("//",)),
    ".toml": ("TOML", ("#",)),
    ".ini": ("INI", ("#", ";")),
    ".cfg": ("INI", ("#", ";")),
    ".env": ("Dotenv", ("#",)),
    ".xml": ("XML", ("<!--",)),
    ".html": ("HTML", ("<!--",)),
    ".htm": ("HTML", ("<!--",)),
    ".css": ("CSS", ("/*", "*")),
    ".scss": ("SCSS", ("//", "/*")),
    ".sass": ("SCSS", ("//",)),
    ".less": ("Less", ("//", "/*")),
    ".md": ("Markdown", ()),
    ".mdx": ("Markdown", ()),
    ".rst": ("reStructuredText", ()),
    ".adoc": ("AsciiDoc", ()),
    ".txt": ("Text", ()),
    ".csv": ("CSV", ()),
    ".gradle": ("Gradle", ("//",)),
    ".cmake": ("CMake", ("#",)),
    ".mk": ("Make", ("#",)),
    ".dockerfile": ("Dockerfile", ("#",)),
}

FILENAME_LANGUAGES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "dockerfile": ("Dockerfile", ("#",)),
    "containerfile": ("Dockerfile", ("#",)),
    "makefile": ("Make", ("#",)),
    "justfile": ("Make", ("#",)),
    "rakefile": ("Ruby", ("#",)),
    "gemfile": ("Ruby", ("#",)),
    "brewfile": ("Ruby", ("#",)),
    "procfile": ("Config", ("#",)),
    "vagrantfile": ("Ruby", ("#",)),
    "jenkinsfile": ("Groovy", ("//",)),
    "cmakelists.txt": ("CMake", ("#",)),
    "go.mod": ("Go", ("//",)),
    "go.sum": ("Go", ()),
}

CODE_LANGUAGES = {
    "Python", "JavaScript", "TypeScript", "Vue", "Svelte", "Go", "Rust", "Java", "Kotlin",
    "Scala", "Groovy", "C#", "F#", "VB.NET", "Ruby", "PHP", "C", "C++", "Objective-C",
    "Objective-C++", "Swift", "Dart", "Elixir", "Erlang", "Haskell", "Clojure", "Lua",
    "Perl", "R", "Julia", "Shell", "PowerShell",
}

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode-test", "node_modules", "bower_components",
    "vendor", "venv", ".venv", "env310", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".nox", "dist", "build", "out", "target",
    ".next", ".nuxt", ".svelte-kit", ".output", ".parcel-cache", ".turbo", ".cache",
    "coverage", "htmlcov", ".terraform", ".serverless", "Pods", "DerivedData", "obj",
    ".gradle", ".m2", ".dart_tool", "site-packages", ".yarn", ".pnpm-store",
    "repograph-out", ".repograph",
}

# Directories we do not descend into but still record as "vendored" evidence.
VENDOR_DIRS = {"node_modules", "vendor", "third_party", "Pods", "site-packages"}

DEFAULT_IGNORE_GLOBS = (
    "*.min.js", "*.min.css", "*.map", "*.log", "*.pyc", "*.pyo", "*.class",
    "*.o", "*.so", "*.dylib", "*.dll", "*.exe", "*.jar", "*.war", "*.zip", "*.tar",
    "*.tar.gz", "*.tgz", "*.rar", "*.7z", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp",
    "*.ico", "*.svg", "*.webp", "*.mp4", "*.mp3", "*.wav", "*.avi", "*.mov", "*.pdf",
    "*.woff", "*.woff2", "*.ttf", "*.eot", "*.otf", "*.db", "*.sqlite", "*.sqlite3",
    "*.bin", "*.dat", "*.pkl", "*.h5", "*.parquet", "*.avro", "*.wasm", "*.node",
    "*.snap", "*.pb.go", "*_pb2.py", "*.generated.*", "*.designer.cs",
)

TEST_PATTERNS = (
    re.compile(r"(^|/)tests?/"), re.compile(r"(^|/)__tests__/"), re.compile(r"(^|/)spec/"),
    re.compile(r"(^|/)e2e/"), re.compile(r"_test\.[a-z]+$"), re.compile(r"^test_[^/]*\.py$"),
    re.compile(r"[./]test_[^/]*\.py$"), re.compile(r"\.(test|spec)\.[jt]sx?$"),
    re.compile(r"Test[s]?\.(java|kt|cs|scala)$"), re.compile(r"_spec\.rb$"),
)

INFRA_PATTERNS = (
    re.compile(r"(^|/)(deploy|deployment|k8s|kubernetes|helm|charts|manifests|infra|infrastructure|terraform|ansible|pulumi|cloudformation)/"),
    re.compile(r"docker-compose[.\w-]*\.ya?ml$"),
    re.compile(r"(^|/)Dockerfile[.\w-]*$"),
    re.compile(r"\.tf$"), re.compile(r"\.bicep$"),
    re.compile(r"(^|/)\.github/workflows/"),
    re.compile(r"(^|/)\.gitlab-ci\.ya?ml$"),
    re.compile(r"(^|/)serverless\.ya?ml$"),
    re.compile(r"(^|/)skaffold\.ya?ml$"),
)

BUILD_FILES = {
    "package.json", "pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile",
    "go.mod", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "gemfile", "composer.json", "makefile", "cmakelists.txt", "build.sbt",
    "mix.exs", "pubspec.yaml", "deno.json", "bun.lockb", "rush.json",
}

DOC_LANGUAGES = {"Markdown", "reStructuredText", "AsciiDoc", "Text"}
CONFIG_LANGUAGES = {"YAML", "JSON", "TOML", "INI", "XML", "Dotenv", "Config"}


@dataclass
class ScanFile:
    """One file on disk, plus everything the walker could tell about it."""

    path: str          # absolute
    rel: str           # repo-relative, forward slashes
    language: str
    comment_prefixes: Tuple[str, ...]
    kind: str
    size: int
    text: Optional[str] = None

    @property
    def is_code(self) -> bool:
        return self.language in CODE_LANGUAGES

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def ext(self) -> str:
        name = self.name
        return name[name.rfind(".") :].lower() if "." in name else ""


@dataclass
class WalkStats:
    total_seen: int = 0
    skipped_ignored: int = 0
    skipped_binary: int = 0
    skipped_large: int = 0
    vendored: int = 0
    vendor_dirs: List[str] = field(default_factory=list)


class GitIgnore:
    """A pragmatic .gitignore matcher covering the patterns repos actually use."""

    def __init__(self) -> None:
        self.rules: List[Tuple[str, bool, bool, str]] = []  # (pattern, negated, dir_only, base)

    def add_file(self, path: str, base: str) -> None:
        text = read_text(path, limit=200_000)
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            self.rules.append((line, negated, dir_only, base))

    def match(self, rel: str, is_dir: bool) -> bool:
        ignored = False
        for pattern, negated, dir_only, base in self.rules:
            if base and not (rel == base or rel.startswith(base + "/")):
                continue
            target = rel[len(base) + 1 :] if base else rel
            if dir_only and not is_dir and "/" not in pattern:
                # a dir-only rule still hides files below that dir
                if not any(seg == pattern for seg in target.split("/")[:-1]):
                    continue
            if self._match_one(pattern, target):
                ignored = not negated
        return ignored

    @staticmethod
    def _match_one(pattern: str, target: str) -> bool:
        if pattern.startswith("/"):
            pattern = pattern[1:]
            return fnmatch.fnmatch(target, pattern) or target.startswith(pattern.rstrip("*") + "/")
        if "/" in pattern:
            return fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(target, pattern + "/*")
        segments = target.split("/")
        return any(fnmatch.fnmatch(seg, pattern) for seg in segments)


def detect_language(name: str, rel: str) -> Tuple[str, Tuple[str, ...]]:
    lower = name.lower()
    if lower in FILENAME_LANGUAGES:
        return FILENAME_LANGUAGES[lower]
    if lower.startswith("dockerfile"):
        return FILENAME_LANGUAGES["dockerfile"]
    if lower.startswith(".env"):
        return ("Dotenv", ("#",))
    ext = lower[lower.rfind(".") :] if "." in lower else ""
    if ext in LANGUAGES:
        return LANGUAGES[ext]
    return ("Unknown", ("#", "//"))


def classify(rel: str, name: str, language: str) -> str:
    lower_rel = rel.lower()
    if any(p.search(rel) for p in TEST_PATTERNS):
        return "test"
    if any(p.search(rel) for p in INFRA_PATTERNS):
        return "infra"
    if name.lower() in BUILD_FILES or lower_rel.endswith((".gradle", ".cmake", "makefile")):
        return "build"
    if language in DOC_LANGUAGES:
        return "docs"
    if language in CONFIG_LANGUAGES:
        return "config"
    if language in CODE_LANGUAGES:
        return "source"
    if language in ("SQL", "Protobuf", "GraphQL"):
        return "source"
    if language in ("Terraform", "HCL", "Bicep", "Dockerfile"):
        return "infra"
    return "data"


class Walker:
    def __init__(
        self,
        root: str,
        extra_ignores: Sequence[str] = (),
        max_file_size: int = 2_000_000,
        follow_symlinks: bool = False,
        use_gitignore: bool = True,
        include_globs: Sequence[str] = (),
    ) -> None:
        self.root = os.path.abspath(root)
        self.extra_ignores = tuple(extra_ignores)
        self.max_file_size = max_file_size
        self.follow_symlinks = follow_symlinks
        self.use_gitignore = use_gitignore
        self.include_globs = tuple(include_globs)
        self.stats = WalkStats()

    def _ignored_glob(self, rel: str, name: str) -> bool:
        for pattern in DEFAULT_IGNORE_GLOBS + self.extra_ignores:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                return True
        return False

    @staticmethod
    def _is_build_output_bin(dirpath: str, siblings: Sequence[str]) -> bool:
        """``bin/`` is build output for .NET/Java, but real scripts elsewhere."""
        return any(s.lower().endswith((".csproj", ".fsproj", ".vbproj", ".sln")) for s in siblings) or os.path.isdir(
            os.path.join(dirpath, "obj")
        )

    def walk(self) -> List[ScanFile]:
        files: List[ScanFile] = []
        gitignore = GitIgnore()
        if self.use_gitignore:
            root_ignore = os.path.join(self.root, ".gitignore")
            if os.path.exists(root_ignore):
                gitignore.add_file(root_ignore, "")

        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=self.follow_symlinks):
            rel_dir = rel_path(self.root, dirpath)
            rel_dir = "" if rel_dir == "." else rel_dir

            if self.use_gitignore and ".gitignore" in filenames and rel_dir:
                gitignore.add_file(os.path.join(dirpath, ".gitignore"), rel_dir)

            keep_dirs = []
            for d in sorted(dirnames):
                child_rel = f"{rel_dir}/{d}" if rel_dir else d
                if d in VENDOR_DIRS:
                    self.stats.vendored += 1
                    self.stats.vendor_dirs.append(child_rel)
                    continue
                if d == "bin" and self._is_build_output_bin(dirpath, filenames):
                    self.stats.skipped_ignored += 1
                    continue
                if d in DEFAULT_IGNORE_DIRS or d.startswith(".") and d not in (".github", ".gitlab", ".circleci"):
                    self.stats.skipped_ignored += 1
                    continue
                if gitignore.match(child_rel, True):
                    self.stats.skipped_ignored += 1
                    continue
                keep_dirs.append(d)
            dirnames[:] = keep_dirs

            for fname in sorted(filenames):
                self.stats.total_seen += 1
                rel = f"{rel_dir}/{fname}" if rel_dir else fname
                if self.include_globs and not any(
                    fnmatch.fnmatch(rel, g) for g in self.include_globs
                ):
                    continue
                if self._ignored_glob(rel, fname):
                    self.stats.skipped_ignored += 1
                    continue
                if self.use_gitignore and gitignore.match(rel, False):
                    self.stats.skipped_ignored += 1
                    continue
                abs_path = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    continue
                if size > self.max_file_size:
                    self.stats.skipped_large += 1
                    continue
                language, prefixes = detect_language(fname, rel)
                kind = classify(rel, fname, language)
                files.append(
                    ScanFile(
                        path=abs_path,
                        rel=rel,
                        language=language,
                        comment_prefixes=prefixes,
                        kind=kind,
                        size=size,
                    )
                )
        files.sort(key=lambda f: f.rel)
        return files


def load_text(sf: ScanFile) -> str:
    if sf.text is None:
        sf.text = read_text(sf.path)
    return sf.text
