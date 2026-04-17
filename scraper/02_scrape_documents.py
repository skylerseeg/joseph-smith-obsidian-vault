#!/usr/bin/env python3
"""
Phase 2 — Document Scraping (Next.js / httpx edition)

Fetches each document page via httpx, extracts __NEXT_DATA__ JSON,
and saves structured data to data/raw/{slug}.json. No browser needed.

Usage:
    python 02_scrape_documents.py                   # Scrape all slugs
    python 02_scrape_documents.py --priority-only   # Priority slugs first
    python 02_scrape_documents.py --series journals # One series only
    python 02_scrape_documents.py --slug journal-1832-1834  # Single slug
    python 02_scrape_documents.py --test            # Inspect one page structure
"""

import argparse
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    TaskProgressColumn, TimeRemainingColumn,
)

from config import (
    BASE_URL,
    SLUGS_DIR,
    RAW_DIR,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    PRIORITY_SLUGS,
    SCRAPE_LOG,
    ERROR_LOG,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.FileHandler(SCRAPE_LOG), logging.StreamHandler()],
)
log = logging.getLogger(__name__)
error_log = logging.getLogger("errors")
error_log.addHandler(logging.FileHandler(ERROR_LOG))
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

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


# ── Data model ─────────────────────────────────────────────────────────────────

class JSPPDocument(BaseModel):
    slug: str
    series: str = ""
    title: str = ""
    date: str = ""
    doc_type: str = ""
    location: str = ""
    volume: str = ""
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    transcript: str = ""
    source_note: str = ""
    footnotes: list[dict] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    related_slugs: list[str] = Field(default_factory=list)
    url: str = ""
    page_count: int = 1
    raw_next_data: dict = Field(default_factory=dict)
    scraped_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def fetch(client: httpx.Client, url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            r = client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
            if r.status_code == 200:
                return r.text
            log.warning(f"HTTP {r.status_code} for {url}")
            return None
        except Exception as e:
            log.warning(f"Attempt {attempt+1} failed {url}: {e}")
            time.sleep(2 ** attempt)
    return None


def extract_next_data(html: str) -> dict | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ── Document parsing ───────────────────────────────────────────────────────────

def text_from(obj: Any) -> str:
    """Recursively extract all string values from a JSON structure."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(text_from(i) for i in obj if i)
    if isinstance(obj, dict):
        return " ".join(text_from(v) for v in obj.values() if v)
    return ""


def find_key(obj: Any, key: str) -> Any:
    """Recursively find the first value for a given key."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = find_key(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_key(item, key)
            if result is not None:
                return result
    return None


def find_all(obj: Any, key: str, results: list | None = None) -> list:
    """Recursively collect all values for a given key."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        if key in obj:
            results.append(obj[key])
        for v in obj.values():
            find_all(v, key, results)
    elif isinstance(obj, list):
        for item in obj:
            find_all(item, key, results)
    return results


SLUG_RE = re.compile(r"/paper-summary/([^/?#\s\"'<>\\]+)")


def parse_document(data: dict, slug: str, series: str) -> JSPPDocument:
    """
    Parse __NEXT_DATA__ from a paper-summary page into a JSPPDocument.
    The structure varies by document type; we probe multiple known key paths.
    """
    doc = JSPPDocument(
        slug=slug,
        series=series,
        url=f"{BASE_URL}/paper-summary/{slug}/1",
        raw_next_data=data,
    )

    pp = data.get("props", {}).get("pageProps", {})

    # ── Title ──────────────────────────────────────────────────────────────────
    for key in ["title", "documentTitle", "paperTitle", "heading"]:
        val = find_key(pp, key)
        if isinstance(val, str) and len(val) > 3:
            doc.title = val.strip()
            break

    # ── Date ───────────────────────────────────────────────────────────────────
    for key in ["date", "documentDate", "dateString", "pubDate"]:
        val = find_key(pp, key)
        if isinstance(val, str) and val:
            doc.date = val.strip()
            break

    # ── Document type ──────────────────────────────────────────────────────────
    for key in ["documentType", "docType", "type", "genre"]:
        val = find_key(pp, key)
        if isinstance(val, str) and val:
            doc.doc_type = val.strip()
            break

    # ── Location ───────────────────────────────────────────────────────────────
    for key in ["location", "place", "createdAt", "originPlace"]:
        val = find_key(pp, key)
        if isinstance(val, str) and val:
            doc.location = val.strip()
            break

    # ── Transcript ─────────────────────────────────────────────────────────────
    # Try known transcript container keys
    for key in ["transcript", "transcription", "text", "content", "body", "documentText"]:
        val = find_key(pp, key)
        if val:
            extracted = text_from(val).strip()
            if len(extracted) > 50:
                doc.transcript = extracted
                break

    # ── Source note ────────────────────────────────────────────────────────────
    for key in ["sourceNote", "source_note", "historicalIntro", "introduction"]:
        val = find_key(pp, key)
        if isinstance(val, str) and len(val) > 20:
            doc.source_note = val.strip()
            break

    # ── People ─────────────────────────────────────────────────────────────────
    people_raw = find_all(pp, "people") + find_all(pp, "persons") + find_all(pp, "individuals")
    for item in people_raw:
        if isinstance(item, str) and item:
            doc.people.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("label") or item.get("displayName")
            if name:
                doc.people.append(name)
        elif isinstance(item, list):
            for subitem in item:
                if isinstance(subitem, str):
                    doc.people.append(subitem)
                elif isinstance(subitem, dict):
                    name = subitem.get("name") or subitem.get("label")
                    if name:
                        doc.people.append(name)
    doc.people = list(dict.fromkeys(doc.people))  # deduplicate

    # ── Places ─────────────────────────────────────────────────────────────────
    places_raw = find_all(pp, "places") + find_all(pp, "locations")
    for item in places_raw:
        if isinstance(item, str) and item:
            doc.places.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("label")
            if name:
                doc.places.append(name)
    doc.places = list(dict.fromkeys(doc.places))

    # ── Related slugs ──────────────────────────────────────────────────────────
    raw_json = json.dumps(data)
    for m in SLUG_RE.finditer(raw_json):
        s = m.group(1)
        if s != slug:
            doc.related_slugs.append(s)
    doc.related_slugs = sorted(set(doc.related_slugs))

    # ── Page count ─────────────────────────────────────────────────────────────
    page_count = find_key(pp, "pageCount") or find_key(pp, "totalPages") or find_key(pp, "pages")
    if isinstance(page_count, int):
        doc.page_count = page_count

    return doc


def scrape_all_pages(client: httpx.Client, slug: str, series: str) -> JSPPDocument | None:
    """Fetch page 1 to get structure, then collect transcripts from all pages."""
    url1 = f"{BASE_URL}/paper-summary/{slug}/1"
    html1 = fetch(client, url1)
    if not html1:
        error_log.error(f"ERROR  {series}  {slug}  {url1}")
        return None

    data = extract_next_data(html1)
    if not data:
        log.warning(f"No __NEXT_DATA__ for {slug}")
        # Still try to save whatever we can
        data = {}

    doc = parse_document(data, slug, series)

    # If multi-page, collect additional transcript pages
    if doc.page_count > 1:
        extra = []
        for pg in range(2, doc.page_count + 1):
            pg_html = fetch(client, f"{BASE_URL}/paper-summary/{slug}/{pg}")
            if not pg_html:
                break
            pg_data = extract_next_data(pg_html)
            if pg_data:
                for key in ["transcript", "text", "content", "body"]:
                    val = find_key(pg_data.get("props", {}).get("pageProps", {}), key)
                    if val:
                        extra.append(text_from(val).strip())
                        break
            time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
        if extra:
            doc.transcript = doc.transcript + "\n\n" + "\n\n".join(extra)

    return doc


# ── Test mode ──────────────────────────────────────────────────────────────────

def run_test(client: httpx.Client, slug: str = "journal-1832-1834") -> None:
    url = f"{BASE_URL}/paper-summary/{slug}/1"
    console.print(f"\n[bold]Test: {url}[/]")
    html = fetch(client, url)
    if not html:
        console.print("[red]Failed[/]")
        return
    console.print(f"HTML: {len(html)} chars")

    data = extract_next_data(html)
    if not data:
        console.print("[red]No __NEXT_DATA__[/]")
        return

    pp = data.get("props", {}).get("pageProps", {})
    console.print(f"__NEXT_DATA__: {len(json.dumps(data))} chars")
    console.print(f"\npageProps keys: {list(pp.keys())}")

    # Print first 4000 chars of pageProps
    console.print("\n[bold]pageProps (first 4000 chars):[/]")
    console.print(json.dumps(pp, indent=2)[:4000])

    # Save full data
    out = Path(f"nextdata_{slug[:30]}.json")
    out.write_text(json.dumps(data, indent=2))
    console.print(f"\nFull data → {out}")

    # Try parsing
    doc = parse_document(data, slug, "test")
    console.print(f"\n[bold]Parsed document:[/]")
    console.print(f"  Title:      {doc.title!r}")
    console.print(f"  Date:       {doc.date!r}")
    console.print(f"  Type:       {doc.doc_type!r}")
    console.print(f"  Location:   {doc.location!r}")
    console.print(f"  Page count: {doc.page_count}")
    console.print(f"  People:     {doc.people[:5]}")
    console.print(f"  Transcript: {doc.transcript[:200]!r}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    series_filter: list[str] | None = None,
    priority_only: bool = False,
    single_slug: str | None = None,
    test: bool = False,
) -> None:

    with httpx.Client() as client:
        if test:
            slug = single_slug or "journal-1832-1834"
            run_test(client, slug)
            return

        # Build work queue
        if single_slug:
            queue = [{"series": "unknown", "slug": single_slug}]
        elif priority_only:
            queue = [{"series": "priority", "slug": s} for s in PRIORITY_SLUGS]
        else:
            master_path = SLUGS_DIR / "master.json"
            if not master_path.exists():
                console.print("[red]No master slug list. Run 01_discover_slugs.py first.[/]")
                return
            master = json.loads(master_path.read_text())
            if series_filter:
                master = [e for e in master if e["series"] in series_filter]
            priority_set = set(PRIORITY_SLUGS)
            queue = (
                [e for e in master if e["slug"] in priority_set] +
                [e for e in master if e["slug"] not in priority_set]
            )

        remaining = [e for e in queue if not (RAW_DIR / f"{e['slug']}.json").exists()]
        done_count = len(queue) - len(remaining)
        console.print(f"Queue: {len(queue)} ({done_count} done, {len(remaining)} to scrape)")

        if not remaining:
            console.print("[green]All documents already scraped.[/]")
            return

        scraped = 0
        errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scraping…", total=len(remaining))

            for entry in remaining:
                series = entry["series"]
                slug = entry["slug"]
                progress.update(task, description=f"[cyan]{slug[:55]}")

                doc = scrape_all_pages(client, slug, series)
                if doc:
                    out = RAW_DIR / f"{slug}.json"
                    out.write_text(doc.model_dump_json(indent=2))
                    scraped += 1
                    log.info(f"OK  {series}  {slug}  '{doc.title}'")
                else:
                    errors += 1

                progress.advance(task)
                time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    total = len(list(RAW_DIR.glob("*.json")))
    console.print(f"\n[bold green]Done.[/] Scraped: {scraped}  Errors: {errors}  Total in raw/: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--priority-only", action="store_true")
    parser.add_argument("--series", nargs="+")
    parser.add_argument("--slug", help="Scrape a single slug")
    parser.add_argument("--test", action="store_true", help="Inspect one page's __NEXT_DATA__ structure")
    args = parser.parse_args()
    main(
        series_filter=args.series,
        priority_only=args.priority_only,
        single_slug=args.slug,
        test=args.test,
    )
