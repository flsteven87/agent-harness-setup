#!/usr/bin/env python3
"""Bring the local default branch up to a target commit without touching dirty files.

The one implementation of default-branch synchronization, shared by `$ship` exact
finalization and `$latest`. Behind: fast-forward. Diverged: replay the local-only
commits onto the target in a temporary worktree, then move the branch with
`git switch -C`, which carries staged, unstaged and untracked files like any branch
switch and refuses atomically when one would be overwritten. Every refusal is a
`blocked` result that leaves the branch as it was.

`--exact`, used by `$latest`, preserves an ahead or diverged tip on a retained
branch before aligning to the target. Ordinary `$ship` callers keep the replay mode.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPORT_SCHEMA = "default-branch-sync"
OPERATION_MARKERS = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
)


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    exit_code: int
    stdout: str


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    detached: bool
    locked: bool
    prunable: bool
    primary: bool


@dataclass(frozen=True)
class DefaultSync:
    """Relation between the local default branch and the target commit.

    planned status: already_current | fast_forward | rebase | align
    executed status: already_current | fast_forwarded | rebased | aligned | blocked
    worktree: the worktree that has the default branch checked out, if any
    """

    status: str
    worktree: Path | None
    before: str
    after: str
    detail: str = ""
    preserved_ref: str | None = None

    def as_report(self) -> dict[str, object]:
        return {
            "status": self.status,
            "worktree": str(self.worktree) if self.worktree else None,
            "before": self.before,
            "after": self.after,
            "detail": self.detail,
            "preserved_ref": self.preserved_ref,
        }


def run(args: list[str], *, cwd: Path, input_text: str | None = None) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    return CommandResult(
        args=args,
        exit_code=completed.returncode,
        stdout=(completed.stdout or "").strip(),
    )


def git(
    cwd: Path, *args: str, check: bool = True, input_text: str | None = None
) -> CommandResult:
    result = run(["git", *args], cwd=cwd, input_text=input_text)
    if check and result.exit_code != 0:
        command = " ".join(result.args)
        raise SafetyError(
            f"{command} failed (exit {result.exit_code}): {result.stdout}"
        )
    return result


def rev_parse(cwd: Path, revision: str) -> str:
    result = git(
        cwd, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
    )
    return result.stdout.splitlines()[-1]


def is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    result = git(cwd, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    if result.exit_code not in (0, 1):
        raise SafetyError(
            f"git merge-base --is-ancestor failed (exit {result.exit_code}): {result.stdout}"
        )
    return result.exit_code == 0


def parse_worktrees(cwd: Path) -> list[Worktree]:
    output = git(cwd, "worktree", "list", "--porcelain").stdout
    records: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for line in [*output.splitlines(), ""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value if value else True

    worktrees: list[Worktree] = []
    for index, record in enumerate(records):
        branch_ref = record.get("branch")
        branch = None
        if isinstance(branch_ref, str) and branch_ref.startswith("refs/heads/"):
            branch = branch_ref.removeprefix("refs/heads/")
        worktrees.append(
            Worktree(
                path=Path(str(record["worktree"])).resolve(),
                branch=branch,
                detached=bool(record.get("detached", False)),
                locked="locked" in record,
                prunable="prunable" in record,
                primary=index == 0,
            )
        )
    return worktrees


def operation_in_progress(worktree: Path) -> str | None:
    """Name the Git operation (rebase, merge, cherry-pick, revert) running in `worktree`."""
    git_dir = Path(git(worktree, "rev-parse", "--absolute-git-dir").stdout)
    for marker in OPERATION_MARKERS:
        if (git_dir / marker).exists():
            return marker
    return None


def rebase_in_progress_on(worktrees: list[Worktree], branch: str) -> Path | None:
    """Return the worktree rebasing `branch`, whose HEAD is detached meanwhile."""
    target = f"refs/heads/{branch}"
    for worktree in worktrees:
        if not worktree.path.exists():
            continue
        git_dir = Path(git(worktree.path, "rev-parse", "--absolute-git-dir").stdout)
        for state_dir in ("rebase-merge", "rebase-apply"):
            head_name = git_dir / state_dir / "head-name"
            if head_name.exists() and head_name.read_text().strip() == target:
                return worktree.path
    return None


def plan_default_sync(
    repo: Path,
    worktrees: list[Worktree],
    default_branch: str,
    target: str,
    *,
    exclude: Path | None = None,
    exact: bool = False,
) -> DefaultSync:
    """Classify how the local default branch reaches `target` (a full commit OID)."""
    before = rev_parse(repo, f"refs/heads/{default_branch}")
    owners = [
        worktree
        for worktree in worktrees
        if worktree.branch == default_branch and worktree.path != exclude
    ]
    owner = owners[0].path if owners else None
    if exact and before != target and not is_ancestor(repo, before, target):
        preserved_ref = f"refs/heads/retained/{default_branch}-before-latest-{before}"
        return DefaultSync("align", owner, before, target, preserved_ref=preserved_ref)
    if is_ancestor(repo, target, before):
        return DefaultSync("already_current", owner, before, before)
    if is_ancestor(repo, before, target):
        return DefaultSync("fast_forward", owner, before, target)
    local_only = git(repo, "rev-list", "--count", f"{target}..{before}").stdout
    return DefaultSync(
        "rebase",
        owner,
        before,
        before,
        detail=f"replay {local_only} local commit(s) onto {target}",
    )


def default_sync_actions(
    repo: Path, default_branch: str, target: str, sync: DefaultSync
) -> list[str]:
    if sync.status == "align":
        move = (
            ["git", "-C", str(sync.worktree), "switch", "--no-overwrite-ignore", "-C", default_branch, target]
            if sync.worktree is not None
            else ["git", "-C", str(repo), "update-ref", f"refs/heads/{default_branch}", target, sync.before]
        )
        return [
            shlex.join(["git", "-C", str(repo), "update-ref", str(sync.preserved_ref), sync.before, "<absent-or-same-tip>"]),
            shlex.join(move),
        ]
    if sync.status == "fast_forward":
        if sync.worktree is not None:
            return [shlex.join(["git", "-C", str(sync.worktree), "merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", target])]
        return [
            shlex.join(
                [
                    "git",
                    "-C",
                    str(repo),
                    "update-ref",
                    f"refs/heads/{default_branch}",
                    target,
                    sync.before,
                ]
            )
        ]
    if sync.status == "rebase":
        move = (
            ["git", "-C", str(sync.worktree), "switch", "--no-overwrite-ignore", "-C", default_branch, "<replayed>"]
            if sync.worktree is not None
            else [
                "git",
                "-C",
                str(repo),
                "update-ref",
                f"refs/heads/{default_branch}",
                "<replayed>",
                sync.before,
            ]
        )
        return [
            shlex.join(["git", "worktree", "add", "--detach", "<temporary>", target]),
            shlex.join(["git", "-C", "<temporary>", "cherry-pick", f"{target}..{sync.before}"]),
            shlex.join(move),
        ]
    return []


def blocked(sync: DefaultSync, detail: str) -> DefaultSync:
    return DefaultSync("blocked", sync.worktree, sync.before, sync.before, detail, sync.preserved_ref)


def local_commits(repo: Path, base: str, tip: str) -> list[str]:
    """Author and subject of each commit in `base..tip`, oldest first: what a replay must carry."""
    return git(repo, "log", "--reverse", "--format=%an%x1f%ae%x1f%s", f"{base}..{tip}").stdout.splitlines()


def replay_local_commits(repo: Path, before: str, target: str) -> tuple[str | None, str]:
    """Replay the commits in `target..before` onto `target` in a temporary worktree.

    Returns the replayed tip, or None with the reason. Repository hooks stay off so the
    throwaway worktree never reaches a hook consumer.
    """
    if git(repo, "rev-list", "--merges", f"{target}..{before}").stdout:
        return None, "local commits include a merge; replay them by hand and pass --replayed"
    with tempfile.TemporaryDirectory(prefix="default-sync-") as temporary:
        replay = Path(temporary) / "replay"
        try:
            git(repo, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", str(replay), target)
            result = git(
                replay,
                "-c",
                "core.hooksPath=/dev/null",
                "cherry-pick",
                f"{target}..{before}",
                check=False,
            )
            if result.exit_code != 0:
                conflicts = git(replay, "diff", "--name-only", "--diff-filter=U", check=False).stdout
                git(replay, "cherry-pick", "--abort", check=False)
                paths = ", ".join(conflicts.splitlines()) or result.stdout
                return None, f"local commits conflict with {target} in: {paths}"
            return rev_parse(replay, "HEAD"), ""
        finally:
            git(repo, "worktree", "remove", "--force", str(replay), check=False)
            git(repo, "worktree", "prune", check=False)
            if any(w.path == replay.resolve() for w in parse_worktrees(repo)):
                raise SafetyError(f"temporary replay worktree {replay} is still registered")


def move_owned_branch(worktree: Path, default_branch: str, new_head: str, fast_forward: bool) -> CommandResult:
    """Move the checked-out default branch like a branch switch: dirty and ignored files stay or Git refuses."""
    if fast_forward:
        return git(
            worktree, "merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", new_head, check=False
        )
    return git(worktree, "switch", "--no-overwrite-ignore", "-C", default_branch, new_head, check=False)


def sync_default_branch(
    repo: Path,
    default_branch: str,
    target: str,
    sync: DefaultSync,
    *,
    replayed: str | None = None,
) -> DefaultSync:
    """Carry out a planned sync. A refusal returns `blocked` and leaves the branch as it was."""
    if sync.status == "already_current":
        return sync
    ref = f"refs/heads/{default_branch}"

    def unchanged() -> None:
        owners = [w.path for w in parse_worktrees(repo) if w.branch == default_branch]
        if (owners[0] if owners else None) != sync.worktree:
            raise SafetyError(f"{default_branch} changed worktree after the sync was planned")
        if rev_parse(repo, ref) != sync.before:
            raise SafetyError(f"{default_branch} moved after the sync was planned")

    unchanged()
    if sync.worktree is not None:
        operation = operation_in_progress(sync.worktree)
        if operation is not None:
            return blocked(sync, f"{operation} is in progress in {sync.worktree}")
    else:
        rebasing = rebase_in_progress_on(parse_worktrees(repo), default_branch)
        if rebasing is not None:
            return blocked(sync, f"{default_branch} is being rebased in {rebasing}")

    if sync.status == "align":
        if replayed is not None:
            raise SafetyError("exact alignment does not accept a replayed tip")
        if sync.preserved_ref is None:
            raise SafetyError("exact alignment requires a preservation ref")
        existing = git(repo, "show-ref", "--verify", "--hash", sync.preserved_ref, check=False)
        if existing.exit_code == 0:
            if existing.stdout != sync.before:
                return blocked(sync, f"preservation ref {sync.preserved_ref} points to another commit")
        else:
            git(repo, "update-ref", sync.preserved_ref, sync.before, "0" * len(sync.before))
        if rev_parse(repo, sync.preserved_ref) != sync.before:
            raise SafetyError("original default-branch tip was not preserved")
        new_head = target
    elif sync.status == "fast_forward":
        new_head = target
    else:
        if replayed is not None:
            new_head = rev_parse(repo, replayed)
        else:
            new_head, reason = replay_local_commits(repo, sync.before, target)
            if new_head is None:
                return blocked(sync, reason)
        if not is_ancestor(repo, target, new_head):
            raise SafetyError(f"replayed commit {new_head} does not contain {target}")
        if local_commits(repo, target, new_head) != local_commits(repo, target, sync.before):
            raise SafetyError(
                f"replayed commit {new_head} does not carry exactly the local commits in {target}..{sync.before}"
            )

    # The replay can take a while; the branch must still be where it was planned before it moves.
    unchanged()
    detail = sync.detail
    if sync.worktree is not None:
        result = move_owned_branch(sync.worktree, default_branch, new_head, sync.status == "fast_forward")
        observed = rev_parse(repo, ref)
        if observed == sync.before and result.exit_code != 0:
            return blocked(sync, result.stdout)
        if result.exit_code != 0:
            # A hook's exit status becomes Git's, after the branch already moved.
            detail = f"{detail}; git exited {result.exit_code} after moving: {result.stdout}".lstrip("; ")
    else:
        git(repo, "update-ref", ref, new_head, sync.before)
        observed = rev_parse(repo, ref)
    if observed != new_head:
        raise SafetyError(f"{default_branch} moved during sync: observed {observed}")
    status = {"fast_forward": "fast_forwarded", "align": "aligned"}.get(sync.status, "rebased")
    return DefaultSync(status, sync.worktree, sync.before, observed, detail, sync.preserved_ref)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bring the local default branch up to a target commit, keeping dirty files."
    )
    parser.add_argument("--repo", required=True, type=Path, help="Any worktree of the repository.")
    parser.add_argument("--default-branch", required=True, help="Local default branch name.")
    parser.add_argument("--target", required=True, help="Commit the default branch must contain.")
    parser.add_argument(
        "--replayed",
        help="A commit already holding the local commits replayed onto the target, "
        "for a replay that needed conflict resolution.",
    )
    parser.add_argument("--execute", action="store_true", help="Perform the planned sync.")
    parser.add_argument(
        "--exact", action="store_true",
        help="Make the local default tip equal target; preserve local-only commits on a retained branch.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        repo = args.repo.resolve()
        if args.exact and args.replayed:
            raise SafetyError("--exact and --replayed are mutually exclusive")
        target = rev_parse(repo, args.target)
        sync = plan_default_sync(repo, parse_worktrees(repo), args.default_branch, target, exact=args.exact)
        actions = default_sync_actions(repo, args.default_branch, target, sync)
        if args.execute:
            sync = sync_default_branch(
                repo, args.default_branch, target, sync, replayed=args.replayed
            )
        print(
            json.dumps(
                {
                    "schema": REPORT_SCHEMA,
                    "mode": "executed" if args.execute else "preview",
                    "target": target,
                    "actions": actions,
                    "default_branch_sync": sync.as_report(),
                },
                indent=2,
            )
        )
        return 0
    except SafetyError as error:
        print(json.dumps({"safe": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
