#!/usr/bin/env python3
"""Subscription routing, frozen prompt and runtime identity regression tests."""
from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("consult", Path(__file__).with_name("consult.py"))
assert SPEC and SPEC.loader
consult = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = consult
SPEC.loader.exec_module(consult)
MODEL = "claude-opus-5-5"
MODEL_1M = MODEL + "[1m]"
AUTH = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}


def stream(answer="VERDICT: AGREE\n", actual=MODEL, assistant_model=None, usage_model=None):
    return "\n".join(json.dumps(e) for e in [
        {"type": "system", "subtype": "init", "model": actual, "apiKeySource": "none",
         "permissionMode": "plan", "tools": ["Read", "Grep", "Glob"]},
        {"type": "assistant", "message": {"model": assistant_model or actual}},
        {"type": "result", "result": answer, "modelUsage": {usage_model or actual: {}}},
    ])


class ConsultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.brief = self.root / "brief.md"
        self.brief.write_text("--- frozen candidate; verify its identity")
        self.out = self.root / "nested/answer.txt"
        self.calls = []
        self.stdout = stream()
        self.auth = AUTH.copy()
        self.login = "Logged in using ChatGPT"
        self.stderr = "model: gpt-6.1-sol\nprovider: openai\nsandbox: read-only\nreasoning effort: high\n"
        self.returncode = 0
        self.config = patch.object(consult, "load_config", return_value={})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(self.tmp.cleanup)

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[:3] == ["claude", "auth", "status"]:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.auth), "")
        if command[:3] == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, "", self.login)
        if command[:2] == ["codex", "exec"]:
            self.out.write_text("VERDICT: AGREE\n")
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)

    def run_consult(self, to="claude", **kwargs):
        return consult.consult(to, self.root, self.brief, self.out, 60, self.runner,
                               model=MODEL if to == "claude" else "gpt-6.1-sol",
                               effort="high", environ=kwargs.pop("environ", {}), **kwargs)

    def test_claude_subscription_identity_and_prompt_receipt(self):
        receipt = self.run_consult()
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["model_resolved"], MODEL)
        self.assertEqual(receipt["inference_route"], "claude_subscription")
        self.assertTrue(receipt["model_verified"])
        self.assertFalse(receipt["effort_verified"])
        self.assertEqual(self.out.read_text(), "VERDICT: AGREE\n")
        command, kwargs = self.calls[-1]
        self.assertIn("--safe-mode", command)
        self.assertEqual(command[command.index("--permission-mode") + 1], "plan")
        self.assertEqual(command[command.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(command[command.index("--model") + 1], MODEL)
        self.assertTrue(kwargs["input"].startswith(self.brief.read_text()))
        self.assertIn(consult.RESPONSE_FORMAT, kwargs["input"])
        self.assertEqual(len(receipt["brief_sha256"]), 64)

    def test_all_routing_overrides_block_before_inference_without_values(self):
        for to, names in [("claude", consult.CLAUDE_ROUTE_ENV),
                          ("codex", consult.CODEX_ROUTE_ENV | {"AZURE_OPENAI_ENDPOINT"})]:
            for name in sorted(names):
              with self.subTest(to=to, name=name):
                  self.calls.clear()
                  receipt = self.run_consult(to, environ={name: "private-value"})
                  self.assertEqual(receipt["status"], "failed")
                  self.assertEqual(self.calls, [])
                  self.assertNotIn("private-value", str(receipt))

    def test_api_login_is_not_a_subscription(self):
        for field, value in [("authMethod", "api_key"), ("apiProvider", "bedrock"),
                             ("loggedIn", False), ("subscriptionType", None)]:
            with self.subTest(field=field):
                self.auth = {**AUTH, field: value}
                self.calls.clear()
                self.assertEqual(self.run_consult()["status"], "failed")
                self.assertEqual(len(self.calls), 1)

    def test_every_claude_model_evidence_must_match(self):
        for data in [stream(actual="claude-sonnet-5-5"), stream(assistant_model="claude-sonnet-5-5"),
                     stream(usage_model="claude-sonnet-5-5")]:
            self.stdout = data
            self.assertEqual(self.run_consult()["status"], "failed")
            self.assertFalse(self.out.exists())

    def test_1m_context_suffix_matches_its_bare_assistant_model(self):
        # Real CLI shape: init and usage carry [1m]; assistant messages report the bare ID.
        self.stdout = stream(actual=MODEL_1M, assistant_model=MODEL)
        receipt = consult.consult("claude", self.root, self.brief, self.out, 60, self.runner,
                                  model=MODEL_1M, effort="high", environ={})
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["model_resolved"], MODEL_1M)
        for data in [stream(actual=MODEL_1M, assistant_model="claude-sonnet-5-5"),
                     stream(actual=MODEL_1M, assistant_model=MODEL, usage_model=MODEL),
                     stream(actual=MODEL)]:
            with self.subTest(data=data[:60]):
                self.stdout = data
                self.assertEqual(consult.consult("claude", self.root, self.brief, self.out, 60, self.runner,
                                                 model=MODEL_1M, effort="high", environ={})["status"], "failed")

    def test_bad_metadata_and_echoed_verdict_fail(self):
        cases = ["not JSON", "{}", "[]", stream("VERDICT: AGREE | PARTIAL | DISAGREE\n"),
                 stream("VERDICT: AGREE\nVERDICT: DISAGREE\n"), stream("Looks fine"),
                 stream().replace('"plan"', '"auto"'), stream().replace('"none"', '"api_key"'),
                 stream().replace('"Glob"', '"Bash"')]
        for data in cases:
            with self.subTest(data=data[:30]):
                self.stdout = data
                self.assertEqual(self.run_consult()["status"], "failed")
                self.assertFalse(self.out.exists())

    def test_preamble_is_allowed_but_single_verdict_is_required(self):
        self.stdout = stream("Reviewed.\n\nVERDICT: PARTIAL\n")
        self.assertEqual(self.run_consult()["status"], "ok")

    def test_failure_removes_stale_answer(self):
        self.out.parent.mkdir()
        self.out.write_text("VERDICT: AGREE\nstale")
        self.returncode = 1
        self.assertEqual(self.run_consult()["status"], "failed")
        self.assertFalse(self.out.exists())

    def test_codex_subscription_header_pins_model_and_effort(self):
        receipt = self.run_consult("codex")
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["inference_route"], "chatgpt_subscription")
        command = self.calls[-1][0]
        self.assertEqual(command[:4], ["codex", "exec", "--sandbox", "read-only"])
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertEqual(command[-1], "-")
        self.assertTrue(receipt["effort_verified"])

    def test_codex_api_login_and_runtime_mismatch_fail(self):
        self.login = "Logged in using an API key"
        self.assertEqual(self.run_consult("codex")["status"], "failed")
        self.login = "Logged in using ChatGPT"
        for data in ["", self.stderr.replace("openai", "custom"),
                     self.stderr.replace("gpt-6.1-sol", "gpt-6-sol"),
                     self.stderr.replace("high", "medium"), self.stderr.replace("read-only", "danger-full-access")]:
            self.stderr = data
            self.assertEqual(self.run_consult("codex")["status"], "failed")
            self.assertFalse(self.out.exists())

    def test_defaults_are_pinned_and_named_claude_alias_is_rejected(self):
        self.stdout = stream(actual=MODEL_1M, assistant_model=MODEL)
        with patch.object(consult, "load_config", return_value={"model": "opus[1m]", "effortLevel": "medium"}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60, self.runner, environ={})
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["model_requested"], "opus[1m]")
        self.assertEqual(receipt["effort_requested"], "medium")
        self.assertEqual(receipt["model_resolved"], MODEL_1M)
        receipt = consult.consult("claude", self.root, self.brief, self.out, 60, self.runner,
                                  model="opus", environ={})
        self.assertEqual(receipt["status"], "failed")

    def test_no_model_is_a_preflight_failure(self):
        self.assertEqual(consult.consult("claude", self.root, self.brief, self.out, 60,
                                        self.runner, environ={})["status"], "failed")
        self.assertEqual(self.calls, [])

    def test_timeout_and_missing_cli_are_named(self):
        for error, status in [(subprocess.TimeoutExpired("claude", 1), "timeout"),
                              (FileNotFoundError(), "missing_cli")]:
            with patch.object(self, "runner", side_effect=error):
                self.assertEqual(self.run_consult()["status"], status)

    def test_colliding_output_preserves_frozen_input(self):
        original = self.brief.read_bytes()
        aliases = [self.brief, self.root / "symlink.txt", self.root / "hardlink.txt"]
        aliases[1].symlink_to(self.brief)
        import os
        os.link(self.brief, aliases[2])
        for alias in aliases:
            receipt = consult.consult("claude", self.root, self.brief, alias, 60, self.runner,
                                      model=MODEL, effort="high", environ={})
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(self.brief.read_bytes(), original)
            self.assertEqual(self.calls, [])

    def test_nonobject_auth_json_is_a_failed_receipt(self):
        for data in [[], None, "unexpected"]:
            self.auth = data
            self.calls.clear()
            self.assertEqual(self.run_consult()["status"], "failed")
            self.assertEqual(len(self.calls), 1)

    def test_missing_brief_returns_receipt_and_preserves_unowned_output(self):
        self.out.parent.mkdir()
        self.out.write_text("existing output")
        self.brief.unlink()
        self.assertEqual(self.run_consult()["status"], "missing_cli")
        self.assertEqual(self.out.read_text(), "existing output")
        self.assertEqual(self.calls, [])

    def test_auxiliary_usage_does_not_substitute_the_review_model(self):
        records = [json.loads(line) for line in stream().splitlines()]
        records[-1]["modelUsage"]["claude-haiku-4-5"] = {}
        self.stdout = "\n".join(json.dumps(e) for e in records)
        receipt = self.run_consult()
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["additional_usage_models"], ["claude-haiku-4-5"])
        self.assertEqual(receipt["model_resolved"], MODEL)

    def test_configured_alias_cannot_resolve_to_another_family(self):
        self.stdout = stream(actual="claude-sonnet-5-5")
        with patch.object(consult, "load_config", return_value={"model": "opus[1m]"}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60,
                                      self.runner, environ={})
        self.assertEqual(receipt["status"], "failed")

    def test_main_preserves_model_timeout_and_failure_exit_status(self):
        argv = ["--to", "claude", "--brief", str(self.brief), "--out", str(self.out),
                "--model", MODEL, "--effort", "high"]
        with patch.object(consult, "consult", return_value={"status": "failed"}) as call:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(consult.main(argv), 1)
            self.assertEqual(call.call_args.args[4], 1800)
            self.assertEqual(call.call_args.kwargs["model"], MODEL)
            self.assertEqual(call.call_args.kwargs["effort"], "high")


class QuotaFallbackTests(unittest.TestCase):
    setUp = ConsultTests.setUp
    runner = ConsultTests.runner
    def fallback_runner(self, command, **kwargs):
        if command[:2] == ["claude", "-p"]:
            self.calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 1, json.dumps({
                "type": "result", "is_error": True, "result": "You've hit your weekly limit"}), "")
        return self.runner(command, **kwargs)

    def test_claude_quota_uses_fresh_codex_default_and_records_both_attempts(self):
        with patch.object(consult, "load_config", side_effect=lambda to, *args: {
                "model": MODEL if to == "claude" else "gpt-6.1-sol"}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60,
                                      self.fallback_runner, effort="high", environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["to"], "codex")
        self.assertEqual(receipt["requested_to"], "claude")
        self.assertTrue(receipt["fallback_used"])
        self.assertEqual([r["status"] for r in receipt["attempts"]], ["quota_exhausted", "ok"])
        self.assertEqual(receipt["attempts"][0]["brief_sha256"], receipt["brief_sha256"])
        inference = [c for c in self.calls if c[0][:2] in (["claude", "-p"], ["codex", "exec"])]
        self.assertEqual(len(inference), 2)
        self.assertEqual(inference[0][1]["input"], inference[1][1]["input"])
        self.assertIn("--ephemeral", inference[1][0])
        self.assertEqual(receipt["model_resolved"], "gpt-6.1-sol")

    def test_codex_quota_switches_to_claude_even_when_error_exit_is_zero(self):
        def runner(command, **kwargs):
            if command[:2] == ["codex", "exec"]:
                self.calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "", "ERROR: You've hit your usage limit.")
            return self.runner(command, **kwargs)
        with patch.object(consult, "load_config", side_effect=lambda to, *args: {
                "model": MODEL if to == "claude" else "gpt-6.1-sol"}):
            receipt = consult.consult("codex", self.root, self.brief, self.out, 60, runner,
                                      effort="high", environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["to"], "claude")
        self.assertEqual(receipt["inference_route"], "claude_subscription")

    def test_both_exhausted_stop_after_two_calls_without_stale_answer(self):
        def runner(command, **kwargs):
            if command[:2] == ["codex", "exec"]:
                self.calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 1, "", "ERROR: usage_limit_reached")
            return self.fallback_runner(command, **kwargs)
        with patch.object(consult, "load_config", return_value={"model": "configured-default"}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60, runner,
                                      environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "quota_exhausted")
        self.assertEqual(len(receipt["attempts"]), 2)
        self.assertEqual(len(self.calls), 4)
        self.assertFalse(self.out.exists())

    def test_explicit_model_and_default_consult_do_not_fallback(self):
        for kwargs in [{"model": MODEL, "quota_fallback": True}, {}]:
            self.calls.clear()
            with patch.object(consult, "load_config", return_value={"model": MODEL}):
                receipt = consult.consult("claude", self.root, self.brief, self.out, 60,
                                          self.fallback_runner, environ={}, **kwargs)
            self.assertEqual(receipt["status"], "quota_exhausted")
            self.assertEqual(len(self.calls), 2)

    def test_nonquota_failures_never_switch(self):
        with patch.object(consult, "load_config", return_value={"model": MODEL}):
            for stdout in ["not JSON", stream(actual="claude-sonnet-5-5"), stream("No verdict"),
                           json.dumps({"type": "result", "is_error": True, "result": "authentication failed"}),
                           json.dumps({"type": "assistant", "error": "rate_limit"}),
                           json.dumps({"type": "result", "is_error": True, "result": "Rate limit exceeded; retry later"})]:
                self.stdout = stdout
                self.calls.clear()
                receipt = consult.consult("claude", self.root, self.brief, self.out, 60,
                                          self.runner, environ={}, quota_fallback=True)
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(len(self.calls), 2)

    def test_answer_and_nonerror_output_cannot_trigger_quota_fallback(self):
        self.assertFalse(consult.quota_error("claude", stream("You've hit your usage limit"), ""))
        self.assertFalse(consult.quota_error("codex", "ERROR: usage_limit_reached", "usage_limit_reached"))
        self.assertFalse(consult.quota_error("codex", "", "ERROR: 429 too many requests"))
        self.assertFalse(consult.quota_error("claude", "[]", ""))
        self.assertFalse(consult.quota_error("claude", json.dumps({
            "type": "assistant", "error": "rate_limit"}), ""))
        self.assertFalse(consult.quota_error("claude", json.dumps({
            "type": "result", "is_error": True, "result": "Rate limit exceeded; retry later"}), ""))
        self.assertTrue(consult.quota_error("claude", json.dumps({"type": "result", "is_error": True,
                         "errors": ["You've hit your weekly limit"]}), ""))

    def test_echoed_error_in_successful_codex_review_is_not_quota(self):
        self.stderr += "ERROR: usage_limit_reached\ntokens used\n2000\n"
        receipt = consult.consult("codex", self.root, self.brief, self.out, 60, self.runner,
                                  model="gpt-6.1-sol", effort="high", environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "ok")
        self.assertTrue(self.out.exists())
        # Even a final quoted ERROR cannot replace a valid verified answer.
        self.stderr += "ERROR: usage_limit_reached"
        receipt = consult.consult("codex", self.root, self.brief, self.out, 60, self.runner,
                                  model="gpt-6.1-sol", effort="high", environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "ok")

    def test_default_effort_is_preserved_on_fallback(self):
        with patch.object(consult, "load_config", side_effect=lambda to, *args: {
                "model": MODEL if to == "claude" else "gpt-6.1-sol", "effortLevel": "high",
                "model_reasoning_effort": "low"}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60,
                                      self.fallback_runner, environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["effort_requested"], "high")

    def test_fallback_preserves_subscription_guard(self):
        with patch.object(consult, "load_config", return_value={"model": MODEL}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60,
                                      self.fallback_runner, environ={"OPENAI_API_KEY": "secret"},
                                      quota_fallback=True)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.out.exists())
        self.assertNotIn("secret", str(receipt))

    def test_changed_brief_blocks_switch(self):
        def runner(command, **kwargs):
            result = self.fallback_runner(command, **kwargs)
            if command[:2] == ["claude", "-p"]:
                self.brief.write_text("changed")
            return result
        with patch.object(consult, "load_config", return_value={"model": MODEL}):
            receipt = consult.consult("claude", self.root, self.brief, self.out, 60, runner,
                                      environ={}, quota_fallback=True)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(len(self.calls), 2)


class ConfigurationTests(unittest.TestCase):
    def test_custom_codex_provider_blocks_and_active_home_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            cwd = Path(tmp) / "repo"
            home.mkdir(); cwd.mkdir()
            p = home / "config.toml"
            with patch.dict("os.environ", {}, clear=True):
                p.write_text('model = "gpt-6.1-sol"\n')
                self.assertEqual(consult.load_config("codex", cwd, {"CODEX_HOME": str(home)})["model"], "gpt-6.1-sol")
                p.write_text('model_provider = "proxy"\n')
                with self.assertRaises(ValueError):
                    consult.load_config("codex", cwd, {"CODEX_HOME": str(home)})
                p.write_text('model = "gpt-6.1-sol"\n')
                p.write_text('profile = "review"\n')
                with self.assertRaises(ValueError):
                    consult.load_config("codex", cwd, {"CODEX_HOME": str(home)})

    def test_active_home_and_trusted_project_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "orca-home"
            root = base / "repo"
            nested = root / "src"
            home.mkdir(); nested.mkdir(parents=True)
            (root / ".git").mkdir()
            (base / ".codex").mkdir()
            (base / ".codex/config.toml").write_text('model = "wrong-home-model"\n')
            (root / ".codex").mkdir()
            (root / ".codex/config.toml").write_text('model = "project-model"\nmodel_provider = "ignored-project-provider"\n')
            config = home / "config.toml"
            config.write_text('model = "active-home-model"\n')
            env = {"CODEX_HOME": str(home)}
            self.assertEqual(consult.load_config("codex", nested, env)["model"], "active-home-model")
            config.write_text('model = "active-home-model"\n[projects.' + json.dumps(str(root)) + ']\ntrust_level = "trusted"\n')
            self.assertEqual(consult.load_config("codex", nested, env)["model"], "project-model")
            self.assertNotIn("model_provider", consult.load_config("codex", nested, env))


if __name__ == "__main__":
    unittest.main()
