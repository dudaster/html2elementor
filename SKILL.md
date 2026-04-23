---
name: html2elementor
description: Convert HTML+CSS into Elementor JSON that imports into WordPress. Always use this skill whenever the user has HTML/CSS (pasted, file, URL, or AI-generated) and wants it to end up as an Elementor page — phrases like "convert HTML to Elementor", "import this landing into WordPress as Elementor", "make this Tailwind mockup an Elementor page", "turn my markup into Elementor JSON", "recreate this site in Elementor", or any variant. Do not try to produce Elementor JSON by hand — Elementor has non-obvious quirks (shared system-color globals that break previous pages, lazy-load hiding backgrounds, widget widths collapsing in row containers, CSS cache requiring flush) that this skill already handles correctly. Failing to use the skill produces output that imports but renders wrong.
metadata:
  openclaw:
    requires:
      bins:
        - python3
      python:
        - beautifulsoup4>=4.12
        - tinycss2>=1.2
        - cssselect2>=0.7
---

# html2elementor

Paste HTML+CSS, get a JSON payload you can drop into `_elementor_data`. A small, free, open-source HTML → Elementor converter that runs locally.

## When to use this skill

Use whenever the user has HTML on one side and wants Elementor on the other. Triggering phrases include (but aren't limited to):

- "convert this HTML to Elementor"
- "import this landing page into WordPress"
- "recreate this design as an Elementor page"
- "turn my mockup into Elementor"
- "bring this Tailwind page into WordPress"
- "I have HTML from [tool X], make it Elementor"
- "Elementor JSON from this markup"

Also use it implicitly — the user pastes or attaches HTML and asks "make this work in Elementor" without naming a tool.

**Don't use for:**
- Editing pages that are already Elementor (use WP-CLI / REST API directly).
- Plain WordPress pages with no Elementor (just `wp_insert_post` with `post_content`).
- Figma / Sketch / design files — this converts markup, not design-tool exports. If the user has a Figma file, suggest they first export to HTML with a tool like Figma-to-HTML or Anima, then run that output through this skill.

## The four-step flow

**Prepare → convert → verify → import.** The first three are local and identical regardless of the user's WordPress setup. The fourth depends on how they run WordPress.

### Step 0 — Prepare the input

- **External stylesheets.** If the HTML uses `<link rel="stylesheet" href="styles.css">`, inline the CSS into a `<style>` block before running the converter. The parser reads `<style>` blocks and inline `style=""`, not external files. Inlining preserves the cascade exactly.
- **Relative image paths.** If `<img src="assets/foo.png">` points to local files on disk, run the converter with `--upload` (see Step 3). Keep the input file next to the `assets/` directory — the uploader resolves relative paths against the HTML file's own directory.
- **Pasted HTML.** If the user pasted raw HTML, write it to a temp file (e.g. `/tmp/input.html`) so the converter has a real path to anchor relative URLs and so error messages make sense.

### Step 1 — Convert

Run from the installed skill directory (typically `~/.claude/skills/html2elementor` or `~/.openclaw/skills/html2elementor`):

```bash
.venv/bin/python3 -m html2elementor path/to/input.html -o /tmp/layout.json
```

Add `--upload` when the HTML references images (either absolute URLs or relative paths) and the user wants them pulled into the WP media library automatically:

```bash
.venv/bin/python3 -m html2elementor path/to/input.html --upload -o /tmp/layout.json
```

This produces two files:
- `/tmp/layout.json` — the `_elementor_data` payload (a list of top-level containers, each with nested widgets).
- `/tmp/layout.kit.json` — custom_colors and custom_typography globals. Widgets in the layout reference these via `globals/colors?id=...`; without merging this into the active kit the page renders with missing colors and fonts.

### Step 2 — Verify

```bash
.venv/bin/python3 -m html2elementor.verify path/to/input.html /tmp/layout.json
```

The verifier walks the source HTML node-by-node and checks that each emitted widget has matching color, font-size, spacing, and max-width. Zero issues means the CSS cascade was resolved correctly and faithfully typed through. It does not guarantee pixel-perfect render — that needs a screenshot diff — but it catches the common failure mode (silent layout drift) cheaply.

Share the issues list with the user verbatim before importing. Each mismatch is actionable.

### Step 3 — Import

This step depends on the user's WordPress setup, so **ask them how they want to import** before running any commands. Common setups and the right approach:

| Setup | How to import |
|-------|---------------|
| Local WP (MAMP, Local by Flywheel, Laravel Valet) | `wp-cli` via terminal |
| Docker sandbox | `docker compose exec wp wp eval ...` |
| Staging on a managed host | SSH + `wp-cli`, or the REST API |
| Production | REST API or Elementor's template-library import |

Whatever the transport, **two invariants always apply**:

1. **Merge `.kit.json` custom globals** into the active kit's `_elementor_page_settings` post meta. Look up the active kit ID with `get_option("elementor_active_kit")`, then append each entry from `.kit.json`'s `custom_colors` and `custom_typography` (dedupe by `_id`). Also copy scalar site settings when present: `body_background_background` (`"classic"`) and `body_background_color` (hex from the HTML's body `background` CSS). Skipping the custom arrays makes widgets render with default colors/fonts; skipping the body scalars leaves the site on the Elementor default white instead of the source page's background.

2. **Flush Elementor's CSS cache** after updating `_elementor_data`: `wp elementor flush_css --allow-root`. Elementor builds per-post CSS files under `wp-content/uploads/elementor/css/` and serves those instead of reading settings live. Without flushing, visual changes won't appear on next page load.

If the user reports "my page looks empty" or "colors are wrong after import", one of those two invariants was missed.

**Internal links still point at the source HTML filenames.** The converter preserves `href` values verbatim — `href="pricing.html"` stays `href="pricing.html"`. After import, rewrite those to the WP page slugs before flushing CSS. Safest approach: preprocess the JSON files on disk with `sed`:

```bash
sed -i '' \
  -e 's|"docs/index\.html"|"/dudaster-docs/"|g' \
  -e 's|"index\.html"|"/dudaster-index/"|g' \
  -e 's|"modules\.html"|"/dudaster-modules/"|g' \
  -e 's|"pricing\.html"|"/dudaster-pricing/"|g' \
  page.json
```

Process the most specific paths first (`docs/index.html` before `index.html`) so short names don't clobber longer ones. **Do not** try this with regex in PHP via `update_post_meta` — a bad pattern returning `null` will silently wipe `_elementor_data` on every matched post. Rewrite on disk, then re-import.

**Kit bloat.** Every re-import merges new `custom_colors` / `custom_typography` IDs into the kit (dedupe by `_id`) but never removes orphans from intermediate runs. After many iterations the kit accumulates hundreds of unused entries. Garbage-collect by scanning every post's `_elementor_data` for referenced `globals/colors?id=` + `globals/typography?id=` IDs and filtering the kit to just those. See `playsand/cleanup_kit.sh` in this repo for a reference implementation — safe to run anytime, only prunes IDs no post references, flags orphans where a post references a missing ID.

### Step 4 (optional) — Visual verify

After import, screenshot both the source HTML and the rendered Elementor page at the same viewport (1440×auto for desktop). Compare side-by-side. The verifier catches semantic drift but some Elementor quirks (see below) only show in a real browser.

## What the converter knows (non-obvious patterns)

The full reference is in [README.md](README.md). These are the patterns that broke in practice and were hardened:

- **CSS custom properties** (`--color-brand`, `--font-sans`) are resolved from `:root`/html/body, substituted post-cascade, then shorthand-re-expanded so `background: var(--x)` populates `background-color` correctly.
- **Mixed inline content** (`<div>Paper<span>fold</span></div>`) is emitted as a single widget with `<span style="color:#xxx">…</span>` inline HTML — never split into two widgets or layout drifts.
- **Circular avatars** (div with bg + `border-radius:50%` + fixed px size + short text) become a styled inner container wrapping a heading — headings alone can't hold width in a flex row.
- **Agenda / schedule slots** (flex row with fixed-width label + content) are emitted as a single text-editor with inline absolute-positioned label. Elementor row containers break fixed+grow widths (see quirks below), so we use inline HTML to sidestep.
- **Split hero** (text column + image column) — any `<img>`, `<svg>`, `<picture>` in a card counts as content for grid detection, so purely visual columns don't collapse the row into a single vertical stack.
- **`<ul>/<ol>`** emit as `icon-list` widgets. The `<ul>` wrapper's `margin: 24px 0 32px` and the first `<li>`'s font/color are preserved on the widget.
- **Styled wrappers** (divs with bg/gradient/border-radius) emit as inner containers preserving bg, gradient stops, per-side borders (`border-top` stays top-only, not a full box), radius, padding, and CSS `gap`.
- **Grid wrapper spacing** (`.mod { padding: 72px 0; border-top: 1px solid }` on each row in a section) — padding-top/bottom and border-top widths/colors propagate to the Elementor row container, so per-row dividers and breathing room survive intact.
- **Typography globals** are keyed on `(family|weight|size)` so a 48px h3 on page A and a 72px h3 on page B get different IDs — no collision, no page A silently re-rendering when page B imports.
- **`position: absolute`** (caption overlays, corner-pinned badges) translates to Elementor's advanced positioning: `_position: "absolute"` + `_offset_orientation_h/v` (start|end) + `_offset_x/y` in px.

## Elementor quirks worth pre-flagging

These aren't in Elementor's docs but trip up every integration. If the user reports the matching symptom, these are the first hypothesis:

- **Bg images / gradients disappear on sections below the fold.** Elementor's lazy-load experiment applies `background-image: none !important` to non-intersecting sections. Either disable site-wide (`wp eval 'update_option("elementor_experiment-e_lazyload", "inactive");'`) or scroll before judging the render.

- **Nested container widths.** Elementor row containers compute child widget widths via `--container-widget-width: calc((1 - flex-grow) * 100%)`, which goes to 0 when flex-grow is 1 at a parent. For fixed-width widgets in a row (time columns, badges), we wrap the widget in an inner container — containers handle widths reliably; widgets don't.

- **Shared system-kit globals.** `primary`, `secondary`, `text`, `accent` are defined once per site. Importing page A with `primary: pink` then page B with `primary: blue` makes page A render blue. The converter avoids system slots entirely — everything goes into `custom_colors` / `custom_typography` with hashed page-unique IDs. If a user complains "old pages changed colors after the new one was imported", a previous tool used system globals.

- **CSS cache.** Every time `_elementor_data` changes on a post, Elementor expects a CSS regeneration pass. Always flush after import.

- **Unicode arrows / symbols replaced with Twemoji PNGs.** Characters like `↗` (U+2197), `↘`, `✓`, `★` render as `<img src="https://s.w.org/images/core/emoji/.../xxxx.svg">` instead of the glyph. Cause: WordPress core's `convert_smilies` / `wp_staticize_emoji` filter runs on `the_content` and widget text, swapping any codepoint in its emoji range with a Twemoji CDN image. Not an Elementor or html2elementor bug. Disable site-wide with a mu-plugin:
  ```php
  add_action('init', function () {
      remove_action('wp_head', 'print_emoji_detection_script', 7);
      remove_action('wp_print_styles', 'print_emoji_styles');
      remove_filter('the_content', 'convert_smilies');
      remove_filter('widget_text', 'convert_smilies');
  });
  ```
  Or one-shot for a sandbox: `wp eval 'update_option("use_smilies", 0);'` plus the `remove_action` calls above via `wp eval`.

- **Images uploaded but not loaded.** Elementor adds `loading="lazy"` on `<img>` tags. A fullPage screenshot may show broken images below the fold until you scroll. Scroll through the page before screenshotting, or check the images are uploaded via `wp post list --post_type=attachment`.

## Dev setup (one-time)

From the installed skill directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Requires Python 3.10+. Dependencies: `beautifulsoup4`, `tinycss2`, `cssselect2`. No Node, no browser runtime.

## Tests

Test HTML files in `tests/` cover common landing patterns: portfolio, pricing, analytics SaaS, conference with agenda + speakers, creative studio, blog with split hero, app with newsletter form, team with circular photos, and AI-style markup with CSS custom properties. They double as examples — point the user at the most similar test if they want to see what a conversion looks like.

Convert + verify any test:

```bash
.venv/bin/python3 -m html2elementor tests/<name>.html -o /tmp/<name>.json
.venv/bin/python3 -m html2elementor.verify tests/<name>.html /tmp/<name>.json
```

Full benchmark run:

```bash
for t in tests/*.html; do
  n=$(basename "$t" .html)
  .venv/bin/python3 -m html2elementor "$t" -o /tmp/$n.json 2>/dev/null
  printf "%-12s " "$n"
  .venv/bin/python3 -m html2elementor.verify "$t" /tmp/$n.json 2>&1 | grep -E "Widgets|Issues" | tr '\n' ' '
  echo
done
```

## When to iterate

Verify at 0 issues and visual side-by-side looking right → stop. Otherwise, suspect these in order:

1. **Section backgrounds missing** → `background: var(--x)` shorthand — check var resolution + shorthand re-expansion.
2. **Widgets empty-looking** → kit wasn't merged. Check `get_option('elementor_active_kit')` and confirm `_elementor_page_settings` has the new custom_colors.
3. **Fonts wrong size** → ID collision. Verify `custom_typography` entries across pages don't share `_id` with different sizes.
4. **Layout collapsed to single column where source has two** → a purely-visual column (image only) was rejected by `_is_card_grid`. Check `CARD_CONTENT_TAGS` includes img/svg/picture.
5. **Spacing too tight / elements touching** → CSS `gap` on grid/flex wrappers not propagated. Check `_styled_wrapper_container` reads gap.
6. **Images missing on import** → forgot `--upload`, or the HTML file path wasn't passed so relative paths didn't resolve. Re-run with `--upload` and the real file path.
