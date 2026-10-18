"""The launchers on PATH must run the versioned scripts in this directory."""

from __future__ import annotations

import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTALL_DIR = (Path.home() / '.local/bin')
LAUNCHERS = (
    "code-review-graph-readonly",
    "crg-isolated-build",
    "crg-lifecycle",
    "crg-safe-refresh",
    "crg-worktree-attach",
    "crg-writer-supervisor",
)


class InstalledLaunchersTest(unittest.TestCase):
    def test_each_launcher_links_to_the_primary_checkout(self) -> None:
        primary = (Path.home() / '.agents/skills/use-code-review-graph/scripts')
        for name in LAUNCHERS:
            with self.subTest(name=name):
                installed = INSTALL_DIR / name
                self.assertTrue(installed.is_symlink(), f"{installed} is not a symlink")
                self.assertEqual(installed.resolve(strict=True), primary / name)

    def test_every_launcher_is_versioned_here(self) -> None:
        versioned = {path.name for path in HERE.iterdir() if path.name.startswith(("crg-", "code-review-graph-"))}
        self.assertEqual(versioned, set(LAUNCHERS))


if __name__ == "__main__":
    unittest.main()
