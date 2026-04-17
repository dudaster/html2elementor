"""Upload external images to WordPress media library via WP-CLI.

Returns {url: local_url, id: attachment_id} for use in Elementor JSON.
Only uploads if running with --upload flag and playsand is available.
"""
from __future__ import annotations
import subprocess
import json
import re
from pathlib import Path

PLAYSAND_DIR = Path(__file__).resolve().parents[1] / "playsand"


def upload_image(url: str, title: str = "") -> dict | None:
    """Download external image and sideload into WP. Returns {url, id} or None."""
    if not url or not url.startswith("http"):
        return None
    if not PLAYSAND_DIR.exists():
        return None

    safe_title = re.sub(r'[^a-zA-Z0-9 -]', '', title or 'image')[:50]
    filename = re.sub(r'[^a-zA-Z0-9_-]', '', safe_title.replace(' ', '-').lower()) + ".jpg"

    php = f'''
$url = {json.dumps(url)};
$tmp = download_url($url, 30);
if (is_wp_error($tmp)) {{ echo json_encode(["error" => $tmp->get_error_message()]); exit; }}
$file = ["name" => {json.dumps(filename)}, "tmp_name" => $tmp];
$id = media_handle_sideload($file, 0, {json.dumps(safe_title)});
if (is_wp_error($id)) {{ echo json_encode(["error" => $id->get_error_message()]); exit; }}
echo json_encode(["id" => $id, "url" => wp_get_attachment_url($id)]);
'''.strip()

    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "wp", "wp", "eval", php, "--allow-root"],
            cwd=PLAYSAND_DIR, capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout.strip())
        if "error" in data:
            return None
        return {"url": data["url"], "id": data["id"]}
    except Exception:
        return None


def upload_all_images(layout: list[dict]) -> int:
    """Walk layout, upload external images, replace URLs with local ones.
    Returns count of uploaded images."""
    count = 0

    def walk(elements: list[dict]):
        nonlocal count
        for el in elements:
            settings = el.get("settings", {})

            # Image widget
            img = settings.get("image")
            if isinstance(img, dict) and img.get("url", "").startswith("http"):
                url = img["url"]
                if "localhost" not in url:
                    alt = settings.get("alt", "")
                    result = upload_image(url, alt or "image")
                    if result:
                        img["url"] = result["url"]
                        img["id"] = result["id"]
                        count += 1

            # Background image on container
            bg_img = settings.get("background_image")
            if isinstance(bg_img, dict) and bg_img.get("url", "").startswith("http"):
                url = bg_img["url"]
                if "localhost" not in url:
                    result = upload_image(url, "background")
                    if result:
                        bg_img["url"] = result["url"]
                        bg_img["id"] = result["id"]
                        count += 1

            # Recurse into children
            walk(el.get("elements", []))

    walk(layout)
    return count
