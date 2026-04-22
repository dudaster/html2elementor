"""Verify Elementor output matches HTML/CSS source.

Compares each emitted widget/container against the original element in HTML
and reports differences in color, typography, spacing, and alignment.
Tolerances: font-size ±2px, padding/margin ±4px, other values exact.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .parser import parse_html
from .colors import to_hex
from .styles import px_to_int


FONT_TOLERANCE = 2   # px
SPACING_TOLERANCE = 4  # px


def _all_text(node: dict) -> str:
    """Recursively collect text (used to match Elementor widgets to HTML nodes)."""
    direct = (node.get("text") or "").strip()
    parts = [direct] if direct else []
    for c in node.get("children", []):
        t = _all_text(c)
        if t:
            parts.append(t)
    return " ".join(parts).strip()


def _iter_html(tree: dict):
    """Yield every node in the HTML tree."""
    yield tree
    for child in tree.get("children", []):
        yield from _iter_html(child)


def _find_html_nodes(tree: dict, target_text: str, target_tags: set[str]) -> list[dict]:
    """Find ALL HTML nodes whose text matches target_text and tag in target_tags.
    Priority: exact direct match > target⊂direct > direct⊂target > target⊂full_text."""
    target_text = re.sub(r"\s+", " ", target_text.strip().lower())[:60]
    if not target_text:
        return []
    exact: list[dict] = []
    target_in_direct: list[dict] = []
    direct_in_target: list[dict] = []
    in_fulltext: list[dict] = []
    # For very short targets (≤4 chars like "AL", "42", "Linear"), prefer exact only
    short_target = len(target_text) <= 5
    for node in _iter_html(tree):
        if target_tags and node.get("tag") not in target_tags:
            continue
        direct = re.sub(r"\s+", " ", (node.get("text") or "").strip().lower())[:60]
        if direct:
            if target_text == direct:
                exact.append(node)
                continue
            if short_target:
                # Don't allow fuzzy matches for short targets — avoids "AL" matching
                # "alphabet" or "Linear" matching "VP Eng, Linear".
                continue
            if target_text in direct:
                target_in_direct.append(node)
                continue
            if direct in target_text and len(direct) >= max(8, int(len(target_text) * 0.6)):
                direct_in_target.append(node)
                continue
        # Full (recursive) text — require target IS substring of full text (one direction only)
        txt = re.sub(r"\s+", " ", _all_text(node).lower())[:200]
        if txt and target_text in txt:
            in_fulltext.append(node)
    return exact + target_in_direct + direct_in_target + in_fulltext


def _find_html_node(tree: dict, target_text: str, target_tags: set[str]) -> dict | None:
    """Find the HTML node whose text matches target_text and tag in target_tags.
    Prefers leaf nodes (direct text match) over ancestors."""
    matches = _find_html_nodes(tree, target_text, target_tags)
    return matches[0] if matches else None


def _close(a: int | None, b: int | None, tol: int) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= tol


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _cmp_color(el_val: Any, css_val: str, label: str, issues: list, ignore_defaults: tuple = ()):
    """Compare a color value from Elementor settings vs CSS.
    Flags both mismatches AND missing elementor values when CSS has a color."""
    css_hex = to_hex(css_val) if css_val else None
    if not css_hex:
        return
    # Skip CSS defaults that aren't worth checking (e.g. inherit from body)
    if css_hex.lower() in ignore_defaults:
        return
    el_hex = None
    if isinstance(el_val, str):
        el_hex = to_hex(el_val)
    if not el_hex:
        issues.append(f"{label}: css={css_hex} but elementor has no color set")
        return
    if el_hex.lower() != css_hex.lower():
        issues.append(f"{label}: elementor={el_hex} vs css={css_hex}")


def _cmp_size(el_val: Any, css_val: str, label: str, issues: list, tol: int = FONT_TOLERANCE):
    css_px = px_to_int(css_val) if css_val else None
    if not css_px:
        return
    el_px = None
    if isinstance(el_val, dict):
        sz = el_val.get("size")
        if sz not in (None, ""):
            try:
                el_px = int(float(sz))
            except (ValueError, TypeError):
                pass
    elif isinstance(el_val, (int, float, str)):
        try:
            el_px = int(float(el_val))
        except (ValueError, TypeError):
            pass
    if el_px is not None and not _close(el_px, css_px, tol):
        issues.append(f"{label}: elementor={el_px}px vs css={css_px}px (tol {tol}px)")


def _resolved_color(s: dict, direct_key: str, kit_maps: dict) -> str | None:
    """Get color either from direct key or resolved global."""
    direct = s.get(direct_key)
    if direct:
        return direct
    return _resolve_global(s.get("__globals__"), kit_maps, direct_key, "color")


def _resolved_typo_size(s: dict, direct_key: str, kit_maps: dict) -> int | None:
    """Get font-size from direct typography_font_size or resolved global."""
    direct = s.get(direct_key)
    if isinstance(direct, dict):
        sz = direct.get("size")
        if sz:
            try:
                return int(float(sz))
            except (ValueError, TypeError):
                pass
    typo = _resolve_global(s.get("__globals__"), kit_maps, "typography_typography", "typo")
    if typo and typo.get("size"):
        try:
            return int(float(typo["size"]))
        except (ValueError, TypeError):
            pass
    return None


def _ancestor_bg_is_dark(node: dict, tree: dict) -> bool:
    """Walk up the HTML tree to see if any ancestor has a dark background."""
    from .colors import relative_luminance
    # Build parent map
    parents: dict[int, dict] = {}
    def map_parents(n):
        for c in n.get("children", []):
            parents[id(c)] = n
            map_parents(c)
    map_parents(tree)
    cur = node
    while cur is not None:
        bg = to_hex(
            cur.get("styles", {}).get("background-color")
            or cur.get("styles", {}).get("background")
            or ""
        )
        if bg and len(bg) <= 7:
            try:
                if relative_luminance(bg) < 0.4:
                    return True
            except (ValueError, ZeroDivisionError):
                pass
        cur = parents.get(id(cur))
    return False


def _check_margin(widget: dict, node: dict, label: str, issues: list, parent_absorbed: bool = False):
    """Check if widget's _margin matches CSS margin properties.
    If parent_absorbed is True, the parent container already applied the margin
    (e.g., avatar pattern: circular container holds the margin, heading inside doesn't)."""
    if parent_absorbed:
        return
    css = node.get("styles", {})
    css_mb = px_to_int(css.get("margin-bottom", ""))
    css_mt = px_to_int(css.get("margin-top", ""))
    s = widget.get("settings", {})
    m = s.get("_margin") or {}
    def parse_side(v):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0
    el_mb = parse_side(m.get("bottom", "0")) if m else 0
    el_mt = parse_side(m.get("top", "0")) if m else 0
    if css_mb and not _close(el_mb, css_mb, SPACING_TOLERANCE):
        issues.append(f"{label}.margin-bottom: elementor={el_mb}px vs css={css_mb}px")
    if css_mt and not _close(el_mt, css_mt, SPACING_TOLERANCE):
        issues.append(f"{label}.margin-top: elementor={el_mt}px vs css={css_mt}px")


def _check_max_width(widget: dict, node: dict, label: str, issues: list):
    """Check if widget's _element_custom_width matches CSS max-width."""
    s = widget.get("settings", {})
    css_mw = px_to_int(node.get("styles", {}).get("max-width", ""))
    if not css_mw:
        return
    ecw = s.get("_element_custom_width")
    el_mw = None
    if isinstance(ecw, dict) and ecw.get("unit") == "px":
        try:
            el_mw = int(float(ecw.get("size")))
        except (ValueError, TypeError):
            pass
    if el_mw is None or not _close(el_mw, css_mw, SPACING_TOLERANCE):
        issues.append(f"{label}.max-width: elementor={el_mw} vs css={css_mw}px")


def _check_widget(widget: dict, html_tree: dict, issues: list, kit_maps: dict, parent_absorbed_margin: bool = False):
    wtype = widget.get("widgetType")
    s = widget.get("settings", {})

    if wtype == "heading":
        title = _strip_html(s.get("title", ""))
        header_size = s.get("header_size", "")
        el_size = _resolved_typo_size(s, "typography_font_size", kit_maps)
        # Tag search strategy — a small heading widget (h5/h6) with bg styling
        # is almost always emitted from a <span> badge in source. Searching only
        # h1-h6 would match it to a semantically-real h-tag with the same text
        # but completely different size.
        is_badge_like = (header_size in ("h5", "h6")
                          and (s.get("_background_background") or s.get("_border_radius")))
        if header_size == "div" or is_badge_like:
            tags = {"div", "span", "p"}
        else:
            tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
        candidates = _find_html_nodes(html_tree, title, tags)
        if not candidates and (s.get("_background_background") or s.get("_border_radius")):
            candidates = _find_html_nodes(html_tree, title, {"div", "span"})
        if not candidates:
            return
        # When multiple candidates share the same text, rank by combined
        # similarity of font-size + color to the widget's resolved values.
        # Handles "Free" appearing as an h3 (48px), 7 mod-tag spans (11px
        # #141414), and a tier div (11px #6b6b6b) — all at once.
        if len(candidates) > 1:
            el_color_hex = _resolved_color(s, "title_color", kit_maps)
            el_color_norm = (to_hex(el_color_hex).lower() if el_color_hex else None)
            def _match_score(n):
                css_sz = px_to_int(n.get("styles", {}).get("font-size", "")) or 0
                size_dist = abs(css_sz - el_size) if el_size else 0
                css_color = to_hex(n.get("styles", {}).get("color", "")) if n.get("styles", {}).get("color") else None
                color_mismatch = 0 if (el_color_norm and css_color and css_color.lower() == el_color_norm) else 100
                return size_dist + color_mismatch
            candidates = sorted(candidates, key=_match_score)
        node = candidates[0]
        tag = node.get("tag", "")
        css = node.get("styles", {})
        # Color: resolve global, skip check on dark bg (inversion to white is intentional)
        el_color = _resolved_color(s, "title_color", kit_maps)
        is_dark_bg = _ancestor_bg_is_dark(node, html_tree)
        # Skip color check on emoji-only headings (inherit body color but emoji renders own)
        has_letters = any(c.isalnum() and ord(c) < 0x2600 for c in title)
        if not has_letters:
            pass  # decorative emoji/symbol heading — no color to enforce
        elif not (is_dark_bg and el_color and to_hex(el_color).lower().startswith("#ffffff")):
            _cmp_color(el_color, css.get("color", ""), f"heading[{tag}]\"{title[:30]}\".color", issues)
        css_size = px_to_int(css.get("font-size", ""))
        if css_size and el_size and not _close(el_size, css_size, FONT_TOLERANCE):
            issues.append(f"heading[{tag}]\"{title[:30]}\".font-size: elementor={el_size}px vs css={css_size}px")
        _check_max_width(widget, node, f"heading[{tag}]\"{title[:30]}\"", issues)
        _check_margin(widget, node, f"heading[{tag}]\"{title[:30]}\"", issues, parent_absorbed_margin)

    elif wtype == "text-editor":
        text = _strip_html(s.get("editor", ""))[:40]
        node = _find_html_node(html_tree, text, {"p", "div", "span", "blockquote"})
        if not node:
            return
        css = node.get("styles", {})
        el_color = _resolved_color(s, "text_color", kit_maps)
        css_color = css.get("color", "")
        # Skip color check if on dark bg (inversion to white is intentional)
        is_dark_bg = _ancestor_bg_is_dark(node, html_tree)
        if not (is_dark_bg and el_color and to_hex(el_color).lower().startswith("#ffffff")):
            _cmp_color(el_color, css_color, f"text\"{text[:30]}\".color", issues)
        el_size = _resolved_typo_size(s, "typography_font_size", kit_maps)
        css_size = px_to_int(css.get("font-size", ""))
        if css_size and el_size and not _close(el_size, css_size, FONT_TOLERANCE):
            issues.append(f"text\"{text[:30]}\".font-size: elementor={el_size}px vs css={css_size}px")
        _check_max_width(widget, node, f"text\"{text[:30]}\"", issues)
        _check_margin(widget, node, f"text\"{text[:30]}\"", issues, parent_absorbed_margin)

    elif wtype == "button":
        text = s.get("text", "")
        candidates = _find_html_nodes(html_tree, text, {"a", "button"})
        if not candidates:
            return
        # Disambiguate duplicates (same button text in multiple places) by matching bg color.
        el_bg_val = _resolved_color(s, "background_color", kit_maps)
        _tmp = to_hex(el_bg_val) if el_bg_val else None
        el_bg_hex = _tmp.lower() if _tmp else None
        el_tc_val = _resolved_color(s, "button_text_color", kit_maps)
        _tmptc = to_hex(el_tc_val) if el_tc_val else None
        el_tc_hex = _tmptc.lower() if _tmptc else None
        node = candidates[0]
        if len(candidates) > 1:
            best_score = -1
            for c in candidates:
                cs = c.get("styles", {})
                css_bg_raw = cs.get("background-color") or cs.get("background") or ""
                css_tc_raw = cs.get("color") or ""
                _tbg = to_hex(css_bg_raw) if css_bg_raw else None
                css_bg_hex = _tbg.lower() if _tbg else None
                _ttc = to_hex(css_tc_raw) if css_tc_raw else None
                css_tc_hex = _ttc.lower() if _ttc else None
                # Score: +2 for bg match, +1 for text color match; +2 for transparent-match
                score = 0
                if el_bg_hex and css_bg_hex and el_bg_hex == css_bg_hex:
                    score += 2
                elif (el_bg_hex in ("#ffffff00", None) and css_bg_raw in ("transparent", "none", "")):
                    score += 2
                if el_tc_hex and css_tc_hex and el_tc_hex == css_tc_hex:
                    score += 1
                if score > best_score:
                    best_score = score
                    node = c
        css = node.get("styles", {})
        el_tc = _resolved_color(s, "button_text_color", kit_maps)
        _cmp_color(el_tc, css.get("color", ""), f"button\"{text}\".text-color", issues)
        _cmp_color(el_bg_val, css.get("background-color") or css.get("background"),
                   f"button\"{text}\".bg", issues)

    elif wtype == "icon-list":
        items = s.get("icon_list", [])
        # Match by finding a sibling group where ALL items appear as <a> descendants
        # (prevents header match when checking footer icon-list with same first link)
        target_texts = {(it.get("text") or "").strip().lower() for it in items if it.get("text")}
        if not target_texts:
            return
        best_node = None
        best_overlap = 0
        for node in _iter_html(html_tree):
            if node.get("tag") not in ("nav", "div", "ul"):
                continue
            link_texts = {
                _all_text(a).strip().lower()
                for a in _iter_html(node)
                if a.get("tag") == "a"
            }
            overlap = len(target_texts & link_texts)
            # Pick the container with MAXIMUM overlap (favors exact match)
            if overlap > best_overlap and overlap >= min(2, len(target_texts)):
                best_overlap = overlap
                best_node = node
        if not best_node:
            return
        # Find first <a> inside best_node to get per-link styling
        for a in _iter_html(best_node):
            if a.get("tag") == "a":
                css = a.get("styles", {})
                _cmp_color(_resolved_color(s, "text_color", kit_maps),
                           css.get("color", ""), "nav-link.color", issues)
                _cmp_size(s.get("icon_typography_font_size"),
                          css.get("font-size", ""), "nav-link.font-size", issues)
                css_spacing = (px_to_int(css.get("margin-left", "")) or
                               px_to_int(css.get("margin-right", "")))
                sb = s.get("space_between")
                el_spacing = None
                if isinstance(sb, dict):
                    try:
                        el_spacing = int(float(sb.get("size")))
                    except (ValueError, TypeError):
                        pass
                if css_spacing and el_spacing is not None and not _close(el_spacing, css_spacing, SPACING_TOLERANCE):
                    issues.append(f"nav-link.spacing: elementor={el_spacing}px vs css={css_spacing}px")
                break


def _check_section_bg(container: dict, html_section: dict, issues: list, kit_maps: dict):
    """Compare top-level container background against source section CSS."""
    s = container.get("settings", {})
    css = html_section.get("styles", {}) or {}
    tag = html_section.get("tag", "section")
    cls = " ".join(html_section.get("classes", []))[:20]
    label = f"section<{tag}.{cls}>"
    bg_raw = css.get("background") or css.get("background-image") or ""
    css_bg_color = css.get("background-color") or ""

    # Gradient case
    if "gradient" in bg_raw:
        el_mode = s.get("background_background")
        if el_mode != "gradient":
            # Check if a child inner container has the gradient (styled wrapper pattern)
            has_gradient_child = any(
                c.get("settings", {}).get("background_background") == "gradient"
                for c in container.get("elements", [])
                if c.get("elType") == "container"
            )
            if not has_gradient_child:
                issues.append(f"{label}.bg: css=gradient vs elementor={el_mode or 'none'}")
        return

    # Solid color case
    css_hex = to_hex(css_bg_color) if css_bg_color else None
    if not css_hex:
        return
    el_mode = s.get("background_background")
    el_bg = _resolved_color(s, "background_color", kit_maps)
    el_hex = to_hex(el_bg).lower() if el_bg else None
    if el_mode != "classic" or not el_hex:
        # Check if child inner container carries the bg (styled wrapper pattern)
        for c in container.get("elements", []):
            if c.get("elType") != "container":
                continue
            cs = c.get("settings", {})
            if cs.get("background_background") == "classic":
                cbg = _resolved_color(cs, "background_color", kit_maps)
                if cbg and to_hex(cbg).lower() == css_hex.lower():
                    return
        issues.append(f"{label}.bg: css={css_hex} vs elementor={el_hex or 'none'} (mode={el_mode or 'none'})")
        return
    if el_hex != css_hex.lower():
        issues.append(f"{label}.bg: css={css_hex} vs elementor={el_hex}")


def _check_container(container: dict, html_tree: dict, issues: list, kit_maps: dict, depth: int = 0):
    # If this container has its own _margin set, its child widgets should NOT
    # independently re-apply the same CSS margin (avatar pattern, styled wrappers).
    absorbed = bool(container.get("settings", {}).get("_margin") or
                    container.get("settings", {}).get("margin"))
    for child in container.get("elements", []):
        if child.get("elType") == "widget":
            _check_widget(child, html_tree, issues, kit_maps, parent_absorbed_margin=absorbed)
        elif child.get("elType") == "container":
            _check_container(child, html_tree, issues, kit_maps, depth + 1)


def _load_kit_maps(kit_path: str | None) -> dict:
    """Build lookup maps from kit.json: global id → value."""
    maps = {"color": {}, "typo": {}}
    if not kit_path:
        return maps
    try:
        with open(kit_path) as f:
            kit = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return maps
    for c in (kit.get("system_colors", []) + kit.get("custom_colors", [])):
        maps["color"][c.get("_id")] = c.get("color")
    for t in (kit.get("system_typography", []) + kit.get("custom_typography", [])):
        tid = t.get("_id")
        maps["typo"][tid] = {
            "family": t.get("typography_font_family"),
            "size": t.get("typography_font_size", {}).get("size") if isinstance(t.get("typography_font_size"), dict) else None,
            "weight": t.get("typography_font_weight"),
        }
    return maps


def _resolve_global(globals_map: dict, kit_maps: dict, key: str, kind: str):
    """Resolve __globals__ reference to actual value from kit."""
    ref = (globals_map or {}).get(key, "")
    m = re.search(r"id=([\w-]+)", ref)
    if not m:
        return None
    gid = m.group(1)
    return kit_maps.get(kind, {}).get(gid)


def verify(html_path: str, output_json_path: str, kit_path: str | None = None) -> dict:
    """Compare Elementor output against HTML source. Return summary dict."""
    with open(html_path) as f:
        html = f.read()
    with open(output_json_path) as f:
        layout = json.load(f)

    # Auto-detect kit file next to output
    if kit_path is None:
        import os
        candidate = os.path.splitext(output_json_path)[0] + ".kit.json"
        if os.path.exists(candidate):
            kit_path = candidate
    kit_maps = _load_kit_maps(kit_path)
    parsed = parse_html(html)
    # Build a virtual root node containing all sections for traversal
    root = {"tag": "root", "children": parsed["sections"]}

    all_issues: list[str] = []
    widget_count = 0

    def count_widgets(el):
        nonlocal widget_count
        if el.get("elType") == "widget":
            widget_count += 1
        for c in el.get("elements", []):
            count_widgets(c)

    html_sections = parsed["sections"]
    for i, section in enumerate(layout):
        count_widgets(section)
        # Match top-level container to source section by index (order preserved)
        if i < len(html_sections):
            _check_section_bg(section, html_sections[i], all_issues, kit_maps)
        _check_container(section, root, all_issues, kit_maps)

    return {
        "widgets": widget_count,
        "issues": all_issues,
        "passed": len(all_issues) == 0,
    }


def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 -m html2elementor.verify <input.html> <output.json>", file=sys.stderr)
        sys.exit(1)
    result = verify(sys.argv[1], sys.argv[2])
    print(f"Widgets checked: {result['widgets']}")
    print(f"Issues: {len(result['issues'])}")
    for issue in result["issues"]:
        print(f"  - {issue}")
    if result["passed"]:
        print("\n✓ All checks passed")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
