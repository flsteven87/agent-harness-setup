---
name: consult
description: Get a read-only second opinion from Claude Code or Codex on a frozen artifact when the user requests another provider or a named model to review, confirm, or stress-test it, or a required review gate needs quota recovery.
---

# Consult

One independent read-only opinion on frozen bytes. Verify each finding against the source before
using it. The surrounding task owns edit and delivery authority; consultation grants neither.

## 1. Freeze the artifact

Identify the repository and candidate with existing base/head SHAs, or save a scratch snapshot and
its SHA256 for uncommitted work. Keep the candidate unchanged during review. A read-only request
uses existing source or scratch copies; it does not create a repository commit. Done when the brief
names the exact identity the reviewer must reproduce.

## 2. Write a blind brief

In scratch space, name the repository, frozen identity, intent, and one question. Include the
candidate bytes needed to review that identity: a diff for changed source or snapshot text for
uncommitted documents. Add current source paths for context inside the repository; paste required
context from other roots because the restricted reader cannot open those paths. Keep the author's verdict and proposed
fixes out. The launcher appends the shared verdict format.

## 3. Run the other provider

Codex consults Claude Code; Claude Code consults Codex. When the user names a model from the caller's
own provider, use a read-only subagent with that selection and the same brief, and confirm its
runtime model; when that model cannot be confirmed, stop that route and report it. A same-provider
fallback uses a fresh CLI process and is disclosed in the result.

```bash
uv run --no-project python ~/.agents/skills/consult/scripts/consult.py --to claude --cwd <repo> --brief <brief-file> --out <answer-file> --effort high
```

Use `--to codex` for the Codex route. Pass `--model` when the user names a model; otherwise the
launcher pins the configured runtime default. The launcher verifies the subscription route and the
runtime model, and its receipt is the evidence.

Wait on the background process's completion. Output is buffered; silence is not failure. The
inference timeout stays at 1800 seconds and can be set with `--timeout`. The JSON receipt reports
`ok`, `quota_exhausted`, `failed`, `timeout`, or `missing_cli`; only `ok` permits using the answer. Report a failed
route with its detail, preserving the frozen artifact.

### Subscription quota recovery

For required review gates, including both `$code-review` axes and `$ship` readiness, add
`--quota-fallback`. On a confirmed CLI usage-limit error, the launcher tries the other subscription
once, with the same brief bytes, requested effort, a fresh read-only context, and that runtime's
configured default model. Its receipt retains both attempts and the verified final provider/model.
Use the successful alternate verdict under the same axis; disclose the substitution and any loss
of cross-provider diversity. Two axes still require two independent launches and blind briefs.

Ordinary second opinions keep their requested provider unless quota recovery is requested. An
explicit `--model` pins the request and disables fallback. For an explicit provider requirement,
omit `--quota-fallback`. Authentication, routing, metadata,
model mismatch, timeout, generic throttling, and malformed-answer failures stop without switching.
If both subscriptions are exhausted or the alternate fails, preserve the candidate and report the
failed predicate plus retry after quota reset or route repair. This launcher never selects an API
key, another account, a paid top-up, or a lower model tier. Reuse keys carry the actual provider,
model, effort, source digest, and axis; an alternate result is a new verdict.

## 4. Verify and disposition

Accept each finding with the source line checked this turn, or reject it with refuting evidence.
When the surrounding task authorizes changes, apply one fix pass for accepted findings and run the
affected checks. A read-only task reports proposed fixes. Later material findings escalate instead
of starting another round. Formal review requirements remain the working profile's responsibility;
this consultation does not replace them.

Done when every finding has a disposition and the report names the verdict, frozen identity,
verified model, fixes or proposals, rejected findings, and unverified behavior.
