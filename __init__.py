"""html2elementor — Convert HTML+CSS to Elementor JSON.

Usage:
    from html2elementor import convert
    result = convert(html_string)
    # result["layout"]  → Elementor _elementor_data JSON array
    # result["kit"]     → Site Settings (colors + typography globals)

CLI:
    python3 -m html2elementor input.html -o layout.json
"""
from __future__ import annotations
import json
from typing import Any

from .parser import parse_html
from .sections import detect_sections, classify_section
from .containers import map_section
from .builder import build_layout
from .globals import build_kit

__version__ = "0.1.0"


def convert(html: str) -> dict[str, Any]:
    """Convert an HTML string to Elementor layout + kit globals.

    Returns dict with:
        "layout": list[dict] — _elementor_data sections
        "kit": dict — site settings (system_colors, custom_colors, system_typography)
        "color_map": dict — {hex: global_id}
        "font_map": dict — {font_name: global_id}
    """
    capture = parse_html(html)

    # Build globals kit from all colors/fonts in the HTML
    kit_settings, color_map, font_map = build_kit(capture)

    sections = detect_sections(capture)

    mapped: list[tuple[dict, list[dict]]] = []
    for sec in sections:
        role = classify_section(sec)
        container, elements = map_section(sec)
        container["_title"] = role
        mapped.append((container, elements))

    layout = build_layout(mapped)

    # Post-pass: replace literal colors/fonts with __globals__ refs
    _apply_globals(layout, color_map, font_map)

    return {
        "layout": layout,
        "kit": kit_settings,
        "color_map": color_map,
        "font_map": font_map,
    }


def convert_to_json(html: str, indent: int = 2) -> str:
    result = convert(html)
    return json.dumps(result["layout"], indent=indent, ensure_ascii=False)


def _apply_globals(layout: list[dict], color_map: dict, font_map: dict) -> None:
    """Recursively walk layout and replace literal color/font values with globals refs."""
    for element in layout:
        _apply_globals_to_element(element, color_map, font_map)


def _apply_globals_to_element(el: dict, color_map: dict, font_map: dict) -> None:
    settings = el.get("settings", {})
    globals_dict = settings.setdefault("__globals__", {})

    # Color fields → globals refs
    _COLOR_FIELDS = {
        "title_color": "color",
        "text_color": "color",
        "button_text_color": "color",
        "button_hover_text_color": "color",
        "background_color": "color",
        "button_background_hover_color": "color",
        "border_color": "color",
        "_background_color": "color",
        "_border_color": "color",
        "_background_hover_color": "color",
        "_border_hover_color": "color",
        "primary_color": "color",
        "hover_primary_color": "color",
        "icon_color": "color",
        "icon_hover_color": "color",
    }

    for field, kind in _COLOR_FIELDS.items():
        val = settings.get(field)
        if isinstance(val, str) and val.startswith("#") and len(val) <= 7:
            global_id = color_map.get(val)
            if global_id:
                globals_dict[field] = f"globals/colors?id={global_id}"
                del settings[field]

    # Typography → globals ref based on widget type + tag
    widget_type = el.get("widgetType", "")
    header_size = settings.get("header_size", "")
    if widget_type == "heading":
        typo_role = "primary" if header_size in ("h1", "h2") else "secondary"
    elif widget_type == "button":
        typo_role = "accent"
    else:
        typo_role = "text"
    # Only set globals ref if we have custom typography that overrides
    if settings.get("typography_typography") == "custom":
        # Keep per-widget custom values (extracted from HTML), they're more precise
        pass
    else:
        globals_dict["typography_typography"] = f"globals/typography?id={typo_role}"

    # Clean empty __globals__
    if not globals_dict:
        settings.pop("__globals__", None)

    # Recurse into children
    for child in el.get("elements", []):
        _apply_globals_to_element(child, color_map, font_map)
