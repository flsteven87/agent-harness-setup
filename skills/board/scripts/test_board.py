#!/usr/bin/env python3
"""Regression tests for the product board's MEMORY parsing and rendering."""

from __future__ import annotations

import html
import importlib.util
import json
import re
import subprocess
import sys
import unittest
import unittest.mock
from datetime import date, datetime
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("board.py")
SPEC = importlib.util.spec_from_file_location("board", MODULE_PATH)
assert SPEC and SPEC.loader
board = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = board
SPEC.loader.exec_module(board)

MEMORY = """# Project Memory

## Current State

- Refreshed today.

## Active Workstreams

### `github:owner/repo#12`

- Objective: Members see their season summary.
- State (verified 2026-09-29): Backend done;
  frontend pending.
  - Sub-point kept with State.
- Next: Build the summary card.
- Decision: Ship behind a flag or to everyone? Recommend the flag (reversible).
- Blocker: None.

### plain-slug

- Objective: Faster page loads.
- Next: Measure LCP.
- Blocker: Needs the owner's device.

### decided-and-blocked

- Objective: Nightly backups.
- Decision: Turn on daily backups? Recommend yes (reversible).
- Blocker: Operator input.

## Waiting on Decisions or External Evidence

### `workstream:vendor-reply`

- Objective: Vendor confirms the quota.
- Blocker: None; waits on the vendor.

## Deferred Workstreams

### deferred-thing

- Objective: Not shown.
- Decision: Not shown either.
"""


class ParseMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {w.key: w for w in board.parse_memory(MEMORY)}

    def test_reads_every_entry_and_classes_deferred_by_section(self) -> None:
        self.assertEqual(
            list(self.items),
            ["github:owner/repo#12", "plain-slug", "decided-and-blocked", "workstream:vendor-reply", "deferred-thing"],
        )
        self.assertEqual([k for k, w in self.items.items() if w.deferred], ["deferred-thing"])
        self.assertEqual(board.status_of(self.items["deferred-thing"]), "deferred")

    def test_joins_continuation_lines_and_drops_label_qualifier(self) -> None:
        state = self.items["github:owner/repo#12"].get("state")
        self.assertEqual(state, "Backend done; frontend pending. - Sub-point kept with State.")

    def test_decision_and_blocker_ignore_none(self) -> None:
        first = self.items["github:owner/repo#12"]
        self.assertTrue(first.decision.startswith("Ship behind a flag"))
        self.assertEqual(first.blocker, "")
        self.assertEqual(self.items["workstream:vendor-reply"].blocker, "")
        self.assertEqual(self.items["plain-slug"].blocker, "Needs the owner's device.")

    def test_a_decision_is_not_also_listed_as_blocked(self) -> None:
        product = board.Product(name="repo", path="/repo", workstreams=list(self.items.values()))
        self.assertEqual([w.key for w in product.decisions], ["github:owner/repo#12", "decided-and-blocked"])
        self.assertEqual([w.key for w in product.blocked], ["plain-slug"])


REAL_FORMATS = """## Active Workstreams

### bold-fields

- **Objective:** Find a positive rule.
- **State (2026-09-27 15:25, verified):** Two runs done.
- **Next:** The owner chooses a direction.
- **Blockers / ruled out:** Owner direction choice.

### fullwidth-and-compound

- **Objective / owner:** Example Owner: ship log delivery.
- **Next：** Watch the next staging run，然後
  確認結果。
- **Blocker / ruled out：** 無技術 blocker；owner 已要求暫停。

### paragraph-style

**Objective.** Fund the company account.

**Blocker.** Receipts remain unreconciled.

- letting the automation query production: not a field

```markdown
### not-a-workstream
- Decision: example only
```

## Inactive Workstreams

### parked

- Blocker: Parked, not stuck.
"""


class RealFormatTest(unittest.TestCase):
    def test_bold_fullwidth_and_compound_labels(self) -> None:
        items = {w.key: w for w in board.parse_memory(REAL_FORMATS)}
        self.assertEqual(list(items), ["bold-fields", "fullwidth-and-compound", "paragraph-style", "parked"])
        self.assertTrue(items["parked"].deferred)
        paragraph = items["paragraph-style"]
        self.assertEqual(paragraph.get("objective"), "Fund the company account.")
        self.assertEqual(paragraph.blocker, "Receipts remain unreconciled. - letting the automation query production: not a field")
        bold = items["bold-fields"]
        self.assertEqual(bold.get("objective"), "Find a positive rule.")
        self.assertEqual(bold.get("state"), "Two runs done.")
        self.assertEqual(bold.blocker, "Owner direction choice.")
        compound = items["fullwidth-and-compound"]
        self.assertEqual(compound.get("objective"), "Example Owner: ship log delivery.")
        self.assertEqual(compound.get("next"), "Watch the next staging run，然後確認結果。")
        # "No technical blocker; paused by the owner" still waits on the owner.
        self.assertEqual(compound.blocker, "無技術 blocker；owner 已要求暫停。")


class CollectTest(unittest.TestCase):
    def test_unreadable_memory_is_reported_not_raised(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "MEMORY.md").write_bytes(b"\xff\xfe not utf-8")
            product = board.collect("broken", tmp)
        self.assertTrue(any(e.startswith("MEMORY.md 讀取失敗") for e in product.errors))

    def test_unrecorded_counts_commits_after_the_notes_that_do_not_write_them(self) -> None:
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            git = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            subprocess.run([*git, "init", "-q", "-b", "main"], cwd=tmp, check=True)
            memory = Path(tmp, "MEMORY.md")
            memory.write_text("## Active Workstreams\n", encoding="utf-8")
            os.utime(memory, (1_700_000_000, 1_700_000_000))
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "later work"], cwd=tmp, check=True)
            subprocess.run([*git, "add", "MEMORY.md"], cwd=tmp, check=True)
            subprocess.run([*git, "commit", "-q", "-m", "handoff"], cwd=tmp, check=True)
            product = board.collect("shop", tmp)
        self.assertEqual(product.unrecorded, 1)

    def test_merged_commits_missing_from_local_main_are_counted_and_checked(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            git = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            subprocess.run([*git, "init", "-q", "-b", "main"], cwd=tmp, check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], cwd=tmp, check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "merged elsewhere"], cwd=tmp, check=True)
            merged = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, check=True, capture_output=True, text=True).stdout.strip()
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", merged], cwd=tmp, check=True)
            subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=tmp, check=True)
            product = board.Product(name="shop", path=tmp, default="main")
            self.assertEqual(board.behind(tmp, "main", "origin/main"), 1)
            # A bot's commit on top (an image bump) is nothing this machine runs, so it is not merged work to sync.
            subprocess.run(["git", "checkout", "-q", "--detach", merged], cwd=tmp, check=True)
            bot = ["git", "-c", "user.email=bot@example.test", "-c", "user.name=github-actions[bot]"]
            subprocess.run([*bot, "commit", "-q", "--allow-empty", "-m", "chore: bump images [skip ci]"], cwd=tmp, check=True)
            subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp, check=True)
            subprocess.run(["git", "checkout", "-q", "main"], cwd=tmp, check=True)
            self.assertEqual(board.behind(tmp, "main", "origin/main"), 1)
            self.assertEqual(board.behind(tmp, "main", "main"), 0)
            self.assertFalse(board.live_here(product, {"state": "MERGED", "mergeCommit": {"oid": merged}}))
            subprocess.run(["git", "merge", "-q", "--ff-only", merged], cwd=tmp, check=True)
            self.assertTrue(board.live_here(product, {"state": "MERGED", "mergeCommit": {"oid": merged}}))
            self.assertFalse(board.live_here(product, {"state": "MERGED"}))
            self.assertTrue(board.live_here(product, {"state": "CLOSED"}))
            self.assertTrue(board.live_here(product, None))

    def test_collect_counts_linked_worktrees_and_branches_no_worktree_holds(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            git = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            repo = Path(tmp, "repo")
            subprocess.run([*git, "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
            subprocess.run([*git, "worktree", "add", "-q", "-b", "task", str(Path(tmp, "wt"))], cwd=repo, check=True)
            subprocess.run([*git, "branch", "stale"], cwd=repo, check=True)
            product = board.collect("shop", str(repo))
        self.assertEqual(([Path(p).name for p in product.worktrees], product.loose_branches), (["wt"], ["stale"]))

    def test_shipped_reads_the_fetched_remote_line_not_unpushed_work(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            git = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            origin, primary, other = (Path(tmp, n) for n in ("origin.git", "primary", "other"))
            subprocess.run([*git, "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
            subprocess.run([*git, "clone", "-q", str(origin), str(primary)], check=True, capture_output=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], cwd=primary, check=True)
            subprocess.run([*git, "push", "-q", "origin", "main"], cwd=primary, check=True)
            subprocess.run([*git, "clone", "-q", str(origin), str(other)], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "merged elsewhere"], cwd=other, check=True)
            subprocess.run([*git, "push", "-q", "origin", "main"], cwd=other, check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "unpushed"], cwd=primary, check=True)
            # Cloned while empty, so origin/HEAD is absent; the fetched origin/main is still the line.
            without_head = board.collect("shop", str(primary))
            subprocess.run([*git, "remote", "set-head", "origin", "main"], cwd=primary, check=True)
            product = board.collect("shop", str(primary))
        for collected in (without_head, product):
            subjects = [subject for _, subject, _ in collected.deliveries]
            self.assertIn("merged elsewhere", subjects)
            self.assertNotIn("unpushed", subjects)

    def test_git_reads_never_take_optional_locks(self) -> None:
        self.assertEqual(board.GIT, ["git", "--no-optional-locks"])


class ScopeTest(unittest.TestCase):
    def test_current_repo_resolves_the_primary_checkout_from_a_worktree(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp, "shop").resolve()
            primary.mkdir()
            git = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            subprocess.run([*git, "init", "-q", "-b", "main"], cwd=primary, check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], cwd=primary, check=True)
            linked = Path(tmp, "shop-feature").resolve()
            subprocess.run([*git, "worktree", "add", "-q", "-b", "feature", str(linked)], cwd=primary, check=True)
            self.assertEqual(board.current_repo(linked), ("shop", str(primary)))

    def test_overview_with_one_project_keeps_the_index(self) -> None:
        page = render([board.Product(name="solo", path="/s")], overview=True)
        self.assertTrue("<title>產品總覽看板</title>" in page)
        self.assertTrue("各產品現況" in page)

    def test_page_names_never_collide_or_shadow_the_overview(self) -> None:
        names = {
            board.page_name("app", "/a/app"),
            board.page_name("app", "/b/app"),
            board.page_name("a_b", "/c/a_b"),
            board.page_name("a-b", "/c/a-b"),
            board.page_name("股市", "/d/股市"),
            board.page_name("基金", "/d/基金"),
        }
        self.assertEqual(len(names), 6)
        self.assertNotIn("index.html", {board.page_name("index", "/e/index")})

    def test_bare_repository_worktree_is_its_own_project(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            git = ["git", "-c", "user.email=t@example.test", "-c", "user.name=t"]
            seed = Path(tmp, "seed").resolve()
            seed.mkdir()
            subprocess.run([*git, "init", "-q", "-b", "main"], cwd=seed, check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], cwd=seed, check=True)
            bare = Path(tmp, "repo.git").resolve()
            subprocess.run([*git, "clone", "-q", "--bare", str(seed), str(bare)], check=True)
            work = Path(tmp, "work").resolve()
            subprocess.run([*git, "worktree", "add", "-q", str(work), "main"], cwd=bare, check=True)
            self.assertEqual(board.current_repo(work), ("work", str(work)))

    def test_single_project_page_is_named_for_it_and_has_no_index(self) -> None:
        product = board.Product(name="shop", path="/s", deliveries=[("abc", "Ship it", "2026-09-29")])
        page = render([product], overview=False)
        self.assertTrue("<title>shop 看板</title>" in page)
        self.assertTrue("0 件事輪到你，0 件卡住；0 條有 agent 在做，0 條可以派工但沒人在做；這 7 天有 1 次更新。" in page)
        self.assertFalse("各產品現況" in page)


class CiStateTest(unittest.TestCase):
    def test_states(self) -> None:
        self.assertEqual(board.ci_state([]), "none")
        self.assertEqual(board.ci_state([{"status": "COMPLETED", "conclusion": "SUCCESS"}]), "pass")
        self.assertEqual(board.ci_state([{"status": "COMPLETED", "conclusion": "SKIPPED"}]), "pass")
        self.assertEqual(board.ci_state([{"status": "IN_PROGRESS", "conclusion": ""}]), "pending")
        self.assertEqual(board.ci_state([{"state": "PENDING"}]), "pending")
        self.assertEqual(board.ci_state([{"status": "COMPLETED", "conclusion": "STALE"}]), "pending")
        self.assertEqual(
            board.ci_state([{"conclusion": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "FAILURE"}]), "fail"
        )


def stub_brief(request: dict) -> dict:
    """A valid plain-language brief for one request, as the agent would write it."""
    if request["kind"] == "product":
        brief = {"summary": f"產品摘要 {request['project']}"}
        if request["shipped"]:
            brief["shipped"] = [{"title": "上線標題", "stage": "已合併", "before": "原本句。", "after": "現在句。",
                                 "commits": [request["shipped"][0]["commit"]]}]
        if request["workstreams"]:
            brief["focus"] = {"key": request["workstreams"][0]["key"], "why": "先做的理由。"}
        return brief
    actor = {"waiting": "external", "stuck": "you", "decide": "you"}.get(request["status"], "engineering")
    brief = {"title": "白話標題", "who": "對象", "before": "原本句。", "now": "現況句。", "why": "重要句。", "next": "下一步句。",
             "actor": actor}
    if request["status"] == "stuck":
        brief["stuck"] = "卡點句。"
    if request["status"] == "decide":
        brief["decision"] = {
            "question": "要不要做這件事？",
            "options": [
                {"label": "做", "consequence": "做的後果。", "reversible": True},
                {"label": "不做", "consequence": "不做的後果。", "reversible": False},
            ],
            "recommended": 0,
        }
    return brief


def stub_briefs(products: list) -> dict:
    return {r["id"]: stub_brief(r) for p in products for r in board.brief_requests(p)}


def render(products: list, overview: bool = True, briefs: dict | None = None) -> str:
    return board.render(products, briefs or stub_briefs(products), datetime(2026, 9, 29, 9, 0), overview=overview)


def plain_story(page: str) -> str:
    """The page without the launch texts it quotes verbatim: what the plain-language layer says."""
    page = re.sub(r'<script type="application/json".*?</script>', "", page, flags=re.S)
    return re.sub(r'<p class="launch-text"[^>]*>.*?</p>', "", page, flags=re.S)


def launches(page: str) -> list[dict]:
    """The launch actions a page embeds, in page order, each with the text its card shows."""
    actions = json.loads(re.search(r'id="launch-actions">(.*?)</script>', page, re.S).group(1))
    shown = re.findall(r'<div class="launch" data-action="([0-9a-f]+)">.*?<p class="launch-text"[^>]*>(.*?)</p>', page, re.S)
    for aid, text in shown:
        assert actions[aid]["text"] == html.unescape(text), aid
    return [actions[aid] for aid, _ in shown]


class RenderTest(unittest.TestCase):
    def test_decisions_lead_and_text_is_escaped(self) -> None:
        quiet = board.Product(name="quiet", path="/q", last_commit="2026-09-29T10:00:00+08:00")
        busy = board.Product(
            name="busy",
            path="/b",
            last_commit="2026-09-01T10:00:00+08:00",
            workstreams=board.parse_memory(MEMORY.replace("Members see", "<script>x</script> Members see")),
        )
        briefs = stub_briefs([quiet, busy])
        briefs[board.product_id(busy)]["summary"] = "<b>摘要</b>"
        page = render([quiet, busy], briefs=briefs)
        self.assertTrue("3 件事輪到你，0 件卡住；0 條有 agent 在做，0 條可以派工但沒人在做；2 個產品裡有 2 個這 7 天沒有更新。" in page)
        self.assertLess(page.index('id="busy"'), page.index('id="quiet"'))
        self.assertFalse("<script>x</script>" in page or "<b>摘要</b>" in page)
        self.assertTrue("&lt;b&gt;摘要&lt;/b&gt;" in page)
        self.assertFalse("Not shown" in page)

    def test_the_page_tells_the_brief_not_the_source_notes(self) -> None:
        product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY),
                                deliveries=[("abc1234", "feat: secret subject", "2026-09-29")])
        page = render([product])
        self.assertFalse("Members see" in page or "secret subject" in page)
        story = plain_story(page)
        self.assertFalse("github:owner" in story)
        self.assertTrue("白話標題" in story and "卡點句。" in story)
        self.assertFalse(re.search(r"\bPR\b|commit|branch|分支", story))

    def test_read_errors_stay_visible(self) -> None:
        product = board.Product(name="shop", path="/s", errors=["沒有 MEMORY.md"])
        self.assertTrue("有些資料沒讀到：沒有 MEMORY.md" in render([product]))

    def test_decision_card_shows_consequences_recommendation_and_reversibility(self) -> None:
        product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY))
        briefs = stub_briefs([product])
        page = plain_story(render([product], briefs=briefs))
        decide = page[page.index('id="h-turns"'):page.index('id="h-stuck"')]
        self.assertEqual(decide.count('class="decision"'), 2)
        self.assertTrue("做的後果。" in decide and "不做的後果。" in decide)
        self.assertEqual(decide.count(">推薦<"), 2)
        self.assertTrue("之後可以改" in decide and "做了很難回頭" in decide)
        for brief in briefs.values():
            if "decision" in brief:
                brief["decision"]["recommended"] = None
        page = render([product], briefs=briefs)
        self.assertFalse(">推薦<" in page)

    def test_each_launch_shows_the_exact_text_it_sends(self) -> None:
        product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY))
        page = render([product])
        actions = launches(page)
        decide = page[page.index('id="h-turns"'):page.index('id="h-stuck"')]
        self.assertEqual(decide.count(">選這個</button>"), 4)
        self.assertTrue('aria-label="選「不做」"' in decide)
        decided = next(w for w in product.workstreams if w.key == "github:owner/repo#12")
        self.assertIn(
            {"kind": "dispatch", "project": "shop", "path": "/s", "key": "github:owner/repo#12",
             "text": "The owner chose 「做」 for 「要不要做這件事？」. Record the decision in this workstream, "
             "then carry out what follows from it.",
             "group": board.stream_id(product, decided), "ask": False, "title": "白話標題：做",
             "entry": board.stream_id(product, decided)},
            actions,
        )
        # A decision's options share one group, so only one of them can launch.
        self.assertEqual(len({a["group"] for a in actions if a["group"]}), 2)
        self.assertIn(
            ("Measure LCP.", True),
            [(a["text"], a["ask"]) for a in actions],
        )
        # The external card gets none; a card listed above keeps its one button there.
        self.assertFalse(any(a["key"] == "workstream:vendor-reply" for a in actions))
        self.assertEqual(len(actions), 4 + 1)
        self.assertTrue('data-launch-token=""' in page)

    def test_every_card_dispatches_and_owner_steps_ask_first(self) -> None:
        streams = board.parse_memory(MEMORY)
        product = board.Product(name="shop", path="/s", workstreams=streams)
        briefs = stub_briefs([product])
        engineering = next(w for w in streams if w.key == "plain-slug")
        briefs[board.stream_id(product, engineering)]["actor"] = "engineering"
        page = render([product], briefs=briefs)
        dispatched = [a for a in launches(page) if not a["ask"] and not a["group"]]
        self.assertEqual([a["text"] for a in dispatched], ["Measure LCP."])
        self.assertTrue(">派工</button>" in page)
        self.assertFalse(dispatched[0]["ask"])
        owner_page = render([product])
        self.assertTrue(all(a["kind"] == "dispatch" for a in launches(owner_page)))
        self.assertIn(("Measure LCP.", True, "白話標題"), [(a["text"], a["ask"], a["title"]) for a in launches(owner_page)])
        # The button explains nothing; the task sits collapsed beside it.
        self.assertFalse("按下後" in owner_page)
        self.assertTrue("交代內容</summary><p class=\"launch-text\" lang=\"en\">" in owner_page)

    def test_a_card_cites_what_its_state_delivered(self) -> None:
        stream = board.Workstream("cited", "Active Workstreams", {
            "state": "Merged (PR #10, `b05fdc5`); synced by `459db8d` and PR #10 again.",
            "ruled out": "An idea from PR #7.", "next": "Measure it.",
        })
        self.assertEqual(board.cited(stream), ["#10", "b05fdc5", "459db8d"])
        # A hash that names no commit here (a transcript id) is not evidence.
        product = board.Product(name="shop", path="/s", workstreams=[stream], commits={"b05fdc5"})
        self.assertEqual(board.evidence(product, stream), ["#10", "b05fdc5"])
        page = render([product])
        self.assertTrue('<span class="lead">證據</span><code>#10</code>、<code>b05fdc5</code></p>' in page)
        self.assertTrue('<p class="shift-label">原本</p><p class="was">原本句。</p>' in page and "影響對象 · 對象" in page)
        self.assertTrue(board.cite(list("abcdef")).endswith('<code>d</code> <span class="nowrap">等 6 筆</span></p>'))

    def test_only_commits_count_as_known_hashes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as repo:
            git = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
            head = subprocess.run([*git, "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip()
            self.assertEqual(board.known_commits(repo, {head, "44dcc0e7"}), {head})

    def test_no_button_without_a_step(self) -> None:
        stream = board.Workstream("bare", "Active Workstreams", {"objective": "Only an objective."})
        product = board.Product(name="shop", path="/s", workstreams=[stream])
        self.assertFalse('class="launch"' in render([product]))

    def test_launch_text_cannot_close_its_script(self) -> None:
        stream = board.Workstream("x", "Active Workstreams", {"next": "Fix </script><script>alert(1)</script>"})
        product = board.Product(name="shop", path="/s", workstreams=[stream])
        page = render([product])
        self.assertFalse("</script><script>alert" in page)
        self.assertTrue(launches(page)[0]["text"].endswith("Fix </script><script>alert(1)</script>"))

    def test_failing_ci_counts_as_stuck(self) -> None:
        failing = {"number": 9, "title": "Break", "url": "https://example.test/9",
                   "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"}]}
        page = render([board.Product(name="ci", path="/c", prs=[failing])])
        self.assertTrue("0 件事輪到你，1 件卡住" in page)
        stuck = page[page.index('id="h-stuck"'):page.index('id="h-products"')]
        self.assertTrue("沒通過自動檢查" in stuck)
        self.assertEqual(
            launches(page),
            [{"kind": "dispatch", "project": "ci", "path": "/c", "key": "", "group": "", "ask": False,
              "text": "Make PR #9 「Break」 (https://example.test/9) pass its checks.", "title": "修好 PR #9 的檢查",
              "entry": ""}],
        )

    def test_empty_owner_queue_explains_itself(self) -> None:
        page = render([board.Product(name="solo", path="/s")])
        self.assertTrue("現在沒有要你決定或動手的事" in page)

    def test_owner_steps_join_decisions_and_leave_stuck(self) -> None:
        streams = board.parse_memory(MEMORY)
        product = board.Product(name="shop", path="/s", workstreams=streams)
        briefs = stub_briefs([product])
        page = render([product], briefs=briefs)
        turns = page[page.index('id="h-turns"'):page.index('id="h-stuck"')]
        stuck = page[page.index('id="h-stuck"'):page.index('id="h-products"')]
        self.assertTrue("卡點句。" in turns and "沒有卡住的事" in stuck)
        self.assertFalse("data-report-meta-token>建議先做" in turns)  # the focus here is a decision card
        briefs[board.product_id(product)]["focus"]["key"] = "plain-slug"
        turns = render([product], briefs=briefs)
        self.assertTrue("data-report-meta-token>建議先做</span>白話標題" in turns)
        self.assertTrue(">輪到你</span>" in page)
        blocked = next(w for w in streams if w.key == "plain-slug")
        briefs[board.stream_id(product, blocked)]["actor"] = "engineering"
        page = render([product], briefs=briefs)
        stuck = page[page.index('id="h-stuck"'):page.index('id="h-products"')]
        self.assertTrue("卡點句。" in stuck and "2 件事輪到你，1 件卡住" in page)

    def test_focus_links_the_card_to_act_on_first(self) -> None:
        streams = board.parse_memory(MEMORY)
        product = board.Product(name="shop", path="/s", workstreams=streams)
        page = render([product], overview=False)
        header = page[:page.index("<main")]
        anchor = f'href="#w-{board.stream_id(product, streams[0])}"'
        self.assertTrue("建議先做" in header and anchor in header and "先做的理由。" in header)
        self.assertTrue(f'id="w-{board.stream_id(product, streams[0])}"' in page)
        overview = render([product, board.Product(name="solo", path="/o")])
        header = overview[:overview.index("<main")]
        self.assertEqual(header.count('class="focus"'), 1)
        self.assertTrue(anchor in header and 'href="#shop"' in header and "各產品建議先做" in header)

    def test_each_project_says_what_shipped_and_how_fresh_its_notes_are(self) -> None:
        shipped = board.Product(name="shop", path="/s", deliveries=[("abc", "Ship it", "2026-09-29")],
                                memory_at=datetime(2026, 9, 25, 20, 8).timestamp(), unrecorded=12)
        quiet = board.Product(name="quiet", path="/q", memory_at=datetime(2026, 9, 29, 8, 0).timestamp())
        page = render([shipped, quiet])
        self.assertTrue("上線標題" in page and "現在句。" in page and "<code>abc</code>" in page)
        self.assertIn('這 7 天<span class="count">沒有更新</span>', page)
        self.assertTrue("09-25 20:08</span>，之後又有 12 次更新沒寫進去" in page)
        self.assertTrue("09-29 08:00</span>，之後沒有新的更新" in page)


def live(key: str, **fields: object) -> dict:
    """A board dispatch record as load_dispatches attaches it."""
    return {"id": f"d-{key}", "kind": "dispatch", "key": key, "state": "done", "live": True, "started": 0, **fields}


class MotionTest(unittest.TestCase):
    """Each workstream is classed by what moves it now, not by the MEMORY section it sits in."""

    def setUp(self) -> None:
        self.streams = [
            board.Workstream("building", "Active Workstreams", {"next": "Ship the card."}),
            board.Workstream("ready", "Active Workstreams", {"next": "Measure LCP."}),
            board.Workstream("vendor", "Active Workstreams", {"next": "Wait for the vendor."}),
            board.Workstream("halted", "Active Workstreams", {"next": "Retry.", "blocker": "Quota."}),
            board.Workstream("silent", "Active Workstreams", {"next": "Finish."}),
        ]
        self.product = board.Product(name="shop", path="/s", workstreams=self.streams, dispatches=[
            live("building", started=datetime(2026, 9, 28, 9).timestamp()),
            live("silent", progress="已經 12 分鐘沒有動靜，切到 Orca 看它是不是在等你。", attention=True),
        ])
        self.briefs = stub_briefs([self.product])
        self.briefs[board.stream_id(self.product, self.streams[2])]["actor"] = "external"
        self.briefs[board.stream_id(self.product, self.streams[3])]["actor"] = "engineering"

    def test_classes_follow_the_dispatch_actor_and_blocker(self) -> None:
        kinds = [board.motion_of(self.product, w, self.briefs) for w in self.streams]
        self.assertEqual(kinds, ["working", "idle", "outside", "stuck", "owner"])
        page = render([self.product], overview=False, briefs=self.briefs)
        self.assertFalse("進行中" in page)
        self.assertTrue("1 條有 agent 在做，1 條可以派工但沒人在做" in page)
        table = page[page.index('class="table-wrap motion"'):page.index('<ul class="streams">')]
        order = [table.index(label) for label in ("輪到你", "卡住", "可以派工，沒人在做", "agent 在做", "等外部或實際使用")]
        self.assertEqual(order, sorted(order))
        self.assertTrue(">1 天<" in table and ">今天<" not in table.split("agent 在做")[0])

    def test_a_blocker_that_only_waits_outside_is_waiting_not_stuck(self) -> None:
        halted = self.streams[3]
        self.briefs[board.stream_id(self.product, halted)]["actor"] = "external"
        self.assertEqual(board.motion_of(self.product, halted, self.briefs), "outside")
        self.assertEqual(board.counts([self.product], self.briefs)[2], 0)

    def test_an_agent_whose_own_entry_now_hands_the_step_to_the_owner_waits_on_them(self) -> None:
        ready = self.streams[1]
        sid = board.stream_id(self.product, ready)
        self.briefs[sid]["actor"] = "you"
        # Launched against this very entry: the agent is working, whatever the brief says now.
        self.product.dispatches.append(live("ready", entry=sid))
        self.assertEqual(board.motion_of(self.product, ready, self.briefs), "working")
        # Its entry changed after launch and now names the owner: the agent waits on them.
        self.product.dispatches[-1]["entry"] = "older-entry"
        self.assertEqual(board.motion_of(self.product, ready, self.briefs), "owner")
        page = render([self.product], overview=False, briefs=self.briefs)
        self.assertTrue("派出的 agent 在等你" in page[page.index('id="h-turns"'):page.index('id="h-stuck"')])
        # A focus card that is dispatched shows where its agent stands.
        self.briefs[board.product_id(self.product)]["focus"] = {"key": "ready", "why": "理由。"}
        header = render([self.product], overview=False, briefs=self.briefs).split("<main")[0]
        self.assertTrue(">輪到你</span>" in header)

    def test_a_dispatch_that_needs_the_owner_joins_their_queue(self) -> None:
        page = render([self.product], overview=False, briefs=self.briefs)
        turns = page[page.index('id="h-turns"'):page.index('id="h-stuck"')]
        self.assertTrue("已經 12 分鐘沒有動靜" in turns)
        self.assertEqual(board.counts([self.product], self.briefs)[0], 1)

    def test_a_dead_launchers_record_is_not_an_agent_at_work(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            saved = board.BOARD_DIR
            board.BOARD_DIR = Path(tmp)
            try:
                ledger = {"r1": {"kind": "dispatch", "repo": "/s", "key": "ready", "state": "running", "pid": 2**22 + 7},
                          "r2": {"kind": "dispatch", "repo": "/s", "key": "vendor", "state": "running", "pid": os.getpid()}}
                Path(tmp, "launches.json").write_text(json.dumps(ledger), encoding="utf-8")
                board.load_dispatches([self.product])
            finally:
                board.BOARD_DIR = saved
        self.assertEqual({d["key"]: d["live"] for d in self.product.dispatches}, {"ready": False, "vendor": True})

    def test_a_decision_with_a_blocker_whose_agent_needs_the_owner_renders(self) -> None:
        product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY),
                                dispatches=[live("decided-and-blocked", progress="agent 已經結束。", attention=True)])
        page = render([product], overview=False)
        turns = page[page.index('id="h-turns"'):page.index('id="h-stuck"')]
        self.assertTrue("agent 已經結束。" in turns)

    def test_a_chosen_decision_leaves_the_owner_queue(self) -> None:
        product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY))
        self.assertEqual(len(product.decisions), 2)
        product.dispatches = [live("github:owner/repo#12")]
        self.assertEqual([w.key for w in product.decisions], ["decided-and-blocked"])

    def test_moved_reads_dispatches_notes_and_past_dates_only(self) -> None:
        today = date(2026, 9, 30)
        stream = board.Workstream("x", "Active", {"state": "Seen 2026-09-20; due 2026-10-15; bad 2026-02-31."})
        product = board.Product(name="shop", path="/s", workstreams=[stream])
        self.assertEqual(board.moved_on(product, stream, today), date(2026, 9, 20))
        product.dispatches = [live("x", started=datetime(2026, 9, 25, 9).timestamp())]
        self.assertEqual(board.moved_on(product, stream, today), date(2026, 9, 25))
        product.visit = {"streams": {"x": {"fields": {"state": "older"}, "moved": "2026-09-01"}}}
        product.memory_at = datetime(2026, 9, 29, 9).timestamp()
        self.assertEqual(board.moved_on(product, stream, today), date(2026, 9, 29))
        # Once seen, a date in the notes that arrives is not movement; only a change or a dispatch is.
        product.dispatches = []
        product.visit["streams"]["x"] = {"fields": board.tracked(stream), "moved": "2026-09-01"}
        self.assertEqual(board.moved_on(product, stream, today), date(2026, 9, 1))
        self.assertEqual(board.days_since(None, today), "—")


class SinceTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saved = board.BOARD_DIR
        board.BOARD_DIR = Path(tmp.name)
        self.addCleanup(setattr, board, "BOARD_DIR", saved)
        self.product = board.Product(name="shop", path="/s", memory_read=True, workstreams=board.parse_memory(MEMORY))

    def test_the_first_visit_marks_nothing_and_the_next_names_changed_fields(self) -> None:
        first = render([self.product], overview=False)
        self.assertTrue("從這次開始記下你看過的內容" in first and "你上次看之後改了" not in first)
        board.record_visit(self.product, datetime(2026, 9, 29, 9, 0))
        self.product.visit = board.load_visit(self.product)
        self.product.workstreams[1].fields["next"] = "Measure INP."
        self.product.workstreams.append(board.Workstream("fresh", "Active Workstreams", {"next": "Start."}))
        page = render([self.product], overview=False)
        since = page[page.index('id="h-since"'):page.index('id="h-turns"')]
        self.assertTrue("上次看是 <span data-report-meta-token>09-29 09:00</span>" in since)
        self.assertTrue("改了下一步" in since and "新增的工作" in since)
        self.assertEqual(since.count('class="changed-row"'), 2)
        self.assertTrue("你上次看之後改了下一步" in page and "你上次看之後新增" in page)

    def test_a_finished_dispatch_reports_what_its_agent_left(self) -> None:
        import tempfile

        worktree = tempfile.TemporaryDirectory()
        gone = {"state": "done", "kind": "dispatch", "repo": "/s", "key": "plain-slug", "worktree": "plain-slug-0929-0900",
                "path": str(Path(worktree.name, "wt")), "started": datetime(2026, 9, 29, 8).timestamp()}
        (board.BOARD_DIR / "launches.json").write_text(json.dumps({"r1": gone}), encoding="utf-8")
        board.load_dispatches([self.product])
        self.product.visit = {"at": datetime(2026, 9, 29, 7).timestamp(), "streams": {}, "inflight": []}
        self.product.memory_at = datetime(2026, 9, 29, 10).timestamp()
        # Its PR is found by the worktree name Orca puts at the end of the branch.
        with unittest.mock.patch.object(board, "run", return_value=json.dumps([
            {"number": 3, "title": "fix: measure", "body": "Done.", "state": "MERGED", "headRefName": "me/plain-slug-0929-0900"},
            {"number": 4, "title": "other", "body": "", "state": "OPEN", "headRefName": "me/other"},
        ])):
            self.product.remote = True
            board.read_receipts(self.product, datetime(2026, 9, 29, 12))
        worktree.cleanup()
        receipt = self.product.receipts[0]
        # The receipt keeps its id when the brief cache forgets the closed card's title.
        facts = {k: v for k, v in receipt.items() if k not in ("id", "kind", "project", "card_title")}
        self.assertEqual(receipt["id"], board.digest([self.product.path, "r1", facts]))
        self.assertEqual((receipt["pr"]["title"], receipt["notes_written"]), ("fix: measure", True))
        self.assertEqual(receipt["notes"]["next"], "Measure LCP.")
        self.assertEqual(receipt["report"], "no report: the receiver wrote none")
        request = next(r for r in board.brief_requests(self.product) if r["kind"] == "receipt")
        self.assertEqual(board.brief_errors(request, {"title": "t"}), ["missing did"])
        briefs = {**stub_briefs([board.Product(name="shop", path="/s", workstreams=self.product.workstreams)]),
                  receipt["id"]: {"title": "量測頁面速度", "did": "agent 量好了速度並合併。"}}
        page = render([self.product], overview=False, briefs=briefs)
        since = page[page.index('id="h-since"'):page.index('id="h-turns"')]
        self.assertTrue("派工結束" in since and "agent 量好了速度並合併。" in since and "fix: measure" not in page)

    def test_a_receivers_receipt_file_is_its_report(self) -> None:
        gone = {"state": "done", "kind": "dispatch", "repo": "/s", "key": "plain-slug", "worktree": "plain-slug-0929-0900",
                "path": "/gone/plain-slug-0929-0900", "started": datetime(2026, 9, 29, 8).timestamp()}
        (board.BOARD_DIR / "launches.json").write_text(json.dumps({"r1": gone}), encoding="utf-8")
        receipt = board.receipt_path("r1")
        receipt.parent.mkdir(parents=True)
        receipt.write_text("關掉 1 張票、開了 1 張新票；不需要 PR。", encoding="utf-8")
        board.load_dispatches([self.product])
        self.product.visit = {"at": datetime(2026, 9, 29, 7).timestamp(), "streams": {}, "inflight": []}
        board.read_receipts(self.product, datetime(2026, 9, 29, 12))
        self.assertEqual((self.product.receipts[0]["pr"], self.product.receipts[0]["report"]),
                         (None, "關掉 1 張票、開了 1 張新票；不需要 PR。"))

    def test_a_merged_dispatch_not_live_here_is_not_reported_as_finished(self) -> None:
        self.product.receipts = [{"id": "r-late", "kind": "receipt", "project": "shop", "notes_written": True, "live": False}]
        briefs = {**stub_briefs([board.Product(name="shop", path="/s", workstreams=self.product.workstreams)]),
                  "r-late": {"title": "量測頁面速度", "did": "agent 量好了速度並合併。"}}
        page = render([self.product], overview=False, briefs=briefs)
        since = page[page.index('id="h-since"'):page.index('id="h-turns"')]
        self.assertTrue("已合併，還沒生效" in since and "派工結束" not in since)

    def test_a_finished_upkeep_run_reports_what_its_agent_said(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "notes-refresh-0929-0900.json")
            log.write_text(json.dumps({"type": "result", "is_error": False, "result": "筆記已更新。"}), encoding="utf-8")
            run = {"state": "done", "kind": "dispatch", "repo": "/s", "key": "notes-refresh", "log": str(log),
                   "agent_pid": 2**22 + 7, "started": datetime(2026, 9, 29, 8).timestamp()}
            (board.BOARD_DIR / "launches.json").write_text(json.dumps({"u1": run}), encoding="utf-8")
            board.load_dispatches([self.product])
            self.assertFalse(self.product.dispatches[0]["live"])
            self.product.visit = {"at": datetime(2026, 9, 29, 7).timestamp(), "streams": {}, "inflight": []}
            board.read_receipts(self.product, datetime(2026, 9, 29, 12))
        receipt = self.product.receipts[0]
        self.assertEqual((receipt["chore"], receipt["report"]), ("更新筆記", "筆記已更新。"))

    def test_a_dispatch_seen_finished_is_not_reported_again(self) -> None:
        started = datetime(2026, 9, 29, 8).timestamp()
        self.product.dispatches = [live("x", live=False, path="/gone", started=started)]
        self.product.visit = {"at": started + 60, "streams": {}, "inflight": []}
        self.assertEqual(board.finished_since(self.product, datetime(2026, 9, 29, 12)), [])
        self.product.visit["inflight"] = ["d-x"]
        self.assertEqual(len(board.finished_since(self.product, datetime(2026, 9, 29, 12))), 1)


class DecisionContractTest(unittest.TestCase):
    def test_a_decision_written_under_older_rules_is_written_again_once(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(board, "BOARD_DIR", Path(tmp)):
            product = board.Product(name="shop", path="/s", memory_read=True, workstreams=board.parse_memory(MEMORY))
            requests = board.brief_requests(product)
            decide = next(r for r in requests if r.get("status") == "decide")
            stored = {r["id"]: {**stub_brief(r), "_key": r["key"]} if "key" in r else stub_brief(r) for r in requests}
            board.save_briefs(product, stored)
            briefs, _ = board.apply_briefs([product], {})
            self.assertNotIn(decide["id"], briefs)
            self.assertIn(next(r["id"] for r in requests if r.get("status") == "stuck"), briefs)
            briefs, errors = board.apply_briefs([product], {decide["id"]: stub_brief(decide)})
            self.assertEqual((errors, decide["id"] in briefs), ([], True))
            self.assertIn(decide["id"], board.apply_briefs([product], {})[0])


class FocusTest(unittest.TestCase):
    def test_each_card_offers_its_own_step_and_nothing_beside_it(self) -> None:
        # Dropping work is said in a session, where `handoff` removes the entry; the page carries no second action.
        page = render([board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY))], overview=False)
        self.assertFalse("不做了" in page or 'class="launch drop"' in page)


class UpkeepTest(unittest.TestCase):
    def test_stale_notes_and_leftovers_each_offer_a_dispatch(self) -> None:
        product = board.Product(name="shop", path="/s", unrecorded=3, worktrees=["/wt/a", "/wt/held"],
                                loose_branches=["stale"], memory_at=datetime(2026, 9, 29, 9).timestamp(),
                                dispatches=[live("x", path="/wt/held")])
        self.assertEqual(board.leftovers(product), ["/wt/a", "stale"])
        actions = launches(render([product], overview=False))
        self.assertEqual([(a["key"], a["ask"]) for a in actions], [("notes-refresh", False), ("leftover-cleanup", False)])
        self.assertIn(str(Path(board.__file__).resolve().parents[1] / "references/refresh.md"), actions[0]["text"])
        self.assertIn("in /s", actions[0]["text"])
        self.assertIn("2026-09-29 09:00", actions[0]["text"])
        # Each names its evidence, so the same count after a finished run is a new action, not the old record.
        self.assertTrue("audit /wt/a, stale," in actions[1]["text"])
        page = render([product], overview=False)
        self.assertLess(page.index(">更新筆記<"), page.index('id="h-since"'))
        quiet = render([board.Product(name="shop", path="/s")], overview=False)
        self.assertFalse('class="launch"' in quiet)

    def test_merged_work_not_live_here_says_so_and_offers_the_sync(self) -> None:
        product = board.Product(name="shop", path="/s", behind=2, memory_at=datetime(2026, 9, 29, 9).timestamp())
        page = render([product], overview=False)
        self.assertTrue("還少了 2 個已合併的更新，這些改動在這台電腦還沒生效" in page)
        actions = launches(page)
        self.assertEqual([a["key"] for a in actions], ["notes-refresh"])
        self.assertTrue("local main lacks 2 merged commits; MEMORY.md, written 2026-09-29 09:00, may miss" in actions[0]["text"])

    def test_a_refresh_that_wrote_the_notes_offers_the_button_again(self) -> None:
        def refresh(hour: int) -> dict:
            product = board.Product(name="shop", path="/s", memory_read=True, memory_at=datetime(2026, 9, 29, hour).timestamp())
            return next(a for a in launches(render([product], overview=False)) if a["key"] == "notes-refresh")

        self.assertNotEqual(refresh(9)["text"], refresh(10)["text"])

    def test_items_outside_any_entry_are_named_and_handed_to_the_refresh(self) -> None:
        text = (
            "## Current State\n\n- main at abc.\n\n## Active Workstreams\n\n- A loose line before any entry.\n\n"
            "### `x`\n\n- **Next:** Do it.\n\n## Follow-ups\n\n- Codex sandbox block: the owner's choice.\n"
            "  continued line\n- Playwright roots.\n\n## Standing Context\n\n- Never force-push main.\n\n"
            "## Durable Pointers\n\n- `docs/`\n\n```\n- fenced, not an item\n```\n"
        )
        self.assertEqual(board.loose_items(text), {"Active Workstreams": 1, "Follow-ups": 2})
        # Every list marker counts, before the first section too; a fenced example of any fence does not.
        edges = ("- Before any section.\n\n## Open Questions\n\n1. Which plan?\n+ Who owns it?\n\n"
                 "~~~\n- tilde fenced\n~~~\n\n````\n```\n- still fenced\n````\n")
        self.assertEqual(board.loose_items(edges), {"檔案開頭": 1, "Open Questions": 2})
        self.assertEqual([w.key for w in board.parse_memory("## Active\n\n~~~\n### not-an-entry\n~~~\n### `x`\n")], ["x"])
        product = board.Product(name="shop", path="/s", memory_read=True, loose=board.loose_items(text))
        page = render([product], overview=False)
        self.assertTrue("筆記裡有些事寫在工作條目以外（「Active Workstreams」1 條、「Follow-ups」2 條），不會變成卡片" in page)
        refresh = next(a for a in launches(page) if a["key"] == "notes-refresh")
        self.assertTrue("items outside any entry under Active Workstreams, Follow-ups" in refresh["text"])


class BriefTest(unittest.TestCase):
    def setUp(self) -> None:
        self.product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY))
        self.requests = {r.get("key", "product"): r for r in board.brief_requests(self.product)}

    def test_ids_follow_the_source_text(self) -> None:
        stream = self.product.workstreams[0]
        before = board.stream_id(self.product, stream)
        self.assertEqual(before, board.stream_id(self.product, stream))
        stream.fields["state"] = "Frontend done too."
        self.assertNotEqual(before, board.stream_id(self.product, stream))

    def test_requests_carry_status(self) -> None:
        statuses = {key: r.get("status") for key, r in self.requests.items()}
        self.assertEqual(statuses["github:owner/repo#12"], "decide")
        self.assertEqual(statuses["plain-slug"], "stuck")
        self.assertEqual(statuses["workstream:vendor-reply"], "waiting")
        self.assertEqual(self.requests["product"]["kind"], "product")

    def test_brief_errors_name_what_is_missing(self) -> None:
        stuck = self.requests["plain-slug"]
        decide = self.requests["github:owner/repo#12"]
        self.assertEqual(board.brief_errors(stuck, stub_brief(stuck)), [])
        self.assertEqual(board.brief_errors(decide, stub_brief(decide)), [])
        self.assertIn("missing stuck", board.brief_errors(stuck, {**stub_brief(stuck), "stuck": ""}))
        self.assertIn("a decision's actor is you", board.brief_errors(decide, {**stub_brief(decide), "actor": "external"}))
        self.assertIn(
            "actor must be one of you, engineering, external",
            board.brief_errors(stuck, {**stub_brief(stuck), "actor": "owner"}),
        )
        bad = stub_brief(decide)
        bad["decision"]["options"][1]["reversible"] = "yes"
        bad["decision"]["recommended"] = 5
        errors = board.brief_errors(decide, bad)
        self.assertIn("decision.options[1].reversible must be true or false", errors)
        self.assertIn("decision.recommended must index an option or be null", errors)
        self.assertEqual(board.brief_errors(decide, {"title": "t"})[:1], ["missing who"])

    def test_the_owners_priority_orders_the_cards_and_fixes_the_focus(self) -> None:
        import tempfile

        text = (
            "## Active Workstreams\n\n### first-in-file\n\n- Next: a.\n\n"
            "### second-pick\n\n- Next: b.\n- Priority: 2 (owner, 2026-10-01)\n\n"
            "### first-pick\n\n- Next: c.\n- **Priority:** 1 (owner, 2026-10-01)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "MEMORY.md").write_text(text, encoding="utf-8")
            product = board.collect("shop", tmp)
        self.assertEqual([w.key for w in product.workstreams], ["first-pick", "second-pick", "first-in-file"])
        request = board.brief_requests(product)[-1]
        self.assertEqual(board.brief_errors(request, stub_brief(request)), [])
        self.assertEqual(
            board.brief_errors(request, {"summary": "s", "focus": {"key": "first-in-file", "why": "w"}}),
            ["focus must be first-pick, the owner's first priority"],
        )

    def test_project_brief_needs_shipped_and_a_focus_from_its_own_cards(self) -> None:
        product = board.Product(name="shop", path="/s", workstreams=board.parse_memory(MEMORY),
                                deliveries=[("abc", "Ship it", "2026-09-29")])
        request = board.brief_requests(product)[-1]
        self.assertEqual(board.brief_errors(request, stub_brief(request)), [])
        self.assertEqual(
            board.brief_errors(request, {"summary": "s", "focus": {"key": "elsewhere", "why": "w"}}),
            ["shipped needs 1 to 5 outcomes", "focus needs a workstream key from this project and a why"],
        )
        outcome = {"title": "t", "stage": "已部署", "before": "b", "after": "a", "commits": ["zzz"]}
        self.assertEqual(
            board.brief_errors(request, {**stub_brief(request), "shipped": [outcome]}),
            ["shipped[0].stage must be one of 已合併, 已上線", "shipped[0].commits must list this week's commits it covers"],
        )
        empty = board.brief_requests(board.Product(name="new", path="/n"))[-1]
        self.assertEqual(board.brief_errors(empty, {"summary": "s"}), [])

    def test_cache_survives_an_unreadable_memory_and_drops_malformed_entries(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            saved = board.BOARD_DIR
            board.BOARD_DIR = Path(tmp)
            try:
                self.product.memory_read = True
                briefs = stub_briefs([self.product])
                board.apply_briefs([self.product], briefs)
                unread = board.Product(name="renamed", path="/s")
                other = board.Product(name="other", path="/o", memory_read=True)
                board.apply_briefs([unread, other], stub_briefs([other]))
                self.assertEqual(set(board.load_briefs(self.product)), set(briefs))

                stored = board.load_briefs(self.product)
                broken = next(rid for rid, b in stored.items() if "title" in b)
                stored[broken] = {}
                board.save_briefs(self.product, stored)
                merged, errors = board.apply_briefs([self.product], {})
                self.assertEqual(errors, [])
                self.assertNotIn(broken, merged)
            finally:
                board.BOARD_DIR = saved

    def test_main_asks_for_briefs_then_renders_and_prunes(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            saved = board.BOARD_DIR, board.current_repo, board.collect
            board.BOARD_DIR = tmp_path
            board.current_repo = lambda cwd: ("shop", "/s")
            board.collect = lambda name, path: self.product
            try:
                out = tmp_path / "shop.html"
                self.assertEqual(board.main(["--out", str(out)]), 3)
                pending = json.loads(out.with_suffix(".pending.json").read_text(encoding="utf-8"))
                self.assertEqual(len(pending["items"]), len(self.requests))
                self.assertFalse(out.exists())

                supplied = tmp_path / "briefs.json"
                briefs = {r["id"]: stub_brief(r) for r in pending["items"]}
                self.product.memory_read = True
                supplied.write_text(json.dumps({**briefs, "stale": {"summary": "x"}}), encoding="utf-8")
                self.assertEqual(board.main(["--out", str(out), "--briefs", str(supplied)]), 0)
                self.assertTrue(out.exists())
                self.assertFalse(out.with_suffix(".pending.json").exists())
                self.assertEqual(set(board.load_briefs(self.product)), set(briefs))

                # Cached briefs render without the agent; only a changed workstream is asked again.
                self.assertEqual(board.main(["--out", str(out)]), 0)
                self.product.workstreams[0].fields["state"] = "Changed."
                self.assertEqual(board.main(["--out", str(out)]), 3)
                pending = json.loads(out.with_suffix(".pending.json").read_text(encoding="utf-8"))
                self.assertEqual([r.get("key") for r in pending["items"]], ["github:owner/repo#12", None])
                # The rewrite sees the card's last brief so its title can stay put.
                self.assertEqual(pending["items"][0]["previous"]["title"], "白話標題")
                self.assertNotIn("_key", pending["items"][0]["previous"])

                supplied.write_text(json.dumps({pending["items"][0]["id"]: {"title": "t"}}), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    board.main(["--out", str(out), "--briefs", str(supplied)])
            finally:
                board.BOARD_DIR, board.current_repo, board.collect = saved


if __name__ == "__main__":
    unittest.main()


LONG_HORIZON = """## Current State

- Stale: `workstream:vendor-reply` — its Blocker names a vendor that already answered.

## Active Workstreams

### plain-slug

- Objective: Faster page loads.
- Next: Measure LCP.

### plain-slug

- Objective: A second entry under the same key.

## Waiting on Decisions or External Evidence

### `workstream:vendor-reply`

- Objective: Vendor confirms the quota.
- Next: Read the reply.

### `program:long-horizon`

Ticket states rechecked 09-28 23:40; product prerequisites are retained context.

- **ENG-1901 (In Progress), Example Owner:** decide D0, then two lineage audits.
- **ENG-1807 (In Progress), Example Owner:** reconcile ENG-1815, then choose ENG-1813 or ENG-1843.
- **Removal:** drop each line when closed with evidence.

## Deferred Workstreams

### `linear:example-org/example-api:ENG-2108`

- **Waiting on:** Example Owner's approval of a fresh repair proposal.
- **Decision:** Approve the proposal? Recommend yes (reversible).

### `linear:example-org/example-api:ENG-2041`

- **Blocker:** Support has not confirmed the member still needs access.
- **Next:** Resume when support confirms.
"""


class CompletenessTest(unittest.TestCase):
    """Every entry reaches the page; what the board cannot read shows instead of vanishing."""

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, "MEMORY.md").write_text(LONG_HORIZON, encoding="utf-8")
        with unittest.mock.patch.object(board, "run", side_effect=RuntimeError("no git")):
            self.product = board.collect("shop", self.tmp.name)
        self.briefs = stub_briefs([self.product])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_duplicate_keys_show_an_error_and_keep_one_card(self) -> None:
        keys = [w.key for w in self.product.workstreams]
        self.assertEqual(keys.count("plain-slug"), 1)
        self.assertTrue(any("同名的工作「plain-slug」" in e for e in self.product.errors))

    def test_unread_lines_and_missing_next_are_flagged(self) -> None:
        program = next(w for w in self.product.workstreams if w.key == "program:long-horizon")
        self.assertEqual(program.unread, 3)
        page = render([self.product], overview=False, briefs=self.briefs)
        card = page[page.index(f'id="w-{board.stream_id(self.product, program)}"'):]
        self.assertTrue("筆記沒寫下一步；筆記有 3 行讀不到，按「更新筆記」整理。" in card[:card.index("</li>")])

    def test_a_stale_entry_is_marked_on_its_card(self) -> None:
        self.assertEqual(self.product.stale, {"workstream:vendor-reply"})
        vendor = next(w for w in self.product.workstreams if w.key == "workstream:vendor-reply")
        page = render([self.product], overview=False, briefs=self.briefs)
        card = page[page.index(f'id="w-{board.stream_id(self.product, vendor)}"'):]
        self.assertTrue("筆記可能過時" in card[:card.index("</li>")])

    def test_deferred_entries_stay_out_of_every_queue_and_button(self) -> None:
        deferred = next(w for w in self.product.workstreams if w.deferred)
        self.assertEqual(board.status_of(deferred), "deferred")
        self.briefs[board.stream_id(self.product, deferred)]["actor"] = "you"
        self.assertEqual(self.product.decisions, [])
        self.assertEqual(board.motion_of(self.product, deferred, self.briefs), "deferred")
        page = render([self.product], overview=False, briefs=self.briefs)
        self.assertFalse(any(a["key"] == deferred.key for a in launches(page)))
        self.assertTrue(">暫緩<" in page and board.counts([self.product], self.briefs) == (0, 0, 0))
        request = board.brief_requests(self.product)[len(self.product.workstreams)]
        self.assertIn("focus needs a workstream key from this project and a why",
                      board.brief_errors(request, {"summary": "s", "focus": {"key": deferred.key, "why": "w"}}))

    def test_the_notes_refresh_is_always_offered(self) -> None:
        page = render([self.product], overview=False, briefs=self.briefs)
        refresh = [a for a in launches(page) if a["key"] == "notes-refresh"]
        self.assertEqual(len(refresh), 1)
        self.assertTrue("program:long-horizon" in refresh[0]["text"])


class ErrorsTest(unittest.TestCase):
    def test_a_launcher_error_is_reported_by_the_next_run_once(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(board, "ERRORS", Path(tmp, "errors.log")):
            board.ERRORS.write_text("2026-09-30 15:02:31 example-api /state: KeyError: 'path'\n", encoding="utf-8")
            self.assertEqual(board.take_errors(), ["2026-09-30 15:02:31 example-api /state: KeyError: 'path'"])
            self.assertEqual(board.take_errors(), [])


class UntilTest(unittest.TestCase):
    def test_a_brief_waiting_on_a_passed_date_is_rewritten(self) -> None:
        today = date(2026, 9, 30)
        self.assertTrue(board.expired({"until": "2026-09-29"}, today))
        self.assertFalse(board.expired({"until": "2026-09-30"}, today) or board.expired({}, today))
        request = {"kind": "workstream", "status": "waiting"}
        self.assertIn("until must be a YYYY-MM-DD date", board.brief_errors(request, {**stub_brief(request), "until": "soon"}))
