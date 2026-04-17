"""Map HTML tree nodes to Elementor widget specs."""
from __future__ import annotations
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

    if tag == "img" and node.get("src"):
        out.append(image_widget(node))
        return


    # Leaf div/span with text but no children — emit as text-editor
    # Catches: badges/pills, taglines, prices, emoji decorations, etc.
    if tag in ("div", "span") and text and not node.get("children"):
        styles = node.get("styles", {})
        has_bg = bool(styles.get("background-color") or styles.get("background"))
        has_radius = bool(styles.get("border-radius") or styles.get("border-top-left-radius"))
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
        out.append(_inline_flex_row_widget(node, consumed))
        return

    # Card grid: a div with 2+ similar child divs (each has heading + content)
    if tag == "div" and _is_card_grid(node):
        cards = _emit_card_grid(node, consumed)
        if cards:
            grid_cols = _get_grid_columns(node)
            grid_max_width = px_to_int(node.get("styles", {}).get("max-width"))
            grid_gap = px_to_int(node.get("styles", {}).get("gap"))
            if grid_cols or grid_max_width or grid_gap:
                for card in cards:
                    if grid_cols:
                        card["_grid_cols"] = grid_cols
                    if grid_max_width:
                        card["_grid_max_width"] = grid_max_width
                    if grid_gap:
                        card["_grid_gap"] = grid_gap
            out.extend(cards)
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
    classes = " ".join(node.get("classes", [])).lower()
    # These are styled links, not visual buttons — but we STILL emit them
    # as button widgets with text-link styling (transparent bg, no border)
    if any(h in classes for h in BUTTON_HINTS):
        return True
    styles = node.get("styles", {})
    bg = styles.get("background-color") or styles.get("backgroundColor")
    has_bg = bool(bg and bg not in ("transparent", "none"))
    has_radius = bool(styles.get("border-radius") or styles.get("borderRadius"))
    has_padding_val = styles.get("padding-top") or styles.get("paddingTop") or ""
    has_padding = bool(has_padding_val and has_padding_val not in ("0px", "0"))
    has_border_val = styles.get("border-top-width") or styles.get("borderTopWidth") or ""
    has_border = bool(has_border_val and has_border_val not in ("0px", "0"))
    return sum([has_bg, has_radius, has_padding, has_border]) >= 2


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
    return {"widgetType": "heading", "settings": settings}


def text_widget(node: dict) -> dict:
    rich_text = _all_text_html(node).strip()
    styles = node.get("styles", {})
    settings: dict[str, Any] = {
        "editor": f"<p>{rich_text}</p>",
        "align": text_align(styles),
        "__globals__": {"text_color": "globals/colors?id=text"},
    }
    apply_typography(settings, styles)
    _apply_margin(settings, styles)
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
            settings["button_hover_text_color"] = darken(text_hex, 0.15)
    else:
        bg_hex = to_hex(bg)
        if bg_hex:
            settings["background_color"] = bg_hex
            settings["button_background_hover_color"] = darken(bg_hex, 0.12)
        text_hex = to_hex(styles.get("color"))
        if text_hex:
            settings["button_text_color"] = text_hex
            settings["button_hover_text_color"] = text_hex

    apply_typography(settings, styles)
    return {"widgetType": "button", "settings": settings}


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
    jc_map = {
        "space-between": "space-between",
        "space-around": "space-around",
        "center": "center",
        "flex-end": "flex-end",
    }
    child_widgets: list[dict] = []
    for child in node.get("children", []):
        _walk(child, child_widgets, consumed)
    return {
        "__inner_container__": True,
        "settings": {
            "content_width": "full",
            "flex_direction": "row",
            "flex_justify_content": jc_map.get(jc, "flex-start"),
            "flex_align_items": "center",
            "flex_gap": {"unit": "px", "size": 8, "column": "8", "row": "8"},
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
    """A div with 3+ direct child divs that each have meaningful content.
    Content = heading/p/blockquote tags OR leaf divs/spans with text."""
    children = [c for c in node.get("children", []) if c.get("tag") == "div"]
    if len(children) < 2:
        return False
    CARD_CONTENT_TAGS = HEADING_TAGS | TEXT_TAGS | {"blockquote"}
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
    """Emit child divs as individual card containers (each walks its content)."""
    children = [c for c in node.get("children", []) if c.get("tag") == "div"]
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
                    card_settings: dict[str, Any] = {
                        "content_width": "full",
                        "flex_direction": "column",
                        "flex_align_items": "center" if ta == "center" else "flex-start",
                        "flex_gap": {"unit": "px", "size": child_gap, "column": str(child_gap), "row": str(child_gap)},
                    }
                    _apply_container_card_styling(card_settings, merged_styles)
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

    # Border
    bw = px_to_int(styles.get("border-top-width") or styles.get("border-width")) or 0
    if bw:
        border_col = to_hex(styles.get("border-top-color") or styles.get("border-color"))
        settings["border_border"] = "solid"
        settings["border_width"] = {
            "unit": "px", "top": str(bw), "right": str(bw),
            "bottom": str(bw), "left": str(bw), "isLinked": True,
        }
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

    # Emoji or very short text (≤4 chars) → heading with div tag
    if len(text) <= 4 and text:
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
    return {"widgetType": "text-editor", "settings": settings}


def _badge_widget(node: dict) -> dict:
    """Small styled inline text (badge, pill, tag) — rendered as heading h6."""
    text = (node.get("text") or "").strip()
    styles = node.get("styles", {})
    settings: dict[str, Any] = {
        "title": text,
        "header_size": "h6",
        "align": "center",
    }
    apply_typography(settings, styles)
    # Badge color
    color_hex = to_hex(styles.get("color"))
    if color_hex:
        settings["title_color"] = color_hex
    # Badge wrapper styling (bg, border, radius)
    from .styles import apply_card_styling
    apply_card_styling(settings, styles)
    return {"widgetType": "heading", "settings": settings}


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


def _all_text_html(node: dict) -> str:
    """Recursively build text in DOM order, preserving inline HTML tags."""
    order = node.get("_order", [])
    children = node.get("children", [])

    if order:
        parts = []
        for kind, val in order:
            if kind == "text":
                parts.append(val)
            elif kind == "child" and val < len(children):
                child = children[val]
                tag = child.get("tag", "")
                inner = _all_text_html(child)
                if not inner:
                    continue
                if tag in ("strong", "b"):
                    parts.append(f"<strong>{inner}</strong>")
                elif tag in ("em", "i"):
                    parts.append(f"<em>{inner}</em>")
                else:
                    parts.append(inner)
        return " ".join(parts)

    # Fallback: direct text + children
    parts = []
    direct = (node.get("text") or "").strip()
    if direct:
        parts.append(direct)
    for child in children:
        inner = _all_text_html(child)
        if inner:
            parts.append(inner)
    return " ".join(parts)


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
