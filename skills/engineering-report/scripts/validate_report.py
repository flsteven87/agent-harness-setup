#!/usr/bin/env python3
"""Validate an engineering period report, then run the shared HTML report gate."""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "html-report-system/scripts"))
import validate_html_report  # noqa: E402


REQUIRED_SECTIONS = {"executive", "outcomes", "gates", "evidence"}
REQUIRED_OUTCOME_FIELDS = {
    "status",
    "before",
    "after",
    "consequence",
    "preserved",
    "fingerprint",
    "data",
    "proof",
}
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class ReportParser(HTMLParser):
    """Collect semantic, outcome, and dependency facts from one report."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[str] = []
        self.outcomes: list[set[str]] = []
        self.visual_count = 0
        self._outcome_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)

        if self._outcome_depth:
            self._outcome_depth += 1
        if "data-report-outcome" in attributes:
            if self._outcome_depth:
                return
            self.outcomes.append(set())
            self._outcome_depth = 1

        outcome_field = attributes.get("data-outcome-field")
        if outcome_field and self._outcome_depth:
            self.outcomes[-1].add(outcome_field)

        if tag in {"table", "svg"}:
            self.visual_count += 1

        section = attributes.get("data-report-section")
        if section:
            self.sections.append(section)

    def handle_endtag(self, tag: str) -> None:
        if self._outcome_depth:
            self._outcome_depth -= 1


def validate(path: Path) -> list[str]:
    """Return engineering-report-specific structural errors."""
    errors: list[str] = []
    if not path.is_file():
        return [f"report does not exist: {path}"]

    text = path.read_text(encoding="utf-8")
    parser = ReportParser()
    parser.feed(text)

    if parser.visual_count == 0:
        errors.append("report needs at least one semantic table or inline SVG visual")

    section_counts = {section: parser.sections.count(section) for section in set(parser.sections)}
    missing_sections = REQUIRED_SECTIONS - set(parser.sections)
    if missing_sections:
        errors.append("missing report sections: " + ", ".join(sorted(missing_sections)))
    repeated_sections = sorted(
        section for section in REQUIRED_SECTIONS if section_counts.get(section, 0) > 1
    )
    if repeated_sections:
        errors.append("report sections must be unique: " + ", ".join(repeated_sections))

    if not parser.outcomes:
        errors.append("report needs at least one main outcome capsule")
    for index, fields in enumerate(parser.outcomes, start=1):
        missing_fields = REQUIRED_OUTCOME_FIELDS - fields
        if missing_fields:
            errors.append(
                f"outcome {index} is missing fields: " + ", ".join(sorted(missing_fields))
            )

    if EMAIL.search(text):
        errors.append("report contains an email address; use a contributor name or redacted identity")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--portable",
        action="store_true",
        help="add the shared 320px mobile viewport and print-media checks",
    )
    args = parser.parse_args()

    report = args.report.expanduser().resolve()
    errors = validate(report)
    shared_errors, warnings = validate_html_report.validate(report, portable=args.portable)
    errors.extend(shared_errors)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Engineering period report and shared HTML checks OK: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
