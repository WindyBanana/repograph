"""Repository history: authorship, age and change hotspots."""

from __future__ import annotations

import os
from collections import Counter
from typing import Dict, List

from .model import GitInfo
from .util import run_git


def collect(root: str, max_commits: int = 4000, hotspot_limit: int = 25) -> GitInfo:
    info = GitInfo()
    if not os.path.isdir(os.path.join(root, ".git")) and run_git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return info
    info.is_repo = True
    info.remote = run_git(root, "config", "--get", "remote.origin.url")
    info.branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    info.head = run_git(root, "rev-parse", "HEAD")
    count = run_git(root, "rev-list", "--count", "HEAD")
    info.commits = int(count) if count.isdigit() else 0

    log = run_git(root, "log", f"-{max_commits}", "--format=%aN\t%aI", timeout=60)
    authors: Counter = Counter()
    dates: List[str] = []
    for line in log.splitlines():
        name, _, date = line.partition("\t")
        if name:
            authors[name.strip()] += 1
        if date:
            dates.append(date.strip())
    info.contributors = len(authors)
    info.top_authors = [{"name": name, "commits": commits} for name, commits in authors.most_common(10)]
    if dates:
        info.last_commit = dates[0][:10]
        info.first_commit = dates[-1][:10]

    changes: Counter = Counter()
    name_log = run_git(root, "log", "-1500", "--name-only", "--pretty=format:", timeout=90)
    for line in name_log.splitlines():
        path = line.strip()
        if path and not path.startswith(("Binary", "commit ")):
            changes[path] += 1
    info.hotspots = [
        {"file": path, "changes": changes_count}
        for path, changes_count in changes.most_common(hotspot_limit)
    ]
    return info


def churn_by_dir(hotspots: List[Dict[str, object]], depth: int = 2) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for entry in hotspots:
        path = str(entry.get("file", ""))
        parts = path.split("/")
        key = "/".join(parts[:depth]) if len(parts) > depth else (parts[0] if parts else "")
        out[key] = out.get(key, 0) + int(entry.get("changes", 0) or 0)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
