from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import sync_default_branch as syncer


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


class SyncDefaultBranchTests(unittest.TestCase):
    """The primary checkout holds a local-only commit and dirty files when upstream moves."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.com")
        for name in ("shared.txt", "draft.txt"):
            (self.repo / name).write_text(f"{name}\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def advance_upstream(self, name: str = "board.txt", text: str = "board\n") -> str:
        """Commit on a detached upstream line and publish it as origin/main."""
        git(self.repo, "switch", "--detach", "origin/main" if self.has_origin() else self.base)
        (self.repo / name).write_text(text)
        git(self.repo, "add", name)
        git(self.repo, "commit", "-m", f"upstream {name}")
        upstream = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", upstream)
        git(self.repo, "switch", "main")
        return upstream

    def has_origin(self) -> bool:
        return bool(git(self.repo, "for-each-ref", "refs/remotes/origin/main"))

    def commit_locally(self, name: str = "handoff.txt", text: str = "handoff\n") -> str:
        (self.repo / name).write_text(text)
        git(self.repo, "add", name)
        git(self.repo, "commit", "-m", f"local {name}")
        return git(self.repo, "rev-parse", "HEAD")

    def sync(self, target: str, **kwargs) -> syncer.DefaultSync:
        exact = kwargs.pop("exact", False)
        planned = syncer.plan_default_sync(
            self.repo, syncer.parse_worktrees(self.repo), "main", target, exact=exact
        )
        return syncer.sync_default_branch(self.repo, "main", target, planned, **kwargs)

    def test_diverged_branch_replays_local_commit_and_keeps_every_dirty_kind(self):
        upstream = self.advance_upstream()
        self.commit_locally()
        (self.repo / "draft.txt").write_text("unstaged edit\n")
        (self.repo / "staged.txt").write_text("staged\n")
        git(self.repo, "add", "staged.txt")
        (self.repo / "untracked.txt").write_text("untracked\n")

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "rebased")
        self.assertEqual(git(self.repo, "rev-parse", "main~1"), upstream)
        self.assertEqual((self.repo / "handoff.txt").read_text(), "handoff\n")
        self.assertEqual((self.repo / "draft.txt").read_text(), "unstaged edit\n")
        self.assertIn("A  staged.txt", git(self.repo, "status", "--short"))
        self.assertEqual((self.repo / "untracked.txt").read_text(), "untracked\n")
        self.assertEqual(len(syncer.parse_worktrees(self.repo)), 1)

    def test_dirty_file_the_upstream_changed_blocks_and_changes_nothing(self):
        upstream = self.advance_upstream("draft.txt", "upstream rewrite\n")
        local = self.commit_locally()
        (self.repo / "draft.txt").write_text("owner edit\n")

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "blocked")
        self.assertIn("draft.txt", sync.detail)
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        self.assertEqual((self.repo / "draft.txt").read_text(), "owner edit\n")

    def test_conflicting_local_commit_blocks_and_leaves_no_replay_worktree(self):
        upstream = self.advance_upstream("shared.txt", "upstream\n")
        local = self.commit_locally("shared.txt", "local\n")

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "blocked")
        self.assertIn("shared.txt", sync.detail)
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        self.assertEqual(len(syncer.parse_worktrees(self.repo)), 1)

    def test_resolved_replay_moves_the_branch(self):
        upstream = self.advance_upstream("shared.txt", "upstream\n")
        self.commit_locally("shared.txt", "local\n")
        git(self.repo, "switch", "--detach", upstream)
        (self.repo / "shared.txt").write_text("upstream and local\n")
        git(self.repo, "commit", "-am", "local shared.txt")
        resolved = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "main")

        sync = self.sync(upstream, replayed=resolved)

        self.assertEqual(sync.status, "rebased")
        self.assertEqual(git(self.repo, "rev-parse", "main"), resolved)

    def test_a_replay_missing_local_commits_is_refused(self):
        upstream = self.advance_upstream()
        local = self.commit_locally()

        with self.assertRaisesRegex(syncer.SafetyError, "exactly the local commits"):
            self.sync(upstream, replayed=upstream)
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)

    def test_a_branch_that_moves_during_the_replay_is_not_overwritten(self):
        upstream = self.advance_upstream()
        self.commit_locally()
        planned = syncer.plan_default_sync(self.repo, syncer.parse_worktrees(self.repo), "main", upstream)
        real_replay = syncer.replay_local_commits

        def replay_then_commit(*args):
            result = real_replay(*args)
            self.commit_locally("late.txt", "late\n")
            return result

        with unittest.mock.patch.object(syncer, "replay_local_commits", replay_then_commit):
            with self.assertRaisesRegex(syncer.SafetyError, "moved after the sync was planned"):
                syncer.sync_default_branch(self.repo, "main", upstream, planned)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s", "main"), "local late.txt")

    def test_an_ignored_file_the_remote_starts_tracking_blocks(self):
        upstream = self.advance_upstream("secret.env", "from upstream\n")
        (self.repo / ".git" / "info" / "exclude").write_text("secret.env\n")
        local = self.commit_locally()
        (self.repo / "secret.env").write_text("owner secret\n")

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "blocked")
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        self.assertEqual((self.repo / "secret.env").read_text(), "owner secret\n")

    def test_a_failing_hook_after_the_move_still_reports_the_move(self):
        upstream = self.advance_upstream()
        self.commit_locally()
        hook = Path(git(self.repo, "rev-parse", "--absolute-git-dir")) / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "rebased")
        self.assertEqual(git(self.repo, "rev-parse", "main~1"), upstream)
        self.assertIn("git exited 1 after moving", sync.detail)

    def test_local_branch_ahead_of_target_is_already_current(self):
        upstream = self.advance_upstream()
        git(self.repo, "merge", "--ff-only", upstream)
        local = self.commit_locally()

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "already_current")
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)

    def test_exact_ahead_branch_preserves_tip_and_aligns(self):
        local = self.commit_locally()
        sync = self.sync(self.base, exact=True)
        self.assertEqual(sync.status, "aligned")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.repo, "rev-parse", sync.preserved_ref), local)
        self.assertEqual(git(self.repo, "show", f"{sync.preserved_ref}:handoff.txt"), "handoff")
        self.assertFalse((self.repo / "handoff.txt").exists())
        self.assertEqual(self.sync(self.base, exact=True).status, "already_current")

    def test_exact_diverged_branch_preserves_merges_without_replay(self):
        local = self.commit_locally()
        upstream = self.advance_upstream()
        git(self.repo, "merge", "--no-ff", upstream, "-m", "local sync merge")
        old = git(self.repo, "rev-parse", "main")
        sync = self.sync(upstream, exact=True)
        self.assertEqual(sync.status, "aligned")
        self.assertEqual(git(self.repo, "rev-parse", "main"), upstream)
        self.assertEqual(git(self.repo, "rev-parse", sync.preserved_ref), old)
        self.assertTrue(syncer.is_ancestor(self.repo, local, sync.preserved_ref))

    def test_exact_divergence_preserves_conflicting_commit_without_replay(self):
        upstream = self.advance_upstream("shared.txt", "remote content\n")
        local = self.commit_locally("shared.txt", "local content\n")
        sync = self.sync(upstream, exact=True)
        self.assertEqual(sync.status, "aligned")
        self.assertEqual(git(self.repo, "rev-parse", "main"), upstream)
        self.assertEqual(git(self.repo, "show", f"{sync.preserved_ref}:shared.txt"), "local content")
        self.assertEqual(git(self.repo, "rev-parse", sync.preserved_ref), local)
        self.assertEqual((self.repo / "shared.txt").read_text(), "remote content\n")

    def test_exact_alignment_blocks_in_progress_operation(self):
        local = self.commit_locally()
        (self.repo / ".git" / "MERGE_HEAD").write_text(f"{self.base}\n")
        sync = self.sync(self.base, exact=True)
        self.assertEqual(sync.status, "blocked")
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        self.assertFalse(git(self.repo, "for-each-ref", "refs/heads/retained/"))

    def test_exact_alignment_keeps_unrelated_dirty_files(self):
        self.commit_locally()
        (self.repo / "draft.txt").write_text("owner edit\n")
        (self.repo / "staged.txt").write_text("staged\n")
        git(self.repo, "add", "staged.txt")
        (self.repo / "untracked.txt").write_text("untracked\n")
        sync = self.sync(self.base, exact=True)
        self.assertEqual(sync.status, "aligned")
        self.assertEqual((self.repo / "draft.txt").read_text(), "owner edit\n")
        self.assertIn("A  staged.txt", git(self.repo, "status", "--short"))
        self.assertEqual((self.repo / "untracked.txt").read_text(), "untracked\n")

    def test_exact_dirty_overlap_refuses_and_preserves_original_tip(self):
        local = self.commit_locally()
        (self.repo / "handoff.txt").write_text("owner edit\n")
        sync = self.sync(self.base, exact=True)
        self.assertEqual(sync.status, "blocked")
        self.assertIn("handoff.txt", sync.detail)
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        self.assertEqual(git(self.repo, "rev-parse", sync.preserved_ref), local)
        self.assertEqual((self.repo / "handoff.txt").read_text(), "owner edit\n")

    def test_exact_unattached_main_keeps_task_checkout(self):
        local = self.commit_locally()
        git(self.repo, "switch", "-c", "task")
        sync = self.sync(self.base, exact=True)
        self.assertEqual(sync.status, "aligned")
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "task")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), local)
        self.assertEqual(git(self.repo, "rev-parse", "main"), self.base)

    def test_exact_preservation_collision_blocks(self):
        local = self.commit_locally()
        ref = f"refs/heads/retained/main-before-latest-{local}"
        git(self.repo, "update-ref", ref, self.base)
        sync = self.sync(self.base, exact=True)
        self.assertEqual(sync.status, "blocked")
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        self.assertEqual(git(self.repo, "rev-parse", ref), self.base)

    def test_exact_cli_preview_is_read_only(self):
        local = self.commit_locally()
        args = [sys.executable, str(Path(syncer.__file__)), "--repo", str(self.repo),
                "--default-branch", "main", "--target", self.base, "--exact"]
        preview = json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)
        self.assertEqual(preview["default_branch_sync"]["status"], "align")
        ref = preview["default_branch_sync"]["preserved_ref"]
        self.assertFalse(git(self.repo, "for-each-ref", ref))
        self.assertEqual(git(self.repo, "rev-parse", "main"), local)
        result = json.loads(subprocess.run([*args, "--execute"], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result["default_branch_sync"]["status"], "aligned")
        self.assertEqual(git(self.repo, "rev-parse", "main"), self.base)
        self.assertEqual(git(self.repo, "rev-parse", ref), local)

    def test_operation_in_progress_blocks(self):
        upstream = self.advance_upstream()
        self.commit_locally()
        git_dir = Path(git(self.repo, "rev-parse", "--absolute-git-dir"))
        (git_dir / "MERGE_HEAD").write_text(f"{upstream}\n")

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "blocked")
        self.assertIn("MERGE_HEAD", sync.detail)

    def test_replay_runs_no_repository_hook(self):
        upstream = self.advance_upstream()
        self.commit_locally()
        marker = Path(self.temp_dir.name) / "hook-ran"
        hook = Path(git(self.repo, "rev-parse", "--absolute-git-dir")) / "hooks" / "post-commit"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)

        sync = self.sync(upstream)

        self.assertEqual(sync.status, "rebased")
        self.assertFalse(marker.exists())

    def test_cli_previews_then_executes(self):
        upstream = self.advance_upstream()
        self.commit_locally()
        script = str(Path(syncer.__file__))
        base = [sys.executable, script, "--repo", str(self.repo), "--default-branch", "main",
                "--target", "origin/main"]

        preview = json.loads(subprocess.run(base, text=True, capture_output=True, check=True).stdout)
        executed = json.loads(
            subprocess.run([*base, "--execute"], text=True, capture_output=True, check=True).stdout
        )

        self.assertEqual(preview["default_branch_sync"]["status"], "rebase")
        self.assertEqual(executed["default_branch_sync"]["status"], "rebased")
        self.assertEqual(git(self.repo, "rev-parse", "main~1"), upstream)


if __name__ == "__main__":
    unittest.main()
