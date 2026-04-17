"""Extract colors + fonts from parsed HTML → build Elementor global kit.

Auto-assigns system roles (primary, secondary, text, accent) based on
CSS usage patterns, then creates named custom globals for remaining values.

Output: kit_settings dict (ready for Site Settings) + a color/font mapping
that widgets use to resolve literal values to __globals__ refs.
"""
from __future__ import annotations
import hashlib
import re
from collections import Counter
from typing import Any
from .colors import to_hex, is_dark, relative_luminance
from .sections import iter_tree


def short_id(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()[:7]


# --- extraction from parsed tree ---

def extract_palette(capture: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Walk the parsed tree and collect all colors + fonts with role hints.

    Returns (color_counter, font_counter) where keys are normalized values
    and values are CSS role hints ("text", "background", "heading", etc).
    """
    colors: Counter[str] = Counter()
    fonts: Counter[str] = Counter()
    color_roles: dict[str, set[str]] = {}
    font_roles: dict[str, set[str]] = {}

    for section in capture.get("sections", []):
        for node in iter_tree(section):
            styles = node.get("styles", {})
            tag = node.get("tag", "")

            # Colors
            for prop, role in [
                ("color", "text"), ("background-color", "bg"),
                ("border-color", "border"), ("border-top-color", "border"),
                ("background", "bg"),
            ]:
                val = to_hex(styles.get(prop))
                if val and len(val) <= 7:  # opaque colors for system globals
                    colors[val] += 1
                    color_roles.setdefault(val, set()).add(role)
                    if tag in ("h1", "h2", "h3"):
                        color_roles[val].add("heading")
                    if tag in ("a", "button"):
                        color_roles[val].add("cta")

            # Fonts
            ff = styles.get("font-family", "")
            if ff:
                clean = ff.split(",")[0].strip().strip('"').strip("'")
                if clean and clean not in ("inherit", "initial", "sans-serif", "serif"):
                    fonts[clean] += 1
                    if tag in ("h1", "h2", "h3"):
                        font_roles.setdefault(clean, set()).add("heading")
                    elif tag in ("p", "span", "li"):
                        font_roles.setdefault(clean, set()).add("body")

    return colors, fonts, color_roles, font_roles


def build_kit(capture: dict) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """Build a complete kit + color/font mapping from a parsed tree.

    Returns:
        kit_settings: dict ready for Elementor site settings
        color_map: {hex_color: global_id} for widget __globals__ refs
        font_map: {font_name: global_id} for typography refs
    """
    colors, fonts, color_roles, font_roles = extract_palette(capture)

    # --- assign system colors ---
    system_colors = _assign_system_colors(colors, color_roles)
    custom_colors = _build_custom_colors(colors, color_roles, system_colors)

    # --- assign system typography ---
    system_typo = _assign_system_fonts(fonts, font_roles)
    custom_typo = _build_custom_typography(system_typo)

    # --- build kit settings ---
    # Extract body/page background
    page_bg = capture.get("pageBg", "#ffffff")
    page_bg_hex = to_hex(page_bg) if page_bg else None

    kit_settings = {
        "system_colors": [
            {"_id": role, "title": role.capitalize(), "color": hex_val}
            for role, hex_val in system_colors.items()
        ],
        "custom_colors": [
            {"_id": short_id(title), "title": title, "color": hex_val}
            for title, hex_val in custom_colors
        ],
        "system_typography": [
            {
                "_id": role, "title": role.capitalize(),
                "typography_typography": "custom",
                "typography_font_family": family,
                "typography_font_weight": weight,
                "typography_font_size": {"unit": "px", "size": size, "sizes": []},
            }
            for role, (family, weight, size) in system_typo.items()
        ],
        "custom_typography": _build_custom_typography(system_typo),
    }

    # Body/page background
    if page_bg_hex and page_bg_hex != "#ffffff":
        kit_settings["body_background_background"] = "classic"
        kit_settings["body_background_color"] = page_bg_hex

    # --- build mappings for widgets ---
    color_map: dict[str, str] = {}
    for role, hex_val in system_colors.items():
        color_map[hex_val] = role
    for title, hex_val in custom_colors:
        color_map[hex_val] = short_id(title)

    font_map: dict[str, str] = {}
    # Priority order: primary > text > secondary > accent (keep first)
    for role in ("primary", "text", "secondary", "accent"):
        family = system_typo[role][0]
        if family not in font_map:
            font_map[family] = role

    return kit_settings, color_map, font_map


def _assign_system_colors(colors: Counter, roles: dict) -> dict[str, str]:
    """Pick 4 system colors from extracted palette."""
    system: dict[str, str] = {}

    skip = {"#ffffff", "#000000", "#fff", "#000"}

    # Text: most frequent color used as text, should be dark
    text_candidates = [
        (c, n) for c, n in colors.most_common(20)
        if "text" in roles.get(c, set()) and is_dark(c) and c not in skip
    ]
    system["text"] = text_candidates[0][0] if text_candidates else "#1a1a2e"

    # Primary: most frequent heading/cta color (non-white/black)
    primary_candidates = [
        (c, n) for c, n in colors.most_common(20)
        if c not in skip and c != system["text"] and
        ("heading" in roles.get(c, set()) or "cta" in roles.get(c, set()))
    ]
    if primary_candidates:
        system["primary"] = primary_candidates[0][0]
    else:
        dark = [(c, n) for c, n in colors.most_common(10) if is_dark(c) and c != system["text"]]
        system["primary"] = dark[0][0] if dark else "#29292a"

    # Secondary/Accent: CTA or prominent saturated colors
    used = set(system.values())
    accent_candidates = [
        (c, n) for c, n in colors.most_common(20)
        if c not in used and "cta" in roles.get(c, set())
    ]
    if not accent_candidates:
        accent_candidates = [
            (c, n) for c, n in colors.most_common(20)
            if c not in used and c not in skip and
            "bg" in roles.get(c, set()) and not _is_neutral(c)
        ]
    system["secondary"] = accent_candidates[0][0] if accent_candidates else "#6366f1"
    used.add(system["secondary"])

    accent2 = [
        (c, n) for c, n in colors.most_common(20)
        if c not in used and c not in skip and not _is_neutral(c)
    ]
    system["accent"] = accent2[0][0] if accent2 else system["primary"]

    return system


def _build_custom_colors(colors: Counter, roles: dict,
                          system: dict[str, str]) -> list[tuple[str, str]]:
    """Build named custom globals for remaining colors."""
    system_vals = set(system.values())
    custom: list[tuple[str, str]] = []

    # Always include utility colors
    custom.append(("Transparent", "#ffffff00"))
    custom.append(("White", "#ffffff"))
    used_names: set[str] = {"Transparent", "White"}
    for hex_val, count in colors.most_common(20):
        if hex_val in system_vals:
            continue
        if hex_val in ("#ffffff", "#000000"):
            continue
        if count < 1:
            continue
        base_name = _name_color(hex_val, roles.get(hex_val, set()))
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name} {suffix}"
            suffix += 1
        used_names.add(name)
        custom.append((name, hex_val))
        if len(custom) >= 10:
            break

    return custom


def _assign_system_fonts(fonts: Counter, roles: dict) -> dict[str, tuple[str, str, int]]:
    """Pick system typography: (family, weight, size) per role."""
    heading_font = body_font = "Inter"

    for font, _n in fonts.most_common(10):
        if "heading" in roles.get(font, set()):
            heading_font = font
            break
    for font, _n in fonts.most_common(10):
        if "body" in roles.get(font, set()) and font != heading_font:
            body_font = font
            break
    if body_font == "Inter" and fonts:
        body_font = fonts.most_common(1)[0][0]

    return {
        "primary": (heading_font, "700", 48),
        "secondary": (heading_font, "600", 32),
        "text": (body_font, "400", 16),
        "accent": (body_font, "500", 16),
    }


def _build_custom_typography(system: dict) -> list:
    """Build custom typography entries for special text styles (e.g. italic review)."""
    body_font = system.get("text", ("Inter", "400", 16))[0]
    return [
        {
            "_id": short_id("Review"),
            "title": "Review",
            "typography_typography": "custom",
            "typography_font_family": body_font,
            "typography_font_weight": "400",
            "typography_font_style": "italic",
            "typography_font_size": {"unit": "px", "size": "16", "sizes": []},
        },
    ]


def _is_neutral(hex_color: str) -> bool:
    """Check if color is near-grey (low saturation)."""
    hx = hex_color.lstrip("#")[:6]
    try:
        r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return True
    spread = max(r, g, b) - min(r, g, b)
    return spread < 30


def _name_color(hex_val: str, roles: set[str]) -> str:
    """Generate a descriptive name for a custom color."""
    lum = relative_luminance(hex_val)
    if "bg" in roles:
        if lum > 0.8:
            return "Light Background"
        if lum < 0.15:
            return "Dark Background"
        return "Section Background"
    if "border" in roles:
        return "Border"
    if "cta" in roles:
        return "CTA Accent"
    if lum > 0.85:
        return "Light Surface"
    if lum < 0.1:
        return "Dark Surface"
    return "Accent"
