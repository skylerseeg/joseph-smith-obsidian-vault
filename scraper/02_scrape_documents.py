#!/usr/bin/env python3
"""
Phase 2 — Document Scraping

For each slug discovered in Phase 1, loads the full paper-summary page,
extracts all document fields, and saves raw JSON to data/raw/{slug}.json.

Usage:
    python 02_scrape_documents.py                   # Scrape all slugs
    python 02_scrape_documents.py --priority-only   # Priority slugs first
    python 02_scrape_documents.py --series journals # One series only
    python 02_scrape_documents.py --slug journal-1832-1834  # Single slug
"""

import argparse
import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout
from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

from config import (
    BASE_URL,
    SLUGS_DIR,
    RAW_DIR,
    PAGE_LOAD_TIMEOUT,
    HEADLESS,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    PRIORITY_SLUGS,
    SCRAPE_LOG,
    ERROR_LOG,
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
error_log = logging.getLogger("errors")
error_log.addHandler(logging.FileHandler(ERROR_LOG))

console = Console()


# ── Data model ─────────────────────────────────────────────────────────────────

class Footnote(BaseModel):
    number: int
    text: str
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)


class JSPPDocument(BaseModel):
    slug: str
    series: str
    title: str
    date: str = ""
    date_range_start: str = ""
    date_range_end: str = ""
    doc_type: str = ""
    location: str = ""
    volume: str = ""
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    transcript: str = ""
    source_note: str = ""
    footnotes: list[Footnote] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    related_slugs: list[str] = Field(default_factory=list)
    url: str = ""
    page_count: int = 1
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_html: str = ""   # Store raw HTML for re-parsing without re-scraping


# ── Parsing helpers ─────────────────────────────────────────────────────────────

def extract_text(soup: BeautifulSoup, selector: str, default: str = "") -> str:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else default


def extract_all_text(soup: BeautifulSoup, selector: str) -> list[str]:
    return [el.get_text(strip=True) for el in soup.select(selector)]


def parse_document(html: str, slug: str, series: str) -> JSPPDocument:
    """
    Parse a rendered paper-summary page HTML into a JSPPDocument.

    NOTE: CSS selectors here are best-guess based on common JSPP page structure.
    They will likely need adjustment after inspecting real rendered HTML.
    Run with --headless=false and inspect the DOM to refine selectors.
    """
    soup = BeautifulSoup(html, "html.parser")
    doc = JSPPDocument(
        slug=slug,
        series=series,
        url=f"{BASE_URL}/paper-summary/{slug}/1",
        raw_html=html,
    )

    # ── Title ──────────────────────────────────────────────────────────────────
    # Try several common heading patterns
    for sel in ["h1.paper-title", "h1.document-title", "h1", ".title h1", ".document-header h1"]:
        title = extract_text(soup, sel)
        if title:
            doc.title = title
            break
    if not doc.title:
        # Fall back to <title> tag
        title_tag = soup.find("title")
        if title_tag:
            doc.title = re.sub(r"\s*[|\-–]\s*Joseph Smith Papers.*$", "", title_tag.text).strip()

    # ── Date ───────────────────────────────────────────────────────────────────
    for sel in [".document-date", ".paper-date", "[class*='date']", "time"]:
        date = extract_text(soup, sel)
        if date:
            doc.date = date
            break

    # ── Document type ──────────────────────────────────────────────────────────
    for sel in [".document-type", ".paper-type", "[class*='doc-type']"]:
        dt = extract_text(soup, sel)
        if dt:
            doc.doc_type = dt
            break

    # ── Location ───────────────────────────────────────────────────────────────
    for sel in [".document-location", ".paper-location", "[class*='location']"]:
        loc = extract_text(soup, sel)
        if loc:
            doc.location = loc
            break

    # ── Volume / Series info ───────────────────────────────────────────────────
    for sel in [".volume-info", ".series-volume", "[class*='volume']"]:
        vol = extract_text(soup, sel)
        if vol:
            doc.volume = vol
            break

    # ── Transcript ─────────────────────────────────────────────────────────────
    # The transcript is the main document text pane
    transcript_selectors = [
        ".transcript",
        ".document-transcript",
        "[class*='transcript']",
        ".paper-body",
        "article.content",
    ]
    for sel in transcript_selectors:
        el = soup.select_one(sel)
        if el:
            doc.transcript = el.get_text(separator="\n", strip=True)
            break

    # ── Source note ────────────────────────────────────────────────────────────
    for sel in [".source-note", "[class*='source-note']", ".provenance"]:
        sn = extract_text(soup, sel)
        if sn:
            doc.source_note = sn
            break

    # ── Footnotes ──────────────────────────────────────────────────────────────
    fn_containers = soup.select(".footnote, [class*='footnote'], .annotation")
    for fn in fn_containers:
        num_el = fn.select_one(".fn-number, sup, [class*='fn-num']")
        num_str = num_el.get_text(strip=True).strip("[]()") if num_el else ""
        try:
            num = int(re.sub(r"\D", "", num_str) or "0")
        except ValueError:
            num = 0
        text = fn.get_text(strip=True)
        doc.footnotes.append(Footnote(number=num, text=text))

    # ── People ─────────────────────────────────────────────────────────────────
    people_selectors = [
        ".people-mentioned a",
        "[class*='people'] a",
        ".person-index a",
        "a[href*='/person/']",
    ]
    for sel in people_selectors:
        names = extract_all_text(soup, sel)
        if names:
            doc.people = list(dict.fromkeys(names))  # deduplicate preserving order
            break

    # ── Places ─────────────────────────────────────────────────────────────────
    for sel in ["a[href*='/place/']", ".places-mentioned a", "[class*='places'] a"]:
        places = extract_all_text(soup, sel)
        if places:
            doc.places = list(dict.fromkeys(places))
            break

    # ── Images ─────────────────────────────────────────────────────────────────
    img_selectors = [
        "img[src*='facsimile']",
        "img[src*='manuscript']",
        "img[src*='image']",
        ".facsimile img",
        ".manuscript-image img",
    ]
    for sel in img_selectors:
        imgs = [el.get("src", "") for el in soup.select(sel)]
        imgs = [s for s in imgs if s]
        if imgs:
            doc.image_urls = imgs
            break

    # ── Related documents ──────────────────────────────────────────────────────
    related_links = soup.select("a[href*='/paper-summary/']")
    related_slugs = set()
    for link in related_links:
        href = link.get("href", "")
        parts = href.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "paper-summary":
            rs = parts[1]
            if rs != slug:
                related_slugs.add(rs)
    doc.related_slugs = sorted(related_slugs)

    return doc


# ── Multi-page handling ─────────────────────────────────────────────────────────

async def get_page_count(page: Page, slug: str) -> int:
    """Detect how many pages a document has."""
    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    # Common pagination patterns
    for sel in [".pagination li", ".page-links a", "[class*='pagination'] a"]:
        pages = soup.select(sel)
        nums = []
        for p in pages:
            try:
                nums.append(int(re.sub(r"\D", "", p.get_text(strip=True))))
            except ValueError:
                pass
        if nums:
            return max(nums)

    return 1


async def scrape_all_pages(page: Page, slug: str) -> str:
    """
    Scrape all pages of a multi-page document and concatenate transcript text.
    Returns the combined HTML of page 1 (with appended transcript from later pages).
    """
    url1 = f"{BASE_URL}/paper-summary/{slug}/1"
    await page.goto(url1, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)

    # Try to detect page count from pagination controls
    page_count = await get_page_count(page, slug)
    html = await page.content()

    if page_count <= 1:
        return html

    # Collect additional pages' transcript content
    extra_transcripts: list[str] = []
    for pg in range(2, page_count + 1):
        await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
        pg_url = f"{BASE_URL}/paper-summary/{slug}/{pg}"
        try:
            await page.goto(pg_url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
            pg_html = await page.content()
            soup = BeautifulSoup(pg_html, "html.parser")
            for sel in [".transcript", ".document-transcript", "[class*='transcript']", ".paper-body"]:
                el = soup.select_one(sel)
                if el:
                    extra_transcripts.append(el.get_text(separator="\n", strip=True))
                    break
        except PWTimeout:
            log.warning(f"  Timeout on page {pg} of {slug}")

    if extra_transcripts:
        # Inject extra pages into the base HTML via a placeholder
        combined = "\n\n".join(extra_transcripts)
        html = html.replace("</body>", f'<div class="extra-pages">{combined}</div></body>')

    return html


# ── Main scraping loop ──────────────────────────────────────────────────────────

async def scrape_slug(page: Page, series: str, slug: str) -> JSPPDocument | None:
    """Scrape a single document. Returns None on failure."""
    out_path = RAW_DIR / f"{slug}.json"
    if out_path.exists():
        return None  # Already scraped

    url = f"{BASE_URL}/paper-summary/{slug}/1"
    try:
        html = await scrape_all_pages(page, slug)
        doc = parse_document(html, slug, series)
        out_path.write_text(doc.model_dump_json(indent=2))
        return doc
    except PWTimeout:
        error_log.error(f"TIMEOUT  {series}  {slug}  {url}")
        return None
    except Exception as exc:
        error_log.error(f"ERROR    {series}  {slug}  {url}  {exc!r}")
        return None


async def main(
    series_filter: list[str] | None = None,
    priority_only: bool = False,
    single_slug: str | None = None,
) -> None:

    # Build work queue
    if single_slug:
        queue = [{"series": "unknown", "slug": single_slug}]
    elif priority_only:
        queue = [{"series": "priority", "slug": s} for s in PRIORITY_SLUGS]
    else:
        # Load master slug list
        master_path = SLUGS_DIR / "master.json"
        if not master_path.exists():
            console.print("[red]No master slug list found. Run 01_discover_slugs.py first.[/]")
            return
        master = json.loads(master_path.read_text())
        if series_filter:
            queue = [e for e in master if e["series"] in series_filter]
        else:
            # Put priority slugs first
            priority_set = set(PRIORITY_SLUGS)
            priority_entries = [e for e in master if e["slug"] in priority_set]
            rest = [e for e in master if e["slug"] not in priority_set]
            queue = priority_entries + rest

    # Filter out already-scraped
    remaining = [e for e in queue if not (RAW_DIR / f"{e['slug']}.json").exists()]
    already_done = len(queue) - len(remaining)

    console.print(f"Queue: {len(queue)} documents ({already_done} already scraped, {len(remaining)} to do)")

    if not remaining:
        console.print("[green]All documents already scraped.[/]")
        return

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

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scraping…", total=len(remaining))

            for i, entry in enumerate(remaining):
                series = entry["series"]
                slug = entry["slug"]

                progress.update(task, description=f"[cyan]{slug[:50]}")
                doc = await scrape_slug(page, series, slug)

                if doc:
                    log.info(f"OK  {series}  {slug}  '{doc.title}'")
                else:
                    log.warning(f"SKIP (already done or failed): {slug}")

                progress.advance(task)

                # Periodic delay
                if i < len(remaining) - 1:
                    await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

        await browser.close()

    total_raw = len(list(RAW_DIR.glob("*.json")))
    console.print(f"\n[bold green]Done.[/] {len(remaining)} scraped. Total in data/raw/: {total_raw}")

    # Report failures
    error_count = sum(1 for line in ERROR_LOG.read_text().splitlines() if "ERROR" in line) if ERROR_LOG.exists() else 0
    if error_count:
        console.print(f"[yellow]{error_count} errors logged to {ERROR_LOG}. Re-run to retry.[/]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape JSPP documents")
    parser.add_argument("--priority-only", action="store_true", help="Only scrape priority slugs")
    parser.add_argument("--series", nargs="+", help="Only scrape specific series")
    parser.add_argument("--slug", help="Scrape a single specific slug")
    args = parser.parse_args()
    asyncio.run(main(
        series_filter=args.series,
        priority_only=args.priority_only,
        single_slug=args.slug,
    ))
