"""
Configuration for the JSPP scraper.
"""
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
VAULT_ROOT = ROOT.parent / "joseph-smith-vault"

DATA_DIR = ROOT / "data"
SLUGS_DIR = DATA_DIR / "slugs"
RAW_DIR = DATA_DIR / "raw"
NOTES_DIR = DATA_DIR / "notes"
LOGS_DIR = ROOT / "logs"
VAULT_JSPP_DIR = VAULT_ROOT / "sources" / "jspp"

for d in [SLUGS_DIR, RAW_DIR, NOTES_DIR, LOGS_DIR, VAULT_JSPP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Site ───────────────────────────────────────────────────────────────────────
BASE_URL = "https://www.josephsmithpapers.org"

# Browse index URL for each series (confirmed from site navigation)
SERIES_BROWSE_URLS = {
    "documents":               f"{BASE_URL}/the-papers/documents",
    "journals":                f"{BASE_URL}/the-papers/journals",
    "histories":               f"{BASE_URL}/the-papers/histories",
    "revelations":             f"{BASE_URL}/the-papers/revelations-and-translations",
    "administrative-records":  f"{BASE_URL}/the-papers/administrative-records",
    "legal-records":           f"{BASE_URL}/the-papers/legal-records",
    "financial-records":       f"{BASE_URL}/the-papers/financial-records",
}

# Series abbreviations used in note filenames
SERIES_ABBREV = {
    "documents":               "Docs",
    "journals":                "Journal",
    "histories":               "History",
    "revelations":             "Rev",
    "administrative-records":  "Admin",
    "legal-records":           "Legal",
    "financial-records":       "Fin",
}

# Tags per series
SERIES_TAGS = {
    "documents":               "#jspp/documents",
    "journals":                "#jspp/journals",
    "histories":               "#jspp/histories",
    "revelations":             "#jspp/revelations",
    "administrative-records":  "#jspp/administrative-records",
    "legal-records":           "#jspp/legal",
    "financial-records":       "#jspp/financial",
}

# ── High-priority document slugs ──────────────────────────────────────────────
# Scrape these first before the full crawl.
PRIORITY_SLUGS = [
    "discourse-29-august-1843",
    "letter-to-the-church-16-december-1838",
    "revelation-12-july-1843-d-c-132",
    "nauvoo-city-council-rough-minute-book-june-1844",
    "council-of-fifty-minutes-march-1844-january-1846",
    "history-1834-1836",
    "history-circa-1841",
    "journal-1832-1834",
    "journal-december-1842-june-1844-book-1",
]

# ── Request settings ───────────────────────────────────────────────────────────
REQUEST_DELAY_MIN = 2.0   # seconds
REQUEST_DELAY_MAX = 4.0   # seconds
PAGE_LOAD_TIMEOUT = 30000  # ms (Playwright)
HEADLESS = True            # Set False to watch the browser

# ── Logging ────────────────────────────────────────────────────────────────────
SCRAPE_LOG = LOGS_DIR / "scrape.log"
ERROR_LOG   = LOGS_DIR / "errors.log"
