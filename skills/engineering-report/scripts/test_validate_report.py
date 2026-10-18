from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import validate_report


VALID_REPORT = """<!doctype html>
<html lang="zh-Hant"><head><title>我的 Sprint</title><style>
</style></head><body><h1 data-report-identity>我的 Sprint</h1>
<p data-report-thesis>本期交付讓會員行為更明確</p>
<header data-report-section="executive"></header><main>
<section data-report-section="outcomes"><article data-report-outcome>
<span data-outcome-field="status">已交付</span>
<div data-outcome-field="before">Before</div><div data-outcome-field="after">After</div>
<p data-outcome-field="consequence">Why</p><p data-outcome-field="preserved">Preserved</p>
<p data-outcome-field="fingerprint">Change</p><p data-outcome-field="data">None</p>
<p data-outcome-field="proof">TRACK-1</p></article></section>
<section data-report-section="gates"><table><tr><td>Gate</td></tr></table></section>
<section data-report-section="evidence"></section></main></body></html>"""


class ValidatorTests(unittest.TestCase):
    def validate_text(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.html"
            path.write_text(text, encoding="utf-8")
            return validate_report.validate(path)

    def test_accepts_complete_report(self) -> None:
        self.assertEqual(self.validate_text(VALID_REPORT), [])

    def test_accepts_complete_report_with_25_outcomes(self) -> None:
        start = VALID_REPORT.index("<article data-report-outcome>")
        end = VALID_REPORT.index("</article>", start) + len("</article>")
        article = VALID_REPORT[start:end]
        report = VALID_REPORT[:start] + article * 25 + VALID_REPORT[end:]

        self.assertEqual(self.validate_text(report), [])

    def test_checks_fields_beyond_the_executive_summary(self) -> None:
        start = VALID_REPORT.index("<article data-report-outcome>")
        end = VALID_REPORT.index("</article>", start) + len("</article>")
        article = VALID_REPORT[start:end]
        incomplete = article.replace(' data-outcome-field="proof"', "")
        report = VALID_REPORT[:start] + article * 24 + incomplete + VALID_REPORT[end:]

        self.assertIn("outcome 25 is missing fields: proof", self.validate_text(report))

    def test_rejects_missing_outcome_field(self) -> None:
        errors = self.validate_text(VALID_REPORT.replace(' data-outcome-field="preserved"', ""))

        self.assertIn("outcome 1 is missing fields: preserved", errors)

    def test_rejects_email_address(self) -> None:
        report = VALID_REPORT.replace("TRACK-1", "owner@example.com")
        self.assertIn(
            "report contains an email address; use a contributor name or redacted identity",
            self.validate_text(report),
        )

    def test_cli_runs_shared_rendering_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.html"
            path.write_text(VALID_REPORT, encoding="utf-8")
            with (
                patch.object(sys, "argv", ["validate_report.py", str(path), "--portable"]),
                patch.object(
                    validate_report.validate_html_report,
                    "validate",
                    return_value=(["shared issue"], []),
                ) as shared_gate,
            ):
                exit_code = validate_report.main()

        shared_gate.assert_called_once_with(path.resolve(), portable=True)
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
