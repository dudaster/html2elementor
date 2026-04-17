"""Build Elementor container structures from sections."""
from __future__ import annotations
from typing import Any
from .colors import to_hex, is_dark
from .styles import css_padding_to_elementor, px_to_int
from .widgets import walk_and_emit, is_hero_bg_image, is_icon_box, _iter


def map_section(section: dict) -> tuple[dict[str, Any], list[dict]]:
    container = _section_settings(section)

    if section.get("tag") in ("header", "nav", "footer"):
        container["flex_direction"] = "row"
        container["flex_direction_tablet"] = "row"
        container["flex_direction_mobile"] = "column"
        container["flex_justify_content"] = "space-between"
        container["flex_align_items"] = "center"
        container["flex_wrap"] = "wrap"
        container["content_width"] = "full"
        # Nav padding often lives on the inner container, not the header tag.
        # Walk children to find it.
        inner = _find_content_wrapper(section)
        if inner and inner is not section:
            inner_p = css_padding_to_elementor(inner.get("styles", {}))
            for side in ("top", "bottom"):
                if inner_p[side] != "0":
                    container["padding"][side] = inner_p[side]
        # Safety: minimum 12px vertical padding for nav
        for side in ("top", "bottom"):
            if int(container["padding"][side]) < 12:
                container["padding"][side] = "16"
        return container, _build_header_elements(section)

    # Split hero: flex row with 2 children (image + content)
    split = _detect_split_layout(section)
    if split:
        first_node, second_node = split
        # Determine which is image and which is content
        first_styles = first_node.get("styles", {})
        first_has_bg = "url(" in (first_styles.get("background-image", "") or first_styles.get("background", ""))
        if first_has_bg:
            img_node, content_node = first_node, second_node
        else:
            img_node, content_node = second_node, first_node
        container["flex_direction"] = "row"
        container["flex_direction_tablet"] = "row"
        container["flex_direction_mobile"] = "column"
        container["flex_align_items"] = "stretch"
        container["content_width"] = "full"
        container["padding"] = {"unit": "px", "top": "0", "right": "0", "bottom": "0", "left": "0", "isLinked": True}

        # Image side
        img_styles = img_node.get("styles", {})
        bg_url = img_styles.get("background-image", "")
        import re as _re
        url_match = _re.search(r"url\(['\"]?([^)'\"\s]+)['\"]?\)", bg_url)

        img_container: dict[str, Any] = {
            "__inner_container__": True,
            "settings": {
                "content_width": "full",
                "flex_direction": "column",
                "_element_width": "initial",
                "_element_custom_width": {"unit": "%", "size": 50, "sizes": []},
                "_element_custom_width_mobile": {"unit": "%", "size": 100, "sizes": []},
            },
            "children": [],
        }
        if url_match:
            img_container["settings"]["background_background"] = "classic"
            img_container["settings"]["background_image"] = {"url": url_match.group(1), "id": ""}
            img_container["settings"]["background_size"] = "cover"
            img_container["settings"]["background_position"] = "center center"
            img_container["settings"]["min_height"] = {"unit": "vh", "size": 60, "sizes": []}

        # Content side
        content_elements = walk_and_emit(content_node)
        content_elements = _group_into_grids(content_elements)
        content_padding = css_padding_to_elementor(content_node.get("styles", {}))
        # Ensure minimum padding so content isn't flush
        for side in ("top", "bottom"):
            if int(content_padding.get(side, "0")) < 40:
                content_padding[side] = "60"
        for side in ("left", "right"):
            if int(content_padding.get(side, "0")) < 20:
                content_padding[side] = "40"
        content_container: dict[str, Any] = {
            "__inner_container__": True,
            "settings": {
                "content_width": "full",
                "flex_direction": "column",
                "flex_justify_content": "center",
                "flex_gap": {"unit": "px", "size": 20, "column": "20", "row": "20"},
                "padding": content_padding,
                "_element_width": "initial",
                "_element_custom_width": {"unit": "%", "size": 50, "sizes": []},
                "_element_custom_width_mobile": {"unit": "%", "size": 100, "sizes": []},
            },
            "children": content_elements,
        }

        # Return in original DOM order
        if first_has_bg:
            return container, [img_container, content_container]
        else:
            return container, [content_container, img_container]

    # Flex-row section with uniform children (stats bar, logo bar, etc.)
    # → each child becomes an inner column container
    sec_styles = section.get("styles", {})
    sec_display = sec_styles.get("display", "")
    sec_dir = sec_styles.get("flex-direction", "row")
    if sec_display == "flex" and sec_dir in ("row", ""):
        children = [c for c in section.get("children", []) if c.get("tag") == "div"]
        if len(children) >= 3:
            container["flex_direction"] = "row"
            container["flex_direction_tablet"] = "row"
            container["flex_direction_mobile"] = "column"
            container["flex_wrap"] = "nowrap"
            container["flex_wrap_tablet"] = "wrap"
            container["flex_justify_content"] = "center"
            container["flex_align_items"] = "stretch"
            container["content_width"] = "full"
            gap = sec_styles.get("gap", "24px").split()[0]
            container["flex_gap"] = {"unit": "px", "size": px_to_int(gap) or 24, "column": gap, "row": gap}

            n = len(children)
            col_pct = int((100 - (n - 1) * 2) / n)

            cols: list[dict] = []
            for child in children:
                child_widgets = walk_and_emit(child)
                child_styles = child.get("styles", {})
                col_settings: dict[str, Any] = {
                    "content_width": "full",
                    "flex_direction": "column",
                    "flex_align_items": "center",
                    "padding": css_padding_to_elementor(child_styles),
                    "_element_width": "initial",
                    "_element_width_tablet": "initial",
                    "_element_width_mobile": "initial",
                    "_element_custom_width": {"unit": "%", "size": col_pct, "sizes": []},
                    "_element_custom_width_tablet": {"unit": "%", "size": 47, "sizes": []},
                    "_element_custom_width_mobile": {"unit": "%", "size": 100, "sizes": []},
                }
                # Child border (e.g., border-right divider on features strip)
                for side in ("right", "left", "top", "bottom"):
                    bw = px_to_int(child_styles.get(f"border-{side}-width"))
                    if bw:
                        col_settings.setdefault("border_border", "solid")
                        col_settings.setdefault("border_width", {
                            "unit": "px", "top": "0", "right": "0",
                            "bottom": "0", "left": "0", "isLinked": False,
                        })
                        col_settings["border_width"][side] = str(bw)
                        bc = to_hex(child_styles.get(f"border-{side}-color"))
                        if bc:
                            col_settings["border_color"] = bc

                col: dict[str, Any] = {
                    "__inner_container__": True,
                    "settings": col_settings,
                    "children": child_widgets,
                }
                from .styles import apply_card_styling as acs
                acs(col["settings"], child.get("styles", {}))
                cols.append(col)
            return container, cols

    consumed: set[int] = set()
    bg_img = _find_hero_bg(section, consumed)
    if bg_img:
        container["background_background"] = "classic"
        container["background_image"] = {"url": bg_img["src"], "id": ""}
        container["background_size"] = "cover"
        container["background_position"] = "center center"
        container["background_overlay_background"] = "classic"
        container["background_overlay_color"] = "#000000"
        container["background_overlay_opacity"] = {"unit": "px", "size": 0.45, "sizes": []}
        container["min_height"] = {"unit": "px", "size": 600, "sizes": []}
        container["flex_direction"] = "column"
        # Preserve original alignment — don't force left
        sec_jc = sec_styles.get("justify-content") or ""
        sec_ai = sec_styles.get("align-items") or ""
        sec_ta = sec_styles.get("text-align") or ""
        if sec_jc == "center" or sec_ta == "center":
            container["flex_align_items"] = "center"
            container["flex_justify_content"] = "center"
        else:
            container["flex_align_items"] = "flex-start"
            container["flex_justify_content"] = "center"
        container["__dark_bg__"] = True

    elements = _walk_skip(section, consumed)
    elements = _group_into_grids(elements, container.get("flex_align_items", "center"))

    if container.pop("__dark_bg__", False):
        _invert_text_colors(elements)
    else:
        # Check if the section bg needs white text (dark OR saturated bg)
        sec_styles = section.get("styles", {})
        section_bg = to_hex(
            sec_styles.get("background-color") or sec_styles.get("backgroundColor") or
            sec_styles.get("background") or sec_styles.get("bg") or ""
        )
        if section_bg and len(section_bg) <= 7:
            from .colors import contrast_ratio, relative_luminance
            # White text when: bg is dark OR bg is vivid/saturated (mid-luminance)
            # Use luminance < 0.4 as threshold — covers dark + saturated colors
            lum = relative_luminance(section_bg)
            if lum < 0.4:
                _invert_text_colors(elements)

    return container, elements


def _section_settings(section: dict) -> dict[str, Any]:
    styles = section.get("styles", {})
    wrapper = _find_content_wrapper(section)
    w_styles = wrapper.get("styles", {}) if wrapper else styles

    bg = (styles.get("background-color") or styles.get("backgroundColor") or
          styles.get("background") or styles.get("bg"))

    is_flex = (w_styles.get("display") or "") in ("flex", "inline-flex", "grid")
    flex_dir = "column"
    align = "center"
    justify = "center"

    if is_flex:
        fd = w_styles.get("flex-direction") or w_styles.get("flexDirection") or "column"
        flex_dir = "row" if fd.startswith("row") else "column"
        ai = w_styles.get("align-items") or w_styles.get("alignItems")
        if ai and ai not in ("normal", "stretch", "center"):
            mapping = {"flex-start": "flex-start", "start": "flex-start",
                       "flex-end": "flex-end", "end": "flex-end", "center": "center"}
            align = mapping.get(ai, "center")
        jc = w_styles.get("justify-content") or w_styles.get("justifyContent")
        if jc and jc not in ("normal", "center"):
            mapping = {"flex-start": "flex-start", "start": "flex-start",
                       "flex-end": "flex-end", "end": "flex-end",
                       "space-between": "space-between", "space-around": "space-around"}
            justify = mapping.get(jc, "center")

    padding = css_padding_to_elementor(styles)
    if wrapper and wrapper is not section:
        wp = css_padding_to_elementor(wrapper.get("styles", {}))
        for side in ("left", "right"):
            if padding[side] == "0" and wp[side] != "0":
                padding[side] = wp[side]
    for side in ("left", "right"):
        if int(padding[side]) < 20:
            padding[side] = "40"

    # Read gap from CSS (row-gap / column-gap / gap shorthand)
    raw_gap = (w_styles.get("gap") or w_styles.get("row-gap") or
               styles.get("gap") or styles.get("row-gap") or "")
    gap_val = px_to_int(raw_gap) if raw_gap else None
    gap_px = gap_val or 20
    gap_str = str(gap_px)

    settings: dict[str, Any] = {
        "content_width": "boxed",
        "flex_direction": flex_dir,
        "flex_justify_content": justify,
        "flex_align_items": align,
        "flex_gap": {"unit": "px", "size": gap_px, "column": gap_str, "row": gap_str},
        "padding": padding,
    }

    # Check for gradient background first
    bg_raw = styles.get("background") or styles.get("background-image") or ""
    if "linear-gradient" in bg_raw or "radial-gradient" in bg_raw:
        _apply_gradient(settings, bg_raw)
    else:
        bg_hex = to_hex(bg)
        if bg_hex:
            settings["background_background"] = "classic"
            settings["background_color"] = bg_hex

    # Section borders (top/bottom lines on features strips, dividers, etc.)
    for side in ("top", "bottom"):
        bw_key = f"border-{side}-width"
        bw = px_to_int(styles.get(bw_key))
        if bw:
            settings.setdefault("border_border", "solid")
            settings.setdefault("border_width", {
                "unit": "px", "top": "0", "right": "0",
                "bottom": "0", "left": "0", "isLinked": False,
            })
            settings["border_width"][side] = str(bw)
            bc_key = f"border-{side}-color"
            bc = to_hex(styles.get(bc_key) or styles.get("border-color"))
            if bc:
                settings["border_color"] = bc

    # Section border-radius
    br = styles.get("border-radius") or styles.get("border-top-left-radius") or ""
    br_val = px_to_int(br) if br else None
    if br_val:
        settings["border_radius"] = {
            "unit": "px",
            "top": str(br_val), "right": str(br_val),
            "bottom": str(br_val), "left": str(br_val),
            "isLinked": True,
        }

    # Section margin (e.g., CTA with margin: 0 48px 48px)
    mt = px_to_int(styles.get("margin-top", "0"))
    mr = px_to_int(styles.get("margin-right", "0"))
    mb = px_to_int(styles.get("margin-bottom", "0"))
    ml = px_to_int(styles.get("margin-left", "0"))
    if mt or mr or mb or ml:
        settings["margin"] = {
            "unit": "px",
            "top": str(mt or 0), "right": str(mr or 0),
            "bottom": str(mb or 0), "left": str(ml or 0),
            "isLinked": False,
        }

    return settings


def _apply_gradient(settings: dict, css: str) -> None:
    """Parse CSS linear-gradient and apply as Elementor gradient background."""
    import re
    settings["background_background"] = "gradient"

    # Extract angle
    angle_match = re.search(r"(\d+)deg", css)
    angle = int(angle_match.group(1)) if angle_match else 180

    # Extract color stops
    colors = re.findall(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))", css)
    color1 = to_hex(colors[0]) if colors else "#ffffff"
    color2 = to_hex(colors[-1]) if len(colors) > 1 else color1

    settings["background_color"] = color1
    settings["background_color_b"] = color2
    settings["background_gradient_angle"] = {"unit": "deg", "size": angle, "sizes": []}
    settings["background_gradient_position"] = "center center"


def _detect_split_layout(section: dict) -> tuple[dict, dict] | None:
    """Detect a flex-row section with exactly 2 children: one image, one content.
    Common pattern: hero with image left + text right (or vice versa)."""
    styles = section.get("styles", {})
    display = styles.get("display", "")
    direction = styles.get("flex-direction", "")
    if display != "flex" or direction not in ("row", "row-reverse", ""):
        return None
    children = [c for c in section.get("children", []) if c.get("tag") in ("div", "section", "article")]
    if len(children) != 2:
        return None

    # Identify which child is image and which is content
    for i, child in enumerate(children):
        child_styles = child.get("styles", {})
        bg_img_val = child_styles.get("background-image", "") or child_styles.get("background", "")
        has_bg_img = "url(" in bg_img_val

        # Skip overlays — divs with semi-transparent bg but no image and no text
        is_overlay = (
            not has_bg_img and
            not child.get("text") and
            not child.get("children") and
            ("rgba" in (child_styles.get("background", "") or child_styles.get("background-color", "")))
        )
        if is_overlay:
            continue

        has_no_text = not child.get("text") and not any(
            gc.get("tag") in ("h1", "h2", "h3", "p") for gc in child.get("children", [])
        )
        if has_bg_img or (has_no_text and not is_overlay):
            other = children[1 - i]
            # Return in ORIGINAL DOM order (preserve left/right)
            if i == 0:
                return (child, other)   # image first (left), content second (right)
            else:
                return (other, child)   # content first (left), image second (right)
    return None


def _find_content_wrapper(section: dict) -> dict | None:
    node = section
    for _ in range(4):
        children = [c for c in node.get("children", []) if c.get("tag") not in ("script", "style", None)]
        if len(children) != 1:
            return node
        ch = children[0]
        if ch.get("tag") in ("div", "section", "article"):
            node = ch
        else:
            return node
    return node


def _find_hero_bg(section: dict, consumed: set[int]) -> dict | None:
    """Find hero bg image — only check first 2 levels (not deep inside cards)."""
    for node in _iter(section, max_depth=2):
        if is_hero_bg_image(node, section):
            consumed.add(id(node))
            return node
    return None


def _walk_skip(node: dict, consumed: set[int]) -> list[dict]:
    return walk_and_emit(node, consumed)


def _group_into_grids(elements: list[dict], parent_align: str = "center") -> list[dict]:
    out: list[dict] = []
    i = 0
    while i < len(elements):
        el = elements[i]
        wt = el.get("widgetType")
        # Group 3+ consecutive cards (icon-box, image-box, or inner containers) into a grid
        is_card = wt in ("icon-box", "image-box") or el.get("__inner_container__")
        if is_card:
            group = [el]
            j = i + 1
            while j < len(elements):
                nxt = elements[j]
                if nxt.get("widgetType") in ("icon-box", "image-box") or nxt.get("__inner_container__"):
                    group.append(nxt)
                    j += 1
                else:
                    break
            if len(group) >= 2:
                grid_cols = group[0].get("_grid_cols") if group else None
                grid_max_width = group[0].get("_grid_max_width") if group else None
                grid_gap = group[0].get("_grid_gap") if group else None
                if grid_cols and grid_cols < len(group):
                    for chunk_start in range(0, len(group), grid_cols):
                        chunk = group[chunk_start:chunk_start + grid_cols]
                        out.append(_wrap_row(chunk, grid_max_width, grid_gap))
                else:
                    out.append(_wrap_row(group, grid_max_width, grid_gap))
                i = j
                continue
        # Group 2+ consecutive buttons into an inline row
        if wt == "button":
            group = [el]
            j = i + 1
            while j < len(elements) and elements[j].get("widgetType") == "button":
                group.append(elements[j])
                j += 1
            if len(group) >= 2:
                out.append(_wrap_buttons(group, parent_align))
                i = j
                continue
        out.append(el)
        i += 1
    return out


def _wrap_buttons(buttons: list[dict], parent_align: str = "flex-start") -> dict:
    """Wrap 2+ buttons in a horizontal flex row, inheriting parent alignment."""
    return {
        "__inner_container__": True,
        "settings": {
            "content_width": "full",
            "flex_direction": "row",
            "flex_direction_tablet": "row",
            "flex_direction_mobile": "column",
            "flex_wrap": "wrap",
            "flex_justify_content": parent_align,
            "flex_align_items": "center",
            "flex_gap": {"unit": "px", "size": 16, "column": "16", "row": "16"},
        },
        "children": buttons,
    }


def _wrap_row(widgets: list[dict], max_width: int | None = None, gap: int | None = None) -> dict:
    n = max(len(widgets), 1)
    desktop_pct = int((100 - (n - 1) * 2) / n)

    widgets_with_widths = []
    for w in widgets:
        w_copy = dict(w)
        s = dict(w_copy.get("settings", {}))
        # For inner containers: use 'width' property
        # For widgets: use '_element_width' + '_element_custom_width'
        if not w_copy.get("__inner_container__"):
            # Widgets: use _element_custom_width
            s["_element_width"] = "initial"
            s["_element_width_tablet"] = "initial"
            s["_element_width_mobile"] = "initial"
            s["_element_custom_width"] = {"unit": "%", "size": desktop_pct, "sizes": []}
            s["_element_custom_width_tablet"] = {"unit": "%", "size": 47, "sizes": []}
            s["_element_custom_width_mobile"] = {"unit": "%", "size": 100, "sizes": []}
        w_copy["settings"] = s
        widgets_with_widths.append(w_copy)

    gap_px = gap or 16
    gap_str = str(gap_px)
    row_settings: dict = {
        "content_width": "boxed" if max_width else "full",
        "flex_direction": "row",
        "flex_direction_tablet": "row",
        "flex_direction_mobile": "column",
        "flex_justify_content": "center",
        "flex_align_items": "stretch",
        "flex_gap": {"unit": "px", "size": gap_px, "column": gap_str, "row": gap_str},
        "flex_gap_tablet": {"unit": "px", "size": gap_px, "column": gap_str, "row": gap_str},
    }
    if max_width:
        row_settings["boxed_width"] = {"unit": "px", "size": max_width, "sizes": []}
    else:
        row_settings["width"] = {"unit": "%", "size": 100, "sizes": []}

    return {
        "__inner_container__": True,
        "settings": row_settings,
        "children": widgets_with_widths,
    }


def _build_header_elements(section: dict) -> list[dict]:
    from .widgets import image_widget, looks_like_button, _first_text
    logo_src = None
    nav_items: list[tuple[str, str]] = []
    for n in _iter(section):
        if n.get("tag") == "img" and n.get("src") and not logo_src:
            logo_src = n["src"]
        if n.get("tag") == "a" and n.get("href"):
            txt = (n.get("text") or _first_text(n)).strip()
            if txt and 2 <= len(txt) <= 30 and not looks_like_button(n):
                nav_items.append((txt, n["href"]))

    # Find text logo (div/span with short text, large font, or "logo" class)
    logo_text = None
    for n in _iter(section):
        if n.get("tag") in ("div", "span", "a") and not logo_src:
            cls = " ".join(n.get("classes", [])).lower()
            txt = (n.get("text") or "").strip()
            if txt and len(txt) <= 20 and ("logo" in cls or "brand" in cls):
                logo_text = n
                break

    elements: list[dict] = []
    if logo_src:
        elements.append({
            "widgetType": "image",
            "settings": {
                "image": {"url": logo_src, "id": ""},
                "image_size": "full", "align": "left",
                "width": {"unit": "px", "size": 80, "sizes": []},
            },
        })
    elif logo_text:
        from .styles import apply_typography
        logo_settings: dict = {
            "title": logo_text["text"].strip(),
            "header_size": "h4",
            "align": "left",
        }
        apply_typography(logo_settings, logo_text.get("styles", {}))
        color = to_hex(logo_text.get("styles", {}).get("color"))
        if color:
            logo_settings["title_color"] = color
        elements.append({"widgetType": "heading", "settings": logo_settings})
    if nav_items:
        elements.append({
            "widgetType": "icon-list",
            "settings": {
                "view": "inline",
                "space_between": {"unit": "px", "size": 20, "sizes": []},
                "icon_list": [
                    {"text": txt, "link": {"url": href, "is_external": False},
                     "selected_icon": {"value": "", "library": ""}}
                    for txt, href in nav_items[:8]
                ],
                "__globals__": {"text_color": "globals/colors?id=primary"},
            },
        })
    # Emit button-like links in nav as actual button widgets
    for n in _iter(section):
        if n.get("tag") == "a" and looks_like_button(n):
            from .widgets import button_widget
            txt = (n.get("text") or _first_text(n)).strip()
            if txt:
                elements.append(button_widget(n, txt))
                break  # usually just one CTA in nav
    return elements


def _invert_text_colors(elements: list[dict]) -> None:
    """On dark sections: only override widget colors if they don't already have
    an explicit light color. If the widget already extracted a light color from
    CSS (e.g., gold #d4c5a9), keep it. Only default dark text gets inverted."""
    from .globals import short_id
    from .colors import relative_luminance, to_hex as _to_hex
    white_id = short_id("White")
    white80_id = short_id("White 80")
    for el in elements:
        if el.get("__inner_container__"):
            _invert_text_colors(el["children"])
            continue
        s = el.get("settings", {})
        g = s.setdefault("__globals__", {})
        wt = el.get("widgetType")

        if wt == "heading":
            # Check if heading already has an explicit light color
            existing = s.get("title_color")
            if existing and _to_hex(existing):
                lum = relative_luminance(_to_hex(existing))
                if lum > 0.3:
                    continue  # already light, keep it
            g["title_color"] = f"globals/colors?id={white_id}"
            s.pop("title_color", None)
        elif wt == "text-editor":
            existing = s.get("text_color")
            if existing and _to_hex(existing):
                lum = relative_luminance(_to_hex(existing))
                if lum > 0.3:
                    continue
            g["text_color"] = f"globals/colors?id={white_id}"
            s.pop("text_color", None)
        elif wt == "icon-box":
            g["title_color"] = f"globals/colors?id={white_id}"
            g["description_color"] = f"globals/colors?id={white_id}"
            s.pop("title_color", None)
            s.pop("description_color", None)
