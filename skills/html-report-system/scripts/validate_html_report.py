#!/usr/bin/env python3
"""Validate semantic, packaging, and rendered-layout invariants for an HTML report."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote


DEFAULT_WIDTHS = (768, 1200)
PORTABLE_WIDTHS = (320, 768, 1200)
PROSE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
TEMPLATE_TOKEN = re.compile(r"%%[A-Z][A-Z0-9_]*%%|\{\{[^{}]+\}\}")
NAMED_TEMPLATE_TOKEN = re.compile(
    r"%%(?P<percent>[A-Z][A-Z0-9_]*)%%|\{\{(?P<brace>[A-Z][A-Z0-9_]*)\}\}"
)
REMOTE_CSS = re.compile(r"@import\s|url\(\s*['\"]?https?://", re.IGNORECASE)


def normalize(parts: list[str]) -> str:
    """Collapse HTML text fragments into one comparable string."""
    return " ".join("".join(parts).split())


class ReportParser(HTMLParser):
    """Collect the document facts shared by all report formats."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: set[str] = set()
        self.stack: list[str] = []
        self.lang = ""
        self.viewport = ""
        self.title_parts: list[str] = []
        self.h1_parts: list[list[str]] = []
        self.identity_parts: list[str] = []
        self.thesis_parts: list[str] = []
        self.main_count = 0
        self.identity_count = 0
        self.thesis_count = 0
        self.manual_prose_breaks = 0
        self.remote_assets: list[str] = []
        self.style_parts: list[str] = []
        self._in_title = False
        self._in_style = False
        self._h1_index: int | None = None
        self._in_identity = False
        self._thesis_tag = ""
        self._thesis_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.tags.add(tag)

        if tag == "br" and any(parent in PROSE_TAGS for parent in self.stack):
            self.manual_prose_breaks += 1

        if tag == "html":
            self.lang = (attributes.get("lang") or "").strip()
        elif tag == "meta" and (attributes.get("name") or "").lower() == "viewport":
            self.viewport = (attributes.get("content") or "").strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "style":
            self._in_style = True
        elif tag == "main":
            self.main_count += 1
        elif tag == "h1":
            self.h1_parts.append([])
            self._h1_index = len(self.h1_parts) - 1
            if "data-report-identity" in attributes:
                self.identity_count += 1
                self._in_identity = True

        if "data-report-thesis" in attributes:
            self.thesis_count += 1
            self._thesis_tag = tag
            self._thesis_depth = len(self.stack) + 1

        if tag == "script" and attributes.get("src"):
            self.remote_assets.append(attributes["src"] or "")
        if tag == "link" and "stylesheet" in (attributes.get("rel") or "").lower().split():
            self.remote_assets.append(attributes.get("href") or "")
        if tag in {"img", "source", "video", "audio"}:
            source = attributes.get("src") or attributes.get("srcset") or ""
            if source.startswith(("http://", "https://", "//")):
                self.remote_assets.append(source)

        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "style":
            self._in_style = False
        elif tag == "h1":
            self._h1_index = None
            self._in_identity = False

        if tag == self._thesis_tag and len(self.stack) == self._thesis_depth:
            self._thesis_tag = ""
            self._thesis_depth = 0

        if tag in self.stack:
            while self.stack:
                popped = self.stack.pop()
                if popped == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_style:
            self.style_parts.append(data)
        if self._h1_index is not None:
            self.h1_parts[self._h1_index].append(data)
        if self._in_identity:
            self.identity_parts.append(data)
        if self._thesis_tag:
            self.thesis_parts.append(data)


def css_has_global_anywhere(css: str) -> bool:
    """Return whether a body-level rule enables arbitrary wrapping."""
    for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css, flags=re.DOTALL):
        selectors = {part.strip().lower() for part in selector.split(",")}
        if selectors.intersection({"body", "html body"}) and re.search(
            r"overflow-wrap\s*:\s*anywhere", declarations, flags=re.IGNORECASE
        ):
            return True
    return False


def validate_static(
    path: Path,
    *,
    allow_template_tokens: bool = False,
    require_print: bool = False,
) -> tuple[list[str], list[str]]:
    """Return static errors and review warnings for one report."""
    errors: list[str] = []
    warnings: list[str] = []
    if path.suffix.lower() not in {".html", ".htm"}:
        errors.append("report must use the .html or .htm extension")
    if not path.is_file():
        return [f"report does not exist: {path}"], warnings

    text = path.read_text(encoding="utf-8")
    parser = ReportParser()
    parser.feed(text)

    if not text.lstrip().lower().startswith("<!doctype html>"):
        errors.append("missing HTML5 doctype")
    for tag in ("html", "head", "title", "body", "main", "style"):
        if tag not in parser.tags:
            errors.append(f"missing <{tag}> element")
    if not parser.lang:
        errors.append("<html> must declare a language")
    if "width=device-width" not in parser.viewport.replace(" ", "").lower():
        errors.append("missing responsive viewport declaration")

    title = normalize(parser.title_parts)
    h1_values = [normalize(parts) for parts in parser.h1_parts]
    identity = normalize(parser.identity_parts)
    thesis = normalize(parser.thesis_parts)
    if not title:
        errors.append("<title> must contain report text")
    if len(h1_values) != 1:
        errors.append(f"expected exactly one <h1>, found {len(h1_values)}")
    if parser.main_count != 1:
        errors.append(f"expected exactly one <main>, found {parser.main_count}")
    if parser.identity_count != 1:
        errors.append(
            "expected exactly one <h1 data-report-identity>, "
            f"found {parser.identity_count}"
        )
    if parser.thesis_count != 1:
        errors.append(
            "expected exactly one element with data-report-thesis, "
            f"found {parser.thesis_count}"
        )
    if not identity:
        errors.append("report identity must contain text")
    if not thesis:
        errors.append("report thesis must contain text")
    if identity and identity not in title:
        errors.append("<title> must contain the report identity")
    if identity and thesis and identity.casefold() == thesis.casefold():
        errors.append("report identity and thesis must be distinct")
    if parser.manual_prose_breaks:
        errors.append(
            f"prose contains {parser.manual_prose_breaks} authored <br> element(s); "
            "let the layout wrap naturally"
        )

    if parser.remote_assets:
        errors.append(
            "external presentation assets are not allowed: " + ", ".join(parser.remote_assets)
        )
    if REMOTE_CSS.search(text):
        errors.append("embedded CSS must not fetch external assets")
    if not allow_template_tokens and TEMPLATE_TOKEN.search(text):
        errors.append("unfinished template token found")
    if require_print and "@media print" not in text:
        errors.append("missing print stylesheet")
    if "prefers-reduced-motion" not in text:
        errors.append("missing reduced-motion handling")

    css = "\n".join(parser.style_parts)
    if css_has_global_anywhere(css):
        errors.append(
            "body-level overflow-wrap:anywhere makes ordinary prose break at arbitrary positions"
        )
    has_cjk_em_override = re.search(
        r"html:lang\(zh[^)]*\)[^{]*\{[^}]*max-width\s*:\s*[0-9.]+em",
        css,
        flags=re.IGNORECASE,
    )
    if (
        parser.lang.lower().startswith("zh")
        and re.search(
            r"(?:p|li)[^{]*\{[^}]*max-width\s*:\s*[0-9.]+ch",
            css,
            flags=re.IGNORECASE,
        )
        and not has_cjk_em_override
    ):
        warnings.append(
            "Traditional Chinese prose uses a ch measure; confirm a language-scoped em override"
        )

    return errors, warnings


class QuietHandler(SimpleHTTPRequestHandler):
    """Serve the report without polluting validator output."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


BROWSER_SCAN = r"""async (page) => {
  const widths = __WIDTHS__;
  const checkPrint = __CHECK_PRINT__;
  const inspect = async (media, width) => page.evaluate(({ media, width }) => {
    const root = document.documentElement;
    const body = document.body;
    const overflow = Math.max(root.scrollWidth, body ? body.scrollWidth : 0) - root.clientWidth;
    const label = (element) => {
      const id = element.id ? `#${element.id}` : "";
      const className = typeof element.className === "string" && element.className.trim()
        ? `.${element.className.trim().split(/\s+/).slice(0, 2).join(".")}`
        : "";
      return `${element.tagName.toLowerCase()}${id}${className}`;
    };
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };

    const overflowElements = [];
    for (const element of document.body.querySelectorAll("*")) {
      if (!visible(element)) continue;
      const rect = element.getBoundingClientRect();
      if (rect.left >= -1 && rect.right <= root.clientWidth + 1) continue;

      let ancestor = element.parentElement;
      let locallyContained = false;
      while (ancestor && ancestor !== body) {
        const overflowX = getComputedStyle(ancestor).overflowX;
        if (overflowX === "auto" || overflowX === "scroll" || overflowX === "hidden") {
          locallyContained = true;
          break;
        }
        ancestor = ancestor.parentElement;
      }
      if (!locallyContained) overflowElements.push(label(element));
      if (overflowElements.length >= 10) break;
    }

    const splitMeta = [];
    for (const element of document.querySelectorAll("[data-report-meta-token]")) {
      if (!visible(element)) continue;
      const range = document.createRange();
      range.selectNodeContents(element);
      const tops = new Set(
        Array.from(range.getClientRects())
          .filter((rect) => rect.width > 0 && rect.height > 0)
          .map((rect) => Math.round(rect.top * 2) / 2)
      );
      if (tops.size > 1) splitMeta.push(label(element));
    }

    const localOverflow = [];
    for (const element of document.querySelectorAll("table, pre")) {
      if (!visible(element) || element.scrollWidth <= element.clientWidth + 1) continue;
      const ownOverflowX = getComputedStyle(element).overflowX;
      let container = element.parentElement;
      let contained = ownOverflowX === "auto" || ownOverflowX === "scroll";
      while (container && container !== body) {
        const overflowX = getComputedStyle(container).overflowX;
        if (overflowX === "auto" || overflowX === "scroll") {
          contained = true;
          break;
        }
        container = container.parentElement;
      }
      if (!contained) localOverflow.push(label(element));
    }

    const hiddenPrintDetails = [];
    const clippedPrintRegions = [];
    if (media === "print") {
      for (const details of document.querySelectorAll("details:not([open])")) {
        const content = Array.from(details.children).find(
          (element) => element.tagName.toLowerCase() !== "summary"
            && (element.textContent || "").trim()
        );
        if (content) {
          const detailsRect = details.getBoundingClientRect();
          const contentRect = content.getBoundingClientRect();
          const laidOutInsideDetails = visible(content)
            && contentRect.top < detailsRect.bottom - 1
            && contentRect.bottom <= detailsRect.bottom + 1;
          if (!laidOutInsideDetails) hiddenPrintDetails.push(label(details));
        }
      }
      for (const element of document.body.querySelectorAll("*")) {
        if (!visible(element) || element.scrollWidth <= element.clientWidth + 1) continue;
        const overflowX = getComputedStyle(element).overflowX;
        if (overflowX === "auto" || overflowX === "scroll" || overflowX === "hidden") {
          clippedPrintRegions.push(label(element));
        }
        if (clippedPrintRegions.length >= 10) break;
      }
    }

    const cjkWhitespace = [];
    const textWalker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    while (textWalker.nextNode()) {
      const node = textWalker.currentNode;
      if (!/\p{Script=Han}[\t\n\r ]+\p{Script=Han}/u.test(node.data)) continue;
      const parent = node.parentElement;
      if (!parent || parent.closest("pre, code, script, style")) continue;
      cjkWhitespace.push({
        element: label(parent),
        excerpt: node.data.trim().replace(/\s+/g, " ").slice(0, 72),
      });
      if (cjkWhitespace.length >= 8) break;
    }

    const identity = document.querySelector("[data-report-identity]");
    const thesis = document.querySelector("[data-report-thesis]");
    const firstViewport = {
      identityPresent: Boolean(identity),
      thesisPresent: Boolean(thesis),
      identity: Boolean(identity && identity.getBoundingClientRect().top < innerHeight),
      thesis: Boolean(thesis && thesis.getBoundingClientRect().top < innerHeight),
    };

    return {
      media,
      width,
      overflow,
      overflowElements,
      splitMeta,
      localOverflow,
      hiddenPrintDetails,
      clippedPrintRegions,
      cjkWhitespace,
      firstViewport,
    };
  }, { media, width });

  const screens = [];
  await page.emulateMedia({ media: "screen" });
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(40);
    screens.push(await inspect("screen", width));
  }

  let print = null;
  if (checkPrint) {
    await page.emulateMedia({ media: "print" });
    await page.setViewportSize({ width: 680, height: 900 });
    await page.waitForTimeout(40);
    print = await inspect("print", 680);
  }
  return { screens, print };
}"""


def find_playwright_cli() -> Path | None:
    """Resolve the installed Playwright CLI wrapper or executable."""
    configured = os.environ.get("PWCLI")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path

    wrapper = Path.home() / ".agents/skills/playwright/scripts/playwright_cli.sh"
    if wrapper.is_file():
        return wrapper

    executable = shutil.which("playwright-cli")
    return Path(executable) if executable else None


def parse_cli_result(output: str) -> dict[str, object]:
    """Extract the JSON result emitted by playwright-cli run-code."""
    match = re.search(r"### Result\s*\n(\{.*?\})(?:\n###|\Z)", output, flags=re.DOTALL)
    if not match:
        raise ValueError("playwright-cli did not return a JSON result")
    return json.loads(match.group(1))


def template_sample(name: str) -> str:
    """Return realistic, bounded preview content for one template token."""
    if name == "REPORT_BODY_HTML":
        return (
            "<section><h2>本期重點</h2><p>這是一段用來驗證中文正文、英文產品名稱與長句自然換行的範例內容。</p></section>"
            "<details><summary>完整稽核軌跡</summary><div><p>列印版本必須保留這段證據。</p></div></details>"
            '<div class="table-wrap"><table><thead><tr><th>Ticket</th><th>Intent</th>'
            "<th>Status</th><th>Code truth</th><th>Evidence</th></tr></thead>"
            "<tbody><tr><td>TRACK-1932</td><td>統一內容讀取規格</td><td>In progress</td>"
            "<td>服務已實作但正式環境尚待驗證</td><td>測試與部署記錄</td></tr></tbody></table></div>"
        )
    if name.endswith("_HTML"):
        return "<p>完整證據與限制範例。</p>"
    if name == "LANG":
        return "zh-Hant"
    if name in {"REPORT_IDENTITY", "REPORT_TITLE"}:
        return "我的 Sprint"
    if name == "WORKSTREAM":
        return "批次匯入"
    if any(part in name for part in ("HEADLINE", "THESIS", "VERDICT", "TOP_ACTION")):
        return "帳戶重複問題收斂後，批次匯入成為下一條產品主線"
    if any(part in name for part in ("LEDE", "SUMMARY", "WHY", "CONSEQUENCE")):
        return "目前交付順序已明確，使用者結果仍需部署與 staging 證據才能成立。"
    if any(part in name for part in ("DATE", "TIME", "WINDOW", "EVIDENCE_THROUGH")):
        return "2026-09-01 14:30 +08:00"
    if "STATUS" in name:
        return "已交付"
    if "CONTRIBUTOR" in name:
        return "Example Contributor"
    if "CONFIDENCE" in name:
        return "High"
    if name.endswith("_TOTAL"):
        return "16"
    return "範例內容"


def render_template_preview(text: str) -> str:
    """Replace tokens with deterministic content for browser layout validation."""
    return NAMED_TEMPLATE_TOKEN.sub(
        lambda match: template_sample(match.group("percent") or match.group("brace")),
        text,
    )


def browser_findings(result: dict[str, object]) -> tuple[list[str], list[str]]:
    """Convert browser measurements into stable validation findings."""
    errors: list[str] = []
    warnings: list[str] = []
    seen_warnings: set[str] = set()
    measurements = list(result.get("screens", []))
    print_result = result.get("print")
    if isinstance(print_result, dict):
        measurements.append(print_result)
    for measurement in measurements:
        media = measurement.get("media", "screen")
        width = measurement.get("width", "unknown")
        prefix = f"{media} {width}px"
        if measurement.get("overflow", 0) > 1:
            culprits = measurement.get("overflowElements", [])
            detail = f": {', '.join(culprits)}" if culprits else ""
            errors.append(f"{prefix}: page has horizontal overflow{detail}")
        if measurement.get("splitMeta"):
            errors.append(
                f"{prefix}: metadata token wraps internally: "
                + ", ".join(measurement["splitMeta"])
            )
        if measurement.get("localOverflow"):
            errors.append(
                f"{prefix}: wide table or pre lacks a local scroll container: "
                + ", ".join(measurement["localOverflow"])
            )
        if measurement.get("hiddenPrintDetails"):
            errors.append(
                f"{prefix}: closed details content is hidden in print: "
                + ", ".join(measurement["hiddenPrintDetails"])
            )
        if measurement.get("clippedPrintRegions"):
            errors.append(
                f"{prefix}: scroll container clips content in print: "
                + ", ".join(measurement["clippedPrintRegions"])
            )
        first_viewport = measurement.get("firstViewport", {})
        if media == "screen":
            if (
                first_viewport.get("identityPresent")
                and first_viewport.get("thesisPresent")
                and (
                    not first_viewport.get("identity")
                    or not first_viewport.get("thesis")
                )
            ):
                errors.append(f"{prefix}: report identity and thesis must appear in the first viewport")

        for item in measurement.get("cjkWhitespace", []):
            warning = (
                f"CJK source whitespace near {item['element']}: {item['excerpt']}"
            )
            if warning not in seen_warnings:
                warnings.append(warning)
                seen_warnings.add(warning)
    return errors, warnings


def validate_browser(
    path: Path,
    widths: tuple[int, ...],
    *,
    render_template: bool = False,
    include_print: bool = False,
) -> tuple[list[str], list[str]]:
    """Render one report in a real browser and return errors plus warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    cli = find_playwright_cli()
    if cli is None:
        return ["Playwright CLI is unavailable; install the user-level playwright skill"], warnings

    session = f"html-report-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    with tempfile.TemporaryDirectory(prefix="html-report-validator-") as temp_directory:
        work_directory = Path(temp_directory)
        served_path = path
        if render_template:
            served_path = work_directory / "template-preview.html"
            served_path.write_text(
                render_template_preview(path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )

        handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
            *args, directory=str(served_path.parent), **kwargs
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/{quote(served_path.name)}"

        def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [str(cli), "--session", session, *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
                cwd=work_directory,
            )

        try:
            run_cli("open", url)
            scan = BROWSER_SCAN.replace("__WIDTHS__", json.dumps(widths)).replace(
                "__CHECK_PRINT__", "true" if include_print else "false"
            )
            result = parse_cli_result(run_cli("run-code", scan).stdout)
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            detail = ""
            if isinstance(error, subprocess.CalledProcessError):
                lines = (error.stderr or error.stdout or "").strip().splitlines()
                detail = lines[-1] if lines else ""
            return [f"browser validation failed: {detail or error}"], warnings
        finally:
            try:
                subprocess.run(
                    [str(cli), "--session", session, "close"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=work_directory,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    return browser_findings(result)


def validate(
    path: Path,
    *,
    allow_template_tokens: bool = False,
    browser: bool = True,
    widths: tuple[int, ...] | None = None,
    portable: bool = False,
) -> tuple[list[str], list[str]]:
    """Run the selected validation layers."""
    selected_widths = widths or (PORTABLE_WIDTHS if portable else DEFAULT_WIDTHS)
    errors, warnings = validate_static(
        path,
        allow_template_tokens=allow_template_tokens,
        require_print=portable,
    )
    if browser and path.is_file():
        browser_errors, browser_warnings = validate_browser(
            path,
            selected_widths,
            render_template=allow_template_tokens,
            include_print=portable,
        )
        errors.extend(browser_errors)
        warnings.extend(browser_warnings)
    return errors, warnings


def parse_widths(value: str) -> tuple[int, ...]:
    """Parse a comma-separated positive viewport list."""
    try:
        widths = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("widths must be comma-separated integers") from error
    if not widths or any(width < 240 for width in widths):
        raise argparse.ArgumentTypeError("each viewport width must be at least 240")
    return widths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--template",
        action="store_true",
        help="allow unfilled %%TOKENS%% while checking an owned template",
    )
    parser.add_argument(
        "--widths",
        type=parse_widths,
        help="override the comma-separated screen widths for the browser pass",
    )
    parser.add_argument(
        "--portable",
        action="store_true",
        help="add the 320px mobile viewport and print-media checks",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()

    report = args.report.expanduser().resolve()
    errors, warnings = validate(
        report,
        allow_template_tokens=args.template,
        widths=args.widths,
        portable=args.portable,
    )
    if args.json:
        print(json.dumps({"report": str(report), "errors": errors, "warnings": warnings}, ensure_ascii=False))
    else:
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if not errors:
            print(f"HTML report system checks OK: {report}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
