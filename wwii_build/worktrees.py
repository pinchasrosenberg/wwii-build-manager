"""Git worktree manager.

* Never touches the user's current branch, index or working tree.
* ``baseline`` snapshots the (largely untracked) game plan paths into a dedicated
  integration branch through a *temporary index* (read-tree HEAD + add paths +
  write-tree + commit-tree + create-only update-ref).
* Each execution task gets ``.worktrees/<task-slug>/`` on branch ``wwii-build/task/<slug>``
  forked from the integration branch; sparse checkout keeps worktrees small.
* Accepted work is merged (--no-ff) into the integration branch inside its own
  worktree; conflicts are aborted and sent to review. No force/reset/clean ever.
"""
from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .generated import EXCLUDE_LINES, EXCLUDE_PATHSPECS, is_generated

IDENT = ["-c", "user.name=WWII Build Manager", "-c", "user.email=wwii-build@localhost", "-c", "commit.gpgsign=false"]
ZERO = "0" * 40
# Merges run via asyncio.to_thread; concurrent merges into the one integration
# worktree race on its index.lock and the loser looks like a merge conflict.
_INTEGRATION_LOCK = threading.Lock()
DEFAULT_SPARSE = ["/AGENTS.md", "/README.md", "/context/", "/docs/game/", "/game/", "/schemas/", "/skills/",
                  "/capabilities/", "/tools/build_manager/"]


class GitError(Exception):
    pass


def slug(task_id: str) -> str:
    return task_id.replace("/", "__").replace(" ", "_")


@dataclass
class GitResult:
    rc: int
    out: str
    err: str


class WorktreeManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.repo = cfg.repo
        self.branch = cfg.section("baseline").get("branch", "wwii-build/integration")
        self.root = cfg.worktrees_dir
        self.integration_dir = self.root / "_integration"
        wt = cfg.data.get("worktree", {})
        # Opt-in: sparse checkout in a linked worktree makes git set
        # extensions.worktreeConfig=true in the repo's shared config.
        self.sparse = wt.get("sparse", False)
        self.sparse_paths = wt.get("sparse_paths", DEFAULT_SPARSE)

    # --- plumbing -----------------------------------------------------------
    def git(self, *args: str, cwd: Path | None = None, env: dict | None = None, check: bool = True) -> GitResult:
        e = dict(os.environ)
        e.pop("GIT_INDEX_FILE", None)
        e.update(env or {})
        e["GIT_TERMINAL_PROMPT"] = "0"
        p = subprocess.run(["git", *args], cwd=str(cwd or self.repo), env=e, capture_output=True, text=True)
        r = GitResult(p.returncode, p.stdout, p.stderr)
        if check and p.returncode != 0:
            raise GitError(f"git {' '.join(args[:4])}... failed: {p.stderr.strip()[:500]}")
        return r

    def common_dir(self) -> Path:
        d = self.git("rev-parse", "--git-common-dir").out.strip()
        p = Path(d)
        return p if p.is_absolute() else (self.repo / p).resolve()

    def ensure_excludes(self) -> None:
        f = self.common_dir() / "info" / "exclude"
        f.parent.mkdir(parents=True, exist_ok=True)
        text = f.read_text() if f.exists() else ""
        have = text.splitlines()
        blocks = []
        state = [ln for ln in ("/.wwii-build/", "/.worktrees/") if ln not in have]
        if state:
            blocks.append("# WWII Build Manager local state\n" + "\n".join(state))
        gen = [ln for ln in EXCLUDE_LINES if ln not in have]
        if gen:   # shared by every worktree; only known generated/cache artifacts
            blocks.append("# WWII Build Manager: generated artifacts (never task-owned)\n" + "\n".join(gen))
        if blocks:
            with open(f, "a") as fh:
                fh.write(("" if text.endswith("\n") or not text else "\n") + "\n".join(blocks) + "\n")

    def rev(self, ref: str, cwd: Path | None = None) -> str | None:
        r = self.git("rev-parse", "--verify", "--quiet", ref + "^{commit}", cwd=cwd, check=False)
        return r.out.strip() or None

    # --- baseline -----------------------------------------------------------
    def baseline_exists(self) -> bool:
        return self.rev(f"refs/heads/{self.branch}") is not None

    def create_baseline(self, include_paths: list[str] | None = None) -> dict:
        if self.baseline_exists():
            return {"created": False, "branch": self.branch, "commit": self.rev(f"refs/heads/{self.branch}")}
        include = [p for p in (include_paths or self.cfg.section("baseline")["include_paths"])
                   if (self.repo / p).exists()]
        head = self.rev("HEAD")
        tmp_index = self.cfg.state_dir / "tmp" / "baseline.index"
        tmp_index.parent.mkdir(parents=True, exist_ok=True)
        if tmp_index.exists():
            tmp_index.unlink()
        env = {"GIT_INDEX_FILE": str(tmp_index)}
        self.git("read-tree", head, env=env)
        self.git("add", "-A", "--", *include, env=env)
        tree = self.git("write-tree", env=env).out.strip()
        files = self.git("diff", "--cached", "--name-only", head, env=env).out.split("\n")
        msg = ("wwii-build: baseline snapshot of the game plan\n\n"
               f"Snapshot of {', '.join(include)} from the working tree on top of {head[:12]}.\n"
               "Created with a temporary index; the user's branch, index and working tree were not touched.")
        commit = self.git(*IDENT, "commit-tree", tree, "-p", head, "-m", msg).out.strip()
        self.git("update-ref", f"refs/heads/{self.branch}", commit, ZERO)   # create-only
        tmp_index.unlink(missing_ok=True)
        return {"created": True, "branch": self.branch, "commit": commit, "parent": head,
                "files": len([f for f in files if f]), "paths": include}

    # --- worktrees ------------------------------------------------------------
    def _is_worktree(self, path: Path) -> bool:
        return (path / ".git").exists() and self.git("rev-parse", "--show-toplevel", cwd=path, check=False).rc == 0

    def _add_worktree(self, path: Path, branch: str, new_from: str | None, sparse: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        args = ["worktree", "add"]
        if sparse:
            args.append("--no-checkout")
        if new_from:
            args += ["-b", branch, str(path), new_from]
        else:
            args += [str(path), branch]
        self.git(*args)
        if sparse:
            self.git("sparse-checkout", "set", "--no-cone", *self.sparse_paths, cwd=path)
            self.git("checkout", branch, cwd=path)

    def ensure_integration(self) -> Path:
        if not self.baseline_exists():
            raise GitError(f"integration branch {self.branch} missing; run `wwii-build baseline` first")
        if not self._is_worktree(self.integration_dir):
            self._add_worktree(self.integration_dir, self.branch, None, self.sparse)
        return self.integration_dir

    def task_branch(self, task_id: str) -> str:
        return f"wwii-build/task/{slug(task_id)}"

    def task_path(self, task_id: str) -> Path:
        return self.root / slug(task_id)

    def ensure_task(self, task_id: str, full_checkout: bool = False) -> tuple[Path, str, str]:
        """Returns (worktree path, branch, base commit). Reuses an existing worktree (keeps prior diff)."""
        path, br = self.task_path(task_id), self.task_branch(task_id)
        if not self._is_worktree(path):
            if self.rev(f"refs/heads/{br}"):
                self._add_worktree(path, br, None, self.sparse and not full_checkout)
            else:
                self._add_worktree(path, br, self.branch, self.sparse and not full_checkout)
        base = self.git("merge-base", br, self.branch).out.strip()
        return path, br, base

    def ensure_system_task(self, task_id: str) -> tuple[Path, str, str, dict[str, str]]:
        """Create an isolated repair checkout from an exact active-manager snapshot.

        The manager is allowed to be untracked on the user's branch, so the normal
        integration baseline may not contain it.  This seed commit exists only on
        the task branch and never mutates the active checkout.
        """
        from .system_repair import mirror_active_manager
        path, branch, _ = self.ensure_task(task_id, full_checkout=True)
        manifest = mirror_active_manager(self.repo, path)
        self.commit_all(path, f"wwii-build: snapshot active Task Manager for {task_id}")
        return path, branch, self.head(path), manifest

    def update_from_integration(self, path: Path) -> tuple[bool, str]:
        """Bring newly integrated dependency work into a task worktree (merge, never rebase)."""
        r = self.git(*IDENT, "merge", "--no-edit", self.branch, cwd=path, check=False)
        if r.rc != 0:
            self.git("merge", "--abort", cwd=path, check=False)
            return False, r.out + r.err
        return True, ""

    # --- results ------------------------------------------------------------
    def head(self, path: Path) -> str:
        return self.git("rev-parse", "HEAD", cwd=path).out.strip()

    def tracked_generated(self, path: Path) -> list[str]:
        out = self.git("ls-files", "-z", cwd=path).out
        return [p for p in out.split("\0") if p and is_generated(p)]

    def untrack_generated(self, path: Path) -> list[str]:
        """Remove generated artifacts from the index (files stay on disk). Returns the paths."""
        gen = self.tracked_generated(path)
        for i in range(0, len(gen), 200):
            self.git("rm", "--cached", "-q", "--", *gen[i:i + 200], cwd=path)
        return gen

    def commit_all(self, path: Path, message: str) -> str | None:
        self.untrack_generated(path)
        self.git("add", "-A", "--", ".", *EXCLUDE_PATHSPECS, cwd=path)
        if self.git("diff", "--cached", "--quiet", cwd=path, check=False).rc == 0:
            return None
        self.git(*IDENT, "commit", "--no-verify", "-q", "-m", message, cwd=path)
        return self.head(path)

    def cleanup_generated(self, path: Path) -> tuple[list[str], str | None]:
        """Deterministic cleanup: commit the removal of generated artifacts already in the branch."""
        gen = self.untrack_generated(path)
        if not gen or self.git("diff", "--cached", "--quiet", cwd=path, check=False).rc == 0:
            return [], None
        self.git(*IDENT, "commit", "--no-verify", "-q", "-m",
                 f"wwii-build: untrack {len(gen)} generated artifacts (manager cleanup, no LLM)", cwd=path)
        return gen, self.head(path)

    def changed_files(self, path: Path, base: str) -> list[str]:
        out = self.git("diff", "--name-only", f"{base}..HEAD", cwd=path).out
        return [ln for ln in out.splitlines() if ln and not is_generated(ln)]

    def changed_files_raw(self, path: Path, base: str) -> list[str]:
        out = self.git("diff", "--name-only", f"{base}..HEAD", cwd=path).out
        return [ln for ln in out.splitlines() if ln]

    def diff(self, path: Path, base: str, max_bytes: int | None = None) -> str:
        d = self.git("diff", "--stat", "--patch", f"{base}..HEAD", "--", ".", *EXCLUDE_PATHSPECS, cwd=path).out
        if max_bytes and len(d.encode()) > max_bytes:
            d = d.encode()[:max_bytes].decode("utf-8", "ignore") + "\n... [truncated]"
        return d

    def diff_check(self, path: Path, base: str) -> tuple[bool, str]:
        r = self.git("diff", "--check", f"{base}..HEAD", "--", ".", *EXCLUDE_PATHSPECS, cwd=path, check=False)
        return r.rc == 0, (r.out + r.err)[-3000:]

    def is_ancestor(self, a: str, b: str) -> bool:
        return self.git("merge-base", "--is-ancestor", a, b, check=False).rc == 0

    def merge_to_integration(self, task_id: str) -> tuple[bool, str, str | None]:
        with _INTEGRATION_LOCK:
            return self._merge_to_integration(task_id)

    def _merge_to_integration(self, task_id: str) -> tuple[bool, str, str | None]:
        integ = self.ensure_integration()
        br = self.task_branch(task_id)
        r = self.git(*IDENT, "merge", "--no-ff", "--no-edit", "-m", f"wwii-build: integrate {task_id}", br,
                     cwd=integ, check=False)
        if r.rc != 0:
            self.git("merge", "--abort", cwd=integ, check=False)
            return False, (r.out + r.err)[-3000:], None
        return True, r.out[-1000:], self.head(integ)

    def remove_clean_worktree(self, task_id: str) -> tuple[bool, str]:
        """Remove a PASSED task's worktree only if clean. The branch (all work) is kept."""
        path = self.task_path(task_id)
        if not self._is_worktree(path):
            return False, "no worktree"
        if self.git("status", "--porcelain", cwd=path).out.strip():
            return False, "worktree has uncommitted changes; left in place"
        r = self.git("worktree", "remove", str(path), check=False)   # never --force
        return r.rc == 0, (r.out + r.err).strip()

    def worktree_list(self) -> list[str]:
        out = self.git("worktree", "list", "--porcelain", check=False).out
        return [ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("worktree ")]
