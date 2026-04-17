"""Assemble valid Elementor _elementor_data JSON."""
from __future__ import annotations
import uuid
from typing import Any


def _id() -> str:
    return uuid.uuid4().hex[:7]


def build_layout(mapped_sections: list[tuple[dict, list[dict]]]) -> list[dict]:
    layout: list[dict] = []
    for container_settings, element_specs in mapped_sections:
        children = [_build_element(spec) for spec in element_specs]
        layout.append({
            "id": _id(),
            "elType": "container",
            "settings": container_settings,
            "elements": children,
            "isInner": False,
        })
    return layout


def _build_element(spec: dict) -> dict:
    if spec.get("__inner_container__"):
        children = [_build_element(c) for c in spec["children"]]
        settings = spec["settings"]
        # Prevent Elementor's 10px default padding on inner containers
        settings.setdefault("padding", {
            "unit": "px", "top": "0", "right": "0",
            "bottom": "0", "left": "0", "isLinked": True,
        })
        return {
            "id": _id(),
            "elType": "container",
            "settings": settings,
            "elements": children,
            "isInner": True,
        }
    return {
        "id": _id(),
        "elType": "widget",
        "settings": spec["settings"],
        "elements": [],
        "widgetType": spec["widgetType"],
    }
