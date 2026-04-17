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
    kit_settings, color_map, font_map, typo_map = build_kit(capture)

    sections = detect_sections(capture)

    mapped: list[tuple[dict, list[dict]]] = []
    for sec in sections:
        role = classify_section(sec)
        container, elements = map_section(sec)
        container["_title"] = role
        mapped.append((container, elements))

    layout = build_layout(mapped)

    # Post-pass: replace literal colors/fonts with __globals__ refs
    _apply_globals(layout, color_map, font_map, typo_map)

    return {
        "layout": layout,
        "kit": kit_settings,
        "color_map": color_map,
        "font_map": font_map,
    }


def convert_to_json(html: str, indent: int = 2) -> str:
    result = convert(html)
    return json.dumps(result["layout"], indent=indent, ensure_ascii=False)


def _apply_globals(layout: list[dict], color_map: dict, font_map: dict, typo_map: dict | None = None) -> None:
    """Recursively walk layout and replace literal color/font values with globals refs."""
    for element in layout:
        _apply_globals_to_element(element, color_map, font_map, typo_map)


def _apply_globals_to_element(el: dict, color_map: dict, font_map: dict, typo_map: dict | None = None) -> None:
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

    # Typography → globals ref
    widget_type = el.get("widgetType", "")
    header_size = settings.get("header_size", "")

    if settings.get("typography_typography") == "custom" and typo_map:
        # Try to match per-widget typography to a global (system or custom)
        import re
        family = settings.get("typography_font_family", "")
        weight = settings.get("typography_font_weight", "400")
        size_obj = settings.get("typography_font_size", {})
        size = str(size_obj.get("size", "16")) if isinstance(size_obj, dict) else "16"
        key = (family, str(weight), str(size))
        global_id = typo_map.get(key)
        # Don't replace with global if widget has unique letter-spacing or text-transform,
        # since Elementor ignores these when typography_typography is a global ref.
        has_unique_typo = (
            settings.get("typography_letter_spacing")
            or settings.get("typography_text_transform")
            or settings.get("typography_font_style")
        )
        if global_id and not has_unique_typo:
            globals_dict["typography_typography"] = f"globals/typography?id={global_id}"
            # Remove per-widget values — global handles them
            for k in ("typography_typography", "typography_font_family",
                       "typography_font_weight", "typography_font_size"):
                settings.pop(k, None)
    elif settings.get("typography_typography") != "custom":
        if widget_type == "heading":
            typo_role = "primary" if header_size in ("h1", "h2") else "secondary"
        elif widget_type == "button":
            typo_role = "accent"
        else:
            typo_role = "text"
        globals_dict["typography_typography"] = f"globals/typography?id={typo_role}"

    # Clean empty __globals__
    if not globals_dict:
        settings.pop("__globals__", None)

    # Recurse into children
    for child in el.get("elements", []):
        _apply_globals_to_element(child, color_map, font_map, typo_map)
