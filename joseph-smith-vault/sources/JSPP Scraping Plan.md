# 🗂️ Joseph Smith Papers Project — Scraping & Integration Plan

**Tags:** #source/joseph-smith-papers #meta/scraping-plan
**Status:** Active — See `/scraper/` directory for implementation
**Last Updated:** 2026-04-16

---

## Overview

This document is the authoritative plan for collecting all data from the Joseph Smith Papers Project (JSPP) at `josephsmithpapers.org` and integrating it into this Obsidian vault.

The JSPP is the most comprehensive documentary edition of Joseph Smith's papers ever compiled. The digital collection contains approximately **2,500 original documents** (from a control file of ~10,000 items counting all copies/versions) across **27 print volumes** and **2 online-only series**, completed in 2023.

---

## Collection Scope

### Series & Volume Inventory

| Series | Volumes | Date Range | Documents |
|---|---|---|---|
| **Documents** | 15 vols (D1–D15) | 1828–1844 | ~1,300+ items |
| **Journals** | 3 vols (J1–J3) | 1832–1844 | 1,306 journal entries |
| **Histories** | 2 vols (H1–H2) | Various | Multiple draft histories |
| **Revelations & Translations** | 5 vols (RT1–RT5) | Various | 155+ revelations |
| **Administrative Records** | 1 vol (AR1) | 1844–1846 | Council of Fifty minutes |
| **Legal Records** | Online only | 1819–1844 | ~200 case introductions |
| **Financial Records** | Online only | Various | Financial documents |

**Total estimated documents: ~2,500 originals; ~10,000 items including copies**

### Document Types Within Each Series

- **Documents series:** Letters, revelations, discourse records, legal documents, licenses, architectural plans, minutes, newspaper articles
- **Journals:** Daily journal entries with dates, locations, people mentioned, and activities
- **Histories:** Multiple draft versions of Smith's autobiography and church history
- **Revelations & Translations:** Original manuscripts of the Doctrine & Covenants, Book of Mormon translation documents, Book of Abraham
- **Administrative Records:** Council of Fifty meeting minutes (March 1844–January 1846)
- **Legal Records:** Case introductions for ~200 legal proceedings
- **Financial Records:** Business records, land transactions, financial accounts

---

## Website Structure

### URL Patterns

```
# Main browse pages
https://josephsmithpapers.org/the-papers
https://josephsmithpapers.org/the-papers/documents
https://josephsmithpapers.org/the-papers/journals
https://josephsmithpapers.org/the-papers/histories
https://josephsmithpapers.org/the-papers/revelations-and-translations
https://josephsmithpapers.org/the-papers/administrative-records
https://josephsmithpapers.org/the-papers/legal-records
https://josephsmithpapers.org/the-papers/financial-records

# Individual document viewer
https://josephsmithpapers.org/paper-summary/{document-slug}/{page-number}

# Example documents
https://josephsmithpapers.org/paper-summary/journal-1832-1834/1
https://josephsmithpapers.org/paper-summary/invoice-from-martin-birge-17-june-1836/1
https://josephsmithpapers.org/paper-summary/history-1834-1836/125

# Series index pages
https://josephsmithpapers.org/the-papers/documents/jspd1     (Documents Vol. 1)
https://josephsmithpapers.org/the-papers/journals/jspj1      (Journals Vol. 1)
https://josephsmithpapers.org/the-papers/revelations-and-translations/jsppr5
```

### Page Structure Per Document

Each `paper-summary` page contains:
- **Document metadata:** Title, date, location, document type, series/volume
- **Transcript pane:** Transcribed text with editorial markup
- **Source notes:** Physical description, archival location, provenance
- **Footnotes:** Contextual annotations identifying people, places, events
- **Facsimile images:** High-resolution scans of original manuscripts
- **Related documents:** Links to connected items
- **People/places index:** Tagged entities within the document

### Technical Notes

- The site runs a JavaScript-heavy SPA (Angular/React). Static HTML fetching (requests/BeautifulSoup) will not work for most content.
- The site blocks simple HTTP requests with 403 errors (User-Agent filtering).
- JavaScript rendering via Playwright or Selenium is required.
- The site may have an internal JSON API; network inspection during browser sessions can reveal endpoints.
- Rate limiting: be respectful — use 2–5 second delays between requests.

---

## Data Model

### Per-Document Fields to Collect

```python
{
    "slug": str,           # URL slug (unique ID)
    "title": str,          # Document title
    "date": str,           # ISO date or date range
    "series": str,         # e.g. "Documents", "Journals"
    "volume": str,         # e.g. "Volume 1", "jspd1"
    "doc_type": str,       # Letter, Revelation, Journal Entry, etc.
    "location": str,       # Geographic location of creation
    "people": list[str],   # People mentioned/involved
    "transcript": str,     # Full transcribed text
    "source_note": str,    # Physical description and archive location
    "footnotes": list[dict], # [{number, text, people, places}]
    "images": list[str],   # URLs to facsimile images
    "related": list[str],  # Slugs of related documents
    "url": str,            # Canonical URL
    "scraped_at": str,     # ISO datetime of scrape
}
```

### Vault Note Structure

Each scraped document becomes one Obsidian note under `/sources/jspp/` using the naming convention from the existing integration plan:

```
JSPP - [Series Abbrev] - [YYYY-MM-DD] - [Brief Title].md
```

Examples:
```
JSPP - Documents - 1843-08-29 - David Nye White Interview.md
JSPP - Journals - 1838-03-20 - Journal Entry Liberty Jail.md
JSPP - Legal - 1826-03-20 - Glass-Looking Trial.md
JSPP - CoFifty - 1844-03-11 - Council of Fifty Minutes.md
```

---

## Implementation Architecture

### Directory Structure

```
scraper/
├── README.md                    # Setup and usage instructions
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration (delays, paths, series list)
├── 01_discover_slugs.py         # Phase 1: Build master list of all document slugs
├── 02_scrape_documents.py       # Phase 2: Scrape each document's full content
├── 03_build_notes.py            # Phase 3: Convert scraped JSON to Obsidian notes
├── 04_build_indexes.py          # Phase 4: Update MOC files and people notes
├── data/
│   ├── slugs/                   # Per-series slug lists (JSON)
│   ├── raw/                     # Raw scraped JSON per document
│   └── notes/                   # Generated Obsidian markdown notes
└── logs/
    ├── scrape.log               # Scraping progress log
    └── errors.log               # Failed requests for retry
```

### Technology Stack

| Tool | Purpose |
|---|---|
| **Python 3.11+** | Primary language |
| **Playwright** | JavaScript-rendering browser automation |
| **BeautifulSoup4** | HTML parsing of rendered pages |
| **httpx** | Async HTTP client for any JSON API endpoints |
| **tqdm** | Progress bars |
| **rich** | Console output formatting |
| **pydantic** | Data validation for scraped records |
| **jinja2** | Templating for Obsidian note generation |

---

## Phased Execution Plan

### Phase 1 — Slug Discovery (Est. 1–2 hours)

**Goal:** Build a complete list of every document URL slug in the collection.

**Method:**
1. Use Playwright to browse each series index page
2. Extract all document links from the browse/index pages
3. Follow pagination through all pages
4. Save slug lists to `data/slugs/{series}.json`

**Output:** `data/slugs/` directory with JSON files per series totaling ~2,500 slugs

**Script:** `scraper/01_discover_slugs.py`

### Phase 2 — Document Scraping (Est. 8–24 hours)

**Goal:** Scrape full content for every document.

**Method:**
1. Load slug list from Phase 1
2. For each slug, load `paper-summary/{slug}/1` in Playwright
3. Wait for JavaScript to render
4. Parse and extract all fields (title, date, transcript, footnotes, images, etc.)
5. Save raw JSON to `data/raw/{slug}.json`
6. Log progress; skip already-scraped slugs on restart

**Rate limiting:** 2–3 second delay between requests, randomized
**Concurrency:** Single browser, sequential (to respect the server)

**Script:** `scraper/02_scrape_documents.py`

### Phase 3 — Note Generation (Est. 30 minutes)

**Goal:** Convert all raw JSON files into Obsidian markdown notes.

**Method:**
1. Load each `data/raw/{slug}.json`
2. Apply naming convention and tagging schema
3. Generate cross-links to existing vault people/event/theme notes
4. Write `.md` files to `data/notes/` then copy to vault `/sources/jspp/`

**Script:** `scraper/03_build_notes.py`

### Phase 4 — Index Updates (Est. 15 minutes)

**Goal:** Update MOC files and enhance existing person notes with JSPP cross-links.

**Method:**
1. Scan all generated JSPP notes for `people` fields
2. Match against existing vault person notes (fuzzy name matching)
3. Append JSPP source references to relevant person notes
4. Update `Sources MOC.md` with JSPP section
5. Update `000 - Joseph Smith Jr - Master MOC.md` with JSPP integration status

**Script:** `scraper/04_build_indexes.py`

---

## Priority Documents

Pull these specific documents first in Phase 2 (before full crawl):

| Priority | Slug (approximate) | Vault Notes Enriched |
|---|---|---|
| 1 | `discourse-29-august-1843` | [[David Nye White]], [[Media MOC]] |
| 2 | `council-of-fifty-minutes-1844-*` | [[Council of Fifty]], [[Politics MOC]] |
| 3 | `letter-to-church-december-1838` | [[Liberty Jail]], [[Legal MOC]] |
| 4 | `revelation-12-july-1843` | [[Polygamy MOC]], [[William Clayton]] |
| 5 | `state-of-ohio-v-joseph-smith-1826` | [[Legal MOC]] |
| 6 | `united-states-v-joseph-smith-1843` | [[Justin Butterfield]], [[Nathaniel Pope]] |
| 7 | `nauvoo-city-council-minutes-june-1844` | [[Nauvoo Expositor]] |
| 8 | `trial-of-the-murderers-of-joseph-1845` | [[1845 Carthage Conspiracy Trial]] |

---

## Obsidian Note Template

Each generated note follows this template:

```markdown
# JSPP — [Document Title]

**Tags:** #source/joseph-smith-papers #jspp/[series] #era/[era]
**Date:** [YYYY-MM-DD]
**Series:** [Series Name], [Volume]
**Document Type:** [Letter / Journal Entry / Revelation / Minutes / etc.]
**Location:** [Place of Creation]
**Source URL:** [canonical URL]
**Scraped:** [date]

---

## Summary

[1–2 sentence summary of document content]

---

## People Mentioned

- [[Person Name]] — [role in document]
- [[Person Name]] — [role in document]

---

## Full Transcript

> [Transcribed text, preserving original spelling per JSPP editorial method]

---

## Source Note

[Physical description, archival location, provenance]

---

## Footnotes

**[1]** [Footnote text]
**[2]** [Footnote text]

---

## Related Documents

- [[JSPP - [Series] - [Date] - [Title]]]

---

## Vault Cross-Links

- [[Relevant Event Note]]
- [[Relevant Theme MOC]]
- [[Relevant Person Note]]
```

---

## Ethical & Legal Considerations

1. **Personal use only** — this vault is a private research tool, not a redistribution platform
2. **Rate limiting** — always add delays; never hammer the server
3. **Respect robots.txt** — verify current state before running at scale
4. **Image handling** — download facsimile images only for personal archival use; do not redistribute
5. **Attribution** — all notes must cite the JSPP canonical URL as source
6. **No redistribution** — scraped content stays within this private vault

The JSPP content is published by the Church Historian's Press. For bulk data access or research partnerships, consider contacting them directly at josephsmithpapers.org/articles/contact.

---

## Setup Instructions

See `../../scraper/README.md` for complete setup and execution instructions.

---

## Related Notes

- [[Joseph Smith Papers Project - Integration Plan]]
- [[Sources MOC]]
- [[000 - Joseph Smith Jr - Master MOC]]
- [[Timeline MOC]]
