# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

The repo mixes two distinct products that share a filesystem:

- **`joseph-smith-vault/`** — An Obsidian vault of research notes on Joseph Smith Jr. (MOCs, person notes under `people/{allies,foes,legal,media,political}/`, and scraped sources under `sources/jspp/`). The root MOC is `000 - Joseph Smith Jr - Master MOC.md`.
- **`scraper/`** — A Python pipeline that scrapes josephsmithpapers.org and writes markdown notes into `joseph-smith-vault/sources/jspp/`. The scraper is the only code in the repo; everything else is markdown content.
- **`Joseph Smith Jr/`** — A second, effectively empty Obsidian vault (only `.obsidian/` config and an empty canvas). Ignore unless you are explicitly asked about it.

The scraper and the vault are coupled: `scraper/config.py` computes `VAULT_ROOT = scraper/../joseph-smith-vault` and writes notes directly into `sources/jspp/` there. Moving or renaming either top-level directory will break phase 3 and phase 4.

## Scraper Pipeline

The scraper is a 4-phase pipeline under `scraper/`. Each phase is a standalone CLI script; run them in order. See `scraper/README.md` for the canonical quick-start.

```bash
cd scraper
pip install -r requirements.txt       # httpx, tqdm, rich, pydantic, jinja2, python-slugify
python 01_discover_slugs.py           # writes data/slugs/{series}.json + master.json
python 02_scrape_documents.py         # writes data/raw/{slug}.json (long-running)
python 03_build_notes.py              # renders data/notes/ + copies to vault sources/jspp/
python 04_build_indexes.py            # updates people/ notes, Sources MOC, writes JSPP People Index
```

Common flags:

- `01_discover_slugs.py --series journals histories` — limit discovery; `--reset` deletes existing slug files; `--test` dumps `__NEXT_DATA__` for inspection.
- `02_scrape_documents.py --priority-only` — scrape `PRIORITY_SERIES` (journals/histories/revelations/administrative-records) + `PRIORITY_SLUGS` first before the big `documents` series.
- `02_scrape_documents.py --slug <slug>` — scrape one document.
- `02_scrape_documents.py --test --slug <slug>` — print parsed structure without saving.
- `03_build_notes.py --dry-run` / `--slug <slug>` — preview filenames or rebuild one note.
- `04_build_indexes.py --dry-run` — preview person-note updates and index changes.

Phase 2 is resumable: any slug with an existing `data/raw/{slug}.json` is skipped. To re-scrape, delete that file. Phase 3 similarly skips files that already exist in `sources/jspp/` — delete the vault file to regenerate. Failed fetches go to `logs/errors.log`; re-running picks them up.

There is no test suite, no linter config, and no build step. "Run one test" means `--test` on the relevant phase script.

## Scraper Architecture

The site is Next.js with SSR. Every page embeds its full data in a `<script id="__NEXT_DATA__" type="application/json">` tag; the scraper fetches HTML via `httpx` and extracts that JSON — no browser, no Playwright. The `NEXT_DATA_RE` regex and `extract_next_data` helper are duplicated in phases 1 and 2; keep them in sync if the site changes its markup.

Phase 1 (`01_discover_slugs.py`) recursively walks `__NEXT_DATA__` JSON and raw HTML hrefs to collect every `/paper-summary/<slug>` URL. It handles series → year/volume sub-pages → (for legal/financial) case-page sub-pages via a depth-aware BFS queue (max depth 2). It also paginates (`?page=N`) until a page yields zero new slugs. Per-series results land in `data/slugs/{series}.json`; a merged `master.json` is `[{series, slug}, ...]`.

Phase 2 (`02_scrape_documents.py`) reads `master.json`, fetches page 1 of each slug, and parses via `parse_document`. The parser assumes this `pageProps` shape:

- `summary.documentSeriesTitle` / `editorialTitle` → title
- `summary.expandedText` (preferred) or `clearText` → transcript HTML (stripped via `_TextExtractor`)
- `summary.historicalIntro` → `source_note`
- `summary.footnotes` → `footnotes`
- `gallery` → page count and image URLs (prepended with `CDN_IMAGE_BASE`)
- `tableOfContents` → date range (start…end)

Multi-page documents: phase 2 walks pages 2..N and concatenates their transcripts onto page 1's. The output schema is `JSPPDocument` (Pydantic), serialized as `data/raw/{slug}.json`. Phase 2 also stashes the entire raw `__NEXT_DATA__` under `raw_next_data` so you can re-derive fields later without re-scraping.

Rate limiting lives in `config.py` as `REQUEST_DELAY_MIN` / `REQUEST_DELAY_MAX` (default 2–4s). Respect this — the live site is the source of truth and aggressive scraping will get you blocked.

Phase 3 (`03_build_notes.py`) renders a single Jinja2 `NOTE_TEMPLATE` per doc. Two conventions matter:

- **Filename**: `JSPP - {SERIES_ABBREV} - {YYYY[-MM-DD]|undated} - {title trimmed to 8 words}.md`. The date regex in `make_filename` is deliberately conservative about multi-year ranges (`1832–1834` extracts to `1832`).
- **Era tag**: derived from the first 4-digit year via `ERA_MAP` (new-york / ohio / missouri / nauvoo / post-martyrdom). The tag is appended to the note's frontmatter-style header alongside `SERIES_TAGS[series]`.

Phase 4 (`04_build_indexes.py`) is the cross-linking step. It:

1. Indexes every `.md` file under `joseph-smith-vault/people/**/` by normalized stem (lowercase, punctuation stripped).
2. Rescans `data/raw/*.json` to build `person → [JSPP note filenames]`.
3. For each person matched (exact, then fallback to last-name-only if exactly one match), appends or replaces a `<!-- JSPP-SOURCES --> … <!-- /JSPP-SOURCES -->` block in their person note. The marker pair is how subsequent runs find and replace the block idempotently — don't remove the HTML comments or the section will be duplicated.
4. Rewrites a `## Joseph Smith Papers Project` section in `sources/Sources MOC.md` (pattern-matched and replaced on each run).
5. Writes `sources/JSPP People Index.md` from scratch.

Unmatched people are printed (top 30 by JSPP appearance count) as candidates for new person notes — these are a signal for the vault author, not an error.

## Vault Conventions

When editing or creating vault notes (not scraped ones), follow the tag vocabulary declared in the Master MOC:

```
#person/ally  #person/foe  #person/neutral
#role/scribe  #role/lawyer  #role/editor  #role/apostle  #role/politician
#era/new-york  #era/ohio  #era/missouri  #era/nauvoo
#theme/law  #theme/media  #theme/polygamy  #theme/economics  #theme/politics
#source/gemini-research  #source/joseph-smith-papers
```

Person notes live under `people/{allies,foes,legal,media,political}/<Full Name>.md`. The filename stem is what phase 4 matches against `people[]` in scraped JSON — renaming a person file breaks its JSPP backlinks until phase 4 reruns. Person notes typically end with a "Related Notes" section of `[[wiki-links]]`; if you add a new person, place them in a subdirectory that matches their category.

Obsidian uses wiki-links (`[[Note Name]]`), not relative markdown links. Preserve that syntax.

## Editing the Scraper

- The `__NEXT_DATA__` extraction and `SLUG_RE` regexes appear in both `01_discover_slugs.py` and `02_scrape_documents.py`. Keep them consistent.
- Field parsing in `parse_document` is defensive by design (every key has a fallback chain) because the Next.js schema varies across series. Before adding new fields, use `python 02_scrape_documents.py --test --slug <slug>` to confirm the key path exists — the script writes the full JSON to `nextdata_<slug>.json` for inspection.
- `strip_html` must handle str, dict, and list inputs — a prior bug (see `74c2604`) crashed on dict inputs from source-note fields. Don't narrow the signature.
- `config.py` creates output directories on import. Importing it from a new script is the standard way to acquire paths.
- The scraper's `.gitignore` excludes `data/`, `logs/`, and `.venv/` — scraped JSON and logs are not versioned. Generated markdown in `joseph-smith-vault/sources/jspp/` **is** versioned, so phase 3/4 output is the permanent artifact.
