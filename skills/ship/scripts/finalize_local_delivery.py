#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sync_default_branch import (
    DefaultSync,
    SafetyError,
    Worktree,
    default_sync_actions,
    git,
    is_ancestor,
    parse_worktrees,
    plan_default_sync,
    rev_parse,
    sync_default_branch,
)


PROTECTED_BRANCH_RE = re.compile(r"^(main|master|develop|release(?:/.*)?)$")
REPORT_SCHEMA = "ship-local-finalization"


@dataclass(frozen=True)
class FinalizationPlan:
    repo: Path
    control_worktree: Path
    task_worktree: Worktree
    branch: str
    expected_head: str
    default_branch: str
    integrated_ref: str
    integrated_head: str
    squash_commit: str | None
    proof: str
    force_delete: bool
    default_sync: DefaultSync
    preserve_worktree: bool

    @property
    def fast_forward_default(self) -> bool:
        return self.default_sync.status == "fast_forward"

    def default_sync_actions(self) -> list[str]:
        return default_sync_actions(
            self.repo, self.default_branch, self.integrated_head, self.default_sync
        )

    @property
    def actions(self) -> list[str]:
        delete_flag = "-D" if self.force_delete else "-d"
        if self.task_worktree.primary:
            actions = [
                shlex.join(
                    [
                        "git",
                        "-C",
                        str(self.task_worktree.path),
                        "switch",
                        self.default_branch,
                    ]
                )
            ]
            actions.extend(self.default_sync_actions())
            actions.append(
                shlex.join(
                    [
                        "git",
                        "-C",
                        str(self.task_worktree.path),
                        "branch",
                        delete_flag,
                        "--",
                        self.branch,
                    ]
                )
            )
            return actions
        actions = [
            *self.default_sync_actions(),
            shlex.join(
                [
                    "git",
                    "-C",
                    str(self.task_worktree.path),
                    "switch",
                    "--detach",
                    self.expected_head,
                ]
            ),
            shlex.join(
                [
                    "git",
                    "-C",
                    str(self.task_worktree.path),
                    "branch",
                    delete_flag,
                    "--",
                    self.branch,
                ]
            ),
        ]
        if not self.preserve_worktree:
            actions.append(
                shlex.join(
                    [
                        "git",
                        "-C",
                        str(self.control_worktree),
                        "worktree",
                        "remove",
                        str(self.task_worktree.path),
                    ]
                )
            )
        return actions


def patch_id(cwd: Path, start: str, end: str) -> str:
    diff = git(cwd, "diff", "--full-index", "--binary", start, end).stdout
    if not diff:
        raise SafetyError(f"empty cumulative diff for {start}..{end}")
    result = git(cwd, "patch-id", "--stable", input_text=diff)
    fields = result.stdout.split()
    if not fields:
        raise SafetyError(f"git patch-id produced no proof for {start}..{end}")
    return fields[0]


def squash_patch_matches(cwd: Path, expected_head: str, squash_commit: str) -> bool:
    parents = git(cwd, "rev-list", "--parents", "-n", "1", squash_commit).stdout.split()
    if len(parents) != 2:
        raise SafetyError("squash proof requires a single-parent squash commit")
    squash_parent = parents[1]
    branch_base = git(cwd, "merge-base", squash_parent, expected_head).stdout.strip()
    return patch_id(cwd, branch_base, expected_head) == patch_id(
        cwd, squash_parent, squash_commit
    )


def path_contains(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def assert_clean_worktree(worktree: Path) -> None:
    status = git(worktree, "status", "--porcelain=v1", "--untracked-files=all").stdout
    if status:
        raise SafetyError(f"task worktree is dirty:\n{status}")


def build_plan(
    *,
    repo: Path,
    worktree_path: Path,
    branch: str,
    expected_head_revision: str,
    default_branch: str,
    integrated_ref: str,
    squash_commit_revision: str | None,
    preserve_worktree: bool = False,
) -> FinalizationPlan:
    repo = repo.resolve()
    git(repo, "rev-parse", "--show-toplevel")
    worktrees = parse_worktrees(repo)
    task_path = worktree_path.resolve()
    matches = [worktree for worktree in worktrees if worktree.path == task_path]
    if len(matches) != 1:
        raise SafetyError(f"task worktree is not registered exactly once: {task_path}")
    task_worktree = matches[0]

    if PROTECTED_BRANCH_RE.fullmatch(branch):
        raise SafetyError(f"refusing to finalize protected branch: {branch}")
    if branch == default_branch:
        raise SafetyError("delivery branch and default branch must differ")
    if task_worktree.detached or task_worktree.branch != branch:
        raise SafetyError(
            f"task worktree branch mismatch: expected {branch}, found {task_worktree.branch or 'DETACHED'}"
        )
    if task_worktree.locked or task_worktree.prunable:
        raise SafetyError("task worktree is locked or prunable")
    if preserve_worktree and task_worktree.primary:
        raise SafetyError("preserve-worktree is valid only for a linked task worktree")

    assert_clean_worktree(task_path)

    branch_head = rev_parse(repo, f"refs/heads/{branch}")
    expected_head = rev_parse(repo, expected_head_revision)
    if branch_head != expected_head:
        raise SafetyError(
            f"delivery branch moved: recorded {expected_head}, current {branch_head}"
        )

    integrated_head = rev_parse(repo, integrated_ref)
    proof = ""
    force_delete = False
    squash_commit: str | None = None
    if is_ancestor(repo, expected_head, integrated_head):
        proof = "delivered head is an ancestor of the integration ref"
    elif squash_commit_revision:
        squash_commit = rev_parse(repo, squash_commit_revision)
        if not is_ancestor(repo, squash_commit, integrated_head):
            raise SafetyError(
                "supplied squash commit is not contained by the integration ref"
            )
        if not squash_patch_matches(repo, expected_head, squash_commit):
            raise SafetyError("squash commit patch does not match the delivered branch")
        proof = f"cumulative patch matches squash commit {squash_commit}"
        force_delete = True
    else:
        raise SafetyError(
            "delivered head is not contained by the integration ref and no squash proof was supplied"
        )

    default_sync = plan_default_sync(
        repo, worktrees, default_branch, integrated_head, exclude=task_path
    )

    if task_worktree.primary:
        if default_sync.worktree is not None:
            raise SafetyError(
                f"default branch is already checked out at {default_sync.worktree}"
            )
        # After switching to the default branch, the task worktree owns it and syncs it.
        default_sync = DefaultSync(
            status=default_sync.status,
            worktree=task_path,
            before=default_sync.before,
            after=default_sync.after,
            detail=default_sync.detail,
        )
        control_worktree = task_path
    else:
        controls = [
            worktree
            for worktree in worktrees
            if worktree.path != task_path
            and worktree.path.exists()
            and not worktree.prunable
        ]
        if not controls:
            raise SafetyError("no surviving control worktree is available")
        control_worktree = controls[0].path

    return FinalizationPlan(
        repo=repo,
        control_worktree=control_worktree,
        task_worktree=task_worktree,
        branch=branch,
        expected_head=expected_head,
        default_branch=default_branch,
        integrated_ref=integrated_ref,
        integrated_head=integrated_head,
        squash_commit=squash_commit,
        proof=proof,
        force_delete=force_delete,
        default_sync=default_sync,
        preserve_worktree=preserve_worktree,
    )


def execute_plan(plan: FinalizationPlan) -> DefaultSync:
    if not plan.task_worktree.primary and path_contains(
        plan.task_worktree.path, Path.cwd()
    ):
        raise SafetyError("run --execute from outside the linked task worktree")

    refreshed = build_plan(
        repo=plan.repo,
        worktree_path=plan.task_worktree.path,
        branch=plan.branch,
        expected_head_revision=plan.expected_head,
        default_branch=plan.default_branch,
        integrated_ref=plan.integrated_ref,
        squash_commit_revision=plan.squash_commit,
        preserve_worktree=plan.preserve_worktree,
    )
    if refreshed != plan:
        raise SafetyError("finalization state changed after preview; run a new preview")

    delete_flag = "-D" if plan.force_delete else "-d"
    if plan.task_worktree.primary:
        git(plan.task_worktree.path, "switch", plan.default_branch)
        default_sync = sync_default_branch(
            plan.repo, plan.default_branch, plan.integrated_head, plan.default_sync
        )
        assert_clean_worktree(plan.task_worktree.path)
        current_branch_head = rev_parse(
            plan.task_worktree.path, f"refs/heads/{plan.branch}"
        )
        if current_branch_head != plan.expected_head:
            raise SafetyError("delivery branch moved immediately before deletion")
        git(plan.task_worktree.path, "branch", delete_flag, "--", plan.branch)
        return default_sync
    else:
        default_sync = sync_default_branch(
            plan.repo, plan.default_branch, plan.integrated_head, plan.default_sync
        )
        git(plan.task_worktree.path, "switch", "--detach", plan.expected_head)
        assert_clean_worktree(plan.task_worktree.path)
        current_branch_head = rev_parse(
            plan.task_worktree.path, f"refs/heads/{plan.branch}"
        )
        if current_branch_head != plan.expected_head:
            raise SafetyError("delivery branch moved immediately before deletion")
        git(plan.task_worktree.path, "branch", delete_flag, "--", plan.branch)
        if not plan.preserve_worktree:
            git(
                plan.control_worktree,
                "worktree",
                "remove",
                str(plan.task_worktree.path),
            )
        return default_sync


def render(
    plan: FinalizationPlan,
    *,
    executed: bool,
    default_sync: DefaultSync | None = None,
) -> dict[str, object]:
    if plan.task_worktree.primary:
        worktree_removal = "retained_primary"
    elif plan.preserve_worktree:
        worktree_removal = "preserved_for_external_owner"
    else:
        worktree_removal = "removed_by_git"
    return {
        "schema": REPORT_SCHEMA,
        "safe": True,
        "mode": "executed" if executed else "preview",
        "default_branch_sync": (default_sync or plan.default_sync).as_report(),
        "repo": str(plan.repo),
        "control_worktree": str(plan.control_worktree),
        "branch": plan.branch,
        "expected_head": plan.expected_head,
        "worktree": str(plan.task_worktree.path),
        "default_branch": plan.default_branch,
        "integration_ref": plan.integrated_ref,
        "integration_head": plan.integrated_head,
        "squash_commit": plan.squash_commit,
        "proof": plan.proof,
        "actions": plan.actions,
        "worktree_removal": worktree_removal,
        "remote_branch": "untouched",
    }


def write_report(path: Path, report: dict[str, object], *, task_worktree: Path) -> Path:
    target = path.expanduser()
    if not target.is_absolute():
        raise SafetyError("report path must be absolute")
    target = target.resolve()
    if path_contains(task_worktree, target):
        raise SafetyError("report path must survive outside the task worktree")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely finalize the local branch and worktree from one completed delivery."
    )
    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Any surviving worktree for the repository.",
    )
    parser.add_argument(
        "--worktree", required=True, type=Path, help="Exact task worktree path."
    )
    parser.add_argument("--branch", required=True, help="Exact local delivery branch.")
    parser.add_argument(
        "--expected-head", required=True, help="Recorded delivery HEAD."
    )
    parser.add_argument(
        "--default-branch", required=True, help="Local default branch name."
    )
    parser.add_argument(
        "--integrated-ref",
        required=True,
        help="Fresh ref containing the delivered work.",
    )
    parser.add_argument(
        "--squash-commit", help="Verified squash commit for patch-equivalence proof."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Recheck the preview and perform local cleanup.",
    )
    parser.add_argument(
        "--preserve-worktree",
        action="store_true",
        help="Detach a linked worktree and delete its branch, but leave worktree removal to its external owner.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Atomically persist the structured result outside the task worktree.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        plan = build_plan(
            repo=args.repo,
            worktree_path=args.worktree,
            branch=args.branch,
            expected_head_revision=args.expected_head,
            default_branch=args.default_branch,
            integrated_ref=args.integrated_ref,
            squash_commit_revision=args.squash_commit,
            preserve_worktree=args.preserve_worktree,
        )
        default_sync = execute_plan(plan) if args.execute else None
        report = render(plan, executed=args.execute, default_sync=default_sync)
        if args.report_path is not None:
            write_report(
                args.report_path,
                report,
                task_worktree=plan.task_worktree.path,
            )
        print(json.dumps(report, indent=2))
        return 0
    except SafetyError as error:
        print(
            json.dumps({"safe": False, "error": str(error)}, indent=2), file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
