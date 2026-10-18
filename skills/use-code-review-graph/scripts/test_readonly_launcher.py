#!/usr/bin/env python3
"""Behavioral tests for the read-only MCP launcher seam."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sqlite3
import tempfile
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().with_name("code-review-graph-readonly")


def load_launcher():
    loader = importlib.machinery.SourceFileLoader("crg_readonly_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ReadonlyLauncherContractTest(unittest.TestCase):
    def test_reader_blocks_graph_writes_while_allowing_temp_pages(self) -> None:
        """`mode=ro` is the write boundary; a temp seed table must still work.

        Impact radius builds its seed set in a TEMP table, so a connection that
        cannot write temp pages serves a broken tool rather than a safer one.
        """
        module = load_launcher()
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "repo" / ".code-review-graph"
            data_dir.mkdir(parents=True)
            database = data_dir / "graph.db"
            seed = sqlite3.connect(database)
            seed.execute("CREATE TABLE nodes (qn TEXT PRIMARY KEY)")
            seed.execute("INSERT INTO nodes VALUES ('a')")
            seed.commit()
            seed.close()

            lock_path = Path(tmp) / "reader.lock"
            lock_path.touch()
            store = SimpleNamespace()
            with (
                mock.patch.object(
                    module, "open_worktree_reader_lock", return_value=open(lock_path)
                ),
                mock.patch.object(
                    module, "readonly_database", return_value=database.resolve()
                ),
            ):
                module.readonly_graph_store_init(store, database)

            connection = store._conn
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0], 1
                )
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM nodes")
                connection.execute("CREATE TEMP TABLE _impact_seeds (qn TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO _impact_seeds VALUES ('a')")
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM _impact_seeds").fetchone()[0],
                    1,
                )
                # Dropping `query_only` re-opened ATTACH and VACUUM INTO against
                # arbitrary writable paths; the attached-database cap closes both.
                escape = Path(tmp) / "escape.db"
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(f"ATTACH DATABASE '{escape}' AS x")
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(f"VACUUM main INTO '{escape}'")
                self.assertFalse(escape.exists())
            finally:
                module.readonly_graph_store_close(store)

    def test_cli_rejects_writer_capable_tools(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "serve", "--tools", "embed_graph_tool"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("refuses non-read-only tools", result.stderr)

    def test_cli_rejects_a_writer_tool_hidden_in_a_duplicate_option(self) -> None:
        result = subprocess.run(
            [
                str(SCRIPT),
                "serve",
                "--tools",
                "list_graph_stats_tool",
                "--tools=embed_graph_tool",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("embed_graph_tool", result.stderr)

    def test_cli_rejects_empty_tool_filters(self) -> None:
        for arguments in (["serve", "--tools="], ["serve", "--tools", ""]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [str(SCRIPT), *arguments],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("at least one read-only tool", result.stderr)

    def test_cli_rejects_argparse_abbreviations_and_non_stdio_modes(self) -> None:
        for argument in ("--to=embed_graph_tool", "--a", "--http"):
            with self.subTest(argument=argument):
                result = subprocess.run(
                    [str(SCRIPT), "serve", argument],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("unsupported serve argument", result.stderr)

    def test_argument_normalization_emits_one_validated_tool_filter(self) -> None:
        launcher = load_launcher()
        normalized = launcher.normalized_readonly_arguments(
            [
                "serve",
                "--tools",
                "query_graph_tool,list_graph_stats_tool",
                "--tools=query_graph_tool",
                ("--repo=" + str(Path.home()) + "/repo"),
            ]
        )
        self.assertEqual(
            normalized,
            [
                "serve",
                "--repo",
                str(Path.home() / 'repo'),
                "--tools",
                "query_graph_tool,list_graph_stats_tool",
            ],
        )

    def test_environment_tool_filter_is_removed_before_upstream_main(self) -> None:
        launcher = load_launcher()
        fake_cli = SimpleNamespace(main=lambda: 0)
        with (
            mock.patch.dict(os.environ, {"CRG_TOOLS": "embed_graph_tool"}),
            mock.patch.object(launcher, "install_readonly_patches"),
            mock.patch.dict(
                "sys.modules", {"code_review_graph.cli": fake_cli}
            ),
            mock.patch.object(
                launcher.sys, "argv", [str(SCRIPT), "serve"]
            ),
        ):
            self.assertEqual(launcher.main(), 0)
            self.assertNotIn("CRG_TOOLS", os.environ)
            self.assertEqual(launcher.sys.argv[1], "serve")
            self.assertEqual(launcher.sys.argv[2], "--tools")
            self.assertEqual(
                set(launcher.sys.argv[3].split(",")), set(launcher.READONLY_TOOLS)
            )

    def test_locked_database_resolution_passes_a_path_to_locked_validator(self) -> None:
        launcher = load_launcher()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            repo = Path(temporary) / "repo"
            database = repo / ".code-review-graph" / "graph.db"
            database.parent.mkdir(parents=True)
            database.touch()

            def inspect_under_lock(path):
                self.assertIsInstance(path, Path)
                return {"managed": True, "usable": True, "reason": "ready"}

            lifecycle = SimpleNamespace(inspect_under_lock=inspect_under_lock)
            with mock.patch.object(
                launcher, "load_lifecycle", return_value=lifecycle
            ):
                resolved = launcher.readonly_database(repo, lock_held=True)
            self.assertEqual(resolved, database.resolve())

    def test_database_resolution_uses_the_lifecycle_verdict_only(self) -> None:
        launcher = load_launcher()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            repo = Path(temporary) / "repo"
            database = repo / ".code-review-graph" / "graph.db"
            database.parent.mkdir(parents=True)
            database.touch()
            lifecycle = SimpleNamespace(
                inspect=lambda path: {
                    "repo": str(repo),
                    "managed": True,
                    "usable": True,
                    "reason": "graph matches the current worktree state",
                }
            )

            with mock.patch.object(
                launcher, "load_lifecycle", return_value=lifecycle
            ):
                resolved = launcher.readonly_database(repo)

            self.assertEqual(resolved, database.resolve())

    def test_database_resolution_rejects_the_same_reason_as_lifecycle(self) -> None:
        launcher = load_launcher()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            lifecycle = SimpleNamespace(
                inspect=lambda path: {
                    "repo": str(repo),
                    "managed": True,
                    "usable": False,
                    "reason": "worktree changed after the last successful index",
                }
            )

            with mock.patch.object(
                launcher, "load_lifecycle", return_value=lifecycle
            ):
                with self.assertRaisesRegex(RuntimeError, "worktree changed"):
                    launcher.readonly_database(repo)

    def test_readonly_db_path_does_not_migrate_legacy_database_or_sidecars(self) -> None:
        launcher = load_launcher()
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            repo = Path(temporary) / "repo"
            database = repo / ".code-review-graph" / "graph.db"
            database.parent.mkdir(parents=True)
            database.touch()
            legacy = repo / ".code-review-graph.db"
            sidecar = repo / ".code-review-graph.db-wal"
            legacy.write_bytes(b"legacy")
            sidecar.write_bytes(b"sidecar")
            lifecycle = SimpleNamespace(
                inspect=lambda path: {"managed": True, "usable": True, "reason": "ready"}
            )
            with mock.patch.object(launcher, "load_lifecycle", return_value=lifecycle):
                resolved = launcher.readonly_db_path(repo)
            self.assertEqual(resolved, database.resolve())
            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertEqual(sidecar.read_bytes(), b"sidecar")

    def test_path_adapters_preserve_upstream_keyword_interfaces(self) -> None:
        """Upstream path-resolution options cannot bypass the read-only seam."""
        launcher = load_launcher()
        repo = (Path.home() / 'repo')
        database = repo / ".code-review-graph" / "graph.db"
        with mock.patch.object(
            launcher, "readonly_database", return_value=database
        ) as resolver:
            self.assertEqual(
                launcher.readonly_data_dir(repo, create=True), database.parent
            )
            self.assertEqual(
                launcher.readonly_data_dir(repo, create=False), database.parent
            )
            self.assertEqual(
                launcher.readonly_db_path(repo, read_only=True), database
            )
            self.assertEqual(
                launcher.readonly_db_path(repo, read_only=False), database
            )
        self.assertEqual(resolver.call_count, 4)


if __name__ == "__main__":
    unittest.main()
