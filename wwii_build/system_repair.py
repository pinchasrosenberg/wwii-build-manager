"""Staged, drift-checked activation for Task Manager self-repair tasks.

The running manager is never used as the worker checkout.  A system task starts
from an explicit snapshot of the active manager, is tested in its own worktree,
and only its accepted diff is copied back.  Activation verifies that every
target still matches the snapshot and keeps a rollback copy before replacing
anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SYSTEM_ROOTS = ("tools/build_manager/",)
_IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store"}
_IGNORED_SUFFIXES = (".pyc", ".pyo")


class SystemRepairError(RuntimeError):
    pass


def is_system_path(path: str) -> bool:
    value = str(path or "").replace("\\", "/").lstrip("./")
    return any(value == root.rstrip("/") or value.startswith(root) for root in SYSTEM_ROOTS)


def _ignored(path: Path) -> bool:
    return any(part in _IGNORED_NAMES for part in path.parts) or path.name.endswith(_IGNORED_SUFFIXES)


def _digest(path: Path) -> str | None:
    if path.is_symlink():
        return "symlink:" + os.readlink(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def active_manifest(repo: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for root in SYSTEM_ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if _ignored(path) or (not path.is_file() and not path.is_symlink()):
                continue
            rel = path.relative_to(repo).as_posix()
            digest = _digest(path)
            if digest is not None:
                manifest[rel] = digest
    return manifest


def mirror_active_manager(repo: Path, worktree: Path) -> dict[str, str]:
    """Replace the isolated checkout's manager tree with the active tree."""
    manifest = active_manifest(repo)
    for root in SYSTEM_ROOTS:
        src, dst = repo / root, worktree / root
        if dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True, ignore=lambda _d, names: [
                name for name in names if name in _IGNORED_NAMES or name.endswith(_IGNORED_SUFFIXES)
            ])
        elif src.exists() or src.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy_entry(src, dst)
    return manifest


def _copy_entry(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        dst.symlink_to(os.readlink(src))
    else:
        shutil.copy2(src, dst)


@dataclass
class StagedRelease:
    path: Path
    changed_files: list[str]
    deleted_files: list[str]


def stage_release(repo: Path, state_dir: Path, worktree: Path, task_id: str,
                  base_commit: str, candidate_commit: str, expected_manifest: dict[str, str]) -> StagedRelease:
    """Verify drift and copy the accepted payload into manager-owned state."""
    raw = subprocess_changed_files(worktree, base_commit, candidate_commit)
    changed = [path for path in raw if not _ignored(Path(path))]
    outside = [path for path in changed if not is_system_path(path)]
    if outside:
        raise SystemRepairError("system repair changed files outside the manager scope: " + ", ".join(outside[:10]))
    if not changed:
        raise SystemRepairError("system repair produced no manager changes")
    drift = []
    for rel in changed:
        if _digest(repo / rel) != expected_manifest.get(rel):
            drift.append(rel)
    if drift:
        raise SystemRepairError("active manager changed after the repair snapshot: " + ", ".join(drift[:10]))

    release = state_dir / "system_releases" / task_id.replace("/", "__") / candidate_commit[:16]
    if release.exists():
        shutil.rmtree(release)
    payload = release / "payload"
    deleted = []
    for rel in changed:
        src = worktree / rel
        if src.exists() or src.is_symlink():
            _copy_entry(src, payload / rel)
        else:
            deleted.append(rel)
    release.mkdir(parents=True, exist_ok=True)
    (release / "release.json").write_text(json.dumps({
        "task_id": task_id, "base_commit": base_commit, "candidate_commit": candidate_commit,
        "changed_files": changed, "deleted_files": deleted,
    }, ensure_ascii=False, indent=1))
    return StagedRelease(release, changed, deleted)


def subprocess_changed_files(worktree: Path, base: str, head: str) -> list[str]:
    import subprocess
    run = subprocess.run(["git", "diff", "--name-only", "-z", f"{base}..{head}"], cwd=str(worktree),
                         capture_output=True, check=False)
    if run.returncode:
        raise SystemRepairError(run.stderr.decode("utf-8", "replace")[-500:])
    return [item.decode("utf-8", "surrogateescape") for item in run.stdout.split(b"\0") if item]


def activate_release(repo: Path, staged: StagedRelease) -> None:
    """Replace files with rollback on any failure.  The old Python process may keep
    running safely; the scheduler immediately performs a graceful exec restart."""
    backup = staged.path / "backup"
    absent: list[str] = []
    processed: list[str] = []
    try:
        for rel in staged.changed_files:
            dst = repo / rel
            if dst.exists() or dst.is_symlink():
                _copy_entry(dst, backup / rel)
            else:
                absent.append(rel)
        for rel in staged.changed_files:
            dst, src = repo / rel, staged.path / "payload" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if rel in staged.deleted_files:
                if dst.is_dir() and not dst.is_symlink():
                    raise SystemRepairError(f"refusing to delete directory {rel}")
                dst.unlink(missing_ok=True)
            else:
                tmp = dst.with_name(dst.name + ".wwii-repair-new")
                tmp.unlink(missing_ok=True)
                _copy_entry(src, tmp)
                os.replace(tmp, dst)
            processed.append(rel)
    except Exception:
        for rel in reversed(processed):
            dst, old = repo / rel, backup / rel
            try:
                if old.exists() or old.is_symlink():
                    tmp = dst.with_name(dst.name + ".wwii-repair-rollback")
                    tmp.unlink(missing_ok=True)
                    _copy_entry(old, tmp)
                    os.replace(tmp, dst)
                elif rel in absent:
                    dst.unlink(missing_ok=True)
            except Exception:
                pass
        raise
