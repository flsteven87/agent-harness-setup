#!/usr/bin/env python3
"""Claude Code Stop hook: keep the session working while endgame work is open.

Registered as a user-level Stop hook; sessions without endgame work pass straight through. Work
opens when the `endgame` skill loads (Claude Code records the load in the transcript, so opening
never depends on the model printing anything) or when an assistant message starts an
`ENDGAME CONTRACT`. It closes when an assistant message says `ENDGAME: DONE`, `ENDGAME: BLOCKED`,
or `ENDGAME: DROPPED`. The hook reads the transcript plus its `last_assistant_message` (the final
message can reach the hook before the transcript file). The stop proceeds with nothing open, while
background tasks will deliver the next turn, or after MAX_BLOCKS continuations.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_BLOCKS = 25
OPEN_RE = re.compile(r"^[#*\s]*ENDGAME CONTRACT\b", re.M)
CLOSE_RE = re.compile(r"^[#*\s]*ENDGAME:\s*(DONE|BLOCKED|DROPPED)\b", re.M)
QUOTED_RE = re.compile(r"^\s*(```|~~~).*?^\s*\1[^\n]*$|^\s*>.*$", re.M | re.S)  # examples, not declarations
SKILL_LOAD_RE = re.compile(r"^Base directory for this skill: \S*/endgame/?$", re.M)
BLOCK_TAG = "[endgame-gate]"


def contract_state(messages: list[tuple[str, str]]) -> tuple[str | None, int]:
    """Fold (role, text) messages into (open contract text or None, gate blocks since it opened).

    Restating an open contract keeps its block count, so the cap always ends the loop.
    """
    contract: str | None = None
    blocks = 0
    for role, text in messages:
        if role == "assistant":
            text = QUOTED_RE.sub("", text)
            opened = [m.start() for m in OPEN_RE.finditer(text)]
            closed = [m.start() for m in CLOSE_RE.finditer(text)]
            if opened and (not closed or opened[-1] > closed[-1]):
                if contract is None:
                    blocks = 0
                contract = text[opened[-1]:]
            elif closed:
                contract = None
        elif SKILL_LOAD_RE.match(text):
            if contract is None:
                contract, blocks = "endgame skill invoked", 0
        elif contract is not None and BLOCK_TAG in text:
            blocks += 1
    return contract, blocks


def read_messages(transcript: Path) -> list[tuple[str, str]]:
    messages = []
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "ENDGAME" not in line and BLOCK_TAG not in line and "/endgame" not in line:  # stay cheap
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = message_text(record)
            if text:
                messages.append(("assistant" if record.get("type") == "assistant" else "other", text))
    return messages


def message_text(record: dict) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def decide(hook_input: dict) -> dict | None:
    path = hook_input.get("transcript_path")
    if not path or not Path(path).is_file():
        return None  # without the transcript the block count cannot bound the loop
    messages = read_messages(Path(path))
    last = hook_input.get("last_assistant_message")
    assistant_texts = [text for role, text in messages if role == "assistant"]
    if isinstance(last, str) and last and (not assistant_texts or assistant_texts[-1] != last):
        messages.append(("assistant", last))
    contract, blocks = contract_state(messages)
    if contract is None or hook_input.get("background_tasks"):
        return None
    if blocks >= MAX_BLOCKS:
        return {"systemMessage": f"{BLOCK_TAG} Contract still open after {MAX_BLOCKS} continuations; stopping for review."}
    return {
        "decision": "block",
        "reason": (
            f"{BLOCK_TAG} The endgame work is still open ({blocks + 1}/{MAX_BLOCKS}). Take the next "
            "action toward its end state. Close it on its own line with `ENDGAME: DONE — <check evidence>` "
            "once every check has passed in this session, `ENDGAME: BLOCKED — <human gate, prepared action>` "
            "when only a listed human gate remains, or `ENDGAME: DROPPED — <reason>` when the user redirected."
        ),
    }


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    result = decide(hook_input)
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
