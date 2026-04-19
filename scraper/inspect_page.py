#!/usr/bin/env python3
"""
Page Inspector — Diagnostic Tool

Opens a JSPP page in a visible browser and prints the full rendered HTML
along with a report of every CSS class and element that looks relevant.
Use this FIRST to calibrate the CSS selectors in 02_scrape_documents.py
before running the full scrape.

Usage:
    python inspect_page.py
    python inspect_page.py --slug journal-1832-1834
    python inspect_page.py --url "https://www.josephsmithpapers.org/the-papers/documents"
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config import BASE_URL, PAGE_LOAD_TIMEOUT


async def inspect(url: str, output_file: Path | None = None) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # Always visible for inspection
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        print(f"\nLoading: {url}")
        await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)  # Extra wait for JS

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        print("\n" + "="*60)
        print("PAGE TITLE:", soup.title.get_text() if soup.title else "None")
        print("="*60)

        # ── Print all unique CSS classes ───────────────────────────────────────
        print("\n--- Unique CSS classes (potential selectors) ---")
        all_classes: set[str] = set()
        for el in soup.find_all(class_=True):
            for cls in el.get("class", []):
                all_classes.add(cls)
        for cls in sorted(all_classes):
            el = soup.select_one(f".{cls}")
            if el:
                preview = el.get_text(strip=True)[:60].replace("\n", " ")
                print(f"  .{cls:40s} → {preview!r}")

        # ── Print all paper-summary links ──────────────────────────────────────
        print("\n--- paper-summary links ---")
        links = soup.select("a[href*='/paper-summary/']")
        for link in links[:20]:
            print(f"  {link.get('href')}  →  {link.get_text(strip=True)[:50]}")
        if len(links) > 20:
            print(f"  ... and {len(links)-20} more")

        # ── Print all anchor tags ──────────────────────────────────────────────
        print("\n--- All internal links ---")
        for a in soup.select("a[href^='/']")[:30]:
            print(f"  {a.get('href')}  →  {a.get_text(strip=True)[:50]}")

        # ── Try to detect JSON data embedded in page ───────────────────────────
        print("\n--- Script tags with data ---")
        for script in soup.select("script"):
            src = script.get("src", "")
            text = script.get_text()
            if not src and len(text) > 50:
                # Check if it's JSON data
                if text.strip().startswith("{") or text.strip().startswith("["):
                    print(f"  Inline JSON script ({len(text)} chars): {text[:100]}…")
                elif "window.__" in text or "var __" in text:
                    print(f"  Data variable script ({len(text)} chars): {text[:100]}…")

        # ── Network requests (via Playwright) ─────────────────────────────────
        print("\n--- Network requests intercepted ---")
        network_urls: list[str] = []

        def on_request(request):
            url = request.url
            if any(x in url for x in ["api", "json", "data", "document"]):
                network_urls.append(f"{request.method} {url}")

        page.on("request", on_request)
        # Reload to capture network traffic
        await page.reload(wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        for req in network_urls[:30]:
            print(f"  {req}")

        # ── Save HTML for offline analysis ────────────────────────────────────
        if output_file:
            output_file.write_text(html, encoding="utf-8")
            print(f"\nFull HTML saved to: {output_file}")
        else:
            out = Path("inspect_output.html")
            out.write_text(html, encoding="utf-8")
            print(f"\nFull HTML saved to: {out}")

        print("\nBrowser will close in 10 seconds (or press Ctrl+C to keep open)…")
        await asyncio.sleep(10)
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a JSPP page for scraper calibration")
    parser.add_argument("--slug", default="journal-1832-1834", help="Document slug to inspect")
    parser.add_argument("--url", help="Full URL to inspect (overrides --slug)")
    parser.add_argument("--output", type=Path, help="Path to save HTML output")
    args = parser.parse_args()

    url = args.url or f"{BASE_URL}/paper-summary/{args.slug}/1"
    asyncio.run(inspect(url, args.output))


if __name__ == "__main__":
    main()
