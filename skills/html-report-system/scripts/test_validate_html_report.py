#!/usr/bin/env python3
"""Tests for the shared HTML report validator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validate_html_report import (
    DEFAULT_WIDTHS,
    PORTABLE_WIDTHS,
    browser_findings,
    find_playwright_cli,
    render_template_preview,
    validate,
    validate_browser,
    validate_static,
)


def report_html(*, identity: str = "我的 Sprint", thesis: str = "批次匯入接棒") -> str:
    """Return the smallest report that satisfies the shared static contract."""
    return f"""<!doctype html>
<html lang="zh-Hant"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{identity}</title><style>
html:lang(zh-Hant) .report-copy {{ line-break: strict; word-break: normal; }}
@media print {{ body {{ color: black; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none; }} }}
</style></head><body>
<header><h1 data-report-identity>{identity}</h1><p data-report-thesis>{thesis}</p></header>
<main class="report-copy"><p>這是一份可閱讀的報告。</p></main>
</body></html>"""


class StaticValidatorTests(unittest.TestCase):
    """Exercise semantic, packaging, and wrapping invariants."""

    def validate_text(self, text: str, *, template: bool = False) -> tuple[list[str], list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text(text, encoding="utf-8")
            return validate_static(path, allow_template_tokens=template)

    def test_accepts_distinct_identity_and_thesis(self) -> None:
        self.assertEqual(self.validate_text(report_html()), ([], []))

    def test_rejects_thesis_as_identity(self) -> None:
        errors, _ = self.validate_text(report_html(identity="同一標題", thesis="同一標題"))
        self.assertIn("report identity and thesis must be distinct", errors)

    def test_rejects_global_arbitrary_wrapping(self) -> None:
        report = report_html().replace(
            "html:lang(zh-Hant)",
            "body { overflow-wrap: anywhere; } html:lang(zh-Hant)",
        )
        errors, _ = self.validate_text(report)
        self.assertTrue(any("body-level overflow-wrap:anywhere" in error for error in errors))

    def test_rejects_authored_prose_break(self) -> None:
        errors, _ = self.validate_text(
            report_html().replace("這是一份可閱讀的報告。", "這是一份<br>被控制換行的報告。")
        )
        self.assertTrue(any("authored <br>" in error for error in errors))

    def test_rejects_remote_presentation_asset(self) -> None:
        errors, _ = self.validate_text(
            report_html().replace("</head>", '<script src="https://example.com/app.js"></script></head>')
        )
        self.assertTrue(any("external presentation assets" in error for error in errors))

    def test_template_mode_allows_tokens(self) -> None:
        report = report_html(identity="%%REPORT_IDENTITY%%")
        self.assertEqual(self.validate_text(report, template=True), ([], []))

    def test_print_styles_are_required_only_for_portable_reports(self) -> None:
        report = report_html().replace("@media print { body { color: black; } }", "")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text(report, encoding="utf-8")

            self.assertEqual(validate_static(path), ([], []))
            errors, _ = validate_static(path, require_print=True)

        self.assertIn("missing print stylesheet", errors)

    def test_template_preview_replaces_semantic_and_html_tokens(self) -> None:
        preview = render_template_preview(
            "%%REPORT_IDENTITY%%|%%EXECUTIVE_HEADLINE%%|{{REPORT_BODY_HTML}}"
        )

        self.assertNotIn("%%", preview)
        self.assertNotIn("{{", preview)
        self.assertIn("我的 Sprint", preview)
        self.assertIn("<details>", preview)

    def test_viewport_profiles_match_report_usage(self) -> None:
        self.assertEqual(DEFAULT_WIDTHS, (768, 1200))
        self.assertEqual(PORTABLE_WIDTHS, (320, 768, 1200))

    def test_browser_findings_reject_hidden_print_details(self) -> None:
        errors, warnings = browser_findings(
            {
                "screens": [],
                "print": {
                    "media": "print",
                    "width": 680,
                    "hiddenPrintDetails": ["details"],
                },
            }
        )

        self.assertEqual(warnings, [])
        self.assertTrue(any("closed details content is hidden" in error for error in errors))

    def test_browser_findings_reject_clipped_print_scroll_regions(self) -> None:
        errors, warnings = browser_findings(
            {
                "screens": [],
                "print": {
                    "media": "print",
                    "width": 680,
                    "clippedPrintRegions": ["div.ledger"],
                },
            }
        )

        self.assertEqual(warnings, [])
        self.assertTrue(any("scroll container clips content" in error for error in errors))

    @unittest.skipUnless(find_playwright_cli() is not None, "Playwright CLI unavailable")
    def test_browser_scan_rejects_closed_details_hidden_in_print(self) -> None:
        hidden_details = (
            "<details><summary>完整稽核軌跡</summary>"
            "<div><p>這段證據必須出現在列印版本。</p></div></details>"
        )
        report = report_html().replace(
            "<p>這是一份可閱讀的報告。</p>",
            hidden_details,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text(report, encoding="utf-8")

            errors, warnings = validate_browser(path, (320,), include_print=True)

        self.assertEqual(warnings, [])
        self.assertTrue(any("closed details content is hidden" in error for error in errors))

    @unittest.skipUnless(find_playwright_cli() is not None, "Playwright CLI unavailable")
    def test_owned_templates_pass_portable_browser_validation(self) -> None:
        skills = Path(__file__).resolve().parents[2]
        templates = (
            skills / "html-report-system/assets/report-foundation.html",
            skills / "engineering-report/assets/report-template.html",
        )

        for template in templates:
            with self.subTest(template=template):
                errors, warnings = validate(
                    template,
                    allow_template_tokens=True,
                    widths=PORTABLE_WIDTHS,
                    portable=True,
                )

                self.assertEqual((errors, warnings), ([], []), str(template))

    @patch("validate_html_report.validate_browser", return_value=(["browser issue"], []))
    def test_static_errors_do_not_hide_browser_findings(self, browser_validator) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text(
                report_html().replace(" data-report-identity", ""),
                encoding="utf-8",
            )

            errors, _ = validate(path, browser=True)

        browser_validator.assert_called_once()
        self.assertTrue(any("data-report-identity" in error for error in errors))
        self.assertIn("browser issue", errors)


if __name__ == "__main__":
    unittest.main()
