#!/usr/bin/env python3
"""Read-only cross-provider consultation with subscription and model receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

RESPONSE_FORMAT = """

---
Review only: read what you need and leave every file unchanged.
Answer in plain text, starting on the first line with:
VERDICT: AGREE | PARTIAL | DISAGREE
Then one line per finding, most severe first, at most 15:
<blocker|high|medium|low> | <file:line or section> | <consequence for the user or the outcome> | must-fix: <yes|no>
Then at most 5 lines starting with "NOTE:" for anything the question asks that is not a finding.
"""
VERDICT_RE = re.compile(r"^VERDICT: (AGREE|PARTIAL|DISAGREE)[ \t]*$", re.M)
CLAUDE_ROUTE_ENV = {
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS", "CLAUDE_CODE_API_KEY_HELPER",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
}
CODEX_ROUTE_ENV = {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE", "CODEX_API_KEY"}


def load_config(to: str, cwd: Path, env: dict[str, str]) -> dict:
    cwd = cwd.resolve()
    if to == "claude":
        path = Path(env.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "settings.json"
        config = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError("Claude settings must be a JSON object")
        return config
    home = Path(env.get("CODEX_HOME", str(Path.home() / ".codex")))
    path = home / "config.toml"
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    if (config.get("model_provider", "openai") != "openai"
            or config.get("model_providers", {}).get("openai")
            or config.get("openai_base_url") or config.get("chatgpt_base_url")):
        raise ValueError("Codex custom routing is outside this subscription launcher")
    if config.get("profile"):
        raise ValueError("Named Codex config profiles require separate resolution; this launcher does not select them")
    # Project layers affect model/effort only, within the trusted project's boundary.
    # Provider and profile keys are machine-local and ignored in project config by Codex.
    ancestors = (cwd, *cwd.parents)
    markers = config.get("project_root_markers", [".git"])
    root = next((p for p in ancestors if any((p / marker).exists() for marker in markers)), cwd)
    trusted = any(Path(p).resolve() == root and v.get("trust_level") == "trusted"
                  for p, v in config.get("projects", {}).items())
    if trusted:
        directories = [cwd, *cwd.parents[:cwd.parents.index(root) + 1]] if cwd != root else [root]
        for directory in reversed(directories):
            path = directory / ".codex/config.toml"
            if path.exists():
                layer = tomllib.loads(path.read_text())
                config.update({k: layer[k] for k in ("model", "model_reasoning_effort") if k in layer})
    return config


def build_command(to: str, cwd: Path, out: Path, model: str | None = None,
                  effort: str | None = None) -> list[str]:
    if to == "codex":
        command = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
                   "--cd", str(cwd), "--output-last-message", str(out)]
        if model:
            command += ["--model", model]
        if effort:
            command += ["-c", f'model_reasoning_effort="{effort}"']
        return command + ["-"]
    command = ["claude", "-p", "--safe-mode", "--restricted", "--strict-mcp-config",
               "--tools", "Read,Grep,Glob", "--permission-mode", "plan", "--output-format",
               "stream-json", "--verbose", "--no-session-persistence"]
    if model:
        command += ["--model", model]
    if effort:
        command += ["--effort", effort]
    return command


def check_subscription(to: str, cwd: Path, env: dict[str, str], runner) -> str:
    names = CLAUDE_ROUTE_ENV if to == "claude" else CODEX_ROUTE_ENV
    active = sorted(k for k, v in env.items() if v and
                    (k in names or (to == "codex" and k.startswith("AZURE_OPENAI_"))))
    if active:
        raise ValueError("Subscription route blocked by environment override names: " + ", ".join(active))
    command = ["claude", "auth", "status"] if to == "claude" else ["codex", "login", "status"]
    result = runner(command, cwd=cwd, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode:
        raise ValueError(f"{to} login status failed; verify subscription login")
    if to == "claude":
        auth = json.loads(result.stdout)
        if not (isinstance(auth, dict) and auth.get("loggedIn") and auth.get("authMethod") == "claude.ai"
                and auth.get("apiProvider") == "firstParty" and auth.get("subscriptionType")):
            raise ValueError("Claude subscription login was not verified")
        return "claude_subscription"
    if (result.stdout + result.stderr).strip() != "Logged in using ChatGPT":
        raise ValueError("Codex ChatGPT login was not verified")
    return "chatgpt_subscription"


def claude_answer(stdout: str, model: str | None) -> tuple[str, dict]:
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    if any(not isinstance(e, dict) for e in events):
        raise ValueError("Claude stream events must be JSON objects")
    init = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    final = [e for e in events if e.get("type") == "result"]
    if len(init) != 1 or len(final) != 1 or final[0].get("is_error"):
        raise ValueError("Claude init/result metadata is missing or reports failure")
    actual = init[0].get("model")
    messages = [e.get("message") for e in events if e.get("type") == "assistant"]
    usage = final[0].get("modelUsage")
    tools = init[0].get("tools")
    if (any(not isinstance(m, dict) or not isinstance(m.get("model"), str) for m in messages) or not isinstance(usage, dict)
            or not isinstance(tools, list) or any(not isinstance(t, str) for t in tools)):
        raise ValueError("Claude runtime metadata has an unsupported shape")
    # Init and usage carry the context suffix (claude-opus-5-5[1m]); assistant messages omit it.
    used = {m["model"].removesuffix("[1m]") for m in messages}
    if not isinstance(actual, str) or used != {actual.removesuffix("[1m]")} or actual not in usage:
        raise ValueError("Claude model metadata is missing or reports a fallback")
    if model and model.startswith("claude-") and actual != model:
        raise ValueError(f"Requested model {model}; runtime reported {actual}")
    if (model or "").endswith("[1m]") and not actual.endswith("[1m]"):
        raise ValueError("Requested 1M context; runtime reported a standard context window")
    family = (model or "").removesuffix("[1m]")
    if family in {"opus", "sonnet", "haiku", "fable"} and not actual.startswith(f"claude-{family}-"):
        raise ValueError("Configured Claude alias does not match the runtime model family")
    if (init[0].get("apiKeySource") != "none" or init[0].get("permissionMode") != "plan"
            or not set(tools) <= {"Read", "Grep", "Glob"}):
        raise ValueError("Claude runtime did not confirm the subscription/read-only launch")
    return final[0].get("result", ""), {"model_resolved": actual, "model_verified": True,
                                        "effort_verified": False,
                                        "additional_usage_models": sorted(set(usage) - {actual})}


def codex_metadata(stderr: str, model: str | None, effort: str | None) -> dict:
    def field(name: str) -> str | None:
        match = re.search(r"^" + re.escape(name) + r": ([^\r\n]+)$", stderr, re.M)
        return match[1].strip() if match else None

    actual = field("model")
    if not actual or field("provider") != "openai" or field("sandbox") != "read-only":
        raise ValueError("Codex runtime header did not confirm model/provider/read-only sandbox")
    if model and actual != model:
        raise ValueError(f"Requested model {model}; runtime reported {actual}")
    resolved_effort = field("reasoning effort")
    if effort and resolved_effort != effort:
        raise ValueError("Codex runtime effort does not match the requested effort")
    return {"model_resolved": actual, "model_verified": True,
            "model_evidence": "runtime_header", "effort_resolved": resolved_effort,
            "effort_verified": resolved_effort is not None}


def quota_error(to: str, stdout: str, stderr: str) -> bool:
    """Read CLI error surfaces only; candidate and successful answers are untrusted."""
    pattern = re.compile(
        r"usage_limit_reached|quota_exceeded|you(?:'|’)ve hit your limit|"
        r"(?:you(?:'|’)ve hit|you have hit|reached|exceeded) (?:your |the )?"
        r"(?:usage|weekly|session|subscription|quota) (?:limit|quota)|"
        r"(?:usage|weekly|session|subscription|quota) limit (?:reached|exceeded)", re.I)
    if to == "codex":
        # Codex echoes the brief and reviewer output before its final diagnostics.
        lines = [line for line in stderr.splitlines() if line.strip()]
        return bool(lines and re.match(r"^(?:\S+\s+)?ERROR[: ]", lines[-1])
                    and pattern.search(lines[-1]))
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result" and event.get("is_error"):
            errors = event.get("errors", [])
            texts = [event.get("result", "")]
            if isinstance(errors, list):
                texts.extend(errors)
            if any(isinstance(text, str) and pattern.search(text) for text in texts):
                return True
    return False


def consult_once(to: str, cwd: Path, brief: Path, out: Path, timeout: int, runner=subprocess.run,
            *, model: str | None = None, effort: str | None = None, environ=None) -> dict:
    env = dict(os.environ if environ is None else environ)
    started = time.monotonic()
    receipt: dict = {"to": to, "cwd": str(cwd), "brief": str(brief), "out": str(out)}
    if brief.resolve() == out.resolve() or (brief.exists() and out.exists() and brief.samefile(out)):
        return {**receipt, "status": "failed", "detail": "Brief and output must be different files", "seconds": 0}
    output_owned = False
    try:
        data = brief.read_bytes()
        prompt = data.decode() + RESPONSE_FORMAT
        receipt["brief_sha256"] = hashlib.sha256(data).hexdigest()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        output_owned = True
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        config = load_config(to, cwd, env)
        # Named models must be exact IDs; only configured defaults may be aliases.
        if to == "claude" and model and not re.fullmatch(r"claude-[a-z0-9-]+(\[1m\])?", model):
            raise ValueError("Pass an exact Claude model ID, not a family name or alias")
        model = model or config.get("model")
        effort = effort or config.get("effortLevel" if to == "claude" else "model_reasoning_effort")
        if not isinstance(model, str) or not model:
            raise ValueError("No configured model; supply an exact --model ID")
        if effort and (not isinstance(effort, str) or effort not in {"low", "medium", "high", "xhigh", "max"}):
            raise ValueError("Unsupported configured effort")
        receipt.update(model_requested=model, effort_requested=effort)
        receipt["inference_route"] = check_subscription(to, cwd, env, runner)
        command = build_command(to, cwd, out, model, effort)
        result = runner(command, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                        input=prompt, env=env)
        receipt["exit_code"] = result.returncode
        valid_codex_answer = (to == "codex" and result.returncode == 0 and out.exists()
                              and len(VERDICT_RE.findall(out.read_text())) == 1)
        if not valid_codex_answer and quota_error(to, result.stdout, result.stderr):
            receipt.update(status="quota_exhausted", detail="Subscription CLI reported a usage limit")
            out.unlink(missing_ok=True)
            receipt["seconds"] = round(time.monotonic() - started)
            return receipt
        if result.returncode:
            raise ValueError(f"{to} consultation exited {result.returncode}; no verified answer")
        if to == "claude":
            answer, metadata = claude_answer(result.stdout, model)
        else:
            metadata = codex_metadata(result.stderr, model, effort)
            answer = out.read_text() if out.exists() else ""
        if not isinstance(answer, str) or len(VERDICT_RE.findall(answer)) != 1:
            raise ValueError("Reviewer did not return a single valid verdict")
        receipt.update(metadata)
        out.write_text(answer)
        receipt["status"] = "ok"
    except subprocess.TimeoutExpired:
        receipt.update(status="timeout", detail="CLI timeout reached")
    except FileNotFoundError:
        receipt.update(status="missing_cli", detail="Required CLI or input file is unavailable")
    except (ValueError, OSError) as error:
        receipt.update(status="failed", detail=str(error))
    if receipt["status"] != "ok" and output_owned:
        out.unlink(missing_ok=True)
    receipt["seconds"] = round(time.monotonic() - started)
    return receipt


def consult(to: str, cwd: Path, brief: Path, out: Path, timeout: int, runner=subprocess.run,
            *, model: str | None = None, effort: str | None = None, environ=None,
            quota_fallback: bool = False) -> dict:
    first = consult_once(to, cwd, brief, out, timeout, runner,
                         model=model, effort=effort, environ=environ)
    if not quota_fallback or model or first["status"] != "quota_exhausted":
        return first
    # The alternate gets the same frozen bytes, its own default, and fresh CLI context.
    try:
        digest = hashlib.sha256(brief.read_bytes()).hexdigest()
    except OSError:
        return {**first, "status": "failed", "detail": "Frozen brief is unavailable before fallback"}
    if digest != first["brief_sha256"]:
        return {**first, "status": "failed", "detail": "Frozen brief changed before fallback"}
    alternate = "codex" if to == "claude" else "claude"
    second = consult_once(alternate, cwd, brief, out, timeout, runner,
                          effort=first.get("effort_requested"), environ=environ)
    if second.get("brief_sha256") != first["brief_sha256"]:
        out.unlink(missing_ok=True)
        second.update(status="failed", detail="Fallback brief digest does not match")
    return {**second, "requested_to": to, "fallback_used": True,
            "fallback_reason": "subscription_quota", "attempts": [first, second]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, choices=("codex", "claude"))
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--model", help="exact model ID when a model is requested; otherwise read runtime config")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--timeout", type=int, default=1800, help="inference timeout in seconds")
    parser.add_argument("--quota-fallback", action="store_true",
                        help="on confirmed quota exhaustion, try the other subscription once; disabled with --model")
    args = parser.parse_args(argv)
    receipt = consult(args.to, args.cwd.resolve(), args.brief, args.out, args.timeout,
                      model=args.model, effort=args.effort, quota_fallback=args.quota_fallback)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
