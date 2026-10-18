#!/usr/bin/env python3
"""End-to-end CLI tests against an isolated control plane and real Git worktree."""

from __future__ import annotations

import json
import importlib.machinery
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LIFECYCLE = Path(__file__).resolve().with_name("crg-lifecycle")
PRODUCTION_CONTROL_DB = (Path.home() / '.code-review-graph/control.db')
READONLY = Path(__file__).resolve().with_name("code-review-graph-readonly")
ISOLATED_WRITER = Path(__file__).resolve().with_name("crg-isolated-build")


def load_lifecycle():
    loader = importlib.machinery.SourceFileLoader("crg_integration_lifecycle", str(LIFECYCLE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class LifecycleCliIntegrationTest(unittest.TestCase):
    def test_docs_only_update_advances_staged_graph_provenance(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "crg@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "CRG Test"],
                check=True,
            )
            (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"], check=True
            )
            base = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            stage = root / "stage"
            environment = {
                **os.environ,
                "CRG_TEST_MODE": "1",
                "CRG_CONTROL_ROOT": str(root / "control"),
                "CRG_PARSE_WORKERS": "1",
                "CRG_SERIAL_PARSE": "1",
            }
            subprocess.run(
                [str(ISOLATED_WRITER), "build", str(repo), str(stage)],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )

            (repo / "README.md").write_text("Documentation only.\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "docs"], check=True
            )
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            updated = subprocess.run(
                [str(ISOLATED_WRITER), "update", str(repo), str(stage), base],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
            connection = sqlite3.connect(stage / "graph.db")
            try:
                indexed_head = connection.execute(
                    "SELECT value FROM metadata WHERE key='git_head_sha'"
                ).fetchone()[0]
                original_hash = connection.execute(
                    "SELECT file_hash FROM nodes "
                    "WHERE file_path=? AND file_hash IS NOT NULL LIMIT 1",
                    (str(repo / "sample.py"),),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(indexed_head, head)

            (repo / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "source"], check=True
            )
            source_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            reparsed = subprocess.run(
                [str(ISOLATED_WRITER), "update", str(repo), str(stage), head],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(reparsed.returncode, 0, reparsed.stderr)
            connection = sqlite3.connect(stage / "graph.db")
            try:
                indexed_source_head = connection.execute(
                    "SELECT value FROM metadata WHERE key='git_head_sha'"
                ).fetchone()[0]
                updated_hash = connection.execute(
                    "SELECT file_hash FROM nodes "
                    "WHERE file_path=? AND file_hash IS NOT NULL LIMIT 1",
                    (str(repo / "sample.py"),),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(indexed_source_head, source_head)
            self.assertNotEqual(updated_hash, original_hash)

    def test_first_enqueues_are_atomic_across_processes(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "crg@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "CRG Test"],
                check=True,
            )
            (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"], check=True
            )
            control = root / "control"
            environment = {
                **os.environ,
                "CRG_TEST_MODE": "1",
                "CRG_USER_ROOT": str(root),
                "CRG_CONTROL_ROOT": str(control),
                "CRG_LIFECYCLE_NO_KICK": "1",
            }
            processes = [
                subprocess.Popen(
                    [
                        str(LIFECYCLE),
                        "enqueue",
                        str(repo),
                        "git:post-commit",
                        "--no-kick",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                )
                for _ in range(12)
            ]
            failures = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                if process.returncode != 0:
                    failures.append((process.returncode, stdout, stderr))
            self.assertEqual(failures, [])

            connection = sqlite3.connect(control / "control.db")
            try:
                generation = connection.execute(
                    "SELECT generation FROM work_items WHERE repo=?", (str(repo),)
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(generation, 12)

    def test_attach_and_inspect_are_isolated_and_lazy(self) -> None:
        production_mtime = (
            PRODUCTION_CONTROL_DB.stat().st_mtime_ns
            if PRODUCTION_CONTROL_DB.exists()
            else None
        )
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "crg@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "CRG Test"],
                check=True,
            )
            (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"], check=True
            )
            control = root / "control"
            environment = {
                **os.environ,
                "CRG_TEST_MODE": "1",
                "CRG_USER_ROOT": str(root),
                "CRG_CONTROL_ROOT": str(control),
                "CRG_LIFECYCLE_NO_KICK": "1",
            }

            attached = subprocess.run(
                [
                    str(LIFECYCLE),
                    "attach",
                    str(repo),
                    "--orca-instance-id",
                    "integration-instance",
                ],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )
            entry = json.loads(attached.stdout.strip().splitlines()[-1])
            self.assertEqual(entry["state"], "dormant")
            self.assertEqual(entry["orca_instance_id"], "integration-instance")
            connection = sqlite3.connect(control / "control.db")
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
                    0,
                )
            finally:
                connection.close()

            inspected = subprocess.run(
                [str(LIFECYCLE), "inspect", str(repo), "--json"],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            result = json.loads(inspected.stdout)
            self.assertEqual(inspected.returncode, 1)
            self.assertTrue(result["managed"])
            self.assertFalse(result["usable"])
            self.assertIn("dormant", result["reason"])
            self.assertFalse((repo / ".code-review-graph").exists())

        if production_mtime is not None:
            self.assertEqual(PRODUCTION_CONTROL_DB.stat().st_mtime_ns, production_mtime)

    def test_cli_and_mcp_launcher_share_one_live_usability_verdict(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "crg@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "CRG Test"],
                check=True,
            )
            source = repo / "sample.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "sample.py"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"], check=True
            )
            control = root / "control"
            environment = {
                **os.environ,
                "CRG_TEST_MODE": "1",
                "CRG_USER_ROOT": str(root),
                "CRG_CONTROL_ROOT": str(control),
                "CRG_WORKTREE_LOCK_DIR": str(control / "locks"),
                "CRG_LIFECYCLE_BIN": str(LIFECYCLE),
                "CRG_LIFECYCLE_NO_KICK": "1",
                "CRG_BIN": str(Path.home() / '.local/bin/code-review-graph'),
                "CRG_PYTHON": (
                    str(Path.home() / '.local/share/uv/tools/code-review-graph/bin/python')
                ),
            }
            subprocess.run(
                [str(LIFECYCLE), "attach", str(repo)],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

            database = repo / ".code-review-graph" / "graph.db"
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            # The installed CRG writes the fixture so its schema tracks upstream.
            fixture = f"""
from code_review_graph.graph import GraphStore
from code_review_graph.parser import EdgeInfo, NodeInfo
store = GraphStore({str(database)!r})
store.upsert_node(NodeInfo('File', 'sample.py', 'sample.py', 1, 1, 'python'))
store.upsert_node(NodeInfo('Function', 'value', 'sample.py', 1, 1, 'python'))
store.upsert_edge(EdgeInfo('CALLS', 'sample.py', 'sample.py::value', 'sample.py', 1))
store.commit()
for key, value in (
    ('last_updated', '2026-08-13T00:00:00+00:00'),
    ('git_branch', 'main'),
    ('git_head_sha', {head!r}),
):
    store.set_metadata(key, value)
store.close()
"""
            subprocess.run(
                [environment["CRG_PYTHON"], "-c", fixture],
                capture_output=True,
                text=True,
                check=True,
            )

            lifecycle = load_lifecycle()
            lifecycle.USER_ROOT = root
            lifecycle.CONTROL_ROOT = control
            lifecycle.CONTROL_DB_PATH = control / "control.db"
            lifecycle.WORKTREE_LOCK_DIR = control / "locks"
            lifecycle.CRG_BIN = Path(environment["CRG_BIN"])
            lifecycle.CRG_PYTHON = Path(environment["CRG_PYTHON"])
            snapshot = lifecycle.workspace_snapshot(repo)
            entry = lifecycle.lifecycle_metadata(repo, snapshot)
            lifecycle.update_state_entry(str(repo), entry)

            healthy = subprocess.run(
                [str(LIFECYCLE), "inspect", str(repo), "--json"],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )
            healthy_result = json.loads(healthy.stdout)
            self.assertTrue(healthy_result["usable"])

            probe = f"""
import importlib.machinery
import importlib.util
from pathlib import Path
loader = importlib.machinery.SourceFileLoader('crg_reader_probe', {str(READONLY)!r})
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
print(module.readonly_database(Path({str(repo)!r})))
"""
            reader = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )
            self.assertEqual(reader.stdout.strip(), str(database))

            before_mcp = database.stat().st_mtime_ns
            mcp_probe = f"""
import anyio
import os
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
async def main():
    environment = dict(os.environ)
    environment['CRG_TOOLS'] = 'embed_graph_tool'
    params = StdioServerParameters(
        command={str(READONLY)!r},
        args=['serve'],
        cwd={str(repo)!r},
        env=environment,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {{tool.name for tool in tools.tools}}
            expected = {set((
                "get_minimal_context_tool",
                "query_graph_tool",
                "get_impact_radius_tool",
                "get_review_context_tool",
                "detect_changes_tool",
                "get_architecture_overview_tool",
                "list_graph_stats_tool",
            ))!r}
            if names != expected:
                raise RuntimeError(f'unsafe tool list: {{sorted(names)}}')
            result = await session.call_tool(
                'list_graph_stats_tool', {{'repo_root': {str(repo)!r}}}
            )
            if result.isError:
                raise RuntimeError(result.content)
            result = await session.call_tool(
                'get_minimal_context_tool',
                {{
                    'repo_root': {str(repo)!r},
                    'task': 'read-only adapter smoke test',
                    'base': 'HEAD',
                }},
            )
            if result.isError:
                raise RuntimeError(result.content)
anyio.run(main)
"""
            mcp_result = subprocess.run(
                [environment["CRG_PYTHON"], "-c", mcp_probe],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(mcp_result.returncode, 0, mcp_result.stderr)
            self.assertEqual(database.stat().st_mtime_ns, before_mcp)

            untracked = repo / "new_module.py"
            untracked.write_text("NEW_VALUE = 1\n", encoding="utf-8")
            partial = subprocess.run(
                [str(LIFECYCLE), "inspect", str(repo), "--json"],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )
            partial_result = json.loads(partial.stdout)
            self.assertTrue(partial_result["usable"])
            self.assertEqual(partial_result["coverage"], "partial")
            self.assertEqual(partial_result["excluded_sources"], ["new_module.py"])
            subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )
            untracked.unlink()

            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "advance head",
                ],
                env=environment,
                check=True,
            )
            poisoned_snapshot = lifecycle.workspace_snapshot(repo)
            poisoned_entry = lifecycle.lifecycle_metadata(repo, poisoned_snapshot)
            lifecycle.update_state_entry(str(repo), poisoned_entry)
            provenance_stale = subprocess.run(
                [str(LIFECYCLE), "inspect", str(repo), "--json"],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            provenance_result = json.loads(provenance_stale.stdout)
            self.assertFalse(provenance_result["usable"])
            self.assertIn("provenance", provenance_result["reason"])
            provenance_reader = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertNotEqual(provenance_reader.returncode, 0)
            self.assertIn(provenance_result["reason"], provenance_reader.stderr)

            current_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "UPDATE metadata SET value=? WHERE key='git_head_sha'",
                    (current_head,),
                )
                connection.commit()
            finally:
                connection.close()
            restored_snapshot = lifecycle.workspace_snapshot(repo)
            lifecycle.update_state_entry(
                str(repo), lifecycle.lifecycle_metadata(repo, restored_snapshot)
            )

            source.write_text("VALUE = 2\n", encoding="utf-8")
            stale = subprocess.run(
                [str(LIFECYCLE), "inspect", str(repo), "--json"],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            stale_result = json.loads(stale.stdout)
            self.assertFalse(stale_result["usable"])
            stale_reader = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertNotEqual(stale_reader.returncode, 0)
            self.assertIn(stale_result["reason"], stale_reader.stderr)


if __name__ == "__main__":
    unittest.main()
