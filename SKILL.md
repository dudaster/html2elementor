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

### 3. Import into WordPress (Playsand sandbox)

```bash
cd ~/Projects/elementor-templates-skill/playsand

# Copy JSON + kit into the container
docker compose cp /tmp/layout.json      wp:/tmp/layout.json
docker compose cp /tmp/layout.kit.json  wp:/tmp/layout.kit.json

# Merge kit globals + create a page
docker compose exec -T wp wp eval '
$data = file_get_contents("/tmp/layout.json");
$kit  = json_decode(file_get_contents("/tmp/layout.kit.json"), true);
$active_kit = get_option("elementor_active_kit");
$ks = get_post_meta($active_kit, "_elementor_page_settings", true) ?: [];
foreach (($kit["custom_colors"] ?? []) as $c) {
    $dup = false;
    foreach ($ks["custom_colors"] ?? [] as &$ec) { if ($ec["_id"] === $c["_id"]) { $ec = $c; $dup = true; break; } }
    if (!$dup) $ks["custom_colors"][] = $c;
}
foreach (($kit["custom_typography"] ?? []) as $t) {
    $dup = false;
    foreach ($ks["custom_typography"] ?? [] as &$et) { if ($et["_id"] === $t["_id"]) { $et = $t; $dup = true; break; } }
    if (!$dup) $ks["custom_typography"][] = $t;
}
update_post_meta($active_kit, "_elementor_page_settings", $ks);

$pid = wp_insert_post([
    "post_title"  => "Imported Page",
    "post_status" => "publish",
    "post_type"   => "page",
    "meta_input"  => [
        "_elementor_edit_mode"      => "builder",
        "_elementor_template_type"  => "wp-page",
        "_wp_page_template"         => "elementor_canvas",
    ],
]);
update_post_meta($pid, "_elementor_data", wp_slash($data));
echo "Page: http://localhost:8090/?p=$pid\n";
' --allow-root

# Flush Elementor's CSS cache so the page renders immediately
docker compose exec -T wp wp elementor flush_css --allow-root
```

### 4. Visual diff (recommended for AI-generated HTML)

Take screenshots of both source and imported page, compare visually, fix any mismatch in `html2elementor/widgets.py` or `resolver.py`, reconvert, reimport. Repeat until matching. See `screenshots/` folder for captured diffs.

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
