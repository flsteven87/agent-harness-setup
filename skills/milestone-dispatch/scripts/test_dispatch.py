#!/usr/bin/env python3
"""Regression tests for the single dispatch implementation shared by milestone-dispatch and the board."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("dispatch.py")
SPEC = importlib.util.spec_from_file_location("dispatch", MODULE_PATH)
assert SPEC and SPEC.loader
dispatch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dispatch
SPEC.loader.exec_module(dispatch)


# Orca's `terminal send --json` result, trimmed to what the dispatcher reads (observed 2026-09-30).
ACCEPTED = {"send": {"accepted": True, "prompt": {"stages": ["input_accepted"]}}, "warnings": []}


class DispatchTest(unittest.TestCase):
    def run_dispatch(
        self, sent: dict, terminals: list[dict] | None = None, linger: int = 0, **kwargs: object
    ) -> tuple[dict, list, str]:
        """`linger` is how many later listings still show a terminal after its close."""
        orca_calls: list[tuple[str, ...]] = []
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp = temporary.name
        self.launch_commands: list[list[str]] = []
        listed = [{"handle": "shell1"}] if terminals is None else terminals
        closed: list[str] = []

        def fake_orca(*args: str, retry: bool = False, timeout: int = 90) -> dict:
            nonlocal linger
            orca_calls.append(args)
            if args[:2] == ("worktree", "create"):
                return {"worktree": {"id": "repo::/wt/new", "path": "/wt/new"}}
            if args[:2] == ("terminal", "close"):
                closed.append(args[args.index("--terminal") + 1])
            if args[:2] == ("terminal", "list"):
                if closed and linger:
                    linger -= 1
                    return {"terminals": listed}
                return {"terminals": [t for t in listed if t["handle"] not in closed]}
            if args[:2] == ("terminal", "send"):
                return sent
            return {}

        def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "git":
                return subprocess.CompletedProcess(argv, 0, f"{tmp}\n", "")
            self.launch_commands.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "terminal_handle": "agent1"}), "")

        with (
            mock.patch.object(dispatch, "orca", fake_orca),
            mock.patch.object(dispatch.subprocess, "run", fake_run),
            mock.patch.object(dispatch.time, "sleep"),
        ):
            result = dispatch.dispatch("/s", "slug-0930-1012", "# Assignment", "/goal Do it.", **kwargs)
        return result, orca_calls, tmp

    def test_default_receiver_is_codex_61_sol_medium_fast(self) -> None:
        self.run_dispatch(ACCEPTED)
        command = self.launch_commands[0]
        for flag, value in (("--agent", "codex"), ("--model", "gpt-6.1-sol"),
                            ("--effort", "medium"), ("--service-tier", "fast")):
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_explicit_receiver_configuration_overrides_defaults(self) -> None:
        self.run_dispatch(ACCEPTED, model="gpt-6-astra", effort="high", service_tier="default")
        command = self.launch_commands[0]
        for flag, value in (("--model", "gpt-6-astra"), ("--effort", "high"),
                            ("--service-tier", "default")):
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_claude_override_uses_its_own_model_and_no_codex_tier(self) -> None:
        self.run_dispatch(ACCEPTED, agent="claude")
        command = self.launch_commands[0]
        self.assertEqual(command[command.index("--model") + 1], "opus")
        self.assertNotIn("--service-tier", command)

    def test_cli_uses_the_same_defaults_as_the_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assignment = Path(tmp, "assignment.md")
            assignment.write_text("Assignment")
            with mock.patch.object(dispatch, "dispatch", return_value={}) as handoff, mock.patch("builtins.print"):
                self.assertEqual(dispatch.main(["--repo", "/s", "--name", "task",
                                                "--assignment", str(assignment), "--goal", "/goal Do it"]), 0)
            self.assertEqual(handoff.call_args.kwargs["agent"], "codex")
            self.assertEqual(handoff.call_args.kwargs["effort"], "medium")
            self.assertIsNone(handoff.call_args.kwargs["model"])
            self.assertIsNone(handoff.call_args.kwargs["service_tier"])

    def test_it_launches_the_reviewed_receiver_and_delivers_the_assignment(self) -> None:
        seen: list[tuple[str, str]] = []
        result, calls, tmp = self.run_dispatch(ACCEPTED, on_worktree=lambda n, p: seen.append((n, p)))
        self.assertEqual(seen, [("slug-0930-1012", "/wt/new")])
        self.assertEqual(Path(tmp, "endgame-assignment.md").read_text(encoding="utf-8"), "# Assignment")
        self.assertEqual(result["terminal"], "agent1")
        create = next(c for c in calls if c[:2] == ("worktree", "create"))
        self.assertEqual(create[create.index("--setup") + 1], "skip")
        self.assertNotIn("--base-branch", create)
        self.assertIn(("terminal", "close", "--terminal", "shell1", "--tab"), calls)
        send = next(c for c in calls if c[:2] == ("terminal", "send"))
        text = send[send.index("--text") + 1]
        self.assertTrue(text.startswith("/goal Do it.") and text.endswith(f"{tmp}/endgame-assignment.md before acting. {dispatch.TERMINAL_LANGUAGE}"))

    def test_a_label_names_the_worktree_and_terminal_for_the_owner(self) -> None:
        _, calls, _ = self.run_dispatch(ACCEPTED, label="看板改成報告格式")
        self.assertIn(("worktree", "set", "--worktree", "id:repo::/wt/new", "--display-name", "看板改成報告格式"), calls)
        _, unlabeled, _ = self.run_dispatch(ACCEPTED)
        self.assertFalse(any(c[:2] == ("worktree", "set") for c in unlabeled))

    def test_the_receiver_starts_only_after_the_closed_shell_leaves_the_list(self) -> None:
        result, calls, _ = self.run_dispatch(ACCEPTED, linger=3)
        self.assertEqual(result["terminal"], "agent1")
        self.assertEqual(sum(c[:2] == ("terminal", "list") for c in calls), 5)

    def test_a_shell_that_never_closes_preserves_the_worktree(self) -> None:
        with mock.patch.object(dispatch, "CLOSE_SETTLE_SECONDS", -1), self.assertRaises(dispatch.LaunchError) as caught:
            self.run_dispatch(ACCEPTED, linger=99)
        self.assertEqual((caught.exception.retry, caught.exception.path), (False, "/wt/new"))

    def test_a_prerequisite_base_is_passed_to_orca(self) -> None:
        _, calls, _ = self.run_dispatch(ACCEPTED, base="origin/feature-base")
        create = next(c for c in calls if c[:2] == ("worktree", "create"))
        self.assertEqual(create[create.index("--base-branch") + 1], "origin/feature-base")

    def test_delivery_counts_only_when_orca_confirms_acceptance(self) -> None:
        with self.assertRaises(dispatch.LaunchError) as caught:
            self.run_dispatch({})
        self.assertEqual((caught.exception.worktree, caught.exception.path, caught.exception.retry), ("slug-0930-1012", "/wt/new", False))
        # The receiver had started, so the failure names it for the board to observe.
        self.assertEqual(caught.exception.terminal, "agent1")

    def test_an_unexpected_terminal_in_the_new_worktree_is_preserved(self) -> None:
        with self.assertRaises(dispatch.LaunchError) as caught:
            self.run_dispatch(ACCEPTED, terminals=[{"handle": "t1", "agentIdentity": "codex"}])
        self.assertEqual((caught.exception.retry, caught.exception.path), (False, "/wt/new"))

    def test_a_failure_after_creation_names_the_preserved_worktree(self) -> None:
        def fake_orca(*args: str, retry: bool = False, timeout: int = 90) -> dict:
            if args[:2] == ("worktree", "create"):
                return {"worktree": {"id": "repo::/wt/new", "path": "/wt/new"}}
            raise dispatch.LaunchError("Orca 沒有回應（terminal list），結果不確定；先到 Orca 看一下。")

        with mock.patch.object(dispatch, "orca", fake_orca), self.assertRaises(dispatch.LaunchError) as caught:
            dispatch.dispatch("/s", "slug-0930-1012", "# Assignment", "/goal Do it.")
        self.assertEqual((caught.exception.worktree, caught.exception.path), ("slug-0930-1012", "/wt/new"))

        def timeout(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired("launch_yolo_agent.py", 300)

        with mock.patch.object(dispatch, "orca", lambda *a, **k: fake_orca(*a) if a[:2] == ("worktree", "create") else {"terminals": []}), \
                mock.patch.object(dispatch.subprocess, "run", timeout), self.assertRaises(dispatch.LaunchError) as caught:
            dispatch.dispatch("/s", "slug-0930-1012", "# Assignment", "/goal Do it.")
        self.assertEqual((caught.exception.path, caught.exception.retry), ("/wt/new", False))

    def test_only_an_explicit_rejection_can_be_retried(self) -> None:
        def run(stdout: str, code: int = 1) -> mock._patch:
            return mock.patch.object(dispatch.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, ""))

        with run('{"ok": false, "error": {"message": "no repo"}}'), self.assertRaises(dispatch.LaunchError) as caught:
            dispatch.orca("worktree", "create", retry=True)
        self.assertTrue(caught.exception.retry)
        with run("garbled"), self.assertRaises(dispatch.LaunchError) as caught:
            dispatch.orca("worktree", "create", retry=True)
        self.assertFalse(caught.exception.retry)
        with run('{"ok": false}'), self.assertRaises(dispatch.LaunchError) as caught:
            dispatch.orca("terminal", "list")
        self.assertFalse(caught.exception.retry)


if __name__ == "__main__":
    unittest.main()
