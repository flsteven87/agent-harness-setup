#!/usr/bin/env python3
"""Audit Git convergence state without changing local branches or worktrees."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(
    r"(github_pat_[A-Za-z0-9_]+|gh[opsur]_[A-Za-z0-9_]{10,}|"
    r"glpat-[A-Za-z0-9_-]{10,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"sk-[A-Za-z0-9]{20,})"
)
CREDENTIAL_URL_RE = re.compile(r"(https?://)[^/\s:@]+(?::[^/\s@]*)?@")
GH_CLI = (Path.home() / '.local/bin/gh')
PATH_GROUP_LIMIT = 10


class GitCommandError(RuntimeError):
    """Raised when a required Git inspection command fails."""

    def __init__(self, result: Result) -> None:
        command = " ".join(result.command)
        detail = f": {result.output}" if result.output else ""
        super().__init__(f"{command} failed with exit {result.exit_code}{detail}")
        self.result = result


@dataclass(frozen=True)
class Result:
    command: list[str]
    exit_code: int
    output: str


def redact(text: str) -> str:
    text = CREDENTIAL_URL_RE.sub(r"\1<redacted>@", text)
    return TOKEN_RE.sub("<redacted-token>", text)


def run(
    args: list[str],
    *,
    cwd: Path,
    input_bytes: bytes | None = None,
    timeout: int = 180,
) -> Result:
    """Run one inspection command and return redacted combined output."""
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
        raw = (completed.stdout or b"").decode(errors="surrogateescape")
        return Result(args, completed.returncode, redact(raw.rstrip("\r\n")))
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        if isinstance(raw, str):
            raw = raw.encode(errors="surrogateescape")
        output_text = raw.decode(errors="surrogateescape").rstrip("\r\n")
        return Result(
            args,
            124,
            redact(f"{output_text}\nTimed out after {timeout}s"),
        )


def git(args: list[str], *, cwd: Path, timeout: int = 180) -> Result:
    return run(["git", *args], cwd=cwd, timeout=timeout)


def output(args: list[str], *, cwd: Path) -> str:
    result = git(args, cwd=cwd)
    if result.exit_code != 0:
        raise GitCommandError(result)
    return result.output


def resolve_repo(path: Path) -> Path:
    result = git(["rev-parse", "--show-toplevel"], cwd=path)
    if result.exit_code != 0:
        raise RuntimeError(result.output or "Not a Git repository")
    return Path(result.output).resolve()


def verify_ref(repo: Path, ref: str) -> str | None:
    result = git(["rev-parse", "--verify", ref], cwd=repo)
    return result.output if result.exit_code == 0 else None


def remote_names(repo: Path) -> list[str]:
    return [name for name in output(["remote"], cwd=repo).splitlines() if name]


def canonical_remote(repo: Path) -> str:
    """Resolve one canonical remote from default-branch and repository config."""
    remotes = remote_names(repo)
    if not remotes:
        raise RuntimeError("Repository has no remote")

    configured: list[str] = []
    for protected in ("main", "master"):
        if verify_ref(repo, f"refs/heads/{protected}") is None:
            continue
        tracked = git(["config", "--get", f"branch.{protected}.remote"], cwd=repo)
        if tracked.exit_code == 0 and tracked.output in remotes:
            configured.append(tracked.output)
    configured = list(dict.fromkeys(configured))
    if len(configured) == 1:
        return configured[0]
    if len(configured) > 1:
        raise RuntimeError(f"Canonical remote is ambiguous: {', '.join(configured)}")

    headed: list[str] = []
    for remote in remotes:
        symbolic = git(
            ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
            cwd=repo,
        )
        if symbolic.exit_code == 0 and symbolic.output.startswith(f"{remote}/"):
            headed.append(remote)
    if len(headed) == 1:
        return headed[0]

    current = git(["branch", "--show-current"], cwd=repo)
    if current.exit_code == 0 and current.output:
        tracked = git(["config", "--get", f"branch.{current.output}.remote"], cwd=repo)
        if tracked.exit_code == 0 and tracked.output in remotes:
            configured.append(tracked.output)
    push_default = git(["config", "--get", "remote.pushDefault"], cwd=repo)
    if push_default.exit_code == 0 and push_default.output in remotes:
        configured.append(push_default.output)
    configured = list(dict.fromkeys(configured))
    if len(configured) == 1:
        return configured[0]
    if len(configured) > 1:
        raise RuntimeError(f"Canonical remote is ambiguous: {', '.join(configured)}")
    if len(remotes) == 1:
        return remotes[0]
    raise RuntimeError(f"Canonical remote is ambiguous: {', '.join(remotes)}")


def default_remote_ref(repo: Path) -> tuple[str, str, str]:
    remote = canonical_remote(repo)
    symbolic = git(
        ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
        cwd=repo,
    )
    if symbolic.exit_code == 0 and symbolic.output.startswith(f"{remote}/"):
        branch = symbolic.output.removeprefix(f"{remote}/")
        return remote, branch, symbolic.output
    for branch in ("main", "master"):
        ref = f"{remote}/{branch}"
        if verify_ref(repo, ref) is not None:
            return remote, branch, ref
    raise RuntimeError(f"No default branch found for canonical remote {remote}")


def unreadable_status(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "clean": False,
        "staged": 0,
        "unstaged": 0,
        "unmerged": 0,
        "untracked": 0,
        "counts": {},
        "entries_total": 0,
        "entries": [],
        "entry_records": [],
        "entries_omitted": 0,
        "groups": [],
        "groups_omitted": 0,
        "token": hashlib.sha256(f"error:{error}".encode()).hexdigest(),
    }


def status_counts(repo: Path, *, include_entries: bool = False) -> dict[str, Any]:
    """Parse porcelain-v2 status without treating filenames as line-oriented."""
    result = git(["status", "--porcelain=v2", "-z", "--untracked-files=all"], cwd=repo)
    if result.exit_code != 0:
        return unreadable_status(result.output or "git status failed")

    records = result.output.split("\0")
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        categories: list[str] = []
        display = record
        path = ""
        if record.startswith("? "):
            categories = ["untracked"]
            path = record[2:]
        elif record.startswith("! "):
            continue
        elif record.startswith("u "):
            categories = ["unmerged"]
            path = record.split(" ", 10)[-1]
        elif record.startswith(("1 ", "2 ")):
            limit = 9 if record.startswith("2 ") else 8
            fields = record.split(" ", limit)
            xy = fields[1]
            if xy[0] != ".":
                categories.append("staged")
            if xy[1] != ".":
                categories.append("unstaged")
            path = fields[-1]
            if record.startswith("2 ") and index < len(records):
                original = records[index]
                index += 1
                display = f"{record}\0{original}"
        else:
            continue
        entries.append({"path": path, "categories": categories, "raw": display})

    counts = Counter(category for item in entries for category in item["categories"])
    group_counts: Counter[str] = Counter()
    for item in entries:
        parts = Path(item["path"]).parts
        group_counts[parts[0] if len(parts) > 1 else "."] += 1
    grouped = sorted(group_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    groups = [
        {"path": path, "count": count} for path, count in grouped[:PATH_GROUP_LIMIT]
    ]
    return {
        "ok": True,
        "error": None,
        "clean": not entries,
        "staged": counts["staged"],
        "unstaged": counts["unstaged"],
        "unmerged": counts["unmerged"],
        "untracked": counts["untracked"],
        "counts": dict(counts),
        "entries_total": len(entries),
        "entries": [item["raw"] for item in entries] if include_entries else [],
        "entry_records": entries if include_entries else [],
        "entries_omitted": 0 if include_entries else len(entries),
        "groups": groups,
        "groups_omitted": max(0, len(grouped) - len(groups)),
        "token": hashlib.sha256(
            result.output.encode(errors="surrogateescape")
        ).hexdigest(),
    }


def ignored_entry_count(repo: Path) -> int | None:
    """Count ignored status entries without exposing their paths."""
    result = git(
        [
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
        ],
        cwd=repo,
    )
    if result.exit_code != 0:
        return None
    return sum(1 for record in result.output.split("\0") if record.startswith("! "))


def operation_state(path: Path) -> list[str]:
    probes = {
        "merge": "MERGE_HEAD",
        "rebase": "rebase-merge",
        "rebase-apply": "rebase-apply",
        "bisect": "BISECT_LOG",
        "cherry-pick": "CHERRY_PICK_HEAD",
        "revert": "REVERT_HEAD",
        "sequencer": "sequencer",
    }
    active: list[str] = []
    for label, git_path in probes.items():
        resolved = git(["rev-parse", "--git-path", git_path], cwd=path)
        resolved_path = Path(resolved.output)
        if not resolved_path.is_absolute():
            resolved_path = path / resolved_path
        if resolved.exit_code == 0 and resolved_path.exists():
            active.append(label)
    return active


def attention_reasons(worktree: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = worktree["status"]
    if not status["ok"]:
        reasons.append("status unreadable")
    elif not status["clean"]:
        reasons.append("dirty")
    if worktree.get("locked"):
        reasons.append("locked")
    if worktree.get("prunable"):
        reasons.append("prunable")
    if worktree["operations"]:
        reasons.append("Git operation: " + ", ".join(worktree["operations"]))
    return reasons


def parse_worktrees(repo: Path) -> list[dict[str, Any]]:
    raw = output(["worktree", "list", "--porcelain", "-z"], cwd=repo)
    groups: list[list[str]] = []
    current: list[str] = []
    for field in raw.split("\0"):
        if field:
            current.append(field)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    worktrees: list[dict[str, Any]] = []
    for fields in groups:
        record: dict[str, Any] = {
            "path": "",
            "head": "",
            "branch": None,
            "detached": False,
            "locked": None,
            "prunable": None,
        }
        for field in fields:
            key, _, value = field.partition(" ")
            if key == "worktree":
                record["path"] = value
            elif key == "HEAD":
                record["head"] = value
            elif key == "branch":
                record["branch"] = value.removeprefix("refs/heads/")
            elif key == "detached":
                record["detached"] = True
            elif key == "locked":
                record["locked"] = value or True
            elif key == "prunable":
                record["prunable"] = value or True
        path = Path(record["path"])
        if path.exists():
            record["status"] = status_counts(path)
            record["ignored_entry_count"] = ignored_entry_count(path)
            record["operations"] = operation_state(path)
        else:
            record["status"] = unreadable_status("worktree path is missing")
            record["ignored_entry_count"] = None
            record["operations"] = []
        record["attention"] = attention_reasons(record)
        worktrees.append(record)
    return worktrees


def ahead_behind(repo: Path, left: str, right: str) -> tuple[int, int]:
    result = git(["rev-list", "--left-right", "--count", f"{left}...{right}"], cwd=repo)
    if result.exit_code != 0:
        raise GitCommandError(result)
    left_count, right_count = result.output.split()
    return int(left_count), int(right_count)


def ancestry(repo: Path, ancestor: str, descendant: str) -> tuple[bool | None, str]:
    result = git(["merge-base", "--is-ancestor", ancestor, descendant], cwd=repo)
    if result.exit_code == 0:
        return True, f"{ancestor} is reachable from {descendant}"
    if result.exit_code == 1:
        return False, f"{ancestor} is not reachable from {descendant}"
    return None, result.output or "ancestry inspection failed"


def default_relation(repo: Path, local_ref: str, remote_ref: str) -> dict[str, Any]:
    local_oid = verify_ref(repo, local_ref)
    remote_oid = verify_ref(repo, remote_ref)
    if remote_oid is None:
        return {"relation": "remote-missing", "ahead": None, "behind": None}
    if local_oid is None:
        return {"relation": "local-missing", "ahead": None, "behind": None}
    ahead, behind = ahead_behind(repo, local_ref, remote_ref)
    if ahead == behind == 0:
        relation = "aligned"
    elif ahead and behind:
        relation = "diverged"
    elif ahead:
        relation = "ahead"
    else:
        relation = "behind"
    return {
        "relation": relation,
        "ahead": ahead,
        "behind": behind,
        "local_oid": local_oid,
        "remote_oid": remote_oid,
    }


def local_branches(
    repo: Path,
    *,
    default_branch: str,
    default_ref: str,
    worktrees: list[dict[str, Any]],
    merge_proof_enabled: bool,
) -> list[dict[str, Any]]:
    raw = output(
        [
            "for-each-ref",
            "--format=%(refname)%09%(objectname)%09%(upstream)%09%(HEAD)",
            "refs/heads",
        ],
        cwd=repo,
    )
    checkouts = {
        item["branch"]: item["path"] for item in worktrees if item.get("branch")
    }
    branches: list[dict[str, Any]] = []
    for line in raw.splitlines():
        branch_ref, oid, upstream_ref, current = (
            line.split("\t") + ["", "", "", ""]
        )[:4]
        name = branch_ref.removeprefix("refs/heads/")
        local_default_ref = f"refs/heads/{default_branch}"
        remote_default_ref = (
            default_ref
            if default_ref.startswith("refs/")
            else f"refs/remotes/{default_ref}"
        )
        local_reachable, local_proof = ancestry(
            repo, branch_ref, local_default_ref
        )
        local_integration = "reachable" if local_reachable else "not-proven"
        if local_reachable is None:
            local_integration = "unknown"

        remote_reachable, remote_proof = ancestry(
            repo, branch_ref, remote_default_ref
        )
        remote_integration = "reachable" if remote_reachable else "not-proven"
        if remote_reachable is None:
            remote_integration = "unknown"
        elif not remote_reachable and merge_proof_enabled:
            merged_proof, error = merge_proof(
                repo,
                branch_name=name,
                branch_ref=branch_ref,
                default_branch=default_branch,
                default_ref=remote_default_ref,
            )
            if merged_proof:
                remote_integration = "patch-equivalent"
                remote_proof = merged_proof
            elif error:
                remote_proof = f"{remote_proof}; {error}"
        if not upstream_ref:
            upstream_state = "none"
            ahead = behind = None
        elif verify_ref(repo, upstream_ref) is None:
            upstream_state = "gone"
            ahead = behind = None
        else:
            upstream_state = "tracking"
            ahead, behind = ahead_behind(repo, branch_ref, upstream_ref)
        upstream_display = upstream_ref.removeprefix("refs/remotes/").removeprefix(
            "refs/heads/"
        )
        branches.append(
            {
                "name": name,
                "oid": oid,
                "current": current == "*",
                "local_integration": local_integration,
                "local_proof": local_proof,
                "remote_integration": remote_integration,
                "remote_proof": remote_proof,
                "upstream": upstream_state,
                "upstream_ref": upstream_display or None,
                "ahead": ahead,
                "behind": behind,
                "checkout": checkouts.get(name, "unattached"),
            }
        )
    return branches


def remote_branches(repo: Path, remote: str) -> list[dict[str, str]]:
    raw = output(
        [
            "for-each-ref",
            "--format=%(refname)%09%(objectname)",
            f"refs/remotes/{remote}",
        ],
        cwd=repo,
    )
    branches: list[dict[str, str]] = []
    prefix = f"refs/remotes/{remote}/"
    for line in raw.splitlines():
        full_name, oid = (line.split("\t") + [""])[:2]
        if full_name == f"{prefix}HEAD" or not full_name.startswith(prefix):
            continue
        name = full_name.removeprefix(prefix)
        branches.append({"name": name, "ref": f"{remote}/{name}", "oid": oid})
    return branches


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        git(["merge-base", "--is-ancestor", ancestor, descendant], cwd=repo).exit_code
        == 0
    )


def stable_patch_id(repo: Path, left: str, right: str) -> str:
    diff = subprocess.run(
        ["git", "diff", "--binary", left, right],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode != 0 or not diff.stdout:
        return ""
    patch = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=str(repo),
        input=diff.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if patch.returncode != 0 or not patch.stdout:
        return ""
    return patch.stdout.decode(errors="replace").split()[0]


@functools.lru_cache(maxsize=8)
def all_merged_prs(
    repo_text: str,
) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    repo = Path(repo_text)
    if not GH_CLI.is_file():
        return {}, f"gh unavailable at policy path {GH_CLI}"
    result = run(
        [
            str(GH_CLI),
            "pr",
            "list",
            "--state",
            "merged",
            "--limit",
            "1000",
            "--json",
            "number,headRefName,headRefOid,baseRefName,mergeCommit,url",
        ],
        cwd=repo,
    )
    if result.exit_code != 0:
        return {}, f"gh failed: {result.output}"
    try:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for pr in json.loads(result.output or "[]"):
            grouped.setdefault(pr.get("headRefName", ""), []).append(pr)
        return grouped, None
    except json.JSONDecodeError:
        return {}, "gh returned invalid JSON"


def merged_prs(repo: Path, branch: str) -> tuple[list[dict[str, Any]], str | None]:
    grouped, error = all_merged_prs(str(repo))
    if error or grouped.get(branch):
        return grouped.get(branch, []), error
    result = run(
        [
            str(GH_CLI),
            "pr",
            "list",
            "--state",
            "merged",
            "--head",
            branch,
            "--limit",
            "10",
            "--json",
            "number,headRefName,headRefOid,baseRefName,mergeCommit,url",
        ],
        cwd=repo,
    )
    if result.exit_code != 0:
        return [], f"gh failed: {result.output}"
    try:
        return json.loads(result.output or "[]"), None
    except json.JSONDecodeError:
        return [], "gh returned invalid JSON"


def merge_proof(
    repo: Path,
    *,
    branch_name: str,
    branch_ref: str,
    default_branch: str,
    default_ref: str,
) -> tuple[str | None, str | None]:
    if is_ancestor(repo, branch_ref, default_ref):
        return f"{branch_ref} is reachable from {default_ref}", None
    prs, error = merged_prs(repo, branch_name)
    if error:
        return None, error
    branch_oid = verify_ref(repo, branch_ref)
    exact = [
        pr
        for pr in prs
        if pr.get("headRefName") == branch_name
        and pr.get("headRefOid") == branch_oid
        and pr.get("baseRefName") == default_branch
    ]
    merge_base = git(["merge-base", default_ref, branch_ref], cwd=repo)
    branch_patch = (
        stable_patch_id(repo, merge_base.output, branch_ref)
        if merge_base.exit_code == 0
        else ""
    )
    if not branch_patch:
        return None, "branch cumulative patch-id unavailable"
    for pr in exact:
        merge_commit = (pr.get("mergeCommit") or {}).get("oid")
        if not merge_commit:
            continue
        exists = git(["cat-file", "-e", f"{merge_commit}^{{commit}}"], cwd=repo)
        if exists.exit_code != 0:
            continue
        if not is_ancestor(repo, merge_commit, default_ref):
            continue
        merge_patch = stable_patch_id(repo, f"{merge_commit}^", merge_commit)
        if merge_patch and merge_patch == branch_patch:
            return (
                f"PR #{pr['number']} merged exact head {branch_name}; cumulative patch-id matches",
                None,
            )
    return None, "no exact merged PR with matching cumulative patch-id"


def state_token(state: dict[str, Any]) -> str:
    material = {key: value for key, value in state.items() if key != "state_token"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def bounded_records(records: list[str], limit: int = 40) -> tuple[list[str], int, int]:
    """Return a context-bounded sample with explicit coverage counts."""
    sample = records[:limit]
    return sample, len(records), len(records) - len(sample)


def snapshot(
    repo: Path,
    *,
    edge_checks: bool = False,
    merge_proof_enabled: bool = False,
) -> dict[str, Any]:
    remote, default_branch, default_ref = default_remote_ref(repo)
    worktrees = parse_worktrees(repo)
    local = local_branches(
        repo,
        default_branch=default_branch,
        default_ref=default_ref,
        worktrees=worktrees,
        merge_proof_enabled=merge_proof_enabled,
    )
    relation = default_relation(
        repo,
        f"refs/heads/{default_branch}",
        f"refs/remotes/{remote}/{default_branch}",
    )
    unreachable: list[str] = []
    unreachable_total: int | None = None
    unreachable_omitted: int | None = None
    if edge_checks:
        edge_result = git(
            ["fsck", "--no-reflogs", "--unreachable", "--no-progress"],
            cwd=repo,
            timeout=240,
        )
        if edge_result.exit_code != 0:
            raise GitCommandError(edge_result)
        unreachable, unreachable_total, unreachable_omitted = bounded_records(
            edge_result.output.splitlines()
        )
    reflog, reflog_total, reflog_omitted = bounded_records(
        output(["reflog", "show", "--all", "--date=iso"], cwd=repo).splitlines()
    )
    state = {
        "repo": str(repo),
        "head": output(["rev-parse", "HEAD"], cwd=repo),
        "current_branch": output(["branch", "--show-current"], cwd=repo) or "DETACHED",
        "working_tree": status_counts(repo),
        "default_remote": remote,
        "default_branch": default_branch,
        "default_ref": default_ref,
        "default_synced": relation["relation"] == "aligned",
        "default_relation": relation,
        "local_branches": local,
        "remote_branches": remote_branches(repo, remote),
        "stashes": output(
            ["stash", "list", "--date=iso", "--format=%gd%09%H%09%ci%09%s"],
            cwd=repo,
        ).splitlines(),
        "worktrees": worktrees,
        "remotes": [
            redact(line) for line in output(["remote", "-v"], cwd=repo).splitlines()
        ],
        "reflog": reflog,
        "reflog_total": reflog_total,
        "reflog_omitted": reflog_omitted,
        "is_shallow": output(["rev-parse", "--is-shallow-repository"], cwd=repo),
        "edge_checks_run": edge_checks,
        "unreachable": unreachable,
        "unreachable_total": unreachable_total,
        "unreachable_omitted": unreachable_omitted,
    }
    state["state_token"] = state_token(state)
    return state


def fetch(repo: Path) -> Result:
    """Refresh remote-tracking refs without moving local branches or worktrees."""
    return git(["fetch", "--all", "--prune", "--tags"], cwd=repo)


def render(payload: dict[str, Any]) -> str:
    if payload.get("status") == "error":
        return "\n".join(
            [
                "# Git Main Convergence Audit",
                "",
                "- Status: error",
                f"- Error: {payload['error']}",
            ]
        )
    tree = payload["working_tree"]
    current = next(
        (item for item in payload["local_branches"] if item["current"]), None
    )
    attention = [
        f"{item['path']} ({', '.join(item['attention'])})"
        for item in payload["worktrees"]
        if item["attention"]
    ]
    tree_summary = (
        "clean"
        if tree["clean"]
        else (
            f"{tree['staged']} staged, {tree['unstaged']} unstaged, "
            f"{tree['unmerged']} unmerged, {tree['untracked']} untracked"
        )
    )
    return "\n".join(
        [
            "# Git Main Convergence Audit",
            "",
            f"- Repo: {payload['repo']}",
            f"- Current: {payload['current_branch']} @ {payload['head'][:10]}",
            f"- Working tree: {tree_summary}",
            f"- Current tracking: {current['upstream_ref'] if current else 'detached'}"
            + (
                f" ({current['ahead']} ahead, {current['behind']} behind)"
                if current and current["ahead"] is not None
                else ""
            ),
            f"- Default relation: {payload['default_relation']['relation']}",
            f"- Shallow repository: {payload['is_shallow'] == 'true'}",
            f"- Local / remote branches: {len(payload['local_branches'])} / {len(payload['remote_branches'])}",
            f"- Stashes / worktrees: {len(payload['stashes'])} / {len(payload['worktrees'])}",
            f"- Worktrees needing attention: {'; '.join(attention) if attention else 'none'}",
            "- Recovery edge checks: "
            + (
                f"run ({payload['unreachable_total']} records, "
                f"{payload['unreachable_omitted']} omitted)"
                if payload["edge_checks_run"]
                else "not run"
            ),
            f"- Reflog sample: {payload['reflog_total']} records, {payload['reflog_omitted']} omitted",
            f"- Inventory token: {payload['state_token']}",
        ]
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit", help="Collect repository state without local mutation"
    )
    audit.add_argument("path", nargs="?", default=os.getcwd())
    audit.add_argument("--fetch", action="store_true")
    audit.add_argument("--edge-checks", action="store_true")
    audit.add_argument("--merge-proof", action="store_true")
    audit.add_argument("--json", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        repo = resolve_repo(Path(args.path).resolve())
        if args.fetch:
            fetched = fetch(repo)
            if fetched.exit_code != 0:
                print(f"Fetch failed: {fetched.output}", file=sys.stderr)
                return 3
        payload = snapshot(
            repo,
            edge_checks=args.edge_checks,
            merge_proof_enabled=args.merge_proof,
        )
        print(
            json.dumps(payload, ensure_ascii=False, indent=2)
            if args.json
            else render(payload)
        )
        return 0
    except RuntimeError as exc:
        payload = {"status": "error", "error": redact(str(exc))}
        print(
            json.dumps(payload, ensure_ascii=False, indent=2)
            if args.json
            else render(payload)
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
