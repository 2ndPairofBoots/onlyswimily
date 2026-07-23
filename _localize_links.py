#!/usr/bin/env python3
"""Localize mirrored pages so in-content navigation stays on GitHub Pages."""

from __future__ import annotations

import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

SITE = Path(__file__).resolve().parent
MIRROR = SITE / "mirrored"
MEMBERS = SITE.parent / "swimstrongdryland-members-mirror"
DOWNLOAD_LOCAL = SITE.parent / "swimstrongdryland-download-local"
ASSETS_ROOT = SITE / "wp-content"

SECTION_MAP = {
    "training": "../../../sections/training.html",
    "nutrition": "../../../sections/nutrition.html",
    "leadership": "../../../sections/leadership.html",
    "mental-skills": "../../../sections/mental-skills.html",
    "educational-webinars": "../../../sections/educational-webinars.html",
    "coachespage": "../../../sections/coachespage.html",
    "masters": "../../../sections/masters.html",
}

# Depth from mirrored/{type}/{slug}/index.html to site root is ../../../
# From mirrored/{type}/index.html depth is ../../
CONTENT_TYPES = {
    "training-video",
    "nutrition-posts",
    "mental-skills-post",
    "masters-post",
    "leadership-page-2-0",
    "training",
    "nutrition",
    "mental-skills",
    "masters",
    "leadership",
    "educational-webinars",
    "coachespage",
}

SSDL = re.compile(
    r"""(?P<attr>href|src)=(["'])(?P<url>https?://(?:www\.)?swimstrongdryland\.com(?P<path>/[^"']*))\2""",
    re.I,
)
ROOT_WP = re.compile(
    r"""(?P<attr>href|src)=(["'])(?P<path>/wp-content/[^"']+)\2""",
    re.I,
)
EMBED_IFRAME = re.compile(
    r"""<iframe(?P<pre>[^>]*?)\ssrc=(["'])https?://(?:www\.)?swimstrongdryland\.com/(?P<ctype>[^/"']+)/(?P<slug>[^/"']+)/embed/[^"']*\2(?P<post>[^>]*)>(?P<inner>.*?)</iframe>""",
    re.I | re.S,
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def build_local_index() -> dict[tuple[str, str], Path]:
    idx: dict[tuple[str, str], Path] = {}
    for d in MIRROR.iterdir():
        if not d.is_dir():
            continue
        if (d / "index.html").exists():
            idx[(d.name, "")] = d / "index.html"
        for child in d.iterdir():
            if child.is_dir() and (child / "index.html").exists():
                idx[(d.name, child.name)] = child / "index.html"
    return idx


def depth_prefix(html_path: Path) -> str:
    """Relative prefix from this HTML file up to site root."""
    rel = html_path.relative_to(SITE)
    # number of parents to climb
    ups = len(rel.parts) - 1
    return "../" * ups


def local_content_href(ctype: str, slug: str, html_path: Path, local: dict) -> str | None:
    key = (ctype, slug)
    if key not in local:
        # hub page
        if slug == "" and (ctype, "") in local:
            pass
        elif (ctype, "") in local and not slug:
            pass
        else:
            return None
    target = local.get((ctype, slug)) or local.get((ctype, ""))
    if not target:
        return None
    # compute relative from html_path parent to target
    start = html_path.parent
    try:
        rel = Path(target).relative_to(SITE)
        # manual relative
        start_parts = start.relative_to(SITE).parts
        target_parts = rel.parts
        # climb up from start
        ups = len(start_parts)
        return ("../" * ups) + "/".join(target_parts)
    except Exception:
        return None


def parse_content_path(path: str) -> tuple[str, str] | None:
    path = unquote(path.split("?")[0].split("#")[0])
    if not path.startswith("/"):
        return None
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return None
    ctype = parts[0]
    if ctype not in CONTENT_TYPES:
        return None
    if len(parts) == 1:
        return ctype, ""
    slug = parts[1]
    if slug in {"embed", "feed"}:
        return None
    return ctype, slug


def copy_wp_content() -> int:
    copied = 0
    sources = []
    for root in (MEMBERS, DOWNLOAD_LOCAL):
        src = root / "wp-content"
        if src.exists():
            sources.append(src)
    ASSETS_ROOT.mkdir(parents=True, exist_ok=True)
    for src in sources:
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(src)
            dest = ASSETS_ROOT / rel
            if dest.exists() and dest.stat().st_size == f.stat().st_size:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            copied += 1
    return copied


def collect_needed_uploads(local_htmls: list[Path]) -> set[str]:
    needed: set[str] = set()
    for html in local_htmls:
        text = html.read_text(encoding="utf-8", errors="ignore")
        for m in SSDL.finditer(text):
            path = m.group("path")
            if "/wp-content/uploads/" in path:
                needed.add(path.split("?")[0].split("#")[0])
        for m in ROOT_WP.finditer(text):
            path = m.group("path")
            if "/wp-content/uploads/" in path:
                needed.add(path.split("?")[0].split("#")[0])
        # also relative ../wp-content
        for m in re.finditer(r"""(?:href|src)=(["'])([^"']*wp-content/uploads/[^"']+)\1""", text):
            p = m.group(2)
            if p.startswith("http"):
                continue
            # normalize
            while p.startswith("../"):
                p = p[3:]
            if not p.startswith("/"):
                p = "/" + p
            if p.startswith("/wp-content/uploads/"):
                needed.add(p.split("?")[0].split("#")[0])
    return needed


def download_missing(paths: set[str]) -> tuple[int, int, list[str]]:
    ok = 0
    fail = 0
    failed: list[str] = []
    for path in sorted(paths):
        # path like /wp-content/uploads/...
        rel = path.lstrip("/")
        if not rel.startswith("wp-content/"):
            continue
        dest = SITE / rel
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = "https://swimstrongdryland.com" + path
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
            if len(data) < 100:
                # likely login wall html
                fail += 1
                failed.append(path + " (tiny)")
                continue
            # reject HTML login pages saved as pdf
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype and not path.endswith(".html"):
                fail += 1
                failed.append(path + " (html)")
                continue
            dest.write_bytes(data)
            ok += 1
            print(f"  downloaded {path} ({len(data)} bytes)")
            time.sleep(0.15)
        except Exception as e:
            fail += 1
            failed.append(f"{path} ({e})")
    return ok, fail, failed


def rewrite_page(html_path: Path, local: dict) -> tuple[int, int]:
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    original = text
    changes = 0
    unresolved = 0
    prefix = depth_prefix(html_path)

    def replace_ssdl(m: re.Match) -> str:
        nonlocal changes, unresolved
        attr = m.group("attr")
        quote = m.group(2)
        path = m.group("path")
        pure = path.split("?")[0].split("#")[0]
        frag = ""
        if "#" in path:
            frag = "#" + path.split("#", 1)[1].split("?")[0]

        # uploads / theme assets
        if pure.startswith("/wp-content/"):
            changes += 1
            return f"{attr}={quote}{prefix}{pure.lstrip('/')}{frag}{quote}"

        # section hubs
        parts = [p for p in pure.strip("/").split("/") if p]
        if len(parts) == 1 and parts[0] in SECTION_MAP:
            # SECTION_MAP assumes depth 3; recompute
            changes += 1
            return f"{attr}={quote}{prefix}sections/{parts[0] if parts[0] != 'coachespage' else 'coachespage'}.html{frag}{quote}".replace(
                "sections/coachespage.html", "sections/coachespage.html"
            )

        # fix section filenames
        if len(parts) == 1:
            section_file = {
                "training": "training.html",
                "nutrition": "nutrition.html",
                "leadership": "leadership.html",
                "mental-skills": "mental-skills.html",
                "educational-webinars": "educational-webinars.html",
                "coachespage": "coachespage.html",
                "masters": "masters.html",
            }.get(parts[0])
            if section_file:
                changes += 1
                return f"{attr}={quote}{prefix}sections/{section_file}{frag}{quote}"

        parsed = parse_content_path(pure)
        if parsed:
            ctype, slug = parsed
            # strip /embed/
            href = local_content_href(ctype, slug, html_path, local)
            if href:
                changes += 1
                return f"{attr}={quote}{href}{frag}{quote}"
            unresolved += 1
            # keep users on site: go to matching section if possible
            section_file = {
                "training-video": "training.html",
                "training": "training.html",
                "nutrition-posts": "nutrition.html",
                "nutrition": "nutrition.html",
                "mental-skills-post": "mental-skills.html",
                "mental-skills": "mental-skills.html",
                "masters-post": "masters.html",
                "masters": "masters.html",
                "leadership-page-2-0": "leadership.html",
                "leadership": "leadership.html",
                "educational-webinars": "educational-webinars.html",
                "coachespage": "coachespage.html",
            }.get(ctype)
            if section_file:
                changes += 1
                return f"{attr}={quote}{prefix}sections/{section_file}{frag}{quote}"

        # non-mirrored marketing pages -> home (stay on GH Pages)
        if attr.lower() == "href":
            changes += 1
            return f"{attr}={quote}{prefix}index.html{frag}{quote}"
        # src to remote scripts/styles - leave or point home? leave CSS from original for now
        # Actually for link stylesheets in head, leaving them loads from SSDL which is ok for styling
        # but user wants to stay on site - stylesheets don't navigate. Leave src/link styles.
        return m.group(0)

    text = SSDL.sub(replace_ssdl, text)

    def replace_root_wp(m: re.Match) -> str:
        nonlocal changes
        attr = m.group("attr")
        quote = m.group(2)
        path = m.group("path").split("?")[0].split("#")[0]
        changes += 1
        return f"{attr}={quote}{prefix}{path.lstrip('/')}{quote}"

    text = ROOT_WP.sub(replace_root_wp, text)

    # Replace embed iframes with local links
    def replace_embed(m: re.Match) -> str:
        nonlocal changes
        ctype = m.group("ctype")
        slug = m.group("slug")
        href = local_content_href(ctype, slug, html_path, local)
        if not href:
            section = {
                "training-video": "training.html",
                "mental-skills-post": "mental-skills.html",
                "nutrition-posts": "nutrition.html",
                "masters-post": "masters.html",
            }.get(ctype, "training.html")
            href = f"{prefix}sections/{section}"
        changes += 1
        title = slug.replace("-", " ").title()
        return (
            f'<div class="onlyswimily-embed-fallback" style="border:1px solid #cfe;border-radius:12px;padding:16px;margin:12px 0;background:#f7fbfd">'
            f'<p style="margin:0 0 8px;font-weight:600">Open resource on this site</p>'
            f'<a href="{href}">{title}</a></div>'
        )

    text = EMBED_IFRAME.sub(replace_embed, text)

    # Strengthen cleanup CSS: hide entire original header
    if "onlyswimily-cleanup-style" in text:
        new_css = (
            ".onlyswimily-nav{position:sticky;top:0;z-index:2147483647;display:flex;gap:8px;flex-wrap:wrap;"
            "padding:9px 12px;background:rgba(8,12,24,.92);backdrop-filter:blur(10px);"
            "border-bottom:1px solid rgba(143,169,226,.24);font-family:Segoe UI,Arial,sans-serif}"
            ".onlyswimily-nav a{color:#dce7ff;text-decoration:none;font-weight:600;font-size:13px;"
            "padding:6px 10px;border-radius:999px}.onlyswimily-nav a:hover{background:rgba(111,182,255,.14)}"
            "header.site-header,#footer,footer,.footer,.site-footer,.ast-footer-overlay,.copyright,"
            ".skip-link,.nav-sm,.nav-lg__item,.xl\\:px-5{display:none !important}"
            "body{padding-top:0 !important}.pt-16,.xl\\:pt-32{padding-top:0 !important}"
        )
        text2 = re.sub(
            r'<style id="onlyswimily-cleanup-style">.*?</style>',
            f'<style id="onlyswimily-cleanup-style">{new_css}</style>',
            text,
            count=1,
            flags=re.S,
        )
        if text2 != text:
            text = text2
            changes += 1

    if text != original:
        html_path.write_text(text, encoding="utf-8", newline="\n")
    return changes, unresolved


def main():
    print("Indexing local pages...")
    local = build_local_index()
    print(f"  {len(local)} local pages")

    print("Copying wp-content from mirrors...")
    copied = copy_wp_content()
    print(f"  copied {copied} files")

    htmls = list(MIRROR.rglob("*.html"))
    print(f"Collecting upload refs from {len(htmls)} pages...")
    needed = collect_needed_uploads(htmls)
    missing = []
    for path in sorted(needed):
        dest = SITE / path.lstrip("/")
        if not dest.exists():
            missing.append(path)
    print(f"  needed uploads: {len(needed)}, missing locally: {len(missing)}")

    if missing:
        print("Downloading missing uploads...")
        ok, fail, failed = download_missing(set(missing))
        print(f"  downloaded={ok} failed={fail}")
        if failed[:20]:
            for f in failed[:20]:
                print("   fail:", f)

    print("Rewriting mirrored HTML...")
    total_changes = 0
    total_unresolved = 0
    touched = 0
    for i, html in enumerate(htmls, 1):
        ch, un = rewrite_page(html, local)
        total_changes += ch
        total_unresolved += un
        if ch:
            touched += 1
        if i % 100 == 0:
            print(f"  {i}/{len(htmls)}...")

    print(f"Done. touched={touched} changes={total_changes} unresolved_content={total_unresolved}")

    # verify remaining absolute SSDL hrefs in <main>
    remaining_main = 0
    remaining_any_href = 0
    for html in htmls:
        text = html.read_text(encoding="utf-8", errors="ignore")
        main_m = re.search(r"<main[\s>].*</main>", text, re.I | re.S)
        main = main_m.group(0) if main_m else ""
        if re.search(r'href=["\']https?://(?:www\.)?swimstrongdryland\.com', main, re.I):
            remaining_main += 1
        if re.search(r'href=["\']https?://(?:www\.)?swimstrongdryland\.com', text, re.I):
            remaining_any_href += 1
    print(f"Pages still having SSDL href in <main>: {remaining_main}")
    print(f"Pages still having any SSDL href: {remaining_any_href}")


if __name__ == "__main__":
    main()
