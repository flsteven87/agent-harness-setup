#!/usr/bin/env python3
"""Regression tests for the cross-runtime session warehouse."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("insights.py")
SPEC = importlib.util.spec_from_file_location("session_insights", MODULE_PATH)
assert SPEC and SPEC.loader
insights = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = insights
SPEC.loader.exec_module(insights)

TS = "2026-09-28T10:00:00.000Z"


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def claude_records() -> list[dict]:
    base = {"timestamp": TS, "cwd": "/repo", "entrypoint": "cli"}
    return [
        {**base, "type": "user", "message": {"role": "user", "content": "<command-name>/ship</command-name>\n<command-args>now</command-args>"}},
        {**base, "type": "user", "isMeta": True, "message": {"role": "user", "content": [{"type": "text", "text": "Base directory for this skill: /skills/ship\n\n# Ship"}]}},
        {**base, "type": "assistant", "message": {"id": "m1", "model": "claude-opus-5-5", "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5}, "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat missing.txt"}},
        ]}},
        {**base, "type": "assistant", "message": {"id": "m1", "model": "claude-opus-5-5", "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5}, "content": [
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/a.py"}},
        ]}},
        {**base, "type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "cat: missing.txt: No such file or directory"},
            {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "0123456789"}, {"type": "image", "source": {}}]},
        ]}},
        {**base, "type": "user", "message": {"role": "user", "content": "[Request interrupted by user]"}},
        {**base, "type": "user", "message": {"role": "user", "content": "請繼續"}},
        {**base, "type": "assistant", "message": {"id": "m2", "model": "claude-opus-5-5", "usage": {"input_tokens": 1, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 179, "output_tokens": 7}, "content": [
            {"type": "text", "text": "done"},
        ]}},
        {**base, "type": "system", "subtype": "compact_boundary", "compactMetadata": {"trigger": "auto"}},
    ]


def codex_records() -> list[dict]:
    def item(body: dict) -> dict:
        return {"timestamp": TS, "type": "event_msg", "payload": {"type": "item_completed", "item": body}}

    return [
        {"timestamp": TS, "type": "session_meta", "payload": {"id": "01a0-codex", "cwd": "/repo", "source": "cli"}},
        {"timestamp": TS, "type": "turn_context", "payload": {"model": "gpt-6-astra"}},
        item({"type": "UserMessage", "content": [{"type": "text", "text": "fix the bug"}]}),
        item({"type": "CommandExecution", "command": ["/bin/zsh", "-lc", "pytest"], "status": "completed", "exit_code": 1, "stderr": "1 failed", "duration": {"secs": 2, "nanos": 500000000}}),
        {"timestamp": TS, "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 200, "total_tokens": 210}, "last_token_usage": {"input_tokens": 200}}}},
        {"timestamp": TS, "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 200, "total_tokens": 210}, "last_token_usage": {"input_tokens": 200}}}},
        item({"type": "CommandExecution", "command": ["/bin/zsh", "-lc", "ls"], "status": "completed", "exit_code": 0, "aggregated_output": "a\nb\n", "formatted_output": "a\nb"}),
        {"timestamp": TS, "type": "compacted", "payload": {"message": ""}},
        item({"type": "ContextCompaction"}),  # current rollouts record one compaction twice
        item({"type": "McpToolCall", "server": "linear", "tool": "get_issue", "status": "failed", "error": "unauthorized"}),
        {"timestamp": TS, "type": "response_item", "payload": {"type": "function_call", "name": "sleep", "arguments": "{\"seconds\":60}"}},
        {"timestamp": TS, "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 500, "cached_input_tokens": 400, "output_tokens": 50, "total_tokens": 550}, "last_token_usage": {"input_tokens": 300}}}},
        {"timestamp": TS, "type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
    ]


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_claude_session_keeps_human_prompts_errors_and_dedupes_usage(self) -> None:
        path = write_jsonl(self.root / "claude/-repo/s1.jsonl", claude_records())
        session = insights.parse_claude(path)

        self.assertEqual([p[1] for p in session.prompts], ["/ship now", "請繼續"])
        self.assertEqual(session.origin, "interactive")
        self.assertEqual((session.input_tokens, session.cache_write_tokens), (300, 20))
        self.assertEqual((session.api_calls, session.first_context, session.peak_context), (2, 100, 200))
        self.assertEqual([(t[1], t[3], t[7]) for t in session.tools], [("Bash", 1, 0), ("Read", 0, 1)])
        self.assertEqual(session.tools[1][6], 10)
        self.assertIn("No such file", session.tools[0][4])
        self.assertEqual(sorted(e[1] for e in session.events), ["compaction", "interrupt", "skill_load"])
        self.assertIn(("skill_load", "ship"), [(e[1], e[2]) for e in session.events])

    def test_claude_subagent_file_links_to_parent(self) -> None:
        path = write_jsonl(self.root / "claude/-repo/parent-id/subagents/agent-1.jsonl", claude_records())
        session = insights.parse_claude(path)

        self.assertEqual((session.origin, session.parent_id), ("subagent", "parent-id"))

    def test_codex_rollout_normalizes_items_into_the_shared_shape(self) -> None:
        path = write_jsonl(self.root / "codex/2026/09/28/rollout-x.jsonl", codex_records())
        session = insights.parse_codex(path)

        self.assertEqual((session.session_id, session.model), ("01a0-codex", "gpt-6-astra"))
        self.assertEqual([p[1] for p in session.prompts], ["fix the bug"])
        self.assertEqual(
            [(t[1], t[2], t[3]) for t in session.tools],
            [("shell", "pytest", 1), ("shell", "ls", 0), ("mcp:linear.get_issue", "", 1), ("sleep", '{"seconds":60}', 0)],
        )
        self.assertEqual(session.tools[0][5], 2500)
        self.assertEqual(session.tools[1][6], 3)
        self.assertEqual((session.api_calls, session.first_context, session.peak_context), (2, 200, 300))
        self.assertEqual((session.input_tokens, session.cached_tokens), (500, 400))
        self.assertEqual([e[1] for e in session.events], ["compaction", "interrupt"])

    def test_ingest_is_incremental_and_report_covers_both_agents(self) -> None:
        write_jsonl(self.root / "claude/-repo/s1.jsonl", claude_records())
        write_jsonl(self.root / "codex/2026/09/28/rollout-x.jsonl", codex_records())
        conn = insights.connect(self.root / "db/sessions.db")

        first = insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)
        second = insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)
        text = insights.report(conn, days=100000, limit=5)

        self.assertEqual((first["parsed"], second["parsed"], second["unchanged"]), (2, 0, 2))
        self.assertIn("| claude | interactive | 1 | 2 | 2 | 1 |", text)
        self.assertIn("| codex | interactive | 1 | 1 | 4 | 2 |", text)
        self.assertIn("1 of 2 human prompts", text)

    def test_ingest_reads_every_codex_root_once(self) -> None:
        write_jsonl(self.root / "codex/2026/09/28/rollout-x.jsonl", codex_records())
        orca = self.root / "orca/acct/home/sessions"
        records = codex_records()
        records[0] = {**records[0], "payload": {**records[0]["payload"], "id": "01a0-orca"}}
        write_jsonl(orca / "2026/09/28/rollout-y.jsonl", records)
        conn = insights.connect(self.root / "db/sessions.db")

        counts = insights.ingest(conn, self.root / "claude", [self.root / "codex", orca, orca], quiet=True)

        self.assertEqual(counts["parsed"], 2)
        self.assertEqual(
            [r[0] for r in conn.execute("SELECT session_id FROM sessions ORDER BY session_id")],
            ["01a0-codex", "01a0-orca"],
        )

    def test_default_codex_roots_include_every_orca_account_home(self) -> None:
        for account in ("a", "b"):
            (self.root / f"Library/Application Support/orca/codex-accounts/{account}/home/sessions").mkdir(parents=True)
        roots = insights.default_codex_roots(self.root)
        self.assertEqual(roots[0], self.root / ".codex/sessions")
        self.assertEqual([r.parts[-3] for r in roots[1:]], ["a", "b"])

    def test_v1_warehouse_migrates_in_place_and_keeps_pruned_sessions(self) -> None:
        db = self.root / "db/sessions.db"
        db.parent.mkdir(parents=True)
        old = insights.sqlite3.connect(db)
        old.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta VALUES ('schema', '1');
            CREATE TABLE files (path TEXT PRIMARY KEY, agent TEXT, size INTEGER, mtime REAL, session_id TEXT);
            INSERT INTO files VALUES ('/gone.jsonl', 'claude', 1, 1, 'pruned');
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY, agent TEXT, origin TEXT, parent_id TEXT,
              path TEXT, cwd TEXT, model TEXT, started_at TEXT, ended_at TEXT, prompts INTEGER,
              tool_calls INTEGER, tool_errors INTEGER, input_tokens INTEGER, cached_tokens INTEGER,
              output_tokens INTEGER, compactions INTEGER, interrupts INTEGER);
            INSERT INTO sessions (session_id, agent) VALUES ('pruned', 'claude');
            CREATE TABLE tool_calls (session_id TEXT, agent TEXT, ts TEXT, tool TEXT, detail TEXT,
              is_error INTEGER, error TEXT, duration_ms INTEGER);
            CREATE TABLE events (session_id TEXT, agent TEXT, ts TEXT, kind TEXT, detail TEXT);
        """)
        old.commit()
        old.close()
        write_jsonl(self.root / "claude/-repo/s1.jsonl", claude_records())

        conn = insights.connect(db)
        counts = insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)

        self.assertEqual(counts["parsed"], 1)
        self.assertEqual(conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0], str(insights.SCHEMA_VERSION))
        self.assertEqual(
            conn.execute("SELECT session_id, api_calls FROM sessions ORDER BY session_id").fetchall(),
            [("pruned", None), ("s1", 2)],
        )

    def test_v3_warehouse_recounts_doubled_codex_compactions_from_unchanged_rollouts(self) -> None:
        write_jsonl(self.root / "codex/2026/09/28/rollout-x.jsonl", codex_records())
        db = self.root / "db/sessions.db"
        conn = insights.connect(db)
        insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)
        conn.executescript("""
            UPDATE meta SET value='3' WHERE key='schema';
            UPDATE sessions SET compactions=2;
            INSERT INTO events SELECT * FROM events WHERE kind='compaction';
        """)
        conn.close()

        conn = insights.connect(db)
        first = insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)
        second = insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)

        self.assertEqual((first["parsed"], second["parsed"]), (1, 0))
        self.assertEqual(conn.execute("SELECT compactions FROM sessions").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='compaction'").fetchone()[0], 1)

    def test_endgame_marks_from_both_runtimes_feed_the_autonomy_section(self) -> None:
        base = {"timestamp": TS, "cwd": "/repo", "entrypoint": "cli"}
        contract = "ENDGAME CONTRACT\n- End state: x\n```text\nENDGAME: BLOCKED — an example\n```"
        write_jsonl(self.root / "claude/-repo/e1.jsonl", [
            {**base, "type": "user", "message": {"role": "user", "content": "<command-name>/endgame</command-name>\n<command-args>fix it</command-args>"}},
            {**base, "type": "assistant", "message": {"id": "a1", "content": [{"type": "text", "text": contract}]}},
            {**base, "type": "user", "message": {"role": "user", "content": "tenant 是什麼意思？"}},
            {**base, "type": "assistant", "message": {"id": "a2", "content": [{"type": "text", "text": "Fixed.\n\nENDGAME: DONE — 2 tests pass"}]}},
        ])
        agent_message = {"timestamp": TS, "type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "AgentMessage", "content": [{"type": "Text", "text": "**ENDGAME: BLOCKED — needs approval**"}]}}}
        write_jsonl(self.root / "codex/2026/09/28/rollout-e.jsonl", [
            {"timestamp": TS, "type": "session_meta", "payload": {"id": "codex-e", "cwd": "/repo", "source": "cli"}},
            {"timestamp": TS, "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "$endgame ship it"}]}}},
            agent_message,
        ])

        claude = insights.parse_claude(self.root / "claude/-repo/e1.jsonl")
        self.assertEqual([e[2] for e in claude.events if e[1] == "endgame"], ["contract", "DONE"])

        conn = insights.connect(self.root / "db/sessions.db")
        insights.ingest(conn, self.root / "claude", [self.root / "codex"], quiet=True)
        text = insights.report(conn, days=100000, limit=5)
        self.assertIn("| claude | printed a contract | 1 |", text)
        self.assertIn("| claude | last close DONE / BLOCKED / DROPPED / none | 1 / 0 / 0 / 0 |", text)
        self.assertIn("| codex | last close DONE / BLOCKED / DROPPED / none | 0 / 1 / 0 / 0 |", text)
        self.assertIn("33.3 (1 of 3)", text)

    def test_error_signature_strips_paths_and_numbers(self) -> None:
        self.assertEqual(
            insights.error_signature("exit 1: cat: /Users/x/a.txt: No such file (line 42)"),
            "cat: <path>: No such file (line <n>)",
        )

    def test_sql_rejects_writes(self) -> None:
        conn = insights.connect(self.root / "db/sessions.db")
        with self.assertRaises(SystemExit):
            insights.run_sql(conn, "DELETE FROM sessions")


if __name__ == "__main__":
    unittest.main()
