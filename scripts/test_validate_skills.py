import tempfile
import unittest
from pathlib import Path

import validate_skills

SKILL = """---
name: demo
description: Demo skill for validator tests.
{extra}---

# Demo
"""


class ValidateSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        if not validate_skills.DEFAULT_VALIDATOR.is_file():
            self.skipTest("skill-creator validator not installed")
        self.root = Path(tempfile.mkdtemp())

    def write(self, extra: str) -> Path:
        skill = self.root / "demo"
        skill.mkdir(exist_ok=True)
        (skill / "SKILL.md").write_text(SKILL.format(extra=extra), encoding="utf-8")
        return skill

    def check(self, skill: Path) -> tuple[bool, str]:
        [(_, valid, message)] = validate_skills.validate([skill], validate_skills.DEFAULT_VALIDATOR)
        return valid, message

    def test_claude_fields_pass_and_the_original_is_untouched(self) -> None:
        extra = "disable-model-invocation: true\nargument-hint: \"[topic]\"\n"
        skill = self.write(extra)
        self.assertEqual(self.check(skill), (True, "Skill is valid!"))
        self.assertIn("disable-model-invocation: true", (skill / "SKILL.md").read_text())

    def test_misspelled_field_still_fails(self) -> None:
        valid, message = self.check(self.write("disable-model-invokation: true\n"))
        self.assertFalse(valid)
        self.assertIn("disable-model-invokation", message)

    def test_portable_rules_still_apply(self) -> None:
        skill = self.write("disable-model-invocation: true\n")
        text = (skill / "SKILL.md").read_text().replace("name: demo", "name: Demo_Skill")
        (skill / "SKILL.md").write_text(text)
        self.assertFalse(self.check(skill)[0])


if __name__ == "__main__":
    unittest.main()
