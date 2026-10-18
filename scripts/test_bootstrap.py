import subprocess
import tempfile
import unittest
from pathlib import Path

import bootstrap
import tomlkit

BASE = """model = "gpt-6.1-sol"
forced_login_method = "chatgpt"

[features]
hooks = true

[[skills.config]]
path = "{HOME}/.agents/skills/teach/SKILL.md"
enabled = false

[mcp_servers.refero]
url = "https://api.refero.design/mcp"
"""

LIVE = """# Codex-owned comment
model = "gpt-5"
features.goals = true
notify = ["host-app"]

[[skills.config]]
path = "{HOME}/.agents/skills/wait-what/SKILL.md"
enabled = false

[[skills.config]]
path = "/elsewhere/skill/SKILL.md"
enabled = false

[projects."/work"]
trust_level = "trusted"
"""


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        bootstrap.HOME = self.home
        bootstrap.AGENTS = self.home / ".agents"
        bootstrap.CODEX = self.home / ".codex"
        (bootstrap.AGENTS / "codex").mkdir(parents=True)
        (bootstrap.AGENTS / "codex/config.base.toml").write_text(BASE)
        self.target = bootstrap.AGENTS / "PROFILE.md"
        self.target.write_text("profile\n")

    def test_missing_path_becomes_a_relative_link(self) -> None:
        path = self.home / ".codex/AGENTS.md"
        report = bootstrap.Report(check=False)
        bootstrap.ensure_link(path, self.target, report)
        self.assertTrue(path.is_symlink())
        self.assertEqual(str(path.readlink()), "../.agents/PROFILE.md")
        self.assertEqual(report.conflicts, [])

    def test_identical_file_becomes_a_link_and_different_file_is_a_conflict(self) -> None:
        same, other = self.home / "same.md", self.home / "other.md"
        same.write_text("profile\n")
        other.write_text("local edits\n")
        report = bootstrap.Report(check=False)
        bootstrap.ensure_link(same, self.target, report)
        bootstrap.ensure_link(other, self.target, report)
        self.assertTrue(same.is_symlink())
        self.assertFalse(other.is_symlink())
        self.assertEqual(other.read_text(), "local edits\n")
        self.assertEqual(len(report.conflicts), 1)

    def test_check_mode_reports_without_writing(self) -> None:
        path = self.home / ".codex/AGENTS.md"
        report = bootstrap.Report(check=True)
        bootstrap.ensure_link(path, self.target, report)
        self.assertFalse(path.exists())
        self.assertEqual(len(report.drift), 1)

    def test_config_merge_sets_shared_keys_and_keeps_codex_owned_ones(self) -> None:
        config = self.home / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text(LIVE.replace("{HOME}", str(self.home)))
        bootstrap.sync_codex_config(bootstrap.Report(check=False))
        text = config.read_text()
        merged = tomlkit.parse(text)
        self.assertIn("# Codex-owned comment", text)
        self.assertEqual(merged["model"], "gpt-6.1-sol")
        self.assertEqual(merged["forced_login_method"], "chatgpt")
        self.assertEqual(merged["notify"], ["host-app"])
        self.assertTrue(merged["features"]["goals"])
        self.assertTrue(merged["features"]["hooks"])
        self.assertEqual(merged["projects"]["/work"]["trust_level"], "trusted")
        self.assertEqual(merged["mcp_servers"]["refero"]["url"], "https://api.refero.design/mcp")
        paths = [entry["path"] for entry in merged["skills"]["config"]]
        self.assertEqual(paths, ["/elsewhere/skill/SKILL.md", f"{self.home}/.agents/skills/teach/SKILL.md"])
        self.assertTrue((config.parent / "config.toml.before-bootstrap").is_file())

        report = bootstrap.Report(check=True)
        bootstrap.sync_codex_config(report)
        self.assertEqual(report.drift, [])

    def test_missing_config_is_created_from_the_base(self) -> None:
        bootstrap.sync_codex_config(bootstrap.Report(check=False))
        created = tomlkit.parse((self.home / ".codex/config.toml").read_text())
        self.assertEqual(created["forced_login_method"], "chatgpt")

    def commit_rules(self, text: str) -> Path:
        source = bootstrap.AGENTS / "codex/rules/default.rules"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text)
        git = ["git", "-C", str(bootstrap.AGENTS)]
        if not (bootstrap.AGENTS / ".git").exists():
            subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "rules"], check=True)
        return source

    def test_copy_follows_the_repository_and_protects_host_edits(self) -> None:
        source = self.commit_rules("v1\n")
        host = self.home / ".codex/rules/default.rules"
        bootstrap.ensure_copy(host, source, bootstrap.Report(check=False))
        self.assertFalse(host.is_symlink())
        self.assertEqual(host.read_text(), "v1\n")

        self.commit_rules("v2\n")
        bootstrap.ensure_copy(host, source, bootstrap.Report(check=False))
        self.assertEqual(host.read_text(), "v2\n")

        host.write_text("v2 plus a host approval\n")
        report = bootstrap.Report(check=False)
        bootstrap.ensure_copy(host, source, report)
        self.assertEqual(host.read_text(), "v2 plus a host approval\n")
        self.assertEqual(len(report.conflicts), 1)

    def test_symlinked_copy_target_becomes_a_regular_file(self) -> None:
        source = self.commit_rules("v1\n")
        host = self.home / ".codex/rules/default.rules"
        host.parent.mkdir(parents=True)
        host.symlink_to(source)
        bootstrap.ensure_copy(host, source, bootstrap.Report(check=False))
        self.assertFalse(host.is_symlink())
        self.assertEqual(host.read_text(), "v1\n")


if __name__ == "__main__":
    unittest.main()
