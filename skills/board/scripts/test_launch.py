#!/usr/bin/env python3
"""Regression tests for the board's local launcher: the launch record, the server's gate, and dispatch."""

from __future__ import annotations

import http.client
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("launch.py")
SPEC = importlib.util.spec_from_file_location("launch", MODULE_PATH)
assert SPEC and SPEC.loader
launch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launch
SPEC.loader.exec_module(launch)

ACTION = {"kind": "dispatch", "project": "shop", "path": "/s", "key": "plain-slug", "text": "Measure LCP.", "title": "首頁載入變快"}
PAGE = (
    '<html lang="zh-Hant" data-launch-token=""><body>'
    f'<script type="application/json" id="launch-actions">{json.dumps({"a1": ACTION}, ensure_ascii=False)}</script>'
    "</body></html>"
)


class LedgerCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patches = [
            mock.patch.object(launch, "BOARD_DIR", Path(tmp.name)),
            mock.patch.object(launch, "LEDGER", Path(tmp.name, "launches.json")),
            mock.patch.object(launch, "ERRORS", Path(tmp.name, "errors.log")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


class LedgerTest(LedgerCase):
    def test_a_card_launches_once(self) -> None:
        self.assertIsNone(launch.claim("a1", ACTION))
        self.assertEqual(launch.claim("a1", ACTION)["state"], "running")
        launch.finish("a1", state="done", worktree="plain-slug-0930-1012")
        self.assertEqual(launch.claim("a1", ACTION)["worktree"], "plain-slug-0930-1012")

    def test_only_a_failure_that_created_nothing_can_retry(self) -> None:
        launch.claim("a1", ACTION)
        launch.finish("a1", state="failed", note="Orca 沒開", retry=True)
        self.assertIsNone(launch.claim("a1", ACTION))
        launch.finish("a1", state="failed", note="worktree 已保留", retry=False)
        self.assertEqual(launch.claim("a1", ACTION)["note"], "worktree 已保留")

    def test_a_launch_orphaned_by_a_dead_server_stops_spinning(self) -> None:
        with launch.ledger() as data:
            data["a1"] = {"state": "running", "kind": "dispatch", "at": "09-30 10:00", "pid": 2**22 + 7}
        # Reading the state alone settles it; the page never has to click a disabled button.
        entry = launch.entries({"a1": ACTION})["a1"]
        self.assertEqual((entry["state"], entry["retry"]), ("failed", False))
        self.assertNotIn("pid", entry)

    def test_an_unreadable_record_refuses_instead_of_forgetting(self) -> None:
        launch.LEDGER.write_text("{broken", encoding="utf-8")
        with self.assertRaises(launch.LaunchError):
            launch.claim("a1", ACTION)
        self.assertEqual(launch.LEDGER.read_text(encoding="utf-8"), "{broken")

    def test_one_decision_launches_one_option(self) -> None:
        yes, no = {**ACTION, "group": "d1"}, {**ACTION, "group": "d1", "text": "no"}
        self.assertIsNone(launch.claim("yes", yes))
        self.assertEqual(launch.claim("no", no), {"state": "taken"})
        self.assertEqual(launch.entries({"yes": yes, "no": no})["no"], {"state": "taken"})

    def test_a_workstream_in_flight_is_not_dispatched_again_under_new_text(self) -> None:
        worktree = tempfile.TemporaryDirectory()
        self.addCleanup(worktree.cleanup)
        rewritten = {**ACTION, "text": "shop（/s）的工作線 plain-slug，下一步：Measure INP。"}
        launch.claim("a1", ACTION)
        launch.finish("a1", state="done", worktree="plain-slug-0930-1012", path=worktree.name, terminal="t1")
        self.assertEqual(launch.claim("a2", rewritten)["worktree"], "plain-slug-0930-1012")
        with mock.patch.object(launch, "read_progress", return_value={"progress": "實作中，還沒開 PR。"}):
            shown = launch.entries({"a2": rewritten})["a2"]
        self.assertEqual((shown["worktree"], shown["progress"]), ("plain-slug-0930-1012", "實作中，還沒開 PR。"))
        self.assertNotIn("repo", shown)
        # A page that showed this dispatch on the rewritten card keeps showing it once it finishes,
        # instead of offering the step the card was rendered with.
        borrowed: dict = {}
        with mock.patch.object(launch, "read_progress", return_value={"progress": "實作中，還沒開 PR。"}):
            launch.entries({"a2": rewritten}, borrowed)
        worktree.cleanup()
        with mock.patch.object(launch, "read_progress", return_value={"progress": "已經收尾", "finished": True}):
            launch._progress.clear()
            self.assertTrue(launch.entries({"a2": rewritten}, borrowed)["a2"]["finished"])
        # The receiver removes its worktree last; after that the workstream's next card can dispatch.
        self.assertIsNone(launch.claim("a2", rewritten))

    def test_a_worktree_preserved_by_a_failed_launch_still_holds_its_workstream(self) -> None:
        worktree = tempfile.TemporaryDirectory()
        self.addCleanup(worktree.cleanup)
        launch.claim("a1", ACTION)
        launch.note_worktree("a1", "plain-slug-0930-1012", worktree.name)
        launch.finish("a1", state="failed", note="agent 沒有順利啟動；worktree 已保留。", retry=False)
        self.assertEqual(launch.claim("a2", {**ACTION, "text": "改過的下一步"})["note"], "agent 沒有順利啟動；worktree 已保留。")
        self.assertFalse(launch.entries({"a1": ACTION})["a1"]["retry"])
        # Once the owner clears that worktree in Orca, the same card can try again.
        worktree.cleanup()
        self.assertTrue(launch.entries({"a1": ACTION})["a1"]["retry"])
        self.assertIsNone(launch.claim("a1", ACTION))


    def test_an_upkeep_launch_reports_through_the_page_state(self) -> None:
        # Upkeep has a log and no worktree; the state the page polls must read it (KeyError 'path', 2026-09-30).
        log = Path(launch.BOARD_DIR, "notes-refresh-0930-1502.json")
        log.write_text(json.dumps({"type": "result", "is_error": False, "result": "筆記已更新。"}), encoding="utf-8")
        with launch.ledger() as data:
            data["a1"] = {"kind": "dispatch", "state": "done", "at": "09-30 15:02", "log": str(log), "agent_pid": 2**22 + 7}
        launch._progress.clear()
        self.addCleanup(launch._progress.clear)
        self.assertTrue(launch.entries({"a1": {**ACTION, "key": "notes-refresh"}})["a1"]["finished"])


    def test_an_unwritable_error_log_still_settles_the_card(self) -> None:
        launch.claim("a1", ACTION)
        with mock.patch.object(launch, "ERRORS", launch.BOARD_DIR), \
                mock.patch.object(launch, "dispatch", side_effect=RuntimeError("boom")), \
                mock.patch.object(launch.sys, "stderr", new=io.StringIO()):
            launch.run_launch("a1", ACTION)
        self.assertEqual(launch.claim("a1", ACTION)["state"], "failed")


class RecoveryTest(LedgerCase):
    def failed_launch(self, worktree: str, repo: str) -> None:
        launch.claim("a1", ACTION)
        with launch.ledger() as data:
            data["a1"].update(repo=repo, started=launch.time.time() - 60)
        launch.note_worktree("a1", "plain-slug-0930-1012", worktree)
        launch.finish("a1", state="failed", note="agent 已啟動，但沒確認收下派工內容", retry=False, terminal="agent1")

    def test_a_receiver_that_ran_after_a_misreported_launch_is_recorded_as_delivered(self) -> None:
        repo = tempfile.TemporaryDirectory()
        self.addCleanup(repo.cleanup)
        self.failed_launch("/gone/worktree", repo.name)
        Path(repo.name, "MEMORY.md").write_text("checkpoint", encoding="utf-8")
        entry = launch.entries({"a1": ACTION})["a1"]
        self.assertEqual((entry["state"], entry.get("finished"), "note" in entry), ("done", True, False))
        with launch.ledger() as data:
            self.assertEqual(data["a1"]["state"], "done")

    def test_a_receiver_that_never_ran_keeps_the_failure(self) -> None:
        worktree = tempfile.TemporaryDirectory()
        self.addCleanup(worktree.cleanup)
        self.failed_launch(worktree.name, "/s")
        with mock.patch.object(launch, "orca", return_value={"terminals": []}):
            entry = launch.entries({"a1": ACTION})["a1"]
        self.assertEqual((entry["state"], entry["note"]), ("failed", "agent 已啟動，但沒確認收下派工內容"))


class ProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.entry = {"path": tmp.name, "terminal": "t1"}
        self.now_ms = launch.time.time() * 1000
        self.gh_error = 'no pull requests found for branch "plain-slug-0930-1012"'

    def read(self, terminals: list[dict], pr: dict | None = None) -> dict:
        gh = subprocess.CompletedProcess([], 0 if pr else 1, json.dumps(pr) if pr else "", self.gh_error)
        with mock.patch.object(launch, "orca", return_value={"terminals": terminals}), \
                mock.patch.object(launch.subprocess, "run", return_value=gh):
            return launch.read_progress(self.entry)

    def agent(self, branch: str = "refs/heads/plain-slug-0930-1012", quiet_min: float = 0) -> dict:
        return {"handle": "t1", "connected": True, "branch": branch, "lastOutputAt": self.now_ms - quiet_min * 60000}

    def test_each_delivery_step_reads_in_plain_words(self) -> None:
        self.assertEqual(self.read([self.agent()])["progress"], "實作中，還沒開 PR。")
        passing = {"state": "OPEN", "statusCheckRollup": [{"conclusion": "SUCCESS"}]}
        self.assertEqual(self.read([self.agent()], passing)["progress"], "PR 已開，檢查都通過了。")
        self.assertEqual(self.read([self.agent()], {"state": "MERGED"})["progress"], "PR 已合併，正在收尾。")
        self.assertEqual(self.read([self.agent(branch="")])["progress"], "已合併，正在收尾。")

    def test_an_unreadable_github_is_not_reported_as_no_pr(self) -> None:
        self.gh_error = "HTTP 502: Bad Gateway"
        self.assertEqual(self.read([self.agent()])["progress"], "還在進行，這次讀不到 GitHub 的狀態。")

    def test_a_removed_worktree_counts_as_finished_only_with_fresh_notes(self) -> None:
        repo = Path(self.entry["path"])
        self.entry.update(path=str(repo / "gone"), repo=str(repo), started=launch.time.time() - 60)
        unproved = self.read([])
        self.assertEqual((unproved["attention"], "finished" in unproved), (True, False))
        (repo / "MEMORY.md").write_text("## Active Workstreams\n", encoding="utf-8")
        finished = self.read([])
        self.assertEqual((finished["finished"], "attention" in finished), (True, False))

    def test_a_finished_dispatch_whose_merge_is_not_local_yet_is_not_done(self) -> None:
        repo = Path(self.entry["path"])
        self.entry.update(path=str(repo / "gone"), repo=str(repo), started=launch.time.time() - 60)
        (repo / "MEMORY.md").write_text("## Active Workstreams\n", encoding="utf-8")
        with mock.patch.object(launch, "remote_default", return_value="origin/main"), \
                mock.patch.object(launch, "behind", return_value=1) as behind:
            pending = self.read([])
        behind.assert_called_once_with(str(repo), "main", "origin/main")
        self.assertEqual((pending["attention"], "finished" in pending), (True, False))
        self.assertIn("還少了 1 個已合併的更新", pending["progress"])

    def test_a_silent_or_exited_agent_asks_the_owner_to_look(self) -> None:
        self.assertTrue(self.read([])["attention"])
        quiet = self.read([self.agent(quiet_min=12)])
        self.assertTrue(quiet["attention"])
        self.assertIn("12 分鐘沒有動靜", quiet["progress"])
        self.assertNotIn("attention", self.read([self.agent(quiet_min=3)]))
        closed = self.read([self.agent()], {"state": "CLOSED"})
        self.assertTrue(closed["attention"])


class ServerTest(LedgerCase):
    def setUp(self) -> None:
        super().setUp()
        self.calls: list[dict] = []
        self.release = threading.Event()

        def fake(aid: str, action: dict) -> dict:
            self.calls.append(action)
            self.release.wait(5)
            return {"worktree": "plain-slug-0930-1012"}

        patch = mock.patch.object(launch, "dispatch", fake)
        patch.start()
        self.addCleanup(patch.stop)
        self.server = launch.LaunchServer(PAGE, "secret-token", socket.create_server(("127.0.0.1", 0)))
        self.server.server_activate()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.release.set)

    def request(self, method: str, path: str, body: dict | None = None, token: str = "secret-token", host: str = "") -> tuple[int, str]:
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        headers = {"X-Launch-Token": token, "Content-Type": "application/json", "Host": host or self.server.host}
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        return response.status, response.read().decode()

    def test_the_page_opens_only_with_its_token_and_carries_it(self) -> None:
        self.assertEqual(self.request("GET", "/?t=wrong")[0], 403)
        with mock.patch.object(launch.sys, "stderr", new=io.StringIO()) as log:
            status, page = self.request("GET", "/?t=secret-token")
        self.assertEqual(status, 200)
        self.assertTrue('data-launch-token="secret-token"' in page)
        self.assertTrue("GET / 200" in log.getvalue() and "secret-token" not in log.getvalue())

    def test_other_pages_and_rebound_hosts_cannot_launch(self) -> None:
        self.assertEqual(self.request("POST", "/launch", {"id": "a1"}, token="guess")[0], 403)
        self.assertEqual(self.request("POST", "/launch", {"id": "a1"}, host="evil.test:80")[0], 403)
        self.assertEqual(self.request("POST", "/launch", {"id": "rm -rf"})[0], 404)
        self.assertEqual(self.calls, [])

    def test_only_the_pages_own_requests_keep_it_alive(self) -> None:
        self.server.last_seen = 0.0
        self.request("GET", "/state", token="guess")
        self.assertEqual(self.server.last_seen, 0.0)
        self.request("GET", "/state")
        self.assertGreater(self.server.last_seen, 0.0)

    def test_an_unexpected_state_error_tells_the_page_and_is_recorded(self) -> None:
        with mock.patch.object(launch, "entries", side_effect=KeyError("path")), \
                mock.patch.object(launch.sys, "stderr", new=io.StringIO()):
            status, body = self.request("GET", "/state")
        self.assertEqual(status, 500)
        self.assertTrue("/board" in json.loads(body)["note"])
        self.assertTrue("/state: KeyError: 'path'" in launch.ERRORS.read_text(encoding="utf-8"))

    def test_a_click_launches_the_embedded_action_once(self) -> None:
        status, body = self.request("POST", "/launch", {"id": "a1"})
        self.assertEqual((status, json.loads(body)["state"]), (202, "running"))
        self.assertEqual(self.request("POST", "/launch", {"id": "a1"})[0], 409)
        self.release.set()
        state: dict = {}
        for _ in range(50):
            state = json.loads(self.request("GET", "/state")[1])["a1"]
            if state["state"] == "done":
                break
            threading.Event().wait(0.05)
        self.assertEqual(state["worktree"], "plain-slug-0930-1012")
        self.assertEqual(self.calls, [ACTION])


class RetireTest(LedgerCase):
    def test_a_newer_server_for_the_page_retires_the_older_once_its_launch_ends(self) -> None:
        marker = Path(launch.BOARD_DIR, "shop.server")
        server = launch.LaunchServer(PAGE, "t", socket.create_server(("127.0.0.1", 0)), marker)
        self.addCleanup(server.server_close)
        self.assertFalse(server.retiring())
        marker.write_text("1", encoding="utf-8")  # the next /board run's server
        server.running = 1
        self.assertFalse(server.retiring())
        server.running = 0
        self.assertTrue(server.retiring())


class DispatchTest(unittest.TestCase):
    def test_a_card_dispatch_hands_its_assignment_to_the_shared_dispatcher(self) -> None:
        calls: list[tuple] = []
        labels: list[str] = []

        def fake(repo: str, name: str, assignment: str, goal: str, **kwargs: object) -> dict:
            calls.append((repo, name, assignment, goal))
            labels.append(kwargs["label"])
            kwargs["on_worktree"](name, "/wt/new")  # type: ignore[operator]
            return {"worktree": name, "path": "/wt/new", "terminal": "agent1", "assignment": "/g/endgame-assignment.md"}

        with mock.patch.object(launch, "hand_off", fake), mock.patch.object(launch, "note_worktree") as noted:
            result = launch.dispatch("a1", ACTION)
        repo, name, assignment, goal = calls[0]
        self.assertEqual((repo, result), ("/s", {"worktree": name, "path": "/wt/new", "terminal": "agent1"}))
        noted.assert_called_once_with("a1", name, "/wt/new")
        self.assertTrue(name.startswith("plain-slug-"))
        self.assertTrue("`scripts.setup`, run it from the worktree root first" in assignment)
        self.assertTrue(ACTION["text"] in assignment and "Authorized endpoint: full delivery." in assignment)
        self.assertTrue("plain-slug` workstream in /s/MEMORY.md" in assignment)
        # The task lives in the assignment; the goal names the dispatch and how it ends.
        self.assertTrue(goal.startswith("/goal The board dispatch for shop workstream `plain-slug` is delivered"))
        # The receipt outlives the terminal that removal closes: the board reads it from this file.
        receipt = str(launch.receipt_path("a1"))
        self.assertTrue(f"write the completion receipt to {receipt}" in assignment and f"receipt written to {receipt}" in goal)
        self.assertFalse(ACTION["text"] in goal)
        self.assertTrue("The card's task, verbatim:\n\nMeasure LCP.\n" in assignment)
        self.assertTrue("The owner is not watching this terminal." in assignment)
        # The owner tells dispatches apart by the card's title and reads the agent in Traditional Chinese.
        self.assertEqual(labels, ["首頁載入變快"])
        self.assertTrue(launch.OWNER_LANGUAGE in assignment)

    def test_a_prefixed_key_names_its_worktree_by_its_last_part(self) -> None:
        now = launch.datetime(2026, 9, 30, 13, 51)
        self.assertEqual(launch.worktree_name("workstream:memory-backlog-triage", now), "memory-backlog-triage-0930-1351")
        self.assertEqual(launch.worktree_name("linear:example-org/example-api:ENG-2173", now), "eng-2173-0930-1351")

    def test_an_owner_card_dispatch_asks_the_owner_without_a_goal(self) -> None:
        sent: list[str] = []
        switched: list[tuple] = []

        def fake(repo: str, name: str, assignment: str, goal: str, **kwargs: object) -> dict:
            sent.extend((assignment, goal))
            return {"worktree": name, "path": "/wt/new", "terminal": "agent1", "assignment": "/g/endgame-assignment.md"}

        # A goal would keep pushing while the agent waits on the owner; the owner attends an /endgame prompt instead.
        with mock.patch.object(launch, "hand_off", fake), mock.patch.object(launch, "orca", lambda *a, **k: switched.append(a)):
            launch.dispatch("a1", {**ACTION, "ask": True})
        assignment, goal = sent
        self.assertEqual(goal, "/endgame Board dispatch for shop workstream `plain-slug`; the owner is at this terminal.")
        self.assertTrue("they are at this terminal" in assignment and "Authorized endpoint: full delivery." in assignment)
        self.assertEqual(switched, [("terminal", "switch", "--terminal", "agent1")])

    def test_upkeep_runs_headless_in_the_primary_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(launch, "UPKEEP_DIR", Path(tmp)), \
                mock.patch.object(launch, "hand_off") as hand_off, mock.patch.object(launch, "memory_tracked", return_value=False), \
                mock.patch.object(launch.subprocess, "Popen", return_value=mock.Mock(pid=4242)) as popen:
            result = launch.dispatch("a1", {**ACTION, "key": "notes-refresh", "text": "Run `$latest` in /s."})
        # The skill acts on the primary checkout, so no worktree is created around it.
        hand_off.assert_not_called()
        argv, kwargs = popen.call_args
        self.assertEqual((argv[0][:2], kwargs["cwd"]), (["claude", "-p"], "/s"))
        self.assertEqual(result["agent_pid"], 4242)
        self.assertTrue(Path(result["log"]).name.startswith("notes-refresh-"))
        self.assertEqual(kwargs["stderr"].name, str(Path(result["log"]).with_suffix(".err")))
        assignment = argv[0][2]
        self.assertTrue("Run `$latest` in /s." in assignment and "headless in its primary checkout /s" in assignment)
        self.assertTrue(launch.OWNER_LANGUAGE in assignment and "worktree" not in assignment)
        # Upkeep delivers nothing: its authority carries no merge or ticket write.
        self.assertTrue("Open no pull request, push nothing," in assignment)
        self.assertFalse("full delivery" in assignment or "$ship" in assignment)


class UpkeepProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name, "notes-refresh-0930-1448.json")
        self.log.write_text("", encoding="utf-8")
        self.entry = {"log": str(self.log), "agent_pid": launch.os.getpid()}
        launch._progress.clear()
        self.addCleanup(launch._progress.clear)

    def test_a_running_upkeep_holds_its_button(self) -> None:
        self.assertTrue(launch.in_flight({"kind": "dispatch", "state": "done", **self.entry}))
        # The page polls through the cache, which must key an upkeep launch by its log: it has no worktree.
        self.assertNotIn("finished", launch.progress(self.entry))

    def test_a_reported_upkeep_is_finished_and_a_silent_exit_asks_the_owner(self) -> None:
        self.log.write_text(json.dumps({"type": "result", "is_error": False, "result": "筆記已更新。"}), encoding="utf-8")
        self.assertTrue(launch.read_progress(self.entry)["finished"])
        self.assertFalse(launch.in_flight({"kind": "dispatch", "state": "done", **self.entry}))
        self.log.write_text("", encoding="utf-8")
        self.entry["agent_pid"] = 2**22 + 7  # no such process
        self.assertTrue(launch.read_progress(self.entry)["attention"])
        # A run that died before reporting points the owner at what it printed on stderr.
        errors = self.log.with_suffix(".err")
        errors.write_text("Error: not logged in\n", encoding="utf-8")
        self.assertIn(str(errors), launch.read_progress(self.entry)["progress"])


class ShowTest(unittest.TestCase):
    URL = "http://127.0.0.1:5000/?t=new"

    def shown(self, tabs: list[dict]) -> list[tuple]:
        calls: list[tuple] = []

        def fake(*args: str, **kwargs: object) -> dict:
            calls.append(args)
            return {"tabs": tabs} if args[:2] == ("tab", "list") else {"browserPageId": "fresh"}

        with mock.patch.object(launch, "orca", fake):
            launch.show(self.URL, "path:/s")
        return calls[1:]

    def test_the_page_reuses_an_earlier_board_tab(self) -> None:
        tabs = [{"browserPageId": "site", "url": "https://example.test/"},
                {"browserPageId": "board", "url": "http://127.0.0.1:4000/?t=old"}]
        self.assertEqual(self.shown(tabs), [
            ("goto", "--page", "board", "--worktree", "path:/s", "--url", self.URL),
            ("tab", "switch", "--page", "board", "--worktree", "path:/s", "--focus"),
        ])

    def test_without_one_the_page_opens_a_new_orca_tab(self) -> None:
        self.assertEqual(self.shown([{"browserPageId": "site", "url": "http://127.0.0.1:3000/"}]), [
            ("tab", "create", "--url", self.URL, "--worktree", "path:/s"),
            ("tab", "switch", "--page", "fresh", "--worktree", "path:/s", "--focus"),
        ])


class HeadlessLedgerTest(LedgerCase):
    def test_one_headless_run_at_a_time_per_primary_checkout(self) -> None:
        refresh = {**ACTION, "key": "notes-refresh", "text": "Run `$latest` in /s."}
        cleanup = {**ACTION, "key": "leftover-cleanup", "text": "Run `$git-converge-main` in /s."}
        self.assertIsNone(launch.claim("r1", refresh))
        busy = launch.claim("c1", cleanup)
        self.assertEqual((busy["state"], busy["retry"]), ("failed", True))
        # A worktree dispatch works elsewhere, so it is not held back.
        self.assertIsNone(launch.claim("a1", {**ACTION, "key": "other"}))
        launch.finish("r1", state="failed", note="x", retry=True)
        self.assertIsNone(launch.claim("c1", cleanup))


class UpkeepDeliveryTest(unittest.TestCase):
    def test_versioned_notes_reach_the_shared_line_and_ignored_notes_stay_local(self) -> None:
        now = launch.datetime(2026, 9, 30, 17, 39)
        refresh = {**ACTION, "key": "notes-refresh", "text": "Run `$latest` in /s."}
        tracked, ignored = launch.chore_assignment(refresh, now, True), launch.chore_assignment(refresh, now, False)
        self.assertTrue("commit exactly MEMORY.md on the default\nbranch" in tracked)
        self.assertTrue("`$ship` only while it is the one default-branch commit the remote lacks" in tracked)
        self.assertTrue("plus one commit of exactly MEMORY.md delivered through `$ship`" in tracked)
        self.assertTrue("Open no pull request, push nothing," in ignored and "$ship" not in ignored)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            Path(tmp, "MEMORY.md").write_text("# Notes\n", encoding="utf-8")
            self.assertFalse(launch.memory_tracked(tmp))
            subprocess.run(["git", "add", "MEMORY.md"], cwd=tmp, check=True)
            self.assertTrue(launch.memory_tracked(tmp))


if __name__ == "__main__":
    unittest.main()
