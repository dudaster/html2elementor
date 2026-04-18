---
name: html2elementor
description: Convert raw HTML+CSS into importable Elementor JSON. Use when the user wants to turn a static webpage, a Tailwind/plain-CSS mockup, an AI-generated design, or a competitor's landing page into an Elementor page for WordPress. Local, no browser, no API calls. Works on HTML strings, local files, or (optionally with playwright) live URLs.
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

Paste HTML+CSS, get a JSON payload you can drop into `_elementor_data`. The only free, open-source, local HTML → Elementor converter.

## When to use this skill

Trigger this skill whenever the user asks to:
- Convert HTML to Elementor
- Import a design into WordPress (Elementor)
- Turn a mockup / Tailwind page / AI-generated landing into an Elementor layout
- Recreate another website's page structure in Elementor
- Build an Elementor import kit from a design

Do NOT use this skill for:
- Editing existing Elementor pages (use wpmcp/WP-CLI directly)
- Pure WordPress content (posts, pages without Elementor)
- Figma → code (this is HTML → Elementor, not Figma → anything)

## Usage

### 1. Convert

```bash
cd ~/Projects/elementor-templates-skill/html2elementor
.venv/bin/python3 -m html2elementor path/to/input.html -o /tmp/layout.json
```

Produces:
- `/tmp/layout.json` — Elementor `_elementor_data` payload
- `/tmp/layout.kit.json` — companion site-kit globals (custom_colors, custom_typography)

### 2. Verify (optional but recommended)

```bash
.venv/bin/python3 -m html2elementor.verify path/to/input.html /tmp/layout.json
```

Reports mismatches in color, font-size, spacing. Zero issues means the cascade was resolved correctly. Visual fidelity still needs a screenshot-compare (see below).

### 3. Import into WordPress

How you import depends on your setup — local WP, Docker, staging, production, REST API, etc. The output is just a JSON payload that goes into the `_elementor_data` post meta, and the companion `.kit.json` merges into the active kit's `_elementor_page_settings` meta. Ask the user about their WordPress setup and pick the appropriate import path (WP-CLI, REST API, or direct DB).

Two things that ALWAYS need to happen regardless of setup:
- Merge `.kit.json` custom_colors + custom_typography into the active Elementor kit's `_elementor_page_settings` meta (widgets reference these via `globals/colors?id=...` and `globals/typography?id=...`).
- After updating `_elementor_data`, run `wp elementor flush_css` (or equivalent) — Elementor caches generated CSS aggressively and visual changes won't appear otherwise.

### 4. Visual diff (recommended for AI-generated HTML)

Take screenshots of both source and imported page, compare visually, fix any mismatch in `html2elementor/widgets.py` or `resolver.py`, reconvert, reimport. Repeat until matching.

## What gets converted

Widget mapping, layout detection, CSS features, responsive behavior, limitations — see [README.md](README.md) for the full reference.

## Dev setup (one-time)

```bash
cd ~/Projects/elementor-templates-skill/html2elementor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Requires Python 3.10+. Three dependencies: `beautifulsoup4`, `tinycss2`, `cssselect2`. No browser runtime.

## Tests

10 test HTML files in `tests/` covering common landing patterns (portfolio, pricing, analytics SaaS, conference, studio, blog, app, team, AI-generated). Run any with:

```bash
.venv/bin/python3 -m html2elementor tests/<name>.html -o /tmp/<name>.json
.venv/bin/python3 -m html2elementor.verify tests/<name>.html /tmp/<name>.json
```

## Key rules learned from building this

- **System colors (primary/secondary/text/accent) are shared across all pages in a site kit.** Widgets must reference only `custom_colors` with page-unique hashed IDs, else each new import overwrites the previous page's palette.
- **Elementor row containers break fixed+grow widget widths.** For patterns like agenda slots (label + content), emit as a single text-editor with inline-styled HTML instead of nested containers.
- **CSS `var()` must be substituted post-cascade, then shorthands re-expanded.** Otherwise `background: var(--color)` resolves the var but never populates `background-color`.
- **Elementor lazy-load hides bg images on containers below the fold.** Either scroll before screenshotting or disable: `wp eval 'update_option("elementor_experiment-e_lazyload", "inactive");'`.
- **After import, always `wp elementor flush_css`** — otherwise old CSS is cached and visual fixes don't show.
