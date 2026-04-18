# Contributing

Small project, simple loop: **find what breaks, fix it, add a test that proves it.**

## Dev setup

```bash
git clone https://github.com/dudaster/html2elementor.git
cd html2elementor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## WordPress sandbox (for visual testing)

Any WordPress install with Elementor 3.x works. Minimal Docker setup:

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

After `docker compose up -d`:

```bash
wp core install --url=http://localhost:8090 --title=Sandbox --admin_user=admin --admin_password=admin --admin_email=a@b.co --allow-root
wp plugin install elementor --activate --allow-root
# Disable lazy-load so imported bg images render without scrolling
wp eval 'update_option("elementor_experiment-e_lazyload", "inactive");' --allow-root
```

## The loop

1. **Pick or write a failing test.** Add a new `.html` file under `tests/` — or grab an existing one that imports wrong.
2. **Convert:** `python3 -m html2elementor tests/your.html -o /tmp/out.json`
3. **Verify:** `python3 -m html2elementor.verify tests/your.html /tmp/out.json`. Zero issues ≠ pixel-perfect, but it means the cascade resolved correctly.
4. **Import + screenshot.** Copy `/tmp/out.json` into WordPress, assign to a page, `wp elementor flush_css`, load the page. Compare visually at the same viewport.
5. **Fix.** Most issues live in:
   - `widgets.py` — DOM → widget spec mapping
   - `resolver.py` — CSS cascade edge cases
   - `containers.py` — section / inner container flex settings
   - `styles.py` — property parsing helpers
   - `globals.py` — what becomes a site-wide global
6. **Leave a breadcrumb.** One-line comment in the code explaining *why* the weird thing exists. Elementor has many quirks (`--container-widget-width`, lazy-load, system-color sharing) — future-you will thank you.
7. **PR.** Include a before/after screenshot when fixing visual drift.

## Testing all pages at once

```bash
for t in tests/*.html; do
  name=$(basename "$t" .html)
  python3 -m html2elementor "$t" -o "/tmp/$name.json" 2>/dev/null
  printf "%-12s " "$name"
  python3 -m html2elementor.verify "$t" "/tmp/$name.json" 2>&1 | grep -E "Widgets|Issues" | tr '\n' ' '
  echo
done
```

## Style

- Python 3.10+ features welcome (`match`, `|` unions).
- No linter enforced — match what's around.
- Small functions, descriptive names. If a helper is used once, inline it.
- No `try/except: pass`. Handle the exception or let it bubble.

## Commit messages

- Imperative, specific, under 70 chars: `Preserve inline span colors in heading titles`
- Body explains *why*, not just *what*.
- Reference the test case: `Fixes missing bg on .cta-inner (see tests/analytics.html section 8)`.

## Out of scope

- Browser runtime dependencies (Playwright, Puppeteer). Local + fast + no Node is the whole point.
- API calls to third parties.
- Heavy deps. `beautifulsoup4` + `tinycss2` + `cssselect2` should cover nearly everything.
- Features that only matter for one client's theme.

## Questions / bugs

Open an issue with:
- HTML input (or a minimal reproducer)
- The `output.json` you got
- What you expected vs what rendered
- Screenshot if it's visual
