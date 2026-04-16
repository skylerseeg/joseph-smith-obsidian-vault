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
from pathlib import Path

from jinja2 import Environment, BaseLoader
from rich.console import Console
from tqdm import tqdm

from config import (
    RAW_DIR,
    NOTES_DIR,
    VAULT_JSPP_DIR,
    SERIES_ABBREV,
    SERIES_TAGS,
)

console = Console()

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

def make_filename(doc: dict) -> str:
    """Generate vault note filename from document data."""
    series = doc.get("series", "unknown")
    abbrev = SERIES_ABBREV.get(series, series.capitalize()[:5])

    # Normalize date to YYYY-MM-DD or YYYY
    date_str = doc.get("date", "")
    m = re.search(r"(\d{4})[^\d]*(\d{1,2})?[^\d]*(\d{1,2})?", date_str or "")
    if m:
        y = m.group(1)
        mo = m.group(2) or "00"
        d = m.group(3) or "00"
        date_part = f"{y}-{int(mo):02d}-{int(d):02d}" if mo != "00" else y
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

**Tags:** #source/joseph-smith-papers {{ series_tag }}{% if era_tag %} {{ era_tag }}{% endif %}
**Date:** {{ date or "Unknown" }}
**Series:** {{ series_display }}{% if volume %}, {{ volume }}{% endif %}
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


def render_note(doc: dict) -> str:
    env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)
    tmpl = env.from_string(NOTE_TEMPLATE)

    series = doc.get("series", "unknown")
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

    # Generate a brief 1-line summary from transcript
    transcript = doc.get("transcript", "")
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
        source_note=doc.get("source_note", ""),
        footnotes=doc.get("footnotes", []),
        related_slugs=doc.get("related_slugs", []),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, single_slug: str | None = None) -> None:
    raw_files: list[Path]
    if single_slug:
        raw_files = [RAW_DIR / f"{single_slug}.json"]
    else:
        raw_files = sorted(RAW_DIR.glob("*.json"))

    if not raw_files:
        console.print("[red]No scraped JSON files found. Run 02_scrape_documents.py first.[/]")
        return

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

        filename = make_filename(doc)
        note_content = render_note(doc)

        staging_path = NOTES_DIR / filename
        vault_path = VAULT_JSPP_DIR / filename

        if vault_path.exists() and not dry_run:
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
    args = parser.parse_args()
    main(dry_run=args.dry_run, single_slug=args.slug)
