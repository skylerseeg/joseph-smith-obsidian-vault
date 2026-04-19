#!/usr/bin/env python3
"""
Phase 4 — Index & Cross-Link Updates

After all notes are generated, this script:
1. Scans all JSPP notes for people mentioned
2. Adds JSPP source backlinks to matching person notes in the vault
3. Updates Sources MOC.md with a JSPP section
4. Updates the Master MOC with JSPP integration status
5. Generates a People-to-JSPP index file

Usage:
    python 04_build_indexes.py
    python 04_build_indexes.py --dry-run
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from config import RAW_DIR, VAULT_JSPP_DIR, VAULT_ROOT

console = Console()

PEOPLE_DIR = VAULT_ROOT / "people"
SOURCES_MOC = VAULT_ROOT / "sources" / "Sources MOC.md"
MASTER_MOC = VAULT_ROOT / "000 - Joseph Smith Jr - Master MOC.md"


# ── Name normalization ────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace."""
    return re.sub(r"[^\w\s]", "", name.lower()).strip()


def build_person_note_index() -> dict[str, Path]:
    """
    Return a dict mapping normalized names to their vault note paths.
    Searches all person notes across people/ subdirectories.
    """
    index: dict[str, Path] = {}
    for note_path in PEOPLE_DIR.rglob("*.md"):
        stem = note_path.stem  # filename without extension
        index[normalize_name(stem)] = note_path
    return index


# ── JSPP note scanning ────────────────────────────────────────────────────────

def scan_jspp_notes() -> dict[str, list[str]]:
    """
    Scan all generated JSPP notes and return a mapping of
    person_name -> [list of JSPP note filenames that mention them].
    """
    person_to_notes: dict[str, list[str]] = defaultdict(list)

    for raw_path in sorted(RAW_DIR.glob("*.json")):
        try:
            doc = json.loads(raw_path.read_text())
        except Exception:
            continue

        note_filename = f"JSPP - {doc.get('series', 'unknown')} - {raw_path.stem}.md"
        # Find corresponding vault note
        jspp_note = None
        for p in VAULT_JSPP_DIR.glob("*.md"):
            if raw_path.stem in p.name:
                jspp_note = p.name
                break

        ref = jspp_note or note_filename
        for person in doc.get("people", []):
            person_to_notes[person].append(ref)

    return dict(person_to_notes)


# ── Person note updating ──────────────────────────────────────────────────────

JSPP_SECTION_MARKER = "<!-- JSPP-SOURCES -->"
JSPP_SECTION_END = "<!-- /JSPP-SOURCES -->"


def build_jspp_section(person: str, note_refs: list[str]) -> str:
    """Build the JSPP sources section to append to a person note."""
    lines = [
        "",
        "---",
        "",
        f"## JSPP Sources ({len(note_refs)} document{'s' if len(note_refs) != 1 else ''})",
        "",
        f"*{person} appears in the following Joseph Smith Papers documents:*",
        "",
    ]
    for ref in sorted(note_refs)[:20]:  # Cap at 20 to avoid enormous notes
        stem = ref.replace(".md", "")
        lines.append(f"- [[{stem}]]")
    if len(note_refs) > 20:
        lines.append(f"- *…and {len(note_refs) - 20} more (see [[Sources MOC]])*")
    lines.append("")
    return "\n".join(lines)


def update_person_note(note_path: Path, person: str, note_refs: list[str], dry_run: bool) -> bool:
    """
    Append or replace the JSPP sources section in a person note.
    Returns True if the note was modified.
    """
    content = note_path.read_text(encoding="utf-8")

    new_section = (
        f"{JSPP_SECTION_MARKER}"
        + build_jspp_section(person, note_refs)
        + f"{JSPP_SECTION_END}\n"
    )

    # Remove existing section if present
    if JSPP_SECTION_MARKER in content:
        pattern = re.compile(
            re.escape(JSPP_SECTION_MARKER) + r".*?" + re.escape(JSPP_SECTION_END) + r"\n?",
            re.DOTALL,
        )
        new_content = pattern.sub(new_section, content)
    else:
        new_content = content.rstrip() + "\n\n" + new_section

    if new_content == content:
        return False

    if not dry_run:
        note_path.write_text(new_content, encoding="utf-8")
    return True


# ── Sources MOC update ────────────────────────────────────────────────────────

def update_sources_moc(total_jspp_notes: int, dry_run: bool) -> None:
    if not SOURCES_MOC.exists():
        console.print(f"[yellow]Sources MOC not found at {SOURCES_MOC}[/]")
        return

    content = SOURCES_MOC.read_text(encoding="utf-8")
    jspp_section = f"""
---

## Joseph Smith Papers Project (JSPP)

*Scraped and integrated: {date.today().isoformat()} — {total_jspp_notes} documents*

**Browse JSPP Notes:**
- [[JSPP Scraping Plan]]
- [[Joseph Smith Papers Project - Integration Plan]]

**By Series:**
- [Documents](sources/jspp/) — 15 volumes, 1828–1844
- [Journals](sources/jspp/) — 3 volumes, 1832–1844
- [Histories](sources/jspp/) — 2 volumes
- [Revelations & Translations](sources/jspp/) — 5 volumes
- [Administrative Records](sources/jspp/) — Council of Fifty minutes
- [Legal Records](sources/jspp/) — ~200 cases, 1819–1844
- [Financial Records](sources/jspp/) — Business and financial documents

**Tags:** #source/joseph-smith-papers
"""

    marker = "## Joseph Smith Papers Project"
    if marker in content:
        # Replace existing section (find from marker to next ## or end)
        pattern = re.compile(r"## Joseph Smith Papers Project.*?(?=\n## |\Z)", re.DOTALL)
        new_content = pattern.sub(jspp_section.strip(), content)
    else:
        new_content = content.rstrip() + "\n" + jspp_section

    if not dry_run:
        SOURCES_MOC.write_text(new_content, encoding="utf-8")
        console.print(f"[green]Updated[/] Sources MOC")
    else:
        console.print("[dim]Would update Sources MOC[/]")


# ── People-to-JSPP index ──────────────────────────────────────────────────────

def write_people_jspp_index(person_to_notes: dict[str, list[str]], dry_run: bool) -> None:
    """Write a standalone index note mapping every person to their JSPP appearances."""
    lines = [
        "# JSPP People Index",
        "",
        "**Tags:** #source/joseph-smith-papers #meta/index",
        f"**Generated:** {date.today().isoformat()}",
        "",
        "Index of all people mentioned across JSPP documents in this vault.",
        "",
        "---",
        "",
    ]

    # Sort by number of appearances (most cited first)
    sorted_people = sorted(person_to_notes.items(), key=lambda x: len(x[1]), reverse=True)

    for person, refs in sorted_people:
        lines.append(f"## {person} ({len(refs)} documents)")
        lines.append("")
        for ref in sorted(refs)[:10]:
            stem = ref.replace(".md", "")
            lines.append(f"- [[{stem}]]")
        if len(refs) > 10:
            lines.append(f"- *…{len(refs) - 10} more*")
        lines.append("")

    out_path = VAULT_ROOT / "sources" / "JSPP People Index.md"
    if not dry_run:
        out_path.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"[green]Written[/] {out_path.relative_to(VAULT_ROOT)}")
    else:
        console.print(f"[dim]Would write JSPP People Index ({len(sorted_people)} people)[/]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> None:
    console.print("[bold]Phase 4: Building indexes and cross-links[/]")

    # Build person note index
    person_note_index = build_person_note_index()
    console.print(f"Found {len(person_note_index)} existing person notes in vault")

    # Scan JSPP notes
    person_to_notes = scan_jspp_notes()
    total_jspp_notes = len(list(VAULT_JSPP_DIR.glob("*.md")))
    console.print(f"Found {total_jspp_notes} JSPP notes, {len(person_to_notes)} unique people mentioned")

    # Update person notes
    updated = 0
    no_match = []

    for person, note_refs in sorted(person_to_notes.items()):
        norm = normalize_name(person)

        # Exact match
        if norm in person_note_index:
            note_path = person_note_index[norm]
            if update_person_note(note_path, person, note_refs, dry_run):
                updated += 1
                console.print(f"  [green]Updated[/] {note_path.name} (+{len(note_refs)} JSPP refs)")
        else:
            # Try partial match (last name only)
            last = norm.split()[-1] if norm.split() else norm
            matches = [p for p in person_note_index if last in p.split()]
            if len(matches) == 1:
                note_path = person_note_index[matches[0]]
                if update_person_note(note_path, person, note_refs, dry_run):
                    updated += 1
                    console.print(f"  [yellow]Partial match[/] '{person}' → {note_path.name}")
            else:
                no_match.append(person)

    console.print(f"\nPerson note updates: {updated}")

    # Report unmatched people (candidates for new person notes)
    if no_match:
        console.print(f"\n[yellow]{len(no_match)} people in JSPP not yet in vault:[/]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Person")
        table.add_column("JSPP appearances", justify="right")
        for person in sorted(no_match, key=lambda p: len(person_to_notes[p]), reverse=True)[:30]:
            table.add_row(person, str(len(person_to_notes[person])))
        console.print(table)

    # Update Sources MOC
    update_sources_moc(total_jspp_notes, dry_run)

    # Write People-to-JSPP index
    write_people_jspp_index(person_to_notes, dry_run)

    mode = " (DRY RUN)" if dry_run else ""
    console.print(f"\n[bold green]Phase 4 complete{mode}.[/]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update vault indexes with JSPP cross-links")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
