"""Parse HTML+CSS into an internal tree for widget mapping.

Node format matches the Playwright dom_capture output so downstream
code (widgets, containers, sections) works without changes.
"""
from __future__ import annotations
import os
from typing import Any
from bs4 import BeautifulSoup, Tag, NavigableString
from .resolver import resolve_all

SKIP_TAGS = {"script", "style", "noscript", "meta", "link", "template", "head"}


def parse_html(html: str, html_path: str | None = None,
               extra_css: list[str] | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    # Inline <style> blocks
    css_sources = [tag.string for tag in soup.find_all("style") if tag.string]

    # External stylesheets via <link rel="stylesheet" href="...">
    if html_path:
        base_dir = os.path.dirname(os.path.abspath(html_path))
        for link in soup.find_all("link", rel=lambda r: r and "stylesheet" in (r if isinstance(r, list) else [r])):
            href = link.get("href", "")
            if not href or href.startswith("http") or href.startswith("//"):
                continue
            css_file = os.path.join(base_dir, href)
            if os.path.isfile(css_file):
                try:
                    with open(css_file) as f:
                        css_sources.append(f.read())
                except OSError:
                    pass

    # Caller-supplied extra CSS (e.g. passed via --css CLI flag)
    if extra_css:
        css_sources.extend(extra_css)

    styles_map = resolve_all(soup, css_sources)

    body = soup.find("body") or soup
    title_tag = soup.find("title")
    title = title_tag.string.strip() if title_tag and title_tag.string else ""

    sections: list[dict] = []
    for child in body.children:
        if isinstance(child, Tag) and child.name not in SKIP_TAGS:
            node = _walk(child, styles_map)
            if node:
                sections.append(node)

    body_styles = styles_map.get(id(body), {})
    page_bg = body_styles.get("background-color") or body_styles.get("background") or "#ffffff"

    return {
        "title": title,
        "url": "",
        "viewport": {"w": 1440, "h": 900},
        "pageBg": page_bg,
        "sections": sections,
    }


def _walk(el: Tag, styles_map: dict, depth: int = 0) -> dict | None:
    if not isinstance(el, Tag):
        return None
    if el.name in SKIP_TAGS:
        return None
    if depth > 15:
        return None

    styles = styles_map.get(id(el), {})

    node: dict[str, Any] = {
        "tag": el.name,
        "classes": (el.get("class") or [])[:],
        "text": _direct_text(el),
        "styles": styles,
        "children": [],
        "_order": _child_order(el),
    }

    if el.name == "img":
        node["src"] = el.get("src", "")
        node["alt"] = el.get("alt", "")
    if el.name == "a":
        node["href"] = el.get("href", "")
    if el.name == "button":
        node["text"] = el.get_text(strip=True)
    if el.name == "input":
        node["type"] = el.get("type", "text")
        node["placeholder"] = el.get("placeholder", "")
        node["name"] = el.get("name", "")

    for child in el.children:
        if isinstance(child, Tag):
            child_node = _walk(child, styles_map, depth + 1)
            if child_node:
                node["children"].append(child_node)

    return node


def _direct_text(el: Tag) -> str:
    parts = []
    for child in el.children:
        if isinstance(child, NavigableString) and not isinstance(child, Tag):
            parts.append(str(child).strip())
    return " ".join(p for p in parts if p)


def _child_order(el: Tag) -> list:
    """Return interleaved list of text strings and child indices, preserving DOM order."""
    order = []
    child_idx = 0
    for item in el.children:
        if isinstance(item, NavigableString) and not isinstance(item, Tag):
            text = str(item).strip()
            if text:
                order.append(("text", text))
        elif isinstance(item, Tag):
            order.append(("child", child_idx))
            child_idx += 1
    return order
