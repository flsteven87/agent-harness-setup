#!/usr/bin/env python3
"""Regression tests for the endgame Stop gate."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("stop_gate", Path(__file__).with_name("stop_gate.py"))
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

CONTRACT = "ENDGAME CONTRACT\n- End state: done.txt contains ok\n- Checks: `cat done.txt`"


def assistant(text: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


class StopGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_gate(self, records: list[dict], **extra: object) -> dict | None:
        self.path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return gate.decide({"transcript_path": str(self.path), **extra})

    def test_no_contract_lets_the_session_stop(self) -> None:
        self.assertIsNone(self.run_gate([user("hi"), assistant("hello")]))

    def test_open_contract_blocks_with_a_counted_reason(self) -> None:
        result = self.run_gate([user("/endgame x"), assistant(CONTRACT)])
        self.assertEqual(result["decision"], "block")
        self.assertIn("(1/25)", result["reason"])

    def test_close_in_last_assistant_message_wins_the_race_with_the_transcript(self) -> None:
        result = self.run_gate([assistant(CONTRACT)], last_assistant_message="ENDGAME: DONE — `cat done.txt` printed ok")
        self.assertIsNone(result)

    def test_each_terminal_state_closes_the_contract(self) -> None:
        for close in ("ENDGAME: DONE — ok", "**ENDGAME: BLOCKED** — deploy needs approval", "ENDGAME: DROPPED — user redirected"):
            self.assertIsNone(self.run_gate([assistant(CONTRACT), assistant("work\n" + close)]), close)

    def test_a_new_contract_after_a_closed_one_reopens_the_gate(self) -> None:
        records = [assistant(CONTRACT), assistant("ENDGAME: DONE — ok"), assistant("next\n" + CONTRACT)]
        self.assertEqual(self.run_gate(records)["decision"], "block")

    def test_running_background_tasks_defer_the_gate(self) -> None:
        self.assertIsNone(self.run_gate([assistant(CONTRACT)], background_tasks=[{"id": "b1"}]))

    def test_block_cap_releases_the_session_with_a_notice(self) -> None:
        records = [assistant(CONTRACT)] + [user(f"Stop hook feedback:\n{gate.BLOCK_TAG} open")] * gate.MAX_BLOCKS
        result = self.run_gate(records)
        self.assertNotIn("decision", result)
        self.assertIn("systemMessage", result)

    def test_blocks_before_a_reopened_contract_do_not_count(self) -> None:
        records = [assistant(CONTRACT)] + [user(f"{gate.BLOCK_TAG} open")] * 5 + [assistant("ENDGAME: DROPPED — x"), assistant(CONTRACT)]
        self.assertIn("(1/25)", self.run_gate(records)["reason"])

    def test_restating_an_open_contract_keeps_the_block_count(self) -> None:
        records = [assistant(CONTRACT)] + [assistant(CONTRACT), user(f"{gate.BLOCK_TAG} open")] * gate.MAX_BLOCKS
        self.assertNotIn("decision", self.run_gate(records, last_assistant_message=CONTRACT))

    def test_missing_transcript_lets_the_session_stop(self) -> None:
        self.assertIsNone(gate.decide({"transcript_path": "/nonexistent", "last_assistant_message": CONTRACT}))

    def test_contract_shown_in_a_code_fence_or_quote_opens_nothing(self) -> None:
        for text in (f"Template:\n```\n{CONTRACT}\n```\nfill it in", f"> {CONTRACT}"):
            self.assertIsNone(self.run_gate([assistant(text)]), text)

    def test_last_message_already_in_the_transcript_is_not_counted_twice(self) -> None:
        records = [assistant(CONTRACT), user(f"{gate.BLOCK_TAG} open")]
        self.assertIn("(2/25)", self.run_gate(records, last_assistant_message=CONTRACT)["reason"])

    def test_loading_the_skill_opens_work_without_a_printed_contract(self) -> None:
        load = {"type": "user", "isMeta": True, "message": {"role": "user", "content": [
            {"type": "text", "text": "Base directory for this skill: /Users/x/.claude/skills/endgame\n\n# Endgame"}]}}
        self.assertEqual(self.run_gate([user("/endgame fix it"), load, assistant("fixed")])["decision"], "block")
        self.assertIsNone(self.run_gate([load], last_assistant_message="ENDGAME: DONE — tests pass"))

    def test_other_skills_do_not_open_work(self) -> None:
        load = user("Base directory for this skill: /Users/x/.claude/skills/ship\n\n# Ship")
        self.assertIsNone(self.run_gate([load, assistant("shipped")]))


if __name__ == "__main__":
    unittest.main()
