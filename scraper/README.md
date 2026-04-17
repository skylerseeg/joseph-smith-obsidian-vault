# JSPP Scraper

Scrapes the Joseph Smith Papers Project website (`josephsmithpapers.org`) and generates Obsidian markdown notes for every document in the collection (~9,400 documents across 7 series).

## How It Works

The site is built on Next.js with server-side rendering. Every page embeds all its data in a `<script id="__NEXT_DATA__">` JSON tag — no JavaScript execution or browser needed. Scripts fetch pages with `httpx` and extract the embedded JSON directly.

## Prerequisites

- Python 3.11+
- `pip install -r requirements.txt`

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Discover all document slugs (runs in a few minutes)
python 01_discover_slugs.py

# 3. Inspect one document to verify field parsing
python 02_scrape_documents.py --test --slug journal-1832-1834

# 4. Scrape priority documents first (9 key docs, fast)
python 02_scrape_documents.py --priority-only

# 5. Scrape all remaining documents (~8–24 hours)
python 02_scrape_documents.py

# 6. Generate Obsidian notes from scraped JSON
python 03_build_notes.py

# 7. Update vault MOCs and cross-link person notes
python 04_build_indexes.py
```

## Per-Series Discovery

To discover slugs for specific series only:

```bash
python 01_discover_slugs.py --series journals
python 01_discover_slugs.py --series histories revelations
python 01_discover_slugs.py --series administrative-records legal-records financial-records
```

Series names: `documents`, `journals`, `histories`, `revelations`, `administrative-records`, `legal-records`, `financial-records`

## Output

| Path | Contents |
|------|----------|
| `data/slugs/` | JSON slug lists per series (`master.json` = all) |
| `data/raw/` | Scraped JSON per document (one file per slug) |
| `data/notes/` | Generated Obsidian markdown (staging copy) |
| `logs/scrape.log` | Scraping progress and status |
| `logs/errors.log` | Failed requests (re-run to retry) |

Notes are also copied directly to `../joseph-smith-vault/sources/jspp/`.

## Resuming Interrupted Scrapes

Already-scraped documents (existing files in `data/raw/`) are skipped automatically. Re-run `02_scrape_documents.py` to continue where it left off.

## Configuration

Edit `config.py` to adjust request delay, output paths, or priority slugs. Default rate limit: 2–4 seconds between requests (polite crawling).
