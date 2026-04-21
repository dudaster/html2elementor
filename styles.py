"""CSS value parsing + Elementor settings mapping."""
from __future__ import annotations
import re
from typing import Any
from .colors import to_hex


_CLAMP_RE = re.compile(r"clamp\(\s*([^,]+),\s*([^,]+),\s*([^)]+)\)")
_VW_RE = re.compile(r"(-?\d+(?:\.\d+)?)vw")
_REM_RE = re.compile(r"(-?\d+(?:\.\d+)?)rem")

_DESKTOP_W = 1440  # viewport width used to evaluate vw units


def _resolve_length(val: str) -> float | None:
    """Resolve a CSS length to px. Handles px, vw, rem, clamp().

    Returns None for context-dependent units (ch, em, %) that cannot be
    resolved without knowing the parent font-size or container width.
    """
    val = val.strip()
    # Bail early on units that require font/container context
    if re.search(r"\d(ch|em|%|ex|lh)$", val):
        return None
    # clamp(min, preferred, max) → evaluate preferred at desktop viewport
    m = _CLAMP_RE.match(val)
    if m:
        lo = _resolve_length(m.group(1))
        mid = _resolve_length(m.group(2))
        hi = _resolve_length(m.group(3))
        if None not in (lo, mid, hi):
            return max(lo, min(mid, hi))
        # Fallback: use the max value (desktop preferred)
        return hi if hi is not None else lo
    # vw
    mv = _VW_RE.match(val)
    if mv:
        return float(mv.group(1)) * _DESKTOP_W / 100
    # rem (assume 1rem = 16px)
    mr = _REM_RE.match(val)
    if mr:
        return float(mr.group(1)) * 16
    # plain number / px
    mp = re.match(r"(-?\d+(?:\.\d+)?)", val)
    return float(mp.group(1)) if mp else None


def px_to_int(css: str | None) -> int | None:
    if not css:
        return None
    v = _resolve_length(str(css))
    return int(v) if v is not None else None


def px_to_float(css: str | None) -> float | None:
    if not css:
        return None
    return _resolve_length(str(css))


def normalize_weight(css: str | None) -> str | None:
    if not css:
        return None
    s = str(css).lower().strip()
    kw = {"normal": "400", "bold": "700", "lighter": "300", "bolder": "800"}
    if s in kw:
        return kw[s]
    if re.match(r"^\d{3}$", s):
        return s
    return None


def text_align(styles: dict) -> str:
    ta = (styles.get("text-align") or styles.get("textAlign") or "").lower()
    if ta in ("left", "start"):
        return "left"
    if ta in ("right", "end"):
        return "right"
    if ta == "center":
        return "center"
    if ta == "justify":
        return "justify"
    return "left"


def css_padding_to_elementor(styles: dict) -> dict:
    def px(prop: str) -> str:
        for key in (prop, _camel(prop)):
            v = styles.get(key)
            if v:
                m = re.match(r"(-?\d+(?:\.\d+)?)", str(v))
                if m:
                    return str(int(float(m.group(1))))
        return "0"
    return {
        "unit": "px",
        "top": px("padding-top"),
        "right": px("padding-right"),
        "bottom": px("padding-bottom"),
        "left": px("padding-left"),
        "isLinked": False,
    }


def apply_typography(settings: dict, styles: dict) -> None:
    font_family = _clean_font(styles.get("font-family") or styles.get("fontFamily") or "")
    font_size = px_to_int(styles.get("font-size") or styles.get("fontSize"))
    font_weight = normalize_weight(styles.get("font-weight") or styles.get("fontWeight"))
    line_height = styles.get("line-height") or styles.get("lineHeight")
    letter_spacing = px_to_int(styles.get("letter-spacing") or styles.get("letterSpacing"))
    text_transform = styles.get("text-transform") or styles.get("textTransform")

    if not (font_family or font_size or font_weight):
        return

    settings["typography_typography"] = "custom"
    if font_family:
        settings["typography_font_family"] = font_family
    if font_size:
        settings["typography_font_size"] = {"unit": "px", "size": str(font_size), "sizes": []}
    if font_weight:
        settings["typography_font_weight"] = font_weight
    if line_height and line_height != "normal":
        lh_str = str(line_height).strip()
        if lh_str.endswith("px") and font_size:
            # Absolute px value — convert to em ratio
            lh_px = px_to_float(lh_str)
            if lh_px:
                settings["typography_line_height"] = {
                    "unit": "em", "size": round(lh_px / font_size, 2), "sizes": []
                }
        elif lh_str.endswith("em"):
            lh_em = px_to_float(lh_str)
            if lh_em:
                settings["typography_line_height"] = {
                    "unit": "em", "size": round(lh_em, 2), "sizes": []
                }
        else:
            # Unitless ratio (e.g., "1.1", "1.6") — already a multiplier, use as em
            lh_ratio = px_to_float(lh_str)
            if lh_ratio and lh_ratio > 0.5:
                settings["typography_line_height"] = {
                    "unit": "em", "size": round(lh_ratio, 2), "sizes": []
                }
    if letter_spacing and letter_spacing != 0:
        settings["typography_letter_spacing"] = {
            "unit": "px", "size": letter_spacing, "sizes": []
        }
    if text_transform and text_transform not in ("none", "normal"):
        settings["typography_text_transform"] = text_transform

    font_style = styles.get("font-style") or styles.get("fontStyle")
    if font_style and font_style not in ("normal", "inherit"):
        settings["typography_font_style"] = font_style

    g = settings.get("__globals__", {})
    g.pop("typography_typography", None)
    if not g and "__globals__" in settings:
        del settings["__globals__"]


def apply_card_styling(settings: dict, styles: dict) -> None:
    bg = to_hex(styles.get("background-color") or styles.get("backgroundColor"))
    if bg:
        settings["_background_background"] = "classic"
        settings["_background_color"] = bg

    for prefix, side in [("border-top", "top"), ("border-right", "right"),
                          ("border-bottom", "bottom"), ("border-left", "left")]:
        w_key = f"{prefix}-width"
        for k in (w_key, _camel(w_key)):
            if styles.get(k):
                bw = px_to_int(styles[k]) or 0
                if bw:
                    settings.setdefault("_border_border", "solid")
                    settings.setdefault("_border_width", {
                        "unit": "px", "top": "0", "right": "0",
                        "bottom": "0", "left": "0", "isLinked": False
                    })
                    settings["_border_width"][side] = str(bw)
                break

    border_col = to_hex(styles.get("border-top-color") or styles.get("borderTopColor") or
                        styles.get("border-color") or styles.get("borderColor"))
    if border_col and "_border_border" in settings:
        settings["_border_color"] = border_col

    corners = ["top-left", "top-right", "bottom-left", "bottom-right"]
    el_corners = ["top", "right", "left", "bottom"]
    radii = {}
    for css_corner, el_corner in zip(corners, el_corners):
        prop = f"border-{css_corner}-radius"
        v = px_to_int(styles.get(prop) or styles.get(_camel(prop)))
        if v:
            radii[el_corner] = str(v)
    if radii:
        settings["_border_radius"] = {
            "unit": "px", **{k: "0" for k in ("top", "right", "bottom", "left")},
            **radii, "isLinked": len(set(radii.values())) == 1,
        }

    shadow = parse_box_shadow(styles.get("box-shadow") or styles.get("boxShadow"))
    if shadow:
        settings["_box_shadow_box_shadow_type"] = "yes"
        settings["_box_shadow_box_shadow"] = shadow

    pt = px_to_int(styles.get("padding-top") or styles.get("paddingTop")) or 0
    pr = px_to_int(styles.get("padding-right") or styles.get("paddingRight")) or 0
    pb = px_to_int(styles.get("padding-bottom") or styles.get("paddingBottom")) or 0
    pl = px_to_int(styles.get("padding-left") or styles.get("paddingLeft")) or 0
    if any((pt, pr, pb, pl)):
        settings["_padding"] = {
            "unit": "px",
            "top": str(pt), "right": str(pr),
            "bottom": str(pb), "left": str(pl),
            "isLinked": len({pt, pr, pb, pl}) == 1,
        }


def parse_box_shadow(css: str | None) -> dict | None:
    if not css or css == "none":
        return None
    color_match = re.search(r"(rgba?\([^)]+\)|#[0-9a-fA-F]{3,8})", css)
    color_str = color_match.group(1) if color_match else "rgba(0,0,0,0.1)"
    remainder = css.replace(color_str, "").strip()
    nums = re.findall(r"-?\d+(?:\.\d+)?", remainder)
    if len(nums) < 2:
        return None
    vals = (nums + ["0"] * 4)[:4]
    color = to_hex(color_str) or "#00000020"
    return {
        "horizontal": int(float(vals[0])),
        "vertical": int(float(vals[1])),
        "blur": int(float(vals[2])),
        "spread": int(float(vals[3])),
        "color": color,
    }


def parse_radius(css: str | None) -> dict:
    m = re.match(r"(\d+)", css or "")
    val = m.group(1) if m else "4"
    return {
        "unit": "px",
        "top": val, "right": val, "bottom": val, "left": val,
        "isLinked": True,
    }


def _clean_font(css: str) -> str:
    if not css:
        return ""
    return css.split(",")[0].strip().strip('"').strip("'")


def _camel(kebab: str) -> str:
    parts = kebab.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])
