#!/usr/bin/env python3
"""Normalize Claude Code and Codex session transcripts into one local SQLite warehouse.

`ingest` parses changed transcript files incrementally; `report` ingests, then prints the
failure and friction signals as compact Markdown; `sql` runs a read-only query for drill-down.
Rows outlive their source files, so the warehouse keeps history after runtimes prune transcripts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
DEFAULT_DB = HOME / ".local/state/session-insights/sessions.db"
CLAUDE_ROOT = HOME / ".claude/projects"
def default_codex_roots(home: Path = HOME) -> list[Path]:
    # Orca launches Codex under per-account homes; most Codex work lives there, not in ~/.codex.
    orca = home / "Library/Application Support/orca/codex-accounts"
    return [home / ".codex/sessions", *sorted(orca.glob("*/home/sessions"))]
SCHEMA_VERSION = 4
SNIPPET = 400
PROMPT_CHARS = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, agent TEXT, size INTEGER, mtime REAL, session_id TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, agent TEXT, origin TEXT, parent_id TEXT, path TEXT, cwd TEXT,
  model TEXT, started_at TEXT, ended_at TEXT, prompts INTEGER, tool_calls INTEGER,
  tool_errors INTEGER, input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER,
  compactions INTEGER, interrupts INTEGER, api_calls INTEGER, cache_write_tokens INTEGER,
  first_context INTEGER, peak_context INTEGER);
CREATE TABLE IF NOT EXISTS prompts (
  session_id TEXT, agent TEXT, ts TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS tool_calls (
  session_id TEXT, agent TEXT, ts TEXT, tool TEXT, detail TEXT, is_error INTEGER,
  error TEXT, duration_ms INTEGER, output_chars INTEGER, images INTEGER);
CREATE TABLE IF NOT EXISTS events (
  session_id TEXT, agent TEXT, ts TEXT, kind TEXT, detail TEXT, size INTEGER);
CREATE INDEX IF NOT EXISTS tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS prompts_session ON prompts(session_id);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id);
"""


MIGRATIONS = {
    2: [
        "ALTER TABLE sessions ADD COLUMN api_calls INTEGER",
        "ALTER TABLE sessions ADD COLUMN cache_write_tokens INTEGER",
        "ALTER TABLE sessions ADD COLUMN first_context INTEGER",
        "ALTER TABLE sessions ADD COLUMN peak_context INTEGER",
        "ALTER TABLE tool_calls ADD COLUMN output_chars INTEGER",
        "ALTER TABLE tool_calls ADD COLUMN images INTEGER",
        "ALTER TABLE events ADD COLUMN size INTEGER",
    ],
    3: [],  # endgame events come from assistant text; the re-parse below fills them
    4: [],  # Codex compactions were counted twice; the re-parse below recounts them
}


def clip(value: object, limit: int = SNIPPET) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class Session:
    session_id: str
    agent: str
    path: str
    origin: str = "interactive"
    parent_id: str | None = None
    cwd: str | None = None
    model: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    api_calls: int = 0
    first_context: int | None = None
    peak_context: int = 0
    prompts: list[tuple[str | None, str]] = field(default_factory=list)
    tools: list[tuple[str | None, str, str, int, str | None, int | None, int, int]] = field(default_factory=list)
    events: list[tuple[str | None, str, str, int | None]] = field(default_factory=list)

    def api_call(self, context: int) -> None:
        """Record one model request whose prompt (cached or not) was `context` tokens."""
        self.api_calls += 1
        if self.first_context is None:
            self.first_context = context
        self.peak_context = max(self.peak_context, context)

    def seen(self, ts: str | None) -> None:
        if not ts:
            return
        if not self.started_at or ts < self.started_at:
            self.started_at = ts
        if not self.ended_at or ts > self.ended_at:
            self.ended_at = ts


def read_records(path: Path, keep: tuple[str, ...] | None = None):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if keep and not any(marker in line for marker in keep):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


# ---------------------------------------------------------------- Claude Code

CLAUDE_NOISE_PREFIXES = (
    "<local-command", "<system-reminder", "<task-notification", "Caveat:", "<bash-",
    "Base directory for this skill", "This session is being continued",
)
COMMAND_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)


# Mirrors skills/endgame/scripts/stop_gate.py: plain-text contract and close lines count; fenced or
# quoted examples do not.
ENDGAME_OPEN_RE = re.compile(r"^[#*\s]*ENDGAME CONTRACT\b", re.M)
ENDGAME_CLOSE_RE = re.compile(r"^[#*\s]*ENDGAME:\s*(DONE|BLOCKED|DROPPED)\b", re.M)
QUOTED_RE = re.compile(r"^\s*(```|~~~).*?^\s*\1[^\n]*$|^\s*>.*$", re.M | re.S)


def endgame_events(ts: str | None, text: str) -> list[tuple]:
    if "ENDGAME" not in text:
        return []
    text = QUOTED_RE.sub("", text)
    marks = ["contract"] * bool(ENDGAME_OPEN_RE.search(text)) + ENDGAME_CLOSE_RE.findall(text)
    return [(ts, "endgame", mark, None) for mark in marks]


def claude_tool_detail(data: dict) -> str:
    for key in ("command", "file_path", "path", "pattern", "url", "query", "skill", "description", "prompt"):
        if isinstance(data.get(key), str):
            return clip(data[key])
    return clip(data)


def tool_result_text(content: object) -> str:
    if isinstance(content, list):
        return " ".join(b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def parse_claude(path: Path) -> Session:
    is_subagent = path.parent.name == "subagents"
    session = Session(session_id=path.stem, agent="claude", path=str(path))
    if is_subagent:
        session.origin = "subagent"
        session.parent_id = path.parent.parent.name
    pending: dict[str, tuple[str | None, str, str]] = {}
    usage_seen: set[str | None] = set()
    for record in read_records(path):
        kind = record.get("type")
        ts = record.get("timestamp")
        session.seen(ts)
        session.cwd = session.cwd or record.get("cwd")
        if record.get("entrypoint", "").startswith("sdk") and not is_subagent:
            session.origin = "exec"
        if kind == "system":
            subtype = record.get("subtype")
            if subtype == "compact_boundary":
                session.events.append((ts, "compaction", clip(record.get("compactMetadata", {}).get("trigger", "")), record.get("compactMetadata", {}).get("preTokens")))
            elif subtype == "api_error" or record.get("level") == "error":
                session.events.append((ts, "api_error", clip(record.get("content") or record.get("error") or ""), None))
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if kind == "assistant":
            session.model = message.get("model") or session.model
            usage = message.get("usage") or {}
            if message.get("id") not in usage_seen and usage:
                usage_seen.add(message.get("id"))
                write = usage.get("cache_creation_input_tokens") or 0
                read = usage.get("cache_read_input_tokens") or 0
                context = (usage.get("input_tokens") or 0) + write + read
                session.api_call(context)
                session.input_tokens += context
                session.cached_tokens += read
                session.cache_write_tokens += write
                session.output_tokens += usage.get("output_tokens") or 0
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "text":
                    session.events.extend(endgame_events(ts, block.get("text", "")))
                elif block.get("type") == "tool_use":
                    data = block.get("input") or {}
                    pending[block.get("id")] = (ts, block.get("name", "?"), claude_tool_detail(data))
            continue
        if kind != "user":
            continue
        if isinstance(content, list):
            texts = []
            for block in content:
                if block.get("type") == "tool_result":
                    call = pending.pop(block.get("tool_use_id"), None)
                    if call:
                        result = block.get("content")
                        output = tool_result_text(result)
                        images = sum(1 for b in result if isinstance(b, dict) and b.get("type") == "image") if isinstance(result, list) else 0
                        error = clip(output) if block.get("is_error") else None
                        session.tools.append((call[0], call[1], call[2], int(bool(block.get("is_error"))), error, None, len(output), images))
                elif block.get("type") == "text":
                    texts.append(block.get("text", ""))
            text = "\n".join(texts)
        else:
            text = content if isinstance(content, str) else ""
        if text.startswith("Base directory for this skill:"):
            skill = text.split("\n", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            session.events.append((ts, "skill_load", skill, len(text)))
            continue
        if not text or record.get("isMeta") or record.get("isCompactSummary"):
            continue
        if text.startswith("[Request interrupted by user"):
            session.events.append((ts, "interrupt", clip(text), None))
            continue
        command = COMMAND_RE.search(text) if text.startswith("<command-") else None
        if command:
            args = COMMAND_ARGS_RE.search(text)
            text = f"{command.group(1)} {args.group(1) if args else ''}".strip()
        elif text.startswith(CLAUDE_NOISE_PREFIXES):
            continue
        session.prompts.append((ts, clip(text, PROMPT_CHARS)))
    for ts, name, detail in pending.values():
        session.tools.append((ts, name, detail, 0, None, None, 0, 0))
    return session


# ---------------------------------------------------------------------- Codex

CODEX_MARKERS = (
    '"session_meta"', '"turn_context"', '"item_completed"', '"token_count"', '"turn_aborted"',
    '"compacted"', '"user_message"', '"function_call"',
)
CODEX_WAIT_CALLS = {"sleep", "wait", "wait_agent", "request_user_input", "request_user_input_async"}


def duration_ms(value: object) -> int | None:
    if isinstance(value, dict) and "secs" in value:
        return int(value.get("secs", 0) * 1000 + value.get("nanos", 0) / 1e6)
    return None


def codex_item(session: Session, ts: str | None, item: dict) -> None:
    kind = item.get("type")
    status = item.get("status")
    if kind == "UserMessage":
        text = "\n".join(b.get("text", "") for b in item.get("content") or [] if isinstance(b, dict))
        if text.strip():
            session.prompts.append((ts, clip(text, PROMPT_CHARS)))
    elif kind == "AgentMessage":
        text = "\n".join(b.get("text", "") for b in item.get("content") or [] if isinstance(b, dict))
        session.events.extend(endgame_events(ts, text))
    elif kind == "CommandExecution":
        command = item.get("command")
        command = command[-1] if isinstance(command, list) and command else command
        exit_code = item.get("exit_code")
        failed = status != "completed" or (exit_code not in (0, None))
        error = clip(f"exit {exit_code}: {item.get('stderr') or item.get('aggregated_output') or ''}") if failed else None
        output = item.get("formatted_output") or item.get("aggregated_output") or ""
        session.tools.append((ts, "shell", clip(command or ""), int(failed), error, duration_ms(item.get("duration")), len(output), 0))
    elif kind == "McpToolCall":
        result = item.get("result") or {}
        failed = status != "completed" or bool(isinstance(result, dict) and result.get("isError")) or bool(item.get("error"))
        error = clip(item.get("error") or result) if failed else None
        content = result.get("content") if isinstance(result, dict) else None
        images = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "image") if isinstance(content, list) else 0
        output = tool_result_text(content) if content is not None else ""
        session.tools.append((ts, f"mcp:{item.get('server')}.{item.get('tool')}", clip(item.get("arguments") or ""), int(failed), error, duration_ms(item.get("duration")), len(output), images))
    elif kind == "FileChange":
        failed = status != "completed"
        paths = ", ".join((item.get("changes") or {}).keys())
        session.tools.append((ts, "apply_patch", clip(paths), int(failed), clip(item.get("stderr") or item.get("stdout") or "") if failed else None, None, len(item.get("stdout") or ""), 0))
    elif kind == "CollabAgentToolCall":
        session.tools.append((ts, f"collab:{item.get('tool')}", "", int(status not in ("completed", None)), None, None, 0, 0))
    elif kind == "Extension":
        session.tools.append((ts, str(item.get("kind") or "extension"), clip(item.get("query") or ""), 0, None, None, len(json.dumps(item.get("results") or "", ensure_ascii=False)), 0))
    elif kind == "ImageView":
        session.tools.append((ts, "view_image", clip(item.get("path") or ""), 0, None, None, 0, 1))


def parse_codex(path: Path) -> Session:
    session = Session(session_id=path.stem[-36:], agent="codex", path=str(path))
    items_seen = False
    last_total = 0
    legacy_prompts: list[tuple[str | None, str]] = []
    for record in read_records(path, CODEX_MARKERS):
        kind = record.get("type")
        ts = record.get("timestamp")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        session.seen(ts)
        subtype = payload.get("type")
        if kind == "session_meta":
            session.session_id = payload.get("id") or session.session_id
            session.cwd = payload.get("cwd")
            source = payload.get("source")
            if isinstance(source, dict) and "subagent" in source:
                session.origin = "subagent"
                session.parent_id = payload.get("parent_thread_id") or json.dumps(source).split('"parent_thread_id": "')[-1][:36]
            elif source == "exec":
                session.origin = "exec"
        elif kind == "turn_context":
            session.model = payload.get("model") or session.model
        elif kind == "compacted":
            session.events.append((ts, "compaction", "", None))
        elif subtype == "item_completed":
            items_seen = True
            codex_item(session, ts, payload.get("item") or {})
        elif subtype == "token_count":
            info = payload.get("info") or {}
            usage = info.get("total_token_usage") or {}
            if (usage.get("total_tokens") or 0) > last_total:  # repeated counts carry no new request
                last_total = usage.get("total_tokens") or 0
                session.api_call((info.get("last_token_usage") or {}).get("input_tokens") or 0)
            session.input_tokens = max(session.input_tokens, usage.get("input_tokens") or 0)
            session.cached_tokens = max(session.cached_tokens, usage.get("cached_input_tokens") or 0)
            session.cache_write_tokens = max(session.cache_write_tokens, usage.get("cache_write_input_tokens") or 0)
            session.output_tokens = max(session.output_tokens, usage.get("output_tokens") or 0)
        elif subtype == "turn_aborted":
            session.events.append((ts, "interrupt" if payload.get("reason") == "interrupted" else "turn_aborted", clip(payload.get("reason") or ""), None))
        elif subtype == "user_message" and kind == "event_msg":
            legacy_prompts.append((ts, clip(payload.get("message") or "", PROMPT_CHARS)))
        elif subtype == "function_call" and payload.get("name") in CODEX_WAIT_CALLS:
            session.tools.append((ts, str(payload.get("name")), clip(payload.get("arguments") or ""), 0, None, None, 0, 0))
    if not items_seen:
        session.prompts = legacy_prompts
    return session


# ------------------------------------------------------------------- Storage


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=120)  # a SessionEnd refresh may hold the write lock
    os.chmod(db_path, 0o600)
    conn.executescript(SCHEMA)
    stored = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    version = int(stored[0]) if stored else SCHEMA_VERSION
    for target in range(version + 1, SCHEMA_VERSION + 1):
        # Migrate in place: rows whose transcripts were pruned exist only here.
        for statement in MIGRATIONS[target]:
            conn.execute(statement)
        conn.execute("DELETE FROM files")  # re-parse surviving transcripts to fill new columns
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    return conn


def store(conn: sqlite3.Connection, session: Session, stat: os.stat_result) -> None:
    sid = session.session_id
    for table in ("prompts", "tool_calls", "events", "sessions"):
        conn.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sid, session.agent, session.origin, session.parent_id, session.path, session.cwd,
            session.model, session.started_at, session.ended_at, len(session.prompts),
            len(session.tools), sum(t[3] for t in session.tools), session.input_tokens,
            session.cached_tokens, session.output_tokens,
            sum(1 for e in session.events if e[1] == "compaction"),
            sum(1 for e in session.events if e[1] == "interrupt"),
            session.api_calls, session.cache_write_tokens, session.first_context, session.peak_context,
        ),
    )
    conn.executemany("INSERT INTO prompts VALUES (?,?,?,?)", [(sid, session.agent, *p) for p in session.prompts])
    conn.executemany("INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)", [(sid, session.agent, *t) for t in session.tools])
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)", [(sid, session.agent, *e) for e in session.events])
    conn.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)", (session.path, session.agent, stat.st_size, stat.st_mtime, sid))


def discover(claude_root: Path, codex_roots: list[Path]):
    for path in claude_root.glob("**/*.jsonl"):
        yield "claude", path
    for root in dict.fromkeys(r.resolve() for r in codex_roots):
        for path in root.glob("**/rollout-*.jsonl"):
            yield "codex", path


def ingest(conn: sqlite3.Connection, claude_root: Path, codex_roots: list[Path], quiet: bool = False) -> dict:
    known = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT path, size, mtime FROM files")}
    counts = {"parsed": 0, "unchanged": 0, "failed": 0}
    for agent, path in discover(claude_root, codex_roots):
        try:
            stat = path.stat()
        except OSError:
            continue
        if known.get(str(path)) == (stat.st_size, stat.st_mtime):
            counts["unchanged"] += 1
            continue
        try:
            session = parse_claude(path) if agent == "claude" else parse_codex(path)
        except Exception as exc:  # one corrupt transcript must not stop the warehouse refresh
            counts["failed"] += 1
            print(f"skip {path}: {exc}", file=sys.stderr)
            continue
        store(conn, session, stat)
        counts["parsed"] += 1
        if counts["parsed"] % 200 == 0:
            conn.commit()
            if not quiet:
                print(f"… {counts['parsed']} files parsed", file=sys.stderr)
    conn.commit()
    return counts


# -------------------------------------------------------------------- Report

EXPLAIN_RE = r"(什麼意思|甚麼意思|看不懂|聽不懂|改了什麼|做了什麼|分析了什麼|是幹嘛|在幹嘛|what does .{1,40} mean|what did you (do|change))"
ENDGAME_INVOKE_RE = r"^\s*[/$]endgame\b"
CONTINUE_RE = r"^\s*(請?繼續|继续|continue|go on|go ahead|keep going|ok|okay|好|好的|yes|y|是|對|嗯)[\s。.!！]*$"


SIGNATURE_NOISE = re.compile(r"^(exit code -?\d+|exit -?\d+:?|#+ ?error|[{}\[\]]|traceback .*|output:|script completed|wall time .*)$", re.I)
SIGNATURE_HINT = re.compile(r"error|fail|denied|not found|no such|fatal|invalid|cannot|unable|refus|timed? ?out|limit", re.I)


def error_signature(text: str) -> str:
    text = re.sub(r"^exit -?\d+:\s*", "", text or "")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not SIGNATURE_NOISE.match(l.strip())]
    line = next((l for l in lines if SIGNATURE_HINT.search(l)), lines[0] if lines else "")
    line = re.sub(r"(/[\w.@+-]+)+/?", "<path>", line)
    line = re.sub(r"\b[0-9a-f]{7,}\b", "<hex>", line)
    line = re.sub(r"\d+", "<n>", line)
    return line[:120]


def table(headers: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in row) + " |")
    return "\n".join(out) + "\n"


def report(conn: sqlite3.Connection, days: int, limit: int) -> str:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    conn.create_function("sig", 1, error_signature)
    conn.create_function("regexp", 2, lambda p, s: int(bool(s and re.search(p, s, re.I))))
    conn.execute("DROP TABLE IF EXISTS temp.win")
    conn.execute("CREATE TEMP TABLE win AS SELECT * FROM sessions WHERE started_at >= ?", (since,))
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    parts = [f"# Session insights — last {days} days (since {since[:10]})\n"]

    parts.append("## Volume by agent and origin\n")
    parts.append(table(
        ["agent", "origin", "sessions", "human prompts", "tool calls", "tool errors", "error %", "input Mtok", "output Mtok", "compactions", "interrupts"],
        q("""SELECT agent, origin, COUNT(*), SUM(prompts), SUM(tool_calls), SUM(tool_errors),
                    ROUND(100.0*SUM(tool_errors)/MAX(SUM(tool_calls),1),1),
                    ROUND(SUM(input_tokens)/1e6,1), ROUND(SUM(output_tokens)/1e6,2),
                    SUM(compactions), SUM(interrupts)
             FROM win GROUP BY agent, origin ORDER BY agent, COUNT(*) DESC"""),
    ))

    parts.append("## Tools with the most errors\n")
    parts.append(table(
        ["agent", "tool", "calls", "errors", "error %"],
        q(f"""SELECT t.agent, t.tool, COUNT(*), SUM(is_error), ROUND(100.0*SUM(is_error)/COUNT(*),1)
              FROM tool_calls t JOIN win USING(session_id) GROUP BY t.agent, t.tool
              HAVING SUM(is_error) > 0 ORDER BY SUM(is_error) DESC LIMIT {limit}"""),
    ))

    parts.append("## Recurring error signatures\n")
    parts.append(table(
        ["agent", "tool", "count", "sessions", "signature"],
        q(f"""SELECT t.agent, t.tool, COUNT(*), COUNT(DISTINCT session_id), sig(error) s
              FROM tool_calls t JOIN win USING(session_id) WHERE is_error=1
              GROUP BY t.agent, t.tool, s ORDER BY COUNT(*) DESC LIMIT {limit}"""),
    ))

    parts.append("## Friction signals\n")
    rows = []
    for agent in ("claude", "codex"):
        main = "origin != 'subagent' AND agent = ?"
        total = q(f"SELECT COUNT(*) FROM prompts p JOIN win USING(session_id) WHERE win.{main.replace('agent', 'win.agent')}", agent)[0][0]
        bare = q(f"SELECT COUNT(*) FROM prompts p JOIN win USING(session_id) WHERE win.{main.replace('agent', 'win.agent')} AND regexp(?, p.text)", agent, CONTINUE_RE)[0][0]
        rows.append((agent, "bare continue/ack prompts", f"{bare} of {total} human prompts"))
        missing = q("""SELECT COUNT(*) FROM tool_calls t JOIN win USING(session_id) WHERE t.agent=? AND is_error=1
                       AND regexp('no such file|does not exist|not found|ENOENT|cannot access', error)""", agent)[0][0]
        rows.append((agent, "missing path / not found errors", missing))
        sleeps = q("""SELECT COUNT(*) FROM tool_calls t JOIN win USING(session_id) WHERE t.agent=?
                      AND (tool='sleep' OR (tool IN ('Bash','shell') AND regexp('(^|[;&|]\\s*)sleep\\s+\\d', detail)))""", agent)[0][0]
        rows.append((agent, "sleep / polling calls", sleeps))
        denied = q("""SELECT COUNT(*) FROM tool_calls t JOIN win USING(session_id) WHERE t.agent=? AND is_error=1
                      AND regexp('denied|not allowed|blocked by|hook error|permission|rejected', error)""", agent)[0][0]
        rows.append((agent, "hook / permission denials", denied))
        retries = q("""SELECT COUNT(*) FROM (SELECT session_id, detail FROM tool_calls t JOIN win USING(session_id)
                       WHERE t.agent=? AND is_error=1 AND detail != '' GROUP BY session_id, detail HAVING COUNT(*) >= 3)""", agent)[0][0]
        rows.append((agent, "same failing call repeated ≥3× in a session", retries))
    parts.append(table(["agent", "signal", "value"], rows))

    parts.append("## Autonomy and understanding\n")
    parts.append(autonomy_section(conn, since, days))

    parts.append("## Heaviest sessions\n")
    parts.append(table(
        ["agent", "origin", "session", "project", "model", "input Mtok", "tool calls", "errors", "prompts"],
        q(f"""SELECT agent, origin, substr(session_id,1,8), replace(cwd, '{HOME}', '~'), model,
                     ROUND(input_tokens/1e6,1), tool_calls, tool_errors, prompts
              FROM win ORDER BY input_tokens DESC LIMIT {limit}"""),
    ))

    parts.append("## Most frequent human prompts (first 80 chars)\n")
    parts.append(table(
        ["agent", "count", "prompt"],
        q(f"""SELECT p.agent, COUNT(*), substr(replace(p.text, char(10), ' '), 1, 80) head
              FROM prompts p JOIN win USING(session_id) WHERE win.origin = 'interactive'
              GROUP BY p.agent, head HAVING COUNT(*) >= 3 ORDER BY COUNT(*) DESC LIMIT {limit}"""),
    ))
    return "\n".join(parts)


def autonomy_section(conn: sqlite3.Connection, since: str, days: int) -> str:
    """Comprehension-debt and human-touch signals, this window against the previous one."""
    before = (datetime.fromisoformat(since) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = []
    for label, start, end in (("previous", before, since), ("current", since, "9999")):
        total, asks = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(regexp(?, p.text)), 0) FROM prompts p JOIN sessions s USING(session_id)
               WHERE s.origin = 'interactive' AND p.ts >= ? AND p.ts < ?""", (EXPLAIN_RE, start, end)).fetchone()
        rows.append((f"{label} {days} days", "「什麼意思／做了什麼」 asks per 100 prompts", f"{round(100 * asks / max(total, 1), 1)} ({asks} of {total})"))
    runs = conn.execute(
        """SELECT w.agent,
                  EXISTS(SELECT 1 FROM events e WHERE e.session_id = w.session_id AND e.kind='endgame' AND e.detail='contract'),
                  (SELECT e.detail FROM events e WHERE e.session_id = w.session_id AND e.kind='endgame' AND e.detail != 'contract'
                   ORDER BY e.ts DESC LIMIT 1),
                  (SELECT COUNT(*) FROM prompts p WHERE p.session_id = w.session_id AND regexp(?, p.text))
           FROM win w
           WHERE w.origin != 'subagent' AND (
             EXISTS(SELECT 1 FROM prompts p WHERE p.session_id = w.session_id AND regexp(?, p.text))
             OR EXISTS(SELECT 1 FROM events e WHERE e.session_id = w.session_id AND e.kind='endgame'))""",
        (CONTINUE_RE, ENDGAME_INVOKE_RE)).fetchall()
    for agent in ("claude", "codex"):
        mine = [r for r in runs if r[0] == agent]
        if not mine:
            continue
        closes = {kind: sum(1 for r in mine if r[2] == kind) for kind in ("DONE", "BLOCKED", "DROPPED")}
        rows.append((agent, "endgame sessions", len(mine)))
        rows.append((agent, "printed a contract", sum(r[1] for r in mine)))
        rows.append((agent, "last close DONE / BLOCKED / DROPPED / none",
                     f"{closes['DONE']} / {closes['BLOCKED']} / {closes['DROPPED']} / {sum(1 for r in mine if r[2] is None)}"))
        rows.append((agent, "bare continue/ack prompts in endgame sessions", sum(r[3] for r in mine)))
    return table(["scope", "signal", "value"], rows)


def run_sql(conn: sqlite3.Connection, sql: str) -> str:
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        sys.exit("sql accepts one read-only SELECT or WITH statement")
    conn.create_function("sig", 1, error_signature)
    conn.create_function("regexp", 2, lambda p, s: int(bool(s and re.search(p, s, re.I))))
    cursor = conn.execute(sql)
    headers = [d[0] for d in cursor.description]
    return table(headers, cursor.fetchall())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--claude-root", type=Path, default=CLAUDE_ROOT)
    parser.add_argument("--codex-root", type=Path, action="append", dest="codex_roots",
                        help="repeatable; replaces the default ~/.codex and Orca account roots")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest")
    rep = sub.add_parser("report")
    rep.add_argument("--days", type=int, default=14)
    rep.add_argument("--limit", type=int, default=12)
    rep.add_argument("--no-ingest", action="store_true")
    sql = sub.add_parser("sql")
    sql.add_argument("query")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    if args.command == "ingest" or (args.command == "report" and not args.no_ingest):
        counts = ingest(conn, args.claude_root, args.codex_roots or default_codex_roots(), quiet=args.command == "report")
        print(f"ingest: {counts['parsed']} parsed, {counts['unchanged']} unchanged, {counts['failed']} failed → {args.db}", file=sys.stderr)
    if args.command == "report":
        print(report(conn, args.days, args.limit))
    elif args.command == "sql":
        print(run_sql(conn, args.query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
