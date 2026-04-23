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


def resolve_all(soup: BeautifulSoup, css_sources: list[str]) -> tuple[dict[int, dict], dict[int, dict], dict[int, dict], dict[int, dict]]:
    """Resolve styles for every element.

    Returns (styles_map, hover_map, tablet_map, mobile_map) where:
      styles_map[id(tag)] = resolved base styles (cascade + inherit + inline + vars)
      hover_map[id(tag)]  = hover-state overlay
      tablet_map[id(tag)] = DIFF — only properties that change at tablet (≤1024px)
      mobile_map[id(tag)] = DIFF — only properties that change at mobile (≤767px)
    """
    # Extract CSS custom properties defined on :root / html / body so we can
    # substitute var(--x) references in later styles.
    css_vars = _extract_css_vars(css_sources)
    rules, hover_rules, media_rules = _parse_all_rules(css_sources)

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

    # Hover rules: match selector with :hover stripped, attach declarations
    # to each element. Specificity order preserved so later rules win.
    hover_map: dict[int, dict] = {}
    for selector, specificity, declarations in hover_rules:
        base_sel = _strip_hover(selector)
        if not base_sel:
            continue
        try:
            matches = soup.select(base_sel)
        except Exception:
            continue
        for el in matches:
            eid = id(el)
            bucket = hover_map.setdefault(eid, {"_layers": []})
            bucket["_layers"].append((specificity, declarations))

    # Flatten hover layers into merged dicts, then substitute vars
    hover_result: dict[int, dict] = {}
    for eid, bucket in hover_map.items():
        merged: dict[str, str] = {}
        for _spec, decls in sorted(bucket["_layers"], key=lambda x: x[0]):
            merged.update(decls)
        if css_vars:
            for k in list(merged.keys()):
                v = merged[k]
                if isinstance(v, str) and "var(" in v:
                    new_val = _substitute_vars(v, css_vars)
                    merged[k] = new_val
                    if new_val != v:
                        _expand_shorthand(merged, k, new_val)
        hover_result[eid] = merged

    # Resolve: flatten specificity layers + merge inline + inherit from parent
    result: dict[int, dict] = {}
    body = soup.find("body") or soup
    _walk_resolve(body, element_styles, result, parent_styles=None, css_vars=css_vars)

    # Filter hover: inline style beats selector-level :hover, so any property
    # the element has set inline should not appear in hover_result.
    for eid, styles in result.items():
        inline_keys = styles.get("_inline_keys") or set()
        if not inline_keys or eid not in hover_result:
            continue
        for k in list(hover_result[eid].keys()):
            if k in inline_keys:
                del hover_result[eid][k]

    # Apply media-query rules to compute tablet/mobile DIFF maps.
    # Elementor breakpoints: tablet applies to ≤1024, mobile to ≤767.
    # A source @media (max-width: N) rule applies at a breakpoint if N >= that
    # breakpoint's max-width floor. We approximate: rules with N >= 768 apply
    # at tablet; rules with N >= 390 apply at mobile.
    tablet_map: dict[int, dict] = {}
    mobile_map: dict[int, dict] = {}
    for bp in ("tablet", "mobile"):
        bp_rules = [r for r in media_rules if _media_applies(r[0], bp)]
        if not bp_rules:
            continue
        # Layer the matching rules onto each element (higher-specificity wins)
        bp_elem: dict[int, list] = {}
        for _mq, selector, specificity, declarations in bp_rules:
            try:
                matches = soup.select(selector)
            except Exception:
                continue
            for el in matches:
                bp_elem.setdefault(id(el), []).append((specificity, declarations))
        target_map = tablet_map if bp == "tablet" else mobile_map
        for eid, layers in bp_elem.items():
            base_styles = result.get(eid, {})
            override: dict[str, str] = {}
            for _spec, decls in sorted(layers, key=lambda x: x[0]):
                for k, v in decls.items():
                    val = v
                    if isinstance(val, str) and "var(" in val:
                        val = _substitute_vars(val, css_vars)
                    # Only include if it differs from base
                    if base_styles.get(k) != val:
                        override[k] = val
            if override:
                target_map[eid] = override

    return result, hover_result, tablet_map, mobile_map


def _media_applies(mq: str, breakpoint: str) -> bool:
    """Check if a media query's max-width applies to an Elementor breakpoint.
    breakpoint ∈ {'tablet', 'mobile'}."""
    m = re.search(r"max-width:\s*(\d+)", mq)
    if not m:
        # Treat non-max-width queries (e.g. prefers-color-scheme) as not applicable
        return False
    n = int(m.group(1))
    if breakpoint == "tablet":
        return n >= 768
    if breakpoint == "mobile":
        return n >= 380
    return False


def _strip_hover(selector: str) -> str:
    """Strip :hover/:focus/:active pseudo-classes for BS4 matching.
    `.btn:hover` → `.btn`; `a:hover span` → `a span`. Returns empty string if
    nothing remains (e.g. just `:hover`)."""
    cleaned = re.sub(r":(?:hover|focus|active|focus-visible|focus-within)\b", "", selector)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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
    inline_keys: set[str] = set()
    if inline:
        parsed_inline = _parse_inline(inline)
        for k, v in parsed_inline.items():
            if str(v).strip().lower() != "inherit":
                styles[k] = v
                inline_keys.add(k)
                # Also track longhands that this shorthand expanded to, so a
                # later inline `background: var(--ink)` correctly marks
                # `background-color` as inline-set too. Used downstream to
                # filter :hover rules (inline beats selector-level :hover).
                tmp: dict[str, str] = {}
                _expand_shorthand(tmp, k, v)
                inline_keys.update(tmp.keys())

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
                    # If this was an inline-set shorthand, the longhands it
                    # now expands to are also inline-authoritative. Without
                    # this, inline `background: var(--ink)` would only mark
                    # `background` as inline, missing `background-color`.
                    if k in inline_keys:
                        tmp2: dict[str, str] = {}
                        _expand_shorthand(tmp2, k, new_val)
                        inline_keys.update(tmp2.keys())

    # Stash inline-set property names under a private key so downstream
    # callers (hover filter) know which props can't be overridden by
    # selector-level :hover rules.
    if inline_keys:
        styles["_inline_keys"] = inline_keys
    result[id(el)] = styles

    for child in el.children:
        if isinstance(child, Tag):
            _walk_resolve(child, element_styles, result, styles, css_vars)


def _parse_all_rules(css_sources: list[str]) -> tuple[list[tuple[str, tuple, dict]], list[tuple[str, tuple, dict]], list[tuple[str, str, tuple, dict]]]:
    """Parse CSS into (base_rules, hover_rules, media_rules).

    base_rules:  selectors without :hover/:focus/:active — applied to static styles
    hover_rules: selectors that include one of those pseudo-classes
    media_rules: rules inside @media blocks, returned as (media_query, sel, spec, decls)
    """
    rules: list[tuple[str, tuple, dict]] = []
    hover_rules: list[tuple[str, tuple, dict]] = []
    media_rules: list[tuple[str, str, tuple, dict]] = []
    order = [0]  # mutable holder for nested helper
    hover_re = re.compile(r":(?:hover|focus|active|focus-visible|focus-within)\b")

    def _process_qualified(rule, media_query: str | None):
        selector_str = tinycss2.serialize(rule.prelude).strip()
        declarations = _parse_declarations(rule.content)
        if not declarations:
            return
        for sel in selector_str.split(","):
            sel = sel.strip()
            if not sel or sel.startswith("@"):
                continue
            spec = _estimate_specificity(sel, order[0])
            if media_query is not None:
                media_rules.append((media_query, sel, spec, declarations))
            elif hover_re.search(sel):
                hover_rules.append((sel, spec, declarations))
            else:
                rules.append((sel, spec, declarations))
            order[0] += 1

    for css_text in css_sources:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
        for rule in parsed:
            if rule.type == "qualified-rule":
                _process_qualified(rule, None)
            elif rule.type == "at-rule" and rule.lower_at_keyword == "media":
                mq = tinycss2.serialize(rule.prelude).strip()
                if rule.content is None:
                    continue
                inner = tinycss2.parse_rule_list(rule.content, skip_whitespace=True)
                for sub in inner:
                    if sub.type == "qualified-rule":
                        _process_qualified(sub, mq)
    return rules, hover_rules, media_rules


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
    elif prop == "border-color" and parts:
        # Expand to per-side so per-side rules override correctly (common case:
        # `.card { border: 1px solid var(--line) }` expands to per-side;
        # `.card.variant { border-color: var(--accent) }` must override per-side too)
        n = len(parts)
        if n == 1:
            vals = [parts[0]] * 4
        elif n == 2:
            vals = [parts[0], parts[1], parts[0], parts[1]]
        elif n == 3:
            vals = [parts[0], parts[1], parts[2], parts[1]]
        else:
            vals = parts[:4]
        for side, val in zip(("top", "right", "bottom", "left"), vals):
            result[f"border-{side}-color"] = val
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
