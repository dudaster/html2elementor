"""Map HTML tree nodes to Elementor widget specs."""
from __future__ import annotations
import re
from typing import Any, Iterator
from .colors import to_hex
from .styles import (
    text_align, apply_typography, apply_card_styling,
    px_to_int, parse_radius,
)

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
TEXT_TAGS = {"p", "blockquote"}
BUTTON_HINTS = ("btn", "button", "cta")


def walk_and_emit(node: dict, consumed: set[int] | None = None) -> list[dict]:
    results: list[dict] = []
    _walk(node, results, consumed or set())
    return results


def _walk(node: dict, out: list[dict], consumed: set[int]) -> None:
    if id(node) in consumed:
        return
    tag = node.get("tag", "")
    text = (node.get("text") or "").strip()
    class_str = " ".join(node.get("classes", [])).lower()

    if tag == "div" and is_icon_box(node):
        out.append(icon_box_widget(node))
        return

    if tag in HEADING_TAGS and (text or _first_text(node)):
        out.append(heading_widget(node))
        return

    if tag in TEXT_TAGS and (text or _first_text(node)):
        out.append(text_widget(node))
        return

    if tag == "button" or (tag == "a" and looks_like_button(node)):
        btn_text = text or _first_text(node)
        if btn_text:
            out.append(button_widget(node, btn_text))
            return

    # Link list column (footer column, sidebar): a div with multiple <a>
    # children — emit the heading + an icon-list widget.
    if tag == "div" and _is_link_list(node):
        out.extend(_link_list_widgets(node))
        return

    if tag == "img" and node.get("src"):
        out.append(image_widget(node))
        return

    # <ul> / <ol> with <li> items — emit as icon-list widget so bullets/numbers
    # and per-item typography render correctly. Without this, list items were
    # silently dropped because <li> had no dedicated handler.
    if tag in ("ul", "ol"):
        items = [c for c in node.get("children", []) if c.get("tag") == "li"]
        if items:
            out.append(_list_widget(node, items, ordered=(tag == "ol")))
            return

    # Input field (newsletter signup, search) — emit as heading div with
    # styled placeholder text. Elementor Free doesn't have a generic text
    # input widget, but a styled text placeholder looks identical visually.
    if tag == "input":
        input_type = (node.get("type") or "text").lower()
        if input_type in ("text", "email", "search", "url", "tel"):
            out.append(_input_widget(node))
            return


    # Div/span with mixed inline content (direct text + inline children like
    # <span>, <em>, <strong>, <b>, <i>). Example: brand "Paper<span>fold</span>".
    # Emit as a single leaf-text widget using _all_text_html to preserve both
    # the direct text AND nested inline markup + colors.
    if tag in ("div", "span") and text and node.get("children"):
        only_inline_children = all(
            c.get("tag") in ("span", "em", "i", "strong", "b")
            for c in node.get("children", [])
        )
        if only_inline_children:
            # Treat as a leaf — text_widget's short-text branch handles this
            # with proper inline span-color preservation via _all_text_html.
            out.append(text_widget(node))
            return

    # Leaf div/span with text but no children — emit as text-editor
    # Catches: badges/pills, taglines, prices, emoji decorations, etc.
    if tag in ("div", "span") and text and not node.get("children"):
        styles = node.get("styles", {})
        has_bg = bool(styles.get("background-color") or styles.get("background"))
        has_radius = bool(styles.get("border-radius") or styles.get("border-top-left-radius"))
        # Circular avatar: fixed-size square with bg + radius 50% → emit as circular container
        w_px = px_to_int(styles.get("width", ""))
        h_px = px_to_int(styles.get("height", ""))
        br_raw = styles.get("border-radius", "") or ""
        is_circular = "50%" in br_raw or "100%" in br_raw
        if has_bg and w_px and h_px and is_circular and abs(w_px - h_px) <= 2:
            out.append(_avatar_widget(node, w_px))
            return
        if has_bg and has_radius:
            out.append(_badge_widget(node))
        else:
            out.append(_leaf_text_widget(node))
        return

    # Inline image row: a flex div containing only img children (avatar stacks, logo bars)
    if tag == "div" and _is_image_row(node):
        out.append(_image_row_widget(node))
        return

    # Inline flex row: a div with display:flex containing 2+ leaf children (price + duration, etc.)
    if tag == "div" and _is_inline_flex_row(node):
        # Special case: "list row" (first child has fixed width, second is content).
        # Common for agenda/schedule/timeline slots. Elementor row containers handle
        # fixed+grow widths poorly, so we render as a single text-editor with
        # inline-styled HTML — reliable visual match without container nesting.
        if _is_list_row(node):
            out.append(_list_row_widget(node))
            return
        out.append(_inline_flex_row_widget(node, consumed))
        return

    # Card grid: a div with 2+ similar child divs (each has heading + content)
    if tag == "div" and _is_card_grid(node):
        cards = _emit_card_grid(node, consumed)
        if cards:
            parent_styles = node.get("styles", {})
            display = (parent_styles.get("display") or "").lower()
            flex_dir = (parent_styles.get("flex-direction") or "").lower()
            # Only wrap in row layout if parent is grid or flex-row.
            # block/flex-column → leave flat (parent container handles vertical stacking).
            is_row_layout = (display == "grid") or (display in ("flex", "inline-flex") and not flex_dir.startswith("column"))
            if is_row_layout:
                grid_cols = _get_grid_columns(node)
                grid_max_width = px_to_int(parent_styles.get("max-width"))
                grid_gap = px_to_int(parent_styles.get("gap"))
                # Capture fr proportions from grid-template-columns so
                # non-equal layouts (e.g. "1.5fr 1fr 1fr" for hero-bottom)
                # assign proportional widths instead of 32/32/32.
                from .containers import _parse_grid_tracks as _tracks
                grid_tracks = _tracks(parent_styles.get("grid-template-columns", ""))
                # align-items on the grid maps to Elementor's flex_align_items
                # ("end" → "flex-end" bottoms the columns, e.g. hero-bottom
                # where the stat numbers should line up with the CTA row).
                _AI_MAP = {"end": "flex-end", "start": "flex-start",
                           "center": "center", "stretch": "stretch",
                           "baseline": "baseline"}
                grid_align_items = _AI_MAP.get((parent_styles.get("align-items") or "").strip())
                # Margins on the grid wrapper itself (margin-top: 48px below
                # headings, margin-bottom before the next section) must ride
                # along to the row container. Otherwise sibling spacing is lost.
                grid_mt = px_to_int(parent_styles.get("margin-top"))
                grid_mb = px_to_int(parent_styles.get("margin-bottom"))
                # Padding-top/bottom (e.g. .hero-bottom { padding-top: 48px }
                # provides the gap between hero headline and stats row).
                grid_pt = px_to_int(parent_styles.get("padding-top"))
                grid_pb = px_to_int(parent_styles.get("padding-bottom"))
                # Border-top (often a horizontal divider line above a stats
                # or action row — purely visual but part of the spacing rhythm).
                grid_bt = px_to_int(parent_styles.get("border-top-width"))
                grid_btc = to_hex(parent_styles.get("border-top-color")) if grid_bt else None
                for card in cards:
                    card.pop("_no_group", None)
                if grid_cols or grid_max_width or grid_gap or grid_mt or grid_mb or grid_pt or grid_pb or grid_bt:
                    for card in cards:
                        if grid_cols:
                            card["_grid_cols"] = grid_cols
                        if grid_max_width:
                            card["_grid_max_width"] = grid_max_width
                        if grid_gap:
                            card["_grid_gap"] = grid_gap
                        if grid_mt or grid_mb:
                            card["_grid_margin"] = {"top": grid_mt or 0, "bottom": grid_mb or 0}
                        if grid_pt or grid_pb:
                            card["_grid_padding"] = {"top": grid_pt or 0, "bottom": grid_pb or 0}
                        if grid_bt:
                            card["_grid_border_top"] = {"width": grid_bt, "color": grid_btc or "#e5e5e5"}
                        if grid_tracks and len(grid_tracks) >= 2:
                            card["_grid_tracks"] = grid_tracks
                        if grid_align_items:
                            card["_grid_align_items"] = grid_align_items
            else:
                # Block / flex-column parent: mark cards so _group_into_grids skips them.
                for card in cards:
                    card["_no_group"] = True
            out.extend(cards)
            return

    # Styled wrapper div: has bg/gradient/radius → preserve as inner container
    # so its bg, padding, radius aren't lost when descending into children.
    if tag == "div" and _is_styled_wrapper(node):
        inner_children: list[dict] = []
        for child in node.get("children", []):
            _walk(child, inner_children, consumed)
        if inner_children:
            out.append(_styled_wrapper_container(node, inner_children))
            return

    # Before descending into children, check if this div has margin-bottom
    # that should be applied to its LAST child widget
    wrapper_mb = None
    if tag == "div":
        from .styles import px_to_int as _pxi2
        mb = _pxi2(node.get("styles", {}).get("margin-bottom"))
        if mb and mb > 0:
            wrapper_mb = mb

    before_len = len(out)
    for child in node.get("children", []):
        _walk(child, out, consumed)

    # Apply wrapper's margin-bottom to the last widget emitted from this div
    if wrapper_mb and len(out) > before_len:
        last = out[-1]
        s = last.get("settings", {})
        existing = s.get("_margin", {})
        s["_margin"] = {
            "unit": "px",
            "top": existing.get("top", "0"),
            "right": existing.get("right", "0"),
            "bottom": str(wrapper_mb),
            "left": existing.get("left", "0"),
            "isLinked": False,
        }


# --- detection ---

def looks_like_button(node: dict) -> bool:
    # Card-link: an <a> that wraps a heading + paragraph block (like
    # `.docs-hub-card` with h3/p/span inside) is a styled card, not a button.
    # Buttons never contain a heading or a paragraph.
    kids_iter = _iter(node, max_depth=3)
    has_heading = any(c is not node and c.get("tag") in HEADING_TAGS for c in kids_iter)
    has_para = any(c is not node and c.get("tag") in TEXT_TAGS for c in _iter(node, max_depth=3))
    if has_heading or has_para:
        return False

    classes = " ".join(node.get("classes", [])).lower()
    styles = node.get("styles", {})
    bg = styles.get("background-color") or styles.get("backgroundColor")
    has_bg = bool(bg and bg not in ("transparent", "none"))
    has_radius = bool(styles.get("border-radius") or styles.get("borderRadius"))
    has_padding_val = styles.get("padding-top") or styles.get("paddingTop") or ""
    has_padding = bool(has_padding_val and has_padding_val not in ("0px", "0"))
    has_border_val = styles.get("border-top-width") or styles.get("borderTopWidth") or ""
    has_border = bool(has_border_val and has_border_val not in ("0px", "0"))
    # A button must have background or border — radius+padding alone is a styled link.
    has_hint = any(h in classes for h in BUTTON_HINTS)
    if has_hint and (has_bg or has_border):
        return True
    if has_bg and (has_radius or has_padding or has_border):
        return True  # solid button
    if has_border and has_padding:
        return True  # ghost/outline button
    return False


def is_icon_box(node: dict) -> bool:
    children = node.get("children", [])
    if len(children) < 2 or len(children) > 6:
        return False
    has_icon = has_heading = has_text = False
    for c in _iter(node, max_depth=2):
        if c is node:
            continue
        t = c.get("tag")
        if t == "svg" or (t == "i" and "icon" in " ".join(c.get("classes", [])).lower()):
            has_icon = True
        # Only real icon elements (font-awesome <i>, not emoji divs)
        if t == "i" and "icon" in " ".join(c.get("classes", [])).lower():
            has_icon = True
        if t in HEADING_TAGS:
            has_heading = True
        if t in TEXT_TAGS:
            has_text = True
    if not (has_icon and has_heading and has_text):
        return False
    # If too many headings/paragraphs, it's a grid of cards not a single icon-box
    n_headings = sum(1 for c in _iter(node, max_depth=2) if c is not node and c.get("tag") in HEADING_TAGS)
    n_texts = sum(1 for c in _iter(node, max_depth=2) if c is not node and c.get("tag") in TEXT_TAGS)
    if n_headings > 2 or n_texts > 2:
        return False
    return True


def is_hero_bg_image(node: dict, section: dict) -> bool:
    if node.get("tag") != "img" or not node.get("src"):
        return False
    styles = node.get("styles", {})
    # Small images (avatars, icons, thumbnails) are never bg images
    from .styles import px_to_int
    w = px_to_int(styles.get("width"))
    h = px_to_int(styles.get("height"))
    if w and w < 200:
        return False
    if h and h < 200:
        return False
    pos = styles.get("position", "")
    obj = styles.get("object-fit", "")
    classes = " ".join(node.get("classes", [])).lower()
    return (pos == "absolute" or
            (obj == "cover" and "w-full" in classes and "h-full" in classes) or
            "absolute" in classes)


# --- widget builders ---

def heading_widget(node: dict) -> dict:
    tag = node["tag"]
    # Collect ALL text including children (spans, em, strong, etc.)
    text = _all_text(node).strip()
    styles = node.get("styles", {})
    # If the heading has an explicit color in CSS, use it.
    # If it inherits (no color set), default to "text" global (body color).
    explicit_color = styles.get("color")
    has_explicit = bool(explicit_color and explicit_color not in ("inherit", "initial"))

    settings: dict[str, Any] = {
        "title": text,
        "header_size": tag,
        "align": text_align(styles),
        "__globals__": {"title_color": "globals/colors?id=text"},
    }
    if has_explicit:
        color_hex = to_hex(explicit_color)
        if color_hex:
            settings["title_color"] = color_hex
            del settings["__globals__"]["title_color"]

    apply_typography(settings, styles)
    _apply_margin(settings, styles)
    _apply_max_width_and_self_align(settings, styles)
    return {"widgetType": "heading", "settings": settings}


def text_widget(node: dict) -> dict:
    rich_text = _all_text_html(node).strip()
    # Strip HTML tags for length check (we care about visible chars)
    plain_text = re.sub(r"<[^>]+>", "", rich_text)
    styles = node.get("styles", {})

    # Short text (≤50 chars) → heading widget with div tag (better typography control)
    if len(plain_text) <= 50:
        settings: dict[str, Any] = {
            "title": rich_text,
            "header_size": "div",
            "align": text_align(styles),
            "__globals__": {"title_color": "globals/colors?id=text"},
        }
        color_hex = to_hex(styles.get("color"))
        if color_hex:
            settings["title_color"] = color_hex
            del settings["__globals__"]["title_color"]
        apply_typography(settings, styles)
        _apply_margin(settings, styles)
        _apply_max_width_and_self_align(settings, styles)
        return {"widgetType": "heading", "settings": settings}

    # Longer paragraphs → text-editor
    settings = {
        "editor": f"<p>{rich_text}</p>",
        "align": text_align(styles),
        "__globals__": {"text_color": "globals/colors?id=text"},
    }
    color_hex = to_hex(styles.get("color"))
    if color_hex:
        settings["text_color"] = color_hex
        del settings["__globals__"]["text_color"]
    apply_typography(settings, styles)
    _apply_margin(settings, styles)
    _apply_max_width_and_self_align(settings, styles)
    return {"widgetType": "text-editor", "settings": settings}


def button_widget(node: dict, text: str) -> dict:
    from .colors import darken
    href = node.get("href", "#")
    styles = node.get("styles", {})
    bg = styles.get("background-color") or styles.get("backgroundColor")
    radius = styles.get("border-radius") or styles.get("borderRadius") or "0px"
    is_ghost = not bg or bg in ("transparent", "none")

    settings: dict[str, Any] = {
        "text": text,
        "link": {"url": href, "is_external": False, "nofollow": False},
        "size": "md",
        "align": text_align(styles),
        "border_radius": parse_radius(radius),
    }

    if is_ghost:
        # Check: is it a text-link style (no border at all) or outlined (has border)?
        has_real_border = bool(
            styles.get("border") or
            (styles.get("border-top-width") or styles.get("borderTopWidth") or "0px") not in ("0px", "0", "")
        )
        settings["background_color"] = "#ffffff00"  # transparent

        if has_real_border:
            border_hex = to_hex(styles.get("border-color") or styles.get("border-top-color")
                               or styles.get("borderColor") or styles.get("borderTopColor"))
            bw_val = str(px_to_int(styles.get("border-top-width") or
                                    styles.get("borderTopWidth") or
                                    styles.get("border-width") or "1") or 1)
            settings["border_border"] = "solid"
            settings["border_width"] = {
                "unit": "px", "top": bw_val, "right": bw_val,
                "bottom": bw_val, "left": bw_val, "isLinked": True,
            }
            if border_hex:
                settings["border_color"] = border_hex
            settings["button_background_hover_color"] = "#00000010"
        else:
            # Pure text link styled as button — no border, no bg, just colored text
            settings["border_border"] = "none"
            settings["border_radius"] = {"unit": "px", "top": "0", "right": "0", "bottom": "0", "left": "0", "isLinked": True}
            settings["_padding"] = {"unit": "px", "top": "0", "right": "0", "bottom": "0", "left": "0", "isLinked": True}

        text_hex = to_hex(styles.get("color"))
        if text_hex:
            settings["button_text_color"] = text_hex
            settings["hover_color"] = darken(text_hex, 0.15)
    else:
        bg_hex = to_hex(bg)
        if bg_hex:
            settings["background_color"] = bg_hex
            settings["button_background_hover_color"] = darken(bg_hex, 0.12)
        text_hex = to_hex(styles.get("color"))
        if text_hex:
            settings["button_text_color"] = text_hex
            settings["hover_color"] = text_hex

    apply_typography(settings, styles)

    # Hover: if source CSS has an explicit :hover rule on this button, prefer
    # those values over the darken-heuristic defaults above. Covers the
    # common case of a color flip (.btn-lime:hover { background: var(--ink);
    # color: var(--lime); }) where "darken by 12%" produces the wrong color.
    hover = node.get("hover_styles") or {}
    if hover:
        hbg = to_hex(hover.get("background-color") or hover.get("background"))
        if hbg:
            settings["button_background_hover_color"] = hbg
        hcol = to_hex(hover.get("color"))
        if hcol:
            settings["hover_color"] = hcol
        hbc = to_hex(hover.get("border-color") or hover.get("border-top-color"))
        if hbc:
            settings["button_hover_border_color"] = hbc

    # Read padding from CSS (if not already set by ghost text-link path)
    if "_padding" not in settings:
        from .styles import css_padding_to_elementor as _pad
        p = _pad(styles)
        if any(p[k] != "0" for k in ("top", "right", "bottom", "left")):
            settings["text_padding"] = p
    return {"widgetType": "button", "settings": settings}


def _list_widget(node: dict, items: list[dict], ordered: bool = False) -> dict:
    """Emit <ul>/<ol> + <li> as an Elementor icon-list widget.
    Each <li>'s text becomes an item; per-item CSS styling isn't preserved
    beyond color + font from the list or first item.
    Ordered lists use numeric markers, unordered ones use default arrow/dot."""
    from .styles import apply_typography as _at, px_to_int as _px
    list_styles = node.get("styles", {})
    first_item_styles = items[0].get("styles", {}) if items else {}
    icon_items = []
    for li in items:
        text = _all_text_html(li).strip()
        if not text:
            continue
        icon_items.append({
            "text": text,
            "link": {"url": "", "is_external": False},
            "selected_icon": {"value": "", "library": ""},
        })
    if not icon_items:
        return {"widgetType": "text-editor", "settings": {"editor": ""}}
    # Space between items from CSS gap or li margin-bottom
    gap = _px(list_styles.get("gap", "")) or _px(first_item_styles.get("margin-bottom", "")) or 10
    settings: dict[str, Any] = {
        "view": "traditional",
        "space_between": {"unit": "px", "size": gap, "sizes": []},
        "icon_list": icon_items,
    }
    # Color: from list-level CSS or first li (both are valid cascade paths)
    color = to_hex(list_styles.get("color")) or to_hex(first_item_styles.get("color"))
    if color:
        settings["text_color"] = color
    # Typography (font family/size/weight) — apply with icon-list prefix so
    # Elementor targets the item labels, not the icon glyph.
    tmp: dict = {}
    _at(tmp, first_item_styles)
    for k, v in tmp.items():
        if k == "typography_typography":
            settings["icon_typography_typography"] = v
        elif k.startswith("typography_"):
            settings["icon_" + k] = v
    # The <ul>/<ol> itself may carry margin (e.g. `.proband-points
    # { margin: 24px 0 32px }` — 24px breathing room above, 32px to the
    # button below). Apply it on the widget so sibling spacing survives.
    _apply_margin(settings, list_styles)
    return {"widgetType": "icon-list", "settings": settings}


def _input_widget(node: dict) -> dict:
    """Emit an input field as a heading widget with inline HTML containing a
    styled <input>. Elementor Free lacks a form input widget but renders inline
    HTML. This gives a visually identical text-input even though it's not
    functionally connected to a form backend."""
    placeholder = (node.get("placeholder") or "").strip() or ""
    input_type = node.get("type") or "text"
    name = node.get("name") or ""
    styles = node.get("styles", {})
    # Read box styles for visual match
    bg = to_hex(styles.get("background-color") or styles.get("background") or "")
    tc = to_hex(styles.get("color"))
    border_c = to_hex(styles.get("border-color") or styles.get("border-top-color"))
    radius = px_to_int(styles.get("border-radius", "")) or 8
    # Build inline HTML input
    css_parts = [
        "width:100%", "padding:14px 18px",
        f"border-radius:{radius}px",
        f"border:1px solid {border_c or '#d4d4d8'}",
        f"background:{bg or '#ffffff'}",
        f"color:{tc or '#111827'}",
        "font-size:14px", "font-family:inherit", "outline:none",
        "box-sizing:border-box",
    ]
    style_attr = ";".join(css_parts)
    name_attr = f' name="{_escape(name)}"' if name else ""
    html = (
        f'<input type="{input_type}" placeholder="{_escape(placeholder)}"{name_attr} '
        f'style="{style_attr}">'
    )
    return {
        "widgetType": "text-editor",
        "settings": {
            "editor": html,
            "align": "left",
            "_flex_size": "grow",
        },
    }


def _collect_link_nodes(node: dict) -> list[dict]:
    """Collect <a> tags from direct children or from a <ul>/<ol> → <li> → <a> subtree."""
    children = node.get("children", [])
    direct = [c for c in children if c.get("tag") == "a"]
    if direct:
        return direct
    for c in children:
        if c.get("tag") in ("ul", "ol"):
            links = []
            for li in c.get("children", []):
                if li.get("tag") == "li":
                    for a in li.get("children", []):
                        if a.get("tag") == "a":
                            links.append(a)
                            break
            if links:
                return links
    return []


def _is_link_list(node: dict) -> bool:
    """A div whose meaningful children are: 0-1 heading + N plain anchors (or ul/li/a).
    Button-like anchors are allowed alongside plain links — they'll be emitted separately.

    Card-link grids (each <a> wraps a heading + paragraph) are explicitly NOT
    link lists. Those should flow through the card-grid path so each card
    preserves its visual structure (icon + title + description + metadata)."""
    children = node.get("children", [])
    if len(children) < 2:
        return False
    link_nodes = _collect_link_nodes(node)
    plain_links = [a for a in link_nodes if not looks_like_button(a)]
    if len(plain_links) < 2:
        return False
    # If any plain link contains a heading or paragraph, treat it as a card,
    # not a nav link — bail out so the card-grid path picks it up.
    for a in plain_links:
        has_block_content = any(
            c is not a and c.get("tag") in (*HEADING_TAGS, *TEXT_TAGS)
            for c in _iter(a, max_depth=3)
        )
        if has_block_content:
            return False
    allowed_tags = {"a", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"}
    for c in children:
        if c.get("tag") not in allowed_tags:
            return False
    return True


def _link_list_widgets(node: dict) -> list[dict]:
    """Emit: optional heading + icon-list of plain links + button for any CTA anchor."""
    from .styles import apply_typography as _at, px_to_int as _px
    out: list[dict] = []
    heading_node = None
    for c in node.get("children", []):
        if c.get("tag") in ("h1", "h2", "h3", "h4", "h5", "h6") and heading_node is None:
            heading_node = c
    all_links = _collect_link_nodes(node)
    link_nodes = [a for a in all_links if not looks_like_button(a)]
    btn_nodes = [a for a in all_links if looks_like_button(a)]

    # Heading
    if heading_node:
        h_styles = heading_node.get("styles", {})
        h_settings: dict[str, Any] = {
            "title": _escape((heading_node.get("text") or "").strip()),
            "header_size": heading_node.get("tag", "h4"),
            "align": text_align(h_styles),
        }
        h_color = to_hex(h_styles.get("color"))
        if h_color:
            h_settings["title_color"] = h_color
        _at(h_settings, h_styles)
        _apply_margin(h_settings, h_styles)
        out.append({"widgetType": "heading", "settings": h_settings})

    # Icon list of plain links
    if link_nodes:
        first_styles = link_nodes[0].get("styles", {})
        items = []
        for a in link_nodes:
            items.append({
                "text": (a.get("text") or "").strip(),
                "link": {"url": a.get("href", "#"), "is_external": False},
                "selected_icon": {"value": "", "library": ""},
            })
        list_settings: dict[str, Any] = {
            "view": "traditional",
            "space_between": {"unit": "px", "size": 10, "sizes": []},
            "icon_list": items,
        }
        link_color = to_hex(first_styles.get("color"))
        if link_color:
            list_settings["text_color"] = link_color
        tmp: dict = {}
        _at(tmp, first_styles)
        for k, v in tmp.items():
            if k == "typography_typography":
                list_settings["icon_typography_typography"] = v
            elif k.startswith("typography_"):
                list_settings["icon_" + k] = v
        out.append({"widgetType": "icon-list", "settings": list_settings})

    # Button-like anchors (e.g. nav CTA) emitted as button widgets
    for a in btn_nodes:
        out.append(button_widget(a, (a.get("text") or "").strip()))

    return out


def _is_list_row(node: dict) -> bool:
    """A flex row with exactly 2 children: first is a fixed-width leaf (label),
    second is a div with text content. Common for agenda/schedule slots."""
    children = node.get("children", [])
    if len(children) != 2:
        return False
    first, second = children
    # First child: fixed width in px, leaf text (no complex children)
    first_styles = first.get("styles", {})
    w = px_to_int(first_styles.get("width", ""))
    if not w or w > 200:
        return False
    if not (first.get("text") or "").strip() or first.get("children"):
        return False
    # Second child: div with text content (heading + paragraph)
    if second.get("tag") != "div":
        return False
    # Must have a heading or paragraph inside
    has_text_content = any(
        c.get("tag") in ("h1", "h2", "h3", "h4", "h5", "h6", "p")
        for c in _iter(second, max_depth=2)
    )
    return has_text_content


def _list_row_widget(node: dict) -> dict:
    """Emit a flex-row "list row" (agenda slot, timeline entry) as a single
    text-editor with inline-styled HTML. The label sits left via float/margin
    tricks, heading + description flow naturally to the right."""
    children = node.get("children", [])
    label_node, content_node = children[0], children[1]
    label_text = (label_node.get("text") or "").strip()
    label_styles = label_node.get("styles", {})
    label_w = px_to_int(label_styles.get("width", "")) or 100
    label_color = to_hex(label_styles.get("color")) or "inherit"
    label_weight = label_styles.get("font-weight", "700")
    label_size = px_to_int(label_styles.get("font-size", "")) or 16

    # Build content HTML from the right side (heading + paragraph)
    parts: list[str] = []
    for gc in content_node.get("children", []):
        gc_tag = gc.get("tag", "")
        gc_text = _all_text_html(gc).strip()
        if not gc_text:
            continue
        gc_styles = gc.get("styles", {})
        gc_color = to_hex(gc_styles.get("color"))
        gc_size = px_to_int(gc_styles.get("font-size", ""))
        gc_weight = gc_styles.get("font-weight", "400")
        if gc_tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            fs = gc_size or 19
            parts.append(
                f'<strong style="display:block;font-size:{fs}px;font-weight:{gc_weight};'
                f'color:{gc_color or "inherit"};margin-bottom:6px">{gc_text}</strong>'
            )
        else:
            fs = gc_size or 14
            parts.append(
                f'<span style="display:block;font-size:{fs}px;color:{gc_color or "inherit"};line-height:1.6">{gc_text}</span>'
            )

    gap = px_to_int(node.get("styles", {}).get("gap", "")) or 32
    content_html = "".join(parts)
    # Two-column layout via inline-block + padding offset on content
    editor_html = (
        f'<div style="position:relative;padding-left:{label_w + gap}px;min-height:1em">'
        f'<strong style="position:absolute;left:0;top:0;width:{label_w}px;'
        f'color:{label_color};font-size:{label_size}px;font-weight:{label_weight};'
        f'letter-spacing:1px">{label_text}</strong>'
        f'{content_html}'
        f'</div>'
    )
    return {
        "widgetType": "text-editor",
        "settings": {"editor": editor_html, "align": "left"},
    }


def _is_inline_flex_row(node: dict) -> bool:
    """A div with display:flex that should be rendered as a horizontal row."""
    styles = node.get("styles", {})
    display = styles.get("display", "")
    direction = styles.get("flex-direction", "row")
    if display != "flex" or direction not in ("row", ""):
        return False
    children = node.get("children", [])
    return len(children) >= 2 and len(children) <= 6


def _inline_flex_row_widget(node: dict, consumed: set[int]) -> dict:
    """Emit children of a flex-row div in a horizontal container."""
    styles = node.get("styles", {})
    jc = styles.get("justify-content", "flex-start")
    gap = px_to_int(styles.get("gap", "8"))
    jc_map = {
        "space-between": "space-between",
        "space-around": "space-around",
        "center": "center",
        "flex-end": "flex-end",
    }
    # Split layout: exactly 2 children with flex:1 on both (or no fixed widths)
    # → emit as 2 inner containers each taking 50% width.
    row_children = [c for c in node.get("children", []) if c.get("tag") in ("div", "section", "article")]
    is_split = False
    if len(row_children) == 2:
        both_no_fixed = all(
            not px_to_int(c.get("styles", {}).get("width", "")) for c in row_children
        )
        # Heuristic: both children have substantial content (so we want
        # side-by-side columns, not time+desc label row)
        both_content = all(
            any(n.get("tag") in ("h1", "h2", "h3", "img", "p") for n in _iter(c, max_depth=3))
            for c in row_children
        )
        is_split = both_no_fixed and both_content

    child_widgets: list[dict] = []
    if is_split:
        parent_ai = (styles.get("align-items") or "center").lower()
        ai_map = {"center": "center", "flex-start": "flex-start",
                  "flex-end": "flex-end", "stretch": "stretch"}
        split_ai = ai_map.get(parent_ai, "center")
        for child in row_children:
            sub_widgets: list[dict] = []
            _walk(child, sub_widgets, consumed)
            if not sub_widgets:
                continue
            child_widgets.append({
                "__inner_container__": True,
                "_no_group": True,
                "settings": {
                    "content_width": "full",
                    "flex_direction": "column",
                    "flex_align_items": "flex-start",
                    "flex_gap": {"unit": "px", "size": 12, "column": "12", "row": "12"},
                    "_element_width": "initial",
                    "_element_custom_width": {"unit": "%", "size": 48, "sizes": []},
                    "_element_width_mobile": "initial",
                    "_element_custom_width_mobile": {"unit": "%", "size": 100, "sizes": []},
                },
                "children": sub_widgets,
            })
        return {
            "__inner_container__": True,
            "_no_group": True,
            "settings": {
                "content_width": "full",
                "flex_direction": "row",
                "flex_direction_mobile": "column",
                "flex_justify_content": jc_map.get(jc, "center"),
                "flex_align_items": split_ai,
                "flex_gap": {"unit": "px", "size": gap, "column": str(gap), "row": str(gap)},
            },
            "children": child_widgets,
        }

    for child in node.get("children", []):
        child_tag = child.get("tag", "")
        child_children = child.get("children", [])
        # If child is a div with multiple children, decide: merge into single
        # text-editor (similar-sized text) or emit as separate widgets
        # (very different sizes like stat num + desc)
        child_children_sizes = [
            px_to_int(gc.get("styles", {}).get("font-size", "16")) or 16
            for gc in child_children if (gc.get("text") or "").strip()
        ]
        size_diff = (max(child_children_sizes) - min(child_children_sizes)) if child_children_sizes else 0
        # Only merge if font sizes are close (e.g., name 16 + role 14)
        # Don't merge if big number + small label (56 vs 15)
        # Don't merge if any grandchild is a heading (h1-h6) — preserves semantic headings
        has_heading_child = any(
            gc.get("tag") in ("h1", "h2", "h3", "h4", "h5", "h6")
            for gc in child_children
        )
        should_merge = size_diff <= 6 and not has_heading_child
        if child_tag == "div" and len(child_children) >= 2 and not _is_inline_flex_row(child) and should_merge:
            # Merge child div's text content into a single text-editor widget
            # (avoids nested container width issues in Elementor row flex)
            parts = []
            for gc in child_children:
                gc_text = (gc.get("text") or "").strip()
                gc_styles = gc.get("styles", {})
                gc_weight = gc_styles.get("font-weight", "400")
                if gc_text:
                    if gc_weight in ("700", "800", "900", "bold"):
                        parts.append(f"<strong>{gc_text}</strong>")
                    else:
                        parts.append(gc_text)
            if parts:
                html_content = "<br>".join(parts)
                child_widgets.append({
                    "widgetType": "text-editor",
                    "settings": {"editor": html_content},
                })
            consumed.add(id(child))
            for gc in child_children:
                consumed.add(id(gc))
        elif child_tag == "div" and len(child_children) >= 2 and not _is_inline_flex_row(child):
            # Different-sized content inside a flex-row parent.
            # Two sub-patterns:
            #   A) "stat" style (parent justify-content center, content centered):
            #      emit as narrow centered column (e.g. big number + small label).
            #   B) "agenda" style (parent justify-content start, content left-aligned):
            #      content grows, left-aligned, no fixed width (heading + description).
            inner_widgets: list[dict] = []
            for gc in child_children:
                _walk(gc, inner_widgets, consumed)
            if inner_widgets:
                parent_jc = jc  # from outer _inline_flex_row_widget scope
                parent_ta = (styles.get("text-align") or "").lower()
                is_centered_parent = parent_jc == "center" or parent_ta == "center"
                if is_centered_parent:
                    inner_settings = {
                        "content_width": "full",
                        "flex_direction": "column",
                        "flex_align_items": "center",
                        "flex_gap": {"unit": "px", "size": 8, "column": "8", "row": "8"},
                        "_element_custom_width": {"unit": "%", "size": 30, "sizes": []},
                        "_element_width": "initial",
                    }
                else:
                    # Agenda-style: content grows to fill remaining row space, left-aligned.
                    # Use flex-grow with flex-basis:0 (via _flex_size grow + min-width override)
                    # Elementor's container flex-grow alone allows content to overflow the row,
                    # so we pair it with _element_custom_width calculated from parent.
                    child_styles = child.get("styles", {})
                    child_ta = (child_styles.get("text-align") or "left").lower()
                    align_map = {"left": "flex-start", "right": "flex-end", "center": "center"}
                    inner_settings = {
                        "content_width": "full",
                        "flex_direction": "column",
                        "flex_align_items": align_map.get(child_ta, "flex-start"),
                        "flex_gap": {"unit": "px", "size": 4, "column": "4", "row": "4"},
                        "_flex_size": "grow",
                        "_flex_shrink": 1,
                        "_flex_basis": {"unit": "px", "size": 0, "sizes": []},
                        "_flex_grow": 1,
                    }
                    # Force left-alignment on child widgets to match content flow
                    if child_ta == "left":
                        for w in inner_widgets:
                            ws = w.get("settings", {})
                            if "align" in ws or w.get("widgetType") in ("heading", "text-editor"):
                                ws["align"] = "left"
                                w["settings"] = ws
                child_widgets.append({
                    "__inner_container__": True,
                    "settings": inner_settings,
                    "children": inner_widgets,
                })
            consumed.add(id(child))
        else:
            sub_widgets: list[dict] = []
            _walk(child, sub_widgets, consumed)
            if not sub_widgets:
                continue
            # Only wrap in a fixed-width container when the CSS explicitly
            # specifies a width on a div child (e.g. agenda `.time { width: 100px }`).
            # Plain buttons/anchors/leaves shouldn't be wrapped — they work
            # directly in row flex.
            child_styles = child.get("styles", {})
            w_px = px_to_int(child_styles.get("width", ""))
            if child_tag == "div" and w_px and not (
                len(sub_widgets) == 1 and sub_widgets[0].get("__inner_container__")
            ):
                child_widgets.append({
                    "__inner_container__": True,
                    "settings": {
                        "content_width": "full",
                        "flex_direction": "column",
                        "flex_align_items": "flex-start",
                        "flex_gap": {"unit": "px", "size": 4, "column": "4", "row": "4"},
                        "_flex_size": "none",
                        "_element_width": "initial",
                        "_element_custom_width": {"unit": "px", "size": w_px, "sizes": []},
                    },
                    "children": sub_widgets,
                })
            else:
                child_widgets.extend(sub_widgets)

    # Align items: respect CSS align-items, default stretch for left-aligned rows
    css_ai = styles.get("align-items", "")
    ai_map = {"flex-start": "flex-start", "center": "center", "flex-end": "flex-end", "stretch": "stretch"}
    flex_ai = ai_map.get(css_ai, "flex-start" if jc_map.get(jc) == "flex-start" else "center")
    # Respect CSS flex-wrap: wrap → Elementor flex_wrap so children wrap to new
    # lines when viewport shrinks (trusted logos, tag clouds, button groups).
    css_fw = (styles.get("flex-wrap") or "").lower()
    fw_settings = {}
    if css_fw == "wrap":
        fw_settings["flex_wrap"] = "wrap"
        fw_settings["flex_wrap_tablet"] = "wrap"
        fw_settings["flex_wrap_mobile"] = "wrap"

    return {
        "__inner_container__": True,
        "settings": {
            "content_width": "full",
            "flex_direction": "row",
            # On mobile, default to column stack (widgets hog width anyway)
            "flex_direction_mobile": "column",
            "flex_justify_content": jc_map.get(jc, "flex-start"),
            "flex_align_items": flex_ai,
            "flex_gap": {"unit": "px", "size": gap, "column": str(gap), "row": str(gap)},
            **fw_settings,
        },
        "children": child_widgets,
    }


def _get_grid_columns(node: dict) -> int | None:
    """Read grid-template-columns from CSS and return column count."""
    import re
    styles = node.get("styles", {})
    gtc = styles.get("grid-template-columns", "")
    if not gtc:
        return None
    # repeat(N, 1fr)
    m = re.search(r"repeat\(\s*(\d+)", gtc)
    if m:
        return int(m.group(1))
    # Count explicit columns (e.g., "1fr 1fr 1fr")
    fracs = gtc.strip().split()
    if len(fracs) >= 2:
        return len(fracs)
    return None


def _is_image_row(node: dict) -> bool:
    """A div with 2+ img children (avatar row, logo bar)."""
    children = node.get("children", [])
    imgs = [c for c in children if c.get("tag") == "img"]
    return len(imgs) >= 2 and len(imgs) == len(children)


def _image_row_widget(node: dict) -> dict:
    """Emit a horizontal row of image widgets."""
    images = []
    for child in node.get("children", []):
        if child.get("tag") == "img":
            images.append(image_widget(child))
    return {
        "__inner_container__": True,
        "settings": {
            "content_width": "full",
            "flex_direction": "row",
            "flex_justify_content": "center",
            "flex_align_items": "center",
            "flex_gap": {"unit": "px", "size": 0, "column": "0", "row": "0"},
        },
        "children": images,
    }


def _is_card_grid(node: dict) -> bool:
    """A div with 2+ direct child divs that each have meaningful content.
    Content = heading/p/blockquote tags OR leaf divs/spans with text.
    Returns False for:
    - Parents with sibling heading/paragraph content outside the card divs
      (regular section with mixed content, not a card grid)
    - Pure centering wrappers (e.g. `.container` with only max-width + margin auto
      and no display:grid / flex → just a width limiter; descend transparently)
    - Children with structurally different shapes (one has direct heading,
      another has grid of sub-cards)."""
    all_children = node.get("children", [])
    # Cards are usually <div>s, but card-link grids (docs-hub-style) use
    # <a> as the outer wrapper when each card is also the click target.
    # Count those too — an <a> with block content (heading/paragraph) is a
    # card wrapper, not a button or nav link.
    def _is_card_wrapper(c):
        if c.get("tag") == "div":
            return True
        if c.get("tag") == "a":
            return any(
                n is not c and n.get("tag") in (*HEADING_TAGS, *TEXT_TAGS)
                for n in _iter(c, max_depth=3)
            )
        return False
    children = [c for c in all_children if _is_card_wrapper(c)]
    if len(children) < 2:
        return False
    # Non-div siblings (h1-h6, p) OUTSIDE the card divs must NOT be content
    content_sibling_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p",
                             "ul", "ol", "table", "blockquote", "figure"}
    for c in all_children:
        if c.get("tag") in content_sibling_tags:
            text = (c.get("text") or "").strip()
            if text or c.get("children"):
                return False
    # Pure centering wrapper: no display flex/grid, has max-width, no bg/radius
    styles = node.get("styles", {})
    display = (styles.get("display") or "").lower()
    if display not in ("flex", "inline-flex", "grid"):
        has_max_width = bool(styles.get("max-width"))
        has_bg = bool(styles.get("background") or styles.get("background-color"))
        has_radius = bool(styles.get("border-radius"))
        if has_max_width and not has_bg and not has_radius:
            return False  # .container-style width limiter
    # Reject if any child has ITSELF a nested card-grid pattern (3+ sibling
    # similar divs) — that's a meta-container, should descend instead.
    # Example: .container has .feature-header + .feature-grid (where
    # .feature-grid has 3 card divs).
    for c in children:
        gc_divs = [gc for gc in c.get("children", []) if gc.get("tag") == "div"]
        if len(gc_divs) >= 3:
            # Check if those grandchildren are "card-shaped" (have content)
            nested_cards = sum(
                1 for gc in gc_divs
                if any(n.get("tag") in ("h1", "h2", "h3", "h4", "h5", "h6", "p")
                       for n in _iter(gc, max_depth=3))
            )
            if nested_cards >= 3:
                return False
    # A card counts as having content if it has a heading/text tag, an
    # image, or any leaf text. Without `img` here, purely-visual columns
    # (side-by-side split: text left, image right) falsely reject as
    # card grids and the whole row collapses into a single column stack.
    CARD_CONTENT_TAGS = HEADING_TAGS | TEXT_TAGS | {"blockquote", "img", "svg", "picture"}
    for c in children:
        has_tag_content = any(
            n.get("tag") in CARD_CONTENT_TAGS for n in _iter(c, max_depth=3)
        )
        has_leaf_text = any(
            (n.get("text") or "").strip() and not n.get("children")
            for n in _iter(c, max_depth=3) if n is not c
        )
        if not (has_tag_content or has_leaf_text):
            return False
    return True


def _emit_card_grid(node: dict, consumed: set[int]) -> list[dict]:
    """Emit child divs as individual card containers (each walks its content).
    <a> children with block content are also treated as cards (docs-hub-style
    clickable cards); the href is preserved on the container's link setting."""
    def _is_card(c):
        if c.get("tag") == "div":
            return True
        if c.get("tag") == "a":
            return any(
                n is not c and n.get("tag") in (*HEADING_TAGS, *TEXT_TAGS)
                for n in _iter(c, max_depth=3)
            )
        return False
    children = [c for c in node.get("children", []) if _is_card(c)]
    cards: list[dict] = []
    for child in children:
        # Check if it's an icon-box (has svg)
        if is_icon_box(child):
            cards.append(icon_box_widget(child))
        else:
            # Generic text card — wrap child's content as a container
            card_elements: list[dict] = []
            _walk(child, card_elements, consumed)
            if card_elements:
                from .styles import px_to_int as _pxi

                card_styles = child.get("styles", {})
                ta = card_styles.get("text-align", "left")

                # Detect image-top card pattern: first child is <img>, rest is content
                has_top_image = (
                    card_elements and
                    card_elements[0].get("widgetType") == "image" and
                    len(card_elements) > 1
                )

                # Find content wrapper with padding
                content_wrapper = None
                for gc in child.get("children", []):
                    if gc.get("tag") == "div" and gc.get("children"):
                        gc_pad = _pxi(gc.get("styles", {}).get("padding") or
                                       gc.get("styles", {}).get("padding-top")) or 0
                        if gc_pad > 0:
                            content_wrapper = gc
                            break

                if has_top_image and content_wrapper:
                    # Image-top card: card HAS padding for text, but image
                    # gets negative margin to sit flush against card edges.
                    wrapper_pad = content_wrapper.get("styles", {})
                    pad_val = _pxi(wrapper_pad.get("padding") or wrapper_pad.get("padding-top")) or 28

                    # Card: no padding on outer (image flush), overflow hidden for radius clip
                    card_settings: dict[str, Any] = {
                        "content_width": "full",
                        "flex_direction": "column",
                        "flex_gap": {"unit": "px", "size": 0, "column": "0", "row": "0"},
                    }
                    _apply_container_card_styling(card_settings, card_styles)
                    card_settings["padding"] = {
                        "unit": "px", "top": "0", "right": "0",
                        "bottom": "0", "left": "0", "isLinked": True,
                    }
                    card_settings["overflow"] = "hidden"

                    # Image flush, then text in inner container with padding
                    img_widget = card_elements[0]
                    text_widgets = card_elements[1:]

                    wrapper_styles = content_wrapper.get("styles", {})
                    text_container: dict = {
                        "__inner_container__": True,
                        "settings": {
                            "content_width": "full",
                            "flex_direction": "column",
                            "flex_align_items": "flex-start" if ta != "center" else "center",
                            "flex_gap": {"unit": "px", "size": 8, "column": "8", "row": "8"},
                            "padding": {
                                "unit": "px",
                                "top": str(pad_val),
                                "right": str(pad_val),
                                "bottom": str(pad_val),
                                "left": str(pad_val),
                                "isLinked": True,
                            },
                        },
                        "children": text_widgets,
                    }
                    card_elements = [img_widget, text_container]
                else:
                    # Regular card: single container with padding
                    merged_styles = dict(card_styles)
                    if content_wrapper:
                        ws = content_wrapper.get("styles", {})
                        for k in ("padding", "padding-top", "padding-right", "padding-bottom", "padding-left"):
                            if ws.get(k):
                                merged_styles[k] = ws[k]

                    child_gap = _pxi(card_styles.get("gap") or card_styles.get("row-gap")) or 12
                    # Respect justify-content: flex-end (content pushed to bottom
                    # for big feature cards with min-height).
                    card_jc = (card_styles.get("justify-content") or "").lower()
                    jc_map = {"flex-end": "flex-end", "end": "flex-end",
                              "center": "center", "space-between": "space-between",
                              "flex-start": "flex-start", "start": "flex-start"}
                    flex_jc = jc_map.get(card_jc, "flex-start")
                    card_settings: dict[str, Any] = {
                        "content_width": "full",
                        "flex_direction": "column",
                        "flex_align_items": "center" if ta == "center" else "flex-start",
                        "flex_justify_content": flex_jc,
                        "flex_gap": {"unit": "px", "size": child_gap, "column": str(child_gap), "row": str(child_gap)},
                    }
                    # min-height from CSS (for large hero/feature cards)
                    min_h = _pxi(card_styles.get("min-height", ""))
                    if min_h:
                        card_settings["min_height"] = {"unit": "px", "size": min_h, "sizes": []}
                    _apply_container_card_styling(card_settings, merged_styles)
                # Collapse redundant double wrapping:
                # Case A: card has no visual decoration — merge padding/border into inner.
                # Case B: card content is a single styled_wrapper that already represents
                #         the same card styling (same bg/radius) — use inner directly and
                #         transfer any extra card_settings keys (jc, min-height).
                has_visual_card = bool(
                    card_settings.get("background_background") or
                    card_settings.get("border_radius")
                )
                single_inner = (len(card_elements) == 1 and card_elements[0].get("__inner_container__"))
                if single_inner:
                    inner = card_elements[0]
                    inner_s = inner.setdefault("settings", {})
                    # Case B: inner already has the card bg/radius → don't double-wrap
                    if has_visual_card and (
                        inner_s.get("background_background") == card_settings.get("background_background")
                        or inner_s.get("background_color") == card_settings.get("background_color")
                    ):
                        # Transfer extra settings only the outer card had
                        for extra_key in ("flex_justify_content", "min_height"):
                            if extra_key in card_settings and extra_key not in inner_s:
                                inner_s[extra_key] = card_settings[extra_key]
                        cards.append(inner)
                        continue
                    # Case A: no visual card → merge outer padding/border into inner
                    if not has_visual_card:
                        if card_settings.get("padding"):
                            inner_s["padding"] = card_settings["padding"]
                        if card_settings.get("border_border"):
                            inner_s["border_border"] = card_settings["border_border"]
                            if card_settings.get("border_width"):
                                inner_s["border_width"] = card_settings["border_width"]
                            if card_settings.get("border_color"):
                                inner_s["border_color"] = card_settings["border_color"]
                        if "flex_gap" not in inner_s and card_settings.get("flex_gap"):
                            inner_s["flex_gap"] = card_settings["flex_gap"]
                        cards.append(inner)
                        continue
                cards.append({
                    "__inner_container__": True,
                    "settings": card_settings,
                    "children": card_elements,
                })
    return cards


def _apply_container_card_styling(settings: dict, styles: dict) -> None:
    """Apply card box styling to a CONTAINER (not widget).
    Containers use background_color, not _background_color."""
    from .styles import px_to_int, parse_box_shadow
    bg = to_hex(styles.get("background-color") or styles.get("background"))
    if bg:
        settings["background_background"] = "classic"
        settings["background_color"] = bg

    # Border — read per-side so patterns like `border-top: 1px solid X`
    # (divider line between list rows) don't become a full 4-side box.
    widths = {side: px_to_int(styles.get(f"border-{side}-width", "")) or 0
              for side in ("top", "right", "bottom", "left")}
    if any(widths.values()):
        settings["border_border"] = styles.get("border-style") or "solid"
        settings["border_width"] = {
            "unit": "px",
            **{s: str(w) for s, w in widths.items()},
            "isLinked": len(set(widths.values())) == 1,
        }
        border_col = (to_hex(styles.get("border-top-color"))
                      or to_hex(styles.get("border-color"))
                      or to_hex(styles.get("border-right-color")))
        if border_col:
            settings["border_color"] = border_col

    # Border radius
    br = px_to_int(styles.get("border-radius") or styles.get("border-top-left-radius")) or 0
    if br:
        settings["border_radius"] = {
            "unit": "px", "top": str(br), "right": str(br),
            "bottom": str(br), "left": str(br), "isLinked": True,
        }

    # Padding
    pt = px_to_int(styles.get("padding-top") or styles.get("padding")) or 0
    pr = px_to_int(styles.get("padding-right")) or pt
    pb = px_to_int(styles.get("padding-bottom")) or pt
    pl = px_to_int(styles.get("padding-left")) or pr
    if any((pt, pr, pb, pl)):
        settings["padding"] = {
            "unit": "px", "top": str(pt), "right": str(pr),
            "bottom": str(pb), "left": str(pl),
            "isLinked": len({pt, pr, pb, pl}) == 1,
        }

    # Box shadow
    shadow = parse_box_shadow(styles.get("box-shadow"))
    if shadow:
        settings["box_shadow_box_shadow_type"] = "yes"
        settings["box_shadow_box_shadow"] = shadow


def _leaf_text_widget(node: dict) -> dict:
    """Styled div/span with text only — taglines, prices, small labels, emojis."""
    text = (node.get("text") or "").strip()
    styles = node.get("styles", {})
    color_hex = to_hex(styles.get("color"))

    # Short text (≤50 chars) → heading with div tag (better typography control)
    if len(text) <= 50 and text:
        settings: dict[str, Any] = {
            "title": text,
            "header_size": "div",
            "align": text_align(styles),
        }
        apply_typography(settings, styles)
        _apply_margin(settings, styles)
        if color_hex:
            settings["title_color"] = color_hex
        return {"widgetType": "heading", "settings": settings}

    settings = {
        "editor": f"<p>{_escape(text)}</p>",
        "align": text_align(styles),
    }
    apply_typography(settings, styles)
    _apply_margin(settings, styles)
    if color_hex:
        settings["text_color"] = color_hex
    # max-width on the widget
    mw = px_to_int(styles.get("max-width"))
    if mw:
        settings["_element_width"] = "initial"
        settings["_element_custom_width"] = {"unit": "px", "size": mw, "sizes": []}
    return {"widgetType": "text-editor", "settings": settings}


def _badge_widget(node: dict) -> dict:
    """Small styled inline text (badge, pill, tag) — rendered as heading h6.
    Auto-width (not stretched) so the pill hugs its text content."""
    text = (node.get("text") or "").strip()
    styles = node.get("styles", {})
    # Content-width so the bg pill hugs its text. _flex_align_self overrides the
    # parent container's align-items:stretch so the badge doesn't span full width.
    settings: dict[str, Any] = {
        "title": text,
        "header_size": "h6",
        "align": "center",
        "_element_width": "initial",
        "_flex_align_self": "flex-start",
    }
    apply_typography(settings, styles)
    # Badge color
    color_hex = to_hex(styles.get("color"))
    if color_hex:
        settings["title_color"] = color_hex
    # Badge wrapper styling (bg, border, radius)
    from .styles import apply_card_styling
    apply_card_styling(settings, styles)
    _apply_margin(settings, styles)
    _apply_absolute_position(settings, styles)
    return {"widgetType": "heading", "settings": settings}


def _apply_absolute_position(settings: dict, styles: dict) -> None:
    """If the element has `position: absolute` in CSS, translate to Elementor
    advanced positioning. Common for image overlays (captions on screenshots,
    hero badges pinned to corners, etc.) where the visual layout depends on
    the element floating over a sibling image."""
    if (styles.get("position") or "").lower() != "absolute":
        return
    settings["_position"] = "absolute"
    from .styles import px_to_int as _pxi
    # Elementor uses _offset_x/_y + _offset_orientation_h/_v (start|end).
    # start = left/top, end = right/bottom.
    left = _pxi(styles.get("left", ""))
    right = _pxi(styles.get("right", ""))
    top = _pxi(styles.get("top", ""))
    bottom = _pxi(styles.get("bottom", ""))
    if left is not None:
        settings["_offset_orientation_h"] = "start"
        settings["_offset_x"] = {"unit": "px", "size": left, "sizes": []}
    elif right is not None:
        settings["_offset_orientation_h"] = "end"
        settings["_offset_x_end"] = {"unit": "px", "size": right, "sizes": []}
    if bottom is not None:
        settings["_offset_orientation_v"] = "end"
        settings["_offset_y_end"] = {"unit": "px", "size": bottom, "sizes": []}
    elif top is not None:
        settings["_offset_orientation_v"] = "start"
        settings["_offset_y"] = {"unit": "px", "size": top, "sizes": []}


def image_widget(node: dict) -> dict:
    from .styles import px_to_int
    styles = node.get("styles", {})
    w = px_to_int(styles.get("width"))
    h = px_to_int(styles.get("height"))
    br = styles.get("border-radius") or styles.get("border-top-left-radius") or ""
    is_circular = "50%" in br or "100%" in br
    obj_fit = styles.get("object-fit", "")
    is_cover = obj_fit == "cover"
    width_full = styles.get("width") in ("100%",)

    settings: dict[str, Any] = {
        "image": {"url": node.get("src", ""), "id": ""},
        "image_size": "full",
        "align": "center",
        "alt": node.get("alt", ""),
    }

    # Only use custom image size when BOTH width and height are in pixels (not %)
    w_raw = styles.get("width", "")
    h_raw = styles.get("height", "")
    has_px_dimensions = (
        w and h and
        "%" not in str(w_raw) and "%" not in str(h_raw) and
        "vh" not in str(h_raw) and "vw" not in str(w_raw)
    )

    if has_px_dimensions:
        settings["image_size"] = "custom"
        settings["image_custom_dimension"] = {"width": w, "height": h}
        settings["width"] = {"unit": "px", "size": str(w), "sizes": []}
        if is_circular:
            radius_val = str(w // 2)
            settings["image_border_radius"] = {
                "unit": "px",
                "top": radius_val, "right": radius_val,
                "bottom": radius_val, "left": radius_val,
                "isLinked": True,
            }
    elif width_full:
        # Full-width card image (width: 100%)
        settings["width"] = {"unit": "%", "size": "100", "sizes": []}
    elif is_cover and w:
        settings["width"] = {"unit": "px", "size": str(w), "sizes": []}
    elif w:
        settings["width"] = {"unit": "px", "size": str(w), "sizes": []}

    # Non-circular border-radius
    if not is_circular and br:
        br_val = px_to_int(br)
        if br_val:
            settings["_border_radius"] = {
                "unit": "px", "top": str(br_val), "right": str(br_val),
                "bottom": str(br_val), "left": str(br_val), "isLinked": True,
            }

    # Border (e.g., white border on avatars)
    border_w = px_to_int(styles.get("border-top-width") or styles.get("border-width"))
    if border_w:
        border_col = to_hex(styles.get("border-top-color") or styles.get("border-color"))
        settings["image_border_border"] = "solid"
        settings["image_border_width"] = {
            "unit": "px", "top": str(border_w), "right": str(border_w),
            "bottom": str(border_w), "left": str(border_w), "isLinked": True,
        }
        if border_col:
            settings["image_border_color"] = border_col

    # Margin (e.g., negative margin-left for overlapping avatars)
    ml = styles.get("margin-left")
    if ml and ml.startswith("-"):
        ml_val = px_to_int(ml)
        if ml_val:
            settings["_margin"] = {
                "unit": "px", "top": "0", "right": "0",
                "bottom": "0", "left": str(ml_val),
                "isLinked": False,
            }

    # CSS filter: turn dark logos white for dark footers and similar patterns.
    # Elementor's Image CSS Filters group has brightness/contrast/saturate/hue
    # sliders, but no `invert` slider. Map the common `filter: invert(1) ...`
    # recipe (used by dudaster footer to whiten a dark logo) to CSS Filters
    # group with invert switched on via `custom_css` as fallback for non-Pro.
    raw_filter = (styles.get("filter") or "").strip().lower()
    if raw_filter and raw_filter != "none":
        # Detect invert(1 or 100%): emit per-image custom CSS so the filter
        # survives without needing Pro's filter group controls.
        if "invert(1" in raw_filter or "invert(100%" in raw_filter:
            settings["_element_custom_css"] = f"selector img {{ filter: {raw_filter}; }}"
            settings["custom_css"] = f"selector img {{ filter: {raw_filter}; }}"

    return {"widgetType": "image", "settings": settings}


def icon_box_widget(node: dict) -> dict:
    from .colors import darken
    heading_text = body_text = ""
    for c in _iter(node, max_depth=4):
        if not heading_text and c.get("tag") in HEADING_TAGS:
            heading_text = (c.get("text") or _first_text(c)).strip()
        if not body_text and c.get("tag") in TEXT_TAGS:
            body_text = (c.get("text") or _first_text(c)).strip()

    ta = "left"
    for c in _iter(node, max_depth=3):
        if c.get("tag") in HEADING_TAGS | TEXT_TAGS:
            ta = text_align(c.get("styles", {}))
            break

    settings: dict[str, Any] = {
        "title_text": heading_text,
        "description_text": body_text,
        "position": "top",
        "text_align": ta,
        "selected_icon": {"value": "fas fa-star", "library": "fa-solid"},
        "title_size": "h3",
        "__globals__": {
            "title_color": "globals/colors?id=primary",
            "description_color": "globals/colors?id=text",
        },
    }

    apply_card_styling(settings, node.get("styles", {}))
    _apply_icon_styling(settings, node)
    _apply_icon_box_hover(settings)

    return {"widgetType": "icon-box", "settings": settings}


def _apply_icon_styling(settings: dict, card_node: dict) -> None:
    icon_wrapper = None
    for c in card_node.get("children", []):
        if c.get("tag") != "div":
            continue
        if any(gc.get("tag") in ("svg", "i") for gc in c.get("children", [])):
            icon_wrapper = c
            break
    if not icon_wrapper:
        return

    styles = icon_wrapper.get("styles", {})
    bg = to_hex(styles.get("background-color") or styles.get("backgroundColor"))
    icon_color = to_hex(styles.get("color"))

    if not (bg or icon_color):
        return

    settings["view"] = "stacked"
    settings["shape"] = "square"
    if bg:
        settings["primary_color"] = bg
    if icon_color:
        settings["icon_color"] = icon_color

    w = px_to_int(styles.get("width")) or px_to_int(styles.get("height"))
    if w:
        settings["icon_padding"] = {"unit": "px", "size": max(12, w // 4), "sizes": []}
        settings["icon_size"] = {"unit": "px", "size": max(20, w // 3), "sizes": []}

    br = px_to_int(styles.get("border-radius") or styles.get("border-top-left-radius")
                   or styles.get("borderTopLeftRadius")) or 12
    settings["border_radius"] = {
        "unit": "px", "top": str(br), "right": str(br),
        "bottom": str(br), "left": str(br), "isLinked": True,
    }


def _apply_icon_box_hover(settings: dict) -> None:
    from .colors import darken
    base_shadow = settings.get("_box_shadow_box_shadow")
    lifted = dict(base_shadow) if base_shadow else {
        "horizontal": 0, "vertical": 12, "blur": 32, "spread": 0, "color": "#00000020"
    }
    if base_shadow:
        lifted["blur"] = int(lifted.get("blur", 12)) * 2
        lifted["vertical"] = int(lifted.get("vertical", 4)) + 4
    settings["_box_shadow_hover_box_shadow_type"] = "yes"
    settings["_box_shadow_hover_box_shadow"] = lifted

    if settings.get("_background_color"):
        settings["_background_hover_background"] = "classic"
        settings["_background_hover_color"] = settings["_background_color"]
    if settings.get("_border_color"):
        settings["_border_hover_border"] = "solid"
        settings["_border_hover_color"] = darken(settings["_border_color"], 0.15)
    settings["_background_hover_transition"] = {"unit": "px", "size": 0.3, "sizes": []}

    primary = settings.get("primary_color")
    if primary:
        settings["hover_primary_color"] = darken(primary, 0.08)
    icon_col = settings.get("icon_color")
    if icon_col:
        settings["icon_hover_color"] = darken(icon_col, 0.1)


# --- helpers ---

def _all_text(node: dict) -> str:
    """Collect ALL text from node and its children, preserving inline HTML tags."""
    return _all_text_html(node)


def _all_text_html(node: dict, parent_color: str | None = None) -> str:
    """Recursively build text in DOM order, preserving inline HTML tags.
    Wraps <span>/<em> with color ≠ parent in <span style="color:#xxx"> so
    inline highlight colors (e.g. hero "actually ship" pink) survive."""
    from .colors import to_hex as _to_hex
    my_color = _to_hex(node.get("styles", {}).get("color") or "") if node.get("styles") else None
    effective_color = my_color or parent_color
    order = node.get("_order", [])
    children = node.get("children", [])

    def _wrap_inline(inner: str, child: dict, tag: str) -> str:
        child_color = _to_hex(child.get("styles", {}).get("color") or "") if child.get("styles") else None
        needs_span = child_color and child_color.lower() != (effective_color or "").lower()
        if tag in ("strong", "b"):
            out = f"<strong>{inner}</strong>"
        elif tag in ("em", "i"):
            out = f"<em>{inner}</em>"
        else:
            out = inner
        if needs_span:
            out = f'<span style="color:{child_color}">{out}</span>'
        return out

    if order:
        parts = []
        for kind, val in order:
            if kind == "text":
                parts.append(val)
            elif kind == "child" and val < len(children):
                child = children[val]
                tag = child.get("tag", "")
                inner = _all_text_html(child, effective_color)
                if not inner:
                    continue
                parts.append(_wrap_inline(inner, child, tag))
        return " ".join(parts)

    # Fallback: direct text + children
    parts = []
    direct = (node.get("text") or "").strip()
    if direct:
        parts.append(direct)
    for child in children:
        inner = _all_text_html(child, effective_color)
        if inner:
            tag = child.get("tag", "")
            parts.append(_wrap_inline(inner, child, tag))
    return " ".join(parts)


def _apply_max_width_and_self_align(settings: dict, styles: dict) -> None:
    """Apply CSS max-width as widget width, and compute widget self-alignment.
    `margin: 0 auto` or `margin-left/right: auto` or text-align:center with max-width
    → widget centers in parent (via _flex_align_self: center). Otherwise no self-align
    (parent flex-align-items applies)."""
    from .styles import px_to_int as _px
    mw = _px(styles.get("max-width"))
    if not mw:
        return
    settings["_element_custom_width"] = {"unit": "px", "size": mw, "sizes": []}
    settings["_element_width"] = "initial"
    # Detect centered positioning: margin-left/right auto OR text-align center
    ml = (styles.get("margin-left") or "").lower()
    mr = (styles.get("margin-right") or "").lower()
    ta = (styles.get("text-align") or "").lower()
    is_centered = (ml == "auto" and mr == "auto") or ta == "center"
    is_right = ml == "auto" and mr != "auto"
    if is_centered:
        settings["_flex_align_self"] = "center"
    elif is_right:
        settings["_flex_align_self"] = "flex-end"


def _apply_margin(settings: dict, styles: dict) -> None:
    """Read margin from CSS and apply as _margin on widget."""
    from .styles import px_to_int
    mt = px_to_int(styles.get("margin-top")) or 0
    mr = px_to_int(styles.get("margin-right")) or 0
    mb = px_to_int(styles.get("margin-bottom")) or 0
    ml = px_to_int(styles.get("margin-left")) or 0
    if any((mt, mb)):  # only set if there's meaningful vertical margin
        settings["_margin"] = {
            "unit": "px",
            "top": str(mt), "right": str(mr),
            "bottom": str(mb), "left": str(ml),
            "isLinked": False,
        }


def _first_text(node: dict) -> str:
    for n in _iter(node):
        t = (n.get("text") or "").strip()
        if t:
            return t
    return ""


def _iter(node: dict, max_depth: int = 20, _d: int = 0) -> Iterator[dict]:
    yield node
    if _d >= max_depth:
        return
    for c in node.get("children", []):
        yield from _iter(c, max_depth, _d + 1)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _avatar_widget(node: dict, size: int) -> dict:
    """Emit a circular avatar: fixed-size inner container with bg + radius 50% wrapping
    a heading widget for the initials/text inside."""
    from .colors import to_hex
    styles = node.get("styles", {})
    text = (node.get("text") or "").strip()
    # Inner heading with just the text/initials
    heading_settings: dict[str, Any] = {
        "title": _escape(text),
        "header_size": "div",
        "align": "center",
    }
    color_hex = to_hex(styles.get("color"))
    if color_hex:
        heading_settings["title_color"] = color_hex
    apply_typography(heading_settings, styles)
    inner_heading = {"widgetType": "heading", "settings": heading_settings}

    # Outer circular container
    bg_hex = to_hex(styles.get("background-color") or styles.get("background"))
    radius_val = size // 2
    container_settings: dict[str, Any] = {
        "content_width": "full",
        "flex_direction": "column",
        "flex_align_items": "center",
        "flex_justify_content": "center",
        "flex_gap": {"unit": "px", "size": 0, "column": "0", "row": "0"},
        "_element_custom_width": {"unit": "px", "size": size, "sizes": []},
        "_element_width": "initial",
        "min_height": {"unit": "px", "size": size, "sizes": []},
        "border_radius": {
            "unit": "px",
            "top": str(radius_val), "right": str(radius_val),
            "bottom": str(radius_val), "left": str(radius_val),
            "isLinked": True,
        },
    }
    if bg_hex:
        container_settings["background_background"] = "classic"
        container_settings["background_color"] = bg_hex
    # Preserve margin (e.g. avatar margin-bottom 16px)
    _apply_margin(container_settings, styles)
    return {
        "__inner_container__": True,
        "_no_group": True,
        "settings": container_settings,
        "children": [inner_heading],
    }


def _is_styled_wrapper(node: dict) -> bool:
    """Div with its own background/gradient/radius that must be preserved as a container.
    Excludes buttons, badges, cards (handled elsewhere) and leaf-text divs."""
    if node.get("tag") != "div":
        return False
    # Leaf with text handled by _leaf_text_widget / _badge_widget
    if (node.get("text") or "").strip() and not node.get("children"):
        return False
    # Don't confuse with buttons: a button would be a leaf (already excluded above) or
    # have only inline content. If this div has 2+ children OR any heading/p, it's a
    # content wrapper, not a button.
    children = node.get("children", [])
    has_block_content = any(
        c.get("tag") in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "div", "section")
        for c in children
    )
    if not has_block_content and len(children) < 2 and looks_like_button(node):
        return False
    styles = node.get("styles", {})
    bg_raw = styles.get("background") or styles.get("background-image") or ""
    bg_color = styles.get("background-color") or ""
    has_gradient = "gradient" in bg_raw
    has_bg_color = bool(bg_color and bg_color not in ("transparent", "none", "rgba(0, 0, 0, 0)", ""))
    has_radius = bool(styles.get("border-radius") or styles.get("border-top-left-radius"))
    # Only wrap when there's visible styling: gradient, OR solid bg, OR substantial radius+padding
    if has_gradient:
        return True
    if has_bg_color:
        # Ignore pure-white bg on body-level wrappers (noise)
        from .colors import to_hex
        hx = to_hex(bg_color)
        if hx and hx.lower() not in ("#ffffff", "#fff"):
            return True
        if has_radius:
            return True
    return False


def _styled_wrapper_container(node: dict, children: list[dict]) -> dict:
    """Build an inner container with this div's bg/gradient/padding/radius preserved."""
    from .colors import to_hex
    from .styles import css_padding_to_elementor, px_to_int
    styles = node.get("styles", {})
    css_jc = (styles.get("justify-content") or "").lower()
    css_ai = (styles.get("align-items") or "").lower()
    jc_map = {"flex-end": "flex-end", "end": "flex-end", "flex-start": "flex-start",
              "start": "flex-start", "center": "center", "space-between": "space-between"}
    ai_map = {"flex-end": "flex-end", "end": "flex-end", "flex-start": "flex-start",
              "start": "flex-start", "center": "center", "stretch": "stretch"}
    flex_dir = "column"
    if (styles.get("flex-direction") or "").lower().startswith("row"):
        flex_dir = "row"
    # Read CSS gap: flex/grid containers commonly use `gap:` to space children,
    # and collapsing to 0 makes stacked widgets touch (e.g. .edition card with
    # `gap: 20px` lost the spacing between h3, p, list, and CTA).
    gap_val = px_to_int(styles.get("gap") or styles.get("row-gap", "")) or 0
    gap_str = str(gap_val)
    settings: dict[str, Any] = {
        "content_width": "boxed",
        "flex_direction": flex_dir,
        "flex_align_items": ai_map.get(css_ai, "center"),
        "flex_justify_content": jc_map.get(css_jc, "center"),
        "flex_gap": {"unit": "px", "size": gap_val, "column": gap_str, "row": gap_str},
    }
    # min-height from CSS (for large feature cards)
    mh = px_to_int(styles.get("min-height", ""))
    if mh:
        settings["min_height"] = {"unit": "px", "size": mh, "sizes": []}
    # Background
    bg_raw = styles.get("background") or styles.get("background-image") or ""
    if "gradient" in bg_raw:
        import re
        settings["background_background"] = "gradient"
        angle_match = re.search(r"(\d+)deg", bg_raw)
        angle = int(angle_match.group(1)) if angle_match else 180
        colors = re.findall(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))", bg_raw)
        color1 = to_hex(colors[0]) if colors else "#ffffff"
        color2 = to_hex(colors[-1]) if len(colors) > 1 else color1
        settings["background_color"] = color1
        settings["background_color_b"] = color2
        settings["background_gradient_angle"] = {"unit": "deg", "size": angle, "sizes": []}
        settings["background_gradient_position"] = "center center"
    else:
        bg_color = styles.get("background-color") or ""
        hx = to_hex(bg_color)
        if hx:
            settings["background_background"] = "classic"
            settings["background_color"] = hx
    # Padding
    pad = css_padding_to_elementor(styles)
    if any(pad[k] != "0" for k in ("top", "right", "bottom", "left")):
        settings["padding"] = pad
    # Border-radius
    br = styles.get("border-radius") or styles.get("border-top-left-radius") or ""
    br_val = px_to_int(br) if br else None
    if br_val:
        settings["border_radius"] = {
            "unit": "px",
            "top": str(br_val), "right": str(br_val),
            "bottom": str(br_val), "left": str(br_val),
            "isLinked": True,
        }
    # Border (width + style + color). CSS shorthand `border: 1px solid X`
    # already expands to per-side width/color in the resolver; we pick per-side
    # here so uneven borders (e.g. border-bottom only) are preserved.
    border_widths = {side: px_to_int(styles.get(f"border-{side}-width", "")) or 0
                      for side in ("top", "right", "bottom", "left")}
    if any(border_widths.values()):
        settings["border_border"] = styles.get("border-style") or "solid"
        settings["border_width"] = {
            "unit": "px",
            **{s: str(w) for s, w in border_widths.items()},
            "isLinked": len(set(border_widths.values())) == 1,
        }
        bc = (to_hex(styles.get("border-top-color"))
              or to_hex(styles.get("border-color"))
              or to_hex(styles.get("border-right-color")))
        if bc:
            settings["border_color"] = bc
    # Max-width
    mw = px_to_int(styles.get("max-width") or "")
    if mw:
        settings["boxed_width"] = {"unit": "px", "size": mw, "sizes": []}
    # text-align → flex_align_items
    ta = (styles.get("text-align") or "").lower()
    if ta == "center":
        settings["flex_align_items"] = "center"
    elif ta in ("right", "end"):
        settings["flex_align_items"] = "flex-end"
    # Mark as styled so _group_into_grids doesn't try to row-wrap
    return {
        "__inner_container__": True,
        "_no_group": True,
        "settings": settings,
        "children": children,
    }
