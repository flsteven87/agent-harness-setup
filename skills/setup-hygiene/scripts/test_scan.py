#!/usr/bin/env python3
"""Focused regression tests for the Setup Hygiene inventory."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("scan.py")
SPEC = importlib.util.spec_from_file_location("setup_hygiene_scan", MODULE_PATH)
assert SPEC and SPEC.loader
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)


class ScanTests(unittest.TestCase):
    def test_current_process_path_does_not_start_a_login_shell(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/one:/two:relative"}, clear=False):
            with mock.patch.object(subprocess, "run") as run:
                status, entries = scan.current_process_path()

        self.assertEqual(status, 0)
        self.assertEqual(entries, ["/one", "/two"])
        run.assert_not_called()

    def test_markdown_fragment_resolves_against_the_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "guide.md"
            target = home / "reference.md"
            source.write_text("[Reference](reference.md#details)\n", encoding="utf-8")
            target.write_text("# Details\n", encoding="utf-8")
            inventory = scan.Inventory(home)

            scan.scan_markdown_links(inventory, [source])

        self.assertFalse(
            any(record["check"] == "markdown-link" for record in inventory.records)
        )
        self.assertEqual(inventory.records[-1]["unresolved_candidates"], 0)

    def test_non_file_uri_is_not_treated_as_a_local_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "guide.md"
            source.write_text("[Skill](skill://setup-hygiene)\n", encoding="utf-8")
            inventory = scan.Inventory(home)

            scan.scan_markdown_links(inventory, [source])

        self.assertEqual(inventory.records[-1]["unresolved_candidates"], 0)

    def test_codex_route_pin_requires_chatgpt_login(self) -> None:
        cases = [('forced_login_method = "chatgpt"\n', "clean"), ('forced_login_method = "api"\n', "review"),
                 ('model = "gpt-6.1-sol"\n', "review"), ("not = [toml", "blocked")]
        for text, status in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                (home / ".codex").mkdir()
                (home / ".codex" / "config.toml").write_text(text, encoding="utf-8")
                inventory = scan.Inventory(home)

                scan.scan_codex_route_pin(inventory)

                self.assertEqual(inventory.records[-1]["check"], "codex-route-pin")
                self.assertEqual(inventory.records[-1]["status"], status)

    def test_orca_codex_home_is_inferred_from_the_resolved_binary(self) -> None:
        binary = Path(
            "/Users/example/Library/Application Support/orca/codex-accounts/"
            "account-id/home/packages/standalone/current/bin/codex"
        )

        self.assertEqual(
            scan.infer_orca_codex_home(binary),
            Path(
                "/Users/example/Library/Application Support/orca/codex-accounts/"
                "account-id/home"
            ),
        )

    def test_doctor_summary_omits_details_and_remediation(self) -> None:
        report = {
            "schemaVersion": 1,
            "codexVersion": "0.150.1",
            "overallStatus": "warning",
            "checks": {
                "config.load": {
                    "id": "config.load",
                    "category": "config",
                    "status": "ok",
                    "summary": "config loaded",
                    "details": {"auth file": "/secret/auth.json"},
                    "remediation": "use token secret-value",
                    "durationMs": 3,
                },
                "state.inventory": {
                    "id": "state.inventory",
                    "category": "state",
                    "status": "warning",
                    "summary": "stale rollout rows",
                    "details": {"path": "/secret/session.jsonl"},
                    "remediation": None,
                    "durationMs": 8,
                },
            },
        }

        summary = scan.summarize_doctor(report)
        rendered = json.dumps(summary)

        self.assertEqual(summary["warning_checks"][0]["id"], "state.inventory")
        self.assertEqual(summary["status_counts"], {"ok": 1, "warning": 1})
        self.assertNotIn("/secret", rendered)
        self.assertNotIn("secret-value", rendered)

    def test_state_freshness_reports_digest_drift_and_age(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            state = home / ".local" / "state" / "setup-hygiene" / "state.md"
            state.parent.mkdir(parents=True)
            state.write_text(
                "# Setup Hygiene State\n\n"
                "- Last run: 2026-08-20T09:00:00+0800\n"
                "- Instruction digest: `old-digest`\n",
                encoding="utf-8",
            )
            inventory = scan.Inventory(home)

            scan.scan_state_freshness(
                inventory,
                "new-digest",
                max_age_hours=36,
                now=datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc),
            )

        record = inventory.records[-1]
        self.assertEqual(record["status"], "review")
        self.assertFalse(record["digest_matches"])
        self.assertGreater(record["age_hours"], 36)

    def test_document_output_reconciles_status_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = scan.Inventory(Path(directory))
            inventory.emit("skills", "inventory", "clean")
            inventory.emit("runtime", "doctor", "handoff")

            document = inventory.document(
                generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc)
            )

        self.assertEqual(document["schema_version"], scan.SCHEMA_VERSION)
        self.assertEqual(document["summary"]["records"], 2)
        self.assertEqual(
            document["summary"]["status_counts"],
            {"clean": 1, "handoff": 1},
        )
        self.assertEqual(document["summary"]["attention_records"], 1)

    def test_missing_state_is_a_review_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = scan.Inventory(Path(directory))
            scan.scan_state_freshness(inventory, "current-digest", max_age_hours=36)

        self.assertEqual(inventory.records[0]["status"], "review")
        self.assertEqual(inventory.records[0]["observed"], "state file is missing")

    def test_current_state_is_clean_before_routine_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            state = home / ".local/state/setup-hygiene/state.md"
            state.parent.mkdir(parents=True)
            state.write_text(
                "- Last run: 2026-08-27T00:00:00+00:00\n"
                f"- Instruction digest: `{'a' * 64}`\n", encoding="utf-8",
            )
            inventory = scan.Inventory(home)
            scan.scan_state_freshness(
                inventory, "a" * 64, max_age_hours=36,
                now=datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(inventory.records[0]["status"], "clean")

    def test_explicit_nonstable_feature_is_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            codex_home = home / ".codex"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text(
                "[features]\nexperimental_thing = true\nstable_thing = true\n",
                encoding="utf-8",
            )
            inventory = scan.Inventory(home)
            listing = (
                "experimental_thing  under development  true\n"
                "stable_thing        stable             true\n"
            )

            scan.scan_feature_maturity(inventory, [codex_home], listing)

        record = inventory.records[-1]
        self.assertEqual(record["status"], "review")
        self.assertEqual(record["explicit_nonstable"], ["experimental_thing"])

    def test_orca_scheduler_summary_keeps_metadata_not_prompts(self) -> None:
        payload = {
            "ok": True,
            "result": {
                "automations": [
                    {
                        "id": "automation-id",
                        "name": "每日 Setup Hygiene",
                        "prompt": "secret-like long prompt",
                        "enabled": True,
                        "schedulerOwner": "local_host_service",
                        "rrule": "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
                    }
                ]
            },
        }

        entries = scan.scheduler_entries_from_orca(payload)
        rendered = json.dumps(entries)

        self.assertEqual(entries[0]["purpose"], "setup-hygiene")
        self.assertEqual(entries[0]["owner"], "local_host_service")
        self.assertNotIn("secret-like", rendered)

    def test_scheduler_conflict_requires_two_enabled_owners(self) -> None:
        entries = [
            {"purpose": "setup-hygiene", "enabled": True},
            {"purpose": "setup-hygiene", "enabled": False},
            {"purpose": "daily-dev-update", "enabled": True},
        ]
        self.assertEqual(scan.scheduler_conflicts(entries), {})

        entries.append({"purpose": "setup-hygiene", "enabled": True})
        self.assertEqual(scan.scheduler_conflicts(entries), {"setup-hygiene": 2})

    def test_launchd_disabled_parser_accepts_boolean_and_word_forms(self) -> None:
        output = (
            '"one" => true\n'
            '"two" => disabled\n'
            '"three" => false\n'
            '"four" => enabled\n'
        )

        self.assertEqual(
            scan.parse_launchd_disabled(output),
            {"one": True, "two": True, "three": False, "four": False},
        )

    def test_active_doctor_scope_selects_orca_runtime_home(self) -> None:
        default = Path("/Users/example/.codex")
        active = Path(
            "/Users/example/Library/Application Support/orca/codex-accounts/"
            "account-id/home"
        )
        binary = active / "packages/standalone/current/bin/codex"

        self.assertEqual(
            scan.select_doctor_homes([default, active], str(binary), "active"),
            [active],
        )

    def test_active_scope_does_not_fall_back_to_environment_home(self) -> None:
        default = Path("/Users/example/.codex")
        configured = Path("/Users/example/other-home")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(configured)}):
            self.assertEqual(
                scan.select_doctor_homes([default, configured], "/usr/bin/codex", "active"),
                [],
            )

    def test_default_scope_ignores_environment_override(self) -> None:
        default = Path("/Users/example/.codex")
        configured = Path("/Users/example/other-home")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(configured)}):
            self.assertEqual(
                scan.select_doctor_homes([default, configured], "/usr/bin/codex", "default", default),
                [default],
            )

    def test_runtime_accounts_for_selected_missing_home_and_scope_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            default = home / ".codex"
            configured = home / "other-home"
            inventory = scan.Inventory(home)
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(configured)}):
                with mock.patch.object(scan.shutil, "which", return_value="/usr/bin/codex"):
                    with mock.patch.object(scan, "run_bounded", return_value=None) as run:
                        scan.scan_codex_runtime(inventory, timeout=1, doctor_scope="default")

        scope = next(r for r in inventory.records if r["check"] == "doctor-scope")
        doctor = next(r for r in inventory.records if r["check"] == "doctor")
        self.assertEqual(scope["homes"], ["~/.codex"])
        self.assertEqual(scope["excluded"], [{"home": "~/other-home", "reason": "outside requested doctor scope"}])
        self.assertEqual(doctor["home"], "~/.codex")
        self.assertEqual(doctor["status"], "blocked")
        self.assertIn("absent", doctor["observed"])
        self.assertFalse(any("doctor" in call.args[0] for call in run.call_args_list))

    def test_missing_executable_accounts_for_each_selected_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = scan.Inventory(Path(directory))
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(scan.shutil, "which", return_value=None):
                    scan.scan_codex_runtime(inventory, timeout=1, doctor_scope="all")

        doctors = [r for r in inventory.records if r["check"] == "doctor"]
        self.assertEqual(len(doctors), 1)
        self.assertEqual(doctors[0]["home"], "~/.codex")
        self.assertEqual(doctors[0]["status"], "blocked")

    def test_unidentified_active_runtime_is_explicitly_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = scan.Inventory(Path(directory))
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(scan.shutil, "which", return_value="/usr/bin/codex"):
                    with mock.patch.object(scan, "run_bounded", return_value=None):
                        scan.scan_codex_runtime(inventory, timeout=1, doctor_scope="active")

        scope = next(r for r in inventory.records if r["check"] == "doctor-scope")
        self.assertEqual(scope["status"], "blocked")
        self.assertEqual(scope["homes"], [])
        self.assertEqual(scope["excluded"][0]["home"], "~/.codex")
        self.assertTrue(scope["discharge"])


if __name__ == "__main__":
    unittest.main()
