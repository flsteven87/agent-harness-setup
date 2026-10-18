#!/usr/bin/env python3
"""Launch one explicitly configured YOLO agent in an existing Orca worktree.

This adapter owns runtime configuration only. It does not create a worktree, deliver a
prompt, monitor the assignment, repeat terminal creation, or grant delivery authority.
Transient readiness timeouts resume waiting on the same terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


SCHEMA = "milestone-dispatch-yolo-launch/v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class LaunchFailure(Exception):
    phase: str
    message: str
    terminal_handle: str | None = None
    created_state: str = "none"
    timed_out: bool = False

    def __str__(self) -> str:
        return self.message


Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def resolve_orca_command(
    env: Mapping[str, str] | None = None,
    system: str | None = None,
) -> list[str]:
    """Resolve the session's Orca CLI without evaluating shell syntax."""
    current_env = os.environ if env is None else env
    configured = current_env.get("ORCA_CLI_COMMAND", "").strip()
    if configured:
        command = shlex.split(configured)
        if not command:
            raise ValueError("ORCA_CLI_COMMAND did not contain an executable")
        return command
    if current_env.get("ORCA_DEV_REPO_ROOT"):
        return ["orca-dev"]

    current_system = platform.system() if system is None else system
    in_managed_terminal = bool(
        current_env.get("ORCA_TERMINAL_HANDLE") or current_env.get("ORCA_WORKTREE_ID")
    )
    if current_system == "Linux" and not in_managed_terminal:
        return ["orca-ide"]
    return ["orca"]


def _require_identifier(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a provider identifier, not shell syntax")
    return value


def _require_text(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    if CONTROL_CHARACTER.search(value):
        raise ValueError(f"{label} must not contain control characters")
    return value


def build_agent_command(
    agent: str,
    model: str | None = None,
    effort: str | None = None,
    service_tier: str | None = None,
) -> tuple[str, dict[str, object]]:
    """Build a reviewed provider command and its autonomy receipt."""
    checked_model = _require_identifier(model, "model")
    checked_effort = _require_identifier("medium" if effort is None else effort, "effort")
    if agent != "codex" and service_tier is not None:
        raise ValueError("service tier applies only to Codex")

    if agent == "codex":
        argv = [
            "codex",
            "--ask-for-approval",
            "never",
            "--sandbox",
            "danger-full-access",
        ]
        if checked_model:
            argv.extend(["--model", checked_model])
        argv.extend(["--config", f'model_reasoning_effort="{checked_effort}"'])
        checked_tier = _require_identifier("fast" if service_tier is None else service_tier, "service tier")
        argv.extend(["--config", f'service_tier="{checked_tier}"'])
        autonomy: dict[str, object] = {
            "mode": "yolo",
            "configured": True,
            "approval_policy": "never",
            "sandbox": "danger-full-access",
        }
    elif agent == "claude":
        argv = ["claude", "--permission-mode", "bypassPermissions"]
        if checked_model:
            argv.extend(["--model", checked_model])
        argv.extend(["--effort", checked_effort])
        autonomy = {
            "mode": "yolo",
            "configured": True,
            "permission_mode": "bypassPermissions",
        }
    else:
        raise ValueError("agent must be one of: codex, claude")

    return shlex.join(argv), autonomy


def _default_runner(argv: Sequence[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _error_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "no diagnostic output").strip()
    return detail[-1000:]


def _invoke_json(
    argv: Sequence[str],
    phase: str,
    timeout_seconds: float,
    runner: Runner,
    terminal_handle: str | None = None,
) -> dict[str, object]:
    try:
        result = runner(argv, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise LaunchFailure(
            phase,
            f"Orca command timed out after {timeout_seconds:g}s",
            terminal_handle,
            "unknown" if phase == "terminal_create" else "none",
            timed_out=True,
        ) from exc
    except OSError as exc:
        raise LaunchFailure(phase, f"Orca command could not start: {exc}", terminal_handle) from exc

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LaunchFailure(
            phase,
            f"Orca did not return valid JSON: {_error_detail(result)}",
            terminal_handle,
            "unknown" if phase == "terminal_create" else "none",
        ) from exc
    if result.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is not True:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise LaunchFailure(
            phase,
            f"Orca rejected the command (exit {result.returncode}): {detail or _error_detail(result)}",
            terminal_handle,
            "unknown" if phase == "terminal_create" else "none",
            timed_out=isinstance(detail, dict) and detail.get("code") == "timeout",
        )
    return payload


def _terminal_inventory(
    payload: dict[str, object],
    phase: str,
    terminal_handle: str | None = None,
) -> list[dict[str, object]]:
    result = payload.get("result")
    terminals = result.get("terminals") if isinstance(result, dict) else None
    if not isinstance(terminals, list) or not all(isinstance(item, dict) for item in terminals):
        raise LaunchFailure(
            phase,
            "Orca receipt omitted the terminal inventory",
            terminal_handle,
        )
    return terminals


def _reconcile_create_failure(
    failure: LaunchFailure,
    *,
    orca: Sequence[str],
    worktree: str,
    timeout_seconds: float,
    runner: Runner,
) -> LaunchFailure:
    """Reconcile an ambiguous create result without retrying the mutation."""
    try:
        payload = _invoke_json(
            [*orca, "terminal", "list", "--worktree", worktree, "--json"],
            "terminal_reconciliation",
            timeout_seconds,
            runner,
        )
        terminals = _terminal_inventory(payload, "terminal_reconciliation")
    except LaunchFailure as reconciliation_failure:
        return LaunchFailure(
            failure.phase,
            f"{failure.message}; terminal inventory reconciliation failed: "
            f"{reconciliation_failure.message}",
            created_state="unknown",
        )

    if not terminals:
        return failure
    if len(terminals) == 1:
        handle = terminals[0].get("handle")
        runtime_worktree_id = terminals[0].get("worktreeId")
        if isinstance(handle, str) and handle and isinstance(runtime_worktree_id, str) and runtime_worktree_id:
            return LaunchFailure(
                failure.phase,
                f"{failure.message}; recovered the sole created terminal from inventory",
                handle,
                "preserved",
            )
    return LaunchFailure(
        failure.phase,
        f"{failure.message}; terminal inventory is ambiguous after create",
        created_state="unknown",
    )


def launch_yolo_agent(
    *,
    worktree: str,
    agent: str,
    model: str | None = None,
    effort: str | None = None,
    service_tier: str | None = None,
    title: str | None = None,
    timeout_ms: int = 60_000,
    orca_command: Sequence[str] | None = None,
    runner: Runner = _default_runner,
) -> dict[str, object]:
    """Create exactly one agent terminal and wait only for its initial TUI readiness."""
    checked_worktree = _require_text(worktree, "worktree")
    checked_title = _require_text(title or f"{agent}-yolo", "title")
    if timeout_ms <= 0:
        raise ValueError("timeout-ms must be positive")

    agent_command, autonomy = build_agent_command(agent, model, effort, service_tier)
    orca = list(orca_command or resolve_orca_command())
    timeout_seconds = timeout_ms / 1000

    preflight_payload = _invoke_json(
        [
            *orca,
            "terminal",
            "list",
            "--worktree",
            checked_worktree,
            "--json",
        ],
        "terminal_preflight",
        timeout_seconds,
        runner,
    )
    existing_terminals = _terminal_inventory(preflight_payload, "terminal_preflight")
    if existing_terminals:
        raise LaunchFailure(
            "terminal_preflight",
            "Target worktree already has a terminal; preserve it and resolve single-writer ownership first",
        )

    try:
        create_payload = _invoke_json(
            [
                *orca,
                "terminal",
                "create",
                "--worktree",
                checked_worktree,
                "--title",
                checked_title,
                "--command",
                agent_command,
                "--json",
            ],
            "terminal_create",
            timeout_seconds,
            runner,
        )
        create_result = create_payload.get("result")
        terminal = create_result.get("terminal") if isinstance(create_result, dict) else None
        if not isinstance(terminal, dict):
            raise LaunchFailure(
                "terminal_create",
                "Orca receipt omitted the terminal handle",
                created_state="unknown",
            )
        handle = terminal.get("handle")
        if not isinstance(handle, str) or not handle:
            raise LaunchFailure(
                "terminal_create",
                "Orca receipt omitted the terminal handle",
                created_state="unknown",
            )
        runtime_worktree_id = terminal.get("worktreeId")
        if not isinstance(runtime_worktree_id, str) or not runtime_worktree_id:
            raise LaunchFailure("terminal_create", "Orca receipt omitted the runtime worktree ID", handle)
    except LaunchFailure as failure:
        if failure.terminal_handle is not None:
            raise
        raise _reconcile_create_failure(
            failure,
            orca=orca,
            worktree=checked_worktree,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )

    # Only the read-only wait is repeated; creation and prompt delivery stay single-shot.
    for readiness_attempt in range(1, 4):
        try:
            wait_payload = _invoke_json(
                [
                    *orca,
                    "terminal",
                    "wait",
                    "--terminal",
                    handle,
                    "--for",
                    "tui-idle",
                    "--timeout-ms",
                    str(min(timeout_ms, 55_000)),
                    "--json",
                ],
                "tui_readiness",
                min(timeout_seconds, 55) + 5,
                runner,
                handle,
            )
            wait_result = wait_payload.get("result")
            wait_receipt = wait_result.get("wait") if isinstance(wait_result, dict) else None
            if not isinstance(wait_receipt, dict):
                raise LaunchFailure("tui_readiness", "Orca receipt omitted the readiness result", handle)
            if wait_receipt.get("handle") != handle:
                raise LaunchFailure("tui_readiness", "Orca readiness receipt named another terminal", handle)
            if wait_receipt.get("satisfied") is not True:
                raise LaunchFailure("tui_readiness", "Agent TUI did not become ready", handle)
            if wait_receipt.get("status") != "running":
                raise LaunchFailure("tui_readiness", "Agent terminal was not running after readiness", handle)
            break
        except LaunchFailure as failure:
            if not failure.timed_out or readiness_attempt == 3:
                raise
            print(
                f"Readiness wait {readiness_attempt}/3 timed out for {handle}; "
                "continuing on the same terminal without relaunching.",
                file=sys.stderr,
                flush=True,
            )

    ownership_payload = _invoke_json(
        [
            *orca,
            "terminal",
            "list",
            "--worktree",
            checked_worktree,
            "--json",
        ],
        "terminal_ownership",
        timeout_seconds,
        runner,
        handle,
    )
    current_terminals = _terminal_inventory(
        ownership_payload,
        "terminal_ownership",
        handle,
    )
    if len(current_terminals) != 1 or current_terminals[0].get("handle") != handle:
        raise LaunchFailure(
            "terminal_ownership",
            "Target worktree does not have exactly the created agent terminal",
            handle,
        )
    if current_terminals[0].get("worktreeId") != runtime_worktree_id:
        raise LaunchFailure(
            "terminal_ownership",
            "Terminal inventory named another runtime worktree",
            handle,
        )
    if current_terminals[0].get("agentIdentity") != agent:
        raise LaunchFailure(
            "terminal_ownership",
            "Terminal inventory did not confirm the requested agent identity",
            handle,
        )

    return {
        "schema": SCHEMA,
        "ok": True,
        "phase": "ready",
        "agent": agent,
        "model": model,
        "effort": effort or "medium",
        "service_tier": (service_tier or "fast") if agent == "codex" else None,
        "worktree": checked_worktree,
        "runtime_worktree_id": runtime_worktree_id,
        "terminal_handle": handle,
        "autonomy": autonomy,
        "prompt_delivery": "not_attempted",
        "automatic_mutation_retry": False,  # Terminal creation is never retried.
        "readiness_attempts": readiness_attempt,
    }


def _failure_receipt(
    failure: LaunchFailure,
    *,
    worktree: str,
    agent: str,
) -> dict[str, object]:
    created_state = "preserved" if failure.terminal_handle is not None else failure.created_state
    created_state_preserved: bool | None
    if created_state == "preserved":
        created_state_preserved = True
    elif created_state == "none":
        created_state_preserved = False
    else:
        created_state_preserved = None
    return {
        "schema": SCHEMA,
        "ok": False,
        "phase": failure.phase,
        "agent": agent,
        "worktree": worktree,
        "terminal_handle": failure.terminal_handle,
        "created_state": created_state,
        "created_state_preserved": created_state_preserved,
        "operator_action": (
            "Inspect the exact worktree terminal inventory before any retry"
            if created_state == "unknown"
            else "Resume readiness checks on the named terminal; verify ownership and launch "
            "configuration before first prompt delivery; do not relaunch"
            if failure.phase == "tui_readiness" and failure.timed_out
            else "Preserve the named terminal; do not relaunch or redeliver the prompt"
            if created_state == "preserved"
            else "No created terminal was observed"
        ),
        "prompt_delivery": "not_attempted",
        "automatic_mutation_retry": False,
        "error": failure.message,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, help="Existing Orca worktree selector")
    parser.add_argument("--agent", required=True, choices=("codex", "claude"))
    parser.add_argument("--model", help="Optional provider model identifier")
    parser.add_argument("--effort", help="Provider reasoning-effort identifier (default: medium)")
    parser.add_argument("--service-tier", help="Codex service tier (default: fast)")
    parser.add_argument("--title", help="Optional Orca terminal title")
    parser.add_argument(
        "--timeout-ms", type=int, default=60_000,
        help="Per-command timeout; readiness waits use at most 55000 ms each, up to three attempts",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = launch_yolo_agent(
            worktree=args.worktree,
            agent=args.agent,
            model=args.model,
            effort=args.effort,
            service_tier=args.service_tier,
            title=args.title,
            timeout_ms=args.timeout_ms,
        )
    except ValueError as exc:
        failure = LaunchFailure("input_validation", str(exc))
        print(json.dumps(_failure_receipt(failure, worktree=args.worktree, agent=args.agent), sort_keys=True))
        return 2
    except LaunchFailure as exc:
        print(json.dumps(_failure_receipt(exc, worktree=args.worktree, agent=args.agent), sort_keys=True))
        return 1

    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
