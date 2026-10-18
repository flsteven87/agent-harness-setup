#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("launch_yolo_agent.py")
SPEC = importlib.util.spec_from_file_location("launch_yolo_agent", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def response(payload: dict[str, object], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, json.dumps(payload), "")


class FakeRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[str] | BaseException]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), timeout))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class AgentCommandTests(unittest.TestCase):
    def test_omitted_effort_defaults_to_medium_for_each_provider(self) -> None:
        for agent, expected in (
            ("codex", "--config 'model_reasoning_effort=\"medium\"'"),
            ("claude", "--effort medium"),
        ):
            with self.subTest(agent=agent):
                command, _ = MODULE.build_agent_command(agent)
                self.assertIn(expected, command)

    def test_codex_command_overrides_attended_global_defaults(self) -> None:
        command, autonomy = MODULE.build_agent_command("codex", "gpt-5.6", "high")

        self.assertEqual(
            command,
            "codex --ask-for-approval never --sandbox danger-full-access --model gpt-5.6 "
            "--config 'model_reasoning_effort=\"high\"' --config 'service_tier=\"fast\"'",
        )
        self.assertEqual(autonomy["approval_policy"], "never")
        self.assertEqual(autonomy["sandbox"], "danger-full-access")

    def test_codex_service_tier_can_be_overridden(self) -> None:
        command, _ = MODULE.build_agent_command("codex", "gpt-6-sol", "medium", "default")
        self.assertIn("service_tier=\"default\"", command)
        self.assertNotIn("service_tier=\"fast\"", command)

    def test_claude_rejects_codex_service_tier(self) -> None:
        with self.assertRaisesRegex(ValueError, "only to Codex"):
            MODULE.build_agent_command("claude", "opus", "medium", "fast")

    def test_claude_command_uses_bypass_permissions(self) -> None:
        command, autonomy = MODULE.build_agent_command("claude", "opus", "high")

        self.assertEqual(
            command,
            "claude --permission-mode bypassPermissions --model opus --effort high",
        )
        self.assertEqual(autonomy["permission_mode"], "bypassPermissions")

    def test_provider_fields_reject_shell_syntax(self) -> None:
        with self.assertRaisesRegex(ValueError, "not shell syntax"):
            MODULE.build_agent_command("codex", "gpt-5.6; touch /tmp/no", None)


class OrcaResolutionTests(unittest.TestCase):
    def test_explicit_cli_command_wins(self) -> None:
        self.assertEqual(
            MODULE.resolve_orca_command({"ORCA_CLI_COMMAND": "/opt/orca cli"}, "Darwin"),
            ["/opt/orca", "cli"],
        )

    def test_linux_outside_managed_terminal_uses_orca_ide(self) -> None:
        self.assertEqual(MODULE.resolve_orca_command({}, "Linux"), ["orca-ide"])

    def test_linux_managed_terminal_uses_orca(self) -> None:
        self.assertEqual(
            MODULE.resolve_orca_command({"ORCA_TERMINAL_HANDLE": "term_current"}, "Linux"),
            ["orca"],
        )


class LaunchTests(unittest.TestCase):
    def successful_runner(self) -> FakeRunner:
        return FakeRunner(
            [
                response({"ok": True, "result": {"terminals": []}}),
                response(
                    {
                        "ok": True,
                        "result": {
                            "terminal": {
                                "handle": "term_123",
                                "worktreeId": "repo::/worktree/path",
                            }
                        },
                    }
                ),
                response(
                    {
                        "ok": True,
                        "result": {
                            "wait": {
                                "handle": "term_123",
                                "satisfied": True,
                                "status": "running",
                            }
                        },
                    }
                ),
                response(
                    {
                        "ok": True,
                        "result": {
                            "terminals": [
                                {
                                    "handle": "term_123",
                                    "worktreeId": "repo::/worktree/path",
                                    "agentIdentity": "codex",
                                }
                            ]
                        },
                    }
                ),
            ]
        )

    def test_success_returns_one_handle_without_claiming_prompt_delivery(self) -> None:
        runner = self.successful_runner()

        receipt = MODULE.launch_yolo_agent(
            worktree="id:repo::/worktree/path",
            agent="codex",
            orca_command=["orca"],
            runner=runner,
        )

        self.assertEqual(receipt["terminal_handle"], "term_123")
        self.assertEqual(receipt["runtime_worktree_id"], "repo::/worktree/path")
        self.assertEqual(receipt["prompt_delivery"], "not_attempted")
        self.assertEqual(len(runner.calls), 4)
        self.assertEqual(runner.calls[1][0].count("terminal"), 1)
        create_args = runner.calls[1][0]
        self.assertIn(
            'model_reasoning_effort="medium"',
            create_args[create_args.index("--command") + 1],
        )

    def test_transient_readiness_timeouts_resume_same_terminal(self) -> None:
        for timeout in (
            response({"ok": False, "error": {"code": "timeout"}}, returncode=1),
            response({"ok": False, "error": {"code": "timeout"}}),
            subprocess.TimeoutExpired(["orca", "terminal", "wait"], 60),
        ):
            with self.subTest(timeout=timeout):
                runner = self.successful_runner()
                runner.responses.insert(2, timeout)
                receipt = MODULE.launch_yolo_agent(
                    worktree="active", agent="codex", orca_command=["orca"], runner=runner,
                )
                self.assertTrue(receipt["ok"])
                self.assertEqual(receipt["readiness_attempts"], 2)
                self.assertEqual(receipt["prompt_delivery"], "not_attempted")
                self.assertEqual(runner.calls[2], runner.calls[3])
                self.assertLessEqual(runner.calls[2][1], 60)
                self.assertEqual(sum("create" in args for args, _ in runner.calls), 1)
                self.assertFalse(any("send" in args for args, _ in runner.calls))

    def test_repeated_readiness_timeout_is_bounded_and_preserves_handle(self) -> None:
        runner = self.successful_runner()
        runner.responses[2:] = [
            response({"ok": False, "error": {"code": "timeout"}}, returncode=1)
            for _ in range(3)
        ]
        with self.assertRaises(MODULE.LaunchFailure) as caught:
            MODULE.launch_yolo_agent(
                worktree="active", agent="codex", orca_command=["orca"], runner=runner,
            )
        receipt = MODULE._failure_receipt(caught.exception, worktree="active", agent="codex")
        self.assertEqual(receipt["terminal_handle"], "term_123")
        self.assertEqual(receipt["prompt_delivery"], "not_attempted")
        self.assertIn("Resume readiness", receipt["operator_action"])
        self.assertEqual(sum("wait" in args for args, _ in runner.calls), 3)
        self.assertEqual(sum("create" in args for args, _ in runner.calls), 1)

    def test_recovery_still_requires_correct_agent_ownership(self) -> None:
        runner = self.successful_runner()
        runner.responses.insert(2, response({"ok": False, "error": {"code": "timeout"}}))
        runner.responses[-1] = response({"ok": True, "result": {"terminals": [{
            "handle": "term_123", "worktreeId": "repo::/worktree/path", "agentIdentity": "claude",
        }]}})
        with self.assertRaisesRegex(MODULE.LaunchFailure, "requested agent identity"):
            MODULE.launch_yolo_agent(
                worktree="active", agent="codex", orca_command=["orca"], runner=runner,
            )

    def test_terminal_exit_after_timeout_stops_recovery(self) -> None:
        runner = self.successful_runner()
        runner.responses.insert(2, response({"ok": False, "error": {"code": "timeout"}}))
        runner.responses[3] = response({"ok": True, "result": {"wait": {
            "handle": "term_123", "satisfied": True, "status": "exited",
        }}})
        with self.assertRaisesRegex(MODULE.LaunchFailure, "not running"):
            MODULE.launch_yolo_agent(
                worktree="active", agent="codex", orca_command=["orca"], runner=runner,
            )
        self.assertEqual(len(runner.calls), 4)

    def test_create_failure_does_not_wait_or_retry(self) -> None:
        runner = FakeRunner(
            [
                response({"ok": True, "result": {"terminals": []}}),
                response({"ok": False, "error": "create denied"}),
                response({"ok": True, "result": {"terminals": []}}),
            ]
        )

        with self.assertRaises(MODULE.LaunchFailure) as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "terminal_create")
        self.assertIsNone(caught.exception.terminal_handle)
        self.assertEqual(caught.exception.created_state, "unknown")
        self.assertEqual(len(runner.calls), 3)

    def test_wait_failure_preserves_handle_without_relaunch(self) -> None:
        runner = self.successful_runner()
        runner.responses[2] = response({"ok": False, "error": "not ready"})

        with self.assertRaises(MODULE.LaunchFailure) as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="claude",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "tui_readiness")
        self.assertEqual(caught.exception.terminal_handle, "term_123")
        self.assertEqual(len(runner.calls), 3)

    def test_incomplete_create_receipt_recovers_created_handle(self) -> None:
        runner = FakeRunner(
            [
                response({"ok": True, "result": {"terminals": []}}),
                response(
                    {
                        "ok": True,
                        "result": {"terminal": {"worktreeId": "repo::/worktree/path"}},
                    }
                ),
                response(
                    {
                        "ok": True,
                        "result": {
                            "terminals": [
                                {"handle": "term_123", "worktreeId": "repo::/worktree/path"}
                            ]
                        },
                    }
                ),
            ]
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "recovered the sole") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.terminal_handle, "term_123")
        self.assertEqual(caught.exception.created_state, "preserved")
        self.assertEqual(len(runner.calls), 3)

    def test_create_timeout_recovers_created_handle_without_retry(self) -> None:
        runner = FakeRunner(
            [
                response({"ok": True, "result": {"terminals": []}}),
                subprocess.TimeoutExpired(["orca", "terminal", "create"], 60),
                response(
                    {
                        "ok": True,
                        "result": {
                            "terminals": [
                                {"handle": "term_123", "worktreeId": "repo::/worktree/path"}
                            ]
                        },
                    }
                ),
            ]
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "recovered the sole") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "terminal_create")
        self.assertEqual(caught.exception.terminal_handle, "term_123")
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(runner.calls[1][0].count("create"), 1)

    def test_failed_create_and_reconciliation_reports_unknown_state(self) -> None:
        runner = FakeRunner(
            [
                response({"ok": True, "result": {"terminals": []}}),
                subprocess.TimeoutExpired(["orca", "terminal", "create"], 60),
                subprocess.TimeoutExpired(["orca", "terminal", "list"], 60),
            ]
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "reconciliation failed") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="claude",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.created_state, "unknown")
        self.assertIsNone(caught.exception.terminal_handle)
        self.assertEqual(len(runner.calls), 3)

    def test_create_timeout_with_empty_inventory_remains_unknown(self) -> None:
        runner = FakeRunner(
            [
                response({"ok": True, "result": {"terminals": []}}),
                subprocess.TimeoutExpired(["orca", "terminal", "create"], 60),
                response({"ok": True, "result": {"terminals": []}}),
            ]
        )

        with self.assertRaises(MODULE.LaunchFailure) as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        receipt = MODULE._failure_receipt(
            caught.exception,
            worktree="active",
            agent="codex",
        )
        self.assertEqual(caught.exception.created_state, "unknown")
        self.assertEqual(receipt["created_state"], "unknown")
        self.assertIsNone(receipt["created_state_preserved"])
        self.assertEqual(len(runner.calls), 3)

    def test_mismatched_readiness_handle_fails_closed(self) -> None:
        runner = self.successful_runner()
        runner.responses[2] = response(
            {
                "ok": True,
                "result": {"wait": {"handle": "term_other", "satisfied": True}},
            }
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "another terminal"):
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

    def test_existing_terminal_refuses_launch(self) -> None:
        runner = FakeRunner(
            [
                response(
                    {
                        "ok": True,
                        "result": {"terminals": [{"handle": "term_existing"}]},
                    }
                )
            ]
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "already has a terminal") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "terminal_preflight")
        self.assertEqual(len(runner.calls), 1)

    def test_postflight_refuses_multiple_terminals(self) -> None:
        runner = self.successful_runner()
        runner.responses[3] = response(
            {
                "ok": True,
                "result": {
                    "terminals": [
                        {"handle": "term_123", "worktreeId": "repo::/worktree/path"},
                        {"handle": "term_other", "worktreeId": "repo::/worktree/path"},
                    ]
                },
            }
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "exactly the created") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "terminal_ownership")
        self.assertEqual(caught.exception.terminal_handle, "term_123")
        self.assertEqual(len(runner.calls), 4)

    def test_malformed_postflight_inventory_preserves_the_created_handle(self) -> None:
        runner = self.successful_runner()
        runner.responses[3] = response({"ok": True, "result": {}})

        with self.assertRaisesRegex(MODULE.LaunchFailure, "omitted the terminal inventory") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        receipt = MODULE._failure_receipt(
            caught.exception,
            worktree="active",
            agent="codex",
        )
        self.assertEqual(caught.exception.phase, "terminal_ownership")
        self.assertEqual(caught.exception.terminal_handle, "term_123")
        self.assertEqual(receipt["created_state"], "preserved")
        self.assertTrue(receipt["created_state_preserved"])
        self.assertIn("do not relaunch", receipt["operator_action"])

    def test_postflight_refuses_another_agent_identity(self) -> None:
        runner = self.successful_runner()
        runner.responses[3] = response(
            {
                "ok": True,
                "result": {
                    "terminals": [
                        {
                            "handle": "term_123",
                            "worktreeId": "repo::/worktree/path",
                            "agentIdentity": "claude",
                        }
                    ]
                },
            }
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "requested agent identity") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "terminal_ownership")
        self.assertEqual(caught.exception.terminal_handle, "term_123")

    def test_unsatisfied_readiness_fails_closed(self) -> None:
        runner = self.successful_runner()
        runner.responses[2] = response(
            {
                "ok": True,
                "result": {
                    "wait": {"handle": "term_123", "satisfied": False, "status": "running"}
                },
            }
        )

        with self.assertRaisesRegex(MODULE.LaunchFailure, "did not become ready"):
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(len(runner.calls), 3)

    def test_orca_timeout_fails_closed(self) -> None:
        runner = mock.Mock(side_effect=subprocess.TimeoutExpired(["orca"], 1))

        with self.assertRaisesRegex(MODULE.LaunchFailure, "timed out") as caught:
            MODULE.launch_yolo_agent(
                worktree="active",
                agent="codex",
                timeout_ms=1_000,
                orca_command=["orca"],
                runner=runner,
            )

        self.assertEqual(caught.exception.phase, "terminal_preflight")
        self.assertEqual(runner.call_count, 1)


class CliReceiptTests(unittest.TestCase):
    def test_input_error_returns_code_two_and_json_receipt(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = MODULE.main(["--worktree", " ", "--agent", "codex"])

        receipt = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["phase"], "input_validation")
        self.assertIsNone(receipt["terminal_handle"])
        self.assertEqual(receipt["created_state"], "none")
        self.assertFalse(receipt["created_state_preserved"])
        self.assertEqual(receipt["prompt_delivery"], "not_attempted")
        self.assertFalse(receipt["automatic_mutation_retry"])

    def test_launch_error_returns_code_one_and_preserves_handle(self) -> None:
        failure = MODULE.LaunchFailure("terminal_ownership", "ambiguous ownership", "term_123")
        output = io.StringIO()

        with mock.patch.object(MODULE, "launch_yolo_agent", side_effect=failure):
            with redirect_stdout(output):
                exit_code = MODULE.main(["--worktree", "active", "--agent", "claude"])

        receipt = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["phase"], "terminal_ownership")
        self.assertEqual(receipt["terminal_handle"], "term_123")
        self.assertEqual(receipt["created_state"], "preserved")
        self.assertTrue(receipt["created_state_preserved"])
        self.assertEqual(receipt["prompt_delivery"], "not_attempted")
        self.assertFalse(receipt["automatic_mutation_retry"])

    def test_unknown_create_state_is_not_reported_as_false(self) -> None:
        failure = MODULE.LaunchFailure(
            "terminal_create",
            "create outcome unknown",
            created_state="unknown",
        )

        receipt = MODULE._failure_receipt(failure, worktree="active", agent="codex")

        self.assertEqual(receipt["created_state"], "unknown")
        self.assertIsNone(receipt["created_state_preserved"])
        self.assertIn("Inspect", receipt["operator_action"])


if __name__ == "__main__":
    unittest.main()
