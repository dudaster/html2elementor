"""Color utilities — hex conversion, darken/lighten, contrast."""
from __future__ import annotations
import colorsys
import re


def to_hex(css: str | None) -> str | None:
    if not css:
        return None
    s = css.strip().lower()
    if s in ("transparent", "none", "currentcolor", "inherit", "initial"):
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
