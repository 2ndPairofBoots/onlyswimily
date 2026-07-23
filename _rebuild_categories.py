#!/usr/bin/env python3
"""Rebuild section pages with original category layouts + polish shared UI."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
MIRROR = ROOT.parent / "swimstrongdryland-members-mirror"
SECTIONS = ROOT / "sections"

def nav_html(active: str | None = None, home: bool = False) -> str:
    items = [
        ("index.html", "Home", "home"),
        ("sections/training.html", "Training", "training"),
        ("sections/nutrition.html", "Nutrition & Wellness", "nutrition"),
        ("sections/leadership.html", "Leadership & Character Development", "leadership"),
        ("sections/mental-skills.html", "Mental Skills", "mental-skills"),
        ("sections/educational-webinars.html", "Educational Webinars", "educational-webinars"),
        ("sections/coachespage.html", "Coaches Page", "coachespage"),
        ("sections/masters.html", "Masters Program", "masters"),
    ]
    links = []
    for href, label, key in items:
        out = href if home else ("../index.html" if key == "home" else f"../{href}")
        cls = ' class="is-active"' if active == key else ""
        aria = ' aria-current="page"' if active == key else ""
        links.append(f'<a href="{out}"{cls}{aria}>{html.escape(label)}</a>')
    return '<nav class="top-nav">' + "".join(links) + "</nav>"


NAV = None  # built per page
HOME_NAV = None

SEARCH_SCRIPT = """
  <script>
  (() => {
    const input = document.getElementById('q');
    const count = document.getElementById('count');
    const sections = Array.from(document.querySelectorAll('.category-block'));
    const items = Array.from(document.querySelectorAll('.resource-item'));
    const total = items.length;

    const update = () => {
      const q = input.value.trim().toLowerCase();
      let visible = 0;
      for (const li of items) {
        const show = !q || li.textContent.toLowerCase().includes(q);
        li.style.display = show ? '' : 'none';
        if (show) visible++;
      }
      for (const sec of sections) {
        const hasVisible = !!sec.querySelector('.resource-item:not([style*="display: none"])');
        sec.style.display = hasVisible ? '' : 'none';
      }
      count.textContent = `Showing ${visible} of ${total}`;
    };

    input.addEventListener('input', update);
  })();
  </script>
"""


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(title: str) -> str:
    t = strip_tags(title)
    t = re.sub(
        r"\s+(Read Article|Read Recipe|Watch Video|Watch Webinar|View|Download|Open)\s*$",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_category_name(name: str) -> str:
    n = clean_title(name)
    n = re.sub(r"[?]+", "", n).strip()
    n = re.sub(r"\s+", " ", n)
    if n.isupper() and len(n) < 48:
        n = n.title()
    return n


def slugify(name: str) -> str:
    s = name.lower()
    s = s.replace("&", " and ")
    s = s.replace("?", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def normalize_key(title: str) -> str:
    t = clean_title(title).lower()
    t = t.replace("–", "-").replace("—", "-").replace("'", "'").replace("'", "'")
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t


def extract_slug(url: str) -> str | None:
    if not url:
        return None
    path = unquote(urlparse(url).path).rstrip("/")
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    if parts[-1] in {"index.html", "index.htm"}:
        parts = parts[:-1]
    if not parts:
        return None
    return parts[-1].lower()


def parse_existing_resources(section_html: Path) -> list[tuple[str, str]]:
    """Return [(title, href)] from an existing section page."""
    text = section_html.read_text(encoding="utf-8", errors="ignore")
    items = []
    for m in re.finditer(
        r'<li class="resource-item"><a href="([^"]+)">([^<]*)</a></li>', text
    ):
        href, title = m.group(1), clean_title(m.group(2))
        items.append((title, href))
    return items


def build_lookup(resources: list[tuple[str, str]]):
    by_slug: dict[str, list[tuple[str, str]]] = {}
    by_key: dict[str, list[tuple[str, str]]] = {}
    for title, href in resources:
        slug = extract_slug(href)
        if slug:
            by_slug.setdefault(slug, []).append((title, href))
        key = normalize_key(title)
        if key:
            by_key.setdefault(key, []).append((title, href))
    return by_slug, by_key


def parse_original_categories(index_html: Path) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Parse h2 categories and their card titles/hrefs from original WP index."""
    text = index_html.read_text(encoding="utf-8", errors="ignore")
    # Split on category headings
    parts = re.split(
        r'(?i)<h2[^>]*class="[^"]*o-text--h3[^"]*"[^>]*>(.*?)</h2>',
        text,
    )
    categories: list[tuple[str, list[tuple[str, str | None]]]] = []
    # parts[0] is preamble; then (title, body, title, body, ...)
    def pick_href(chunk: str) -> str | None:
        hrefs = re.findall(r'href="([^"]+)"', chunk)
        for h in reversed(hrefs):
            low = h.lower()
            if h.startswith("#") or "javascript:" in low:
                continue
            if any(
                x in low
                for x in (
                    "/wp-content/",
                    ".pdf",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".gif",
                    "youtu",
                    "vimeo",
                    "google.com",
                    "docs.google",
                )
            ):
                continue
            return h
        return None

    for i in range(1, len(parts), 2):
        cat_name = clean_category_name(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        cards: list[tuple[str, str | None]] = []
        for hm in re.finditer(
            r'(?is)<h4[^>]*class="[^"]*text-xl[^"]*"[^>]*>(.*?)</h4>', body
        ):
            title = clean_title(hm.group(1))
            if not title:
                continue
            before = body[max(0, hm.start() - 1400) : hm.start()]
            after = body[hm.end() : hm.end() + 900]
            href = pick_href(before) or pick_href(after)
            cards.append((title, href))
        if cat_name and cards:
            categories.append((cat_name, cards))
    return categories


def match_resource(
    title: str,
    href: str | None,
    by_slug: dict,
    by_key: dict,
    used_in_cat: set[str],
    disallow_hrefs: set[str] | None = None,
) -> tuple[str, str] | None:
    disallow_hrefs = disallow_hrefs or set()

    def ok(cands: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [(t, h) for t, h in cands if h not in disallow_hrefs]

    # Prefer slug match from original href
    slug = extract_slug(href) if href else None
    candidates: list[tuple[str, str]] = []
    if slug and slug in by_slug:
        candidates = ok(by_slug[slug])
    if not candidates:
        key = normalize_key(title)
        if key in by_key:
            candidates = ok(by_key[key])
    if not candidates:
        # fuzzy: key containment, but require tighter overlap
        key = normalize_key(title)
        if len(key) >= 12:
            best = None
            best_score = 0
            for k, vals in by_key.items():
                filtered = ok(vals)
                if not filtered:
                    continue
                if key in k or k in key:
                    score = min(len(key), len(k)) / max(len(key), len(k))
                    if score > best_score and score >= 0.72:
                        best_score = score
                        best = filtered
            if best:
                candidates = best
    for title2, href2 in candidates:
        if href2 not in used_in_cat:
            return title2, href2
    if candidates:
        return candidates[0]
    return None


def rebuild_section(
    section_file: str,
    title: str,
    mirror_index: str,
    include_unmatched: bool = True,
    source_html: Path | None = None,
    extra_resources: list[tuple[str, str]] | None = None,
    active_key: str | None = None,
) -> dict:
    section_path = SECTIONS / section_file
    resources = parse_existing_resources(source_html or section_path)
    lookup_resources = list(resources)
    if extra_resources:
        lookup_resources.extend(extra_resources)
    by_slug, by_key = build_lookup(lookup_resources)

    cats = parse_original_categories(MIRROR / mirror_index)

    built: list[tuple[str, list[tuple[str, str]]]] = []
    matched_hrefs: set[str] = set()
    section_hrefs = {h for _, h in resources}
    section_root = mirror_index.split("/")[0]
    disallow = {
        h
        for h in section_hrefs
        if h.endswith(f"/mirrored/{section_root}/index.html")
        or h.endswith(f"../mirrored/{section_root}/index.html")
    }

    for cat_name, cards in cats:
        used_in_cat: set[str] = set()
        items: list[tuple[str, str]] = []
        for card_title, card_href in cards:
            m = match_resource(
                card_title, card_href, by_slug, by_key, used_in_cat, disallow
            )
            if not m:
                continue
            t, h = m
            if h in used_in_cat:
                continue
            used_in_cat.add(h)
            if h in section_hrefs:
                matched_hrefs.add(h)
            items.append((t, h))
        if items:
            built.append((cat_name, items))

    if include_unmatched:
        leftover = [(t, h) for t, h in resources if h not in matched_hrefs]
        leftover = [(t, h) for t, h in leftover if h not in disallow]
        if leftover:
            built.append(("More Resources", leftover))

    # Keep section hub accessible
    hubs = [(t, h) for t, h in resources if h in disallow]
    if hubs:
        built.append(("Section Hub", hubs))

    # placements count
    placements = sum(len(items) for _, items in built)
    page_unique = len({h for _, items in built for _, h in items})
    local_unique = len(section_hrefs)

    chips = []
    blocks = []
    for cat_name, items in built:
        cid = slugify(cat_name)
        chips.append(f'<a class="chip" href="#{cid}">{html.escape(cat_name)}</a>')
        lis = "".join(
            f'<li class="resource-item"><a href="{html.escape(h, quote=True)}">{html.escape(t)}</a></li>'
            for t, h in items
        )
        blocks.append(
            f'<section id="{cid}" class="category-block">'
            f'<div class="category-head"><h2>{html.escape(cat_name)}</h2>'
            f'<span class="metric">{len(items)} resources</span></div>'
            f'<ul class="resource-list">{lis}</ul></section>'
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="../assets/styles.css">
</head>
<body>
  <main class="wrap">
    {nav_html(active_key or section_file.replace('.html',''))}
    <header class="hero">
      <p class="eyebrow">Members library</p>
      <h1>{html.escape(title)}</h1>
      <p class="sub">Structured by the same subcategories used on the original page.</p>
      <div class="metrics"><span class="metric">{len(built)} categories</span><span class="metric">{placements} listings</span><span class="metric">{page_unique} on page</span></div>
    </header>

    <div class="toolbar toolbar-stack">
      <div class="toolbar-row">
        <input id="q" class="search" type="search" placeholder="Filter all {html.escape(title.lower())} resources..." aria-label="Filter resources">
        <span id="count" class="pill">Showing {placements} of {placements}</span>
      </div>
      <div class="chip-row">{"".join(chips)}</div>
    </div>

    {"".join(blocks)}
  </main>
{SEARCH_SCRIPT}
</body>
</html>
"""
    section_path.write_text(page, encoding="utf-8", newline="\n")
    return {
        "file": section_file,
        "categories": len(built),
        "placements": placements,
        "unique": local_unique,
        "cat_names": [c for c, _ in built],
    }


def polish_training() -> dict:
    """Keep training categories; apply shared chrome/UI markup."""
    path = SECTIONS / "training.html"
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Extract existing category blocks
    blocks = re.findall(
        r'(<section id="[^"]+" class="category-block">.*?</section>)', text, flags=re.S
    )
    chips = re.findall(r'<a class="chip" href="(#[^"]+)">([^<]+)</a>', text)
    # Recount
    cat_count = len(blocks)
    items = re.findall(r'<li class="resource-item">', text)
    placements = len(items)
    hrefs = re.findall(r'<li class="resource-item"><a href="([^"]+)">', text)
    unique = len(set(hrefs))

    chip_html = "".join(
        f'<a class="chip" href="{html.escape(h, quote=True)}">{html.escape(t)}</a>'
        for h, t in chips
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Training</title>
  <link rel="stylesheet" href="../assets/styles.css">
</head>
<body>
  <main class="wrap">
    {nav_html("training")}
    <header class="hero">
      <p class="eyebrow">Members library</p>
      <h1>Training</h1>
      <p class="sub">Structured by the same subcategories used on the original Training page.</p>
      <div class="metrics"><span class="metric">{cat_count} categories</span><span class="metric">{placements} listings</span><span class="metric">{unique} unique</span></div>
    </header>

    <div class="toolbar toolbar-stack">
      <div class="toolbar-row">
        <input id="q" class="search" type="search" placeholder="Filter all training resources..." aria-label="Filter resources">
        <span id="count" class="pill">Showing {placements} of {placements}</span>
      </div>
      <div class="chip-row">{chip_html}</div>
    </div>

    {"".join(blocks)}
  </main>
{SEARCH_SCRIPT}
</body>
</html>
"""
    path.write_text(page, encoding="utf-8", newline="\n")
    return {
        "file": "training.html",
        "categories": cat_count,
        "placements": placements,
        "unique": unique,
    }


def rebuild_simple_section(
    section_file: str,
    title: str,
    categories: list[tuple[str, list[tuple[str, str]]]],
    active_key: str | None = None,
) -> dict:
    """Build a categorized page from an explicit category map."""
    section_path = SECTIONS / section_file
    existing = {h: t for t, h in parse_existing_resources(section_path)}
    built: list[tuple[str, list[tuple[str, str]]]] = []
    for cat_name, items in categories:
        resolved = []
        for t, h in items:
            if h in existing:
                resolved.append((existing[h], h))
            else:
                # try keep as-is if file exists conceptually
                resolved.append((t, h))
        if resolved:
            built.append((cat_name, resolved))

    placements = sum(len(i) for _, i in built)
    unique = len({h for _, i in built for _, h in i})
    chips = []
    blocks = []
    for cat_name, items in built:
        cid = slugify(cat_name)
        chips.append(f'<a class="chip" href="#{cid}">{html.escape(cat_name)}</a>')
        lis = "".join(
            f'<li class="resource-item"><a href="{html.escape(h, quote=True)}">{html.escape(t)}</a></li>'
            for t, h in items
        )
        blocks.append(
            f'<section id="{cid}" class="category-block">'
            f'<div class="category-head"><h2>{html.escape(cat_name)}</h2>'
            f'<span class="metric">{len(items)} resources</span></div>'
            f'<ul class="resource-list">{lis}</ul></section>'
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="../assets/styles.css">
</head>
<body>
  <main class="wrap">
    {nav_html(active_key or section_file.replace('.html',''))}
    <header class="hero">
      <p class="eyebrow">Members library</p>
      <h1>{html.escape(title)}</h1>
      <p class="sub">Structured for faster browsing.</p>
      <div class="metrics"><span class="metric">{len(built)} categories</span><span class="metric">{placements} listings</span><span class="metric">{unique} unique</span></div>
    </header>

    <div class="toolbar toolbar-stack">
      <div class="toolbar-row">
        <input id="q" class="search" type="search" placeholder="Filter resources..." aria-label="Filter resources">
        <span id="count" class="pill">Showing {placements} of {placements}</span>
      </div>
      <div class="chip-row">{"".join(chips)}</div>
    </div>

    {"".join(blocks)}
  </main>
{SEARCH_SCRIPT}
</body>
</html>
"""
    section_path.write_text(page, encoding="utf-8", newline="\n")
    return {
        "file": section_file,
        "categories": len(built),
        "placements": placements,
        "unique": unique,
    }


def write_styles():
    css = """:root {
  --bg-0: #071018;
  --bg-1: #0b1522;
  --bg-2: #122033;
  --glass: rgba(12, 22, 36, 0.78);
  --card: rgba(14, 26, 42, 0.88);
  --line: rgba(120, 170, 200, 0.18);
  --text: #e8f1f6;
  --muted: #9db4c5;
  --accent: #3ec6c4;
  --accent-2: #7ad4ff;
  --accent-soft: rgba(62, 198, 196, 0.14);
  --shadow: 0 18px 42px rgba(0, 0, 0, 0.32);
  --radius: 16px;
  --font-display: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif;
  --font-body: "Segoe UI", system-ui, -apple-system, sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
html, body { margin: 0; }
body {
  min-height: 100vh;
  font-family: var(--font-body);
  color: var(--text);
  background:
    radial-gradient(900px 380px at 8% -8%, rgba(40, 120, 140, 0.28) 0%, transparent 55%),
    radial-gradient(800px 360px at 96% 4%, rgba(30, 90, 140, 0.22) 0%, transparent 50%),
    linear-gradient(165deg, var(--bg-1) 0%, var(--bg-0) 55%, #050c12 100%);
}
a { color: var(--accent-2); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 22px 22px 48px; }

.top-nav {
  position: sticky;
  top: 0;
  z-index: 1000;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  padding: 10px;
  margin: -22px -22px 22px;
  backdrop-filter: blur(14px);
  background: rgba(6, 12, 20, 0.82);
  border-bottom: 1px solid var(--line);
}
.top-nav a {
  color: #d7e8f2;
  font-weight: 600;
  font-size: .86rem;
  padding: .42rem .68rem;
  border-radius: 999px;
  border: 1px solid transparent;
  transition: background .15s ease, border-color .15s ease;
}
.top-nav a:hover {
  text-decoration: none;
  border-color: var(--line);
  background: var(--accent-soft);
}
.top-nav a.is-active {
  border-color: rgba(62,198,196,.45);
  background: rgba(62,198,196,.18);
  color: #edfbfd;
}

.hero {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  background:
    linear-gradient(135deg, rgba(28, 70, 90, .35), rgba(10, 20, 32, .78)),
    linear-gradient(180deg, rgba(255,255,255,.03), transparent);
  box-shadow: var(--shadow);
  border-radius: calc(var(--radius) + 4px);
  padding: 28px 26px;
  margin-bottom: 18px;
}
.hero::after {
  content: "";
  position: absolute;
  inset: auto -10% -40% 40%;
  height: 180px;
  background: radial-gradient(circle, rgba(62,198,196,.18), transparent 70%);
  pointer-events: none;
}
.eyebrow {
  margin: 0 0 8px;
  font-size: .78rem;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: 700;
}
h1 {
  margin: 0 0 8px;
  font-family: var(--font-display);
  font-size: clamp(1.7rem, 3vw, 2.55rem);
  letter-spacing: -0.02em;
  line-height: 1.15;
}
p.sub { margin: 0; color: var(--muted); font-size: 1.02rem; line-height: 1.55; max-width: 52ch; }

.metrics { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.metric {
  border: 1px solid var(--line);
  background: rgba(8, 18, 28, 0.65);
  border-radius: 999px;
  padding: 7px 12px;
  font-size: .84rem;
  color: #d2e6f0;
}

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.card {
  border: 1px solid var(--line);
  background: var(--card);
  border-radius: var(--radius);
  padding: 18px 16px;
  box-shadow: var(--shadow);
  transition: transform .16s ease, border-color .16s ease, background .16s ease;
}
.card:hover {
  transform: translateY(-2px);
  border-color: rgba(62,198,196,.4);
  background: rgba(16, 32, 48, 0.95);
}
.card h2 { margin: 0 0 8px; font-size: 1.05rem; line-height: 1.35; }
.card h2 a { color: var(--text); }
.card h2 a:hover { color: var(--accent-2); text-decoration: none; }
.card .sub { margin: 0; color: var(--muted); font-size: .92rem; }
.card .card-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.toolbar {
  margin: 0 0 16px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--glass);
  backdrop-filter: blur(10px);
}
.toolbar-stack { display: block; }
.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.search {
  flex: 1 1 280px;
  min-width: 220px;
  padding: 11px 13px;
  border-radius: 12px;
  border: 1px solid var(--line);
  color: var(--text);
  background: rgba(6, 14, 24, 0.9);
  outline: none;
  font-size: .95rem;
}
.search:focus {
  border-color: rgba(62,198,196,.65);
  box-shadow: 0 0 0 3px rgba(62,198,196,.14);
}
.pill {
  font-size: .86rem;
  color: #c5dae6;
  white-space: nowrap;
}

.chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip {
  display: inline-block;
  font-size: .8rem;
  font-weight: 650;
  color: #d9eef5;
  background: rgba(62,198,196,.1);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 11px;
  transition: background .15s ease, border-color .15s ease;
}
.chip:hover {
  text-decoration: none;
  background: rgba(62,198,196,.2);
  border-color: rgba(62,198,196,.45);
}

.category-block {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
  box-shadow: var(--shadow);
  padding: 16px;
  margin: 0 0 14px;
  scroll-margin-top: 72px;
}
.category-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(120, 170, 200, 0.12);
}
.category-head h2 {
  margin: 0;
  font-size: 1.08rem;
  line-height: 1.3;
  letter-spacing: -0.01em;
}

.resource-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 8px;
}
.resource-item {
  border: 1px solid transparent;
  border-radius: 12px;
  background: rgba(7, 16, 28, 0.72);
  transition: border-color .15s ease, background .15s ease, transform .15s ease;
}
.resource-item:hover {
  border-color: rgba(62,198,196,.35);
  background: rgba(18, 40, 54, 0.9);
  transform: translateY(-1px);
}
.resource-item a {
  display: block;
  padding: 11px 12px;
  color: #dff0f7;
  text-decoration: none;
  font-size: .94rem;
  line-height: 1.35;
}

@media (max-width: 640px) {
  .wrap { padding: 14px 12px 28px; }
  .top-nav { margin: -14px -12px 14px; padding: 8px; }
  .hero { padding: 18px 16px; }
  .category-head { align-items: flex-start; flex-direction: column; }
}
"""
    (ROOT / "assets" / "styles.css").write_text(css, encoding="utf-8", newline="\n")


def write_home(stats: dict[str, dict]):
    # stats keyed by section file stem
    order = [
        ("training", "Training", "sections/training.html"),
        ("nutrition", "Nutrition & Wellness", "sections/nutrition.html"),
        ("leadership", "Leadership & Character Development", "sections/leadership.html"),
        ("mental-skills", "Mental Skills", "sections/mental-skills.html"),
        ("educational-webinars", "Educational Webinars", "sections/educational-webinars.html"),
        ("coachespage", "Coaches Page", "sections/coachespage.html"),
        ("masters", "Masters Program", "sections/masters.html"),
    ]
    cards = []
    total_unique = 0
    total_cats = 0
    for key, label, href in order:
        s = stats[key]
        total_unique += s["unique"]
        total_cats += s["categories"]
        cat_label = "category" if s["categories"] == 1 else "categories"
        list_label = "listing" if s["placements"] == 1 else "listings"
        res_label = "resource" if s["unique"] == 1 else "resources"
        cards.append(
            f'<article class="card">'
            f'<h2><a href="{href}">{html.escape(label)}</a></h2>'
            f'<p class="sub">{s["unique"]} unique {res_label}</p>'
            f'<div class="card-meta">'
            f'<span class="metric">{s["categories"]} {cat_label}</span>'
            f'<span class="metric">{s["placements"]} {list_label}</span>'
            f"</div></article>"
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SwimStrong Members Library</title>
  <link rel="stylesheet" href="assets/styles.css">
</head>
<body>
  <main class="wrap">
    {nav_html("home", home=True)}
    <header class="hero">
      <p class="eyebrow">SwimStrong Dryland</p>
      <h1>SwimStrong Members Library</h1>
      <p class="sub">Browse the mirrored members library by section and subcategory, with fast search on every page.</p>
      <div class="metrics">
        <span class="metric">{len(order)} sections</span>
        <span class="metric">{total_cats} categories</span>
        <span class="metric">{total_unique} unique resources</span>
      </div>
    </header>
    <section class="grid">{"".join(cards)}</section>
  </main>
</body>
</html>
"""
    (ROOT / "index.html").write_text(page, encoding="utf-8", newline="\n")


def main():
    write_styles()
    flat = ROOT

    stats = {}
    stats["training"] = polish_training()
    print("training:", stats["training"])

    stats["nutrition"] = rebuild_section(
        "nutrition.html",
        "Nutrition & Wellness",
        "nutrition/index.html",
        include_unmatched=True,
        source_html=flat / "_nutrition_flat.html",
    )
    print("nutrition:", {k: stats["nutrition"][k] for k in ("categories", "placements", "unique")})
    print("  cats:", stats["nutrition"]["cat_names"])

    stats["mental-skills"] = rebuild_section(
        "mental-skills.html",
        "Mental Skills",
        "mental-skills/index.html",
        include_unmatched=True,
        source_html=flat / "_mental_flat.html",
    )
    print("mental-skills:", {k: stats["mental-skills"][k] for k in ("categories", "placements", "unique")})
    print("  cats:", stats["mental-skills"]["cat_names"])

    nutrition_resources = parse_existing_resources(flat / "_nutrition_flat.html")
    # Prefer nutrition-posts paths for masters recipe cross-links
    nutrition_extra = [
        (t, h) for t, h in nutrition_resources if "/nutrition-posts/" in h
    ]

    stats["masters"] = rebuild_section(
        "masters.html",
        "Masters Program",
        "masters/index.html",
        include_unmatched=True,
        source_html=flat / "_masters_flat.html",
        extra_resources=nutrition_extra,
    )
    print("masters:", {k: stats["masters"][k] for k in ("categories", "placements", "unique")})
    print("  cats:", stats["masters"]["cat_names"])

    # Leadership: two programs
    lead = parse_existing_resources(flat / "_leadership_flat.html")
    lead_map = []
    rising = [(t, h) for t, h in lead if "rising" in h.lower() or "rising" in t.lower()]
    senior = [(t, h) for t, h in lead if "senior" in h.lower() or "senior" in t.lower()]
    other = [(t, h) for t, h in lead if (t, h) not in rising and (t, h) not in senior]
    if senior:
        lead_map.append(("Senior Leadership & Character Development", senior))
    if rising:
        lead_map.append(("Rising Leadership & Character Development", rising))
    if other:
        lead_map.append(("Program Hub", other))
    # write using flat source by temporarily copying content into section? rebuild_simple uses current section
    (SECTIONS / "leadership.html").write_text(
        (flat / "_leadership_flat.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    stats["leadership"] = rebuild_simple_section(
        "leadership.html", "Leadership & Character Development", lead_map
    )
    print("leadership:", stats["leadership"])

    (SECTIONS / "educational-webinars.html").write_text(
        (flat / "_webinars_flat.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    webinars = parse_existing_resources(SECTIONS / "educational-webinars.html")
    stats["educational-webinars"] = rebuild_simple_section(
        "educational-webinars.html",
        "Educational Webinars",
        [("Athlete & Parent Educational Webinars", webinars)],
    )
    print("educational-webinars:", stats["educational-webinars"])

    (SECTIONS / "coachespage.html").write_text(
        (flat / "_coaches_flat.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    coaches = parse_existing_resources(SECTIONS / "coachespage.html")
    stats["coachespage"] = rebuild_simple_section(
        "coachespage.html",
        "Coaches Page",
        [("Coaches Resources", coaches)],
    )
    print("coachespage:", stats["coachespage"])

    write_home(stats)
    print("Wrote index.html and styles.css")


if __name__ == "__main__":
    main()
