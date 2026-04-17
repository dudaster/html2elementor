"""Resolve CSS styles per element without a browser.

Strategy: parse <style> blocks with tinycss2, use BeautifulSoup's built-in
CSS selector matching (soup.select) to apply rules, then merge inline styles.
"""
from __future__ import annotations
import re
import tinycss2
from bs4 import BeautifulSoup, Tag

INHERITED = {
    "color", "font-family", "font-size", "font-weight", "font-style",
    "line-height", "letter-spacing", "text-align", "text-transform",
    "visibility", "cursor", "direction",
}


def resolve_all(soup: BeautifulSoup, css_sources: list[str]) -> dict[int, dict]:
    """Resolve styles for every element. Returns id(tag) → styles dict."""
    rules = _parse_all_rules(css_sources)

    # Pre-compute: for each CSS rule, find matching elements via BS4 select
    element_styles: dict[int, dict] = {}
    for selector, specificity, declarations in rules:
        try:
            matches = soup.select(selector)
        except Exception:
            continue
        for el in matches:
            eid = id(el)
            entry = element_styles.setdefault(eid, {"_specificity_layers": []})
            entry["_specificity_layers"].append((specificity, declarations))

    # Resolve: flatten specificity layers + merge inline + inherit from parent
    result: dict[int, dict] = {}
    body = soup.find("body") or soup
    _walk_resolve(body, element_styles, result, parent_styles=None)
    return result


def _walk_resolve(el: Tag, element_styles: dict, result: dict,
                  parent_styles: dict | None) -> None:
    if not isinstance(el, Tag):
        return

    styles: dict[str, str] = {}

    # 1. Inherited from parent
    if parent_styles:
        for prop in INHERITED:
            if prop in parent_styles:
                styles[prop] = parent_styles[prop]

    # 2. CSS rules sorted by specificity
    entry = element_styles.get(id(el), {})
    layers = entry.get("_specificity_layers", [])
    for _spec, decls in sorted(layers, key=lambda x: x[0]):
        styles.update(decls)

    # 3. Inline styles (highest priority)
    inline = el.get("style", "")
    if inline:
        styles.update(_parse_inline(inline))

    result[id(el)] = styles

    for child in el.children:
        if isinstance(child, Tag):
            _walk_resolve(child, element_styles, result, styles)


def _parse_all_rules(css_sources: list[str]) -> list[tuple[str, tuple, dict]]:
    """Parse CSS into (selector_str, specificity, declarations) tuples."""
    rules: list[tuple[str, tuple, dict]] = []
    order = 0
    for css_text in css_sources:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
        for rule in parsed:
            if rule.type != "qualified-rule":
                continue
            selector_str = tinycss2.serialize(rule.prelude).strip()
            declarations = _parse_declarations(rule.content)
            if not declarations:
                continue
            # Split comma-separated selectors
            for sel in selector_str.split(","):
                sel = sel.strip()
                if not sel or sel.startswith("@") or ":hover" in sel or ":focus" in sel:
                    continue  # skip pseudo-states (can't resolve statically)
                spec = _estimate_specificity(sel, order)
                rules.append((sel, spec, declarations))
                order += 1
    return rules


def _parse_declarations(tokens: list) -> dict[str, str]:
    decls = tinycss2.parse_declaration_list(tokens, skip_whitespace=True)
    result: dict[str, str] = {}
    for d in decls:
        if d.type == "declaration":
            val = tinycss2.serialize(d.value).strip()
            result[d.lower_name] = val
            _expand_shorthand(result, d.lower_name, val)
    return result


def _parse_inline(style_str: str) -> dict[str, str]:
    decls = tinycss2.parse_declaration_list(style_str, skip_whitespace=True)
    result: dict[str, str] = {}
    for d in decls:
        if d.type == "declaration":
            val = tinycss2.serialize(d.value).strip()
            result[d.lower_name] = val
            _expand_shorthand(result, d.lower_name, val)
    return result


def _expand_shorthand(result: dict, prop: str, value: str) -> None:
    """Expand CSS shorthand properties into longhand equivalents."""
    parts = value.split()
    if prop == "padding" and parts:
        _expand_box(result, "padding", parts)
    elif prop == "margin" and parts:
        _expand_box(result, "margin", parts)
    elif prop == "border-radius" and parts:
        _expand_box(result, "border", parts, suffix="-radius",
                    sides=["top-left", "top-right", "bottom-right", "bottom-left"])
    elif prop in ("border-top", "border-right", "border-bottom", "border-left") and parts:
        side = prop.split("-")[1]  # "top", "right", etc.
        for p in parts:
            if p.endswith("px") or p.isdigit():
                result[f"border-{side}-width"] = p
            elif p in ("solid", "dashed", "dotted", "none"):
                result[f"border-{side}-style"] = p
            elif p.startswith("#") or p.startswith("rgb"):
                result[f"border-{side}-color"] = p
    elif prop == "border" and parts:
        for p in parts:
            if p.endswith("px") or p.isdigit():
                for side in ("top", "right", "bottom", "left"):
                    result[f"border-{side}-width"] = p
            elif p in ("solid", "dashed", "dotted", "none"):
                result["border-style"] = p
            elif p.startswith("#") or p.startswith("rgb"):
                for side in ("top", "right", "bottom", "left"):
                    result[f"border-{side}-color"] = p
    elif prop == "gap" and parts:
        result["row-gap"] = parts[0]
        result["column-gap"] = parts[1] if len(parts) > 1 else parts[0]
    elif prop == "background":
        # background shorthand: may contain color, url(), gradient
        # Simple color value
        for p in parts:
            if p.startswith("#") or p.startswith("rgb"):
                result.setdefault("background-color", p)
                break
        # url()
        url_match = re.search(r"url\(['\"]?([^)'\"\s]+)['\"]?\)", value)
        if url_match:
            result["background-image"] = f"url({url_match.group(1)})"


def _expand_box(result: dict, prefix: str, parts: list[str],
                suffix: str = "", sides: list[str] | None = None) -> None:
    """Expand 1-4 value shorthand into per-side properties."""
    if sides is None:
        sides = ["top", "right", "bottom", "left"]
    n = len(parts)
    if n == 1:
        vals = [parts[0]] * 4
    elif n == 2:
        vals = [parts[0], parts[1], parts[0], parts[1]]
    elif n == 3:
        vals = [parts[0], parts[1], parts[2], parts[1]]
    else:
        vals = parts[:4]
    for side, val in zip(sides, vals):
        key = f"{prefix}-{side}{suffix}" if suffix else f"{prefix}-{side}"
        result.setdefault(key, val)


def _estimate_specificity(selector: str, order: int) -> tuple:
    """Rough specificity: (ids, classes+attrs, tags, order)."""
    ids = selector.count("#")
    classes = selector.count(".") + selector.count("[") + selector.count(":")
    tags = len([p for p in selector.split() if p and not p.startswith((".", "#", "[", ":"))])
    return (ids, classes, tags, order)
