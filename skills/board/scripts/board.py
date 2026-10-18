#!/usr/bin/env python3
"""Render an HTML board of one project, or of every Orca-registered project with --all.

For each repository it reads the primary checkout's MEMORY.md (active and
waiting workstreams, their `Decision:` and `Blocker:` lines, and when it was last written), the last
seven days of commits on the fetched remote default branch, and open pull requests with CI state. The page itself is plain
language: an agent writes a brief per workstream and per project (what shipped, which card to act on
first) from those facts, cached by content hash under
~/.local/state/board/briefs/. When briefs are missing the script writes `<out>.pending.json` and exits 3;
rerun with `--briefs FILE` to render. It fetches remote refs and writes nothing else outside the board directory.

Each actionable card embeds one launch action and shows its exact text. With --open the page is served
by launch.py on this machine, so a button starts the launch itself instead of copying a command.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

HOME = Path.home()
BOARD_DIR = HOME / ".local/state/board"
# Unexpected launcher errors (launch.py writes them); each board run reports them once.
ERRORS = BOARD_DIR / "errors.log"
GH = str(HOME / ".local/bin/gh")
# Every `###` entry is a workstream; its section is its class. A Deferred one is parked on purpose.
# The handoff format's sections that hold no work; an item anywhere else outside an entry never becomes a card.
NOTE_SECTIONS = {"current state", "retained context", "standing context", "durable pointers"}
DEFERRED = re.compile(r"\b(deferred|inactive|parked)\b", re.I)
# `/latest` lists entries that live evidence contradicts under Current State: `- Stale: <key> — <why>`.
STALE = re.compile(r"^[-*] (?:\*\*)?Stale(?:\*\*)?[:：]\s*(?:\*\*)?`?([^`—–]+?)`?\s*(?:[—–-]\s|$)")
# Field lines as handoff and older checkpoints write them: `- Label: v`, `- **Label (qualifier):** v`,
# `- **Label / other：** v`, and paragraph-style `**Label.** v`. The first label names the field.
_LABEL = r"([A-Z][A-Za-z /]*?)\s*(?:\([^)]*\))?\s*"
FIELD = re.compile(
    rf"^(?:[-*] )?\*\*{_LABEL}[:：.]\*\*\s*(.*)$"
    rf"|^(?:[-*] )?\*\*{_LABEL}\*\*\s*[:：]\s*(.*)$"
    rf"|^[-*] {_LABEL}[:：]\s*(.*)$"
)
CJK = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]")
NONE_VALUE = re.compile(r"^(none|無)\b", re.I)
# The owner's rank for a workstream, `- Priority: 1 (who, when, why)`: lower comes first, ties keep file order.
PRIORITY = re.compile(r"^(\d+)\b")
CI_FAIL = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
CI_PASS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
PR_LIMIT = 100
SHIPPED_LIMIT = 30
GIT = ["git", "--no-optional-locks"]
# The fields a manager reads, named as the page names them; a change to any other field does not mark a card.
TRACKED = {"objective": "目標", "state": "現況", "next": "下一步", "blocker": "卡點", "decision": "要你決定的事"}
DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
# Evidence a card cites: pull requests (`#10`) and backticked commit hashes in the notes' delivery fields.
EVIDENCE = re.compile(r"(?<![\w/-])#(\d{1,6})\b|`([0-9a-f]{7,12})`")
EVIDENCE_FIELDS = ("state", "blocker", "decision")
EVIDENCE_LIMIT = 4
# How far a week's outcome got: merged into the main line, or said by its commits to be released or deployed.
STAGES = {"已合併": "fresh", "已上線": "good"}
OUTCOME_LIMIT = 5
# Board buttons that keep a repository's own upkeep, keyed like a workstream so one runs at a time.
CHORES = {"notes-refresh": "更新筆記", "leftover-cleanup": "清理殘留"}
RECEIPT_WINDOW = 7 * 86400  # before the owner's first recorded visit, dispatches started this week
# The plain-language rules a decision brief was written under; a decision cached under older rules is written again.
DECISION_CONTRACT = "2026-09-30 plain-words options"
REPORT_LIMIT = 2000  # a receiver's receipt or an upkeep run's report, as the receipt brief reads it


@dataclass
class Workstream:
    key: str
    section: str
    fields: dict[str, str] = field(default_factory=dict)
    unread: int = 0  # lines of the entry that map to no field, shown so nothing drops silently

    @property
    def deferred(self) -> bool:
        return bool(DEFERRED.search(self.section))

    def get(self, name: str) -> str:
        return self.fields.get(name, "").strip()

    @property
    def decision(self) -> str:
        value = self.get("decision")
        return "" if not value or NONE_VALUE.match(value) else value

    @property
    def priority(self) -> int | None:
        match = PRIORITY.match(self.get("priority"))
        return int(match.group(1)) if match else None

    @property
    def blocker(self) -> str:
        value = self.get("blocker")
        return "" if not value or NONE_VALUE.match(value) else value


@dataclass
class Product:
    name: str
    path: str
    workstreams: list[Workstream] = field(default_factory=list)
    deliveries: list[tuple[str, ...]] = field(default_factory=list)
    prs: list[dict] = field(default_factory=list)
    last_commit: str = ""
    remote: bool = False
    default: str = ""
    memory_read: bool = False
    memory_at: float = 0.0  # when MEMORY.md was last written
    unrecorded: int = 0  # default-branch commits since then that MEMORY.md does not reflect
    behind: int = 0  # remote default-branch commits the local default branch lacks: merged but not live here
    commits: set[str] = field(default_factory=set)  # hashes the notes cite that name commits here
    stale: set[str] = field(default_factory=set)  # keys `/latest` found contradicted by live evidence
    loose: dict[str, int] = field(default_factory=dict)  # section -> items written outside any entry
    worktrees: list[str] = field(default_factory=list)  # linked worktree paths
    loose_branches: list[str] = field(default_factory=list)  # local branches besides the default no worktree holds
    dispatches: list[dict] = field(default_factory=list)  # this repository's board dispatches, from launches.json
    visit: dict = field(default_factory=dict)  # what the page showed at the owner's last visit
    receipts: list[dict] = field(default_factory=list)  # dispatches that finished since that visit
    errors: list[str] = field(default_factory=list)

    @property
    def decisions(self) -> list[Workstream]:
        """Open decisions: a chosen option's dispatch takes the card out of the owner's hands."""
        return [w for w in self.workstreams if w.decision and not w.deferred and not live_dispatch(self, w.key)]

    @property
    def blocked(self) -> list[Workstream]:
        return [w for w in self.workstreams if w.blocker and not w.decision and not w.deferred]


FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
ITEM = re.compile(r"(?:[-*+]|\d+[.)]) ")


def unfenced(text: str) -> list[str]:
    """The lines outside fenced code blocks; a fence closes only on its own character, at least as long."""
    lines, fence = [], ""
    for line in text.splitlines():
        match = FENCE.match(line)
        if fence:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and not line.strip(" `~"):
                fence = ""
        elif match:
            fence = match.group(1)
        else:
            lines.append(line)
    return lines


def loose_items(text: str) -> dict[str, int]:
    """Top-level items written outside any `###` entry in a section that may hold work, by section."""
    loose: dict[str, int] = {}
    section, inside = "檔案開頭", False
    for line in unfenced(text):
        if line.startswith("## "):
            section, inside = line[3:].strip(), False
        elif line.startswith("### "):
            inside = True
        elif not inside and ITEM.match(line) and section.casefold() not in NOTE_SECTIONS:
            loose[section] = loose.get(section, 0) + 1
    return loose


def parse_memory(text: str) -> list[Workstream]:
    """Return every `###` workstream entry, each with its section, fields, and the lines no field took."""
    items: list[Workstream] = []
    section = ""
    current: Workstream | None = None
    label = ""
    for line in unfenced(text):
        if line.startswith("## "):
            section = line[3:].strip()
            current, label = None, ""
            continue
        if line.startswith("### "):
            key = line[4:].strip().replace("`", "")
            current, label = Workstream(key=key, section=section), ""
            items.append(current)
            continue
        if current is None:
            continue
        match = FIELD.match(line)
        if match:
            name, value = [g for g in match.groups() if g is not None][:2]
            label = name.split("/")[0].strip().lower()
            label = {"blockers": "blocker", "decisions": "decision"}.get(label, label)
            current.fields[label] = value.strip()
        elif line.startswith(("- **", "* **")) or (not label and line.strip()):
            # A bold-labelled bullet no field pattern reads, and text before the first field, belong to no field.
            current.unread += 1
            label = ""
        elif label and line.strip():
            previous, nxt = current.fields[label], line.strip()
            # Markdown soft breaks between two CJK characters carry no space.
            gap = "" if previous and CJK.match(previous[-1]) and CJK.match(nxt[0]) else " "
            current.fields[label] = (previous + gap + nxt).strip()
    return items


def parse_stale(text: str) -> set[str]:
    """The keys `/latest` listed under Current State as contradicted by live evidence."""
    keys, current = set(), False
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower().startswith("current state")
        elif current and (match := STALE.match(line)):
            keys.add(match.group(1).strip())
    return keys


def ci_state(rollup: list[dict] | None) -> str:
    states = set()
    for check in rollup or []:
        conclusion = (check.get("conclusion") or "").upper()
        status = (check.get("status") or check.get("state") or "").upper()
        states.add(conclusion or status or "PENDING")
    if not states:
        return "none"
    if states & CI_FAIL:
        return "fail"
    # Anything not known to pass (queued, stale, unrecognized) is not yet a pass.
    return "pass" if states <= CI_PASS else "pending"


def run(args: list[str], cwd: str, timeout: int = 20) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"exit {done.returncode}")
    return done.stdout


def registered_repos() -> list[tuple[str, str]]:
    try:
        data = json.loads(run(["orca", "repo", "list", "--json"], cwd=str(HOME)))
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        sys.exit(f"board: cannot read Orca repos ({exc}); start Orca with `orca open` and retry")
    return [(r["displayName"], r["path"]) for r in data["result"]["repos"] if r.get("kind") == "git"]


def current_repo(cwd: Path) -> tuple[str, str]:
    """Resolve the primary checkout of the repository containing cwd, worktrees included."""
    try:
        first = run([*GIT, "worktree", "list", "--porcelain"], str(cwd)).split("\n\n")[0].splitlines()
        path = first[0].removeprefix("worktree ")
        if "bare" in first:  # a bare repository has no primary checkout; the current worktree is the project
            path = run([*GIT, "rev-parse", "--show-toplevel"], str(cwd)).strip()
    except (OSError, RuntimeError, IndexError) as exc:
        sys.exit(f"board: {cwd} is not inside a Git repository ({exc}); run it from a project or pass --all")
    return Path(path).name, path


def page_name(name: str, path: str) -> str:
    """A per-project file name that stays distinct across same-named or non-Latin projects."""
    return f"{slug(name)}-{hashlib.sha1(path.encode()).hexdigest()[:8]}.html"


def collect(name: str, path: str) -> Product:
    product = Product(name=name, path=path)
    try:
        memory = Path(path, "MEMORY.md")
        text = memory.read_text(encoding="utf-8")
        product.workstreams = parse_memory(text)
        product.stale = parse_stale(text)
        product.loose = loose_items(text)
        seen: set[str] = set()
        for w in list(product.workstreams):
            if w.key in seen:  # one key, one card: a duplicate would share the first card's dispatch identity
                product.workstreams.remove(w)
                product.errors.append(f"MEMORY.md 有兩條同名的工作「{w.key}」，只顯示第一條")
            seen.add(w.key)
        # The owner's ranked work leads every list and the focus pick; unranked work follows in file order.
        product.workstreams.sort(key=lambda w: (w.priority is None, w.priority or 0))
        product.memory_read = True
        product.memory_at = memory.stat().st_mtime
    except FileNotFoundError:
        product.errors.append("沒有 MEMORY.md")
    except (OSError, UnicodeDecodeError) as exc:
        product.errors.append(f"MEMORY.md 讀取失敗：{exc}")
    try:
        product.remote = bool(run([*GIT, "remote"], path).strip())
        # The fetched remote default branch is the shared line: it holds merges made anywhere and leaves out
        # unpushed local commits. A repository without a remote default has only the primary checkout's branch.
        product.default = run([*GIT, "branch", "--show-current"], path).strip()
        base = product.default or "HEAD"
        if product.remote:
            try:
                run([*GIT, "fetch", "--quiet", "--prune", "origin"], path, timeout=30)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                product.errors.append(f"抓不到遠端最新狀態，改看本機紀錄：{exc}")
        try:
            remote_head = run([*GIT, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], path).strip()
            product.default, base = remote_head.split("/", 1)[-1], remote_head
        except RuntimeError:
            # A clone of an empty repository or a remote added later has no origin/HEAD; fetch does not create it.
            if product.remote and product.default:
                try:
                    run([*GIT, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{product.default}"], path)
                    base = f"origin/{product.default}"
                except RuntimeError:
                    pass
        log = run([*GIT, "log", "--first-parent", "--since=7.days.ago", "--format=%h%x1f%s%x1f%cs%x1f%an", base], path)
        product.deliveries = [
            tuple(row.split("\x1f")[:3]) for row in log.splitlines() if row and by_person(row.rsplit("\x1f", 1)[-1])
        ]
        product.last_commit = run([*GIT, "log", "-1", "--format=%cI", base], path).strip()
        if product.memory_at:
            product.unrecorded = unrecorded(path, base, product.memory_at)
        product.behind = behind(path, product.default, base)
        product.commits = known_commits(path, {r for w in product.workstreams for r in cited(w) if not r.startswith("#")})
        blocks = [b.splitlines() for b in run([*GIT, "worktree", "list", "--porcelain"], path).split("\n\n") if b.strip()]
        product.worktrees = [b[0].removeprefix("worktree ") for b in blocks[1:]]
        held = {line.removeprefix("branch refs/heads/") for b in blocks for line in b if line.startswith("branch ")}
        heads = run([*GIT, "for-each-ref", "--format=%(refname:short)", "refs/heads"], path).split()
        product.loose_branches = sorted(set(heads) - held - {product.default})
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        product.errors.append(f"Git 讀取失敗：{exc}")
    if not product.remote:
        return product
    try:
        fields = "number,title,url,isDraft,headRefName,statusCheckRollup,updatedAt"
        product.prs = json.loads(run([GH, "pr", "list", "--state", "open", "--limit", str(PR_LIMIT), "--json", fields], path))
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        product.errors.append(f"PR 讀取失敗：{exc}")
    return product


def known_commits(path: str, refs: set[str]) -> set[str]:
    """The hashes among `refs` that name commits here; a transcript or session id looks the same."""
    if not refs:
        return set()
    ordered = sorted(refs)
    done = subprocess.run(
        [*GIT, "cat-file", "--batch-check=%(objecttype)"], input="".join(f"{r}^{{commit}}\n" for r in ordered),
        cwd=path, capture_output=True, text=True, timeout=20,
    )
    return {r for r, line in zip(ordered, done.stdout.splitlines()) if line == "commit"}


def by_person(author: str) -> bool:
    """A commit a person made; a bot's (an image bump, generated docs) changes nothing the owner reads or runs."""
    return bool(author) and not author.endswith("[bot]")


def behind(path: str, default: str, base: str) -> int:
    """People's commits on the remote default branch that the local one lacks. Skills and local tools run from the
    primary checkout, so a merge is live on this machine only once local main contains it."""
    if not default or not base.startswith("origin/"):
        return 0
    return sum(map(by_person, run([*GIT, "log", "--format=%an", f"refs/heads/{default}..{base}"], path).splitlines()))


def remote_default(path: str) -> str:
    """The fetched remote default branch, such as `origin/main`, or empty when the remote names none."""
    try:
        return run([*GIT, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], path).strip()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return ""


def unrecorded(path: str, base: str, since: float) -> int:
    """Default-branch commits after MEMORY.md was written, less those that write MEMORY.md themselves."""
    log = [*GIT, "log", "--first-parent", f"--since=@{int(since)}", "--format=%H%x1f%an", base]
    later = {row.split("\x1f")[0] for row in run(log, path).splitlines() if row and by_person(row.split("\x1f")[-1])}
    return len(later - {row.split("\x1f")[0] for row in run([*log, "--", "MEMORY.md"], path).splitlines()})


# What moves each workstream now, in the order the status table lists them.
MOTION = {
    "owner": ("輪到你", "ask"),
    "stuck": ("卡住", "bad"),
    "idle": ("可以派工，沒人在做", "warn"),
    "working": ("agent 在做", "good"),
    "outside": ("等外部或實際使用", ""),
    "deferred": ("暫緩", ""),
}
# Who takes the next step. The agent judges it from the source; the page offers a launch unless it is external.
ACTORS = ("you", "engineering", "external")


def status_of(w: Workstream) -> str:
    if w.deferred:
        return "deferred"
    if w.decision:
        return "decide"
    if w.blocker:
        return "stuck"
    return "waiting" if "waiting" in w.section.lower() else "active"


# --- what moves each workstream ------------------------------------------------------------------


def load_dispatches(products: list[Product]) -> None:
    """Attach each project's board dispatches from the launcher's record, and where each live one stands.

    A dispatch is live while it is starting or its worktree exists; the receiver removes the worktree last.
    An upkeep run has no worktree: it is live while its headless agent runs in the primary checkout.
    """
    try:
        ledger = json.loads((BOARD_DIR / "launches.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        ledger = {}
    for p in products:
        p.dispatches = [
            {**e, "id": rid, "live": starting(e) or upkeep_running(e) or (bool(e.get("path")) and Path(e["path"]).is_dir())}
            for rid, e in (ledger.items() if isinstance(ledger, dict) else [])
            if isinstance(e, dict) and e.get("kind") == "dispatch" and e.get("repo") == p.path
        ]
        for d in p.dispatches:
            if not d["live"] or d.get("state") == "running":
                continue
            if d.get("state") == "failed" and not d.get("terminal"):
                d.update(progress="派工沒有成功，留下的 worktree 要你在 Orca 清掉。", attention=True)
                continue
            from launch import read_progress  # reads Orca and GitHub; loaded only when a dispatch is live

            d.update(read_progress(d))


def upkeep_result(entry: dict) -> dict | None:
    """What a headless upkeep run printed when it ended; its JSON result is written only then."""
    try:
        result = json.loads(Path(entry["log"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) and result.get("type") == "result" else None


def upkeep_running(entry: dict) -> bool:
    """An upkeep run still at work in the primary checkout: its agent process lives and has not reported."""
    if not entry.get("log") or not isinstance(entry.get("agent_pid"), int):
        return False
    try:
        os.kill(entry["agent_pid"], 0)
    except OSError:
        return False
    return upkeep_result(entry) is None


def starting(entry: dict) -> bool:
    """A launch still running in a live launcher; a dead launcher's record started nothing it can prove."""
    if entry.get("state") != "running" or not isinstance(entry.get("pid"), int):
        return False
    try:
        os.kill(entry["pid"], 0)
    except OSError:
        return False
    return True


def live_dispatch(p: Product, key: str) -> dict | None:
    return next((d for d in reversed(p.dispatches) if d.get("key") == key and d["live"]), None)


def motion(p: Product, w: Workstream, brief: dict) -> str:
    """Who or what moves the workstream now: a live dispatch first, then the owner, the outside world, a blocker."""
    if w.deferred:
        return "deferred"
    if d := live_dispatch(p, w.key):
        return "owner" if d.get("attention") or awaits_owner(p, w, brief, d) else "working"
    if w.decision or brief["actor"] == "you":
        return "owner"
    if brief["actor"] == "external":  # a blocker that only waits on outside evidence is waiting, not stuck
        return "outside"
    return "stuck" if w.blocker else "idle"


def awaits_owner(p: Product, w: Workstream, brief: dict, d: dict) -> bool:
    """A live dispatch whose own entry changed since launch and now hands the next step to the owner."""
    return bool(d.get("entry")) and d["entry"] != stream_id(p, w) and brief["actor"] == "you"


def tracked(w: Workstream) -> dict:
    return {name: w.get(name) for name in TRACKED if w.get(name)}


def changes(p: Product, w: Workstream) -> list[str] | None:
    """The fields changed since the owner's last visit, or None for a card new since then."""
    if not p.visit:
        return []
    seen = p.visit.get("streams", {}).get(w.key)
    if seen is None:
        return None
    now, before = tracked(w), seen.get("fields", {})
    return [label for name, label in TRACKED.items() if now.get(name, "") != before.get(name, "")]


def moved_on(p: Product, w: Workstream, today: date) -> date | None:
    """The last day the workstream visibly moved: its notes changed or it was dispatched."""
    marks = [datetime.fromtimestamp(d["started"]).date() for d in p.dispatches if d.get("key") == w.key and d.get("started")]
    seen = p.visit.get("streams", {}).get(w.key)
    if seen:
        if seen.get("fields") != tracked(w) and p.memory_at:
            marks.append(datetime.fromtimestamp(p.memory_at).date())
        if seen.get("moved"):
            marks.append(date.fromisoformat(seen["moved"]))
        return max(marks, default=None)
    # Before the board has seen it, the notes' own past dates are the best estimate; afterwards a date that
    # merely arrives (a deadline) is not movement.
    for match in DATE.finditer(" ".join(w.fields.values())):
        try:
            day = date(*map(int, match.groups()))
        except ValueError:
            continue
        if day <= today:  # a later date is a deadline, not movement
            marks.append(day)
    return max(marks, default=None)


def visit_path(p: Product) -> Path:
    return BOARD_DIR / "visits" / f"{hashlib.sha1(p.path.encode()).hexdigest()[:12]}.json"


def load_visit(p: Product) -> dict:
    try:
        stored = json.loads(visit_path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return stored if isinstance(stored, dict) and isinstance(stored.get("streams"), dict) else {}


def record_visit(p: Product, now: datetime) -> None:
    """Remember what the owner was shown, so the next page marks what changed since."""
    if not p.memory_read:  # an unread MEMORY.md would record every card as gone
        return
    streams = {}
    for w in p.workstreams:
        moved = moved_on(p, w, now.date())
        streams[w.key] = {"fields": tracked(w), "moved": moved.isoformat() if moved else None}
    visit = {"at": now.timestamp(), "streams": streams, "inflight": [d["id"] for d in p.dispatches if d["live"]]}
    path = visit_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(visit, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def finished_since(p: Product, now: datetime) -> list[dict]:
    """Dispatches whose worktree is gone that the owner has not seen finish: live at the last visit or started after it."""
    since = p.visit.get("at", now.timestamp() - RECEIPT_WINDOW)
    inflight = set(p.visit.get("inflight", []))
    return [
        d for d in p.dispatches
        if d.get("state") == "done" and (d.get("path") or d.get("log")) and not d["live"] and (d["id"] in inflight or d.get("started", 0) > since)
    ]


def read_receipts(p: Product, now: datetime) -> None:
    """What each finished dispatch left: the pull request its branch opened and the notes it wrote."""
    finished = finished_since(p, now)
    if not finished:
        return
    prs: list[dict] = []
    if p.remote:
        try:
            fields = "number,title,body,state,headRefName,mergeCommit"
            prs = json.loads(run([GH, "pr", "list", "--state", "all", "--limit", "200", "--json", fields], p.path))
        except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            p.errors.append(f"派工結果的 PR 讀取失敗：{exc}")
    streams = {w.key: w for w in p.workstreams}
    titles = {b["_key"]: b.get("title") for b in load_briefs(p).values() if isinstance(b, dict) and b.get("_key")}
    for d in finished:
        # Orca names a worktree's branch `<prefix>/<worktree>`.
        pr = next((x for x in prs if x.get("headRefName", "").rsplit("/", 1)[-1] == d.get("worktree")), None)
        key = d.get("key", "")
        w = streams.get(key)
        facts = {
            "stream": key,
            "chore": CHORES.get(key, ""),
            "pr": {"title": pr["title"], "state": pr["state"], "body": (pr.get("body") or "")[:1200]} if pr else None,
            "notes": tracked(w) if w else "entry removed",
            "notes_written": p.memory_at > d.get("started", float("inf")),
            "live": live_here(p, pr),
        }
        # The agent's own report: an upkeep run's final message, or the receipt a receiver wrote before removing its
        # worktree, which closed the terminal that showed it.
        if d.get("log"):
            report = (upkeep_result(d) or {}).get("result") or "no report: the run ended without one"
        else:
            receipt = receipt_path(d["id"])
            report = receipt.read_text(encoding="utf-8") if receipt.is_file() else "no report: the receiver wrote none"
        facts["report"] = str(report)[:REPORT_LIMIT]
        # The card title is a hint from the brief cache, which forgets a closed card; it stays out of the id.
        rid = digest([p.path, d["id"], facts])
        p.receipts.append({"id": rid, "kind": "receipt", "project": p.name, **facts, "card_title": titles.get(key, "")})


def receipt_path(record: str) -> Path:
    """Where a dispatch's receiver writes its completion receipt for the board, by its launch record id."""
    return BOARD_DIR / "receipts" / f"{record}.md"


def live_here(p: Product, pr: dict | None) -> bool:
    """Whether a merged pull request has reached the local default branch, the dispatch contract's last sync step."""
    if not pr or pr.get("state") != "MERGED" or not p.default:
        return True
    oid = (pr.get("mergeCommit") or {}).get("oid")
    if not oid:
        return False
    try:
        run([*GIT, "merge-base", "--is-ancestor", oid, f"refs/heads/{p.default}"], p.path)
        return True
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return False


def leftovers(p: Product) -> list[str]:
    """Linked worktrees no live board dispatch holds, then branches no worktree has checked out."""
    held = {d.get("path") for d in p.dispatches if d["live"]}
    return [path for path in p.worktrees if path not in held] + p.loose_branches


def digest(value: object) -> str:
    return hashlib.sha1(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def stream_id(p: Product, w: Workstream) -> str:
    return digest([p.path, w.key, w.section, w.fields])


def shipped(p: Product) -> list[dict]:
    return [{"commit": sha, "day": day, "subject": subject} for sha, subject, day in p.deliveries[:SHIPPED_LIMIT]]


def cited(w: Workstream) -> list[str]:
    """The pull requests and hex tokens a card's notes cite for what was delivered, first seen first."""
    found: list[str] = []
    for name in EVIDENCE_FIELDS:
        for pr, sha in EVIDENCE.findall(w.get(name)):
            ref = f"#{pr}" if pr else sha
            if ref not in found:
                found.append(ref)
    return found


def evidence(p: Product, w: Workstream) -> list[str]:
    """What a card cites that the repository can show: its pull requests and the hashes that are commits here."""
    return [ref for ref in cited(w) if ref.startswith("#") or ref in p.commits]


def product_id(p: Product) -> str:
    return digest([p.path, [stream_id(p, w) for w in p.workstreams], shipped(p)])


def brief_requests(p: Product) -> list[dict]:
    """What the plain-language layer must cover for one project: each workstream, then the project."""
    items = [
        {
            "id": stream_id(p, w),
            "kind": "workstream",
            "project": p.name,
            "status": status_of(w),
            "key": w.key,
            "source": w.fields,
        }
        for w in p.workstreams
    ]
    items.append(
        {
            "id": product_id(p),
            "kind": "product",
            "project": p.name,
            "path": p.path,
            "workstreams": [
                {"key": w.key, "status": status_of(w), "priority": w.priority, "objective": w.get("objective"),
                 "next": w.get("next")}
                for w in p.workstreams
            ],
            "shipped": shipped(p),
        }
    )
    return items + p.receipts


def with_previous(p: Product, items: list[dict]) -> list[dict]:
    """Attach each workstream's last brief, matched by key, so a rewrite keeps what the source did not change."""
    last = {b["_key"]: b for b in load_briefs(p).values() if isinstance(b, dict) and b.get("_key")}
    for item in items:
        if item["kind"] == "workstream" and item["key"] in last:
            item["previous"] = {k: v for k, v in last[item["key"]].items() if not k.startswith("_")}
    return items


def brief_errors(request: dict, brief: object) -> list[str]:
    """Shape errors for one brief against the request it answers."""
    if not isinstance(brief, dict):
        return ["brief is not an object"]
    if request["kind"] == "product":
        errors = [] if _text(brief.get("summary")) else ["missing summary"]
        if request["shipped"]:
            errors += outcome_errors(brief.get("shipped"), {c["commit"] for c in request["shipped"]})
        keys = [w["key"] for w in request["workstreams"] if w["status"] != "deferred"]
        focus = brief.get("focus")
        if keys and not (isinstance(focus, dict) and focus.get("key") in keys and _text(focus.get("why"))):
            errors.append("focus needs a workstream key from this project and a why")
        ranked = [w for w in request["workstreams"] if w["status"] != "deferred" and w.get("priority") is not None]
        if ranked:
            first = min(ranked, key=lambda w: w["priority"])["key"]
            if isinstance(focus, dict) and focus.get("key") in keys and focus.get("key") != first:
                errors.append(f"focus must be {first}, the owner's first priority")
        return errors
    if request["kind"] == "receipt":
        return [f"missing {name}" for name in ("title", "did") if not _text(brief.get(name))]
    errors = [f"missing {name}" for name in ("title", "who", "before", "now", "why", "next") if not _text(brief.get(name))]
    if "until" in brief and not _day(brief["until"]):
        errors.append("until must be a YYYY-MM-DD date")
    if brief.get("actor") not in ACTORS:
        errors.append(f"actor must be one of {', '.join(ACTORS)}")
    elif request["status"] == "decide" and brief["actor"] != "you":
        errors.append("a decision's actor is you")
    if request["status"] == "stuck" and not _text(brief.get("stuck")):
        errors.append("missing stuck")
    if request["status"] == "decide":
        decision = brief.get("decision")
        options = decision.get("options") if isinstance(decision, dict) else None
        if not isinstance(decision, dict) or not _text(decision.get("question")):
            errors.append("missing decision.question")
        if not isinstance(options, list) or len(options) < 2:
            errors.append("decision.options needs at least two options")
        else:
            for i, option in enumerate(options):
                if not (isinstance(option, dict) and _text(option.get("label")) and _text(option.get("consequence"))):
                    errors.append(f"decision.options[{i}] needs label and consequence")
                elif not isinstance(option.get("reversible"), bool):
                    errors.append(f"decision.options[{i}].reversible must be true or false")
            recommended = decision.get("recommended") if isinstance(decision, dict) else None
            if recommended is not None and not (isinstance(recommended, int) and 0 <= recommended < len(options)):
                errors.append("decision.recommended must index an option or be null")
    return errors


def outcome_errors(outcomes: object, commits: set[str]) -> list[str]:
    """A week's outcomes: one to five, each naming its stage and citing this week's commits."""
    if not isinstance(outcomes, list) or not 1 <= len(outcomes) <= OUTCOME_LIMIT:
        return [f"shipped needs 1 to {OUTCOME_LIMIT} outcomes"]
    errors = []
    for i, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            errors.append(f"shipped[{i}] is not an object")
            continue
        errors += [f"shipped[{i}] missing {name}" for name in ("title", "before", "after") if not _text(outcome.get(name))]
        if outcome.get("stage") not in STAGES:
            errors.append(f"shipped[{i}].stage must be one of {', '.join(STAGES)}")
        cited = outcome.get("commits")
        if not (isinstance(cited, list) and cited and all(c in commits for c in cited)):
            errors.append(f"shipped[{i}].commits must list this week's commits it covers")
    return errors


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def expired(brief: object, today: date) -> bool:
    """An external brief waiting on a date is re-briefed once that date has passed."""
    until = _day(brief.get("until")) if isinstance(brief, dict) else None
    return until is not None and until < today


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def brief_path(p: Product) -> Path:
    # Keyed by path alone: the single-project page and the Orca overview may name a project differently.
    return BOARD_DIR / "briefs" / f"{hashlib.sha1(p.path.encode()).hexdigest()[:12]}.json"


def load_briefs(p: Product) -> dict:
    try:
        stored = json.loads(brief_path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return stored if isinstance(stored, dict) else {}


def apply_briefs(products: list[Product], supplied: dict) -> tuple[dict, list[str]]:
    """Merge supplied briefs into each project's store and return the valid briefs its current items use."""
    merged: dict = {}
    errors: list[str] = []
    for p in products:
        stored = load_briefs(p)
        requests = {r["id"]: r for r in brief_requests(p)}
        for rid, request in requests.items():
            if rid in supplied:
                problems = brief_errors(request, supplied[rid])
                if problems:
                    errors.append(f"{rid} ({p.name} {request.get('key') or request['kind']}): {'; '.join(problems)}")
                else:
                    stored[rid] = {**supplied[rid], "_key": request["key"], "_contract": DECISION_CONTRACT} if "key" in request else supplied[rid]
        today = date.today()
        current = {
            rid: stored[rid] for rid in requests
            if rid in stored and not brief_errors(requests[rid], stored[rid]) and not expired(stored[rid], today)
            and not (requests[rid].get("status") == "decide" and stored[rid].get("_contract") != DECISION_CONTRACT)
        }
        if supplied and not errors:
            # An unread MEMORY.md looks like zero workstreams; keep its briefs until it reads again.
            save_briefs(p, current if p.memory_read else stored)
        merged.update(current)
    return merged, errors


def save_briefs(p: Product, briefs: dict) -> None:
    path = brief_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(briefs, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def pill(label: str, tone: str = "") -> str:
    return f'<span class="pill {tone}" data-report-meta-token>{html.escape(label)}</span>'


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "product"


def product_link(p: Product) -> str:
    return f'<a class="product-link" href="#{slug(p.name)}">{html.escape(p.name)}</a>'


def where(p: Product, overview: bool) -> str:
    """The product a card belongs to, as a quiet trailing note on its heading in the overview."""
    return f'<span class="where"> · {product_link(p)}</span>' if overview else ""


def failing_prs(p: Product) -> list[dict]:
    return [pr for pr in p.prs if ci_state(pr.get("statusCheckRollup")) == "fail"]


def motion_of(p: Product, w: Workstream, briefs: dict) -> str:
    return motion(p, w, briefs[stream_id(p, w)])


def owner_steps(p: Product, briefs: dict) -> list[Workstream]:
    """Workstreams waiting on the owner without a decision card: their step, or a dispatch that needs them."""
    return [w for w in p.workstreams if w not in p.decisions and motion_of(p, w, briefs) == "owner"]


def stuck_streams(p: Product, briefs: dict) -> list[Workstream]:
    """Blocked workstreams nobody is moving and the owner cannot unblock; the owner's own appear under 輪到你."""
    return [w for w in p.blocked if motion_of(p, w, briefs) == "stuck"]


def counts(products: list[Product], briefs: dict) -> tuple[int, int, int]:
    """Items for the owner, of which decisions, and stuck items (failing checks included)."""
    decisions = sum(len(p.decisions) for p in products)
    turns = decisions + sum(len(owner_steps(p, briefs)) for p in products)
    stuck = sum(len(stuck_streams(p, briefs)) + len(failing_prs(p)) for p in products)
    return turns, decisions, stuck


def motion_count(products: list[Product], briefs: dict, kind: str) -> int:
    return sum(motion_of(p, w, briefs) == kind for p in products for w in p.workstreams)


def focus_stream(p: Product, briefs: dict) -> Workstream | None:
    focus = briefs[product_id(p)].get("focus")
    key = focus.get("key") if isinstance(focus, dict) else None
    return next((w for w in p.workstreams if w.key == key), None)


def focus_line(p: Product, briefs: dict, overview: bool) -> str:
    """The brief's pick of the one card to act on first, linked to that card."""
    w = focus_stream(p, briefs)
    if w is None:
        return ""
    sid = stream_id(p, w)
    # Once the card is dispatched, the pick says where its agent stands instead of repeating the call to act.
    state = pill(*MOTION[motion_of(p, w, briefs)]) if live_dispatch(p, w.key) else ""
    return (
        f'<p class="focus">{"" if overview else '<span class="lead">建議先做</span>'}<a href="#w-{sid}">{html.escape(briefs[sid]["title"])}</a>'
        f'{state}{where(p, overview)}：{html.escape(briefs[product_id(p)]["focus"]["why"])}</p>'
    )


def focus_list(products: list[Product], briefs: dict, overview: bool) -> str:
    lines = "".join(focus_line(p, briefs, overview) for p in products)
    return f'<p class="lead">各產品建議先做</p>{lines}' if overview and lines else lines


def freshness(p: Product, overview: bool) -> str:
    """When the workstream notes were last written, and whether Git has moved on since."""
    if not p.memory_at:
        return ""
    at = f'<span data-report-meta-token>{datetime.fromtimestamp(p.memory_at).strftime("%m-%d %H:%M")}</span>'
    whose = f"{html.escape(p.name)} 的" if overview else ""
    if p.unrecorded:
        line = f'<p class="fresh stale">{whose}筆記寫於 {at}，之後又有 {p.unrecorded} 次更新沒寫進去，下面的卡片可能落後。</p>'
    else:
        line = f'<p class="fresh">{whose}筆記寫於 {at}，之後沒有新的更新。</p>'
    if p.behind:
        line += f'<p class="fresh stale">你電腦上的版本還少了 {p.behind} 個已合併的更新，這些改動在這台電腦還沒生效；按「更新筆記」會同步。</p>'
    return line


def launch(
    actions: dict, p: Product, text: str, title: str, key: str = "", label: str = "派工", name: str = "", group: str = "",
    ask: bool = False, entry: str = "",
) -> str:
    """Register one dispatch action and render its button, with the text the agent receives one click away.

    Every launch dispatches a worktree agent that takes the step through merge, its checkpoint, and removing
    its worktree; an owner card's agent (`ask`) first asks the owner in Orca for what only they can do.
    `title` names the worktree in Orca so the owner can tell what they dispatched. Actions sharing a `group`
    (the options of one decision) launch at most one of them.
    """
    action = {
        "kind": "dispatch", "project": p.name, "path": p.path, "key": key, "text": text, "title": title, "group": group,
        "ask": ask, "entry": entry,
    }
    aid = digest(action)
    actions[aid] = action
    aria = f' aria-label="{html.escape(name, quote=True)}"' if name else ""
    return (
        f'<div class="launch" data-action="{aid}"><div class="launch-row">'
        f'<button type="button"{aria}>{html.escape(label)}</button>'
        f'<details><summary>{CHEVRON}交代內容</summary><p class="launch-text" lang="en">{html.escape(text)}</p></details>'
        '</div><p class="launch-state" aria-live="polite"></p></div>'
    )


def stream_launch(actions: dict, p: Product, w: Workstream, brief: dict) -> str:
    if brief["actor"] == "external" or w.deferred:
        return ""
    # Next says what to do; the blocker only says what is wrong.
    step = (w.get("next") or w.blocker).strip()
    if not step:
        return ""
    return launch(actions, p, step, brief["title"], w.key, ask=brief["actor"] == "you", entry=stream_id(p, w))


def render_turns(products: list[Product], briefs: dict, overview: bool, actions: dict) -> str:
    cards, steps = [], []
    for p in products:
        for w in p.decisions:
            brief = briefs[stream_id(p, w)]
            decision = brief["decision"]
            options = "".join(
                f'<li><p class="option"><strong>{html.escape(o["label"])}</strong>'
                + (pill("推薦", "ask") if decision.get("recommended") == i else "")
                + (pill("之後可以改", "good") if o["reversible"] else pill("做了很難回頭", "bad"))
                + f'</p><p>{html.escape(o["consequence"])}</p>'
                + launch(
                    actions,
                    p,
                    f"The owner chose 「{o['label']}」 for 「{decision['question']}」. Record the decision in this "
                    "workstream, then carry out what follows from it.",
                    f"{brief['title']}：{o['label']}",
                    w.key,
                    "選這個",
                    f"選「{o['label']}」",
                    stream_id(p, w),
                    entry=stream_id(p, w),
                )
                + "</li>"
                for i, o in enumerate(decision["options"])
            )
            cards.append(
                f'<article class="decision"><h3 class="question">{html.escape(decision["question"])}{where(p, overview)}</h3>'
                f'<p class="why">{html.escape(brief["why"])}</p><ol class="options">{options}</ol>'
                '</article>'
            )
        focus = focus_stream(p, briefs)
        for w in owner_steps(p, briefs):
            brief = briefs[stream_id(p, w)]
            steps.append((w is not focus, len(steps),
                f'<li><h3>{pill("建議先做", "ask") if w is focus else ""}{html.escape(brief["title"])}{where(p, overview)}</h3>'
                f'<p>{html.escape(brief.get("stuck") or brief["now"])}</p>'
                + (f'<p class="needs"><span class="lead">派出的 agent 在等你</span>到 Orca 的「{html.escape(brief["title"])}」'
                   f'回覆它：{html.escape(brief["next"])}</p>'
                   if (d := live_dispatch(p, w.key)) and awaits_owner(p, w, brief, d) else
                   f'<p class="needs"><span class="lead">派出的 agent</span>{html.escape(d["progress"])}</p>'
                   if d and d.get("progress") else
                   f'<p><span class="lead">下一步</span>{html.escape(brief["next"])}</p>')
                + f"{stream_launch(actions, p, w, brief)}</li>"
            ))
    # Each project's 建議先做 card leads the owner's queue.
    steps = [row for *_, row in sorted(steps)]
    if not cards and not steps:
        return '<p class="empty">現在沒有要你決定或動手的事。</p>'
    return (f'<div class="decisions">{"".join(cards)}</div>' if cards else "") + (
        f'<ul class="rows">{"".join(steps)}</ul>' if steps else ""
    )


def render_stuck(products: list[Product], briefs: dict, overview: bool, actions: dict) -> str:
    rows = []
    for p in products:
        for w in stuck_streams(p, briefs):
            brief = briefs[stream_id(p, w)]
            rows.append(
                f'<li><h3>{html.escape(brief["title"])}{where(p, overview)}</h3><p>{html.escape(brief["stuck"])}</p>'
                f'<p><span class="lead">下一步</span>{html.escape(brief["next"])}</p>'
                f"{stream_launch(actions, p, w, brief)}</li>"
            )
        for pr in failing_prs(p):
            text = f"Make PR #{pr['number']} 「{pr['title']}」 ({pr['url']}) pass its checks."
            rows.append(
                f"<li><h3>一個準備上線的更新沒通過自動檢查{where(p, overview)}</h3>"
                "<p>工程要先修好這個更新，它才能上線。</p>" + launch(actions, p, text, f"修好 PR #{pr['number']} 的檢查") + "</li>"
            )
    if not rows:
        return '<p class="empty">沒有卡住的事。</p>'
    return f'<ul class="rows">{"".join(rows)}</ul>'


def activity(p: Product) -> str:
    return f"有 {len(p.deliveries)} 次更新" if p.deliveries else "沒有更新"


def render_index(products: list[Product], briefs: dict) -> str:
    rows = "".join(
        f'<tr><th scope="row">{product_link(p)}</th>'
        f'<td data-label="現況" class="summary">{html.escape(briefs[product_id(p)]["summary"])}</td>'
        f'<td data-label="這 7 天" class="num{"" if p.deliveries else " quiet"}">{activity(p)}</td>'
        f'<td data-label="最近更新" class="num" data-report-meta-token>{html.escape(p.last_commit[:10] or "—")}</td>'
        f'<td data-label="輪到你／卡住" class="num">{"／".join(str(n) for n in counts([p], briefs)[::2])}</td></tr>'
        for p in products
    )
    return (
        '<section aria-labelledby="h-moving"><h2 id="h-moving">各產品現況</h2>'
        '<div class="table-wrap"><table><thead><tr><th scope="col">產品</th><th scope="col">現況</th>'
        '<th scope="col">這 7 天</th><th scope="col">最近更新</th><th scope="col">輪到你／卡住</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def render_stream(p: Product, w: Workstream, briefs: dict, actions: dict) -> str:
    sid = stream_id(p, w)
    brief = briefs[sid]
    kind = motion(p, w, brief)
    label, tone = ("等你決定", "ask") if w in p.decisions else MOTION[kind]
    stuck = f'<p>{html.escape(brief["stuck"])}</p>' if brief.get("stuck") else ""
    # A card already listed under 輪到你 or 卡住 keeps its one button there.
    surfaced = w in p.decisions or kind in ("owner", "stuck")
    return (
        f'<li class="stream" id="w-{sid}"><h5>{pill(label, tone)}{html.escape(brief["title"])}{change_pill(p, w)}'
        f'{pill("筆記可能過時", "warn") if w.key in p.stale else ""}</h5>{notes_gaps(w)}'
        f'<p class="who">影響對象 · {html.escape(brief["who"])}</p>'
        f'<p><span class="lead">為什麼重要</span>{html.escape(brief["why"])}</p>'
        f'{shift(brief["before"], brief["now"])}{stuck}'
        f'<p><span class="lead">下一步</span>{html.escape(brief["next"])}</p>'
        f"{cite(evidence(p, w))}{'' if surfaced else stream_launch(actions, p, w, brief)}</li>"
    )


CHEVRON = (
    '<svg class="chevron" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)
def notes_gaps(w: Workstream) -> str:
    """What the board could not read from the entry, so a gap in the notes shows instead of vanishing."""
    gaps = []
    if not w.get("next"):
        gaps.append("筆記沒寫下一步" + ("或恢復條件" if w.deferred else ""))
    if w.unread:
        gaps.append(f"筆記有 {w.unread} 行讀不到")
    return f'<p class="fresh stale">{"；".join(gaps)}，按「更新筆記」整理。</p>' if gaps else ""


ARROW = (
    '<svg class="arrow" viewBox="0 0 20 20" aria-hidden="true" focusable="false">'
    '<path d="M4 10h11M11 5.5 15.5 10 11 14.5" fill="none" stroke="currentColor" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def shift(before: str, after: str) -> str:
    """What was true before and what is true now, side by side."""
    return (
        f'<div class="shift"><div><p class="shift-label">原本</p><p class="was">{html.escape(before)}</p></div>{ARROW}'
        f'<div><p class="shift-label">現在</p><p>{html.escape(after)}</p></div></div>'
    )


def cite(refs: list[str]) -> str:
    if not refs:
        return ""
    shown = "、".join(f"<code>{html.escape(r)}</code>" for r in refs[:EVIDENCE_LIMIT])
    more = f' <span class="nowrap">等 {len(refs)} 筆</span>' if len(refs) > EVIDENCE_LIMIT else ""
    return f'<p class="evidence"><span class="lead">證據</span>{shown}{more}</p>'


def render_shipped(p: Product, outcomes: list[dict]) -> str:
    """The week's changes as outcomes: stage, what it was, what it is now, and the commits behind it."""
    if not p.deliveries:
        return ""
    rows = "".join(
        f'<li><h5>{pill(o["stage"], STAGES[o["stage"]])}{html.escape(o["title"])}</h5>'
        f'{shift(o["before"], o["after"])}{cite(o["commits"])}</li>'
        for o in outcomes
    )
    return f'<ul class="outcomes">{rows}</ul>'


def render_product(p: Product, briefs: dict, actions: dict, today: date) -> str:
    summary = briefs[product_id(p)]
    streams = "".join(render_stream(p, w, briefs, actions) for w in p.workstreams) or (
        '<li class="stream"><p class="muted">這個產品目前沒有記錄中的工作。</p></li>'
    )
    errors = f'<p class="read-errors">有些資料沒讀到：{html.escape("；".join(p.errors))}</p>' if p.errors else ""
    return (
        f'<section class="product" id="{slug(p.name)}"><header><h3>{html.escape(p.name)}</h3>'
        f'<p class="summary">{html.escape(summary["summary"])}</p>'
        f'{errors}</header>'
        f'<section class="week" aria-label="{html.escape(p.name)} 這 7 天"><h4 class="part">這 7 天'
        f'<span class="count">{activity(p)}</span></h4>{render_shipped(p, summary.get("shipped", []))}</section>'
        f'<section aria-label="{html.escape(p.name)} 正在做的事"><h4 class="part">工作</h4>'
        f'{render_motion(p, briefs, today)}<ul class="streams">{streams}</ul></section></section>'
    )


def change_pill(p: Product, w: Workstream) -> str:
    changed = changes(p, w)
    if changed is None:
        return pill("你上次看之後新增", "fresh")
    return pill(f"你上次看之後改了{'、'.join(changed)}", "fresh") if changed else ""


def days_since(day: date | None, today: date) -> str:
    if day is None:
        return "—"
    days = (today - day).days
    return "今天" if days <= 0 else f"{days} 天"


def render_motion(p: Product, briefs: dict, today: date) -> str:
    """One row per workstream: what moves it now and how long since it last moved."""
    if not p.workstreams:
        return ""
    order = list(MOTION)
    rows = []
    for i, w in enumerate(p.workstreams):
        sid = stream_id(p, w)
        kind = motion_of(p, w, briefs)
        label, tone = ("等你決定", "ask") if w in p.decisions else MOTION[kind]
        day = moved_on(p, w, today)
        late = day is not None and kind in ("idle", "stuck", "owner") and (today - day).days >= 7
        changed = changes(p, w)
        note = "新增" if changed is None else "改了" + "、".join(changed) if changed else ""
        rows.append((order.index(kind), i,
            f'<tr><td data-label="狀態">{pill(label, tone)}</td>'
            f'<th scope="row"><a href="#w-{sid}">{html.escape(briefs[sid]["title"])}</a></th>'
            f'<td data-label="多久沒動" class="num{" late" if late else ""}">{days_since(day, today)}</td>'
            f'<td data-label="你上次看之後" class="{"changed" if note else "quiet"}">{html.escape(note or ("沒變" if p.visit else "—"))}</td></tr>'))
    body = "".join(row for *_, row in sorted(rows))
    return (
        '<div class="table-wrap motion"><table><thead><tr><th scope="col">狀態</th><th scope="col">工作</th>'
        '<th scope="col">多久沒動</th><th scope="col">你上次看之後</th></tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def upkeep(p: Product, actions: dict) -> str:
    """Buttons for the repository's own upkeep: stale notes, and worktrees or branches nobody works in."""
    parts = []
    # Notes drift in ways Git cannot show (tickets, environments), so the refresh is always one click away.
    if p.memory_read or p.unrecorded or p.behind:
        gaps = [f"local main lacks {p.behind} merged commits"] if p.behind else []
        # The write time keys the button: once a refresh writes the notes, the button is offered again.
        written = f"MEMORY.md, written {datetime.fromtimestamp(p.memory_at):%Y-%m-%d %H:%M}" if p.memory_at else "MEMORY.md"
        gaps.append(f"{written}, misses {p.unrecorded} default-branch commits" if p.unrecorded else f"{written}, may miss "
                    "ticket and environment changes Git cannot show")
        if unread := [w.key for w in p.workstreams if w.unread or not w.get("next")]:
            gaps.append(f"entries with unread lines or no Next: {', '.join(unread)}")
        if p.loose:
            gaps.append(f"items outside any entry under {', '.join(p.loose)}: make each with an owner and a next action "
                        "its own keyed entry, and move standing rules to ## Standing Context")
        if p.loose:
            names = "、".join(f"「{name}」{count} 條" for name, count in p.loose.items())
            parts.append(f'<p class="fresh stale">筆記裡有些事寫在工作條目以外（{html.escape(names)}），不會變成卡片；按「更新筆記」整理。</p>')
        parts.append(launch(
            actions, p,
            f"Follow {Path(__file__).resolve().parents[1] / 'references/refresh.md'} in {p.path} "
            "as 更新筆記 upkeep: synchronize when needed and reconcile selected MEMORY.md entries against live evidence"
            + (f"; {'; '.join(gaps)}." if gaps else "."),
            f"{p.name} {CHORES['notes-refresh']}", "notes-refresh", CHORES["notes-refresh"],
        ))
    if found := leftovers(p):
        parts.append(
            f'<p class="fresh stale">有 {len(found)} 個工作區或分支沒有看板派出的 agent 在用。</p>'
            + launch(
                actions, p,
                f"Run `$git-converge-main` in {p.path}: audit {', '.join(found)}, which no board dispatch is "
                "working in, and clean up only what is merged or empty.",
                f"{p.name} {CHORES['leftover-cleanup']}", "leftover-cleanup", CHORES["leftover-cleanup"],
            )
        )
    return "".join(parts)


def render_upkeep(products: list[Product], actions: dict, overview: bool) -> str:
    """Each product's notes freshness with its upkeep buttons, at the top: the page is only as current as the notes."""
    return "".join(
        f'<div class="upkeep">{block}</div>' for p in products if (block := freshness(p, overview) + upkeep(p, actions))
    )


def visited_at(products: list[Product]) -> float:
    return max((p.visit.get("at", 0) for p in products), default=0)


def render_since(products: list[Product], briefs: dict, overview: bool) -> tuple[str, int]:
    """What changed since the owner last looked: finished dispatches with what their agents did, then changed cards."""
    rows = []
    for p in products:
        for r in p.receipts:
            brief = briefs[r["id"]]
            lead = pill("派工結束", "good") if r.get("live", True) else pill("已合併，還沒生效", "warn")
            flag = "" if r["notes_written"] else pill("沒寫筆記", "warn")
            rows.append(
                f'<li><h3>{lead}{flag}{html.escape(brief["title"])}{where(p, overview)}</h3>'
                f'<p>{html.escape(brief["did"])}</p></li>'
            )
        for w in p.workstreams:
            changed = changes(p, w)
            if changed == []:
                continue
            sid = stream_id(p, w)
            note = "新增的工作" if changed is None else f"改了{'、'.join(changed)}"
            rows.append(
                f'<li class="changed-row"><p><a href="#w-{sid}">{html.escape(briefs[sid]["title"])}</a>'
                f'{where(p, overview)}<span class="changed">{note}</span></p></li>'
            )
    at = visited_at(products)
    if at:
        when = f'<span data-report-meta-token>{datetime.fromtimestamp(at).strftime("%m-%d %H:%M")}</span>'
        lead = f'<p class="since-lead">上次看是 {when}。</p>' if rows else f'<p class="empty">上次看是 {when}，之後沒有卡片改動，也沒有派工結束。</p>'
    else:
        lead = '<p class="since-lead">從這次開始記下你看過的內容，下次打開會標出之後改了什麼。</p>'
    return lead + (f'<ul class="rows">{"".join(rows)}</ul>' if rows else ""), len(rows)


def actions_json(actions: dict) -> str:
    """The page's launch actions as inline JSON the launcher reads back; `<` is escaped so it cannot close the script."""
    return json.dumps(actions, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")


def render(products: list[Product], briefs: dict, now: datetime, overview: bool = True) -> str:
    # Most recently active first, then stable-sorted so products waiting on the owner lead.
    products = sorted(products, key=lambda p: p.last_commit, reverse=True)
    products = sorted(products, key=lambda p: tuple(-n for n in counts([p], briefs)[::2]))
    turns, _, stuck = counts(products, briefs)
    working, idle = (motion_count(products, briefs, kind) for kind in ("working", "idle"))
    moving = f"{working} 條有 agent 在做，{idle} 條可以派工但沒人在做"
    if overview:
        title = "產品總覽看板"
        quiet = sum(not p.deliveries for p in products)
        thesis = f"{turns} 件事輪到你，{stuck} 件卡住；{moving}；{len(products)} 個產品裡有 {quiet} 個這 7 天沒有更新。"
    else:
        title = f"{products[0].name} 看板"
        thesis = f"{turns} 件事輪到你，{stuck} 件卡住；{moving}；這 7 天{activity(products[0])}。"
    actions: dict = {}
    notes = render_upkeep(products, actions, overview)
    since, since_count = render_since(products, briefs, overview)
    return TEMPLATE.format(
        title=html.escape(title),
        thesis=html.escape(thesis),
        focus=focus_list(products, briefs, overview),
        stamp=now.strftime("%Y-%m-%d %H:%M"),
        upkeep=notes,
        turns=render_turns(products, briefs, overview, actions),
        turn_count=turns,
        stuck=render_stuck(products, briefs, overview, actions),
        stuck_count=stuck,
        index=render_index(products, briefs) if overview else "",
        products_heading="各產品在做什麼" if overview else "正在做的事",
        since=since,
        since_count=since_count,
        products="".join(render_product(p, briefs, actions, now.date()) for p in products),
        actions=actions_json(actions),
    )


TEMPLATE = """<!doctype html>
<html lang="zh-Hant" data-launch-token="">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>{title}</title>
<link rel="icon" href="data:,">
<style>
:root {{
  --ink: #172221; --muted: #596866; --line: #d9e2df; --paper: #ffffff; --canvas: #f4f7f6;
  --accent: #0f766e; --accent-deep: #0b5c56; --accent-soft: #e4f3f0;
  --ask: #8a4b00; --ask-soft: #fff3df; --ask-line: #eccb94; --ask-ink: #6b4a1f;
  --bad: #a3312a; --bad-soft: #fdecea; --warn: #7a5a00; --warn-soft: #fbf3d6; --good: #1d6b3f; --good-soft: #e5f4ea;
}}
* {{ box-sizing: border-box; }}
html {{ color: var(--ink); background: var(--canvas); line-height: 1.6;
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", sans-serif; }}
html:lang(zh-Hant) .report-copy {{ line-break: strict; word-break: normal; }}
body {{ margin: 0; background: var(--canvas); }}
::selection {{ background: var(--accent-soft); color: var(--ink); }}
a {{ color: var(--accent); text-underline-offset: .18em; }}
a:focus-visible {{ border-radius: 4px; outline: 3px solid rgba(15,118,110,.32); outline-offset: 3px; }}
[data-report-meta-token] {{ white-space: nowrap; overflow-wrap: normal; }}
h1, h2, h3, h4, h5, p {{ margin: 0; }}
.page {{ width: min(1120px, calc(100% - 40px)); margin: 0 auto; padding-block: 36px 72px; }}
.report-header {{ display: grid; gap: 10px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }}
h1 {{ font-size: 2rem; font-weight: 760; line-height: 1.2; letter-spacing: -0.01em; }}
.report-thesis {{ font-size: 1.2rem; font-weight: 600; line-height: 1.4; text-wrap: balance; }}
.stamp {{ color: var(--muted); font-size: .88rem; }}
main {{ display: grid; gap: 44px; padding-top: 32px; }}
main > section {{ min-width: 0; }}
h2 {{ font-size: 1.4rem; line-height: 1.3; margin-bottom: 14px; display: flex; gap: 10px; align-items: baseline; }}
h2 .count {{ font-variant-numeric: tabular-nums; color: var(--muted); font-weight: 600; font-size: 1rem; }}
.empty, .muted {{ color: var(--muted); }}
.where {{ font-size: .88rem; font-weight: 500; color: var(--muted); }}
.where .product-link {{ font-weight: 600; color: var(--muted); }}
.decisions {{ align-items: start; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 14px; }}
.decision {{ display: grid; gap: 8px; align-content: start; padding: 18px 20px; border: 1px solid var(--ask-line);
  border-radius: 12px; background: var(--ask-soft); min-width: 0; }}
.decision .question {{ font-size: 1.2rem; font-weight: 700; line-height: 1.45; }}
.decision .why {{ color: var(--ask-ink); font-size: .9rem; }}
.decision .options {{ margin: 4px 0 0; padding-left: 1.3em; display: grid; gap: 10px; }}
.decision .options li {{ min-width: 0; }}
.decisions + .rows {{ margin-top: 14px; }}
.decision .option {{ display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }}
.rows {{ list-style: none; margin: 0; padding: 0; display: grid; border: 1px solid var(--line); border-radius: 12px; background: var(--paper); }}
.rows > li {{ display: grid; gap: 6px; padding: 14px 16px; min-width: 0; }}
.rows > li + li {{ border-top: 1px solid var(--line); }}
.rows h3 {{ font-size: 1.15rem; font-weight: 700; line-height: 1.45; }}
.rows h3 .pill {{ margin-right: 10px; vertical-align: .12em; }}
.product-link {{ color: var(--ink); font-weight: 700; text-decoration: underline; text-decoration-color: var(--line); text-underline-offset: .18em; }}
.product-link:hover {{ color: var(--accent); text-decoration: underline; }}
.table-wrap {{ max-width: 100%; overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--paper); }}
table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
th, td {{ padding: 9px 14px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); white-space: nowrap; }}
thead th {{ background: var(--accent-soft); font-size: .82rem; }}
tbody tr:last-child th, tbody tr:last-child td {{ border-bottom: 0; }}
.num {{ font-variant-numeric: tabular-nums; }}
.quiet {{ color: var(--muted); }}
.products {{ display: grid; gap: 18px; }}
.product {{ display: grid; gap: 12px; padding: 18px 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--paper); min-width: 0; }}
.product header {{ display: grid; gap: 4px; }}
.product .summary {{ font-size: 1rem; }}
.product h3 {{ font-size: 1.35rem; }}
.pill {{ font-variant-numeric: tabular-nums; display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: .78rem; font-weight: 600; white-space: nowrap;
  color: var(--muted); background: var(--canvas); border: 1px solid var(--line); }}
.pill.good {{ color: var(--good); background: var(--good-soft); border-color: transparent; }}
.pill.warn {{ color: var(--warn); background: var(--warn-soft); border-color: transparent; }}
.pill.bad {{ color: var(--bad); background: var(--bad-soft); border-color: transparent; }}
.pill.fresh {{ color: var(--accent-deep); background: var(--accent-soft); border-color: transparent; }}
.pill.ask {{ color: var(--ask); background: var(--ask-soft); border-color: var(--ask-line); }}
.streams {{ list-style: none; margin: 0; padding: 0; display: grid; }}
.stream {{ display: grid; gap: 6px; padding: 22px 0; min-width: 0; }}
.motion + .streams {{ margin-top: 10px; }}
.stream h5 {{ margin: 0; font-size: 1.1rem; font-weight: 700; line-height: 1.45; }}
.stream h5 .pill {{ margin-right: 10px; vertical-align: .12em; }}
.stream h5 .pill:not(:first-child) {{ margin-left: 8px; }}
.lead {{ font-weight: 600; color: var(--muted); margin-right: 8px; }}
td.summary {{ white-space: normal; min-width: 16rem; }}
.stream + .stream {{ border-top: 1px solid var(--line); }}
.read-errors {{ color: var(--bad); font-size: .9rem; }}
.focus {{ font-size: 1rem; }}
.focus a {{ font-weight: 650; }}
.focuses {{ display: grid; gap: 4px; }}
.focuses:empty {{ display: none; }}
.fresh {{ color: var(--muted); font-size: .88rem; }}
.upkeep {{ display: grid; gap: 2px; }}
.since-lead {{ color: var(--muted); font-size: .92rem; margin-bottom: 10px; }}
.rows h3 .pill + .pill {{ margin-left: -4px; }}
.changed-row p {{ display: flex; flex-wrap: wrap; gap: 2px 12px; align-items: baseline; }}
.changed-row a {{ font-weight: 650; }}
.changed {{ color: var(--accent-deep); font-size: .9rem; }}
.needs {{ color: var(--warn); }}
.motion {{ margin-top: 4px; }}
.motion th[scope="row"] {{ white-space: normal; font-weight: 600; min-width: 14rem; }}
.motion th[scope="row"] a {{ color: var(--ink); text-decoration-color: var(--line); }}
.motion th[scope="row"] a:hover {{ color: var(--accent); }}
.motion td.late {{ color: var(--warn); font-weight: 650; }}
.fresh.stale {{ color: var(--warn); }}
.launch {{ display: grid; gap: 6px; margin-top: 6px; min-width: 0; }}
.launch-row {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 14px; align-items: start; }}
.launch details {{ min-width: 0; }}
.launch summary {{ display: inline-flex; align-items: center; gap: 4px; min-height: 36px; width: fit-content;
  color: var(--muted); font-size: .88rem; cursor: pointer; list-style: none; }}
.launch .chevron {{ width: 14px; height: 14px; transition: transform .15s ease-out; }}
.launch details[open] .chevron {{ transform: rotate(90deg); }}
.launch summary::-webkit-details-marker {{ display: none; }}
.launch summary:hover {{ color: var(--accent); }}
.launch summary:focus-visible {{ border-radius: 4px; outline: 3px solid rgba(15,118,110,.32); outline-offset: 3px; }}
.launch-text {{ margin-top: 2px; color: var(--muted); font-size: .88rem; line-height: 1.65; overflow-wrap: anywhere; }}
.launch-state:empty {{ display: none; }}
.launch button {{ min-height: 36px; padding: 5px 16px; border: 1px solid var(--accent); border-radius: 8px; background: var(--accent);
  color: #fff; font: inherit; font-size: .9rem; font-weight: 650; cursor: pointer; transition: background-color .15s ease-out; }}
.launch button:hover {{ background: var(--accent-deep); border-color: var(--accent-deep); }}
.launch button:focus-visible {{ outline: 3px solid rgba(15,118,110,.32); outline-offset: 2px; }}
.launch button:disabled {{ background: var(--paper); border-color: var(--line); color: var(--muted); cursor: default; }}
.launch-state {{ font-size: .88rem; color: var(--muted); }}
.decision > .launch {{ margin-top: 4px; }}
.who {{ color: var(--muted); font-size: .9rem; }}
.shift {{ display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 4px 14px; align-items: start;
  margin: 4px 0; padding: 12px 14px; border-radius: 10px; background: var(--canvas); }}
.shift-label {{ color: var(--muted); font-size: .8rem; font-weight: 650; }}
.shift .was {{ color: var(--muted); }}
.shift .arrow {{ width: 18px; height: 18px; margin-top: 26px; color: var(--accent); }}
.evidence {{ color: var(--muted); font-size: .86rem; }}
.evidence .nowrap {{ white-space: nowrap; }}
.evidence code {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: .92em; color: var(--ink); }}
.part {{ margin: 20px 0 0; font-size: 1.15rem; font-weight: 700; display: flex; gap: 10px; align-items: baseline; }}
.part .count {{ color: var(--muted); font-size: .88rem; font-weight: 500; font-variant-numeric: tabular-nums; }}
.week {{ display: grid; gap: 6px; }}
.outcomes {{ list-style: none; margin: 0; padding: 0; display: grid; }}
.outcomes > li {{ display: grid; gap: 4px; padding: 12px 0; min-width: 0; }}
.outcomes > li + li {{ border-top: 1px solid var(--line); }}
.outcomes h5 {{ margin: 0; font-size: 1rem; font-weight: 700; line-height: 1.45; }}
.outcomes h5 .pill {{ margin-right: 10px; vertical-align: .12em; }}
.launch[data-state="running"] .launch-state {{ color: var(--warn); }}
.launch[data-state="done"] .launch-state {{ color: var(--good); font-weight: 600; }}
.launch[data-attention] .launch-state {{ color: var(--warn); }}
.launch[data-state="failed"] .launch-state, .launch[data-state="offline"] .launch-state {{ color: var(--bad); }}
@media (max-width: 640px) {{
  .page {{ width: calc(100% - 32px); padding-top: 20px; }}
  .report-thesis {{ text-wrap: pretty; }}
  .decision, .product {{ padding: 16px; }}
  .table-wrap thead {{ display: none; }}
  .table-wrap tr {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px 12px; padding: 10px 14px; border-bottom: 1px solid var(--line); }}
  .table-wrap tbody tr:last-child {{ border-bottom: 0; }}
  .table-wrap th, .table-wrap td {{ padding: 0; border: 0; white-space: normal; }}
  .table-wrap th, .table-wrap td.summary {{ grid-column: 1 / -1; }}
  .motion th[scope="row"] {{ min-width: 0; order: -1; }}
  .motion td[data-label="狀態"]::before {{ content: none; }}
  .table-wrap td.summary {{ min-width: 0; }}
  .table-wrap td::before {{ content: attr(data-label) "："; color: var(--muted); font-size: .82rem; }}
  .shift {{ grid-template-columns: minmax(0, 1fr); }}
  .shift .arrow {{ margin: 0; transform: rotate(90deg); }}
}}
@media (prefers-reduced-motion: reduce) {{ .launch button, .launch .chevron {{ transition: none; }} }}
@media print {{
  .launch {{ display: none; }}
  .table-wrap {{ overflow: visible; }}
  th, td {{ white-space: normal; }}
}}
</style>
</head>
<body>
<div class="page">
<header class="report-header">
<h1 data-report-identity>{title}</h1>
<p class="report-thesis" data-report-thesis>{thesis}</p>
<div class="focuses">{focus}</div>
<p class="stamp">看板更新於 <span data-report-meta-token>{stamp}</span></p>
<p class="fresh stale" id="launcher-status" role="status" hidden></p>
{upkeep}
</header>
<main class="report-copy">
<section aria-labelledby="h-since"><h2 id="h-since">你上次看之後 <span class="count">{since_count}</span></h2>{since}</section>
<section aria-labelledby="h-turns"><h2 id="h-turns">輪到你 <span class="count">{turn_count}</span></h2>{turns}</section>
{index}
<section aria-labelledby="h-stuck"><h2 id="h-stuck">卡住 <span class="count">{stuck_count}</span></h2>{stuck}</section>
<section aria-labelledby="h-products"><h2 id="h-products">{products_heading}</h2><div class="products">{products}</div></section>
</main>
</div>
<script type="application/json" id="launch-actions">{actions}</script>
<script>
// Buttons talk to launch.py, which serves this page with a per-run token. Opened as a plain file, the page has no token.
const token = document.documentElement.dataset.launchToken;
const blocks = [...document.querySelectorAll(".launch")];
const status = document.getElementById("launcher-status");
let polling = null;
// A launch starting is checked every 3 seconds; a dispatched agent's progress every 30.
const FAST = 3000, SLOW = 30000;

function show(block, entry) {{
  const button = block.querySelector("button");
  const state = block.querySelector(".launch-state");
  button.dataset.label ||= button.textContent;
  block.dataset.state = entry.state;
  block.toggleAttribute("data-attention", Boolean(entry.attention));
  button.disabled = ["running", "done", "taken"].includes(entry.state) || (entry.state === "failed" && !entry.retry);
  button.textContent = {{
    running: "派工中…",
    done: entry.finished ? "已完成" : "已派出",
    taken: "已選其他選項",
    failed: entry.retry ? "再試一次" : "沒有派工",
  }}[entry.state] || button.dataset.label;
  state.textContent = {{
    running: "正在開 worktree 並啟動 agent，通常要一到三分鐘。",
    done: entry.log ? `${{entry.at}} 在主目錄背景執行。${{entry.progress || ""}}`
      : `${{entry.at}} 派給 worktree「${{entry.worktree}}」的 agent。${{entry.progress || "它會一路做到合併。"}}`,
    taken: "這一題已經選了另一個選項；要改主意，到 Orca 裡那個 worktree 的 agent 說。",
    failed: `沒有派工成功：${{entry.note}}`,
    offline: entry.note,
  }}[entry.state] || "";
}}

async function api(path, body) {{
  let response;
  try {{
    response = await fetch(path, {{
      method: body ? "POST" : "GET",
      headers: {{ "X-Launch-Token": token, "Content-Type": "application/json" }},
      body: body ? JSON.stringify(body) : undefined,
    }});
  }} catch (error) {{
    throw new Error("這一頁已經停止更新，可能已經開了新的看板頁。在這個專案的對話重新執行 /board。");
  }}
  if (response.status === 403) throw new Error("這一頁的通行碼已經失效。在這個專案的對話重新執行 /board。");
  const data = await response.json();
  if (response.status >= 500) throw new Error(data.note);
  return data;
}}

async function refresh() {{
  let entries;
  try {{ entries = await api("state"); }} catch (error) {{
    // Say so instead of freezing the cards, and keep watching: a closed launcher costs a request every 30 seconds.
    status.textContent = error.message;
    status.hidden = false;
    clearTimeout(polling);
    polling = setTimeout(refresh, SLOW);
    return;
  }}
  status.hidden = true;
  for (const block of blocks) if (entries[block.dataset.action]) show(block, entries[block.dataset.action]);
  const all = Object.values(entries);
  const delay = all.some((e) => e.state === "running") ? FAST : all.some((e) => e.progress && !e.finished) ? SLOW : 0;
  clearTimeout(polling);
  polling = delay ? setTimeout(refresh, delay) : null;
}}

document.addEventListener("click", async (event) => {{
  const button = event.target.closest(".launch button");
  if (!button) return;
  const block = button.closest(".launch");
  if (!token) {{
    show(block, {{ state: "offline", note: "這一頁要從 /board 打開，按鈕才能開工。在這個專案的對話執行 /board。" }});
    return;
  }}
  show(block, {{ state: "running" }});
  try {{
    show(block, await api("launch", {{ id: block.dataset.action }}));
  }} catch (error) {{
    show(block, {{ state: "offline", note: error.message }});
    return;
  }}
  refresh();
}});

if (token) refresh();
</script>
</body>
</html>
"""


CONTRACT = Path(__file__).resolve().parent.parent / "references/plain-language.md"


def take_errors() -> list[str]:
    """The launcher errors recorded since the last board run; reading them clears them."""
    # Moving the file first keeps an error written meanwhile for the next run, and one of two runs reads it.
    taken = ERRORS.with_suffix(f".{os.getpid()}")
    try:
        os.replace(ERRORS, taken)
    except FileNotFoundError:
        return []
    lines = taken.read_text(encoding="utf-8").splitlines()
    taken.unlink()
    return [line for line in lines if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="every Orca-registered project instead of the current one")
    parser.add_argument("--out", type=Path, help="output path (default ~/.local/state/board/<project>.html or index.html)")
    parser.add_argument("--briefs", type=Path, help="JSON object of plain-language briefs keyed by request id")
    parser.add_argument("--open", action="store_true", help="serve the page on this machine so its buttons launch, and show it in Orca's browser")
    args = parser.parse_args(argv)

    repos = registered_repos() if args.all else [current_repo(Path.cwd())]
    with ThreadPoolExecutor(max_workers=8) as pool:
        products = list(pool.map(lambda r: collect(*r), repos))
    now = datetime.now()
    load_dispatches(products)
    for p in products:
        p.visit = load_visit(p)
        read_receipts(p, now)
    out = args.out or BOARD_DIR / ("index.html" if args.all else page_name(*repos[0]))
    out.parent.mkdir(parents=True, exist_ok=True)
    pending_path = out.with_suffix(".pending.json")

    supplied = json.loads(args.briefs.read_text(encoding="utf-8")) if args.briefs else {}
    if not isinstance(supplied, dict):
        sys.exit(f"{args.briefs}: expected a JSON object keyed by request id")
    briefs, errors = apply_briefs(products, supplied)
    if errors:
        sys.exit("invalid briefs:\n" + "\n".join(errors))
    missing = [r for p in products for r in with_previous(p, [r for r in brief_requests(p) if r["id"] not in briefs])]
    if missing:
        pending_path.write_text(
            json.dumps({"contract": str(CONTRACT), "items": missing}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{pending_path}\n{len(missing)} briefs to write; follow {CONTRACT}, then rerun with --briefs FILE")
        return 3
    pending_path.unlink(missing_ok=True)

    out.write_text(render(products, briefs, now, overview=args.all), encoding="utf-8")
    turns, decisions, stuck = counts(products, briefs)
    print(f"{out}\n{len(products)} products, {turns} for the owner ({decisions} decisions), {stuck} stuck")
    for p in products:
        w = focus_stream(p, briefs)
        if w:
            print(f"focus {p.name}: {briefs[stream_id(p, w)]['title']}：{briefs[product_id(p)]['focus']['why']}")
        if p.unrecorded:
            print(f"stale {p.name}: {p.unrecorded} commits since MEMORY.md was written")
        if p.loose:
            print(f"loose {p.name}: " + ", ".join(f"{name} ({count})" for name, count in p.loose.items()))
        if p.behind:
            print(f"behind {p.name}: local main lacks {p.behind} merged commits, so they are not live here")
        changed = sum(changes(p, w) != [] for w in p.workstreams)
        if changed or p.receipts:
            pending = sum(not r.get("live", True) for r in p.receipts)
            print(f"since {p.name}: {changed} cards changed, {len(p.receipts) - pending} dispatches finished"
                  + (f", {pending} merged but not live here" if pending else ""))
    for line in take_errors():
        print(f"error: {line}")
    if args.open:
        from launch import LaunchError, show, start  # the script's own directory; loaded only when serving

        url = start(out)
        print(url)
        try:
            show(url, "active" if args.all else f"path:{repos[0][1]}")
            for p in products:  # the owner sees this page now; the next one marks what changes after it
                record_visit(p, now)
        except LaunchError as exc:
            print(f"not shown in Orca: {exc.note} Start Orca with `orca open`, then rerun.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
