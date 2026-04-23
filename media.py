"""Upload images (HTTP or relative) to WordPress media library via WP-CLI.

When `--upload` is passed, the CLI walks the emitted layout for image URLs
and routes each through the right path:
  - Absolute http(s) URLs → `download_url()` + `media_handle_sideload()`.
  - Relative paths (e.g. `assets/screens/foo.png`) → resolved against the
    input HTML file's directory, copied into the WP container, then
    sideloaded from that local path.

Returns {url, id} for use in Elementor JSON or None on failure.
"""
from __future__ import annotations
import subprocess
import json
import re
import base64
from pathlib import Path

PLAYSAND_DIR = Path(__file__).resolve().parents[1] / "playsand"

_IMG_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|svg|avif)(\?|#|$)", re.I)


def _safe_filename(path_or_url: str, title: str = "") -> str:
    """Derive a filename from the URL/path, preserving extension."""
    ext_match = _IMG_EXT_RE.search(path_or_url)
    ext = ext_match.group(1).lower() if ext_match else "jpg"
    # Prefer the last path segment as base; fall back to title
    stem = Path(path_or_url.split("?")[0].split("#")[0]).stem[:40]
    if not stem or stem == "/":
        stem = re.sub(r'[^a-zA-Z0-9 -]', '', title or 'image')[:40]
    stem = re.sub(r'[^a-zA-Z0-9_-]', '-', stem.replace(' ', '-').lower()).strip('-')
    return f"{stem}.{ext}"


def upload_local_file(local_path: Path, title: str = "") -> dict | None:
    """Upload a file already on disk into WP media. Copies into the Playsand
    container then calls media_handle_sideload on the container-side path."""
    if not local_path.exists() or not PLAYSAND_DIR.exists():
        return None
    filename = _safe_filename(str(local_path), title)
    container_path = f"/tmp/media-{filename}"
    try:
        # Copy into the WP container
        subprocess.run(
            ["docker", "compose", "cp", str(local_path), f"wp:{container_path}"],
            cwd=PLAYSAND_DIR, capture_output=True, text=True, timeout=30, check=True,
        )
    except Exception:
        return None
    php = f'''
$path = {json.dumps(container_path)};
if (!file_exists($path)) {{ echo json_encode(["error" => "missing"]); exit; }}
$file = ["name" => {json.dumps(filename)}, "tmp_name" => $path];
require_once ABSPATH . "wp-admin/includes/file.php";
require_once ABSPATH . "wp-admin/includes/media.php";
require_once ABSPATH . "wp-admin/includes/image.php";
$id = media_handle_sideload($file, 0, {json.dumps(title)});
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


def upload_http_url(url: str, title: str = "") -> dict | None:
    """Download a remote image inside WP and sideload it."""
    if not url or not url.startswith("http") or not PLAYSAND_DIR.exists():
        return None
    filename = _safe_filename(url, title)
    php = f'''
$url = {json.dumps(url)};
require_once ABSPATH . "wp-admin/includes/file.php";
require_once ABSPATH . "wp-admin/includes/media.php";
require_once ABSPATH . "wp-admin/includes/image.php";
$tmp = download_url($url, 30);
if (is_wp_error($tmp)) {{ echo json_encode(["error" => $tmp->get_error_message()]); exit; }}
$file = ["name" => {json.dumps(filename)}, "tmp_name" => $tmp];
$id = media_handle_sideload($file, 0, {json.dumps(title)});
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


def _resolve_url(src: str, html_dir: Path | None) -> tuple[str, Path | None]:
    """Classify an image URL. Returns (kind, local_path):
      kind = 'http', 'local', or 'skip'.
      local_path set only for 'local'."""
    if not src:
        return ("skip", None)
    if src.startswith(("http://", "https://")):
        # Skip already-local WP URLs (would upload into itself)
        if "localhost:8090" in src or "wp-content/uploads" in src:
            return ("skip", None)
        return ("http", None)
    if src.startswith("data:"):
        return ("skip", None)
    # Relative / root-relative path — try to resolve from HTML dir
    if html_dir:
        candidate = (html_dir / src.lstrip("/")).resolve()
        if candidate.exists() and candidate.is_file():
            return ("local", candidate)
    return ("skip", None)


def upload_all_images(layout: list[dict], html_path: str | None = None) -> int:
    """Walk layout, upload referenced images to WP media, rewrite URLs to
    the attachment's local URL + ID. `html_path` anchors relative paths."""
    html_dir = Path(html_path).parent.resolve() if html_path else None
    cache: dict[str, dict] = {}  # original URL → {url, id}
    count = 0

    def resolve(src: str, title: str) -> dict | None:
        nonlocal count
        if src in cache:
            return cache[src]
        kind, local = _resolve_url(src, html_dir)
        if kind == "skip":
            return None
        if kind == "http":
            result = upload_http_url(src, title)
        else:
            result = upload_local_file(local, title)
        if result:
            cache[src] = result
            count += 1
        return result

    def walk(elements: list[dict]):
        for el in elements:
            settings = el.get("settings", {})
            img = settings.get("image")
            if isinstance(img, dict) and img.get("url"):
                title = settings.get("alt") or "image"
                result = resolve(img["url"], title)
                if result:
                    img["url"] = result["url"]
                    img["id"] = result["id"]
            bg_img = settings.get("background_image")
            if isinstance(bg_img, dict) and bg_img.get("url"):
                result = resolve(bg_img["url"], "background")
                if result:
                    bg_img["url"] = result["url"]
                    bg_img["id"] = result["id"]
            walk(el.get("elements", []))

    walk(layout)
    return count
