#!/usr/bin/env python3
"""
Phase 1 — Slug Discovery

Browses every series index page on josephsmithpapers.org and collects
the URL slug for every document. Saves one JSON file per series to
data/slugs/{series}.json.

Usage:
    python 01_discover_slugs.py
    python 01_discover_slugs.py --series documents journals
"""

import argparse
import asyncio
import json
import logging
import random
import time
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


async def get_page_slugs(page: Page, url: str) -> list[str]:
    """
    Load a browse/index page and extract all document slugs from links.
    Returns a list of slug strings.
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
    except PWTimeout:
        log.warning(f"Timeout loading {url}, retrying once…")
        await asyncio.sleep(5)
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

    # Wait for document list to appear — adjust selector based on actual site structure
    try:
        await page.wait_for_selector("a[href*='/paper-summary/']", timeout=10000)
    except PWTimeout:
        log.warning(f"No paper-summary links found on {url}")
        return []

    # Extract all hrefs pointing to /paper-summary/
    links = await page.eval_on_selector_all(
        "a[href*='/paper-summary/']",
        "els => els.map(e => e.getAttribute('href'))"
    )

    slugs = set()
    for href in links:
        if not href:
            continue
        # href format: /paper-summary/{slug}/{page}
        parts = href.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "paper-summary":
            slugs.add(parts[1])

    return sorted(slugs)


async def discover_series(page: Page, series: str, browse_url: str) -> list[str]:
    """
    Iterate through all pages of a series index, collecting slugs.
    Returns deduplicated sorted list of slugs.
    """
    all_slugs: set[str] = set()
    page_num = 1

    console.print(f"[bold cyan]Discovering:[/] {series}")

    while True:
        # Try both common pagination patterns
        if page_num == 1:
            url = browse_url
        else:
            url = f"{browse_url}?page={page_num}"

        log.info(f"  {series} page {page_num}: {url}")
        slugs = await get_page_slugs(page, url)

        if not slugs:
            log.info(f"  No slugs on page {page_num} — series complete")
            break

        new = set(slugs) - all_slugs
        if not new:
            log.info(f"  No new slugs on page {page_num} — series complete")
            break

        all_slugs.update(new)
        console.print(f"  Page {page_num}: +{len(new)} slugs (total {len(all_slugs)})")

        page_num += 1
        await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    return sorted(all_slugs)


async def main(series_filter: list[str] | None = None) -> None:
    targets = {
        k: v for k, v in SERIES_BROWSE_URLS.items()
        if series_filter is None or k in series_filter
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        grand_total = 0
        for series, browse_url in targets.items():
            out_path = SLUGS_DIR / f"{series}.json"

            # Skip if already discovered (allow re-run without re-scraping)
            if out_path.exists():
                existing = json.loads(out_path.read_text())
                console.print(
                    f"[yellow]Skip[/] {series} — already discovered "
                    f"{len(existing)} slugs (delete {out_path.name} to redo)"
                )
                grand_total += len(existing)
                continue

            slugs = await discover_series(page, series, browse_url)

            out_path.write_text(json.dumps(slugs, indent=2))
            console.print(
                f"[green]Saved[/] {len(slugs)} slugs → {out_path.relative_to(Path.cwd())}"
            )
            grand_total += len(slugs)

            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

        await browser.close()

    console.print(f"\n[bold green]Done.[/] Total slugs discovered: {grand_total}")

    # Write a combined master slug list
    master: list[dict] = []
    for series in SERIES_BROWSE_URLS:
        p = SLUGS_DIR / f"{series}.json"
        if p.exists():
            for slug in json.loads(p.read_text()):
                master.append({"series": series, "slug": slug})

    master_path = SLUGS_DIR / "master.json"
    master_path.write_text(json.dumps(master, indent=2))
    console.print(f"Master slug list → {master_path.relative_to(Path.cwd())} ({len(master)} entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover JSPP document slugs")
    parser.add_argument(
        "--series",
        nargs="+",
        choices=list(SERIES_BROWSE_URLS.keys()),
        help="Only discover specific series (default: all)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.series))
