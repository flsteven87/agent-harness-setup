from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import finalize_local_delivery as finalizer


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return completed.stdout.strip()


class FinalizeLocalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.task = self.root / "task"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.com")
        (self.repo / "base.txt").write_text("base\n")
        git(self.repo, "add", "base.txt")
        git(self.repo, "commit", "-m", "base")
        git(self.repo, "branch", "feature/test")
        git(self.repo, "worktree", "add", str(self.task), "feature/test")
        (self.task / "feature.txt").write_text("feature\n")
        git(self.task, "add", "feature.txt")
        git(self.task, "commit", "-m", "feature")
        self.feature_head = git(self.task, "rev-parse", "HEAD")

    def build_plan(self, **overrides):
        values = {
            "repo": self.repo,
            "worktree_path": self.task,
            "branch": "feature/test",
            "expected_head_revision": self.feature_head,
            "default_branch": "main",
            "integrated_ref": "main",
            "squash_commit_revision": None,
        }
        values.update(overrides)
        return finalizer.build_plan(**values)

    def test_preview_and_execute_merged_linked_worktree(self):
        git(self.repo, "remote", "add", "origin", "https://example.invalid/repo.git")
        git(
            self.repo,
            "update-ref",
            "refs/remotes/origin/feature/test",
            self.feature_head,
        )
        git(
            self.repo,
            "branch",
            "--set-upstream-to=origin/feature/test",
            "feature/test",
        )
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/feature/test")
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")

        plan = self.build_plan()

        self.assertFalse(plan.force_delete)
        self.assertIn("ancestor", plan.proof)
        self.assertTrue(self.task.exists())
        finalizer.execute_plan(plan)
        self.assertFalse(self.task.exists())
        branches = git(self.repo, "branch", "--format=%(refname:short)").splitlines()
        self.assertNotIn("feature/test", branches)

    def integrate_on_remote_only(self) -> tuple[str, str]:
        """Merge the feature on a remote-tracking ref while local main stays behind."""
        base_head = git(self.repo, "rev-parse", "main")
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "remote merge")
        integrated_head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", integrated_head)
        git(self.repo, "reset", "--hard", base_head)
        return base_head, integrated_head

    def test_linked_worktree_fast_forwards_checked_out_default_branch(self):
        base_head, integrated_head = self.integrate_on_remote_only()

        plan = self.build_plan(integrated_ref="origin/main")

        self.assertEqual(plan.default_sync.status, "fast_forward")
        self.assertEqual(plan.default_sync.worktree, self.repo.resolve())
        self.assertIn("merge --ff-only", plan.actions[0])
        sync = finalizer.execute_plan(plan)
        self.assertEqual(sync.status, "fast_forwarded")
        self.assertEqual((sync.before, sync.after), (base_head, integrated_head))
        self.assertEqual(git(self.repo, "rev-parse", "main"), integrated_head)
        self.assertFalse(self.task.exists())
        report = finalizer.render(plan, executed=True, default_sync=sync)
        self.assertEqual(report["default_branch_sync"], sync.as_report())

    def test_unrelated_dirty_file_in_primary_keeps_fast_forward(self):
        _, integrated_head = self.integrate_on_remote_only()
        (self.repo / "notes.md").write_text("in progress\n")

        sync = finalizer.execute_plan(self.build_plan(integrated_ref="origin/main"))

        self.assertEqual(sync.status, "fast_forwarded")
        self.assertEqual(git(self.repo, "rev-parse", "main"), integrated_head)
        self.assertEqual((self.repo / "notes.md").read_text(), "in progress\n")

    def test_colliding_dirty_file_blocks_sync_and_cleanup_continues(self):
        base_head, _ = self.integrate_on_remote_only()
        (self.repo / "feature.txt").write_text("local draft\n")

        sync = finalizer.execute_plan(self.build_plan(integrated_ref="origin/main"))

        self.assertEqual(sync.status, "blocked")
        self.assertIn("feature.txt", sync.detail)
        self.assertEqual(git(self.repo, "rev-parse", "main"), base_head)
        self.assertEqual((self.repo / "feature.txt").read_text(), "local draft\n")
        self.assertFalse(self.task.exists())
        branches = git(self.repo, "branch", "--format=%(refname:short)").splitlines()
        self.assertNotIn("feature/test", branches)

    def test_unchecked_out_default_branch_moves_by_update_ref(self):
        _, integrated_head = self.integrate_on_remote_only()
        git(self.repo, "switch", "-c", "other")
        (self.repo / "other.txt").write_text("other\n")

        plan = self.build_plan(integrated_ref="origin/main")

        self.assertIsNone(plan.default_sync.worktree)
        self.assertIn("update-ref refs/heads/main", plan.actions[0])
        sync = finalizer.execute_plan(plan)
        self.assertEqual(sync.status, "fast_forwarded")
        self.assertEqual(git(self.repo, "rev-parse", "main"), integrated_head)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "other")

    def test_diverged_default_branch_replays_local_commits_keeping_dirty_files(self):
        _, integrated_head = self.integrate_on_remote_only()
        (self.repo / "local.txt").write_text("local\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-m", "local only")
        (self.repo / "notes.md").write_text("in progress\n")

        plan = self.build_plan(integrated_ref="origin/main")

        self.assertEqual(plan.default_sync.status, "rebase")
        self.assertIn("-C main", "\n".join(plan.actions))
        sync = finalizer.execute_plan(plan)
        self.assertEqual(sync.status, "rebased")
        self.assertEqual(git(self.repo, "rev-parse", "main~1"), integrated_head)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s", "main"), "local only")
        self.assertEqual((self.repo / "notes.md").read_text(), "in progress\n")
        self.assertFalse(self.task.exists())

    def test_refuses_dirty_worktree(self):
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")
        (self.task / "dirty.txt").write_text("dirty\n")

        with self.assertRaisesRegex(finalizer.SafetyError, "worktree is dirty"):
            self.build_plan()

    def test_refuses_branch_that_moved_after_recorded_head(self):
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")
        (self.task / "later.txt").write_text("later\n")
        git(self.task, "add", "later.txt")
        git(self.task, "commit", "-m", "later")

        with self.assertRaisesRegex(finalizer.SafetyError, "delivery branch moved"):
            self.build_plan()

    def test_accepts_matching_squash_commit_and_force_deletes(self):
        git(self.repo, "merge", "--squash", "feature/test")
        git(self.repo, "commit", "-m", "squash feature")
        squash_commit = git(self.repo, "rev-parse", "HEAD")

        plan = self.build_plan(squash_commit_revision=squash_commit)

        self.assertTrue(plan.force_delete)
        self.assertIn(squash_commit, plan.proof)
        finalizer.execute_plan(plan)
        branches = git(self.repo, "branch", "--format=%(refname:short)").splitlines()
        self.assertNotIn("feature/test", branches)

    def test_preserves_linked_worktree_for_external_owner(self):
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")

        plan = self.build_plan(preserve_worktree=True)

        self.assertTrue(plan.preserve_worktree)
        self.assertNotIn("worktree remove", "\n".join(plan.actions))
        self.assertEqual(
            finalizer.render(plan, executed=False)["worktree_removal"],
            "preserved_for_external_owner",
        )
        finalizer.execute_plan(plan)
        self.assertTrue(self.task.exists())
        self.assertEqual(git(self.task, "branch", "--show-current"), "")
        branches = git(self.repo, "branch", "--format=%(refname:short)").splitlines()
        self.assertNotIn("feature/test", branches)

    def test_writes_one_durable_preview_outside_the_task_worktree(self):
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")
        plan = self.build_plan(preserve_worktree=True)
        report_path = self.root / "state" / "cleanup-preview.json"

        written = finalizer.write_report(
            report_path,
            finalizer.render(plan, executed=False),
            task_worktree=self.task,
        )

        report = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], "ship-local-finalization")
        self.assertEqual(report["mode"], "preview")
        self.assertEqual(report["worktree"], str(self.task.resolve()))
        self.assertEqual(report["control_worktree"], str(self.repo.resolve()))
        self.assertEqual(oct(written.stat().st_mode & 0o777), oct(0o600))

    def test_refuses_a_report_inside_the_task_worktree(self):
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")
        plan = self.build_plan(preserve_worktree=True)

        with self.assertRaisesRegex(finalizer.SafetyError, "survive outside"):
            finalizer.write_report(
                self.task / "cleanup-preview.json",
                finalizer.render(plan, executed=False),
                task_worktree=self.task,
            )

    def test_cli_persists_the_same_preview_it_prints(self):
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")
        report_path = self.root / "state" / "cleanup-preview.json"

        completed = subprocess.run(
            [
                sys.executable,
                str(Path(finalizer.__file__)),
                "--repo",
                str(self.repo),
                "--worktree",
                str(self.task),
                "--branch",
                "feature/test",
                "--expected-head",
                self.feature_head,
                "--default-branch",
                "main",
                "--integrated-ref",
                "main",
                "--preserve-worktree",
                "--report-path",
                str(report_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout), json.loads(report_path.read_text())
        )

    def test_refuses_preserving_primary_worktree(self):
        git(self.repo, "worktree", "remove", str(self.task))
        git(self.repo, "switch", "feature/test")
        git(self.repo, "merge", "--ff-only", self.feature_head)
        git(self.repo, "switch", "main")
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature")
        git(self.repo, "switch", "feature/test")

        with self.assertRaisesRegex(finalizer.SafetyError, "linked task worktree"):
            finalizer.build_plan(
                repo=self.repo,
                worktree_path=self.repo,
                branch="feature/test",
                expected_head_revision=self.feature_head,
                default_branch="main",
                integrated_ref="main",
                squash_commit_revision=None,
                preserve_worktree=True,
            )

    def test_refuses_unproven_squash_merge(self):
        git(self.repo, "merge", "--squash", "feature/test")
        git(self.repo, "commit", "-m", "squash feature")

        with self.assertRaisesRegex(finalizer.SafetyError, "no squash proof"):
            self.build_plan()

    def test_primary_worktree_switches_and_fast_forwards_default_branch(self):
        git(self.repo, "worktree", "remove", str(self.task))
        git(self.repo, "switch", "feature/test")
        git(self.repo, "merge", "--ff-only", self.feature_head)
        git(self.repo, "switch", "main")
        base_head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "remote merge")
        integrated_head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", integrated_head)
        git(self.repo, "reset", "--hard", base_head)
        git(self.repo, "switch", "feature/test")

        plan = finalizer.build_plan(
            repo=self.repo,
            worktree_path=self.repo,
            branch="feature/test",
            expected_head_revision=self.feature_head,
            default_branch="main",
            integrated_ref="origin/main",
            squash_commit_revision=None,
        )

        self.assertTrue(plan.task_worktree.primary)
        self.assertTrue(plan.fast_forward_default)
        self.assertEqual(
            finalizer.render(plan, executed=False)["worktree_removal"],
            "retained_primary",
        )
        finalizer.execute_plan(plan)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), integrated_head)
        branches = git(self.repo, "branch", "--format=%(refname:short)").splitlines()
        self.assertNotIn("feature/test", branches)


if __name__ == "__main__":
    unittest.main()
