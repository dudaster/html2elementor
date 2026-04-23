"""Color utilities — hex conversion, darken/lighten, contrast."""
from __future__ import annotations
import colorsys
import re


_NAMED_COLORS = {
    "white": "#ffffff", "black": "#000000",
    "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "pink": "#ffc0cb", "gray": "#808080", "grey": "#808080",
    "silver": "#c0c0c0", "maroon": "#800000", "olive": "#808000",
    "navy": "#000080", "teal": "#008080", "aqua": "#00ffff",
    "lime": "#00ff00", "fuchsia": "#ff00ff", "cyan": "#00ffff",
    "magenta": "#ff00ff", "brown": "#a52a2a", "beige": "#f5f5dc",
}


def to_hex(css: str | None) -> str | None:
    if not css:
        return None
    s = css.strip().lower()
    if s in ("transparent", "none", "currentcolor", "inherit", "initial"):
        return None
    if s in _NAMED_COLORS:
        return _NAMED_COLORS[s]
    # color-mix(in <space>, <colorA> <pct>, <colorB>): CSS 4 feature we can't
    # evaluate, but it nearly always means "tint colorA toward colorB". Fall
    # back to colorA so translucent sticky navs (color-mix(--bg 88%, transparent))
    # still emit a solid-enough approximation instead of dropping the bg entirely.
    if s.startswith("color-mix("):
        inside = s[len("color-mix("):].rsplit(")", 1)[0]
        # Try hex first (most reliable after var() substitution)
        m = re.search(r"#[0-9a-f]{3,8}\b", inside)
        if m:
            return to_hex(m.group(0))
        # Then rgb/rgba
        m = re.search(r"rgba?\([^)]+\)", inside)
        if m:
            return to_hex(m.group(0))
        # Last resort: named color (skip CSS-space keywords like "in", "oklab")
        _SKIP = {"in", "srgb", "oklab", "oklch", "lab", "lch", "hsl", "rgb",
                 "transparent", "longer", "shorter", "hue"}
        for m in re.finditer(r"\b[a-z]+\b", inside):
            tok = m.group(0)
            if tok not in _SKIP and tok in _NAMED_COLORS:
                return _NAMED_COLORS[tok]
        return None
    if s.startswith("#"):
        hx = s[1:]
        if len(hx) == 3:
            hx = "".join(c * 2 for c in hx)
        if len(hx) in (6, 8) and all(c in "0123456789abcdef" for c in hx):
            return f"#{hx}"
        return None
    m = re.match(r"rgba?\(\s*([^)]+)\)", s)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    try:
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        if a < 0.05:
            return None
        if a >= 0.99:
            return f"#{r:02x}{g:02x}{b:02x}"
        return f"#{r:02x}{g:02x}{b:02x}{int(a * 255):02x}"
    except (ValueError, IndexError):
        return None


def darken(hex_color: str, amount: float = 0.12) -> str:
    if not hex_color or not hex_color.startswith("#"):
        return hex_color or ""
    hx = hex_color.lstrip("#")
    alpha = hx[6:] if len(hx) == 8 else ""
    hx = hx[:6]
    if len(hx) != 6:
        return hex_color
    try:
        r, g, b = (max(0, int(int(hx[i:i + 2], 16) * (1 - amount))) for i in (0, 2, 4))
    except ValueError:
        return hex_color
    return f"#{r:02x}{g:02x}{b:02x}{alpha}"


def lighten(hex_color: str, amount: float = 0.12) -> str:
    if not hex_color or not hex_color.startswith("#"):
        return hex_color or ""
    hx = hex_color.lstrip("#")
    alpha = hx[6:] if len(hx) == 8 else ""
    hx = hx[:6]
    if len(hx) != 6:
        return hex_color
    try:
        r, g, b = (min(255, int(int(hx[i:i + 2], 16) + (255 - int(hx[i:i + 2], 16)) * amount)) for i in (0, 2, 4))
    except ValueError:
        return hex_color
    return f"#{r:02x}{g:02x}{b:02x}{alpha}"


def relative_luminance(hex_color: str) -> float:
    hx = hex_color.lstrip("#")[:6]
    rgb = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def is_dark(hex_color: str) -> bool:
    return relative_luminance(hex_color) < 0.2
