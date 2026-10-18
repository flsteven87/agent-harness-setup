#!/usr/bin/env python3
"""Behavioral tests for the Orca/Git worktree attach adapter."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().with_name("crg-worktree-attach")


def load_attach():
    loader = importlib.machinery.SourceFileLoader("crg_attach_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class WorktreeAttachContractTest(unittest.TestCase):
    def test_explicit_orca_attach_does_not_write_worktree_mcp_config(self) -> None:
        attach = load_attach()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            lifecycle = root / "crg-lifecycle"
            lifecycle.touch()
            attach.LIFECYCLE = lifecycle

            with mock.patch.object(attach.subprocess, "run") as run:
                run.return_value = SimpleNamespace(returncode=0)
                result = attach.main(
                    [str(repo), "--orca-instance-id", "orca-instance-123"]
                )

            self.assertEqual(result, 0)
            run.assert_called_once_with(
                [
                    str(lifecycle),
                    "attach",
                    str(repo),
                    "--orca-instance-id",
                    "orca-instance-123",
                ],
                check=False,
            )
            self.assertFalse((repo / ".mcp.json").exists())

    def test_explicit_repo_does_not_inherit_ambient_orca_instance(self) -> None:
        attach = load_attach()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            lifecycle = root / "crg-lifecycle"
            lifecycle.touch()
            attach.LIFECYCLE = lifecycle
            with (
                mock.patch.object(
                    attach, "current_orca_instance_id", return_value="wrong-instance"
                ) as current_instance,
                mock.patch.object(
                    attach.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                result = attach.main([str(repo)])
            self.assertEqual(result, 0)
            current_instance.assert_not_called()
            run.assert_called_once_with(
                [str(lifecycle), "attach", str(repo)], check=False
            )

    def test_lifecycle_failure_is_reported_without_a_traceback(self) -> None:
        attach = load_attach()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            lifecycle = root / "crg-lifecycle"
            lifecycle.touch()
            attach.LIFECYCLE = lifecycle
            with (
                mock.patch.object(
                    attach.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=7),
                ),
                mock.patch("sys.stderr") as stderr,
            ):
                result = attach.main([str(repo)])
            self.assertEqual(result, 7)
            stderr.write.assert_any_call(
                "crg-worktree-attach: lifecycle attach failed (exit 7)"
            )


if __name__ == "__main__":
    unittest.main()
