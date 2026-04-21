"""CLI entry point: python3 -m html2elementor input.html -o layout.json"""
from __future__ import annotations
import argparse
import sys
import json
import os
from . import convert


def main():
    ap = argparse.ArgumentParser(
        prog="html2elementor",
        description="Convert HTML+CSS to Elementor JSON template with global kit.",
    )
    ap.add_argument("input", nargs="?", help="HTML file path (or - for stdin)")
    ap.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    ap.add_argument("--indent", type=int, default=2, help="JSON indent (default: 2)")
    ap.add_argument("--url", help="Fetch URL via Playwright instead of reading a file")
    ap.add_argument("--no-kit", action="store_true", help="Skip kit.json generation")
    ap.add_argument("--upload", action="store_true", help="Upload external images to WP media library via Playsand")
    ap.add_argument("--css", action="append", metavar="FILE",
                    help="Extra CSS file(s) to include (may be repeated). Useful when the HTML links external stylesheets that can't be auto-resolved.")
    args = ap.parse_args()

    extra_css: list[str] | None = None
    if args.css:
        extra_css = []
        for css_file in args.css:
            with open(css_file) as f:
                extra_css.append(f.read())

    if args.url:
        try:
            from ._playwright import fetch_and_convert
            result = fetch_and_convert(args.url)
        except ImportError:
            print("Error: --url requires playwright. Install: pip install playwright && playwright install chromium", file=sys.stderr)
            sys.exit(1)
    elif args.input and args.input != "-":
        with open(args.input) as f:
            html = f.read()
        result = convert(html, html_path=args.input, extra_css=extra_css)
    elif not sys.stdin.isatty():
        html = sys.stdin.read()
        result = convert(html, extra_css=extra_css)
    else:
        ap.print_help()
        sys.exit(1)

    if args.upload:
        from .media import upload_all_images
        n = upload_all_images(result["layout"])
        if n:
            print(f"Uploaded {n} images to WP media library", file=sys.stderr)

    layout_json = json.dumps(result["layout"], indent=args.indent, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(layout_json)

        # Write kit alongside layout
        if not args.no_kit:
            kit_path = os.path.splitext(args.output)[0] + ".kit.json"
            with open(kit_path, "w") as f:
                json.dump(result["kit"], f, indent=args.indent, ensure_ascii=False)

        n_sections = len(result["layout"])
        n_colors = len(result["kit"].get("system_colors", [])) + len(result["kit"].get("custom_colors", []))
        print(f"Wrote {n_sections} sections to {args.output}", file=sys.stderr)
        if not args.no_kit:
            print(f"Wrote {n_colors} global colors to {kit_path}", file=sys.stderr)

        # Print mapping summary
        cm = result.get("color_map", {})
        fm = result.get("font_map", {})
        if cm:
            print(f"Color globals: {', '.join(f'{v}={k}' for k, v in list(cm.items())[:8])}", file=sys.stderr)
        if fm:
            print(f"Font globals: {', '.join(f'{v}={k}' for k, v in fm.items())}", file=sys.stderr)
    else:
        print(layout_json)


if __name__ == "__main__":
    main()
