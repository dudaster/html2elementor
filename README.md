# html2elementor — HTML → Elementor skill for Claude Code / openclaw

> **Open-source HTML → Elementor JSON converter, packaged as both a Claude Code and an openclaw skill.** Paste HTML + CSS, get a `_elementor_data` payload you can import into WordPress. Works as a standalone Python CLI or as a skill that Claude auto-invokes when you ask to "import this design into Elementor".

[![Claude Code skill](https://img.shields.io/badge/claude%20code-skill-d97757.svg)](https://docs.anthropic.com/en/docs/claude-code)
[![openclaw skill](https://img.shields.io/badge/openclaw-skill-6366f1.svg)](https://github.com/openclaw/openclaw)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Elementor](https://img.shields.io/badge/elementor-3.x+-ec4899.svg)](https://elementor.com/)

`html2elementor` is a **fully open-source, local, zero-dependency-on-external-services** converter that emits clean Elementor container-based JSON from static HTML + CSS.

Pairs naturally with AI-generated HTML: point an LLM at your design brief, run the output through this tool, and import the JSON into Elementor. Or install as a Claude Code skill and let Claude do all three steps for you.

---

## What it does

- Parses HTML + CSS **locally** (no browser, no API calls) using BeautifulSoup + tinycss2.
- Resolves the CSS cascade including inheritance, inline styles, and **CSS custom properties** (`var(--x)`).
- Maps DOM nodes to Elementor widgets: `heading`, `text-editor`, `button`, `image`, `icon-list`, `icon-box`.
- Builds a container tree matching Elementor 3.x flex layouts (rows, columns, nested grids).
- Extracts **global colors and typography** into a companion `kit.json` (page-unique hashed IDs so imports don't clobber each other).
- Emits a `verify.py` companion that diff-checks the output against the source and flags missing colors / wrong sizes / mis-matched backgrounds.

### Example

**Input** (`landing.html`):
```html
<section style="padding:96px 64px;background:#0b1220;text-align:center">
  <h1 style="color:white;font-size:64px">Hello world</h1>
  <p style="color:#9ca3af;font-size:19px">A subtitle.</p>
  <a href="#" style="background:#ec4899;color:white;padding:14px 28px;border-radius:8px">
    Get started
  </a>
</section>
```

**Output** (`landing.json`):
```json
[
  {
    "elType": "container",
    "settings": {
      "background_background": "classic",
      "background_color": "#0b1220",
      "padding": {"unit":"px","top":"96","right":"64","bottom":"96","left":"64"},
      "flex_align_items": "stretch"
    },
    "elements": [
      {"elType":"widget","widgetType":"heading","settings":{"title":"Hello world","title_color":"#ffffff","typography_font_size":{"unit":"px","size":"64"}}},
      {"elType":"widget","widgetType":"text-editor","settings":{"editor":"<p>A subtitle.</p>","text_color":"#9ca3af"}},
      {"elType":"widget","widgetType":"button","settings":{"text":"Get started","background_color":"#ec4899","button_text_color":"#ffffff"}}
    ]
  }
]
```

Drop into `_elementor_data` meta of a WordPress page → your layout renders.

---

## Installation

```bash
git clone https://github.com/dudaster/html2elementor.git
cd html2elementor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.10+ and three tiny dependencies: `beautifulsoup4`, `tinycss2`, `cssselect2`. No browser, no Node, no services.

### Install as a Claude Code skill

`SKILL.md` at the repo root tells Claude when to invoke the tool. Clone straight into your skills folder:

```bash
git clone https://github.com/dudaster/html2elementor.git ~/.claude/skills/html2elementor
cd ~/.claude/skills/html2elementor
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

After that, prompts like *"convert landing.html to Elementor"* or *"import this mockup into the WP sandbox"* auto-trigger the skill — Claude runs the conversion, the verifier, and the import for you.

### Install as an openclaw skill

The same `SKILL.md` is valid for [openclaw](https://github.com/openclaw/openclaw) — the frontmatter declares `metadata.openclaw.requires` (Python bin + pip deps) so openclaw can install dependencies automatically.

```bash
git clone https://github.com/dudaster/html2elementor.git ~/.openclaw/skills/html2elementor
openclaw install  # resolves bins + pip deps declared in frontmatter
```

---

## Usage

### CLI

```bash
python3 -m html2elementor input.html -o output.json
```

This produces:
- `output.json` — the Elementor data payload
- `output.kit.json` — site-kit globals (custom colors, custom typography)

### Python API

```python
from html2elementor import convert

with open("landing.html") as f:
    html = f.read()

result = convert(html)
# result["layout"]     → list[dict] (sections → containers → widgets)
# result["kit"]        → dict (custom_colors + custom_typography)
```

### Importing into WordPress

```bash
# 1. Copy files into the container / host
docker compose cp output.json     wp:/tmp/layout.json
docker compose cp output.kit.json wp:/tmp/layout.kit.json

# 2. Merge into the active Elementor kit + create a page
docker compose exec wp wp eval '
$data = file_get_contents("/tmp/layout.json");
$kit  = json_decode(file_get_contents("/tmp/layout.kit.json"), true);
$active_kit = get_option("elementor_active_kit");
$ks = get_post_meta($active_kit, "_elementor_page_settings", true) ?: [];
foreach (($kit["custom_colors"] ?? []) as $c) {
    $ks["custom_colors"][] = $c;
}
foreach (($kit["custom_typography"] ?? []) as $t) {
    $ks["custom_typography"][] = $t;
}
update_post_meta($active_kit, "_elementor_page_settings", $ks);

$pid = wp_insert_post([
    "post_title"  => "My Page",
    "post_status" => "publish",
    "post_type"   => "page",
    "meta_input"  => [
        "_elementor_edit_mode"      => "builder",
        "_elementor_template_type"  => "wp-page",
        "_wp_page_template"         => "elementor_canvas",
    ],
]);
update_post_meta($pid, "_elementor_data", wp_slash($data));
echo "Page: $pid\n";
' --allow-root

# 3. Flush Elementor's CSS cache so the page renders immediately
docker compose exec wp wp elementor flush_css --allow-root
```

### Verify the conversion

`verify.py` compares the generated layout against the source HTML and reports mismatches in color, font-size, spacing, and alignment. Useful during iteration:

```bash
python3 -m html2elementor.verify input.html output.json
# Widgets checked: 52
# Issues: 0
# ✓ All checks passed
```

Tolerances: font-size ±2px, padding/margin ±4px, colors exact.

---

## What gets converted

### Widget mapping

| HTML | Elementor widget |
|------|------------------|
| `<h1>` … `<h6>` | `heading` with matching `header_size` |
| `<p>` (long text) | `text-editor` with resolved color + typography |
| `<p>` / `<div>` with short text (≤50 chars) | `heading` with `header_size: "div"` |
| `<button>` / styled `<a>` | `button` (filled, outlined, or text-link) |
| `<img>` | `image` (with circular / custom-size detection) |
| `<div>` + bg + radius 50% + fixed size | **circular avatar** inner container |
| `<div>` + bg + radius + short text | **badge** / pill |
| `<div class="col"><h4>…</h4><a>…</a>…</div>` | `heading` + `icon-list` (footer columns) |
| `<input>` | `text-editor` with inline-styled HTML input |

### Layout detection

- **Card grids** — `display: grid` or similar flex-row containers → Elementor row with per-column widths from `grid-template-columns`
- **Split hero** — 2-child flex-row with no fixed widths → 2× 48% side-by-side columns
- **List rows** — flex-row with fixed-width label + content div (agenda/schedule slots) → single text-editor with absolute-positioned label (reliable cross-browser)
- **Header navs** — `<header>` / `<nav>` with logo + links + CTA → dedicated flex-row layout with icon-list + button
- **Styled wrappers** — any `<div>` with gradient / solid non-white bg / border-radius preserved as inner container

### CSS features supported

- Cascade with specificity sorting
- Inheritance of `color`, `font-*`, `text-align`, `letter-spacing`, `text-transform`
- Inline `style=""` attributes (highest priority)
- **CSS custom properties** (`var(--x)`) resolved from `:root` / `html` / `body` (with chain resolution)
- Shorthand expansion: `padding`, `margin`, `border`, `border-radius`, `background`
- Named color keywords (`white`, `black`, `red`, `purple`, …)
- Linear gradients (parsed into Elementor gradient settings)

### Responsive behavior

- `flex-wrap: wrap` → propagates to tablet + mobile
- Row flex containers default to `flex_direction_mobile: column` (stack below 768px)
- Typography globals respected at all breakpoints
- Tested at desktop / tablet / mobile

---

## Limitations

**Will not work well:**
- JS-rendered pages (Next.js hydration, React CSR, etc.) — use the optional `--url` mode with Playwright if needed
- Media queries with `@media (min-width: …)` — currently no extraction
- Grid tracks beyond `repeat(N, 1fr)` — e.g. `grid-template-columns: 2fr 1fr` collapses to "N columns"
- CSS animations, transitions, `transform`
- Pseudo-elements (`::before`, `::after`, `:hover`, `:focus`)
- `backdrop-filter`, `clip-path`, complex `mask` effects

**Elementor-specific gotchas:**
- Elementor's lazy-load experiment hides `background-image` on containers below the fold until scroll. If your imported page shows missing section backgrounds, disable it:
  ```bash
  wp eval 'update_option("elementor_experiment-e_lazyload", "inactive");' --allow-root
  ```
- `image_custom_dimension` only works with files already in the WP media library. Remote URLs fall back to natural image size.
- System colors (`primary`, `secondary`, `text`, `accent`) are **site-shared**. `html2elementor` only uses `custom_colors` with page-unique hashed IDs to prevent page A's palette from overwriting page B's.

---

## Architecture

```
html2elementor/
├── __init__.py      # Public API: convert(html) → {layout, kit}
├── cli.py           # `python3 -m html2elementor input.html -o out.json`
├── parser.py        # HTML → tree of {tag, classes, text, styles, children}
├── resolver.py      # CSS cascade: selector matching + specificity + var() sub
├── sections.py      # Top-level section detection
├── widgets.py       # DOM → widget specs (heading, button, image, …)
├── containers.py    # Section → flex container settings
├── styles.py        # CSS parsing helpers (padding, radius, shadow, typography)
├── colors.py        # hex/rgb/named-color → #hex, darken(), lighten()
├── globals.py       # Extract site-wide colors + typography into kit.json
├── hover.py         # Hover state generation for buttons / icon-boxes
├── media.py         # Optional image upload helpers
├── builder.py       # Assemble final _elementor_data JSON (IDs, nesting)
└── verify.py        # Diff output vs source (colors, sizes, spacing)
```

Pipeline:
```
HTML string
  ↓ parser.parse_html (BeautifulSoup + inline styles)
  ↓ resolver.resolve_all (cascade + var() + inheritance)
  ↓ sections.detect_sections
  ↓ containers.map_section (per section)
    ↓ widgets._walk (recursive DOM traversal)
      ↓ emit widgets with Elementor settings
  ↓ globals.consolidate (extract kit + rewrite references)
  ↓ builder.build_layout (assign IDs, nest elements)
  ↓ JSON
```

---

## Testing

10 test pages covering common modern landing patterns:

| Test | Pattern |
|------|---------|
| `portfolio.html` | Minimalist creative portfolio |
| `education.html` | Edtech / courses |
| `pricing.html` | SaaS pricing plans |
| `analytics.html` | Complex SaaS landing (10 sections) |
| `conference.html` | Event with agenda + speakers + sponsors |
| `studio.html` | Agency with left-aligned hero |
| `blog.html` | Magazine with split hero + image cards |
| `app.html` | Newsletter form with input+button |
| `team.html` | Team photos + values grid |
| `ai-saas.html` | AI-generated style (CSS vars, Tailwind-ish classes) |

Run all tests:
```bash
for t in portfolio education pricing analytics conference studio blog app team ai-saas; do
  python3 -m html2elementor html2elementor/tests/$t.html -o /tmp/out.json
  python3 -m html2elementor.verify html2elementor/tests/$t.html /tmp/out.json
done
```

Current status: **95% visual match on AI-generated HTML** after 5 iterations of a screenshot-diff loop.

---

## Design principles

- **Local, deterministic, free forever.** No API keys, no services, no "AI credits."
- **Prefer visual fidelity over semantic fidelity.** A text-editor with inline HTML that renders correctly beats a semantically-pure widget that looks wrong.
- **Never share state between pages.** Every page import uses hashed-ID custom colors and typographies so a new import can't break an existing page.
- **Fail loud, not silent.** `verify.py` catches missing colors, wrong sizes, and structural drift before you import.

---

## Roadmap

- [ ] Extract `@media` queries into tablet/mobile overrides
- [ ] Support `grid-template-columns: 2fr 1fr` (non-uniform widths)
- [ ] `:hover` state extraction for buttons
- [ ] Image upload into WP media library via REST API
- [ ] Elementor template kit format (`.zip` instead of raw JSON)
- [ ] VS Code extension (paste HTML → preview Elementor)

---

## Contributing

PRs welcome. The shortest path to a useful contribution:

1. Pick a landing page (your own, or a competitor's exported HTML).
2. Run `python3 -m html2elementor your.html -o out.json`.
3. Import, screenshot, compare.
4. If something looks wrong, find the fix in `widgets.py` or `resolver.py`, add a test file to `tests/`, send a PR.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup.

---

## License

MIT. Use it, fork it, resell it in your SaaS, doesn't matter — just don't pretend you wrote it.

---

## Author

Built by [@dudaster](https://github.com/dudaster). If this saves you money on a commercial license, consider starring the repo.
