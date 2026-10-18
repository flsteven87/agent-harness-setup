# HTML Report Rendering Contract

Apply this contract after the report-specific narrative is settled. It owns rendering invariants,
not visual sameness: each report type keeps its own composition and hierarchy.

## Semantic shell

- Declare the document language, mobile viewport, one `<main>`, and one `<h1>`.
- Mark the stable `<h1>` with `data-report-identity` and the distinct thesis with
  `data-report-thesis` when the renderer permits attributes.
- Keep the report self-contained. Inline presentation CSS and SVG; evidence may remain ordinary HTTPS
  links. Pre-render generated diagrams instead of loading a browser runtime.
- Keep the DOM reading order equal to the visible reading order. Color reinforces status but never
  carries it alone.

## Natural wrapping

Let the viewport and container determine prose wrapping. Source formatting never controls visible
line endings.

- Write prose without authored `<br>` elements.
- Scope `overflow-wrap: anywhere` to genuinely unbounded values such as URLs, paths, code, hashes,
  and opaque identifiers. Body copy, headings, labels, and ordinary list items use natural wrapping.
- A metadata row may wrap between tokens. Mark dates, times, versions, and short status tokens with
  `data-report-meta-token` and keep each marked token on one line.
- Use `text-wrap: balance` only for short display headings on widths where it improves the line
  shape. Mixed Latin/CJK titles can look artificially indented when balanced in a narrow viewport;
  switch them back to natural wrapping or `text-wrap: pretty` at the mobile breakpoint. Use normal
  wrapping for body copy; `text-wrap: pretty` may be a progressive enhancement.

For Traditional Chinese, apply a language-scoped baseline:

```css
html:lang(zh-Hant) .report-copy {
  line-break: strict;
  word-break: normal;
}
```

`ch` measures the Latin zero, not a Han glyph. A Latin measure such as `72ch` can become an
unexpectedly narrow Chinese column. Give Chinese prose a template-specific `em` measure based on
rendered evidence. Treat `66em` as the current strategic-report default, not a universal constant.

## Markdown to HTML

Markdown source may wrap for maintainability, but its soft breaks must not create visible spaces
between adjacent CJK text. A Pandoc renderer uses a CJK-aware soft-break filter and `--wrap=none`
together: the filter owns semantic whitespace; `--wrap=none` prevents the generated HTML from adding
new source wrapping.

## Layout behavior

- Treat an embedded laptop browser as the default reading surface. Start from one narrow reading
  column, then add columns only where the content earns them.
- Use content-driven breakpoints and `minmax(0, 1fr)` for shrinkable grid tracks.
- Use a quiet full outline or tonal background for callouts. Do not default to a thick, decorative
  border on one side; reserve directional borders for information that truly has direction.
- Convert dense tables to labeled rows or cards in compact panes. A wide evidence table may scroll
  inside its own container; the page itself never scrolls horizontally.
- Honor `prefers-reduced-motion`; the report remains complete without JavaScript.

For portable reports, keep links, status, tables, and disclosed evidence meaningful in print. Expand
closed `<details>` through both its light-DOM child and `::details-content`; Chrome print skips the
slotted subtree when only the child display changes. Remove interactive table overflow and fit every
claim-bearing column inside the paper content box.

## What the gate fails

The shared validator measures these rules at 768 and 1200 px with a 900 px height; `--portable` adds
320 px and print media. Write to them directly:

- the semantic shell or packaging rules above are missing;
- the page scrolls horizontally, or a wide table or `pre` lacks its own scroll container;
- a `data-report-meta-token` wraps internally;
- the identity or thesis falls below the first viewport;
- in print, closed `<details>` content stays hidden or a scroll container clips content.

CJK source whitespace is a warning to review. For an owned template, the validator fills tokens with
deterministic Traditional Chinese samples before measuring.
