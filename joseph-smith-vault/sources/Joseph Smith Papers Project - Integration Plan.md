# 📚 Joseph Smith Papers Project — Integration Plan

**Tags:** #source/joseph-smith-papers
**Status:** Phase 2 — Not yet loaded
**URL:** https://josephsmithpapers.org

---

## Overview

The Joseph Smith Papers Project (JSPP) is the most comprehensive documentary edition of Joseph Smith's personal and administrative papers ever compiled. Published by the Church Historian's Press (an imprint of the LDS Church), it represents decades of archival work and is considered authoritative by both LDS and non-LDS historians.

---

## What the JSPP Contains

The project is organized into several series:

### Documents Series
Primary correspondence, legal documents, discourse records, and administrative papers. Organized chronologically.

Key volumes for this vault:
- **Documents Vol. 1** — July 1828–June 1831 (Book of Mormon period)
- **Documents Vol. 2** — July 1831–January 1833 (early Ohio)
- **Documents Vol. 3** — February–March 1833 (Kirtland revelations)
- **Documents Vol. 4** — April–September 1833
- **Documents Vol. 5** — October 1835–January 1838
- **Documents Vol. 6** — February 1838–August 1839 (Missouri War + Liberty Jail)
- **Documents Vol. 7** — September 1839–January 1841 (early Nauvoo)
- **Documents Vol. 8** — February–November 1841
- **Documents Vol. 9** — December 1841–April 1842
- **Documents Vol. 10** — May–August 1842
- **Documents Vol. 11** — September 1842–February 1843
- **Documents Vol. 12** — March–July 1843
- **Documents Vol. 13** — August–December 1843 *(includes the David Nye White interview)*
- **Documents Vol. 14** — January–April 1844
- **Documents Vol. 15** — May–June 1844 (final months)

### Journals Series
Smith's personal journals, 1832–1844. Three volumes.

### Histories Series
The various drafts of Smith's official autobiography / "History of the Church."

### Revelations and Translations Series
The manuscripts underlying the Doctrine & Covenants, Book of Mormon, and other scriptural texts.

### Administrative Records Series
Minutes of councils, financial records, membership records.

### Legal Records Series
Court documents, legal correspondence.

### Council of Fifty Minutes
Published 2016 — the first comprehensive release of the Council of Fifty records.

---

## Integration Strategy for This Vault

When loading JSPP content, recommended structure:

### Per-Document Notes
Create individual notes in `/sources/jspp/` with naming convention:
```
JSPP - [Series] - [Date] - [Brief Description].md
```

Example:
```
JSPP - Documents - 1843-08-29 - David Nye White Interview.md
```

### Tagging Schema
```
#source/joseph-smith-papers
#jspp/documents
#jspp/journals  
#jspp/histories
#jspp/revelations
#jspp/legal
#jspp/council-of-fifty
```

### Cross-Linking Protocol
Each JSPP note should link to:
1. The relevant person note(s)
2. The relevant event note(s)
3. The relevant theme MOC(s)
4. The existing Gemini research notes that reference the document

---

## Priority Documents for Phase 2 Loading

Based on the current vault's coverage, highest-priority JSPP documents:

| Priority | Document | Vault Notes it Enriches |
|---|---|---|
| 1 | David Nye White Interview (Aug 29, 1843) | [[David Nye White]], [[Media MOC]] |
| 2 | Council of Fifty Minutes (1844) | [[Council of Fifty]], [[Politics MOC]] |
| 3 | Liberty Jail Epistles (Dec 1838–Mar 1839) | [[Liberty Jail]], [[Legal MOC]] |
| 4 | Plural Marriage Revelation Record (May 1843) | [[Polygamy MOC]], [[William Clayton]] |
| 5 | 1826 Trial Records | [[Legal MOC]] |
| 6 | Boggs Extradition Trial Report (Jan 1843) | [[Justin Butterfield]], [[Nathaniel Pope]] |
| 7 | Nauvoo Expositor Proceedings (June 1844) | [[Nauvoo Expositor]] |
| 8 | Carthage Trial Account (May 1845) | [[1845 Carthage Conspiracy Trial]] |

---

## Notes on Source Quality

The JSPP employs professional historical editors and uses archival standards. Documents are presented in original spelling with editorial notes. Key quality indicators:
- Full transcription of original manuscripts
- Extensive footnotes identifying people, places, and events
- Biographical register of all mentioned individuals
- Thorough cross-referencing

This makes JSPP notes ideal candidates for the "people" notes in this vault — each JSPP biographical entry can supplement or replace the current person notes with documented archival sourcing.

---

## Related Notes
- [[000 - Joseph Smith Jr - Master MOC]]
- [[Sources MOC]]
- [[The Prophetic Circle]]
- [[The Media the Law and the Prophet]]
