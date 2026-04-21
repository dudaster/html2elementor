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

# Common CSS color keywords that may appear in shorthand values
_CSS_COLOR_KEYWORDS = {
    "white", "black", "red", "green", "blue", "yellow", "orange", "purple",
    "pink", "gray", "grey", "silver", "maroon", "olive", "navy", "teal",
    "aqua", "lime", "fuchsia", "cyan", "magenta", "brown", "beige",
    "transparent", "currentcolor",
}


def resolve_all(soup: BeautifulSoup, css_sources: list[str]) -> dict[int, dict]:
    """Resolve styles for every element. Returns id(tag) → styles dict."""
    # Extract CSS custom properties defined on :root / html / body so we can
    # substitute var(--x) references in later styles.
    css_vars = _extract_css_vars(css_sources)
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
    _walk_resolve(body, element_styles, result, parent_styles=None, css_vars=css_vars)
    return result


def _extract_css_vars(css_sources: list[str]) -> dict[str, str]:
    """Find --name: value declarations in :root/html/body selectors and capture
    them. Resolves chains (e.g. --foo: var(--bar) → substituted)."""
    vars_map: dict[str, str] = {}
    var_selectors = {":root", "html", "body", ":root, html, body", "html, body"}
    for css_text in css_sources:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
        for rule in parsed:
            if rule.type != "qualified-rule":
                continue
            selector = tinycss2.serialize(rule.prelude).strip()
            if selector.lower() not in var_selectors and ":root" not in selector:
                continue
            decls = tinycss2.parse_declaration_list(rule.content, skip_whitespace=True)
            for d in decls:
                if d.type == "declaration" and d.name.startswith("--"):
                    vars_map[d.name] = tinycss2.serialize(d.value).strip()
    # Resolve var-to-var chains (one pass is usually enough)
    for _ in range(3):
        changed = False
        for k, v in list(vars_map.items()):
            new = _substitute_vars(v, vars_map)
            if new != v:
                vars_map[k] = new
                changed = True
        if not changed:
            break
    return vars_map


_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)")


def _substitute_vars(value: str, css_vars: dict[str, str]) -> str:
    """Replace var(--name, fallback) with resolved value (or fallback)."""
    if "var(" not in value:
        return value
    def _sub(m):
        name = m.group(1)
        fallback = (m.group(2) or "").strip()
        return css_vars.get(name, fallback)
    # Apply up to 3 times for nested var refs
    for _ in range(3):
        new = _VAR_RE.sub(_sub, value)
        if new == value:
            break
        value = new
    return value


def _walk_resolve(el: Tag, element_styles: dict, result: dict,
                  parent_styles: dict | None, css_vars: dict | None = None) -> None:
    if not isinstance(el, Tag):
        return
    css_vars = css_vars or {}

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
        for k, v in decls.items():
            if str(v).strip().lower() == "inherit":
                # Keep already-inherited value from step 1; don't overwrite with literal "inherit"
                pass
            else:
                styles[k] = v

    # 3. Inline styles (highest priority)
    inline = el.get("style", "")
    if inline:
        parsed_inline = _parse_inline(inline)
        for k, v in parsed_inline.items():
            if str(v).strip().lower() != "inherit":
                styles[k] = v

    # 4. Substitute CSS var() references AFTER cascade so declarations that
    # override will still use resolved variables. Also re-expand shorthand
    # for keys whose values changed (e.g. background: var(--color) → hex
    # should populate background-color).
    if css_vars:
        for k in list(styles.keys()):
            v = styles[k]
            if isinstance(v, str) and "var(" in v:
                new_val = _substitute_vars(v, css_vars)
                styles[k] = new_val
                if new_val != v:
                    _expand_shorthand(styles, k, new_val)

    result[id(el)] = styles

    for child in el.children:
        if isinstance(child, Tag):
            _walk_resolve(child, element_styles, result, styles, css_vars)


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
        # Extract color — hex, rgb/rgba, hsl, or named color keyword
        if "gradient" not in value and "url(" not in value:
            # Try: first part that looks like a color
            for p in parts:
                if (p.startswith("#") or p.startswith("rgb") or
                    p.startswith("hsl") or p in _CSS_COLOR_KEYWORDS):
                    result.setdefault("background-color", p)
                    break
        else:
            # Mixed: still try to find a solid color in the string
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
