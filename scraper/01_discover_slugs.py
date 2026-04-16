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
    python 01_discover_slugs.py --debug          # dump all links found on page
    python 01_discover_slugs.py --test           # test connectivity only (no scrape)
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

from config import (
    BASE_URL,
    SERIES_BROWSE_URLS,
    SLUGS_DIR,
    PAGE_LOAD_TIMEOUT,
    JS_SETTLE_WAIT,
    HEADLESS,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    SCRAPE_LOG,
    PRIORITY_SLUGS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.FileHandler(SCRAPE_LOG), logging.StreamHandler()],
)
log = logging.getLogger(__name__)
console = Console()

SLUG_RE = re.compile(r"/paper-summary/([^/?#\s]+)")


async def load_page(page: Page, url: str) -> bool:
    """
    Load a URL, tolerating Angular's never-ending network activity.
    Returns True on success, False on total failure.
    """
    # Try 1: wait for 'load' event (DOM + resources, ignores XHR)
    try:
        await page.goto(url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(JS_SETTLE_WAIT)  # let Angular bootstrap
        return True
    except PWTimeout:
        log.warning(f"'load' timeout on {url}, trying domcontentloaded…")

    # Try 2: bare DOM load
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(JS_SETTLE_WAIT + 5)
        return True
    except PWTimeout:
        log.error(f"Total timeout on {url}")
        return False


async def extract_slugs_from_page(page: Page, debug: bool = False) -> list[str]:
    """Pull every /paper-summary/{slug} href from the current page."""
    html = await page.content()

    if debug:
        console.print(f"\n[dim]Page title:[/] {await page.title()}")
        console.print(f"[dim]HTML length:[/] {len(html)} chars")
        console.print(f"\n[dim]--- First 4000 chars of HTML ---[/]\n{html[:4000]}")

    # Mine slugs from raw HTML (catches JS-rendered links too)
    slugs = set(SLUG_RE.findall(html))

    if debug:
        console.print(f"\n[dim]Slugs found in raw HTML:[/] {len(slugs)}")
        for s in sorted(slugs)[:20]:
            console.print(f"  {s}")

    return sorted(slugs)


async def test_connectivity(page: Page) -> None:
    """Quick check: can we reach the site at all?"""
    console.print("\n[bold]Connectivity test[/]")
    test_urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/paper-summary/journal-1832-1834/1",
        f"{BASE_URL}/the-papers/documents",
    ]
    for url in test_urls:
        ok = await load_page(page, url)
        title = await page.title() if ok else "—"
        html_len = len(await page.content()) if ok else 0
        status = "[green]OK[/]" if ok else "[red]FAIL[/]"
        console.print(f"  {status}  {url}")
        console.print(f"         title={title!r}  html={html_len} chars")

    # Also dump all hrefs so we can see what links exist
    hrefs = await page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
    )
    console.print(f"\n[dim]All hrefs on last page ({len(hrefs)} total):[/]")
    for h in hrefs[:50]:
        console.print(f"  {h}")


async def discover_series(page: Page, series: str, browse_url: str, debug: bool = False) -> list[str]:
    all_slugs: set[str] = set()
    page_num = 1

    console.print(f"\n[bold cyan]Discovering:[/] {series}")

    while True:
        url = browse_url if page_num == 1 else f"{browse_url}?page={page_num}"
        log.info(f"  {series} p{page_num}: {url}")

        ok = await load_page(page, url)
        if not ok:
            console.print(f"  [red]Failed to load page {page_num}, stopping.[/]")
            break

        slugs = await extract_slugs_from_page(page, debug=debug)
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
    test: bool = False,
) -> None:
    targets = {
        k: v for k, v in SERIES_BROWSE_URLS.items()
        if series_filter is None or k in series_filter
    }

    if reset:
        for series in targets:
            p = SLUGS_DIR / f"{series}.json"
            if p.exists():
                data = json.loads(p.read_text())
                if len(data) == 0:
                    p.unlink()
                    console.print(f"[yellow]Deleted empty stub:[/] {p.name}")

    async with async_playwright() as pw:
        # Always launch visible (non-headless) when debugging
        headless = False if (debug or test) else HEADLESS
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        if test:
            await test_connectivity(page)
            await browser.close()
            return

        grand_total = 0
        for series, browse_url in targets.items():
            out_path = SLUGS_DIR / f"{series}.json"

            if out_path.exists():
                existing = json.loads(out_path.read_text())
                if existing:
                    console.print(f"[yellow]Skip[/] {series} — {len(existing)} slugs (use --reset to redo)")
                    grand_total += len(existing)
                    continue
                else:
                    out_path.unlink()
                    console.print(f"[yellow]Empty stub removed for {series}, re-discovering…[/]")

            slugs = await discover_series(page, series, browse_url, debug=debug)
            out_path.write_text(json.dumps(slugs, indent=2))
            console.print(f"[green]Saved[/] {len(slugs)} slugs → {out_path.name}")
            grand_total += len(slugs)
            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

        await browser.close()

    console.print(f"\n[bold green]Done.[/] Total slugs: {grand_total}")

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", nargs="+", choices=list(SERIES_BROWSE_URLS.keys()))
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Dump raw HTML and found slugs")
    parser.add_argument("--test", action="store_true", help="Test connectivity only, no scrape")
    args = parser.parse_args()
    asyncio.run(main(args.series, reset=args.reset, debug=args.debug, test=args.test))
