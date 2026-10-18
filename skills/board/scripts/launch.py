#!/usr/bin/env python3
"""Serve one board page on this machine and turn its buttons into Orca launches.

`board.py --open` calls start(): it binds 127.0.0.1 on a free port and hands the socket to a detached
`launch.py serve` process with a per-run token. The server serves the page with that token, accepts
only the launch actions embedded in the page, and exits after two idle hours or once a newer server for the
same page starts. An unexpected error lands in errors.log, which the next `board.py` run reports once.

Every action hands the card's step to milestone-dispatch's dispatch script, which creates an Orca
worktree, starts a YOLO Claude receiver, writes the assignment into the worktree's Git directory, and
sends the step: as a `/goal` for engineering work, or as an `/endgame` prompt the owner attends for an
owner step (`ask`), since a goal would keep pushing while the agent waits on the owner. Every launch is recorded in ~/.local/state/board/launches.json, so a card
launches once; only a failure that created nothing can be retried. A workstream whose dispatched worktree
still exists cannot be dispatched again, and its card reports that agent's progress from Orca and GitHub.
Upkeep (更新筆記, 清理殘留) acts on the primary checkout itself, so each runs there as one
headless agent with no worktree; its card reports the agent's own result.
"""

from __future__ import annotations

import argparse
import fcntl
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

from board import CHORES, ERRORS, GH, behind, ci_state, receipt_path, remote_default, upkeep_result, upkeep_running

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "milestone-dispatch/scripts"))
from dispatch import LaunchError, orca  # noqa: E402 - the one dispatch implementation lives in milestone-dispatch
from dispatch import dispatch as hand_off  # noqa: E402

BOARD_DIR = Path.home() / ".local/state/board"
LEDGER = BOARD_DIR / "launches.json"
LOG = BOARD_DIR / "launcher.log"
UPKEEP_DIR = BOARD_DIR / "upkeep"
IDLE_SECONDS = 2 * 3600
RECEIVER_CONTRACT = SKILLS / "milestone-dispatch/references/handoff-contract.md"
# How the receiver meets the owner: an owner card's receiver (`ask`) has the owner at its terminal.
OWNER_LINE = {
    False: "The owner is not watching this terminal. If the task turns out to wait on them (a decision or an\n"
    "action only they can take), stop before implementation and report that one decision.",
    True: "The owner pressed this card because its step waits on them, and they are at this terminal. First\n"
    "check whether the step still needs them; do whatever an agent can verify or do yourself, and ask them,\n"
    "one question at a time, only for the decision or action that is theirs. Then continue to the endpoint.",
}
# The owner reads this terminal; the assignment itself stays English for the agent.
OWNER_LANGUAGE = (
    "The owner reads everything you write in this terminal: write all of it, progress notes included, in\n"
    "Traditional Chinese (繁體中文, never Simplified)."
)
ACTIONS = re.compile(r'<script type="application/json" id="launch-actions">(.*?)</script>', re.S)
TOKEN_SLOT = 'data-launch-token=""'
# The page polls every 30 seconds while a dispatch is in flight; each refresh reads Orca and GitHub at most once.
PROGRESS_TTL = 20
# The owner's working profile probes a delegated job after ten minutes without any signal.
QUIET_MINUTES = 10
_progress: dict[str, tuple[float, dict]] = {}



# --- ledger -------------------------------------------------------------------------------------


@contextmanager
def ledger():
    """The launch record shared by every board server, read and written under one file lock."""
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(LEDGER.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, json.JSONDecodeError) as exc:
            # Rewriting an unreadable record would forget past launches and let their cards launch again.
            raise LaunchError(f"啟動紀錄 {LEDGER} 讀不出來（{exc}），先修好或移走它再按。") from exc
        if not isinstance(data, dict):
            raise LaunchError(f"啟動紀錄 {LEDGER} 的格式不對，先修好或移走它再按。")
        for entry in data.values():
            settle(entry)
        yield data
        tmp = LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(LEDGER)


def alive(pid: object) -> bool:
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def settle(entry: dict) -> None:
    """A launch whose server died mid-way is failed with an unknown result, so its card stops spinning."""
    if entry.get("state") == "running" and not alive(entry.get("pid")):
        entry.update(
            state="failed",
            retry=False,
            note="啟動器在開工途中關掉了，結果不確定；先到 Orca 看有沒有多出的 worktree 或對話。",
        )


def stamp() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def taken(data: dict, group: str) -> bool:
    """Whether another option of the same decision already launched."""
    return bool(group) and any(e.get("group") == group and e["state"] in ("running", "done") for e in data.values())


def in_flight(entry: dict) -> bool:
    """A dispatch still starting, or any whose worktree still exists, launched or preserved after a failure.

    The receiver removes its worktree as its last command; a preserved one waits for the owner in Orca.
    """
    if entry.get("kind") != "dispatch":
        return False
    return entry["state"] == "running" or upkeep_running(entry) or (bool(entry.get("path")) and Path(entry["path"]).is_dir())


def retryable(entry: dict) -> bool:
    """A failure that created nothing, or one whose preserved worktree the owner has since cleared."""
    return entry["state"] == "failed" and bool(entry.get("retry") or (entry.get("path") and not Path(entry["path"]).is_dir()))


def live_dispatch(data: dict, action: dict) -> str | None:
    """The record id of the dispatch already working this action's workstream, whatever text its card showed."""
    if action["kind"] != "dispatch" or not action.get("key"):
        return None
    return next(
        (i for i, e in data.items() if e.get("repo") == action["path"] and e.get("key") == action["key"] and in_flight(e)),
        None,
    )


def headless(action: dict) -> bool:
    """Upkeep runs in the primary checkout itself rather than in a worktree."""
    return action["key"] in CHORES


def primary_busy(data: dict, repo: str) -> bool:
    """Whether a headless run is starting or at work in this primary checkout: two would share MEMORY.md and the index."""
    return any(
        e.get("repo") == repo and ((e.get("primary") and e["state"] == "running") or upkeep_running(e)) for e in data.values()
    )


def claim(aid: str, action: dict) -> dict | None:
    """Mark an action running and return None, or return what already owns it."""
    with ledger() as data:
        entry = data.get(aid)
        if entry and not retryable(entry):
            return entry
        group = action.get("group", "")
        if taken(data, group):
            return {"state": "taken"}
        if live := live_dispatch(data, action):
            return data[live]
        if headless(action) and primary_busy(data, action["path"]):
            return {"state": "failed", "retry": True, "note": "主目錄正有另一個背景工作在跑，等它跑完再按一次。"}
        data[aid] = {
            "state": "running", "kind": action["kind"], "group": group, "repo": action["path"], "key": action["key"],
            "entry": action.get("entry", ""), "at": stamp(), "started": time.time(), "pid": os.getpid(),
            **({"primary": True} if headless(action) else {}),
        }
        return None


def finish(aid: str, **fields: object) -> None:
    with ledger() as data:
        old = data.get(aid, {})
        kept = {k: old[k] for k in ("group", "repo", "key", "entry", "started", "worktree", "path", "primary") if k in old}
        data[aid] = {"kind": old.get("kind"), **kept, "at": stamp(), **fields}


def note_worktree(aid: str, name: str, path: str) -> None:
    """Record a new worktree at once, so a failure or a dead server after this point still holds its workstream."""
    with ledger() as data:
        if aid in data:
            data[aid].update(worktree=name, path=path)


def public(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in ("pid", "agent_pid", "group", "repo", "key", "started", "primary")}


def entries(actions: dict, borrowed: dict | None = None) -> dict:
    """What each of the page's actions shows: its own record, the dispatch working its workstream, or
    `taken` when its decision was answered. A dispatched card carries its progress.

    `borrowed` (per page) remembers which dispatch a card showed, so after that dispatch finishes the card
    keeps saying so instead of offering the step it was rendered with again.
    """
    borrowed = {} if borrowed is None else borrowed
    with ledger() as data:
        shown, source = {}, {}
        for aid, action in actions.items():
            source[aid] = aid if aid in data else borrowed.get(aid, "")
            entry = data.get(source[aid])
            # An unchosen option says its question was answered.
            if not entry and taken(data, action.get("group", "")):
                shown[aid] = {"state": "taken"}
                continue
            if not entry and (live := live_dispatch(data, action)):
                borrowed[aid] = source[aid] = live
                entry = data[live]
            if entry:
                shown[aid] = {**entry, "retry": True} if retryable(entry) else dict(entry)
    # Progress reads Orca and GitHub, so it runs outside the lock every board server shares.
    for aid, entry in shown.items():
        if entry.get("kind") != "dispatch" or not (entry.get("path") or entry.get("log")):
            continue
        if entry["state"] == "done":
            entry.update(progress(entry))
        elif entry["state"] == "failed" and entry.get("terminal"):
            # The launch could not prove delivery, but its receiver started; what it did since is the record.
            observed = progress(entry)
            if not observed.get("attention"):
                recovered(source[aid])
                entry.update(observed, state="done")
                entry.pop("note", None)
                entry.pop("retry", None)
    return {aid: public(entry) for aid, entry in shown.items()}


def recovered(rid: str) -> None:
    """Record that a launch reported as failed was delivered after all: its receiver is working or finished."""
    with ledger() as data:
        if rid in data and data[rid]["state"] == "failed":
            data[rid]["state"] = "done"
            for field in ("note", "retry"):
                data[rid].pop(field, None)


# --- progress -----------------------------------------------------------------------------------


def progress(entry: dict) -> dict:
    """Where a dispatched agent is, read at most once per PROGRESS_TTL for each worktree or upkeep log."""
    # Upkeep runs in the primary checkout, so its log, not a worktree, names the launch.
    key = entry.get("path") or entry["log"]
    hit = _progress.get(key)
    if hit and time.monotonic() - hit[0] < PROGRESS_TTL:
        return hit[1]
    result = read_progress(entry)
    _progress[key] = (time.monotonic(), result)
    return result


def read_progress(entry: dict) -> dict:
    if entry.get("log"):
        return upkeep_progress(entry)
    if not Path(entry["path"]).is_dir():
        # The receiver's last two acts are the checkpoint and the removal; a removal alone proves neither.
        memory = Path(entry.get("repo", ""), "MEMORY.md")
        noted = memory.is_file() and memory.stat().st_mtime > entry.get("started", float("inf"))
        if noted:
            # The dispatch contract's last sync step: the merge is live only once local main contains it.
            try:
                base = remote_default(entry["repo"])
                missing = behind(entry["repo"], base.split("/", 1)[-1], base) if base else 0
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return {"progress": "已經收尾，但這次讀不到你電腦上的版本有沒有同步；重新執行 /board 確認。", "attention": True}
            if missing:
                return {"progress": f"已經收尾，但你電腦上的版本還少了 {missing} 個已合併的更新，還沒生效；按「更新筆記」同步。", "attention": True}
            return {"progress": "已經收尾，筆記也在派工後更新了；重新執行 /board 看下一步。", "finished": True}
        return {"progress": "worktree 已收掉，但筆記沒有在派工後更新；到 Orca 或 PR 看它停在哪。", "attention": True}
    try:
        terminals = orca("terminal", "list", "--worktree", f"path:{entry['path']}", timeout=15).get("terminals") or []
    except LaunchError:
        return {"progress": "還在進行，這次讀不到 Orca 的狀態。"}
    agent = next((t for t in terminals if t.get("handle") == entry.get("terminal")), None)
    if not agent or not agent.get("connected"):
        return {"progress": "agent 已經結束，但 worktree 還在；切到 Orca 看它停在哪。", "attention": True}
    result = pr_step(entry["path"], (agent.get("branch") or "").removeprefix("refs/heads/"))
    last = agent.get("lastOutputAt")
    quiet = int((time.time() * 1000 - last) / 60000) if isinstance(last, (int, float)) else 0
    if quiet >= QUIET_MINUTES:
        result = {"progress": f"{result['progress']}已經 {quiet} 分鐘沒有動靜，切到 Orca 看它是不是在等你。", "attention": True}
    return result


def upkeep_progress(entry: dict) -> dict:
    if upkeep_running(entry):
        return {"progress": "正在跑，跑完這裡會顯示結果。"}
    result = upkeep_result(entry)
    if result and not result.get("is_error"):
        return {"progress": "已完成；重新執行 /board 看結果。", "finished": True}
    # A run that dies before its result leaves an empty log; what it printed on the way out says why.
    errors = Path(entry["log"]).with_suffix(".err")
    where = errors if errors.is_file() and errors.stat().st_size else entry["log"]
    return {"progress": f"沒有正常跑完；紀錄在 {where}。", "attention": True}


def pr_step(worktree: str, branch: str) -> dict:
    """The delivery step the worktree's branch has reached on GitHub."""
    if not branch:
        # Finalization detaches the worktree after the merge; nothing else leaves it without a branch.
        return {"progress": "已合併，正在收尾。"}
    unread = {"progress": "還在進行，這次讀不到 GitHub 的狀態。"}
    try:
        done = subprocess.run(
            [GH, "pr", "view", branch, "--json", "state,statusCheckRollup"], cwd=worktree, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return unread
    if done.returncode:
        return {"progress": "實作中，還沒開 PR。"} if "no pull requests found" in done.stderr else unread
    try:
        pr = json.loads(done.stdout)
    except json.JSONDecodeError:
        return unread
    if not isinstance(pr, dict):
        return unread
    if pr.get("state") == "MERGED":
        return {"progress": "PR 已合併，正在收尾。"}
    if pr.get("state") == "CLOSED":
        return {"progress": "PR 被關掉了，沒有合併；切到 Orca 看原因。", "attention": True}
    checks = {"pass": "檢查都通過了", "pending": "檢查還在跑", "fail": "有檢查沒過，agent 會接著修", "none": "還沒有檢查結果"}
    return {"progress": f"PR 已開，{checks[ci_state(pr.get('statusCheckRollup'))]}。"}


# --- launches -----------------------------------------------------------------------------------



def worktree_name(key: str, now: datetime) -> str:
    # The branch and path; the owner recognizes the worktree by its display name, the card's title.
    # A prefixed key (`workstream:x`, `linear:Team/repo:ENG-1`) is named by its last part.
    base = re.sub(r"[^a-z0-9]+", "-", key.rsplit(":", 1)[-1].lower()).strip("-")[:32] or "fix"
    return f"{base}-{now:%m%d-%H%M}"


def assignment(action: dict, name: str, now: datetime, receipt: Path) -> str:
    if action["key"]:
        source = f"the `{action['key']}` workstream in {action['path']}/MEMORY.md"
    else:
        source = "the failing pull request named in the task"
    return f"""# Board dispatch assignment

The owner pressed 「派工」 on the {action['project']} board at {now:%Y-%m-%d %H:%M}. The card's task, verbatim:

{action['text']}

## The owner

{OWNER_LINE[bool(action.get("ask"))]} {OWNER_LANGUAGE}

## Grounding

- Repository: {action['project']}; primary checkout {action['path']}. You work in the Orca worktree
  `{name}`, created from the repository's default base; verify that base.
- Source: {source}, plus the repository's AGENTS.md. Treat recorded claims as hypotheses and
  revalidate them against live source before changing anything.
- The launcher created this worktree with Orca's setup skipped. If the repository's `orca.yaml` has
  `scripts.setup`, run it from the worktree root first and resolve any failure it reports.

## Endpoint

Start with the `endgame` skill: write its ENDGAME CONTRACT for this task with endpoint merge, then carry
it out through the receiver duties in {RECEIVER_CONTRACT}#receiver-delivery-ownership, in order:
implement and verify (or confirm nothing needs to change), merge through `$ship`, observe delivery
or verify asynchronous staging custody where the repository explicitly enables it, reconcile owning
tickets, fast-forward local main, write the workstream checkpoint with `$handoff` (remove the entry
when the outcome is complete), write the completion receipt to {receipt} and report it, and remove
this worktree last. The board shows that file to the owner once removal has closed this terminal, so
write it for them, in their language. Pending staging keeps its custody handle, remaining acceptance
gate, and owner in that receipt and checkpoint; report development complete, deployment pending.

## Authority

> User authorization: the owner's click on the board card above, under the owner's standing choice
> (2026-09-29) that board dispatches deliver through merge.
> Scope: {action['project']} ({action['path']}), the task above; destination: the repository's remote
> default branch.
> Authorized endpoint: full delivery.
> For full delivery, continue through implementation, verification, local commits, push,
> PR creation/updates, required review/checks, policy-compliant merge, owning-ticket reconciliation,
> primary synchronization, final checkpoint, and exact cleanup. Invoke `$ship`, `$handoff`, and
> `$latest` as needed under this assignment. Worktree removal is your last command.
> Task-scoped PR and owning-ticket writes are covered by the user's dispatch authorization and
> working-profile exception. Prepare and execute them without another permission request.
> Remaining human gates: the action-time confirmations in the owner's working profile (production
> data, irreversible migration, purchase, messages to people or external services, deletion of
> unmerged work).
"""


def memory_tracked(path: str) -> bool:
    """Whether the repository versions MEMORY.md, so a change to it is uncommitted work until it reaches the shared line.

    An unreadable answer counts as not versioned: the run then pushes nothing, which the owner can still ship.
    """
    try:
        done = subprocess.run(["git", "ls-files", "--error-unmatch", "MEMORY.md"], cwd=path, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def chore_assignment(action: dict, now: datetime, tracked: bool) -> str:
    """Upkeep runs one contract for the primary checkout and delivers nothing beyond the notes it changed.

    Where MEMORY.md is versioned, the notes it changed reach the shared line as a dispatch's checkpoint does, so the
    primary checkout never keeps them as an uncommitted edit.
    """
    button = CHORES[action["key"]]
    if tracked:
        endpoint = (
            "MEMORY.md is tracked in Git here: when the skill changed it, commit exactly MEMORY.md on the default\n"
            "branch, so the primary checkout keeps no uncommitted MEMORY.md change. Deliver that commit through\n"
            "`$ship` only while it is the one default-branch commit the remote lacks; otherwise keep it local and name\n"
            "the other unpushed commits in your report. Open no other pull request, push nothing else, and write no ticket."
        )
        granted = "plus one commit of exactly MEMORY.md delivered through `$ship`; no other push, pull request,\n> merge, or ticket write."
    else:
        endpoint = "Open no pull request, push nothing, merge nothing, and write no ticket."
        granted = "no push, pull request,\n> merge, or ticket write."
    return f"""# Board upkeep assignment

The owner pressed 「{button}」 on the {action['project']} board at {now:%Y-%m-%d %H:%M}. The task, verbatim:

{action['text']}

## The owner

Nobody reads this session while it runs; your final message is the report the board shows the owner.
If a step turns out to need the owner, stop before it and name it in that report. {OWNER_LANGUAGE}

## Grounding

- Repository: {action['project']}; you run headless in its primary checkout {action['path']}, where the
  owner or other agents may also be working: change only what the named upkeep contract owns, and edit MEMORY.md
  by hunk.
- Source: {action['path']}/MEMORY.md, the repository's Git state, and its AGENTS.md.

## Endpoint

Complete the named upkeep contract for the primary checkout, including its referenced skills. {endpoint} End with a short report of
what changed.

## Authority

> User authorization: the owner's click on the board's upkeep button above.
> Scope: {action['project']} ({action['path']}), the named upkeep contract only.
> Authorized endpoint: the named upkeep contract's result for the primary checkout; {granted}
> Remaining human gates: the action-time confirmations in the owner's working profile, and deletion of
> anything not proven merged or empty.
"""


def run_upkeep(action: dict, now: datetime) -> dict:
    """Start the upkeep agent headless in the primary checkout: the skill acts there, so a worktree would only
    add a create, a setup, and a removal around it."""
    UPKEEP_DIR.mkdir(parents=True, exist_ok=True)
    log = UPKEEP_DIR / f"{worktree_name(action['key'], now)}.json"
    argv = ["claude", "-p", chore_assignment(action, now, memory_tracked(action["path"])), "--permission-mode", "bypassPermissions",
            "--model", "opus", "--effort", "medium", "--output-format", "json"]
    try:
        with open(log, "w", encoding="utf-8") as out, open(log.with_suffix(".err"), "w", encoding="utf-8") as err:
            agent = subprocess.Popen(
                argv, cwd=action["path"], stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                start_new_session=True,
            )
    except OSError as exc:
        raise LaunchError(f"背景執行沒有啟動（{exc}）。", retry=True) from exc
    threading.Thread(target=agent.wait, daemon=True).start()  # reap it while this server lives
    return {"log": str(log), "agent_pid": agent.pid}


def dispatch(aid: str, action: dict) -> dict:
    """Hand the card's step to a new worktree agent that delivers it through merge."""
    now = datetime.now()
    if action["key"] in CHORES:
        return run_upkeep(action, now)
    name = worktree_name(action["key"], now)
    receipt = receipt_path(aid)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    ask = bool(action.get("ask"))
    subject = f"{action['project']} workstream `{action['key']}`" if action["key"] else action["project"]
    # The assignment file carries the task; the terminal line only names it and how it ends.
    if ask:
        goal = f"/endgame Board dispatch for {subject}; the owner is at this terminal."
    else:
        goal = (
            f"/goal The board dispatch for {subject} is delivered: merged or confirmed unneeded, local main "
            f"synced, checkpoint written, receipt written to {receipt}, and this worktree removed."
        )
    result = hand_off(
        action["path"], name, assignment(action, name, now, receipt), goal, label=action.get("title", ""),
        on_worktree=lambda n, p: note_worktree(aid, n, p),
    )
    if ask:
        try:  # bring the owner to the question; the launch already succeeded, so a failed switch only costs a click
            orca("terminal", "switch", "--terminal", result["terminal"], timeout=15)
        except LaunchError:
            pass
    return {k: result[k] for k in ("worktree", "path", "terminal")}


def run_launch(aid: str, action: dict) -> None:
    try:
        finish(aid, state="done", **dispatch(aid, action))
    except LaunchError as exc:
        finish(aid, state="failed", note=exc.note, retry=exc.retry, **({"terminal": exc.terminal} if exc.terminal else {}))
    except Exception as exc:  # noqa: BLE001 - an unexpected error must not leave the card spinning
        record_error(f"launch {action.get('project')}/{action.get('key')}", exc)
        finish(aid, state="failed", note=f"啟動器出錯：{exc}", retry=False)


def record_error(where: str, exc: BaseException) -> None:
    """Keep an unexpected error where the next /board run reports it; the traceback goes to launcher.log."""
    traceback.print_exc()
    try:
        BOARD_DIR.mkdir(parents=True, exist_ok=True)
        with open(ERRORS, "a", encoding="utf-8") as log:
            log.write(f"{datetime.now():%F %T} {where}: {type(exc).__name__}: {exc}\n")
    except OSError:
        pass  # the traceback above is still in launcher.log; the caller must go on to answer the page


# --- server -------------------------------------------------------------------------------------


class LaunchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, page: str, token: str, sock: socket.socket, marker: Path | None = None) -> None:
        super().__init__(sock.getsockname(), Handler, bind_and_activate=False)
        self.socket.close()  # the base class made an unbound socket; serve the inherited one instead
        self.socket = sock
        self.token = token
        match = ACTIONS.search(page)
        self.actions: dict = json.loads(match.group(1)) if match else {}
        self.borrowed: dict[str, str] = {}
        self.page = page.replace(TOKEN_SLOT, f'data-launch-token="{token}"', 1).encode()
        self.host = f"127.0.0.1:{self.server_address[1]}"
        self.last_seen = time.monotonic()
        self.running = 0
        self.lock = threading.Lock()
        # One server per page: each start writes its pid here, and an older server sees it lost the page.
        self.marker = marker
        if marker:
            # Replaced whole, so two servers starting at once never leave a pid that is neither's.
            staged = marker.with_suffix(f".{os.getpid()}")
            staged.write_text(str(os.getpid()), encoding="utf-8")
            os.replace(staged, marker)

    def launch(self, aid: str) -> None:
        with self.lock:
            self.running += 1
        try:
            run_launch(aid, self.actions[aid])
        finally:
            with self.lock:
                self.running -= 1
                self.last_seen = time.monotonic()

    def retiring(self) -> bool:
        """Idle for two hours, or replaced by a newer server for this page; a launch in progress finishes first."""
        try:
            superseded = bool(self.marker) and self.marker.read_text(encoding="utf-8") != str(os.getpid())
        except OSError:
            superseded = False
        with self.lock:
            return not self.running and (superseded or time.monotonic() - self.last_seen > IDLE_SECONDS)

    def watch_idle(self) -> None:
        while True:
            time.sleep(60)
            if self.retiring():
                self.shutdown()
                return


class Handler(BaseHTTPRequestHandler):
    @property
    def board(self) -> LaunchServer:
        return cast(LaunchServer, self.server)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"{datetime.now():%F %T} {format % args}\n")

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # The request line carries the page token in its query; log the path alone.
        self.log_message("%s %s %s", self.command, urlsplit(self.path).path, code)

    def reply(self, status: int, body: object, kind: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def trusted(self, supplied: str) -> bool:
        # The Host check stops DNS rebinding; the token stops every other local page.
        if self.headers.get("Host") != self.board.host or not hmac.compare_digest(supplied, self.board.token):
            return False
        self.board.last_seen = time.monotonic()  # only the page's own requests keep the server alive
        return True

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/":
            if not self.trusted(parse_qs(url.query).get("t", [""])[0]):
                return self.reply(403, {"error": "forbidden"})
            return self.reply(200, self.board.page, "text/html")
        if url.path == "/state":
            if not self.trusted(self.headers.get("X-Launch-Token", "")):
                return self.reply(403, {"error": "forbidden"})
            try:
                return self.reply(200, entries(self.board.actions, self.board.borrowed))
            except LaunchError as exc:
                return self.reply(500, {"state": "failed", "note": exc.note, "retry": False})
            except Exception as exc:  # noqa: BLE001 - the page must learn it cannot read progress
                record_error(f"{self.board.marker.stem if self.board.marker else 'page'} /state", exc)
                return self.reply(500, {"note": "看板讀不到派工進度，這一頁暫時不會更新。重新執行 /board，它會回報原因。"})
        self.reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/launch":
            return self.reply(404, {"error": "not found"})
        if not self.trusted(self.headers.get("X-Launch-Token", "")):
            return self.reply(403, {"error": "forbidden"})
        try:
            aid = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))).get("id")
        except (ValueError, AttributeError):
            aid = None
        action = self.board.actions.get(aid) if isinstance(aid, str) else None
        if not isinstance(aid, str) or not action or action.get("kind") != "dispatch":
            return self.reply(404, {"error": "unknown action"})
        try:
            existing = claim(aid, action)
        except LaunchError as exc:
            return self.reply(500, {"state": "failed", "note": exc.note, "retry": False})
        if existing:
            return self.reply(409, public(existing))
        threading.Thread(target=self.board.launch, args=(aid,), daemon=False).start()
        self.reply(202, {"state": "running", "kind": action["kind"]})


def start(page: Path) -> str:
    """Start a detached server for this page and return the URL that opens it."""
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    sock = socket.create_server(("127.0.0.1", 0))
    token = secrets.token_urlsafe(24)
    with open(LOG, "a") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "serve", "--page", str(page), "--fd", str(sock.fileno())],
            env={**os.environ, "BOARD_LAUNCH_TOKEN": token},
            pass_fds=[sock.fileno()],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/?t={token}"


# A board server's URL; an earlier run's tab still holds one after its server exits.
BOARD_URL = re.compile(r"http://127\.0\.0\.1:\d+/\?t=")


def show(url: str, worktree: str) -> None:
    """Show the page in Orca's browser in `worktree`, reusing the tab an earlier board run left there."""
    tabs = orca("tab", "list", "--worktree", worktree, timeout=15).get("tabs") or []
    tab = next((t["browserPageId"] for t in tabs if BOARD_URL.match(t.get("url") or "")), None)
    if tab:
        orca("goto", "--page", tab, "--worktree", worktree, "--url", url, timeout=30)
    else:
        tab = orca("tab", "create", "--url", url, "--worktree", worktree, timeout=30).get("browserPageId")
    orca("tab", "switch", "--page", tab, "--worktree", worktree, "--focus", timeout=15)


def serve(page: Path, fd: int) -> None:
    server = LaunchServer(
        page.read_text(encoding="utf-8"), os.environ.pop("BOARD_LAUNCH_TOKEN"), socket.socket(fileno=fd), page.with_suffix(".server"),
    )
    print(f"{datetime.now():%F %T} serving {page} on {server.host} ({len(server.actions)} actions)", file=sys.stderr, flush=True)
    threading.Thread(target=server.watch_idle, daemon=True).start()
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serving = sub.add_parser("serve", help="serve one board page on an inherited socket (started by board.py --open)")
    serving.add_argument("--page", type=Path, required=True)
    serving.add_argument("--fd", type=int, required=True)
    args = parser.parse_args(argv)
    serve(args.page, args.fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
