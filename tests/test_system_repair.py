from __future__ import annotations

from pathlib import Path

from helpers import TmpTestCase, git
from wwii_build.activation import activation_id, record_activation, restart_decision
from wwii_build.db import DB
from wwii_build.system_repair import (SystemRepairError, activate_release, active_manifest,
                                      stage_release)


class SystemRepairActivation(TmpTestCase):
    def test_activation_marker_is_monotonic_and_drives_restart_decision(self):
        db = DB(self.tmp / "synthetic-state.sqlite3")
        self.addCleanup(db.close)
        self.assertEqual(activation_id(db), 0)  # migration compatibility: an existing database has no marker
        first = record_activation(db)
        second = record_activation(db)
        self.assertEqual((first, second, activation_id(db)), (1, 2, 2))
        self.assertEqual(restart_decision(second, second), "unchanged")
        self.assertEqual(restart_decision(first, second, busy=True), "wait")
        self.assertEqual(restart_decision(first, second), "restart")

    def _candidate(self, active: Path, name: str = "candidate") -> tuple[Path, str, str]:
        worktree = self.tmp / name
        worktree.mkdir()
        git(worktree, "init", "-q", "-b", "main")
        target = worktree / "tools/build_manager/wwii_build/example.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n")
        git(worktree, "add", ".")
        git(worktree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        base = git(worktree, "rev-parse", "HEAD").strip()
        target.write_text("VALUE = 2\n")
        git(worktree, "add", ".")
        git(worktree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "repair")
        return worktree, base, git(worktree, "rev-parse", "HEAD").strip()

    def test_stage_activate_and_keep_rollback_copy(self):
        active = self.tmp / "active"
        target = active / "tools/build_manager/wwii_build/example.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n")
        expected = active_manifest(active)
        candidate, base, head = self._candidate(active)
        staged = stage_release(active, self.tmp / "state", candidate, "SYSTEM/1", base, head, expected)
        self.assertEqual(staged.changed_files, ["tools/build_manager/wwii_build/example.py"])
        activate_release(active, staged)
        self.assertEqual(target.read_text(), "VALUE = 2\n")
        self.assertEqual((staged.path / "backup/tools/build_manager/wwii_build/example.py").read_text(),
                         "VALUE = 1\n")

    def test_drift_blocks_activation_before_active_files_change(self):
        active = self.tmp / "active"
        target = active / "tools/build_manager/wwii_build/example.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n")
        expected = active_manifest(active)
        candidate, base, head = self._candidate(active)
        target.write_text("VALUE = 99\n")
        with self.assertRaises(SystemRepairError):
            stage_release(active, self.tmp / "state", candidate, "SYSTEM/2", base, head, expected)
        self.assertEqual(target.read_text(), "VALUE = 99\n")
