#!/usr/bin/env python3
"""Refresh every external skill in ~/.agents/skills from its upstream, keeping local changes.

One run covers the three external sources named in ``external-skills.json``:

1. Lock-managed skills: ``npx skills update -g`` at the pinned CLI version. The CLI replaces each
   folder wholesale, so a local ``agents/openai.yaml`` it deletes (our Codex invocation gate for a
   skill whose upstream ships none) is restored from HEAD.
2. Matt Pocock's skills: a three-way sync from the recorded upstream commit to upstream HEAD. Each
   file takes upstream's change when the local copy still matches the old upstream, merges with
   ``git merge-file`` when both sides changed, and reports a conflict otherwise. Files upstream
   never had (our ``agents/openai.yaml``) stay. The recorded commit advances only after a
   conflict-free run, so a conflict is retried on the next run.
3. Impeccable's Claude subagents: copied into ``claude/agents`` here (``~/.claude/setup.sh`` links
   them into ``~/.claude/agents``) when upstream HEAD ships the same skill folder that is installed,
   so the subagents always match the installed release.

Changed skills are validated with ``validate_skills.py``. ``--commit`` lands the result as one
``chore(skills)`` commit. The JSON report on stdout lists every change and every item that needs a
human; the exit code is 0 when nothing needs one, 1 when something does, 2 when a precondition
failed before any change.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import validate_skills

AGENTS_REPO = Path.home() / ".agents"
MANIFEST = "external-skills.json"
OWNED_PATHS = ("skills", "claude/agents", ".skill-lock.json", MANIFEST)
LOCAL_GATE = "agents/openai.yaml"


@dataclass
class Report:
    lock_updated: list[str] = field(default_factory=list)
    gates_restored: list[str] = field(default_factory=list)
    matt: dict = field(default_factory=dict)
    impeccable_agents: dict = field(default_factory=dict)
    invalid: list[str] = field(default_factory=list)
    needs_human: list[str] = field(default_factory=list)
    commit: str | None = None


def run(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(repo), *args], check=check).stdout


def dirty_paths(repo: Path) -> list[str]:
    out = git(repo, "status", "--porcelain", "--untracked-files=all", "--", *OWNED_PATHS)
    return [line[3:] for line in out.splitlines()]


def changed_skills(repo: Path) -> list[str]:
    names = {Path(path).parts[1] for path in dirty_paths(repo) if path.startswith("skills/")}
    return sorted(name for name in names if (repo / "skills" / name).is_dir())


# --- lock-managed skills ---------------------------------------------------------------------


def update_lock_skills(repo: Path, cli: str, report: Report) -> None:
    run(["npx", "-y", cli, "update", "-g", "-y"], cwd=Path.home())
    report.lock_updated = changed_skills(repo)
    restore_local_gates(repo, report)


def restore_local_gates(repo: Path, report: Report) -> None:
    deleted = git(repo, "diff", "--name-only", "--diff-filter=D", "HEAD", "--", "skills").splitlines()
    for path in deleted:
        if path.endswith("/" + LOCAL_GATE):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(run(["git", "-C", str(repo), "show", f"HEAD:{path}"]).stdout.encode())
            report.gates_restored.append(path)


# --- Matt Pocock skills ----------------------------------------------------------------------


class Upstream:
    """A blobless clone read through git plumbing, so no checkout is needed."""

    def __init__(self, url: str, workdir: Path):
        self.path = workdir / "upstream"
        run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(self.path)])
        self.head = git(self.path, "rev-parse", "HEAD").strip()

    def manifest(self, rev: str) -> dict[str, str]:
        plugin = json.loads(git(self.path, "show", f"{rev}:.claude-plugin/plugin.json"))
        return {Path(entry).name: Path(entry).as_posix().removeprefix("./") for entry in plugin["skills"]}

    def files(self, rev: str, path: str) -> dict[str, bytes]:
        names = git(self.path, "ls-tree", "-r", "--name-only", rev, "--", path).splitlines()
        return {
            name.removeprefix(path + "/"): subprocess.run(
                ["git", "-C", str(self.path), "show", f"{rev}:{name}"], check=True, capture_output=True
            ).stdout
            for name in names
        }


def local_files(skill_dir: Path) -> dict[str, bytes]:
    if not skill_dir.is_dir():
        return {}
    return {
        path.relative_to(skill_dir).as_posix(): path.read_bytes()
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def merge(local: bytes, old: bytes, new: bytes) -> bytes | None:
    with tempfile.TemporaryDirectory() as scratch:
        paths = []
        for label, data in (("local", local), ("old", old), ("new", new)):
            path = Path(scratch) / label
            path.write_bytes(data)
            paths.append(str(path))
        result = subprocess.run(["git", "merge-file", "-p", *paths], capture_output=True)
        return result.stdout if result.returncode == 0 else None


def write(skill_dir: Path, rel: str, data: bytes | None) -> None:
    target = skill_dir / rel
    if data is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def sync_skill(skill_dir: Path, old: dict[str, bytes], new: dict[str, bytes]) -> tuple[str, list[str]]:
    """Apply old->new upstream changes to one local skill; return (outcome, conflicting files)."""
    local = local_files(skill_dir)
    conflicts, touched, merged = [], False, False
    for rel in sorted(old.keys() | new.keys()):
        o, n, l = old.get(rel), new.get(rel), local.get(rel)
        if o == n or l == n:
            continue
        if l == o:
            write(skill_dir, rel, n)
            touched = True
        elif o is not None and n is not None and l is not None and (combined := merge(l, o, n)) is not None:
            write(skill_dir, rel, combined)
            touched = merged = True
        else:
            conflicts.append(rel)
    if conflicts:
        return "conflict", conflicts
    return ("merged" if merged else "updated" if touched else "unchanged"), []


def codex_gate(skill_md: bytes) -> bytes:
    frontmatter = skill_md.decode("utf-8").split("---", 2)[1]
    implicit = "disable-model-invocation: true" not in frontmatter
    return f"policy:\n  allow_implicit_invocation: {'true' if implicit else 'false'}\n".encode()


def sync_matt(repo: Path, config: dict, report: Report, workdir: Path) -> None:
    upstream = Upstream(config["repo"], workdir)
    old_rev, new_rev = config["commit"], upstream.head
    status = {"old": old_rev, "new": new_rev, "updated": [], "merged": [], "added": [], "removed": []}
    report.matt = status
    if old_rev == new_rev:
        return
    excluded = set(config.get("exclude", {}))
    old_manifest = {k: v for k, v in upstream.manifest(old_rev).items() if k not in excluded}
    new_manifest = {k: v for k, v in upstream.manifest(new_rev).items() if k not in excluded}
    conflicted = False
    for name in sorted(old_manifest.keys() | new_manifest.keys()):
        skill_dir = repo / "skills" / name
        old = upstream.files(old_rev, old_manifest[name]) if name in old_manifest else {}
        new = upstream.files(new_rev, new_manifest[name]) if name in new_manifest else {}
        if name not in old_manifest:
            if skill_dir.exists():
                report.needs_human.append(f"matt: new upstream skill {name} collides with an existing folder")
                conflicted = True
                continue
            for rel, data in new.items():
                write(skill_dir, rel, data)
            if LOCAL_GATE not in new and "SKILL.md" in new:
                write(skill_dir, LOCAL_GATE, codex_gate(new["SKILL.md"]))
            status["added"].append(name)
            continue
        if name not in new_manifest:
            local = local_files(skill_dir)
            if all(local.get(rel) == data for rel, data in old.items()):
                shutil.rmtree(skill_dir, ignore_errors=True)
                status["removed"].append(name)
            else:
                report.needs_human.append(f"matt: upstream removed {name}, which has local changes")
                conflicted = True
            continue
        outcome, files = sync_skill(skill_dir, old, new)
        if outcome == "conflict":
            report.needs_human.append(f"matt: {name} conflicts in {', '.join(files)}")
            conflicted = True
        elif outcome != "unchanged":
            status[outcome].append(name)
    if not conflicted:
        config["commit"] = new_rev


# --- Impeccable Claude subagents ---------------------------------------------------------------


def sync_impeccable_agents(repo: Path, config: dict, report: Report, workdir: Path) -> None:
    clone = workdir / "impeccable"
    run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse", config["repo"], str(clone)])
    run(["git", "-C", str(clone), "sparse-checkout", "set", config["upstream_skill_path"], config["upstream_agents_path"]])
    installed = repo / "skills" / config["skill"]
    if local_files(clone / config["upstream_skill_path"]) != local_files(installed):
        report.impeccable_agents = {"status": "skipped"}
        report.needs_human.append("impeccable: installed skill differs from upstream HEAD; subagents not synced")
        return
    target = repo / config["target"]
    copied = []
    for source in sorted((clone / config["upstream_agents_path"]).glob("*.md")):
        destination = target / source.name
        if not destination.is_file() or destination.read_bytes() != source.read_bytes():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied.append(source.name)
    report.impeccable_agents = {"status": "synced", "copied": copied}


# --- run -------------------------------------------------------------------------------------


def commit(repo: Path, report: Report) -> None:
    names = sorted({*report.lock_updated, *changed_skills(repo)})
    if not dirty_paths(repo):
        return
    git(repo, "add", "-A", "--", *(path for path in OWNED_PATHS if (repo / path).exists()))
    body = "Updated through scripts/update_external_skills.py: " + ", ".join(names) + "."
    git(repo, "commit", "-q", "-m", "chore(skills): update external skills to upstream", "-m", body)
    report.commit = git(repo, "rev-parse", "HEAD").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh external skills from their upstreams.")
    parser.add_argument("--repo", type=Path, default=AGENTS_REPO)
    parser.add_argument("--commit", action="store_true", help="land the result as one chore(skills) commit")
    parser.add_argument("--skip-lock", action="store_true", help="leave lock-managed skills untouched")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    if dirty := dirty_paths(repo):
        print(json.dumps({"error": "uncommitted skill changes", "paths": dirty}, indent=2))
        return 2
    manifest_path = repo / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = Report()

    with tempfile.TemporaryDirectory() as scratch:
        workdir = Path(scratch)
        if not args.skip_lock:
            update_lock_skills(repo, manifest["skills_cli"], report)
        sync_matt(repo, manifest["matt"], report, workdir)
        if "impeccable_claude_agents" in manifest:
            sync_impeccable_agents(repo, manifest["impeccable_claude_agents"], report, workdir)

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    changed = [repo / "skills" / name for name in changed_skills(repo)]
    if changed and not validate_skills.DEFAULT_VALIDATOR.is_file():
        report.needs_human.append(f"skill-creator validator missing: {validate_skills.DEFAULT_VALIDATOR}")
    elif changed:
        for skill_dir, valid, message in validate_skills.validate(changed, validate_skills.DEFAULT_VALIDATOR):
            if not valid:
                report.invalid.append(f"{skill_dir.name}: {message}")
    report.needs_human.extend(f"invalid skill {item}" for item in report.invalid)

    if args.commit and not report.needs_human:
        commit(repo, report)
    print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
    return 1 if report.needs_human else 0


if __name__ == "__main__":
    sys.exit(main())
