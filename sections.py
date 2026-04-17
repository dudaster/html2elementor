"""Detect logical sections from parsed HTML tree."""
from __future__ import annotations
from typing import Iterator

SECTION_TAGS = {"section", "header", "footer", "nav", "main", "article"}


def iter_tree(node: dict) -> Iterator[dict]:
    yield node
    for child in node.get("children", []):
        yield from iter_tree(child)


def detect_sections(capture: dict) -> list[dict]:
    all_nodes: list[dict] = []
    for root in capture.get("sections", []):
        all_nodes.extend(iter_tree(root))

    section_nodes = [
        n for n in all_nodes
        if n.get("tag") in SECTION_TAGS and n.get("children")
    ]

    # Deduplicate: keep outermost only (header containing nav → keep header)
    kept: list[dict] = []
    ids_seen: set[int] = set()
    for n in section_nodes:
        nid = id(n)
        # Skip if any ancestor is already in kept
        is_child = False
        for k in kept:
            if _is_descendant_of(n, k):
                is_child = True
                break
        if is_child:
            continue
        kept.append(n)
        ids_seen.add(nid)

    # Also include body-level divs with background (announcement bars, cookie bars)
    for root in capture.get("sections", []):
        if root.get("tag") == "div" and root not in kept:
            styles = root.get("styles", {})
            has_bg = bool(styles.get("background-color") or styles.get("background"))
            has_text = bool(root.get("text") or any(
                c.get("text") for c in root.get("children", [])
            ))
            if has_bg and has_text:
                kept.insert(0, root)  # announcement bars go at top

    if len(kept) >= 2:
        return kept

    # Fallback: direct children of first root
    roots = capture.get("sections", [])
    if roots and roots[0].get("children"):
        return [c for c in roots[0]["children"] if c.get("children")]
    return section_nodes


def _is_descendant_of(child: dict, parent: dict) -> bool:
    """Check if child appears anywhere in parent's subtree (by identity)."""
    for n in iter_tree(parent):
        if n is child and n is not parent:
            return True
    return False


def classify_section(node: dict) -> str:
    tag = node.get("tag", "")
    classes = " ".join(node.get("classes", [])).lower()

    if tag in ("header", "nav"):
        return "nav"
    if tag == "footer":
        return "footer"
    if "hero" in classes:
        return "hero"

    h1s = sum(1 for n in iter_tree(node) if n.get("tag") == "h1")
    if h1s >= 1:
        return "hero"
    if "testimon" in classes:
        return "testimonials"
    if "cta" in classes or "contact" in classes:
        return "cta"
    h3s = sum(1 for n in iter_tree(node) if n.get("tag") == "h3")
    svgs = sum(1 for n in iter_tree(node) if n.get("tag") == "svg")
    if h3s >= 3 or svgs >= 3:
        return "features"
    return "content"
