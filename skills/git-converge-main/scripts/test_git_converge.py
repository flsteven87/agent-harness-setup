import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("git_converge.py")
SPEC = importlib.util.spec_from_file_location("git_converge", SCRIPT)
assert SPEC and SPEC.loader
converge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = converge
SPEC.loader.exec_module(converge)


def command(cwd: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )
    return completed.stdout.strip()


def git(cwd: Path, *args: str) -> str:
    return command(cwd, "git", *args)


class RepoFixture:
    def __init__(self, root: Path):
        self.remote = root / "remote.git"
        self.repo = root / "repo"
        git(root, "init", "--bare", str(self.remote))
        git(root, "init", "-b", "main", str(self.repo))
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.com")
        (self.repo / "tracked.txt").write_text("initial\n")
        (self.repo / ".gitignore").write_text(".cache/\n")
        git(self.repo, "add", "tracked.txt", ".gitignore")
        git(self.repo, "commit", "-m", "initial")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-u", "origin", "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        git(self.repo, "remote", "set-head", "origin", "-a")

    def commit(self, message: str, text: str) -> str:
        (self.repo / "tracked.txt").write_text(text)
        git(self.repo, "add", "tracked.txt")
        git(self.repo, "commit", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def remote_commit(self, root: Path, name: str, text: str) -> str:
        publisher = root / f"publisher-{name.replace('/', '-')}"
        git(root, "clone", str(self.remote), str(publisher))
        git(publisher, "config", "user.name", "Remote User")
        git(publisher, "config", "user.email", "remote@example.com")
        target = publisher / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(publisher, "add", "-f", name)
        git(publisher, "commit", "-m", f"remote {name}")
        git(publisher, "push", "origin", "HEAD:main")
        return git(publisher, "rev-parse", "HEAD")


class GitConvergeAuditTests(unittest.TestCase):
    def test_failed_required_command_raises_and_status_fails_closed(self):
        failure = converge.Result(["git", "status"], 128, "cannot read index")
        with mock.patch.object(converge, "git", return_value=failure):
            with self.assertRaises(converge.GitCommandError):
                converge.output(["status"], cwd=Path("."))
            status = converge.status_counts(Path("."))

        self.assertFalse(status["ok"])
        self.assertFalse(status["clean"])
        self.assertEqual(status["error"], "cannot read index")

    def test_canonical_remote_is_not_hardcoded_to_origin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git(fixture.repo, "remote", "rename", "origin", "upstream")

            self.assertEqual(
                converge.default_remote_ref(fixture.repo),
                ("upstream", "main", "upstream/main"),
            )

    def test_status_and_worktree_inventory_are_nul_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = RepoFixture(root)
            (fixture.repo / "line\nbreak.txt").write_text("untracked\n")
            (fixture.repo / "tracked.txt").write_text("modified\n")
            (fixture.repo / ".cache").mkdir()
            (fixture.repo / ".cache" / "ignored.txt").write_text("ignored\n")
            git(fixture.repo, "branch", "linked")
            linked = root / "linked\nworktree"
            git(fixture.repo, "worktree", "add", str(linked), "linked")

            state = converge.snapshot(fixture.repo)
            primary = next(
                item
                for item in state["worktrees"]
                if Path(item["path"]).resolve() == fixture.repo.resolve()
            )
            detailed = converge.status_counts(fixture.repo, include_entries=True)

            self.assertEqual(primary["status"]["untracked"], 1)
            self.assertEqual(primary["status"]["unstaged"], 1)
            self.assertEqual(primary["status"]["entries_omitted"], 2)
            self.assertEqual(primary["status"]["groups"], [{"path": ".", "count": 2}])
            self.assertIn(
                linked.resolve(),
                [Path(item["path"]).resolve() for item in state["worktrees"]],
            )
            self.assertEqual(primary["ignored_entry_count"], 1)
            self.assertTrue(
                any(
                    "line\nbreak.txt" in item["path"]
                    for item in detailed["entry_records"]
                )
            )

    def test_audit_branch_records_keep_independent_axes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git(fixture.repo, "branch", "reachable")
            git(fixture.repo, "switch", "-c", "work")
            fixture.commit("unique", "unique\n")
            git(fixture.repo, "config", "branch.work.remote", "origin")
            git(fixture.repo, "config", "branch.work.merge", "refs/heads/deleted")

            with mock.patch.object(
                converge,
                "merged_prs",
                side_effect=AssertionError("plain audit contacted GitHub"),
            ):
                state = converge.snapshot(fixture.repo)

            records = {item["name"]: item for item in state["local_branches"]}
            self.assertEqual(records["reachable"]["local_integration"], "reachable")
            self.assertEqual(records["reachable"]["remote_integration"], "reachable")
            self.assertEqual(records["reachable"]["upstream"], "none")
            self.assertEqual(records["reachable"]["checkout"], "unattached")
            self.assertEqual(records["work"]["local_integration"], "not-proven")
            self.assertEqual(records["work"]["remote_integration"], "not-proven")
            self.assertEqual(records["work"]["upstream"], "gone")
            self.assertEqual(
                Path(records["work"]["checkout"]).resolve(), fixture.repo.resolve()
            )

    def test_local_and_remote_integration_are_independent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git(fixture.repo, "switch", "-c", "work")
            fixture.commit("unique", "unique\n")
            git(fixture.repo, "switch", "main")
            git(fixture.repo, "merge", "--ff-only", "work")

            state = converge.snapshot(fixture.repo)
            records = {item["name"]: item for item in state["local_branches"]}

            self.assertEqual(records["main"]["local_integration"], "reachable")
            self.assertEqual(records["main"]["remote_integration"], "not-proven")
            self.assertEqual(records["work"]["local_integration"], "reachable")
            self.assertEqual(records["work"]["remote_integration"], "not-proven")

    def test_integration_uses_fully_qualified_refs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git(fixture.repo, "switch", "-c", "collision")
            collision_oid = fixture.commit("collision", "collision\n")
            git(fixture.repo, "tag", "main", collision_oid)
            git(fixture.repo, "branch", "origin/main", collision_oid)
            git(fixture.repo, "switch", "main")

            state = converge.snapshot(fixture.repo)
            records = {item["name"]: item for item in state["local_branches"]}

            self.assertEqual(records["main"]["local_integration"], "reachable")
            self.assertEqual(records["main"]["remote_integration"], "reachable")
            self.assertEqual(records["collision"]["local_integration"], "not-proven")
            self.assertEqual(records["origin/main"]["remote_integration"], "not-proven")

    def test_merge_proof_is_explicit_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git(fixture.repo, "switch", "-c", "squashed")
            fixture.commit("unique", "unique\n")
            with mock.patch.object(
                converge,
                "merge_proof",
                return_value=("PR #9 merged exact head; patch matches", None),
            ) as proof:
                state = converge.snapshot(fixture.repo, merge_proof_enabled=True)

            branch = next(
                item for item in state["local_branches"] if item["name"] == "squashed"
            )
            self.assertEqual(branch["remote_integration"], "patch-equivalent")
            self.assertIn("PR #9", branch["remote_proof"])
            proof.assert_called_once()

    def test_merge_proof_rejects_matching_patch_outside_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git(fixture.repo, "switch", "-c", "squashed")
            branch_oid = fixture.commit("branch change", "unique\n")
            git(fixture.repo, "switch", "main")
            git(fixture.repo, "switch", "-c", "unlanded-merge")
            merge_oid = fixture.commit("matching squash", "unique\n")
            git(fixture.repo, "switch", "squashed")
            merged_pr = {
                "number": 9,
                "headRefName": "squashed",
                "headRefOid": branch_oid,
                "baseRefName": "main",
                "mergeCommit": {"oid": merge_oid},
            }

            with mock.patch.object(
                converge, "merged_prs", return_value=([merged_pr], None)
            ):
                proof, error = converge.merge_proof(
                    fixture.repo,
                    branch_name="squashed",
                    branch_ref="squashed",
                    default_branch="main",
                    default_ref="origin/main",
                )

            self.assertIsNone(proof)
            self.assertEqual(
                error, "no exact merged PR with matching cumulative patch-id"
            )
            self.assertEqual(
                subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        merge_oid,
                        "origin/main",
                    ],
                    cwd=fixture.repo,
                    check=False,
                ).returncode,
                1,
            )

    def test_fetch_only_refreshes_remote_tracking_refs(self):
        with mock.patch.object(
            converge,
            "git",
            return_value=converge.Result(["git", "fetch"], 0, ""),
        ) as called:
            converge.fetch(Path("."))

        called.assert_called_once_with(
            ["fetch", "--all", "--prune", "--tags"], cwd=Path(".")
        )

    def test_audit_fetch_reports_behind_without_moving_local_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = RepoFixture(root)
            local_oid = git(fixture.repo, "rev-parse", "main")
            remote_oid = fixture.remote_commit(root, "incoming.txt", "incoming\n")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "audit",
                    str(fixture.repo),
                    "--fetch",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(payload["default_relation"]["relation"], "behind")
            self.assertEqual(git(fixture.repo, "rev-parse", "main"), local_oid)
            self.assertEqual(git(fixture.repo, "rev-parse", "origin/main"), remote_oid)

    def test_git_operation_is_an_attention_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            git_dir = Path(git(fixture.repo, "rev-parse", "--absolute-git-dir"))
            (git_dir / "BISECT_LOG").write_text("active\n")

            state = converge.snapshot(fixture.repo)
            primary = next(
                item
                for item in state["worktrees"]
                if Path(item["path"]).resolve() == fixture.repo.resolve()
            )

            self.assertIn("bisect", primary["operations"])
            self.assertIn("Git operation: bisect", primary["attention"])

    def test_cli_json_exposes_inventory_and_relation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "audit", str(fixture.repo), "--json"],
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(payload["default_relation"]["relation"], "aligned")
            self.assertTrue(payload["state_token"])
            self.assertTrue(
                {
                    "local_integration",
                    "local_proof",
                    "remote_integration",
                    "remote_proof",
                    "upstream",
                    "checkout",
                }
                <= payload["local_branches"][0].keys()
            )

    def test_mutating_cli_surfaces_are_absent_and_state_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            before = git(fixture.repo, "show-ref")
            for removed_command in ("sync-default", "plan", "apply"):
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), removed_command, str(fixture.repo)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("invalid choice", completed.stderr)
            self.assertEqual(git(fixture.repo, "show-ref"), before)

    def test_script_contains_no_local_mutation_commands(self):
        source = SCRIPT.read_text()
        forbidden = (
            '"update-ref"',
            '"worktree", "remove"',
            '"merge", "--ff-only"',
            '"branch", "-D"',
            '"stash", "drop"',
            'git(["rebase"',
        )
        for command_text in forbidden:
            self.assertNotIn(command_text, source)

    def test_provider_query_uses_policy_selected_gh(self):
        converge.all_merged_prs.cache_clear()
        response = converge.Result([str(converge.GH_CLI), "pr", "list"], 0, "[]")
        with mock.patch.object(converge, "run", return_value=response) as called:
            grouped, error = converge.all_merged_prs("/tmp")

        self.assertEqual(grouped, {})
        self.assertIsNone(error)
        self.assertEqual(called.call_args.args[0][0], str(converge.GH_CLI))

    def test_secrets_and_remote_credentials_are_redacted(self):
        secret = "github_pat_abcdefghijklmnopqrstuvwxyz"
        text = f"https://user:password@example.com/repo {secret}"

        redacted = converge.redact(text)

        self.assertEqual(
            redacted,
            "https://<redacted>@example.com/repo <redacted-token>",
        )

    def test_inventory_token_changes_when_repository_state_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))
            before = converge.snapshot(fixture.repo)["state_token"]
            (fixture.repo / "new.txt").write_text("new\n")
            after = converge.snapshot(fixture.repo)["state_token"]

            self.assertNotEqual(before, after)

    def test_bounded_recovery_samples_report_total_and_omitted_counts(self):
        sample, total, omitted = converge.bounded_records(
            [f"record-{index}" for index in range(45)]
        )

        self.assertEqual(len(sample), 40)
        self.assertEqual(total, 45)
        self.assertEqual(omitted, 5)

    def test_snapshot_reports_reflog_coverage_and_edge_check_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RepoFixture(Path(temp_dir))

            without_edges = converge.snapshot(fixture.repo)
            with_edges = converge.snapshot(fixture.repo, edge_checks=True)

            self.assertGreaterEqual(without_edges["reflog_total"], 1)
            self.assertEqual(
                without_edges["reflog_omitted"],
                max(0, without_edges["reflog_total"] - 40),
            )
            self.assertIsNone(without_edges["unreachable_total"])
            self.assertIsNone(without_edges["unreachable_omitted"])
            self.assertIsInstance(with_edges["unreachable_total"], int)
            self.assertIsInstance(with_edges["unreachable_omitted"], int)

    def test_audit_inspection_error_returns_nonzero_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "audit", temp_dir, "--json"],
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["status"], "error")


if __name__ == "__main__":
    unittest.main()
