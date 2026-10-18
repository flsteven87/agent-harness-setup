"""The shareable wrapper forwards to gh without selecting a private account."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WRAPPER = Path(__file__).resolve().parents[1] / "bin/gh"


class GitHubWrapperTests(unittest.TestCase):
    def test_forwards_arguments_and_existing_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "gh"
            real.write_text('#!/bin/sh\nprintf "%s\\n" "$@" "$GH_TOKEN"\n')
            real.chmod(0o700)
            result = subprocess.run(
                [str(WRAPPER), "repo", "view", "example/project"],
                env={**os.environ, "PATH": str(root), "GH_TOKEN": "fixture-token"},
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(result.stdout.splitlines(),
                             ["repo", "view", "example/project", "fixture-token"])

    def test_skips_itself_on_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            links, tools = root / "links", root / "tools"
            links.mkdir()
            tools.mkdir()
            (links / "gh").symlink_to(WRAPPER)
            real = tools / "gh"
            real.write_text('#!/bin/sh\nprintf "real-gh\\n"\n')
            real.chmod(0o700)
            result = subprocess.run(
                [str(links / "gh"), "auth", "status"],
                env={**os.environ, "PATH": f"{links}:{tools}"},
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(result.stdout, "real-gh\n")

    def test_missing_real_gh_fails_instead_of_recursing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "gh").symlink_to(WRAPPER)
            result = subprocess.run(
                [str(root / "gh"), "repo", "view"],
                env={**os.environ, "PATH": str(root)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 127)
            self.assertIn("no gh executable", result.stderr)


if __name__ == "__main__":
    unittest.main()
