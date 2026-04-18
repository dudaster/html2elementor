# Architecture

High-level overview of how `html2elementor` turns HTML into Elementor JSON.

## Pipeline

```
HTML string
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ parser.py — BeautifulSoup walks DOM, extracts:          │
│   - tag, classes, text (direct), _order (child order)   │
│   - href (for <a>), src/alt (for <img>)                 │
│   - type/placeholder/name (for <input>)                 │
└─────────────────────────────────────────────────────────┘
  │  (list of nodes with placeholder `styles: {}`)
  ▼
┌─────────────────────────────────────────────────────────┐
│ resolver.py — computes styles for every node:           │
│   1. Parse <style> blocks with tinycss2                 │
│   2. Extract :root/html/body CSS custom properties      │
│   3. Match each rule's selector via soup.select()       │
│   4. Walk the DOM:                                      │
│      a. Inherit text/font properties from parent        │
│      b. Apply matched rules sorted by specificity       │
│      c. Apply inline `style=""` (highest)               │
│      d. Substitute var(--x) → hex                       │
│      e. Re-expand shorthands (background, border, …)    │
└─────────────────────────────────────────────────────────┘
  │  (each node now has a complete `styles: {k: v}` map)
  ▼
┌─────────────────────────────────────────────────────────┐
│ sections.py — splits the DOM into top-level sections    │
│   (<section>, <header>, <footer>, direct body children) │
└─────────────────────────────────────────────────────────┘
  │  (list of section nodes)
  ▼
┌─────────────────────────────────────────────────────────┐
│ containers.map_section — per section:                   │
│   - Compute container flex settings from CSS            │
│   - Header/footer → _build_header_elements (special)    │
│   - Otherwise → widgets.walk_and_emit                   │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ widgets._walk — recursive DOM→widget mapping:           │
│   - Buttons → button_widget                             │
│   - <a> plain text link → skip (inline)                 │
│   - <img> → image_widget                                │
│   - <input> → text-editor with inline <input> HTML      │
│   - Mixed inline content (div + spans) → text_widget    │
│   - Leaf div/span with text → leaf_text_widget          │
│     with badge / avatar detection                       │
│   - <div>.flex with label+content → list_row_widget     │
│   - <div>.flex with 2 content children → split layout   │
│   - <div> with multi-sibling card divs → card grid      │
│   - <div> with bg/radius/gradient → styled wrapper      │
│   - <div> with heading + 2+ anchors → link_list_widgets │
│   - Fallback → descend into children                    │
└─────────────────────────────────────────────────────────┘
  │  (list of widget dicts with `__inner_container__` marker)
  ▼
┌─────────────────────────────────────────────────────────┐
│ globals.py — consolidates site-kit globals:             │
│   - Extract 4 system role hints (primary/secondary/…)   │
│   - Build custom_colors + custom_typography with        │
│     page-unique hashed IDs                              │
│   - Rewrite widget color/typography refs →              │
│     globals/colors?id=<hash>                            │
└─────────────────────────────────────────────────────────┘
  │  (widgets now reference kit globals)
  ▼
┌─────────────────────────────────────────────────────────┐
│ builder.py — assembles final JSON tree:                 │
│   - Assign unique IDs to every container/widget         │
│   - Convert __inner_container__ → elType: "container"   │
│   - Convert widget specs → elType: "widget"             │
│   - Nest elements properly                              │
└─────────────────────────────────────────────────────────┘
  │
  ▼
{layout: [...], kit: {custom_colors, custom_typography}}
```

## Key data shapes

### Parsed DOM node
```python
{
    "tag": "div",
    "classes": ["hero", "dark"],
    "text": "Hello",                     # direct text (no children text)
    "styles": {"color": "#fff", ...},    # computed after resolver
    "_order": [("text", "Hi "), ("child", 0), ...],  # child order with inline text
    "children": [...],                    # nested nodes
    "src": "...", "href": "...",          # attribute extras
}
```

### Widget spec (pre-builder)
```python
{
    "widgetType": "heading",
    "settings": {
        "title": "Hello",
        "header_size": "h1",
        "title_color": "#ffffff",
        "typography_font_size": {"unit":"px","size":"64","sizes":[]},
        "_element_custom_width": {"unit":"px","size":820,"sizes":[]},
        "__globals__": {"title_color": "globals/colors?id=abc123"},
    },
}
```

### Inner container spec
```python
{
    "__inner_container__": True,    # becomes elType: container in builder
    "_no_group": True,              # optional: skip row-grouping
    "_grid_cols": 3,                # optional: chunk into rows of N
    "settings": {
        "flex_direction": "row",
        "background_background": "classic",
        "background_color": "#0b1220",
        ...
    },
    "children": [...],              # widgets or more inner containers
}
```

### Elementor output (post-builder)
```python
[
    {
        "id": "abc1234",
        "elType": "container",
        "settings": {...},
        "elements": [
            {
                "id": "def5678",
                "elType": "widget",
                "widgetType": "heading",
                "settings": {...},
                "elements": [],
            },
            ...
        ],
    },
    ...
]
```

## Why two kinds of containers

Elementor 3.x has a single "container" element type, but visually they split into:
- **Sections** — top-level containers, typically boxed width with padding
- **Inner containers** — nested flex layouts inside sections (rows of cards, split hero columns, etc.)

In the intermediate representation we tag the inner ones with `__inner_container__: True` so the builder knows the difference. Output-wise they're both `elType: "container"`.

## Why the widget-wrapping for fixed-width row children

In Elementor row containers, direct child widgets get this CSS:
```css
.elementor-element {
  width: var(--container-widget-width);
}
.e-con-inner > .elementor-widget {
  --container-widget-width: calc((1 - var(--container-widget-flex-grow)) * 100%);
}
```

For a row with flex-grow:1, `--container-widget-width` becomes `0`, so child widgets collapse. This makes it impossible to put a fixed-width heading (like "09:00" time label) directly in a row.

Workaround: wrap such widgets in an **inner container** with the width. Container widths work reliably; widget widths don't.

## Why `_no_group` exists

`_group_into_grids` in `containers.py` groups consecutive `__inner_container__` children (cards) into rows of N columns. Useful for card grids.

But some patterns produce `__inner_container__`s that are NOT cards and shouldn't be row-wrapped:
- Styled wrappers (divs with bg+radius that happen to produce containers)
- Avatar widgets (circular container with heading inside)
- Split hero columns (already arranged in their own row)

We mark these with `_no_group: True` so `_group_into_grids` leaves them alone.

## Why CSS variables need post-cascade substitution

tinycss2 parses `background: var(--color-brand)` as a literal `var(--color-brand)` token. At parse time we don't know what `--color-brand` resolves to, and `:root { --color-brand: #x }` might be defined in a different stylesheet / later in cascade order.

So we:
1. Extract ALL `--name: value` from `:root`/`html`/`body` first
2. Parse all other rules normally, leaving `var(...)` as literals
3. Apply cascade normally
4. THEN substitute vars in resolved styles
5. THEN re-run shorthand expansion (so `background: #x` after substitution populates `background-color`)

## Why system colors are forbidden

Elementor site kits have 4 "system" color slots: `primary`, `secondary`, `text`, `accent`. These are shared across every page on the site. If page A imports with `secondary: pink` and page B imports with `secondary: blue`, one of them overwrites the other and both pages break.

`html2elementor` avoids this entirely: every color used by a widget gets a `custom_colors` entry with a **hashed ID derived from the hex value**. Two pages using `#ec4899` share the same hash ID. Two pages using different hex values get different hash IDs. System slots stay untouched.

Same rule applies to `system_typography` (font-family globals).

## Why `verify.py` exists

Silent layout drift is the worst failure mode: the converter produces JSON that imports cleanly, but the rendered page looks subtly different from the source (wrong font size, missing bg color, spans losing color).

`verify.py` compares each emitted widget back to its source DOM node and flags mismatches in:
- Colors (exact match required)
- Font sizes (±2px tolerance)
- Padding / margins (±4px)
- Max-widths
- Section backgrounds

Running `verify` with zero issues is a weak but useful signal: it means the cascade was resolved correctly and typed through to widget settings. It does NOT guarantee pixel-perfect render — that requires a real browser screenshot diff.
