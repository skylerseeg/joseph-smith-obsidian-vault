#!/usr/bin/env python3
"""
Phase 1 — Slug Discovery

Strategy: intercept the Angular app's internal API calls to capture the
document list JSON directly, rather than waiting for links to render in HTML.
Falls back to mining raw HTML for /paper-summary/ slugs if no API found.

Usage:
    python 01_discover_slugs.py
    python 01_discover_slugs.py --series documents journals
    python 01_discover_slugs.py --reset
    python 01_discover_slugs.py --test           # connectivity + API sniff
    python 01_discover_slugs.py --calendar       # use calendar-of-documents page
"""

import argparse
import asyncio
import json
import logging
import random
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page, Request, Response, TimeoutError as PWTimeout
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

SLUG_RE = re.compile(r"/paper-summary/([^/?#\s\"'<>]+)")


# ── Page loading ───────────────────────────────────────────────────────────────

async def load_page(page: Page, url: str, settle: int = JS_SETTLE_WAIT) -> bool:
    try:
        await page.goto(url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(settle)
        return True
    except PWTimeout:
        log.warning(f"'load' timeout on {url}, trying domcontentloaded…")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(settle + 5)
        return True
    except PWTimeout:
        log.error(f"Total timeout on {url}")
        return False


# ── API interception ───────────────────────────────────────────────────────────

async def sniff_api_for_slugs(page: Page, url: str, wait_seconds: int = 15) -> tuple[list[str], list[str]]:
    """
    Load a page while intercepting all JSON API responses.
    Returns (slugs_found, api_urls_seen).
    """
    api_responses: list[dict] = []
    api_urls: list[str] = []

    async def handle_response(response: Response):
        rurl = response.url
        ctype = response.headers.get("content-type", "")
        if "json" in ctype or rurl.endswith(".json"):
            api_urls.append(rurl)
            try:
                body = await response.json()
                api_responses.append({"url": rurl, "body": body})
            except Exception:
                pass

    page.on("response", handle_response)

    ok = await load_page(page, url, settle=wait_seconds)
    page.remove_listener("response", handle_response)

    if not ok:
        return [], api_urls

    # Mine slugs from all captured API responses
    slugs: set[str] = set()
    for entry in api_responses:
        raw = json.dumps(entry["body"])
        for m in SLUG_RE.finditer(raw):
            slugs.add(m.group(1))

    # Also mine the rendered HTML
    html = await page.content()
    for m in SLUG_RE.finditer(html):
        slugs.add(m.group(1))

    return sorted(slugs), api_urls


# ── Calendar of documents ──────────────────────────────────────────────────────

async def slugs_from_calendar(page: Page, debug: bool = False) -> list[str]:
    """
    The /reference/calendar-of-documents page is a comprehensive chronological
    index. Mine it for every paper-summary slug.
    """
    console.print("\n[bold cyan]Mining calendar-of-documents…[/]")
    url = f"{BASE_URL}/reference/calendar-of-documents"
    slugs, apis = await sniff_api_for_slugs(page, url, wait_seconds=20)

    if debug:
        console.print(f"  API endpoints hit: {len(apis)}")
        for a in apis[:20]:
            console.print(f"    {a}")

    console.print(f"  Found {len(slugs)} slugs from calendar")
    return slugs


# ── Test mode ─────────────────────────────────────────────────────────────────

async def run_test(page: Page) -> None:
    console.print("\n[bold]API sniff test — documents browse page[/]")
    url = f"{BASE_URL}/the-papers/documents"
    slugs, apis = await sniff_api_for_slugs(page, url, wait_seconds=20)

    console.print(f"\n[bold]API endpoints intercepted ({len(apis)}):[/]")
    for a in apis:
        console.print(f"  {a}")

    console.print(f"\n[bold]Slugs found ({len(slugs)}):[/]")
    for s in sorted(slugs)[:30]:
        console.print(f"  {s}")

    console.print(f"\n[bold]Also testing calendar page…[/]")
    url2 = f"{BASE_URL}/reference/calendar-of-documents"
    slugs2, apis2 = await sniff_api_for_slugs(page, url2, wait_seconds=20)
    console.print(f"  API endpoints: {len(apis2)}")
    for a in apis2[:10]:
        console.print(f"  {a}")
    console.print(f"  Slugs: {len(slugs2)}")
    for s in sorted(slugs2)[:20]:
        console.print(f"  {s}")


# ── Series discovery ───────────────────────────────────────────────────────────

async def discover_series(page: Page, series: str, browse_url: str) -> list[str]:
    all_slugs: set[str] = set()
    page_num = 1
    console.print(f"\n[bold cyan]Discovering:[/] {series}")

    while True:
        url = browse_url if page_num == 1 else f"{browse_url}?page={page_num}"
        log.info(f"  {series} p{page_num}: {url}")

        slugs, apis = await sniff_api_for_slugs(page, url, wait_seconds=15)

        if page_num == 1 and apis:
            log.info(f"  {len(apis)} API calls intercepted for {series}")

        new = set(slugs) - all_slugs
        if not new:
            log.info(f"  No new slugs on page {page_num} — done")
            break

        all_slugs.update(new)
        console.print(f"  Page {page_num}: +{len(new)} slugs (total {len(all_slugs)})")
        page_num += 1
        await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    return sorted(all_slugs)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(
    series_filter: list[str] | None = None,
    reset: bool = False,
    test: bool = False,
    use_calendar: bool = False,
) -> None:
    targets = {
        k: v for k, v in SERIES_BROWSE_URLS.items()
        if series_filter is None or k in series_filter
    }

    if reset:
        for series in targets:
            p = SLUGS_DIR / f"{series}.json"
            if p.exists() and json.loads(p.read_text()) == []:
                p.unlink()
                console.print(f"[yellow]Deleted empty stub:[/] {p.name}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
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
            await run_test(page)
            await browser.close()
            return

        if use_calendar:
            all_slugs = await slugs_from_calendar(page)
            out = SLUGS_DIR / "calendar-all.json"
            out.write_text(json.dumps(sorted(all_slugs), indent=2))
            console.print(f"[green]Saved {len(all_slugs)} slugs → {out.name}[/]")
            # Write master
            master = [{"series": "calendar", "slug": s} for s in all_slugs]
            (SLUGS_DIR / "master.json").write_text(json.dumps(master, indent=2))
            await browser.close()
            return

        grand_total = 0
        for series, browse_url in targets.items():
            out_path = SLUGS_DIR / f"{series}.json"

            if out_path.exists():
                existing = json.loads(out_path.read_text())
                if existing:
                    console.print(f"[yellow]Skip[/] {series} — {len(existing)} slugs (--reset to redo)")
                    grand_total += len(existing)
                    continue
                else:
                    out_path.unlink()

            slugs = await discover_series(page, series, browse_url)
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
    (SLUGS_DIR / "master.json").write_text(json.dumps(master, indent=2))
    console.print(f"Master list → master.json ({len(master)} entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", nargs="+", choices=list(SERIES_BROWSE_URLS.keys()))
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--test", action="store_true", help="Sniff API calls, report what's found")
    parser.add_argument("--calendar", action="store_true", help="Mine calendar-of-documents for all slugs")
    args = parser.parse_args()
    asyncio.run(main(args.series, reset=args.reset, test=args.test, use_calendar=args.calendar))
