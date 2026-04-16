#!/usr/bin/env python3
"""
Phase 1 — Slug Discovery (Next.js edition)

The JSPP site is built on Next.js. Every page embeds its data in a
<script id="__NEXT_DATA__"> JSON blob in the initial HTML response.
We extract that JSON directly — no browser, no JavaScript, no timeouts.

Strategy:
  1. Fetch each series page with httpx (fast, no Playwright needed)
  2. Extract __NEXT_DATA__ JSON
  3. Recursively mine it for all document slugs
  4. If a series page links to volume sub-pages, fetch those too
  5. Fall back to Playwright only if httpx is blocked

Usage:
    python 01_discover_slugs.py
    python 01_discover_slugs.py --series documents
    python 01_discover_slugs.py --reset
    python 01_discover_slugs.py --test         # test one page, print structure
"""

import argparse
import asyncio
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.pretty import pprint

from config import (
    BASE_URL,
    SERIES_BROWSE_URLS,
    SLUGS_DIR,
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

SLUG_RE = re.compile(r"/paper-summary/([^/?#\s\"'<>\\]+)")
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


# ── HTTP fetch ─────────────────────────────────────────────────────────────────

def fetch_html(client: httpx.Client, url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            r = client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
            if r.status_code == 200:
                return r.text
            log.warning(f"HTTP {r.status_code} for {url}")
            return None
        except Exception as e:
            log.warning(f"Attempt {attempt+1} failed for {url}: {e}")
            time.sleep(2 ** attempt)
    return None


def extract_next_data(html: str) -> dict | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse __NEXT_DATA__: {e}")
        return None


# ── Slug mining ────────────────────────────────────────────────────────────────

def mine_slugs_recursive(obj: Any, found: set[str]) -> None:
    """Recursively walk any JSON structure mining paper-summary slugs."""
    if isinstance(obj, str):
        for m in SLUG_RE.finditer(obj):
            found.add(m.group(1))
    elif isinstance(obj, dict):
        for v in obj.values():
            mine_slugs_recursive(v, found)
    elif isinstance(obj, list):
        for item in obj:
            mine_slugs_recursive(item, found)


def mine_slugs_from_html(html: str) -> set[str]:
    """Mine all paper-summary slugs from raw HTML (catches all occurrences)."""
    return set(SLUG_RE.findall(html))


# ── Volume sub-page discovery ─────────────────────────────────────────────────

def find_subpage_paths(data: dict) -> list[str]:
    """
    Extract any /the-papers/* sub-paths from __NEXT_DATA__ that look like
    volume or sub-series pages (e.g. /the-papers/documents/jspd1).
    """
    raw = json.dumps(data)
    paths = re.findall(r'"/the-papers/[^"]+/[^"]{4,}"', raw)
    paths = [p.strip('"') for p in paths]
    # Filter to paths that look like volume pages (not just series roots)
    seen = set(SERIES_BROWSE_URLS.values())
    result = []
    for p in paths:
        full = BASE_URL + p if not p.startswith("http") else p
        if full not in seen and "/the-papers/" in p:
            result.append(p)
    return sorted(set(result))


# ── Per-series discovery ───────────────────────────────────────────────────────

def fetch_all_pages(client: httpx.Client, base_url: str, label: str) -> set[str]:
    """
    Fetch a URL and all its paginated variants (?page=2, ?page=3, …).
    Returns all slugs found across all pages.
    """
    slugs: set[str] = set()
    for page_num in range(1, 200):  # generous upper bound
        url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
        html = fetch_html(client, url)
        if not html:
            break
        before = len(slugs)
        slugs.update(mine_slugs_from_html(html))
        data = extract_next_data(html)
        if data:
            mine_slugs_recursive(data, slugs)
        new = len(slugs) - before
        log.info(f"  {label} p{page_num}: +{new} slugs (total {len(slugs)})")
        if new == 0:
            break  # no new slugs = end of pagination
        time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
    return slugs


def discover_series(client: httpx.Client, series: str, browse_url: str) -> list[str]:
    all_slugs: set[str] = set()
    console.print(f"\n[bold cyan]Discovering:[/] {series}")

    # Step 1: Fetch series index page to find year/volume sub-pages
    html = fetch_html(client, browse_url)
    if not html:
        log.error(f"Could not fetch {browse_url}")
        return []

    data = extract_next_data(html)
    if not data:
        log.warning(f"No __NEXT_DATA__ on {browse_url}")
        return []

    # Mine slugs directly on series page (usually 0 but worth checking)
    mine_slugs_recursive(data, all_slugs)
    all_slugs.update(mine_slugs_from_html(html))

    # Step 2: Find year/volume sub-pages and crawl each with pagination
    subpages = find_subpage_paths(data)

    if subpages:
        # Prefer year-based pages over volume pages to avoid duplicates
        year_pages = [p for p in subpages if re.search(r'/\d{4}$|/pre\d+$', p)]
        vol_pages  = [p for p in subpages if p not in year_pages]
        ordered = year_pages if year_pages else vol_pages

        console.print(f"  {len(ordered)} sub-pages to crawl ({'year' if year_pages else 'volume'}-based)")

        for sub_path in ordered:
            sub_url = BASE_URL + sub_path
            before = len(all_slugs)
            new_slugs = fetch_all_pages(client, sub_url, sub_path)
            all_slugs.update(new_slugs)
            added = len(all_slugs) - before
            console.print(f"  {sub_path}: +{added} slugs")

    else:
        # No sub-pages found — try paginating the series root directly
        console.print(f"  No sub-pages found, paginating series root…")
        all_slugs.update(fetch_all_pages(client, browse_url, series))

    console.print(f"  [green]Total: {len(all_slugs)} slugs for {series}[/]")
    return sorted(all_slugs)


# ── Test mode ─────────────────────────────────────────────────────────────────

def inspect_page(client: httpx.Client, url: str, label: str) -> dict | None:
    console.print(f"\n[bold]── {label} ──[/]")
    console.print(f"URL: {url}")
    html = fetch_html(client, url)
    if not html:
        console.print("[red]Failed to fetch[/]")
        return None
    console.print(f"HTML: {len(html)} chars")
    data = extract_next_data(html)
    if not data:
        console.print("[red]No __NEXT_DATA__[/]")
        return None
    console.print(f"__NEXT_DATA__: {len(json.dumps(data))} chars")

    pp = data.get("props", {}).get("pageProps", {})

    # Print docDetails — this is the document listing
    doc_details = pp.get("docDetails")
    if doc_details:
        console.print(f"\n[green]docDetails type:[/] {type(doc_details).__name__}")
        if isinstance(doc_details, dict):
            console.print(f"docDetails keys: {list(doc_details.keys())}")
            console.print(json.dumps(doc_details, indent=2)[:3000])
        elif isinstance(doc_details, list):
            console.print(f"docDetails length: {len(doc_details)}")
            console.print(json.dumps(doc_details[:3], indent=2))
    else:
        console.print("[yellow]No docDetails key[/]")
        console.print(f"pageProps keys: {list(pp.keys())}")
        # Print first 2000 chars of pageProps to find where docs are
        console.print(json.dumps(pp, indent=2)[:2000])

    # Mine slugs
    slugs: set[str] = set()
    mine_slugs_recursive(data, slugs)
    console.print(f"\nSlugs found: {len(slugs)}")
    for s in sorted(slugs)[:15]:
        console.print(f"  {s}")

    return data


def run_test(client: httpx.Client) -> None:
    # Test 1: series index page
    data = inspect_page(client, f"{BASE_URL}/the-papers/documents", "Documents series index")
    if data:
        Path("nextdata_series.json").write_text(json.dumps(data, indent=2))
        console.print("[dim]Saved → nextdata_series.json[/]")

    # Test 2: year sub-page (1830 — smallest year, fastest)
    data2 = inspect_page(client, f"{BASE_URL}/the-papers/documents/1830", "Documents / 1830 year page")
    if data2:
        Path("nextdata_1830.json").write_text(json.dumps(data2, indent=2))
        console.print("[dim]Saved → nextdata_1830.json[/]")

    # Test 3: probe the internal API directly
    console.print("\n[bold]── Internal API probe ──[/]")
    api_base = "https://jsp-api.pvu.cf.churchofjesuschrist.org"
    api_probes = [
        f"{api_base}/documents",
        f"{api_base}/papers",
        f"{api_base}/api/documents",
        f"{api_base}/api/papers",
        f"{api_base}/paper-summary",
        f"{api_base}/the-papers/documents",
    ]
    for api_url in api_probes:
        try:
            r = client.get(api_url, headers=HEADERS, timeout=10, follow_redirects=True)
            console.print(f"  {r.status_code}  {api_url}  [{r.headers.get('content-type', '?')}]  {len(r.text)} chars")
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                console.print(f"    Preview: {r.text[:300]}")
        except Exception as e:
            console.print(f"  ERR  {api_url}  {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    series_filter: list[str] | None = None,
    reset: bool = False,
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
                p.unlink()
                console.print(f"[yellow]Deleted:[/] {p.name}")

    with httpx.Client() as client:
        if test:
            run_test(client)
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

            slugs = discover_series(client, series, browse_url)
            out_path.write_text(json.dumps(slugs, indent=2))
            grand_total += len(slugs)
            time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

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
    parser.add_argument("--test", action="store_true", help="Inspect __NEXT_DATA__ structure of documents page")
    args = parser.parse_args()
    main(args.series, reset=args.reset, test=args.test)
