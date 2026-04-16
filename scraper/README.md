# JSPP Scraper

Scrapes the Joseph Smith Papers Project website (`josephsmithpapers.org`) and generates Obsidian markdown notes for every document in the collection.

## Prerequisites

- Python 3.11+
- `pip install -r requirements.txt`
- `playwright install chromium`

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Discover all document slugs (~1–2 hours)
python 01_discover_slugs.py

# 3. Scrape all documents (~8–24 hours depending on collection size)
python 02_scrape_documents.py

# To scrape only priority documents first:
python 02_scrape_documents.py --priority-only

# 4. Generate Obsidian notes from scraped JSON
python 03_build_notes.py

# 5. Update vault MOC files and cross-link person notes
python 04_build_indexes.py
```

## Output

- `data/slugs/` — JSON lists of document slugs per series
- `data/raw/` — Raw scraped JSON per document
- `data/notes/` — Generated Obsidian markdown notes
- `logs/scrape.log` — Scraping progress
- `logs/errors.log` — Failed requests (re-run to retry)

Notes are also copied directly to `../joseph-smith-vault/sources/jspp/`.

## Configuration

Edit `config.py` to adjust:
- Request delay (default: 2–4s randomized)
- Output paths
- Which series to scrape
- Browser headless mode

## Resuming Interrupted Scrapes

The scraper tracks progress in `data/raw/`. Already-scraped documents are skipped automatically. Just re-run `02_scrape_documents.py` to continue.
