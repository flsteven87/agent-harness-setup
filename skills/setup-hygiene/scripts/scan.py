#!/usr/bin/env python3
"""Read-only inventory for projectless user-level setup integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = 2
SKIP_DIRS = {
    ".git", "node_modules", "projects", "sessions", "history", "file-history",
    "logs", "vendor_imports", "__pycache__", ".pytest_cache",
}
BACKUP_RE = re.compile(
    r"(?i)(?:\.bak(?=$|[._-])|\.backup(?=$|[._-])|\.old(?=$|[._-])|"
    r"\.orig(?=$|[._-])|\.tmp(?=$|[._-])|\.pre(?=$|[._-])|"
    r"doctor-backup|doctor-quarantine|(?:^|[._-])quarantine(?:$|[._-]))"
)
SECRET_EXPORT_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*(?:_TOKEN|_SECRET|_API_KEY|"
    r"_PASSWORD|_CREDENTIAL|_COOKIE|_AUTH_HEADER))\s*="
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER_NAME_RE = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
PENDING_RE = re.compile(r"(?i)\[ \]|TODO|PENDING|IN PROGRESS")
DONE_RE = re.compile(r"(?i)\[x\]|COMPLETED|DONE")


class Inventory:
    def __init__(self, home: Path) -> None:
        self.home = home.resolve()
        self.records: list[dict[str, Any]] = []

    def visible(self, path: Path) -> str:
        absolute = path.expanduser()
        if not absolute.is_absolute():
            absolute = Path.cwd() / absolute
        try:
            rel = absolute.relative_to(self.home)
            return "~" if not rel.parts else f"~/{rel.as_posix()}"
        except ValueError:
            return str(absolute)

    def emit(self, surface: str, check: str, status: str, **details: Any) -> None:
        record = {"surface": surface, "check": check, "status": status}
        record.update(details)
        self.records.append(record)

    def print_jsonl(self) -> None:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record["status"]] = counts.get(record["status"], 0) + 1
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        print(json.dumps({
            "surface": "run", "check": "summary", "status": "summary",
            "records": len(self.records), "status_counts": counts,
        }, ensure_ascii=False, sort_keys=True))

    def document(self, generated_at: datetime | None = None) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for record in self.records:
            status = str(record["status"])
            counts[status] = counts.get(status, 0) + 1
        attention = sum(
            counts.get(status, 0)
            for status in ("candidate", "review", "handoff", "blocked")
        )
        if counts.get("blocked"):
            overall = "blocked"
        elif attention:
            overall = "attention"
        else:
            overall = "clean"
        observed_at = generated_at or datetime.now(timezone.utc)
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": observed_at.astimezone(timezone.utc).isoformat(),
            "home": "~",
            "overall_status": overall,
            "records": self.records,
            "summary": {
                "records": len(self.records),
                "status_counts": counts,
                "attention_records": attention,
            },
        }

    def print_json(self) -> None:
        print(json.dumps(self.document(), ensure_ascii=False, indent=2, sort_keys=True))


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def strip_fenced_blocks(text: str) -> str:
    kept: list[str] = []
    in_fence = False
    marker = ""
    for line in text.splitlines():
        match = re.match(r"^\s*(```+|~~~+)", line)
        if match:
            token = match.group(1)
            if not in_fence:
                in_fence = True
                marker = token[0]
            elif token[0] == marker:
                in_fence = False
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def tree_metrics(path: Path) -> tuple[int, int, int | None]:
    count = 0
    size = 0
    oldest: int | None = None
    if not path.exists():
        return count, size, oldest
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [name for name in dirnames if name not in {".git", "node_modules"}]
        for name in filenames:
            item = Path(dirpath) / name
            try:
                stat = item.stat()
            except OSError:
                continue
            count += 1
            size += stat.st_size
            stamp = int(stat.st_mtime)
            oldest = stamp if oldest is None else min(oldest, stamp)
    return count, size, oldest


def sha256_paths(paths: Iterable[Path], home: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        try:
            rel = path.resolve(strict=False).relative_to(home).as_posix()
            data = path.read_bytes()
        except (OSError, ValueError):
            continue
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def infer_orca_codex_home(binary: Path) -> Path | None:
    """Return the Orca-managed Codex home encoded in a runtime binary path."""
    parts = binary.parts
    try:
        accounts_index = parts.index("codex-accounts")
    except ValueError:
        return None
    home_index = accounts_index + 2
    if len(parts) <= home_index or parts[home_index] != "home":
        return None
    return Path(*parts[:home_index + 1])


def discover_codex_homes(inv: Inventory, binary: str | None) -> list[Path]:
    homes: dict[Path, set[str]] = {}

    def add(path: Path, role: str) -> None:
        resolved = path.expanduser().resolve(strict=False)
        homes.setdefault(resolved, set()).add(role)

    add(inv.home / ".codex", "default")
    configured = os.environ.get("CODEX_HOME")
    if configured:
        add(Path(configured), "environment")
    if binary:
        inferred = infer_orca_codex_home(Path(binary).resolve(strict=False))
        if inferred:
            add(inferred, "active-runtime")

    records = [
        {
            "path": inv.visible(path),
            "roles": sorted(roles),
            "exists": path.is_dir(),
            "config": (path / "config.toml").is_file(),
            "hooks": (path / "hooks.json").is_file(),
        }
        for path, roles in sorted(homes.items(), key=lambda item: str(item[0]))
    ]
    inv.emit("codex", "home-inventory", "clean", homes=records, count=len(records))
    return list(sorted(homes, key=str))


def summarize_doctor(report: dict[str, Any]) -> dict[str, Any]:
    raw_checks = report.get("checks")
    if isinstance(raw_checks, dict):
        checks = list(raw_checks.values())
    elif isinstance(raw_checks, list):
        checks = raw_checks
    else:
        checks = []

    status_counts: dict[str, int] = {}
    warning_checks: list[dict[str, Any]] = []
    for raw in checks:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "unknown").lower()
        status_counts[status] = status_counts.get(status, 0) + 1
        if status != "ok":
            warning_checks.append({
                "id": str(raw.get("id") or "unknown"),
                "category": str(raw.get("category") or "unknown"),
                "status": status,
                "summary": str(raw.get("summary") or "")[:300],
                "duration_ms": raw.get("durationMs"),
            })
    return {
        "schema_version": report.get("schemaVersion"),
        "codex_version": report.get("codexVersion"),
        "overall_status": str(report.get("overallStatus") or "unknown").lower(),
        "checks": sum(status_counts.values()),
        "status_counts": status_counts,
        "warning_checks": warning_checks,
    }


def run_bounded(
    args: list[str], *, timeout: int, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_feature_listing(text: str) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        match = re.match(r"^(\S+)\s{2,}(.+?)\s{2,}(true|false)\s*$", line)
        if not match:
            continue
        features[match.group(1)] = {
            "maturity": match.group(2).strip(),
            "enabled": match.group(3) == "true",
        }
    return features


def scan_feature_maturity(inv: Inventory, homes: list[Path], listing: str) -> None:
    features = parse_feature_listing(listing)
    explicit_enabled: set[str] = set()
    for home in homes:
        config = home / "config.toml"
        if not config.is_file():
            continue
        try:
            import tomllib
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        configured = parsed.get("features") if isinstance(parsed, dict) else None
        if isinstance(configured, dict):
            explicit_enabled.update(
                str(name) for name, enabled in configured.items() if enabled is True
            )

    nonstable = sorted(
        name for name in explicit_enabled
        if name not in features or features[name]["maturity"] != "stable"
    )
    maturity_counts: dict[str, int] = {}
    for value in features.values():
        maturity = str(value["maturity"])
        maturity_counts[maturity] = maturity_counts.get(maturity, 0) + 1
    inv.emit(
        "codex", "feature-maturity", "review" if nonstable else "clean",
        available=len(features), maturity_counts=maturity_counts,
        explicit_enabled=sorted(explicit_enabled), explicit_nonstable=nonstable,
        expected="explicitly enabled features should use stable contracts unless deliberately reviewed",
    )


def select_doctor_homes(
    homes: list[Path], binary: str | None, scope: str, default_home: Path | None = None,
) -> list[Path]:
    if scope == "all":
        return homes
    if scope == "default":
        default = (default_home or Path.home() / ".codex").resolve(strict=False)
        return [home for home in homes if home == default]
    if scope == "active" and binary:
        inferred = infer_orca_codex_home(Path(binary).resolve(strict=False))
        if inferred and inferred in homes:
            return [inferred]
    return []


def scan_codex_runtime(inv: Inventory, timeout: int, doctor_scope: str) -> list[Path]:
    binary = shutil.which("codex")
    homes = discover_codex_homes(inv, binary)
    doctor_homes = select_doctor_homes(homes, binary, doctor_scope, inv.home / ".codex")
    inv.emit(
        "codex", "doctor-scope", "clean" if doctor_homes else "blocked", scope=doctor_scope,
        homes=[inv.visible(home) for home in doctor_homes],
        excluded=[{"home": inv.visible(home), "reason": "outside requested doctor scope"}
                  for home in homes if home not in doctor_homes],
        observed="requested homes selected" if doctor_homes else "active Orca runtime home could not be identified",
        **({"discharge": "identify the active Orca executable/home or explicitly choose all scope"}
           if not doctor_homes else {}),
    )
    if not binary:
        inv.emit(
            "codex", "runtime", "handoff", observed="codex executable is absent from PATH",
            owner="daily development-tool updater",
        )
        for home in doctor_homes:
            inv.emit(
                "codex", "doctor", "blocked", home=inv.visible(home),
                observed="codex executable is absent from PATH",
                discharge="daily development-tool updater restores the intended executable",
            )
        return homes

    inv.emit(
        "codex", "runtime-binary", "clean", path=inv.visible(Path(binary)),
        resolved_path=inv.visible(Path(binary).resolve(strict=False)),
    )
    for home in homes:
        if not home.is_dir():
            if home in doctor_homes:
                inv.emit(
                    "codex", "doctor", "blocked", home=inv.visible(home),
                    observed="selected runtime home directory is absent",
                    discharge="runtime owner confirms or restores the intended home directory",
                )
            continue
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        strict = run_bounded([binary, "--strict-config", "--version"], timeout=10, env=env)
        if strict is None:
            inv.emit(
                "codex", "strict-config", "blocked", home=inv.visible(home),
                observed="strict config probe timed out or could not start",
            )
        elif strict.returncode:
            inv.emit(
                "codex", "strict-config", "review", home=inv.visible(home),
                observed="strict config probe failed", exit_code=strict.returncode,
            )
        else:
            inv.emit(
                "codex", "strict-config", "clean", home=inv.visible(home),
                version=strict.stdout.strip()[:100],
            )

        if home not in doctor_homes:
            continue
        doctor = run_bounded([binary, "doctor", "--json"], timeout=timeout, env=env)
        if doctor is None:
            inv.emit(
                "codex", "doctor", "blocked", home=inv.visible(home),
                observed="doctor timed out or could not start",
                discharge=f"rerun with a timeout longer than {timeout} seconds",
            )
            continue
        if doctor.returncode:
            inv.emit(
                "codex", "doctor", "blocked", home=inv.visible(home),
                observed="doctor returned a nonzero status", exit_code=doctor.returncode,
            )
            continue
        try:
            summary = summarize_doctor(json.loads(doctor.stdout))
        except (json.JSONDecodeError, TypeError, ValueError):
            inv.emit(
                "codex", "doctor", "blocked", home=inv.visible(home),
                observed="doctor output was not valid JSON",
            )
            continue
        status = "clean" if summary["overall_status"] == "ok" else "handoff"
        inv.emit(
            "codex", "doctor", status, home=inv.visible(home), report=summary,
            owner="daily development-tool updater" if status == "handoff" else None,
        )

    feature_result = run_bounded([binary, "features", "list"], timeout=10)
    if feature_result is None or feature_result.returncode:
        inv.emit(
            "codex", "feature-maturity", "blocked",
            observed="feature inventory could not be read",
        )
    else:
        scan_feature_maturity(inv, homes, feature_result.stdout)
    return homes


def parse_state_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def scan_state_freshness(
    inv: Inventory,
    current_digest: str,
    *,
    max_age_hours: int,
    now: datetime | None = None,
) -> None:
    state = inv.home / ".local" / "state" / "setup-hygiene" / "state.md"
    if not state.is_file():
        inv.emit(
            "state", "setup-hygiene-freshness", "review", path=inv.visible(state),
            observed="state file is missing", expected="a bounded current state checkpoint",
        )
        return
    text = read_text(state)
    if text is None:
        inv.emit(
            "state", "setup-hygiene-freshness", "blocked", path=inv.visible(state),
            observed="state file is not readable as UTF-8",
        )
        return
    last_match = re.search(r"^- Last run:\s*(\S+)\s*$", text, re.MULTILINE)
    digest_match = re.search(
        r"^- Instruction digest:\s*`?([0-9a-fA-F-]+)`?\s*$", text, re.MULTILINE
    )
    last_run = parse_state_timestamp(last_match.group(1)) if last_match else None
    observed_at = now or datetime.now(timezone.utc)
    age_hours = None
    if last_run:
        age_hours = max(0.0, (observed_at - last_run.astimezone(timezone.utc)).total_seconds() / 3600)
    stored_digest = digest_match.group(1) if digest_match else None
    digest_matches = stored_digest == current_digest
    stale = age_hours is None or age_hours > max_age_hours
    status = "review" if stale or not digest_matches else "clean"
    inv.emit(
        "state", "setup-hygiene-freshness", status, path=inv.visible(state),
        last_run=last_run.isoformat() if last_run else None,
        age_hours=round(age_hours, 1) if age_hours is not None else None,
        max_age_hours=max_age_hours, digest_matches=digest_matches,
        observed="state is stale or its instruction digest changed" if status == "review" else "state is current",
    )


def scheduler_purpose(*values: Any) -> str | None:
    text = " ".join(str(value) for value in values if value).lower()
    if "setup-hygiene" in text or "setup hygiene" in text:
        return "setup-hygiene"
    if "agent 摩擦" in text or "agent-friction" in text:
        return "agent-friction"
    if "daily-dev-update" in text or "每日開發工具更新" in text:
        return "daily-dev-update"
    return None


def scheduler_entries_from_orca(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    automations = result.get("automations") if isinstance(result, dict) else None
    if not isinstance(automations, list):
        return []
    entries: list[dict[str, Any]] = []
    for raw in automations:
        if not isinstance(raw, dict):
            continue
        purpose = scheduler_purpose(raw.get("name"))
        if not purpose:
            continue
        entries.append({
            "source": "orca",
            "name": str(raw.get("name") or "unnamed"),
            "purpose": purpose,
            "enabled": raw.get("enabled") is True,
            "owner": str(raw.get("schedulerOwner") or "unknown"),
            "schedule": raw.get("rrule"),
        })
    return entries


def scheduler_conflicts(entries: list[dict[str, Any]]) -> dict[str, int]:
    enabled: dict[str, int] = {}
    for entry in entries:
        purpose = entry.get("purpose")
        if isinstance(purpose, str) and entry.get("enabled") is True:
            enabled[purpose] = enabled.get(purpose, 0) + 1
    return {purpose: count for purpose, count in enabled.items() if count > 1}


def parse_launchd_disabled(text: str) -> dict[str, bool]:
    states = re.findall(
        r'"([^"]+)"\s*=>\s*(true|false|enabled|disabled)', text
    )
    return {
        name: value in {"true", "disabled"}
        for name, value in states
    }


def launchd_disabled_services(timeout: int = 5) -> dict[str, bool]:
    result = run_bounded(
        ["launchctl", "print-disabled", f"gui/{os.getuid()}"], timeout=timeout
    )
    if result is None or result.returncode:
        return {}
    return parse_launchd_disabled(result.stdout)


def scan_scheduler_ownership(inv: Inventory, timeout: int) -> None:
    entries: list[dict[str, Any]] = []
    disabled = launchd_disabled_services()
    launch_agents = inv.home / "Library" / "LaunchAgents"
    if launch_agents.is_dir():
        for path in sorted(launch_agents.glob("*.plist")):
            try:
                with path.open("rb") as handle:
                    parsed = plistlib.load(handle)
            except (OSError, plistlib.InvalidFileException):
                continue
            if not isinstance(parsed, dict):
                continue
            label = str(parsed.get("Label") or path.stem)
            arguments = parsed.get("ProgramArguments") or []
            purpose = scheduler_purpose(label, *arguments if isinstance(arguments, list) else [])
            if not purpose:
                continue
            is_disabled = disabled.get(label)
            entries.append({
                "source": "launchd",
                "name": label,
                "purpose": purpose,
                "enabled": None if is_disabled is None else not is_disabled,
                "owner": "launchd",
                "schedule": "calendar" if parsed.get("StartCalendarInterval") else None,
                "path": inv.visible(path),
            })

    codex_automations = inv.home / ".codex" / "automations"
    if codex_automations.is_dir():
        for path in sorted(codex_automations.glob("*/automation.toml")):
            try:
                import tomllib
                parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            purpose = scheduler_purpose(parsed.get("name"), parsed.get("id"))
            if not purpose:
                continue
            status = str(parsed.get("status") or "").upper()
            entries.append({
                "source": "codex-automation",
                "name": str(parsed.get("name") or path.parent.name),
                "purpose": purpose,
                "enabled": status not in {"PAUSED", "DISABLED"},
                "owner": "codex-automation",
                "schedule": parsed.get("rrule"),
                "path": inv.visible(path),
            })

    orca = shutil.which("orca")
    orca_measured = False
    if orca:
        result = run_bounded([orca, "automations", "list", "--json"], timeout=timeout)
        if result is not None and result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                entries.extend(scheduler_entries_from_orca(payload))
                orca_measured = True

    conflicts = scheduler_conflicts(entries)
    if not orca_measured:
        status = "blocked"
        observed = "Orca automation ownership could not be measured"
    elif conflicts:
        status = "review"
        observed = "more than one enabled scheduler owns the same purpose"
    else:
        status = "clean"
        observed = "each measured purpose has at most one enabled scheduler owner"
    inv.emit(
        "scheduler", "ownership", status, entries=entries, conflicts=conflicts,
        orca_measured=orca_measured, observed=observed,
    )


def scan_invocation_policy(inv: Inventory, folder: Path, entrypoint_text: str) -> None:
    disable = re.search(r"^disable-model-invocation:\s*(true|false)\s*$", entrypoint_text, re.MULTILINE | re.IGNORECASE)
    metadata = folder / "agents" / "openai.yaml"
    metadata_text = read_text(metadata) if metadata.is_file() else None
    allow = re.search(
        r"^\s*allow_implicit_invocation:\s*(true|false)\s*$",
        metadata_text or "",
        re.MULTILINE | re.IGNORECASE,
    )
    if not disable or not allow:
        return
    disabled = disable.group(1).lower() == "true"
    allowed = allow.group(1).lower() == "true"
    if allowed == disabled:
        inv.emit(
            "skills", "invocation-policy", "review", path=inv.visible(folder),
            observed={"disable_model_invocation": disabled, "allow_implicit_invocation": allowed},
            expected="the two product faces must agree",
        )


def scan_skills(inv: Inventory) -> list[Path]:
    agents = inv.home / ".agents" / "skills"
    claude = inv.home / ".claude" / "skills"
    docs: list[Path] = []
    canonical: dict[str, Path] = {}

    if agents.is_dir():
        for folder in sorted(agents.iterdir(), key=lambda item: item.name):
            if not folder.is_dir():
                continue
            entrypoint = folder / "SKILL.md"
            if not entrypoint.is_file():
                inv.emit("skills", "entrypoint", "candidate", path=inv.visible(folder), observed="missing SKILL.md")
                continue
            canonical[folder.name] = folder
            docs.append(entrypoint)
            text = read_text(entrypoint)
            match = FRONTMATTER_NAME_RE.search(text or "")
            if not match:
                inv.emit("skills", "identity", "candidate", path=inv.visible(entrypoint), observed="missing frontmatter name")
            else:
                declared = yaml_scalar(match.group(1))
                if declared != folder.name:
                    inv.emit("skills", "identity", "candidate", path=inv.visible(entrypoint), observed=declared, expected=folder.name)
            scan_invocation_policy(inv, folder, text or "")
            refs = folder / "references"
            if refs.is_dir():
                docs.extend(path for path in refs.rglob("*.md") if path.is_file())

    symlinks = 0
    broken = 0
    duplicate_dirs = 0
    claude_only = 0
    claude_entries = 0
    if claude.is_dir():
        for item in sorted(claude.iterdir(), key=lambda path: path.name):
            claude_entries += 1
            if item.is_symlink():
                symlinks += 1
                if not item.exists():
                    broken += 1
                    inv.emit(
                        "skills", "claude-symlink", "candidate", path=inv.visible(item),
                        observed=os.readlink(item),
                        expected=inv.visible(canonical[item.name]) if item.name in canonical else "no unique canonical target",
                    )
                elif item.name in canonical and item.resolve() != canonical[item.name].resolve():
                    inv.emit(
                        "skills", "claude-symlink", "candidate", path=inv.visible(item),
                        observed=inv.visible(item.resolve()), expected=inv.visible(canonical[item.name]),
                    )
            elif item.is_dir():
                if item.name in canonical:
                    duplicate_dirs += 1
                    inv.emit(
                        "skills", "duplicate-owner", "review", path=inv.visible(item),
                        canonical=inv.visible(canonical[item.name]),
                        observed="real directories exist in both skill trees",
                    )
                else:
                    claude_only += 1
                    entrypoint = item / "SKILL.md"
                    inv.emit(
                        "skills", "claude-only-owner", "review", path=inv.visible(item),
                        entrypoint=entrypoint.is_file(),
                        observed="real skill directory exists outside the canonical Agents tree",
                    )
                    if entrypoint.is_file():
                        docs.append(entrypoint)
                        text = read_text(entrypoint)
                        match = FRONTMATTER_NAME_RE.search(text or "")
                        if not match or yaml_scalar(match.group(1)) != item.name:
                            inv.emit(
                                "skills", "identity", "review", path=inv.visible(entrypoint),
                                observed=yaml_scalar(match.group(1)) if match else "missing frontmatter name",
                                expected=item.name,
                            )
                        scan_invocation_policy(inv, item, text or "")
                        refs = item / "references"
                        if refs.is_dir():
                            docs.extend(path for path in refs.rglob("*.md") if path.is_file())

    inv.emit(
        "skills", "inventory", "clean" if not broken and not duplicate_dirs and not claude_only else "candidate",
        canonical=len(canonical), claude_symlinks=symlinks, broken_symlinks=broken,
        claude_entries=claude_entries, duplicate_real_directories=duplicate_dirs,
        claude_only_real_directories=claude_only,
    )
    return docs


def instruction_docs(inv: Inventory, skill_docs: list[Path]) -> list[Path]:
    candidates = [
        inv.home / ".agents" / "AGENTS.md", inv.home / ".agents" / "PROFILE.md",
        inv.home / ".claude" / "CLAUDE.md",
        inv.home / ".codex" / "AGENTS.md", inv.home / ".codex" / "AGENTS.override.md",
    ]
    docs = [path for path in candidates if path.is_file()] + skill_docs
    unique = sorted(set(docs), key=lambda path: str(path))
    inv.emit("instructions", "inventory", "clean", files=len(unique), digest=sha256_paths(unique, inv.home))
    return unique


def scan_markdown_links(inv: Inventory, docs: list[Path]) -> None:
    checked = 0
    candidates = 0
    for source in docs:
        text = read_text(source)
        if text is None:
            inv.emit("instructions", "markdown-read", "blocked", path=inv.visible(source), observed="not readable as UTF-8")
            continue
        for raw in MARKDOWN_LINK_RE.findall(strip_fenced_blocks(text)):
            target = raw.strip()
            if target.startswith("<") and ">" in target:
                target = target[1:target.index(">")]
            else:
                target = target.split(maxsplit=1)[0]
            checked += 1
            parsed = urlsplit(target)
            if not target or target.startswith("#") or parsed.scheme:
                continue
            target = unquote(parsed.path)
            if not target:
                continue
            if any(token in target for token in ("{", "}", "*", "$")):
                continue
            target_path = Path(target).expanduser() if target.startswith(("/", "~")) else source.parent / target
            resolved = target_path.resolve(strict=False)
            try:
                resolved.relative_to(inv.home)
            except ValueError:
                inv.emit(
                    "instructions", "markdown-link", "handoff", path=inv.visible(source),
                    target=target, observed="pointer leaves the projectless user-level boundary",
                )
                continue
            if not target_path.exists():
                candidates += 1
                inv.emit(
                    "instructions", "markdown-link", "candidate", path=inv.visible(source),
                    target=target,
                    observed="target does not resolve; confirm live pointer versus example",
                )
    inv.emit(
        "instructions", "markdown-links", "clean" if candidates == 0 else "candidate",
        checked=checked, unresolved_candidates=candidates,
    )


def scan_backup_candidates(inv: Inventory) -> None:
    roots = [
        inv.home / ".agents", inv.home / ".claude", inv.home / ".codex",
        inv.home / ".config", inv.home / ".local" / "bin",
    ]
    found = 0
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [
                name for name in dirnames
                if name not in SKIP_DIRS
                and not (current.name == "plugins" and name in {"cache", "data"})
                and not (current == inv.home / ".codex" and name == ".tmp")
                and not (current == inv.home / ".claude" and name == "backups")
            ]
            for name in list(dirnames):
                if BACKUP_RE.search(name):
                    path = current / name
                    count, size, _ = tree_metrics(path)
                    found += 1
                    inv.emit(
                        "sediment", "backup-candidate", "review", path=inv.visible(path),
                        kind="directory", files=count, bytes=size,
                        age_days=max(0, int((time.time() - path.stat().st_mtime) // 86400)),
                    )
            for name in filenames:
                if not BACKUP_RE.search(name) or name.startswith("pre_compact_"):
                    continue
                path = current / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                found += 1
                inv.emit(
                    "sediment", "backup-candidate", "review", path=inv.visible(path),
                    kind="file", bytes=stat.st_size,
                    age_days=max(0, int((time.time() - stat.st_mtime) // 86400)),
                )
    inv.emit("sediment", "backup-inventory", "clean" if found == 0 else "review", candidates=found)


def current_process_path() -> tuple[int, list[str]]:
    """Return the inherited PATH without executing user shell startup files."""
    raw = os.environ.get("PATH", "")
    return (0 if raw else 1), [entry for entry in raw.split(os.pathsep) if entry.startswith("/")]


def scan_shell(inv: Inventory) -> None:
    files = [inv.home / name for name in (".zshrc", ".zprofile", ".bashrc", ".bash_profile")]
    existing = [path for path in files if path.is_file()]
    syntax_failures = 0
    secret_exports = 0
    for path in existing:
        if path.name.startswith(".z"):
            result = subprocess.run(["/bin/zsh", "-n", str(path)], capture_output=True, text=True, check=False)
            if result.returncode:
                syntax_failures += 1
                inv.emit("shell", "syntax", "review", path=inv.visible(path), observed="zsh syntax check failed")
        text = read_text(path) or ""
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = SECRET_EXPORT_RE.match(line)
            if match:
                secret_exports += 1
                inv.emit(
                    "shell", "global-secret-export", "review", path=inv.visible(path),
                    line=line_number, variable=match.group(1),
                    observed="secret-like variable is assigned in shell startup; value not read or reported",
                )

    path_status, path_entries = current_process_path()
    duplicates = sorted({entry for entry in path_entries if path_entries.count(entry) > 1})
    for entry in duplicates:
        inv.emit("shell", "path-duplicate", "review", path=inv.visible(Path(entry)), occurrences=path_entries.count(entry))
    inv.emit(
        "shell", "inventory",
        "clean" if not syntax_failures and not secret_exports and not duplicates and path_status == 0 else "review",
        startup_files=len(existing), syntax_failures=syntax_failures,
        secret_like_exports=secret_exports, effective_path_entries=len(path_entries),
        duplicate_path_entries=len(duplicates), current_process_path_status=path_status,
    )


def command_path(value: str) -> str | None:
    if value.startswith("./"):
        # App-managed MCP commands can be relative to a runtime-selected cwd rather than
        # the config directory. The scan cannot prove their base without starting the owner.
        return None
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if not parts:
        return None
    token = parts[0]
    return token if "/" in token or token.startswith("~") else None


def walk_config_paths(value: Any, trail: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_config_paths(child, trail + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_config_paths(child, trail + (str(index),))
    elif isinstance(value, str) and trail:
        key = trail[-1].lower()
        if key in {"path", "script", "command"} or key.endswith(("path", "script", "command")):
            candidate = command_path(value) if "command" in key else value
            if candidate:
                yield trail, candidate


def scan_config_paths(inv: Inventory) -> None:
    configs: list[tuple[Path, Any]] = []
    claude = inv.home / ".claude" / "settings.json"
    if claude.is_file():
        try:
            configs.append((claude, json.loads(claude.read_text())))
        except (OSError, json.JSONDecodeError):
            inv.emit("config", "parse", "blocked", path=inv.visible(claude), observed="invalid JSON or unreadable")
    codex = inv.home / ".codex" / "config.toml"
    if codex.is_file():
        try:
            import tomllib
            configs.append((codex, tomllib.loads(codex.read_text())))
        except (OSError, ValueError):
            inv.emit("config", "parse", "blocked", path=inv.visible(codex), observed="invalid TOML or unreadable")

    checked = 0
    missing = 0
    for config, data in configs:
        for trail, raw in walk_config_paths(data):
            checked += 1
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = config.parent / path
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(inv.home)
            except ValueError:
                continue
            if not path.exists():
                missing += 1
                inv.emit(
                    "config", "local-pointer", "review", path=inv.visible(config),
                    key=".".join(trail), target=inv.visible(resolved),
                    observed="local target does not resolve",
                )
    inv.emit("config", "pointer-inventory", "clean" if missing == 0 else "review", checked=checked, missing=missing)


def scan_codex_route_pin(inv: Inventory) -> None:
    # The owner profile cites this pin as Codex route evidence; Orca mirrors it into account homes.
    path = inv.home / ".codex" / "config.toml"
    try:
        import tomllib
        value = tomllib.loads(path.read_text()).get("forced_login_method") if path.is_file() else None
    except (OSError, ValueError):
        inv.emit("config", "codex-route-pin", "blocked", path=inv.visible(path), observed="invalid TOML or unreadable")
        return
    if value == "chatgpt":
        inv.emit("config", "codex-route-pin", "clean", path=inv.visible(path))
    else:
        inv.emit("config", "codex-route-pin", "review", path=inv.visible(path),
                 observed=f"forced_login_method is {value!r}; expected 'chatgpt'")


def scan_mcp_and_plugins(inv: Inventory) -> None:
    settings: dict[str, Any] = {}
    claude_state: dict[str, Any] = {}
    installed: dict[str, Any] = {}
    marketplaces: dict[str, Any] = {}
    codex: dict[str, Any] = {}

    json_inputs = [
        (inv.home / ".claude" / "settings.json", "settings"),
        (inv.home / ".claude.json", "claude_state"),
        (inv.home / ".claude" / "plugins" / "installed_plugins.json", "installed"),
        (inv.home / ".claude" / "plugins" / "known_marketplaces.json", "marketplaces"),
    ]
    parsed: dict[str, dict[str, Any]] = {}
    for path, label in json_inputs:
        if not path.is_file():
            parsed[label] = {}
            continue
        try:
            value = json.loads(path.read_text())
            parsed[label] = value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            inv.emit("integrations", "inventory-parse", "blocked", path=inv.visible(path), observed="invalid JSON or unreadable")
            parsed[label] = {}
    settings = parsed["settings"]
    claude_state = parsed["claude_state"]
    installed = parsed["installed"]
    marketplaces = parsed["marketplaces"]

    codex_path = inv.home / ".codex" / "config.toml"
    if codex_path.is_file():
        try:
            import tomllib
            value = tomllib.loads(codex_path.read_text())
            codex = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            inv.emit("integrations", "inventory-parse", "blocked", path=inv.visible(codex_path), observed="invalid TOML or unreadable")

    enabled_raw = settings.get("enabledPlugins") or {}
    enabled = {name for name, active in enabled_raw.items() if active} if isinstance(enabled_raw, dict) else set()
    installed_raw = installed.get("plugins", installed)
    installed_names = set(installed_raw) if isinstance(installed_raw, dict) else set()
    missing_plugins = sorted(enabled - installed_names)
    for name in missing_plugins:
        inv.emit(
            "integrations", "enabled-plugin", "review", name=name,
            observed="enabled plugin is absent from the local installed inventory",
        )

    extra_raw = settings.get("extraKnownMarketplaces") or {}
    extra_names = set(extra_raw) if isinstance(extra_raw, dict) else set()
    known_names = set(marketplaces) if isinstance(marketplaces, dict) else set()
    missing_marketplaces = sorted(extra_names - known_names)
    for name in missing_marketplaces:
        inv.emit(
            "integrations", "marketplace-pointer", "review", name=name,
            observed="configured marketplace is absent from the local known inventory",
        )

    skill_roots = [inv.home / ".agents" / "skills", inv.home / ".claude" / "skills"]
    local_skills = {
        child.name for root in skill_roots if root.is_dir()
        for child in root.iterdir() if child.is_dir() or child.is_symlink()
    }
    overrides_raw = settings.get("skillOverrides") or {}
    override_names = set(overrides_raw) if isinstance(overrides_raw, dict) else set()
    missing_overrides = sorted(override_names - local_skills)
    for name in missing_overrides:
        inv.emit(
            "integrations", "skill-override", "review", name=name,
            observed="skill override names no local user-level skill",
        )

    mcp_sets = [
        ("claude", claude_state.get("mcpServers") or {}),
        ("codex", codex.get("mcp_servers") or {}),
    ]
    path_status, path_entries = current_process_path()
    process_path = os.pathsep.join(path_entries)
    missing_commands = 0
    contextual_commands = 0
    mcp_count = 0
    for owner, servers in mcp_sets:
        if not isinstance(servers, dict):
            continue
        mcp_count += len(servers)
        for name, config in servers.items():
            if not isinstance(config, dict):
                continue
            command = config.get("command")
            if isinstance(command, list):
                command = command[0] if command else None
            if not isinstance(command, str) or not command:
                continue
            if command.startswith("./"):
                contextual_commands += 1
                continue
            try:
                token = shlex.split(command)[0]
            except (ValueError, IndexError):
                continue
            if token.startswith(("/", "~")):
                exists = Path(token).expanduser().exists()
            else:
                exists = bool(path_status == 0 and shutil.which(token, path=process_path))
            if not exists:
                missing_commands += 1
                inv.emit(
                    "integrations", "mcp-command", "review", owner=owner, name=name,
                    command=token, observed="configured command does not resolve in the current process environment",
                )

    issues = len(missing_plugins) + len(missing_marketplaces) + len(missing_overrides) + missing_commands
    inv.emit(
        "integrations", "inventory", "clean" if issues == 0 else "review",
        enabled_plugins=len(enabled), installed_plugins=len(installed_names),
        configured_marketplaces=len(extra_names), known_marketplaces=len(known_names),
        skill_overrides=len(override_names), mcp_servers=mcp_count,
        contextual_mcp_commands=contextual_commands, unresolved=issues,
    )


def scan_memories_and_plans(inv: Inventory, max_lines: int, max_bytes: int) -> None:
    memories = [
        inv.home / ".claude" / "automations" / "daily-dev-update" / "memory.md",
        inv.home / ".codex" / "automations" / "automation" / "memory.md",
    ]
    for path in memories:
        if not path.is_file():
            continue
        text = read_text(path) or ""
        lines = len(text.splitlines())
        size = path.stat().st_size
        inv.emit(
            "state", "memory-growth", "review" if lines > max_lines or size > max_bytes else "clean",
            path=inv.visible(path), lines=lines, bytes=size,
            thresholds={"lines": max_lines, "bytes": max_bytes},
        )

    plans = inv.home / ".claude" / "plans"
    plan_count = 0
    completed_candidates = 0
    if plans.is_dir():
        for path in sorted(plans.glob("*.md")):
            plan_count += 1
            text = read_text(path) or ""
            if DONE_RE.search(text) and not PENDING_RE.search(text):
                completed_candidates += 1
                inv.emit(
                    "state", "completed-plan-candidate", "review", path=inv.visible(path),
                    lines=len(text.splitlines()),
                    observed="completion markers present and no pending marker; content role still requires review",
                )
    inv.emit(
        "state", "plan-inventory", "clean" if completed_candidates == 0 else "review",
        plans=plan_count, completed_candidates=completed_candidates,
    )


def scan_runtime_metrics(inv: Inventory, codex_homes: list[Path]) -> None:
    roots: list[Path] = [
        inv.home / ".claude" / "backups", inv.home / ".claude" / "projects",
        inv.home / ".claude" / "file-history",
    ]
    for home in codex_homes:
        roots.extend((home / "sessions", home / "rollouts"))
    for path in sorted(set(roots), key=str):
        if not path.exists():
            continue
        count, size, oldest = tree_metrics(path)
        inv.emit(
            "runtime-state", "growth-telemetry", "clean", path=inv.visible(path),
            files=count, bytes=size, oldest_mtime=oldest,
        )


def git_output(path: Path, args: list[str]) -> tuple[int, str]:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def scan_user_git(inv: Inventory) -> None:
    for path in (inv.home / ".agents", inv.home / ".claude"):
        code, inside = git_output(path, ["rev-parse", "--is-inside-work-tree"])
        if code or inside != "true":
            continue
        _, branch = git_output(path, ["branch", "--show-current"])
        _, status = git_output(path, ["status", "--porcelain"])
        dirty = len([line for line in status.splitlines() if line])
        default = ""
        _, remote_head = git_output(path, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
        if remote_head.startswith("origin/"):
            default = remote_head.removeprefix("origin/")
        elif (path / ".git" / "refs" / "heads" / "main").exists():
            default = "main"
        elif (path / ".git" / "refs" / "heads" / "master").exists():
            default = "master"
        handoff = bool(dirty or (default and branch != default))
        inv.emit(
            "git", "user-setup-tree", "handoff" if handoff else "clean",
            path=inv.visible(path), branch=branch, default_branch=default or None,
            dirty_paths=dirty,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="User home to inspect")
    parser.add_argument("--format", choices=("json", "jsonl"), default="jsonl")
    parser.add_argument(
        "--doctor-scope", choices=("active", "default", "all"), default="all"
    )
    parser.add_argument("--doctor-timeout", type=int, default=120)
    parser.add_argument("--scheduler-timeout", type=int, default=10)
    parser.add_argument("--state-max-age-hours", type=int, default=36)
    parser.add_argument("--memory-max-lines", type=int, default=400)
    parser.add_argument("--memory-max-bytes", type=int, default=100_000)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    if home == Path("/") or not home.is_dir():
        parser.error("--home must resolve to an existing user home, not filesystem root")

    inv = Inventory(home)
    skill_docs = scan_skills(inv)
    docs = instruction_docs(inv, skill_docs)
    instruction_digest = sha256_paths(docs, home)
    scan_state_freshness(
        inv, instruction_digest, max_age_hours=args.state_max_age_hours
    )
    codex_homes = scan_codex_runtime(inv, args.doctor_timeout, args.doctor_scope)
    scan_scheduler_ownership(inv, args.scheduler_timeout)
    scan_markdown_links(inv, docs)
    scan_config_paths(inv)
    scan_codex_route_pin(inv)
    scan_mcp_and_plugins(inv)
    scan_shell(inv)
    scan_backup_candidates(inv)
    scan_memories_and_plans(inv, args.memory_max_lines, args.memory_max_bytes)
    scan_runtime_metrics(inv, codex_homes)
    scan_user_git(inv)
    if args.format == "json":
        inv.print_json()
    else:
        inv.print_jsonl()
    return 0


if __name__ == "__main__":
    sys.exit(main())
