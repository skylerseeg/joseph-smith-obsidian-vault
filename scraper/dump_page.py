#!/usr/bin/env python3
"""
Diagnostic: dump full rendered HTML of a page to a file for analysis.
Also prints all script tags, embedded JSON, and every unique href pattern.

Usage:
    python dump_page.py                          # dumps documents browse page
    python dump_page.py --url /the-papers/documents
    python dump_page.py --url /reference/calendar-of-documents
    python dump_page.py --url /the-papers/documents/jspd1
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright
from config import BASE_URL, PAGE_LOAD_TIMEOUT, JS_SETTLE_WAIT

ALL_REQUESTS: list[str] = []

async def dump(path: str) -> None:
    url = BASE_URL + path if path.startswith("/") else path
    out_html = Path("dump_output.html")
    out_json = Path("dump_output_scripts.txt")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Capture ALL network requests
        page.on("request", lambda r: ALL_REQUESTS.append(r.url))

        print(f"Loading: {url}")
        try:
            await page.goto(url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT)
        except Exception as e:
            print(f"Warning: {e}")
        await asyncio.sleep(JS_SETTLE_WAIT + 5)

        html = await page.content()
        title = await page.title()
        print(f"Title: {title}")
        print(f"HTML length: {len(html)} chars")

        # Save full HTML
        out_html.write_text(html, encoding="utf-8")
        print(f"\nFull HTML → {out_html}")

        # ── All network requests ───────────────────────────────────────────────
        print(f"\n=== ALL NETWORK REQUESTS ({len(ALL_REQUESTS)}) ===")
        for r in ALL_REQUESTS:
            print(f"  {r}")

        # ── Script tags with substantial content ──────────────────────────────
        script_re = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL)
        scripts = script_re.findall(html)
        big_scripts = [s.strip() for s in scripts if len(s.strip()) > 100]
        print(f"\n=== SCRIPT TAGS WITH CONTENT ({len(big_scripts)}) ===")
        lines = []
        for i, s in enumerate(big_scripts):
            preview = s[:300].replace("\n", " ")
            print(f"\n--- Script {i+1} ({len(s)} chars) ---")
            print(preview)
            lines.append(f"\n--- Script {i+1} ({len(s)} chars) ---\n{s[:2000]}")
        out_json.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nScript contents → {out_json}")

        # ── All unique href patterns ──────────────────────────────────────────
        hrefs = re.findall(r'href="([^"]+)"', html)
        unique_hrefs = sorted(set(hrefs))
        print(f"\n=== ALL UNIQUE HREFS ({len(unique_hrefs)}) ===")
        for h in unique_hrefs[:80]:
            print(f"  {h}")

        # ── Look for paper-summary patterns anywhere in HTML ──────────────────
        ps_matches = re.findall(r'paper-summary[/"\'][^"\'<\s]*', html)
        print(f"\n=== paper-summary occurrences in HTML ({len(ps_matches)}) ===")
        for m in ps_matches[:30]:
            print(f"  {m}")

        # ── Look for Angular state transfer ──────────────────────────────────
        ng_state = re.search(r'id=["\']serverApp-state["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        if ng_state:
            print(f"\n=== Angular SSR State ({len(ng_state.group(1))} chars) ===")
            print(ng_state.group(1)[:1000])

        # ── Look for any JSON-looking embedded data ──────────────────────────
        json_re = re.compile(r'window\.__\w+\s*=\s*(\{.*?\});', re.DOTALL)
        for m in json_re.finditer(html):
            print(f"\n=== window.__ variable ({len(m.group(1))} chars) ===")
            print(m.group(1)[:500])

        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="/the-papers/documents", help="Path or full URL to dump")
    args = parser.parse_args()
    asyncio.run(dump(args.url))
