#!/usr/bin/env python3
"""Hand one resolved assignment to a new YOLO receiver in its own Orca worktree.

This is the single dispatch implementation: milestone-dispatch's Dispatch mode runs it from the command
line, and the board's 「派工」 button imports it. It creates the worktree with Orca's setup skipped (the
receiver runs the repository's setup itself and sees its failures), closes the fallback shell, starts
the receiver through the reviewed launcher, writes the assignment to `endgame-assignment.md` in the
worktree's Git directory, and sends the goal with a pointer to it. Each mutation runs once; a failure
reports whether it created nothing (`retry`) and names any worktree it preserved.

    dispatch.py --repo PATH --name NAME [--label TEXT] --assignment FILE --goal TEXT [--base REF]
                [--agent claude|codex] [--model MODEL] [--effort EFFORT] [--service-tier TIER]

prints one JSON receipt: {"ok": true, "worktree", "path", "terminal", "assignment"} or
{"ok": false, "error", "retry", "worktree", "path"}.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

YOLO_LAUNCHER = Path(__file__).with_name("launch_yolo_agent.py")
# Orca still lists a closed tab for about two seconds (observed 2026-09-30), and the reviewed launcher refuses
# a worktree that lists any terminal, so a close counts only once the list is empty.
CLOSE_SETTLE_SECONDS = 15


class LaunchError(Exception):
    """A launch that did not finish; `retry` is true only when it created nothing, and `terminal` names the
    receiver when it had already started, so a caller can observe whether the receiver ran after all."""

    def __init__(self, note: str, retry: bool = False, worktree: str = "", path: str = "", terminal: str = "") -> None:
        super().__init__(note)
        self.note = note
        self.retry = retry
        self.worktree = worktree
        self.path = path
        self.terminal = terminal


# The owner reads the receiver's terminal. An English line here pulls every reply into English whatever the
# assignment says, so the line itself states the language, in that language.
TERMINAL_LANGUAGE = "這個終端機裡的每句話都用繁體中文寫，不用簡體；程式碼、commit、PR 和 repository 文件維持原本的語言。"


def orca(*args: str, retry: bool = False, timeout: int = 90) -> dict:
    """Run one Orca CLI command and return its result; `retry` says whether a failure left nothing behind."""
    try:
        done = subprocess.run(["orca", *args, "--json"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LaunchError(f"Orca 沒有回應（{' '.join(args[:2])}），結果不確定；先到 Orca 看一下。") from exc
    except OSError as exc:
        raise LaunchError("這台電腦找不到 orca 指令。", retry=retry) from exc
    try:
        payload = json.loads(done.stdout)
    except json.JSONDecodeError:
        payload = None
    if done.returncode or not isinstance(payload, dict) or payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload, dict) else None
        detail = error.get("message") if isinstance(error, dict) else error or (done.stderr or done.stdout).strip()[-200:]
        # Only an explicit rejection proves nothing was made; garbled output leaves the result unknown.
        rejected = isinstance(payload, dict) and payload.get("ok") is False
        raise LaunchError(f"Orca 沒有完成 {' '.join(args[:2])}：{detail}", retry=retry and rejected)
    return payload.get("result") or {}


def dispatch(
    repo: str,
    name: str,
    assignment: str,
    goal: str,
    *,
    base: str = "",
    agent: str = "codex",
    model: str | None = None,
    effort: str = "medium",
    service_tier: str | None = None,
    label: str = "",
    on_worktree: Callable[[str, str], None] | None = None,
) -> dict:
    """Create the worktree, start the receiver, and deliver the assignment; `on_worktree(name, path)` runs
    as soon as the worktree exists, so a caller can record it before anything else can fail.

    `label` is what the owner reads in Orca for the worktree and its terminal: the task in their words,
    where `name` stays the ASCII branch and path."""
    if agent != "codex" and service_tier is not None:
        raise LaunchError("service tier 只適用於 Codex。", retry=True)
    model = model or ("gpt-6.1-sol" if agent == "codex" else "opus")
    create = ["worktree", "create", "--repo", f"path:{repo}", "--name", name, "--no-parent", "--setup", "skip"]
    if base:
        create += ["--base-branch", base]
    worktree = orca(*create, retry=True).get("worktree") or {}
    if not worktree.get("id") or not worktree.get("path"):
        raise LaunchError(f"Orca 沒有回報新 worktree「{name}」的位置；先到 Orca 看一下。")
    path = worktree["path"]
    if on_worktree:
        on_worktree(name, path)
    selector = f"id:{worktree['id']}"
    if label:
        try:
            orca("worktree", "set", "--worktree", selector, "--display-name", label)
        except LaunchError:
            pass  # a label that did not stick leaves the ASCII name; it must not strand a created worktree
    try:
        return _start(name, path, selector, assignment, goal, agent, model, effort, label or name, service_tier)
    except LaunchError as exc:
        exc.worktree, exc.path, exc.retry = name, path, False
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise LaunchError(f"啟動途中出錯（{exc}）；worktree「{name}」已保留。", worktree=name, path=path) from exc


def _start(
    name: str, path: str, selector: str, assignment: str, goal: str, agent: str, model: str, effort: str, title: str,
    service_tier: str | None = None,
) -> dict:
    """Everything after the worktree exists; the caller attaches the worktree to any failure."""
    # A bare create opens one fallback shell; the reviewed launcher needs a worktree with no terminal. With
    # setup skipped, nothing has run in a shell Orca opened for this brand-new worktree, so closing it is safe.
    terminals = orca("terminal", "list", "--worktree", selector).get("terminals") or []
    if len(terminals) > 1 or any(t.get("agentIdentity") for t in terminals):
        raise LaunchError(f"新 worktree「{name}」一開就有別的終端機在跑，已保留不動；先到 Orca 看一下。")
    for terminal in terminals:
        orca("terminal", "close", "--terminal", terminal["handle"], "--tab")
    deadline = time.monotonic() + CLOSE_SETTLE_SECONDS
    while terminals:
        time.sleep(0.5)
        terminals = orca("terminal", "list", "--worktree", selector).get("terminals") or []
        if terminals and time.monotonic() > deadline:
            raise LaunchError(f"新 worktree「{name}」的預設終端機關不掉，已保留不動；先到 Orca 看一下。")
    launch_command = [sys.executable, str(YOLO_LAUNCHER), "--worktree", selector, "--agent", agent,
                      "--model", model, "--effort", effort, "--title", title]
    if agent == "codex":
        launch_command += ["--service-tier", service_tier or "fast"]
    launched = subprocess.run(
        launch_command,
        capture_output=True, text=True, timeout=300,
    )
    try:
        receipt = json.loads(launched.stdout)
    except json.JSONDecodeError:
        receipt = {"phase": "launch", "error": (launched.stderr or launched.stdout).strip()[-200:]}
    if receipt.get("ok") is not True:
        raise LaunchError(f"agent 沒有順利啟動（{receipt.get('phase')}：{receipt.get('error')}）；worktree「{name}」已保留。")
    handle = receipt["terminal_handle"]
    try:
        git_dir = subprocess.run(
            ["git", "-C", path, "rev-parse", "--absolute-git-dir"], capture_output=True, text=True, check=True
        ).stdout.strip()
        brief = Path(git_dir, "endgame-assignment.md")
        brief.write_text(assignment, encoding="utf-8")
        sent = orca(
            "terminal", "send", "--terminal", handle,
            "--text", f"{goal} Read the full assignment at {brief} before acting. {TERMINAL_LANGUAGE}",
            "--enter", "--wait-submit", "20",
        )
    except LaunchError as exc:
        exc.terminal = handle
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise LaunchError(f"啟動途中出錯（{exc}）；worktree「{name}」已保留。", terminal=handle) from exc
    # Delivery counts only when Orca says the input was accepted (`result.send.accepted`); anything else leaves
    # it unproved.
    if (sent.get("send") or {}).get("accepted") is not True:
        raise LaunchError(
            f"agent 已啟動，但沒確認收下派工內容；worktree「{name}」已保留，到 Orca 看它有沒有收到，沒有就把內容貼給它。",
            terminal=handle,
        )
    return {"worktree": name, "path": path, "terminal": handle, "assignment": str(brief)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="primary checkout path of the target repository")
    parser.add_argument("--name", required=True, help="new Orca worktree name: the ASCII branch and path")
    parser.add_argument("--label", default="", help="what the owner reads in Orca: the milestone in their words")
    parser.add_argument("--assignment", type=Path, required=True, help="file holding the full assignment")
    parser.add_argument("--goal", required=True, help="the /goal line: the milestone's ENDGAME CONTRACT, under 4,000 characters")
    parser.add_argument("--base", default="", help="base ref when prerequisites require one (default: Orca's default base)")
    parser.add_argument("--agent", choices=("claude", "codex"), default="codex")
    parser.add_argument("--model", help="Provider model (default: gpt-6.1-sol for Codex, opus for Claude)")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--service-tier", help="Codex service tier (default: fast)")
    args = parser.parse_args(argv)
    try:
        result = dispatch(
            args.repo, args.name, args.assignment.read_text(encoding="utf-8"), args.goal,
            base=args.base, agent=args.agent, model=args.model, effort=args.effort, label=args.label,
            service_tier=args.service_tier,
        )
    except LaunchError as exc:
        print(json.dumps({"ok": False, "error": exc.note, "retry": exc.retry, "worktree": exc.worktree, "path": exc.path},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
