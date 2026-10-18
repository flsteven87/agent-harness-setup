#!/usr/bin/env python3
"""Give this host the shared agent setup: Claude Code, Codex, and the tools they call.

Run after cloning this repository to ~/.agents (it is private, so clone it with gh):

    gh repo clone flsteven87/agent-harness-setup ~/.agents -- --recurse-submodules
    uv run --no-project --with tomlkit python ~/.agents/scripts/bootstrap.py

Each step is idempotent and never overwrites a file it does not own:

1. Owl, the one submodule, is initialised.
2. ~/.claude is cloned from claude-code-setup (or fast-forwarded), its setup.sh links every shared
   skill, and every plugin its settings enable is installed.
3. Codex reads the shared profile through a link, and gets copies of the shared rules and agents
   (Codex does not apply a rules file reached through a symlink). A copy is refreshed only while it
   still equals some committed version of its source, so a host edit is reported, never lost. The
   keys in codex/config.base.toml are merged into ~/.codex/config.toml, leaving the keys Codex owns.
4. ~/.local/bin gets the account-neutral gh wrapper and the Code Review Graph launchers.

A path that already holds different content is reported as a conflict and left alone; a file with
identical content becomes the link. ``--check`` reports drift without writing. The exit code is 0
when the host matches, 1 when anything drifts or conflicts, 2 when a prerequisite is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit

HOME = Path.home()
AGENTS = HOME / ".agents"
CLAUDE = HOME / ".claude"
CODEX = HOME / ".codex"
CLAUDE_SETUP_URL = "https://github.com/flsteven87/claude-code-setup.git"
REQUIRED_TOOLS = ("git", "uv", "npx", "claude", "codex", "trash")
CRG_LAUNCHERS = (
    "code-review-graph-readonly",
    "crg-isolated-build",
    "crg-lifecycle",
    "crg-safe-refresh",
    "crg-worktree-attach",
    "crg-writer-supervisor",
)


@dataclass
class Report:
    check: bool
    done: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def change(self, message: str) -> bool:
        """Record a needed change; return True when this run may perform it."""
        (self.drift if self.check else self.done).append(message)
        return not self.check


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def links() -> dict[Path, Path]:
    pairs = {
        CODEX / "AGENTS.md": AGENTS / "PROFILE.md",
        HOME / ".local/bin/gh": AGENTS / "bin/gh",
    }
    for name in CRG_LAUNCHERS:
        pairs[HOME / ".local/bin" / name] = AGENTS / "skills/use-code-review-graph/scripts" / name
    return pairs


def copies() -> dict[Path, Path]:
    pairs = {CODEX / "rules/default.rules": AGENTS / "codex/rules/default.rules"}
    for agent in sorted((AGENTS / "codex/agents").glob("*.toml")):
        pairs[CODEX / "agents" / agent.name] = agent
    return pairs


def committed_blobs(source: Path) -> set[str]:
    rel = source.relative_to(AGENTS).as_posix()
    revs = run(["git", "-C", str(AGENTS), "rev-list", "HEAD", "--", rel]).stdout.split()
    blobs = (run(["git", "-C", str(AGENTS), "rev-parse", f"{rev}:{rel}"]).stdout.strip() for rev in revs)
    return {blob for blob in blobs if blob}


def ensure_copy(path: Path, source: Path, report: Report) -> None:
    label = str(path).replace(str(HOME), "~")
    if path.is_file() and not path.is_symlink() and path.read_bytes() == source.read_bytes():
        return
    if path.is_symlink() or not path.exists():
        pass
    elif run(["git", "hash-object", str(path)]).stdout.strip() not in committed_blobs(source):
        report.conflicts.append(f"{label} has host edits; fold them into {source}, then rerun")
        return
    if not report.change(f"copy {source} -> {label}"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.bootstrap-copy")
    shutil.copyfile(source, temporary)
    os.replace(temporary, path)


def ensure_link(path: Path, target: Path, report: Report) -> None:
    label = str(path).replace(str(HOME), "~")
    if path.is_symlink() and path.resolve() == target.resolve():
        return
    if path.is_symlink() or (path.exists() and not path.is_file()):
        report.conflicts.append(f"{label} points elsewhere; expected a link to {target}")
        return
    if path.exists() and path.read_bytes() != target.read_bytes():
        report.conflicts.append(f"{label} differs from {target}; merge it by hand, then rerun")
        return
    if not report.change(f"link {label} -> {target}"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.bootstrap-link")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(os.path.relpath(target, path.parent))
    os.replace(temporary, path)


# --- Codex config ----------------------------------------------------------------------------


def base_config() -> tomlkit.TOMLDocument:
    text = (AGENTS / "codex/config.base.toml").read_text(encoding="utf-8")
    return tomlkit.parse(text.replace("{HOME}", str(HOME)))


def merge_table(live, base, prefix: str, report: Report) -> None:
    for key, value in base.items():
        name = f"{prefix}{key}"
        if key == "skills" and "config" in value:
            merge_skill_gates(live, value["config"], report)
            continue
        if isinstance(value, dict):
            if key not in live:
                if report.change(f"config: add [{name}]"):
                    live[key] = tomlkit.table()
                else:
                    continue
            merge_table(live[key], value, f"{name}.", report)
        elif live.get(key) != value:
            if report.change(f"config: set {name} = {json.dumps(value)}"):
                live[key] = value


def merge_skill_gates(live, base_entries, report: Report) -> None:
    """The base owns every [[skills.config]] entry for a shared skill under ~/.agents/skills."""
    shared = str(AGENTS / "skills") + "/"
    wanted = {entry["path"]: dict(entry) for entry in base_entries}
    current = live.get("skills", {}).get("config", [])
    kept = [entry for entry in current if not str(entry.get("path", "")).startswith(shared)]
    present = {entry["path"]: dict(entry) for entry in current if str(entry.get("path", "")).startswith(shared)}
    if present == wanted:
        return
    if not report.change(f"config: set {len(wanted)} shared [[skills.config]] gates"):
        return
    skills = live.setdefault("skills", tomlkit.table())
    entries = tomlkit.aot()
    for entry in [*kept, *wanted.values()]:
        table = tomlkit.table()
        table.update(entry)
        entries.append(table)
    skills["config"] = entries


def sync_codex_config(report: Report) -> None:
    path = CODEX / "config.toml"
    live = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    before = tomlkit.dumps(live)
    merge_table(live, base_config(), "", report)
    after = tomlkit.dumps(live)
    if report.check or after == before:
        return
    if path.exists():
        shutil.copyfile(path, path.with_name("config.toml.before-bootstrap"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(after)
    os.replace(handle.name, path)


# --- Claude Code -----------------------------------------------------------------------------


def sync_claude(report: Report) -> None:
    if not CLAUDE.exists():
        if report.change("clone claude-code-setup into ~/.claude"):
            result = run(["git", "clone", "--quiet", CLAUDE_SETUP_URL, str(CLAUDE)])
            if result.returncode:
                report.conflicts.append(f"clone ~/.claude failed: {result.stderr.strip()}")
                return
        else:
            return
    elif run(["git", "-C", str(CLAUDE), "remote", "get-url", "origin"]).stdout.strip().removesuffix(".git").split(
        "/"
    )[-1] != "claude-code-setup":
        report.conflicts.append("~/.claude is not a claude-code-setup checkout; move it aside, then rerun")
        return
    else:
        run(["git", "-C", str(CLAUDE), "fetch", "--quiet", "origin"])
        behind = run(["git", "-C", str(CLAUDE), "rev-list", "--count", "HEAD..@{upstream}"]).stdout.strip()
        if behind not in ("", "0") and report.change(f"fast-forward ~/.claude by {behind} commits"):
            result = run(["git", "-C", str(CLAUDE), "merge", "--ff-only", "--quiet", "@{upstream}"])
            if result.returncode:
                report.conflicts.append(f"~/.claude cannot fast-forward: {result.stderr.strip()}")
    if report.check:
        return
    result = run(["bash", str(CLAUDE / "setup.sh")])
    if result.returncode:
        failures = [line for line in result.stdout.splitlines() if "✗" in line]
        report.conflicts.append("~/.claude/setup.sh failed: " + "; ".join(failures or [result.stderr.strip()]))
    else:
        report.done.append("ran ~/.claude/setup.sh")
    install_claude_plugins(report)


def install_claude_plugins(report: Report) -> None:
    settings = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))
    for name, source in settings.get("extraKnownMarketplaces", {}).items():
        repo = source.get("source", {}).get("repo")
        if repo and not (CLAUDE / "plugins/marketplaces" / name).exists():
            result = run(["claude", "plugin", "marketplace", "add", repo])
            (report.done if result.returncode == 0 else report.conflicts).append(f"claude marketplace {name}")
    installed = CLAUDE / "plugins/installed_plugins.json"
    have = set(json.loads(installed.read_text())["plugins"]) if installed.exists() else set()
    for plugin, enabled in settings.get("enabledPlugins", {}).items():
        if enabled and plugin not in have:
            result = run(["claude", "plugin", "install", plugin])
            (report.done if result.returncode == 0 else report.conflicts).append(f"claude plugin {plugin}")


# --- run -------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Give this host the shared agent setup.")
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args(argv)
    report = Report(check=args.check)

    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if shutil.which("gh") is None:
        missing.append("gh")
    if missing:
        print(json.dumps({"missing_tools": missing}, indent=2))
        return 2

    owl = AGENTS / "vendor/owl-designer-skills"
    if not any(owl.iterdir() if owl.is_dir() else []) and report.change("init vendor/owl-designer-skills"):
        run(["git", "-C", str(AGENTS), "submodule", "update", "--init", "--", "vendor/owl-designer-skills"])
    sync_claude(report)
    for path, target in links().items():
        ensure_link(path, target, report)
    for path, source in copies().items():
        ensure_copy(path, source, report)
    sync_codex_config(report)

    print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
    return 1 if report.drift or report.conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
