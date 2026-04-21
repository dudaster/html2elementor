"""Build Elementor container structures from sections."""
from __future__ import annotations
import re as _re
from typing import Any
from .colors import to_hex, is_dark
from .styles import css_padding_to_elementor, px_to_int
from .widgets import walk_and_emit, is_hero_bg_image, is_icon_box, _iter


def _parse_grid_columns(grid_template_columns: str) -> int:
    """Parse grid-template-columns and return the number of explicit columns."""
    if not grid_template_columns:
        return 1
    val = grid_template_columns.strip()
    # repeat(N, ...) → N columns
    m = _re.match(r"repeat\(\s*(\d+)\s*,", val)
    if m:
        return int(m.group(1))
    # repeat(auto-fill/auto-fit, ...) → can't determine statically, return 0
    if "auto-fill" in val or "auto-fit" in val:
        return 0
    # Space-separated list of track sizes: "1fr 2fr 1fr" → 3
    return len(val.split())


def map_section(section: dict) -> tuple[dict[str, Any], list[dict]]:
    container = _section_settings(section)

    sec_tag = section.get("tag", "")
    sec_display = section.get("styles", {}).get("display", "")
    if sec_tag in ("header", "nav", "footer"):
        # Check for a grid layout inside footer — if found, fall through to
        # normal section handling so the grid columns are preserved.
        has_grid_child = any(
            (c.get("styles", {}).get("display") or "") == "grid"
            for c in _iter(section)
            if c is not section
        )
        use_header_builder = (sec_tag in ("header", "nav")) or (sec_tag == "footer" and not has_grid_child)
        if use_header_builder:
            is_flex_row = sec_display == "flex" or sec_tag in ("header", "nav")
            if is_flex_row:
                container["flex_direction"] = "row"
                container["flex_direction_tablet"] = "row"
                container["flex_direction_mobile"] = "column"
                container["flex_justify_content"] = "space-between"
                container["flex_align_items"] = "center"
                container["flex_wrap"] = "nowrap"
                container["flex_wrap_tablet"] = "wrap"
                container["content_width"] = "full"
            inner = _find_content_wrapper(section)
            if inner and inner is not section:
                inner_p = css_padding_to_elementor(inner.get("styles", {}))
                for side in ("top", "bottom"):
                    if inner_p[side] != "0":
                        container["padding"][side] = inner_p[side]
            for side in ("top", "bottom"):
                if int(container["padding"][side]) < 12:
                    container["padding"][side] = "16"
            return container, _build_header_elements(section)
        # Footer with grid inside: fall through to generic section handling

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

    # If section has horizontal margin, wrap in a transparent outer section
    # with padding, and move bg/radius to inner container (prevents overflow)
    sec_styles = section.get("styles", {})
    ml = px_to_int(sec_styles.get("margin-left", "0"))
    mr = px_to_int(sec_styles.get("margin-right", "0"))
    if ml or mr:
        # Move bg, gradient, radius, padding from section to inner container
        inner_settings: dict[str, Any] = {
            "content_width": "full",
            "flex_direction": container.get("flex_direction", "column"),
            "flex_justify_content": container.get("flex_justify_content", "center"),
            "flex_align_items": container.get("flex_align_items", "center"),
            "flex_gap": container.get("flex_gap", {"unit": "px", "size": 20, "column": "20", "row": "20"}),
        }
        # Move styling keys to inner
        for key in list(container.keys()):
            if key.startswith("background") or key.startswith("border"):
                inner_settings[key] = container.pop(key)
        # Move padding to inner
        if "padding" in container:
            inner_settings["padding"] = container.pop("padding")
        # Outer becomes transparent wrapper with margin as padding
        mt = px_to_int(sec_styles.get("margin-top", "0"))
        mb = px_to_int(sec_styles.get("margin-bottom", "0"))
        container["content_width"] = "full"
        container["flex_direction"] = "column"
        container["padding"] = {
            "unit": "px",
            "top": str(mt or 0), "right": str(mr or 0),
            "bottom": str(mb or 0), "left": str(ml or 0),
            "isLinked": False,
        }
        container.pop("margin", None)
        # Wrap elements in inner container
        inner = {
            "__inner_container__": True,
            "settings": inner_settings,
            "children": elements,
        }
        return container, [inner]

    return container, elements


def _section_settings(section: dict) -> dict[str, Any]:
    styles = section.get("styles", {})
    wrapper = _find_content_wrapper(section)
    w_styles = wrapper.get("styles", {}) if wrapper else styles

    bg = (styles.get("background-color") or styles.get("backgroundColor") or
          styles.get("background") or styles.get("bg"))

    display = (w_styles.get("display") or "")
    is_flex = display in ("flex", "inline-flex", "grid")
    flex_dir = "column"
    # For column (vertical) sections, use stretch so child widgets take full
    # width — then each widget's own align setting (from text-align) controls
    # horizontal positioning of its content. This handles both "centered
    # hero" (widgets stretched, text centered) and "left-aligned hero"
    # (widgets stretched, text left-aligned) uniformly.
    align = "stretch"
    justify = "flex-start"

    if display == "grid":
        # CSS grid → Elementor row container. Determine column count from
        # grid-template-columns so _group_into_grids can chunk correctly.
        gtc = w_styles.get("grid-template-columns", "")
        ncols = _parse_grid_columns(gtc)
        if ncols >= 2:
            flex_dir = "row"

    elif is_flex:
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
    # Only use default gap if section is flex/grid; otherwise margins handle spacing
    gap_px = gap_val if gap_val is not None else (20 if is_flex else 0)
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

    # Section margin — only top/bottom applied directly.
    # Left/right margin handled in map_section via wrapper approach.
    mt = px_to_int(styles.get("margin-top", "0"))
    mb = px_to_int(styles.get("margin-bottom", "0"))
    if mt or mb:
        settings["margin"] = {
            "unit": "px",
            "top": str(mt or 0), "right": "0",
            "bottom": str(mb or 0), "left": "0",
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
            # Stop before descending into a multi-column grid/flex container.
            # Those are content grids that walk_and_emit() should handle via
            # _is_card_grid() — promoting their direction to the section level
            # collapses the grid into a flat row of mixed widgets.
            ch_styles = ch.get("styles", {})
            ch_display = ch_styles.get("display", "")
            if ch_display == "grid":
                ncols = _parse_grid_columns(ch_styles.get("grid-template-columns", ""))
                if ncols >= 2:
                    return node
            elif ch_display in ("flex", "inline-flex"):
                fd = ch_styles.get("flex-direction", "row")
                if not fd.startswith("column") and len(ch.get("children", [])) >= 2:
                    # Flex-row with 2+ children — this is a content row, stop here.
                    # Exception: if child has a .container-style class (max-width wrapper)
                    # it's just a centering shell, keep descending.
                    cls = " ".join(ch.get("classes", [])).lower()
                    if not any(k in cls for k in ("container", "wrapper", "inner", "content")):
                        return node
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
        if is_card and el.get("_no_group"):
            # Card explicitly opted out of row grouping (block/flex-column parent)
            el.pop("_no_group", None)
            out.append(el)
            i += 1
            continue
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
        if w_copy.get("__inner_container__"):
            # Inner containers inside a row: force content_width=full so Elementor
            # doesn't insert .e-con-inner wrapper, which breaks flex-grow width calc.
            s["content_width"] = "full"
            # Elementor 4.x containers use `width` (not _element_custom_width) for sizing.
            s["width"] = {"unit": "%", "size": desktop_pct, "sizes": []}
            s["width_tablet"] = {"unit": "%", "size": 47, "sizes": []}
            s["width_mobile"] = {"unit": "%", "size": 100, "sizes": []}
        else:
            # Widgets: explicit percentage widths
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
        from .styles import apply_typography, px_to_int as _px
        from .widgets import _all_text_html, _apply_margin
        # Preserve ALL text including child spans (e.g., "Code<span>Academy</span>")
        full_text = _all_text_html(logo_text).strip()
        if not full_text:
            full_text = logo_text.get("text", "").strip()
        logo_settings: dict = {
            "title": full_text,
            "header_size": "h4",
            "align": "left",
        }
        apply_typography(logo_settings, logo_text.get("styles", {}))
        color = to_hex(logo_text.get("styles", {}).get("color"))
        if color:
            logo_settings["title_color"] = color
        _apply_margin(logo_settings, logo_text.get("styles", {}))
        elements.append({"widgetType": "heading", "settings": logo_settings})
    if nav_items:
        # Find the parent div of nav links (for margin-bottom)
        links_parent = None
        first_link_node = None
        for n in _iter(section):
            if n.get("tag") == "div" and any(
                c.get("tag") == "a" for c in n.get("children", [])
            ):
                links_parent = n
                break
        # Read link color from the first nav <a> (non-button) in CSS
        for n in _iter(section):
            if n.get("tag") == "a" and n.get("href") and not looks_like_button(n):
                first_link_node = n
                break
        # Read spacing between links from CSS (margin-left or margin-right)
        spacing = 20
        if first_link_node:
            ls = first_link_node.get("styles", {})
            ml = px_to_int(ls.get("margin-left"))
            mr = px_to_int(ls.get("margin-right"))
            spacing = ml or mr or 20
        icon_list_settings: dict = {
            "view": "inline",
            "space_between": {"unit": "px", "size": spacing, "sizes": []},
            "icon_list": [
                {"text": txt, "link": {"url": href, "is_external": False},
                 "selected_icon": {"value": "", "library": ""}}
                for txt, href in nav_items[:8]
            ],
        }
        if first_link_node:
            from .styles import apply_typography as _at
            link_styles = first_link_node.get("styles", {})
            link_color = to_hex(link_styles.get("color"))
            if link_color:
                icon_list_settings["text_color"] = link_color
            # Apply typography (font-size, font-weight, etc.) with icon_list prefix
            tmp: dict = {}
            _at(tmp, link_styles)
            for k, v in tmp.items():
                if k == "typography_typography":
                    icon_list_settings["icon_typography_typography"] = v
                elif k.startswith("typography_"):
                    icon_list_settings["icon_" + k] = v
        if links_parent:
            from .widgets import _apply_margin as _am
            _am(icon_list_settings, links_parent.get("styles", {}))
        nav_icon_list = {"widgetType": "icon-list", "settings": icon_list_settings}
    else:
        nav_icon_list = None

    nav_cta = None
    for n in _iter(section):
        if n.get("tag") == "a" and looks_like_button(n):
            from .widgets import button_widget
            txt = (n.get("text") or _first_text(n)).strip()
            if txt:
                nav_cta = button_widget(n, txt)
                break

    # For flex-row headers with BOTH nav + CTA: group them in a nested row
    # so they stay together on the right (HTML <nav> semantics).
    # Use _element_custom_width: auto + content_width not set so container shrinks.
    sec_tag_local = section.get("tag", "")
    is_flex_header = (
        sec_tag_local in ("header", "nav")
        or section.get("styles", {}).get("display") == "flex"
    )
    if is_flex_header and nav_icon_list and nav_cta:
        # Wrap logo in its own container too for symmetry
        if elements and elements[0].get("widgetType") in ("heading", "image"):
            logo_widget = elements.pop(0)
            elements.insert(0, {
                "__inner_container__": True,
                "settings": {
                    "flex_direction": "row",
                    "flex_align_items": "center",
                    "_flex_size": "shrink",
                },
                "children": [logo_widget],
            })
        elements.append({
            "__inner_container__": True,
            "settings": {
                "flex_direction": "row",
                "flex_align_items": "center",
                "flex_justify_content": "flex-end",
                "flex_gap": {"unit": "px", "size": 20, "column": "20", "row": "20"},
                "_flex_size": "shrink",
            },
            "children": [nav_icon_list, nav_cta],
        })
    else:
        if nav_icon_list:
            elements.append(nav_icon_list)
        if nav_cta:
            elements.append(nav_cta)

    # Emit remaining text divs (copyright, taglines) not captured above
    collected_texts = set()
    if logo_text:
        collected_texts.add(logo_text.get("text", "").strip())
    for txt, _ in nav_items:
        collected_texts.add(txt)
    for child in section.get("children", []):
        tag = child.get("tag", "")
        txt = (child.get("text") or "").strip()
        if tag == "div" and txt and txt not in collected_texts:
            from .styles import apply_typography
            settings: dict = {"editor": txt}
            apply_typography(settings, child.get("styles", {}))
            color = to_hex(child.get("styles", {}).get("color"))
            if color:
                settings["text_color"] = color
            elements.append({"widgetType": "text-editor", "settings": settings})

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
