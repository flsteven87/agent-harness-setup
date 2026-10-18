#!/usr/bin/env python3
"""Behavioral contract tests for the user-level CRG lifecycle coordinator."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().with_name("crg-lifecycle")
SAFE_REFRESH = Path(__file__).resolve().with_name("crg-safe-refresh")
ISOLATED_WRITER = Path(__file__).resolve().with_name("crg-isolated-build")


def load_lifecycle():
    loader = importlib.machinery.SourceFileLoader("crg_lifecycle_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_lifecycle_with_environment(environment: dict[str, str]):
    with mock.patch.dict("os.environ", environment, clear=False):
        return load_lifecycle()


class LifecycleContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_lifecycle()
        self.tempdir = tempfile.TemporaryDirectory(dir=str(Path.home()))
        root = Path(self.tempdir.name)
        control = root / "control"
        replacements = {
            "CONTROL_ROOT": control,
            "CONTROL_DB_PATH": control / "control.db",
            "CONTROL_INIT_LOCK_PATH": control / "control-init.lock",
            "OFFICIAL_REGISTRY_PATH": control / "registry.json",
            "COORDINATOR_LOCK_PATH": control / "lifecycle-coordinator.lock",
            "WORKTREE_LOCK_DIR": control / "locks",
        }
        for name, value in replacements.items():
            setattr(self.module, name, value)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_production_paths_ignore_ungated_environment_overrides(self) -> None:
        module = load_lifecycle_with_environment(
            {
                "CRG_TEST_MODE": "0",
                "CRG_USER_ROOT": "/tmp/attacker",
                "CRG_CONTROL_ROOT": "/tmp/attacker/control",
            }
        )
        self.assertEqual(module.USER_ROOT, Path.home())
        self.assertEqual(
            module.CONTROL_ROOT, (Path.home() / '.code-review-graph')
        )

    def seed_state(self, paths: list[str]) -> None:
        for path in paths:
            self.module.update_state_entry(path, {"path": path, "state": "pending"})

    def seed_event(self, path: str, **overrides: object) -> dict[str, object]:
        event: dict[str, object] = {
            "id": "event-1",
            "generation": 1,
            "repo": path,
            "reasons": ["git:post-commit"],
            "provision_required": False,
            "enqueued_at": "2026-08-12T00:00:00+00:00",
            "attempts": 0,
            "next_attempt_at": None,
        }
        event.update(overrides)
        self.module.store_queue_event(event)
        return event

    def test_enqueue_coalesces_reasons_and_keeps_provision_intent(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        identity = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "head": "abc",
            "branch": "main",
        }
        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=identity),
        ):
            self.module.enqueue(str(repo), "agent:graph-needed", kick=False)
            event = self.module.enqueue(str(repo), "git:post-commit", kick=False)

        self.assertEqual(event["generation"], 2)
        self.assertEqual(event["reasons"], ["agent:graph-needed", "git:post-commit"])
        self.assertTrue(event["provision_required"])
        entry = self.module.read_state()["worktrees"][str(repo)]
        self.assertIsInstance(entry["lifecycle_id"], str)

    def test_inspect_does_not_create_a_missing_control_database(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.module.ensure_worktree_lock(repo)

        result = self.module.inspect(str(repo))

        self.assertFalse(result["managed"])
        self.assertFalse(result["usable"])
        self.assertFalse(self.module.CONTROL_DB_PATH.exists())

    def test_inspect_ignores_the_retired_json_registry(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        database = repo / ".code-review-graph" / "graph.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"graph")
        identity = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "git_dir_device": 1,
            "git_dir_inode": 2,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 2,
            "head": "abc",
            "branch": "main",
        }
        entry = {
            **identity,
            "state": "healthy",
            "graph_artifact": self.module.graph_artifact_identity(database),
            "ignore_hash": "ignore",
            "crg_version": "1.0",
            "schema_version": "3",
            "fingerprint_version": 2,
            "indexed_fingerprint": "fingerprint",
            "built_commit": "abc",
            "nodes": 2,
            "files": 1,
        }
        self.module.update_state_entry(str(repo), entry)
        self.module.OFFICIAL_REGISTRY_PATH.write_text(
            json.dumps(
                {
                    "repos": [
                        {"path": str(repo), "data_dir": str(repo / "wrong")}
                    ]
                }
            ),
            encoding="utf-8",
        )

        with (
            mock.patch.object(self.module, "worktree_identity", return_value=identity),
            mock.patch.object(self.module, "ignore_hash", return_value="ignore"),
            mock.patch.object(self.module, "crg_version", return_value="1.0"),
            mock.patch.object(self.module, "graph_schema_version", return_value="3"),
            mock.patch.object(
                self.module,
                "workspace_snapshot",
                return_value={
                    "fingerprint": "fingerprint",
                    "parseable_untracked_files": [],
                },
            ),
        ):
            result = self.module.inspect_under_lock(repo)

        self.assertTrue(result["usable"])

    def test_inspect_reports_partial_coverage_for_untracked_source(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        database = repo / ".code-review-graph" / "graph.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"graph")
        identity = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "head": "abc",
            "branch": "main",
        }
        entry = {
            **identity,
            "state": "healthy",
            "graph_artifact": self.module.graph_artifact_identity(database),
            "ignore_hash": "ignore",
            "crg_version": "1.0",
            "schema_version": "3",
            "fingerprint_version": 2,
            "indexed_fingerprint": "fingerprint",
            "built_commit": "abc",
            "nodes": 2,
            "files": 1,
        }
        self.module.update_state_entry(str(repo), entry)
        with (
            mock.patch.object(self.module, "worktree_identity", return_value=identity),
            mock.patch.object(self.module, "ignore_hash", return_value="ignore"),
            mock.patch.object(self.module, "crg_version", return_value="1.0"),
            mock.patch.object(self.module, "graph_schema_version", return_value="3"),
            mock.patch.object(
                self.module,
                "workspace_snapshot",
                return_value={
                    "fingerprint": "fingerprint",
                    "parseable_untracked_files": ["new_module.py"],
                },
            ),
        ):
            result = self.module.inspect_under_lock(repo)

        self.assertTrue(result["usable"])
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["excluded_sources"], ["new_module.py"])

    def test_decision_uses_tracked_graph_with_untracked_source_excluded(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        database = repo / ".code-review-graph" / "graph.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"graph")
        snapshot = {
            "head": "abc",
            "fingerprint": "fingerprint",
            "parseable_untracked_files": ["new_module.py"],
        }
        entry = {
            "state": "healthy",
            "ignore_hash": "ignore",
            "crg_version": "1.0",
            "schema_version": "3",
            "fingerprint_version": 2,
            "indexed_fingerprint": "fingerprint",
            "built_commit": "abc",
            "graph_artifact": self.module.graph_artifact_identity(database),
            "nodes": 2,
            "files": 1,
        }
        with (
            mock.patch.object(self.module, "ignore_hash", return_value="ignore"),
            mock.patch.object(self.module, "crg_version", return_value="1.0"),
            mock.patch.object(self.module, "graph_schema_version", return_value="3"),
        ):
            action, _, _, _ = self.module.decide_action(repo, entry, snapshot)
        self.assertEqual(action, "noop")

    def test_stale_provenance_rebuilds_instead_of_looping(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        database = repo / ".code-review-graph" / "graph.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"graph")
        snapshot = {
            "head": "new-head",
            "fingerprint": "current-fingerprint",
            "parseable_untracked_files": [],
        }
        entry = {
            "state": "healthy",
            "ignore_hash": "ignore",
            "crg_version": "1.0",
            "schema_version": "3",
            "fingerprint_version": 2,
            "indexed_fingerprint": snapshot["fingerprint"],
            "built_commit": "old-head",
            "graph_artifact": self.module.graph_artifact_identity(database),
            "nodes": 2,
            "files": 1,
        }
        stale_status = {
            "built_at_commit": "old-head",
            "nodes": 2,
            "files": 1,
        }
        with (
            mock.patch.object(self.module, "ignore_hash", return_value="ignore"),
            mock.patch.object(self.module, "crg_version", return_value="1.0"),
            mock.patch.object(self.module, "graph_schema_version", return_value="3"),
            mock.patch.object(
                self.module, "readonly_graph_status", return_value=stale_status
            ),
        ):
            action, reason, _, _ = self.module.decide_action(repo, entry, snapshot)

        self.assertEqual(action, "rebuild")
        self.assertIn("provenance", reason)

        entry["built_commit"] = snapshot["head"]
        with (
            mock.patch.object(self.module, "ignore_hash", return_value="ignore"),
            mock.patch.object(self.module, "crg_version", return_value="1.0"),
            mock.patch.object(self.module, "graph_schema_version", return_value="3"),
        ):
            action, _, _, _ = self.module.decide_action(repo, entry, snapshot)
        self.assertEqual(action, "noop")

    def test_attach_registers_a_dormant_worktree_without_queueing_a_build(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        identity = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "git_dir_device": 1,
            "git_dir_inode": 2,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 2,
            "head": "abc",
            "branch": "main",
        }
        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=identity),
            mock.patch.object(self.module, "install_hooks", return_value=0),
        ):
            entry = self.module.attach(
                str(repo), orca_instance_id="orca-worktree-instance"
            )

        self.assertEqual(entry["state"], "dormant")
        self.assertEqual(entry["orca_instance_id"], "orca-worktree-instance")
        self.assertIsInstance(entry["lifecycle_id"], str)
        self.assertIsNone(self.module.read_queue_event(repo))

    def test_hook_preflight_does_not_partially_install_on_collision(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        hooks = repo / ".git" / "hooks"
        collision = hooks / "post-commit"
        collision.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        result = self.module.install_hooks(str(repo), dry_run=False)

        self.assertEqual(result, 1)
        self.assertEqual(collision.read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")
        for hook_name in ("post-checkout", "post-merge", "post-rewrite"):
            self.assertFalse((hooks / hook_name).exists())

    def test_hook_install_rolls_back_files_created_before_a_race(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        hooks = repo / ".git" / "hooks"
        real_open = self.module.os.open
        calls = 0

        def fail_second_open(path, flags, mode=0o777):
            nonlocal calls
            if Path(path).parent == hooks:
                calls += 1
                if calls == 2:
                    raise FileExistsError(path)
            return real_open(path, flags, mode)

        with mock.patch.object(self.module.os, "open", side_effect=fail_second_open):
            result = self.module.install_hooks(str(repo), dry_run=False)

        self.assertEqual(result, 1)
        for hook_name in ("post-checkout", "post-commit", "post-merge", "post-rewrite"):
            self.assertFalse((hooks / hook_name).exists())

    def test_liveness_rejects_a_reused_path_with_a_new_git_admin_inode(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        expected = {
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "git_dir_device": 1,
            "git_dir_inode": 10,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 20,
        }
        actual = {**expected, "git_dir_inode": 999}
        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=actual),
        ):
            live = self.module.is_live_worktree(str(repo), expected)

        self.assertFalse(live)

    def test_attach_rebinds_a_moved_worktree_by_stable_git_identity(self) -> None:
        old = str(Path(self.tempdir.name) / "old-path")
        repo = Path(self.tempdir.name) / "new-path"
        lifecycle_id = "lifecycle-stable-id"
        stable = {
            "git_dir": str(Path(self.tempdir.name) / "admin"),
            "git_common_dir": str(Path(self.tempdir.name) / "common"),
            "git_dir_device": 1,
            "git_dir_inode": 10,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 20,
        }
        self.module.update_state_entry(
            old,
            {
                **stable,
                "path": old,
                "state": "dormant",
                "lifecycle_id": lifecycle_id,
            },
        )
        self.seed_event(old)
        identity = {
            **stable,
            "path": str(repo),
            "head": "abc",
            "branch": "main",
        }

        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=identity),
            mock.patch.object(self.module, "install_hooks", return_value=0),
        ):
            entry = self.module.attach(str(repo))

        state = self.module.read_state()["worktrees"]
        self.assertNotIn(old, state)
        self.assertEqual(entry["lifecycle_id"], lifecycle_id)
        self.assertIsNotNone(self.module.read_queue_event(repo))
        self.assertIsNone(self.module.read_queue_event(Path(old)))

    def test_attach_treats_a_reused_path_as_a_new_lifecycle_identity(self) -> None:
        repo = Path(self.tempdir.name) / "reused-path"
        old_id = "old-lifecycle-id"
        self.module.update_state_entry(
            str(repo),
            {
                "path": str(repo),
                "state": "healthy",
                "lifecycle_id": old_id,
                "git_dir": str(repo / ".git"),
                "git_common_dir": str(repo / ".git"),
                "git_dir_device": 1,
                "git_dir_inode": 10,
                "git_common_dir_device": 1,
                "git_common_dir_inode": 20,
                "graph_artifact": {"inode": 99},
            },
        )
        self.seed_event(str(repo))
        replacement = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "git_dir_device": 1,
            "git_dir_inode": 999,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 20,
            "head": "replacement-head",
            "branch": "main",
        }
        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=replacement),
            mock.patch.object(self.module, "install_hooks", return_value=0),
        ):
            entry = self.module.attach(str(repo))

        self.assertNotEqual(entry["lifecycle_id"], old_id)
        self.assertEqual(entry["state"], "dormant")
        self.assertNotIn("graph_artifact", entry)
        self.assertIsNone(self.module.read_queue_event(repo))

    def test_enqueue_treats_a_reused_path_as_a_new_lifecycle_identity(self) -> None:
        repo = Path(self.tempdir.name) / "reused-hook-path"
        self.module.update_state_entry(
            str(repo),
            {
                "path": str(repo),
                "state": "healthy",
                "lifecycle_id": "old-lifecycle-id",
                "git_dir": str(repo / ".git"),
                "git_common_dir": str(repo / ".git"),
                "git_dir_device": 1,
                "git_dir_inode": 10,
                "git_common_dir_device": 1,
                "git_common_dir_inode": 20,
                "graph_artifact": {"inode": 99},
            },
        )
        self.seed_event(str(repo), generation=7)
        replacement = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "git_dir_device": 1,
            "git_dir_inode": 999,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 20,
            "head": "replacement-head",
            "branch": "main",
        }
        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=replacement),
        ):
            event = self.module.enqueue(str(repo), "git:post-checkout", kick=False)

        entry = self.module.read_state()["worktrees"][str(repo)]
        self.assertNotEqual(entry["lifecycle_id"], "old-lifecycle-id")
        self.assertNotIn("graph_artifact", entry)
        self.assertEqual(event["generation"], 1)

    def test_concurrent_enqueues_are_one_monotonic_work_item(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        identity = {
            "path": str(repo),
            "git_dir": str(repo / ".git"),
            "git_common_dir": str(repo / ".git"),
            "head": "abc",
            "branch": "main",
        }
        with (
            mock.patch.object(self.module, "canonical_live_worktree", return_value=repo),
            mock.patch.object(self.module, "worktree_identity", return_value=identity),
        ):
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(
                    executor.map(
                        lambda _: self.module.enqueue(
                            str(repo), "git:post-commit", kick=False
                        ),
                        range(40),
                    )
                )
        event = self.module.read_queue_event(repo)
        assert event is not None
        self.assertEqual(event["generation"], 40)
        self.assertEqual(event["reasons"], ["git:post-commit"])

    def test_stale_completion_cannot_acknowledge_new_generation(self) -> None:
        repo = (Path.home() / 'queued-repo')
        self.seed_state([str(repo)])
        old = self.seed_event(str(repo))
        claimed = self.module.claim_queue_event(old)
        assert claimed is not None
        new = {**old, "id": "event-2", "generation": 2}
        self.module.store_queue_event(new)

        self.module.commit_attempt(
            repo,
            claimed,
            {"path": str(repo), "state": "healthy"},
            success=True,
        )

        remaining = self.module.read_queue_event(repo)
        assert remaining is not None
        self.assertEqual(remaining["generation"], 2)
        self.assertEqual(
            self.module.read_state()["worktrees"][str(repo)]["state"], "pending"
        )

    def test_commit_preserves_newer_runtime_identity_metadata(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        self.module.update_state_entry(
            str(repo),
            {
                "path": str(repo),
                "state": "pending",
                "lifecycle_id": "current-lifecycle",
                "orca_instance_id": "current-orca-instance",
            },
        )
        event = self.seed_event(str(repo))
        claimed = self.module.claim_queue_event(event)
        assert claimed is not None

        self.module.commit_attempt(
            repo,
            claimed,
            {"path": str(repo), "state": "healthy"},
            success=True,
        )

        entry = self.module.read_state()["worktrees"][str(repo)]
        self.assertEqual(entry["lifecycle_id"], "current-lifecycle")
        self.assertEqual(entry["orca_instance_id"], "current-orca-instance")

    def test_noop_preserves_runtime_identity_metadata(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        repo.mkdir()
        entry = {
            "path": str(repo),
            "state": "healthy",
            "lifecycle_id": "stable-lifecycle",
            "orca_instance_id": "stable-orca-instance",
        }
        snapshot = {"fingerprint": "same", "dirty_files": []}
        with (
            mock.patch.object(self.module, "ensure_worktree_lock"),
            mock.patch.object(self.module, "workspace_snapshot", return_value=snapshot),
            mock.patch.object(
                self.module,
                "decide_action",
                return_value=("noop", "graph is current", None, {}),
            ),
            mock.patch.object(
                self.module,
                "lifecycle_metadata",
                return_value={"path": str(repo), "state": "healthy"},
            ),
        ):
            success, updated = self.module.process_live_worktree(
                repo, entry, None, dry_run=False
            )

        self.assertTrue(success)
        self.assertEqual(updated["lifecycle_id"], "stable-lifecycle")
        self.assertEqual(updated["orca_instance_id"], "stable-orca-instance")

    def test_reader_contention_stays_pending_without_running_graph_logic(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        repo.mkdir()
        entry = {"path": str(repo), "state": "pending", "lifecycle_id": "stable"}
        snapshot = {"fingerprint": "before", "dirty_files": []}
        contention = subprocess.CompletedProcess(
            [str(self.module.SAFE_REFRESH), "refresh", str(repo)],
            75,
            "",
            "crg-writer-supervisor: target worktree has active readers\n",
        )
        with (
            mock.patch.object(self.module, "ensure_worktree_lock"),
            mock.patch.object(self.module, "workspace_snapshot", return_value=snapshot),
            mock.patch.object(
                self.module,
                "decide_action",
                return_value=("refresh", "tracked files changed", "HEAD", {}),
            ),
            mock.patch.object(
                self.module, "read_state", return_value={"worktrees": {}}
            ),
            mock.patch.object(self.module, "total_managed_graph_bytes", return_value=0),
            mock.patch.object(self.module, "graph_directory_bytes", return_value=0),
            mock.patch.object(self.module, "run", return_value=contention),
            mock.patch.object(
                self.module,
                "worktree_identity",
                return_value={"path": str(repo), "head": "abc", "branch": "main"},
            ),
        ):
            success, updated = self.module.process_live_worktree(
                repo, entry, {"reason": "git:post-commit"}, dry_run=False
            )

        self.assertFalse(success)
        self.assertEqual(updated["state"], "pending")
        self.assertEqual(updated["lifecycle_id"], "stable")
        self.assertIn("active graph readers", updated["last_error"])

    def test_successful_write_with_stale_provenance_fails_closed(self) -> None:
        repo = Path(self.tempdir.name) / "repo"
        repo.mkdir()
        entry = {"path": str(repo), "state": "pending", "lifecycle_id": "stable"}
        snapshot = {"head": "new-head", "fingerprint": "same", "dirty_files": []}
        completed = subprocess.CompletedProcess(
            [str(self.module.SAFE_REFRESH), "refresh", str(repo)], 0, "", ""
        )
        with (
            mock.patch.object(self.module, "ensure_worktree_lock"),
            mock.patch.object(
                self.module,
                "workspace_snapshot",
                side_effect=[snapshot, snapshot],
            ),
            mock.patch.object(
                self.module,
                "decide_action",
                return_value=("refresh", "tracked files changed", "old-head", {}),
            ),
            mock.patch.object(self.module, "read_state", return_value={"worktrees": {}}),
            mock.patch.object(self.module, "total_managed_graph_bytes", return_value=0),
            mock.patch.object(self.module, "graph_directory_bytes", return_value=0),
            mock.patch.object(self.module, "run", return_value=completed),
            mock.patch.object(
                self.module,
                "readonly_graph_status",
                return_value={"built_at_commit": "old-head"},
            ),
            mock.patch.object(
                self.module,
                "worktree_identity",
                return_value={
                    "path": str(repo),
                    "head": "new-head",
                    "branch": "main",
                },
            ),
        ):
            success, updated = self.module.process_live_worktree(
                repo, entry, {"reason": "git:post-commit"}, dry_run=False
            )

        self.assertFalse(success)
        self.assertEqual(updated["state"], "failed")
        self.assertEqual(updated["lifecycle_id"], "stable")
        self.assertIn("provenance", updated["last_error"])

    def test_reconcile_leaves_an_idle_fresh_worktree_untouched(self) -> None:
        """An idle worktree is processed only when something queues it.

        The idle entry is seeded `healthy` with its graph built at HEAD, so the
        stale sweep genuinely evaluates it and declines, rather than being
        filtered out by a `pending` state before the predicate ever runs.
        """
        queued = str(Path.home() / 'queued-repo')
        idle = str(Path.home() / 'idle-repo')
        self.seed_state([queued])
        self.module.update_state_entry(
            idle, {"path": idle, "state": "healthy", "built_commit": "abc"}
        )
        self.seed_event(queued)
        calls: list[str] = []

        def process(repo, entry, event, *, dry_run):
            calls.append(str(repo))
            return True, {**entry, "state": "healthy"}

        with (
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(self.module, "git_value", return_value="abc"),
            mock.patch.object(self.module, "process_live_worktree", side_effect=process),
            mock.patch.object(self.module, "available_bytes", return_value=30 << 30),
        ):
            result = self.module.reconcile(repo_filter=None, dry_run=False)

        self.assertEqual(result, 0)
        self.assertEqual(calls, [queued])

    def sweep_once(self, head_by_repo: dict[str, str]) -> list[tuple[str, str, bool]]:
        enqueued: list[tuple[str, str, bool]] = []
        with (
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(
                self.module,
                "git_value",
                side_effect=lambda repo, *a, **k: head_by_repo[str(repo)],
            ),
            mock.patch.object(
                self.module,
                "enqueue",
                side_effect=lambda repo, reason, kick=True: enqueued.append(
                    (repo, reason, kick)
                ),
            ),
        ):
            self.module.sweep_stale_graphs(
                self.module.read_state(),
                dry_run=False,
                budget=self.module.MAX_ITEMS_PER_RUN,
            )
        return enqueued

    def test_stale_sweep_enqueues_only_commit_drift(self) -> None:
        """Only `built_commit != HEAD` enqueues.

        Dirty-but-current and zero-node graphs must not: neither clears by
        rebuilding, so sweeping them would rebuild on every edit and loop
        forever on a repo with no parseable source.
        """
        drifted = str(Path.home() / 'drifted-repo')
        current = str(Path.home() / 'current-repo')
        dirty_only = str(Path.home() / 'dirty-repo')
        zero_nodes = str(Path.home() / 'empty-repo')
        dormant = str(Path.home() / 'dormant-repo')
        queued = str(Path.home() / 'queued-repo')
        never_built = str(Path.home() / 'never-built-repo')
        for path, entry in (
            (drifted, {"state": "healthy", "built_commit": "old"}),
            (current, {"state": "healthy", "built_commit": "head"}),
            (dirty_only, {"state": "healthy", "built_commit": "head", "nodes": 12}),
            (zero_nodes, {"state": "healthy", "built_commit": "head", "nodes": 0}),
            (dormant, {"state": "dormant", "built_commit": "old"}),
            (queued, {"state": "healthy", "built_commit": "old"}),
            (never_built, {"state": "healthy"}),
        ):
            self.module.update_state_entry(path, {"path": path, **entry})
        heads = dict.fromkeys(
            [drifted, current, dirty_only, zero_nodes, dormant, queued, never_built],
            "head",
        )

        with mock.patch.object(
            self.module,
            "read_queue_event",
            side_effect=lambda repo: {"id": "e1"} if str(repo) == queued else None,
        ):
            enqueued = self.sweep_once(heads)

        self.assertEqual(enqueued, [(drifted, self.module.STALE_SWEEP_REASON, False)])

    def test_stale_sweep_enqueues_installed_version_drift(self) -> None:
        repo = str(Path.home() / 'version-drifted-repo')
        self.module.update_state_entry(
            repo,
            {
                "path": repo,
                "state": "healthy",
                "built_commit": "head",
                "crg_version": "2.3.7",
            },
        )
        enqueued: list[tuple[str, str, bool]] = []
        with (
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(self.module, "git_value", return_value="head"),
            mock.patch.object(self.module, "crg_version", return_value="2.3.8"),
            mock.patch.object(self.module, "read_queue_event", return_value=None),
            mock.patch.object(
                self.module,
                "enqueue",
                side_effect=lambda target, reason, kick=True: enqueued.append(
                    (target, reason, kick)
                ),
            ),
        ):
            self.module.sweep_stale_graphs(
                self.module.read_state(),
                dry_run=False,
                budget=self.module.MAX_ITEMS_PER_RUN,
            )

        self.assertEqual(
            enqueued,
            [(repo, self.module.VERSION_SWEEP_REASON, False)],
        )

    def test_stale_sweep_goes_quiet_once_the_graph_is_rebuilt(self) -> None:
        """The predicate must be monotone: one repair ends the sweep.

        A zero-node graph stays unusable however often it is rebuilt, so a
        predicate that keyed on usability would re-enqueue it every cycle
        forever. Keying on the indexed commit terminates after one pass.
        """
        repo = str(Path.home() / 'drifted-repo')
        self.module.update_state_entry(
            repo, {"path": repo, "state": "healthy", "built_commit": "old", "nodes": 0}
        )
        heads = {repo: "new"}

        with mock.patch.object(self.module, "read_queue_event", return_value=None):
            first = self.sweep_once(heads)
        self.assertEqual(first, [(repo, self.module.STALE_SWEEP_REASON, False)])

        # A successful rebuild advances built_commit and leaves nodes at zero.
        self.module.update_state_entry(
            repo, {"path": repo, "state": "healthy", "built_commit": "new", "nodes": 0}
        )
        with mock.patch.object(self.module, "read_queue_event", return_value=None):
            second = self.sweep_once(heads)
        self.assertEqual(second, [])

    def test_stale_sweep_yields_its_budget_to_queued_hook_events(self) -> None:
        """Detection must never starve real user activity."""
        drifted = str(Path.home() / 'drifted-repo')
        self.module.update_state_entry(
            drifted, {"path": drifted, "state": "healthy", "built_commit": "old"}
        )
        enqueued: list[str] = []
        with (
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(self.module, "git_value", return_value="head"),
            mock.patch.object(self.module, "read_queue_event", return_value=None),
            mock.patch.object(
                self.module,
                "enqueue",
                side_effect=lambda repo, reason, kick=True: enqueued.append(repo),
            ),
        ):
            self.module.sweep_stale_graphs(
                self.module.read_state(), dry_run=False, budget=0
            )
        self.assertEqual(enqueued, [])

    def test_reconcile_repairs_a_stale_graph_with_no_queued_event(self) -> None:
        stale = str(Path.home() / 'stale-repo')
        self.module.update_state_entry(
            stale, {"path": stale, "state": "healthy", "built_commit": "old"}
        )
        calls: list[str] = []

        def process(repo, entry, event, *, dry_run):
            calls.append(str(repo))
            return True, {**entry, "state": "healthy"}

        with (
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(self.module, "git_value", return_value="new"),
            mock.patch.object(
                self.module,
                "canonical_live_worktree",
                return_value=Path(stale),
            ),
            mock.patch.object(
                self.module,
                "worktree_identity",
                return_value={"path": stale, "head": "new", "branch": "main"},
            ),
            mock.patch.object(self.module, "process_live_worktree", side_effect=process),
            mock.patch.object(self.module, "available_bytes", return_value=30 << 30),
        ):
            result = self.module.reconcile(repo_filter=None, dry_run=False)

        self.assertEqual(result, 0)
        self.assertEqual(calls, [stale])

    def test_reconcile_audits_an_idle_missing_worktree(self) -> None:
        missing = str(Path.home() / 'missing-idle-repo')
        self.module.update_state_entry(
            missing,
            {
                "path": missing,
                "state": "healthy",
                "git_dir": f"{missing}/.git",
                "git_common_dir": f"{missing}/.git",
            },
        )

        with (
            mock.patch.object(self.module, "available_bytes", return_value=30 << 30),
            mock.patch.object(self.module, "is_live_worktree", return_value=False),
        ):
            result = self.module.reconcile(repo_filter=None, dry_run=False)

        entry = self.module.read_state()["worktrees"][missing]
        self.assertEqual(result, 0)
        self.assertEqual(entry["state"], "orphaned")
        self.assertEqual(entry["missing_confirmations"], 1)
        self.assertIsInstance(entry["orphaned_at"], str)

    def test_reconcile_forgets_only_after_orphan_grace_and_confirmation(self) -> None:
        missing = str(Path.home() / 'missing-after-grace')
        self.module.ORPHAN_GRACE_SECONDS = 0
        self.module.update_state_entry(
            missing,
            {
                "path": missing,
                "state": "orphaned",
                "state_before_orphan": "healthy",
                "missing_confirmations": 1,
                "orphaned_at": "2026-01-01T00:00:00+00:00",
            },
        )

        with (
            mock.patch.object(self.module, "available_bytes", return_value=30 << 30),
            mock.patch.object(self.module, "is_live_worktree", return_value=False),
        ):
            result = self.module.reconcile(repo_filter=None, dry_run=False)

        self.assertEqual(result, 0)
        self.assertNotIn(missing, self.module.read_state()["worktrees"])

    def test_reconcile_restores_an_orphan_that_is_live_again(self) -> None:
        repo = str(Path.home() / 'returned-worktree')
        self.module.update_state_entry(
            repo,
            {
                "path": repo,
                "state": "orphaned",
                "state_before_orphan": "dormant",
                "missing_confirmations": 1,
                "orphaned_at": "2026-08-13T00:00:00+00:00",
            },
        )

        with (
            mock.patch.object(self.module, "available_bytes", return_value=30 << 30),
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
        ):
            result = self.module.reconcile(repo_filter=None, dry_run=False)

        entry = self.module.read_state()["worktrees"][repo]
        self.assertEqual(result, 0)
        self.assertEqual(entry["state"], "dormant")
        self.assertNotIn("orphaned_at", entry)

    def test_forget_removes_an_exact_absent_managed_worktree(self) -> None:
        missing = str(Path(self.tempdir.name) / "removed-worktree")
        self.module.update_state_entry(
            missing,
            {"path": missing, "state": "orphaned", "missing_confirmations": 2},
        )

        self.module.forget(missing)

        self.assertNotIn(missing, self.module.read_state()["worktrees"])

    def test_low_disk_circuit_defers_without_invoking_graph_logic(self) -> None:
        queued = str(Path.home() / 'queued-repo')
        self.seed_state([queued])
        self.seed_event(queued)

        with (
            mock.patch.object(self.module, "available_bytes", return_value=7 << 30),
            mock.patch.object(self.module, "process_live_worktree") as process,
        ):
            result = self.module.reconcile(repo_filter=None, dry_run=False)

        self.assertEqual(result, 0)
        process.assert_not_called()
        self.assertIsNotNone(self.module.read_queue_event(Path(queued)))

    def test_disk_circuit_uses_8_10_gib_hysteresis(self) -> None:
        self.assertEqual(self.module.MIN_FREE_BYTES, 8 << 30)
        self.assertEqual(self.module.RESUME_FREE_BYTES, 10 << 30)

        with mock.patch.object(
            self.module, "available_bytes", return_value=7 << 30
        ):
            self.assertFalse(self.module.disk_work_allowed(dry_run=False))

        with mock.patch.object(
            self.module, "available_bytes", return_value=9 << 30
        ):
            self.assertFalse(self.module.disk_work_allowed(dry_run=False))

        with mock.patch.object(
            self.module, "available_bytes", return_value=10 << 30
        ):
            self.assertTrue(self.module.disk_work_allowed(dry_run=False))

        connection = self.module.control_connection(write=False)
        try:
            row = connection.execute(
                "SELECT value_json FROM system_state WHERE key='disk_circuit'"
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        circuit = json.loads(row[0])
        self.assertFalse(circuit["open"])
        self.assertEqual(circuit["minimum_free_bytes"], 8 << 30)
        self.assertEqual(circuit["resume_free_bytes"], 10 << 30)

    def test_failure_is_backed_off_and_not_immediately_retried(self) -> None:
        queued = str(Path.home() / 'queued-repo')
        self.seed_state([queued])
        self.seed_event(queued)

        with (
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(self.module, "available_bytes", return_value=30 << 30),
            mock.patch.object(
                self.module,
                "process_live_worktree",
                return_value=(False, {"path": queued, "state": "failed"}),
            ) as process,
        ):
            first = self.module.reconcile(repo_filter=None, dry_run=False)
            second = self.module.reconcile(repo_filter=None, dry_run=False)

        event = self.module.read_queue_event(Path(queued))
        assert event is not None
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(process.call_count, 1)
        self.assertEqual(event["attempts"], 1)
        self.assertIsInstance(event["next_attempt_at"], str)

    def test_incremental_refresh_mutates_only_an_apfs_clone(self) -> None:
        script = SAFE_REFRESH.read_text(encoding="utf-8")
        isolated = ISOLATED_WRITER.read_text(encoding="utf-8")
        self.assertIn('cp -cR "$data_dir" "$stage"', script)
        self.assertIn('update "$repo" "$stage" "$base"', script)
        self.assertIn('"--data-dir"', isolated)
        self.assertNotIn('--data-dir "$data_dir" \\\n+      --base "$base"', script)

    def test_safe_refresh_does_not_write_the_retired_json_registry(self) -> None:
        script = SAFE_REFRESH.read_text(encoding="utf-8")
        self.assertNotIn("registry.json", script)
        self.assertNotIn("bind_registry", script)
        self.assertNotIn('"$CRG_BIN" update', script)

    def test_safe_refresh_uses_the_circuit_breaker_floor(self) -> None:
        script = SAFE_REFRESH.read_text(encoding="utf-8")
        self.assertIn(
            'MIN_FREE_BYTES="${CRG_MIN_FREE_BYTES:-8589934592}"', script
        )

    def test_initial_provision_uses_a_fresh_worktree_build(self) -> None:
        repo = Path(self.tempdir.name) / "target"
        source = Path(self.tempdir.name) / "source"
        repo.mkdir()
        source.mkdir()
        source_database = source / ".code-review-graph" / "graph.db"
        source_database.parent.mkdir()
        source_database.write_bytes(b"validated sibling graph")
        entry = {"path": str(repo), "state": "pending"}
        event = {"reason": "agent:graph-needed", "provision_required": True}
        snapshot = {
            "head": "target-head",
            "fingerprint": "target-fingerprint",
            "parseable_untracked_files": [],
        }
        common_dir = str(Path(self.tempdir.name) / "common.git")
        target_identity = {
            "path": str(repo),
            "git_dir": str(Path(self.tempdir.name) / "target-admin"),
            "git_common_dir": common_dir,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 2,
            "head": "target-head",
            "branch": "feature",
        }
        sibling = {
            "path": str(source),
            "state": "healthy",
            "git_dir": str(Path(self.tempdir.name) / "source-admin"),
            "git_common_dir": common_dir,
            "git_common_dir_device": 1,
            "git_common_dir_inode": 2,
            "indexed_dirty_files": [],
            "fingerprint_version": 2,
            "ignore_hash": "ignore",
            "crg_version": "1.0",
            "built_commit": "abc123",
            "nodes": 2,
            "files": 1,
            "graph_artifact": self.module.graph_artifact_identity(source_database),
            "last_success_at": "2026-08-13T00:00:00+00:00",
        }
        commands: list[list[str]] = []

        with (
            mock.patch.object(self.module, "ensure_worktree_lock"),
            mock.patch.object(
                self.module, "workspace_snapshot", side_effect=[snapshot, snapshot]
            ),
            mock.patch.object(
                self.module,
                "decide_action",
                return_value=("build", "graph is missing", None, None),
            ),
            mock.patch.object(
                self.module,
                "read_state",
                return_value={"version": 2, "worktrees": {str(source): sibling}},
            ),
            mock.patch.object(
                self.module, "worktree_identity", return_value=target_identity
            ),
            mock.patch.object(self.module, "ignore_hash", return_value="ignore"),
            mock.patch.object(self.module, "crg_version", return_value="1.0"),
            mock.patch.object(self.module, "is_live_worktree", return_value=True),
            mock.patch.object(self.module, "is_ancestor", return_value=True),
            mock.patch.object(self.module, "total_managed_graph_bytes", return_value=0),
            mock.patch.object(self.module, "graph_directory_bytes", return_value=0),
            mock.patch.object(
                self.module,
                "run",
                side_effect=lambda command, **kwargs: (
                    commands.append(command)
                    or subprocess.CompletedProcess(command, 0, "", "")
                ),
            ),
            mock.patch.object(
                self.module,
                "lifecycle_metadata",
                return_value={"path": str(repo), "state": "healthy"},
            ),
            mock.patch.object(
                self.module,
                "readonly_graph_status",
                return_value={"built_at_commit": "target-head"},
            ),
        ):
            success, updated = self.module.process_live_worktree(
                repo, entry, event, dry_run=False
            )

        self.assertTrue(success)
        self.assertEqual(updated["last_action"], "build")
        self.assertEqual(
            commands,
            [
                [
                    str(self.module.SAFE_REFRESH),
                    "build",
                    str(repo),
                ]
            ],
        )

    def test_safe_refresh_has_no_cross_worktree_seed_mode(self) -> None:
        script = SAFE_REFRESH.read_text(encoding="utf-8")
        self.assertNotIn('cp -cR "$source_dir" "$stage"', script)
        self.assertNotIn('seed)', script)
        self.assertNotIn('crg-safe-refresh seed', script)


if __name__ == "__main__":
    unittest.main()
