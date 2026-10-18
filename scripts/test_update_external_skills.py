import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import update_external_skills as updater
import validate_skills


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def skill_md(name: str, body: str = "Body.\n", gate: bool = False) -> str:
    extra = "disable-model-invocation: true\n" if gate else ""
    return f"---\nname: {name}\ndescription: {name} skill for tests.\n{extra}---\n\n{body}"


class Fixture:
    """An upstream Matt-style repo and a local skills repo synced to its first commit."""

    def __init__(self, root: Path):
        self.upstream = root / "upstream"
        self.local = root / "local"
        for repo in (self.upstream, self.local):
            repo.mkdir()
            sh(repo, "git", "init", "-q", "-b", "main")
            sh(repo, "git", "config", "user.email", "test@example.com")
            sh(repo, "git", "config", "user.name", "Test")
        self.skills: dict[str, dict[str, str]] = {}

    def upstream_commit(self, skills: dict[str, dict[str, str]]) -> str:
        for path in self.upstream.glob("skills/*"):
            subprocess.run(["rm", "-rf", str(path)], check=True)
        for name, files in skills.items():
            for rel, text in files.items():
                target = self.upstream / "skills/engineering" / name / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        plugin = self.upstream / ".claude-plugin/plugin.json"
        plugin.parent.mkdir(exist_ok=True)
        plugin.write_text(json.dumps({"skills": [f"./skills/engineering/{n}" for n in sorted(skills)]}))
        sh(self.upstream, "git", "add", "-A")
        sh(self.upstream, "git", "commit", "-q", "-m", "upstream")
        return sh(self.upstream, "git", "rev-parse", "HEAD").strip()

    def local_commit(self, skills: dict[str, dict[str, str]], commit: str) -> None:
        for name, files in skills.items():
            for rel, text in files.items():
                target = self.local / "skills" / name / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        manifest = {
            "skills_cli": "skills@0",
            "matt": {"repo": str(self.upstream), "commit": commit, "exclude": {"handoff": "ours"}},
        }
        (self.local / updater.MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
        sh(self.local, "git", "add", "-A")
        sh(self.local, "git", "commit", "-q", "-m", "local")

    def read(self, name: str, rel: str = "SKILL.md") -> str:
        return (self.local / "skills" / name / rel).read_text()

    def run(self) -> tuple[int, dict]:
        out = tempfile.TemporaryFile("w+")
        import contextlib

        with contextlib.redirect_stdout(out):
            code = updater.main(["--repo", str(self.local), "--skip-lock", "--commit"])
        out.seek(0)
        return code, json.loads(out.read())


GATE = "policy:\n  allow_implicit_invocation: true\n"


class MattSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        if not validate_skills.DEFAULT_VALIDATOR.is_file():
            self.skipTest("skill-creator validator not installed")
        self.fx = Fixture(Path(tempfile.mkdtemp()))
        self.old = self.fx.upstream_commit(
            {
                "tdd": {"SKILL.md": skill_md("tdd", "one\ntwo\nthree\nfour\nfive\n")},
                "pr": {"SKILL.md": skill_md("pr")},
                "retro": {"SKILL.md": skill_md("retro")},
                "handoff": {"SKILL.md": skill_md("handoff")},
            }
        )

    def sync_local(self, tdd_body: str = "one\ntwo\nthree\nfour\nfive\n", pr_body: str = "Body.\n") -> None:
        self.fx.local_commit(
            {
                "tdd": {"SKILL.md": skill_md("tdd", tdd_body), updater.LOCAL_GATE: GATE},
                "pr": {"SKILL.md": skill_md("pr", pr_body), updater.LOCAL_GATE: GATE},
                "retro": {"SKILL.md": skill_md("retro"), updater.LOCAL_GATE: GATE},
                "handoff": {"SKILL.md": skill_md("handoff", "Our own handoff.\n")},
            },
            self.old,
        )

    def test_unchanged_upstream_is_a_no_op(self) -> None:
        self.sync_local()
        code, report = self.fx.run()
        self.assertEqual(code, 0)
        self.assertIsNone(report["commit"])
        self.assertEqual(report["matt"]["old"], report["matt"]["new"])

    def test_clean_update_merge_add_and_remove_land_in_one_commit(self) -> None:
        self.sync_local(tdd_body="one\ntwo\nthree\nfour\nfive LOCAL\n")
        new = self.fx.upstream_commit(
            {
                "tdd": {"SKILL.md": skill_md("tdd", "ONE\ntwo\nthree\nfour\nfive\n")},
                "pr": {"SKILL.md": skill_md("pr", "New body.\n")},
                "wizard": {"SKILL.md": skill_md("wizard", gate=True)},
                "handoff": {"SKILL.md": skill_md("handoff", "Upstream handoff v2.\n")},
            }
        )
        code, report = self.fx.run()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["matt"]["updated"], ["pr"])
        self.assertEqual(report["matt"]["merged"], ["tdd"])
        self.assertEqual(report["matt"]["added"], ["wizard"])
        self.assertEqual(report["matt"]["removed"], ["retro"])
        self.assertIn("ONE", self.fx.read("tdd"))
        self.assertIn("five LOCAL", self.fx.read("tdd"))
        self.assertEqual(self.fx.read("pr", updater.LOCAL_GATE), GATE)
        self.assertIn("allow_implicit_invocation: false", self.fx.read("wizard", updater.LOCAL_GATE))
        self.assertIn("Our own handoff", self.fx.read("handoff"))
        self.assertFalse((self.fx.local / "skills/retro").exists())
        manifest = json.loads((self.fx.local / updater.MANIFEST).read_text())
        self.assertEqual(manifest["matt"]["commit"], new)
        self.assertEqual(sh(self.fx.local, "git", "status", "--porcelain"), "")
        self.assertIsNotNone(report["commit"])

    def test_conflict_keeps_local_copy_and_holds_the_recorded_commit(self) -> None:
        self.sync_local(pr_body="Local body.\n")
        self.fx.upstream_commit(
            {
                "tdd": {"SKILL.md": skill_md("tdd", "one\ntwo\nthree\nfour\nfive\n")},
                "pr": {"SKILL.md": skill_md("pr", "Upstream body.\n")},
                "retro": {"SKILL.md": skill_md("retro")},
            }
        )
        code, report = self.fx.run()
        self.assertEqual(code, 1)
        self.assertIn("matt: pr conflicts in SKILL.md", report["needs_human"])
        self.assertIn("Local body.", self.fx.read("pr"))
        self.assertIsNone(report["commit"])
        manifest = json.loads((self.fx.local / updater.MANIFEST).read_text())
        self.assertEqual(manifest["matt"]["commit"], self.old)

    def test_dirty_skills_stop_before_any_change(self) -> None:
        self.sync_local()
        (self.fx.local / "skills/pr/SKILL.md").write_text("edited\n")
        code, report = self.fx.run()
        self.assertEqual(code, 2)
        self.assertEqual(report["paths"], ["skills/pr/SKILL.md"])


class ImpeccableAgentTests(unittest.TestCase):
    def test_subagents_land_in_the_repository_when_the_skill_matches_upstream(self) -> None:
        fx = Fixture(Path(tempfile.mkdtemp()))
        for skill in (fx.upstream / ".agents/skills/impeccable", fx.local / "skills/impeccable"):
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(skill_md("impeccable"))
        agent = fx.upstream / ".claude/agents/impeccable-documenter.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("agent\n")
        sh(fx.upstream, "git", "add", "-A")
        sh(fx.upstream, "git", "commit", "-q", "-m", "release")
        config = {
            "repo": fx.upstream.as_uri(),
            "skill": "impeccable",
            "upstream_skill_path": ".agents/skills/impeccable",
            "upstream_agents_path": ".claude/agents",
            "target": "claude/agents",
        }
        report = updater.Report()
        updater.sync_impeccable_agents(fx.local, config, report, Path(tempfile.mkdtemp()))
        self.assertEqual(report.impeccable_agents, {"status": "synced", "copied": ["impeccable-documenter.md"]})
        self.assertEqual((fx.local / "claude/agents/impeccable-documenter.md").read_text(), "agent\n")
        self.assertIn("claude/agents/impeccable-documenter.md", updater.dirty_paths(fx.local))


class LocalGateTests(unittest.TestCase):
    def test_gate_deleted_by_a_lock_update_is_restored(self) -> None:
        fx = Fixture(Path(tempfile.mkdtemp()))
        fx.local_commit({"ai-seo": {"SKILL.md": skill_md("ai-seo"), updater.LOCAL_GATE: GATE}}, "x")
        (fx.local / "skills/ai-seo" / updater.LOCAL_GATE).unlink()
        report = updater.Report()
        updater.restore_local_gates(fx.local, report)
        self.assertEqual(report.gates_restored, ["skills/ai-seo/agents/openai.yaml"])
        self.assertEqual(fx.read("ai-seo", updater.LOCAL_GATE), GATE)


if __name__ == "__main__":
    unittest.main()
