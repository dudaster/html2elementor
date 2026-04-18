# Contributing to html2elementor

Thanks for wanting to help. This is a small project with a simple loop: **look at what breaks, fix it, add a test that proves it.**

## Dev setup

```bash
git clone https://github.com/dudaster/html2elementor.git
cd html2elementor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## WordPress sandbox (for import testing)

The repo doesn't ship a sandbox; use any WordPress install with Elementor 3.x. A local Docker setup works well:

```yaml
# docker-compose.yml
services:
  wp:
    image: wordpress:latest
    ports: ["8090:80"]
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wp
      WORDPRESS_DB_PASSWORD: wp
      WORDPRESS_DB_NAME: wp
  db:
    image: mariadb:lts
    environment:
      MARIADB_DATABASE: wp
      MARIADB_USER: wp
      MARIADB_PASSWORD: wp
      MARIADB_ROOT_PASSWORD: root
```

Then `wp plugin install elementor --activate` via WP-CLI. Disable the lazy-load experiment so background images render in screenshots:

```bash
wp eval 'update_option("elementor_experiment-e_lazyload", "inactive");' --allow-root
```

## The dev loop

1. **Pick or write a failing test.** Either reach for an existing file in `tests/` that looks wrong after import, or add a new `.html` file there.

2. **Convert it:**
   ```bash
   python3 -m html2elementor tests/your.html -o /tmp/out.json
   ```

3. **Verify it:**
   ```bash
   python3 -m html2elementor.verify tests/your.html /tmp/out.json
   ```
   Zero issues means the resolved CSS matches what was emitted. It does NOT mean the Elementor render is visually correct — that's step 4.

4. **Import + screenshot.** Copy `/tmp/out.json` into WordPress, assign to a page, flush Elementor's CSS cache, load the page. Compare to the source HTML at the same viewport.

5. **Fix.** Most issues live in:
   - `widgets.py` — how DOM nodes map to widget specs
   - `resolver.py` — CSS cascade edge cases
   - `containers.py` — section → flex container settings
   - `styles.py` — property parsing helpers
   - `globals.py` — what becomes a site-wide global

6. **Add a memory of the fix.** One-line comment in the code explaining *why* the weird thing exists. Elementor has many quirks (lazy-load, `--container-widget-width`, system color sharing) — future-you will thank present-you.

7. **Send the PR.** Include a before/after screenshot if it's a visual fix.

## Testing all pages

```bash
for t in tests/*.html; do
  name=$(basename "$t" .html)
  python3 -m html2elementor "$t" -o "tests/$name-output.json" 2>/dev/null
  printf "%-12s " "$name"
  python3 -m html2elementor.verify "$t" "tests/$name-output.json" 2>&1 | grep -E "Widgets|Issues" | tr '\n' ' '
  echo
done
```

## Code style

- Python 3.10+ features are fine (`match`, `|` union types, etc.).
- No linting enforced — just match what's around.
- Small functions, descriptive names, no magic imports. If you're adding a helper used once, inline it.
- Avoid `try/except: pass`. Either handle the exception or let it bubble.

## Commit messages

- Imperative, specific, under 70 chars: `Preserve inline span colors in heading titles`
- Body explains *why* the change exists, not just *what* changed.
- Reference the test case that motivates the change: `Fixes missing bg on .cta-inner (see tests/analytics.html section 8)`.

## What NOT to add

- Browser runtime dependencies (Playwright, Puppeteer). The point is local + fast + no Node.
- API calls to any third party.
- Heavy dependencies. If `beautifulsoup4 + tinycss2 + cssselect2` can't do it, look twice before pulling in another package.
- Features that only matter for a single client's theme.

## Questions

Open an issue with:
- The HTML input (or a minimal reproducer)
- The `output.json` you got
- What you expected vs what rendered
- Screenshot if it's a visual problem
