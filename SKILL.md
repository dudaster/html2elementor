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

## The three-step flow

Running this skill end-to-end is three steps: **convert → verify → import**. The first two are always local and identical regardless of the user's WordPress setup. The third depends on how they run WordPress.

### Step 1 — Convert

Run from the installed skill directory (typically `~/.claude/skills/html2elementor` or `~/.openclaw/skills/html2elementor`):

```bash
.venv/bin/python3 -m html2elementor path/to/input.html -o /tmp/layout.json
```

This produces two files:
- `/tmp/layout.json` — the `_elementor_data` payload (a list of top-level containers, each with nested widgets).
- `/tmp/layout.kit.json` — custom_colors and custom_typography globals. Widgets in the layout reference these via `globals/colors?id=...`; without merging this into the active kit the page renders with missing colors and fonts.

If the user pasted HTML directly (no file), write it to a temp file first (e.g. `/tmp/input.html`) and pass that path.

### Step 2 — Verify

```bash
.venv/bin/python3 -m html2elementor.verify path/to/input.html /tmp/layout.json
```

The verifier walks the source HTML node-by-node and checks that each emitted widget has matching color, font-size, spacing, and max-width. Zero issues means the CSS cascade was resolved correctly and faithfully typed through. It does not guarantee pixel-perfect render — that needs a screenshot diff — but it catches the common failure mode (silent layout drift) cheaply.

Share the issues list with the user verbatim before importing. Each mismatch is actionable.

### Step 3 — Import

This step is different for every WordPress setup, so **ask the user how they want to import** before running any commands. Common setups and the right approach for each:

| Setup | How to import |
|-------|---------------|
| Local WordPress (MAMP, Local by Flywheel, Laravel Valet) | `wp-cli` via terminal |
| Docker / Playsand sandbox | `docker compose exec wp wp eval ...` |
| Staging on a managed host | SSH + `wp-cli`, or the REST API |
| Production | REST API or Elementor's template-library import |

Whatever the transport, two invariants always apply:

1. **Merge `.kit.json` custom globals** into the active kit's `_elementor_page_settings` post meta. Look up the active kit ID with `get_option("elementor_active_kit")`, then append each entry from `.kit.json` to `custom_colors` and `custom_typography` (dedupe by `_id`). Skipping this makes all widgets that reference globals render with default colors/fonts.

2. **Flush Elementor's CSS cache** after updating `_elementor_data`: `wp elementor flush_css --allow-root`. Elementor builds per-post CSS files under `wp-content/uploads/elementor/css/` and serves those instead of reading settings live. Without flushing, your visual changes won't appear on next page load.

If the user tells you their Elementor pages look empty or misstyled after import, the most common root cause is one of these two invariants being missed.

## What the converter knows

The full reference lives in [README.md](README.md). Highlights worth remembering:

- **Mixed inline content** (e.g. `<div>Paper<span>fold</span></div>`) is preserved as a single widget — the converter keeps the direct text plus the inline span and wraps span-colored runs in `<span style="color:#xxx">`. Never split these into separate widgets or the layout drifts.
- **Circular elements** (div with bg + `border-radius:50%` + fixed px size + short text) are detected as avatars and emitted as an inner container with the bg on the container + a heading inside for the initials. Otherwise Elementor collapses them because headings don't carry width.
- **Agenda / schedule slots** (flex row with fixed-width label + content) are emitted as a single text-editor with inline absolute-positioned label. Elementor row containers reliably break fixed+grow widths (see quirks below), so we avoid nesting and use inline HTML.
- **Sections** get custom, page-unique hashed color IDs — never `primary` / `secondary` / `text` / `accent`. Those system slots are site-wide; reusing them means every page import overwrites the previous page's palette.

## Elementor quirks worth pre-flagging

These aren't in Elementor's docs but trip up every integration. If the user reports the matching symptom, these are the first hypothesis:

- **Bg images / gradients disappear on sections below the fold.** Elementor has a lazy-load experiment that uses `background-image: none !important` on non-intersecting sections. Either disable it site-wide (`wp eval 'update_option("elementor_experiment-e_lazyload", "inactive");'`) or tell the user to scroll before judging.

- **Nested container widths.** Elementor row containers compute child widget widths via `--container-widget-width: calc((1 - flex-grow) * 100%)`, which goes to 0 when flex-grow is 1 at a parent level. For patterns needing a fixed width widget in a row (time columns, tags), we emit an inner container wrapping the widget — containers handle widths; widgets don't.

- **Shared system-kit globals.** `primary`, `secondary`, `text`, `accent` are defined once per site. Importing page A with `primary: pink` then page B with `primary: blue` makes page A render blue. The converter avoids system slots entirely; if a user complains about "old pages changing colors after I imported a new one", a previous tool probably used system globals.

- **CSS cache.** Every time `_elementor_data` changes on a post, Elementor expects a CSS regeneration pass. Hence `flush_css` above.

## Dev setup (one-time)

From the installed skill directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Requires Python 3.10+. Dependencies: `beautifulsoup4`, `tinycss2`, `cssselect2`. No Node, no browser runtime.

## Tests

Ten test HTML files live in `tests/` covering common landing patterns: portfolio, pricing, analytics SaaS, conference with agenda + speakers, creative studio, blog with split hero, app with newsletter form, team with circular photos, and AI-style markup with CSS custom properties. They double as examples — point the user at the most similar test if they want to see what a conversion looks like before running their own.

Convert + verify any test:

```bash
.venv/bin/python3 -m html2elementor tests/<name>.html -o /tmp/<name>.json
.venv/bin/python3 -m html2elementor.verify tests/<name>.html /tmp/<name>.json
```

Full benchmark run across all ten:

```bash
for t in tests/*.html; do
  n=$(basename "$t" .html)
  .venv/bin/python3 -m html2elementor "$t" -o /tmp/$n.json 2>/dev/null
  printf "%-12s " "$n"
  .venv/bin/python3 -m html2elementor.verify "$t" /tmp/$n.json 2>&1 | grep -E "Widgets|Issues" | tr '\n' ' '
  echo
done
```
