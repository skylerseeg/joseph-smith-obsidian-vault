#!/usr/bin/env python3
"""
Phase 1 — Slug Discovery

Browses every series index page on josephsmithpapers.org and collects
the URL slug for every document. Saves one JSON file per series to
data/slugs/{series}.json.

Usage:
    python 01_discover_slugs.py
    python 01_discover_slugs.py --series documents journals
    python 01_discover_slugs.py --reset          # delete empty stubs and re-run
    python 01_discover_slugs.py --debug          # print raw HTML + all links found
"""

import argparse
import asyncio
import json
import logging
import random
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from config import (
    BASE_URL,
    SERIES_BROWSE_URLS,
    SLUGS_DIR,
    PAGE_LOAD_TIMEOUT,
    HEADLESS,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    SCRAPE_LOG,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(SCRAPE_LOG),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)
console = Console()

# Every selector pattern we'll try for finding document links
LINK_SELECTORS = [
    "a[href*='/paper-summary/']",
    "a[href*='paper-summary']",
    "a[href*='/papers/']",
    ".document-list a",
    ".paper-list a",
    ".results a",
    ".search-results a",
    "ul.papers li a",
    "table a[href]",
    ".item-title a",
    ".document-title a",
    "a.paper-link",
    "a.document-link",
    "li a[href]",          # broad fallback
]

# Regex to pull a slug out of any JSPP-looking href
SLUG_PATTERNS = [
    re.compile(r"/paper-summary/([^/?#]+)"),
    re.compile(r"/papers/([^/?#]+)"),
    re.compile(r"/document/([^/?#]+)"),
]


def extract_slug(href: str) -> str | None:
    for pat in SLUG_PATTERNS:
        m = pat.search(href)
        if m:
            return m.group(1)
    return None


async def get_all_hrefs(page: Page) -> list[str]:
    """Return every href on the current page."""
    return await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
    )


async def get_page_slugs(page: Page, url: str, debug: bool = False) -> list[str]:
    try:
        await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
    except PWTimeout:
        log.warning(f"Timeout on {url}, retrying with domcontentloaded…")
        await asyncio.sleep(5)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        except PWTimeout:
            log.error(f"Second timeout on {url}, skipping page.")
            return []

    # Extra wait for JS-heavy Angular apps
    await asyncio.sleep(3)

    if debug:
        html = await page.content()
        console.print(f"\n[dim]--- Raw HTML snippet (first 3000 chars) ---[/]")
        console.print(html[:3000])

    # Try each selector in order; use the first that returns links
    slugs: set[str] = set()

    for selector in LINK_SELECTORS:
        try:
            links = await page.eval_on_selector_all(
                selector,
                "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
            )
        except Exception:
            continue

        if debug and links:
            console.print(f"\n[dim]Selector '{selector}' → {len(links)} links:[/]")
            for l in links[:10]:
                console.print(f"  {l}")

        for href in links:
            slug = extract_slug(href)
            if slug:
                slugs.add(slug)

        if slugs:
            break  # Found results with this selector

    # Last resort: scan ALL hrefs on the page
    if not slugs:
        all_hrefs = await get_all_hrefs(page)
        if debug:
            console.print(f"\n[dim]All hrefs on page ({len(all_hrefs)} total):[/]")
            for h in all_hrefs[:40]:
                console.print(f"  {h}")

        for href in all_hrefs:
            slug = extract_slug(href)
            if slug:
                slugs.add(slug)

        if not slugs:
            log.warning(f"No document slugs found on {url}")
            if not debug:
                log.warning("Re-run with --debug to see the raw page HTML and all links.")

    return sorted(slugs)


async def discover_series(page: Page, series: str, browse_url: str, debug: bool = False) -> list[str]:
    all_slugs: set[str] = set()
    page_num = 1

    console.print(f"[bold cyan]Discovering:[/] {series} — {browse_url}")

    while True:
        url = browse_url if page_num == 1 else f"{browse_url}?page={page_num}"

        log.info(f"  {series} page {page_num}: {url}")
        slugs = await get_page_slugs(page, url, debug=debug)

        if not slugs:
            log.info(f"  No slugs on page {page_num} — series complete")
            break

        new = set(slugs) - all_slugs
        if not new:
            log.info(f"  No new slugs on page {page_num} — done")
            break

        all_slugs.update(new)
        console.print(f"  Page {page_num}: +{len(new)} slugs (total {len(all_slugs)})")

        page_num += 1
        await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    return sorted(all_slugs)


async def main(
    series_filter: list[str] | None = None,
    reset: bool = False,
    debug: bool = False,
) -> None:
    targets = {
        k: v for k, v in SERIES_BROWSE_URLS.items()
        if series_filter is None or k in series_filter
    }

    # --reset: delete empty stub files so they get re-scraped
    if reset:
        for series in targets:
            p = SLUGS_DIR / f"{series}.json"
            if p.exists():
                data = json.loads(p.read_text())
                if len(data) == 0:
                    p.unlink()
                    console.print(f"[yellow]Deleted empty stub:[/] {p.name}")
        master = SLUGS_DIR / "master.json"
        if master.exists() and json.loads(master.read_text()) == []:
            master.unlink()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False if debug else HEADLESS)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        grand_total = 0
        for series, browse_url in targets.items():
            out_path = SLUGS_DIR / f"{series}.json"

            if out_path.exists():
                existing = json.loads(out_path.read_text())
                if existing:
                    console.print(
                        f"[yellow]Skip[/] {series} — {len(existing)} slugs already saved "
                        f"(use --reset to redo)"
                    )
                    grand_total += len(existing)
                    continue
                else:
                    # Empty stub — delete and re-run
                    out_path.unlink()
                    console.print(f"[yellow]Removed empty stub for {series}, re-discovering…[/]")

            slugs = await discover_series(page, series, browse_url, debug=debug)

            out_path.write_text(json.dumps(slugs, indent=2))
            console.print(f"[green]Saved[/] {len(slugs)} slugs → {out_path.name}")
            grand_total += len(slugs)

            if not debug:
                await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

        await browser.close()

    console.print(f"\n[bold green]Done.[/] Total slugs discovered: {grand_total}")

    # Rebuild master list
    master: list[dict] = []
    for series in SERIES_BROWSE_URLS:
        p = SLUGS_DIR / f"{series}.json"
        if p.exists():
            for slug in json.loads(p.read_text()):
                master.append({"series": series, "slug": slug})

    master_path = SLUGS_DIR / "master.json"
    master_path.write_text(json.dumps(master, indent=2))
    console.print(f"Master list → {master_path.name} ({len(master)} entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover JSPP document slugs")
    parser.add_argument("--series", nargs="+", choices=list(SERIES_BROWSE_URLS.keys()))
    parser.add_argument("--reset", action="store_true", help="Delete empty stub files and re-run")
    parser.add_argument("--debug", action="store_true", help="Print raw HTML and all links; opens visible browser")
    args = parser.parse_args()
    asyncio.run(main(args.series, reset=args.reset, debug=args.debug))
