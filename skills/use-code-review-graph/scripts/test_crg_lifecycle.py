from __future__ import annotations

import fcntl
import importlib.machinery
import importlib.util
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().with_name("crg-lifecycle")
READONLY_SCRIPT = Path(__file__).resolve().with_name("code-review-graph-readonly")
WRITER_SCRIPT = Path(__file__).resolve().with_name("crg-writer-supervisor")


def load_script(path: Path, prefix: str):
    name = f"{prefix}_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class LifecycleSafetyTests(unittest.TestCase):
    def test_run_is_safe_from_a_worker_thread(self) -> None:
        lifecycle = load_script(SCRIPT, "crg_lifecycle")
        result: list[int] = []
        failure: list[BaseException] = []

        def worker() -> None:
            try:
                result.append(lifecycle.run(["/usr/bin/true"]).returncode)
            except BaseException as error:
                failure.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failure, [])
        self.assertEqual(result, [0])

    def test_run_forwards_termination_to_child_process_group(self) -> None:
        with tempfile.TemporaryDirectory(prefix="crg-signal-test.") as temporary:
            pid_file = Path(temporary) / "child.pid"
            harness_code = f"""
import importlib.machinery
import importlib.util
loader = importlib.machinery.SourceFileLoader('crg_signal_harness', {str(SCRIPT)!r})
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
module.run(['/bin/sh', '-c', 'echo $$ > "$1"; sleep 60', 'sh', {str(pid_file)!r}], timeout=60)
"""
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            harness = subprocess.Popen([sys.executable, "-c", harness_code], env=environment)
            try:
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(pid_file.exists(), "child process did not start")
                child_pid = int(pid_file.read_text().strip())
                os.kill(harness.pid, signal.SIGTERM)
                harness.wait(timeout=10)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if harness.poll() is None:
                    harness.kill()
                    harness.wait(timeout=5)

    def test_unchanged_graph_uses_cached_status_fast_path(self) -> None:
        lifecycle = load_script(SCRIPT, "crg_lifecycle")
        with tempfile.TemporaryDirectory(prefix="crg-noop-test.") as temporary:
            repo = Path(temporary) / "repo"
            database = repo / ".code-review-graph" / "graph.db"
            database.parent.mkdir(parents=True)
            database.write_bytes(b"validated graph")
            snapshot = {
                "head": "abc123",
                "fingerprint": "workspace-fingerprint",
                "parseable_untracked_files": [],
            }
            entry = {
                "state": "healthy",
                "ignore_hash": "ignore-hash",
                "crg_version": "2.3.7",
                "schema_version": "9",
                "fingerprint_version": 2,
                "indexed_fingerprint": snapshot["fingerprint"],
                "graph_artifact": lifecycle.graph_artifact_identity(database),
                "built_commit": "abc123",
                "built_branch": "main",
                "last_action": "refresh",
                "nodes": 2,
                "edges": 1,
                "files": 1,
                "languages": ["Python"],
            }
            with (
                mock.patch.object(lifecycle, "ignore_hash", return_value="ignore-hash"),
                mock.patch.object(lifecycle, "crg_version", return_value="2.3.7"),
                mock.patch.object(lifecycle, "graph_schema_version", return_value="9"),
                mock.patch.object(
                    lifecycle,
                    "readonly_graph_status",
                    side_effect=AssertionError("cached status should be enough"),
                ),
            ):
                action, _, _, status = lifecycle.decide_action(repo, entry, snapshot)
            self.assertEqual(action, "noop")
            self.assertEqual(status["nodes"], 2)

    def test_inspect_rejects_changed_graph_artifact_before_deep_reads(self) -> None:
        lifecycle = load_script(SCRIPT, "crg_lifecycle")
        with tempfile.TemporaryDirectory(prefix="crg-artifact-test.") as temporary:
            repo = Path(temporary) / "repo"
            database = repo / ".code-review-graph" / "graph.db"
            database.parent.mkdir(parents=True)
            database.write_bytes(b"validated graph")
            lifecycle.WORKTREE_LOCK_DIR = Path(temporary) / "locks"
            lifecycle.ensure_worktree_lock(repo)
            artifact = lifecycle.graph_artifact_identity(database)
            database.write_bytes(b"changed after validation")
            entry = {"state": "healthy", "graph_artifact": artifact}
            with (
                mock.patch.object(lifecycle, "canonical_live_worktree", return_value=repo),
                mock.patch.object(
                    lifecycle,
                    "read_state_readonly",
                    return_value={"version": 2, "worktrees": {str(repo): entry}},
                ),
            ):
                result = lifecycle.inspect(str(repo))
            self.assertFalse(result["usable"])
            self.assertIn("artifact", result["reason"])

    def test_worktree_writer_only_blocks_matching_reader(self) -> None:
        readonly = load_script(READONLY_SCRIPT, "crg_readonly")
        writer = load_script(WRITER_SCRIPT, "crg_writer")
        with tempfile.TemporaryDirectory(prefix="crg-lock-test.") as temporary:
            lock_dir = Path(temporary) / "locks"
            readonly.WORKTREE_LOCK_DIR = lock_dir
            writer.WORKTREE_LOCK_DIR = lock_dir
            repo_a = Path(temporary) / "repo-a"
            repo_b = Path(temporary) / "repo-b"
            for repo in (repo_a, repo_b):
                repo.mkdir()
                lock = readonly.worktree_lock_path(repo)
                lock.parent.mkdir(parents=True, exist_ok=True)
                lock.touch()
            self.assertEqual(
                readonly.worktree_lock_path(repo_a), writer.worktree_lock_path(repo_a)
            )
            writer_handle = writer.worktree_lock_path(repo_a).open("r+")
            fcntl.flock(writer_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaisesRegex(
                    sqlite3.OperationalError, "worktree refresh is in progress"
                ):
                    readonly.open_worktree_reader_lock(repo_a)
                reader_handle = readonly.open_worktree_reader_lock(repo_b)
                fcntl.flock(reader_handle.fileno(), fcntl.LOCK_UN)
                reader_handle.close()
            finally:
                fcntl.flock(writer_handle.fileno(), fcntl.LOCK_UN)
                writer_handle.close()

    def test_lock_paths_canonicalize_equivalent_worktree_paths(self) -> None:
        lifecycle = load_script(SCRIPT, "crg_lifecycle")
        readonly = load_script(READONLY_SCRIPT, "crg_readonly")
        writer = load_script(WRITER_SCRIPT, "crg_writer")
        with tempfile.TemporaryDirectory(prefix="crg-lock-canonical.") as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            variant = Path(f"{repo}/./")
            expected = lifecycle.worktree_lock_path(repo)
            self.assertEqual(lifecycle.worktree_lock_path(variant), expected)
            self.assertEqual(readonly.worktree_lock_path(variant), expected)
            self.assertEqual(writer.worktree_lock_path(variant), expected)

    def test_writer_waits_for_matching_reader_instead_of_failing(self) -> None:
        writer = load_script(WRITER_SCRIPT, "crg_writer")
        with tempfile.TemporaryDirectory(prefix="crg-writer-wait.") as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            refresh = root / "refresh"
            refresh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            refresh.chmod(0o755)
            writer.SAFE_REFRESH = refresh.resolve(strict=True)
            writer.GLOBAL_WRITER_LOCK = root / "writer.flock"
            writer.GLOBAL_WRITER_LOCK.touch()
            writer.WORKTREE_LOCK_DIR = root / "locks"
            target = writer.worktree_lock_path(repo)
            target.parent.mkdir(parents=True)
            target.touch()
            reader = target.open("r")
            fcntl.flock(reader.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            outcomes: list[int] = []

            def run_writer() -> None:
                with (
                    mock.patch.object(
                        writer.sys,
                        "argv",
                        ["crg-writer-supervisor", str(refresh), "build", str(repo)],
                    ),
                    mock.patch.object(writer.signal, "signal"),
                ):
                    outcomes.append(writer.main())

            thread = threading.Thread(target=run_writer)
            try:
                thread.start()
                time.sleep(0.1)
                self.assertTrue(thread.is_alive())
            finally:
                fcntl.flock(reader.fileno(), fcntl.LOCK_UN)
                reader.close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes, [0])

    def test_writer_bounds_wait_for_a_wedged_reader(self) -> None:
        writer = load_script(WRITER_SCRIPT, "crg_writer")
        with tempfile.TemporaryDirectory(prefix="crg-writer-timeout.") as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            refresh = root / "refresh"
            refresh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            refresh.chmod(0o755)
            writer.SAFE_REFRESH = refresh.resolve(strict=True)
            writer.GLOBAL_WRITER_LOCK = root / "writer.flock"
            writer.GLOBAL_WRITER_LOCK.touch()
            writer.WORKTREE_LOCK_DIR = root / "locks"
            writer.TARGET_LOCK_WAIT_SECONDS = 0.1
            target = writer.worktree_lock_path(repo)
            target.parent.mkdir(parents=True)
            target.touch()
            reader = target.open("r")
            fcntl.flock(reader.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            try:
                with (
                    mock.patch.object(
                        writer.sys,
                        "argv",
                        ["crg-writer-supervisor", str(refresh), "build", str(repo)],
                    ),
                    mock.patch.object(writer.subprocess, "Popen") as popen,
                ):
                    started = time.monotonic()
                    result = writer.main()
                    elapsed = time.monotonic() - started
                self.assertEqual(result, writer.TEMPORARY_CONTENTION_EXIT)
                self.assertLess(elapsed, 1.0)
                popen.assert_not_called()
            finally:
                fcntl.flock(reader.fileno(), fcntl.LOCK_UN)
                reader.close()


if __name__ == "__main__":
    unittest.main()
