"""Central generated-artifact policy.

Only *known* generated/cache artifacts are listed here. They never count as task-owned
changes: excluded from changed-file discovery, ownership validation, commits and
artifact collection. Anything not matching stays visible — nothing else is ignored.
"""
from __future__ import annotations

import fnmatch

# (dir names anywhere in the path, file-name globs)
GENERATED_DIRS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
GENERATED_FILES = ("*.pyc", "*.pyo", ".coverage", ".DS_Store")

# gitignore-style lines for .git/info/exclude (shared by every worktree).
EXCLUDE_LINES = ["__pycache__/", "*.pyc", "*.pyo", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
                 ".coverage", ".DS_Store"]

# git pathspecs that drop these from `git add` / `git diff`.
EXCLUDE_PATHSPECS = [f":(exclude,glob)**/{d}/**" for d in GENERATED_DIRS] + \
                    [f":(exclude,glob)**/{f}" for f in GENERATED_FILES]


def is_generated(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if any(p in GENERATED_DIRS for p in parts[:-1]):
        return True
    return any(fnmatch.fnmatchcase(parts[-1], g) for g in GENERATED_FILES)


def split(paths: list[str]) -> tuple[list[str], list[str]]:
    """(real, generated)"""
    real, gen = [], []
    for p in paths:
        (gen if is_generated(p) else real).append(p)
    return real, gen
