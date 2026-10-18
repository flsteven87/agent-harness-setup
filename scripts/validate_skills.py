#!/usr/bin/env python3
"""Validate skill folders with skill-creator's quick_validate, accepting Claude Code frontmatter.

quick_validate allows only the portable Agent Skills keys, so every skill that uses a Claude Code
field (argument-hint, disable-model-invocation, ...) fails it. This wrapper removes exactly the
documented Claude Code fields before running the unchanged validator; any other unknown key, a
misspelled Claude field included, still fails.

Usage: uv run --no-project --with pyyaml python scripts/validate_skills.py <skill-dir>...
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tempfile
from pathlib import Path

import yaml

DEFAULT_VALIDATOR = (
    Path.home()
    / ".claude/plugins/marketplaces/anthropic-agent-skills/skills/skill-creator/scripts/quick_validate.py"
)

# Claude Code SKILL.md fields beyond the portable set (code.claude.com/docs/en/skills, frontmatter
# reference). quick_validate already allows name, description, license, allowed-tools, metadata and
# compatibility.
CLAUDE_FIELDS = frozenset(
    {
        "when_to_use",
        "argument-hint",
        "arguments",
        "disable-model-invocation",
        "user-invocable",
        "disallowed-tools",
        "model",
        "effort",
        "context",
        "agent",
        "background",
        "hooks",
        "paths",
        "shell",
    }
)

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def load_validator(path: Path):
    spec = importlib.util.spec_from_file_location("quick_validate", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_skill


def portable_copy(skill_dir: Path, scratch: Path) -> Path:
    """Return a folder whose SKILL.md drops the Claude Code fields; the original is untouched."""
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = FRONTMATTER.match(content)
    if match is None:
        return skill_dir
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return skill_dir
    if not isinstance(frontmatter, dict) or not CLAUDE_FIELDS & frontmatter.keys():
        return skill_dir
    kept = {key: value for key, value in frontmatter.items() if key not in CLAUDE_FIELDS}
    target = scratch / skill_dir.name
    target.mkdir()
    body = content[match.end() :]
    dumped = yaml.safe_dump(kept, sort_keys=False, allow_unicode=True, width=10_000)
    (target / "SKILL.md").write_text(f"---\n{dumped}---{body}", encoding="utf-8")
    return target


def validate(skill_dirs: list[Path], validator_path: Path) -> list[tuple[Path, bool, str]]:
    validate_skill = load_validator(validator_path)
    results = []
    with tempfile.TemporaryDirectory() as scratch:
        for skill_dir in skill_dirs:
            if not (skill_dir / "SKILL.md").is_file():
                results.append((skill_dir, False, "SKILL.md not found"))
                continue
            valid, message = validate_skill(portable_copy(skill_dir, Path(scratch)))
            results.append((skill_dir, valid, message))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate skill folders, accepting Claude Code fields.")
    parser.add_argument("skills", nargs="+", type=Path, help="skill folders to validate")
    parser.add_argument("--validator", type=Path, default=DEFAULT_VALIDATOR)
    args = parser.parse_args(argv)
    if not args.validator.is_file():
        print(f"skill-creator validator not found: {args.validator}", file=sys.stderr)
        return 2
    results = validate([path.resolve() for path in args.skills], args.validator)
    for skill_dir, valid, message in results:
        print(f"{'ok  ' if valid else 'FAIL'} {skill_dir.name}: {message}")
    return 0 if all(valid for _, valid, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
