#!/usr/bin/env python3
"""
Phase 3 — Obsidian Note Generation

Reads every scraped JSON file in data/raw/ and converts it to a formatted
Obsidian markdown note. Notes are written to:
  - data/notes/          (staging area)
  - ../joseph-smith-vault/sources/jspp/  (live vault)

Usage:
    python 03_build_notes.py
    python 03_build_notes.py --dry-run     # Preview only, don't write files
    python 03_build_notes.py --slug journal-1832-1834
"""

import argparse
import json
import re
import shutil
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader
from rich.console import Console
from tqdm import tqdm

from config import (
    RAW_DIR,
    NOTES_DIR,
    SLUGS_DIR,
    VAULT_JSPP_DIR,
    SERIES_ABBREV,
    SERIES_TAGS,
)

console = Console()


# ── HTML stripping ─────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def strip_html(text: Any) -> str:
    """Strip HTML tags from a string (or recursively extract text from dict/list)."""
    if not text:
        return ""
    if isinstance(text, dict):
        return " ".join(strip_html(v) for v in text.values() if v).strip()
    if isinstance(text, list):
        return " ".join(strip_html(i) for i in text if i).strip()
    text = str(text)
    if "<" not in text:
        return text.strip()
    try:
        ex = _TextExtractor()
        ex.feed(text)
        return ex.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", text).strip()


# ── Series resolution ──────────────────────────────────────────────────────────

def load_slug_series_map() -> dict[str, str]:
    """Load master.json to resolve slug → series."""
    master_path = SLUGS_DIR / "master.json"
    if not master_path.exists():
        return {}
    try:
        entries = json.loads(master_path.read_text())
        return {e["slug"]: e["series"] for e in entries if "slug" in e and "series" in e}
    except Exception:
        return {}

# ── Era detection ─────────────────────────────────────────────────────────────

ERA_MAP = [
    ("1805", "1830", "new-york"),
    ("1831", "1838", "ohio"),
    ("1838", "1839", "missouri"),
    ("1839", "1844", "nauvoo"),
    ("1844", "1847", "post-martyrdom"),
]

def detect_era(date_str: str) -> str:
    """Return an era tag based on date string."""
    m = re.search(r"(\d{4})", date_str or "")
    if not m:
        return ""
    year = int(m.group(1))
    for start, end, era in ERA_MAP:
        if int(start) <= year <= int(end):
            return f"#era/{era}"
    return ""


# ── Filename generation ───────────────────────────────────────────────────────

def make_filename(doc: dict, slug_series_map: dict[str, str] | None = None) -> str:
    """Generate vault note filename from document data."""
    series = doc.get("series", "unknown")
    if series in ("priority", "unknown", "") and slug_series_map:
        series = slug_series_map.get(doc.get("slug", ""), series)
    abbrev = SERIES_ABBREV.get(series, series.capitalize()[:5])

    # Normalize date to YYYY-MM-DD or YYYY
    # Match YYYY optionally followed by a 1-2 digit month/day, but stop
    # before another 4-digit year (handles "1832–1834" correctly).
    date_str = doc.get("date", "") or ""
    m = re.search(r"(\d{4})(?:[^\d](\d{1,2})(?:[^\d](\d{1,2})(?!\d))?)?(?!\d)", date_str)
    if m:
        y = m.group(1)
        mo = m.group(2) or "00"
        d_val = m.group(3) or "00"
        # Reject month/day values that look like a year fragment (>12 or >31)
        if mo != "00" and int(mo) > 12:
            mo = "00"
            d_val = "00"
        elif d_val != "00" and int(d_val) > 31:
            d_val = "00"
        date_part = f"{y}-{int(mo):02d}-{int(d_val):02d}" if mo != "00" else y
    else:
        date_part = "undated"

    # Shorten title
    title = doc.get("title", doc.get("slug", "untitled"))
    title_clean = re.sub(r'[\\/:*?"<>|]', "", title)
    title_short = " ".join(title_clean.split()[:8])  # Max 8 words

    return f"JSPP - {abbrev} - {date_part} - {title_short}.md"


# ── Jinja2 note template ──────────────────────────────────────────────────────

NOTE_TEMPLATE = """\
# JSPP — {{ title }}

**Tags:** #source/joseph-smith-papers {{ series_tag }}{{ " " + era_tag if era_tag else "" }}
**Date:** {{ date or "Unknown" }}
**Series:** {{ series_display }}{{ ", " + volume if volume else "" }}
**Document Type:** {{ doc_type or "Document" }}
**Location:** {{ location or "Unknown" }}
**Source URL:** {{ url }}
**Scraped:** {{ scraped_date }}

---

## Summary

{{ summary }}

---
{% if people %}

## People Mentioned

{% for person in people %}
- [[{{ person }}]]
{% endfor %}

---
{% endif %}
{% if places %}

## Places

{% for place in places %}
- {{ place }}
{% endfor %}

---
{% endif %}

## Full Transcript

{% if transcript %}
{{ transcript | indent(2) }}
{% else %}
*Transcript not available — visit source URL above.*
{% endif %}

---

## Source Note

{{ source_note or "*See source URL above for archival details.*" }}

---
{% if footnotes %}

## Footnotes

{% for fn in footnotes %}
**[{{ fn.number }}]** {{ fn.text }}
{% endfor %}

---
{% endif %}
{% if related_slugs %}

## Related Documents

{% for rs in related_slugs[:10] %}
- [[JSPP - {{ rs }}]]
{% endfor %}

---
{% endif %}

## Vault Cross-Links

- [[Joseph Smith Papers Project - Integration Plan]]
- [[Sources MOC]]
"""


def render_note(doc: dict, slug_series_map: dict[str, str] | None = None) -> str:
    env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)
    tmpl = env.from_string(NOTE_TEMPLATE)

    series = doc.get("series", "unknown")
    # Resolve "priority" / "unknown" series via master.json lookup
    if series in ("priority", "unknown", "") and slug_series_map:
        slug = doc.get("slug", "")
        series = slug_series_map.get(slug, series)

    series_tag = SERIES_TAGS.get(series, "#jspp/other")
    era_tag = detect_era(doc.get("date", ""))

    series_display_map = {
        "documents": "Documents Series",
        "journals": "Journals Series",
        "histories": "Histories Series",
        "revelations": "Revelations & Translations Series",
        "administrative-records": "Administrative Records Series",
        "legal-records": "Legal Records Series",
        "financial-records": "Financial Records Series",
    }

    # Strip any residual HTML from transcript and source_note
    transcript = strip_html(doc.get("transcript", ""))
    source_note = strip_html(doc.get("source_note", ""))

    # Generate a brief 1-line summary from transcript
    summary_text = " ".join(transcript.split()[:50]).strip()
    if summary_text and len(transcript.split()) > 50:
        summary_text += "…"
    if not summary_text:
        summary_text = f"*{doc.get('doc_type', 'Document')} from the {series_display_map.get(series, series)} collection.*"

    return tmpl.render(
        title=doc.get("title", doc.get("slug", "Untitled")),
        series_tag=series_tag,
        era_tag=era_tag,
        date=doc.get("date", ""),
        series_display=series_display_map.get(series, series),
        volume=doc.get("volume", ""),
        doc_type=doc.get("doc_type", ""),
        location=doc.get("location", ""),
        url=doc.get("url", ""),
        scraped_date=str(date.today()),
        summary=summary_text,
        people=doc.get("people", []),
        places=doc.get("places", []),
        transcript=transcript,
        source_note=source_note,
        footnotes=doc.get("footnotes", []),
        related_slugs=doc.get("related_slugs", []),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, single_slug: str | None = None, force: bool = False) -> None:
    raw_files: list[Path]
    if single_slug:
        raw_files = [RAW_DIR / f"{single_slug}.json"]
    else:
        raw_files = sorted(RAW_DIR.glob("*.json"))

    if not raw_files:
        console.print("[red]No scraped JSON files found. Run 02_scrape_documents.py first.[/]")
        return

    slug_series_map = load_slug_series_map()
    console.print(f"Generating notes for {len(raw_files)} documents…")

    generated = 0
    skipped = 0
    errors = 0

    for raw_path in tqdm(raw_files, desc="Building notes"):
        try:
            doc = json.loads(raw_path.read_text())
        except Exception as e:
            console.print(f"[red]Failed to parse {raw_path.name}: {e}[/]")
            errors += 1
            continue

        filename = make_filename(doc, slug_series_map)
        note_content = render_note(doc, slug_series_map)

        staging_path = NOTES_DIR / filename
        vault_path = VAULT_JSPP_DIR / filename

        if vault_path.exists() and not dry_run and not force:
            skipped += 1
            continue

        if dry_run:
            console.print(f"[dim]Would write:[/] {filename}")
            generated += 1
            continue

        # Write to staging
        staging_path.write_text(note_content, encoding="utf-8")
        # Copy to vault
        shutil.copy2(staging_path, vault_path)
        generated += 1

    mode = " (DRY RUN)" if dry_run else ""
    console.print(
        f"\n[bold green]Done{mode}.[/] "
        f"Generated: {generated}  Skipped (existing): {skipped}  Errors: {errors}"
    )
    if not dry_run:
        console.print(f"Notes written to:\n  {NOTES_DIR}\n  {VAULT_JSPP_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Obsidian notes from scraped JSPP data")
    parser.add_argument("--dry-run", action="store_true", help="Preview filenames without writing")
    parser.add_argument("--slug", help="Generate note for a single slug only")
    parser.add_argument("--force", action="store_true", help="Overwrite existing notes")
    args = parser.parse_args()
    main(dry_run=args.dry_run, single_slug=args.slug, force=args.force)
