# Role A (Data & Retrieval) Implementation Report

**Date:** 2026-04-11  
**Role:** Role A (Data & Retrieval)  
**Assignee:** Ella Lu  

---

## Overview

Role A is responsible for the complete data ingestion and retrieval pipeline: scraping official Canadian immigration webpages, cleaning and chunking content, enriching with structured metadata, and serving hybrid-ranked retrieval results with citation traceability.

---

## Source URL Registry

All sources are curated in `data/sources/url_registry.json`. Each entry includes: `id`, `page`, `url`, `priority` (P0/P1/P2), `province`, `program`, `stream`, `source_type`, `verified`, and `verified_at`. All URLs were verified accessible on 2026-04-09.

### P0 — Core Sources (11)

| # | ID | Page | URL | Program | Province |
|---|------|------|-----|---------|----------|
| 1 | ircc-homepage | IRCC homepage | https://www.canada.ca/en/immigration-refugees-citizenship.html | IRCC | — |
| 2 | ee-overview | Express Entry overview | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry.html | Express Entry | — |
| 3 | crs-criteria | CRS scoring criteria | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score/crs-criteria.html | Express Entry | — |
| 4 | fsw | Federal Skilled Worker Program | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/federal-skilled-workers.html | Express Entry | — |
| 5 | cec | Canadian Experience Class | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/canadian-experience-class.html | Express Entry | — |
| 6 | language-requirements | Language requirements | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/language-requirements.html | Express Entry | — |
| 7 | oinp-homepage | OINP homepage | https://www.ontario.ca/page/ontario-immigrant-nominee-program-oinp | OINP | Ontario |
| 8 | oinp-hcp | OINP Human Capital Priorities Stream | https://www.ontario.ca/page/oinp-human-capital-priorities-stream | OINP | Ontario |
| 9 | oinp-masters | OINP Masters Graduate Stream | https://www.ontario.ca/page/oinp-masters-graduate-stream | OINP | Ontario |
| 10 | oinp-phd | OINP PhD Graduate Stream | https://www.ontario.ca/page/oinp-phd-graduate-stream | OINP | Ontario |
| 11 | oinp-streams | OINP Streams Overview | https://www.ontario.ca/page/ontario-immigrant-nominee-program-streams | OINP | Ontario |

### P1 — Extended Sources (29)

| # | ID | Page | URL | Program | Province |
|---|------|------|-----|---------|----------|
| 12 | fst | Federal Skilled Trades Program | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply/federal-skilled-trades.html | Express Entry | — |
| 13 | noc-finder | Find your NOC | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/find-national-occupation-code.html | Express Entry | — |
| 14 | ee-rounds | Rounds of invitations (draw history) | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/rounds-invitations.html | Express Entry | — |
| 15 | oinp-intl-student | OINP Employer Job Offer: International Student Stream | https://www.ontario.ca/page/oinp-employer-job-offer-international-student-stream | OINP | Ontario |
| 16 | crs-check-score | Express Entry: Check your CRS score | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score.html | Express Entry | — |
| 17 | noc-esdc | National Occupational Classification (NOC) lookup | https://noc.esdc.gc.ca/ | Express Entry | — |
| 18 | ircc-processing-times | IRCC processing times | https://www.canada.ca/en/immigration-refugees-citizenship/services/application/check-processing-times.html | IRCC | — |
| 19 | ee-who-can-apply | Express Entry: Who can apply | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply.html | Express Entry | — |
| 20 | ee-create-profile | Express Entry: Create profile and enter pool | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/create-profile.html | Express Entry | — |
| 21 | ee-apply-pr | Express Entry: Apply for permanent residence | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/apply-permanent-residence.html | Express Entry | — |
| 22 | ee-after-apply | Express Entry: After you apply | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/after-apply.html | Express Entry | — |
| 23 | ee-documents | Express Entry: Documents overview | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents.html | Express Entry | — |
| 24 | ee-doc-eca | Express Entry: Educational credential assessment | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/education-assessment.html | Express Entry | — |
| 25 | ee-doc-language-test | Express Entry: Language test results | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/language-test.html | Express Entry | — |
| 26 | ee-doc-job-offer | Express Entry: Job offer document | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/job-offer.html | Express Entry | — |
| 27 | ee-doc-police-cert | Express Entry: Police certificates | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/police-certificates.html | Express Entry | — |
| 28 | ee-doc-proof-funds | Express Entry: Proof of funds | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/proof-funds.html | Express Entry | — |
| 29 | pnp-overview | Immigrate as a provincial nominee (PNP overview) | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/provincial-nominees.html | PNP | — |
| 30 | ontario-federal-agreement | Ontario Federal-Provincial Immigration Agreement | https://www.canada.ca/en/immigration-refugees-citizenship/corporate/mandate/policies-operational-instructions-agreements/agreements/federal-provincial-territorial/ontario.html | OINP | Ontario |
| 31 | pr-status | Understand permanent resident status | https://www.canada.ca/en/immigration-refugees-citizenship/services/permanent-residents/status.html | IRCC | — |
| 32 | settle-canada | Settling in Canada | https://www.canada.ca/en/immigration-refugees-citizenship/services/settle-canada.html | IRCC | — |
| 33 | oinp-foreign-worker | OINP Employer Job Offer: Foreign Worker Stream | https://www.ontario.ca/page/oinp-employer-job-offer-foreign-worker-stream | OINP | Ontario |
| 34 | work-permit-need | Find out if you need a work permit | https://www.canada.ca/en/immigration-refugees-citizenship/services/work-canada/need-permit.html | IRCC | — |
| 35 | immigrate-canada-hub | Immigrate to Canada (main hub) | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada.html | IRCC | — |
| 36 | ee-how-it-works | Express Entry: How it works | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/works.html | Express Entry | — |
| 37 | work-canada-overview | Work in Canada overview | https://www.canada.ca/en/immigration-refugees-citizenship/services/work-canada.html | IRCC | — |
| 38 | clb-equivalency | Language test equivalency charts (CLB) | https://www.canada.ca/en/immigration-refugees-citizenship/corporate/publications-manuals/operational-bulletins-manuals/standard-requirements/language-requirements/test-equivalency-charts.html | Express Entry | — |
| 39 | noc-2021 | NOC 2021 – What changed | https://www.canada.ca/en/employment-social-development/services/noc.html | Express Entry | — |
| 40 | crs-tool | Official CRS calculator (IRCC) | https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score.html | Express Entry | — |

> **Note:** Entries #17 (`noc-esdc`) and #40 (`crs-tool`) are classified as `official_tool` and are not scraped by the ingestion pipeline. Entry #40 shares the same URL as #16.

### P2 — Supplementary Sources (5)

| # | ID | Page | URL | Program | Province |
|---|------|------|-----|---------|----------|
| 41 | bc-pnp-overview | BC Provincial Nominee Program overview | https://www.welcomebc.ca/immigrate-to-b-c/about-the-bc-provincial-nominee-program/about-the-bc-provincial-nominee-program | BC PNP | British Columbia |
| 42 | bc-pnp-skills-immigration | BC PNP Skills Immigration (for workers) | https://www.welcomebc.ca/immigrate-to-b-c/skills-immigration | BC PNP | British Columbia |
| 43 | alberta-aaip | Alberta Advantage Immigration Program | https://www.alberta.ca/alberta-advantage-immigration-program | AAIP | Alberta |
| 44 | manitoba-mpnp | Manitoba Provincial Nominee Program | https://immigratemanitoba.com/immigrate-to-manitoba/ | MPNP | Manitoba |
| 45 | pr-card-renew | Renew or replace your PR card | https://www.canada.ca/en/immigration-refugees-citizenship/services/new-immigrants/pr-card/apply-renew-replace.html | IRCC | — |

### Source Summary

| Category | Count |
|----------|-------|
| Total registry entries | 45 |
| Scrapable webpages | 43 |
| Official tools (not scraped) | 2 |
| P0 (core) | 11 |
| P1 (extended) | 29 |
| P2 (supplementary) | 5 |

### Domain Coverage

| Domain | Count | Type |
|--------|-------|------|
| canada.ca (IRCC) | 32 | Federal immigration |
| ontario.ca (OINP) | 7 | Ontario provincial |
| welcomebc.ca (BC PNP) | 2 | British Columbia provincial |
| alberta.ca (AAIP) | 1 | Alberta provincial |
| immigratemanitoba.com (MPNP) | 1 | Manitoba provincial |
| noc.esdc.gc.ca (NOC tool) | 1 | Federal tool |

---

## Completed Deliverables

### 1. `src/ingestion_module.py`

**Status:** Created & Fully Implemented.

- End-to-end data ingestion pipeline: scrape, clean, chunk, persist.
- **HTML Fetching:** `_fetch_page()` via `httpx` with 1s polite delay, custom User-Agent, redirect handling, and error recovery.
- **HTML Cleaning:** `_extract_main_content()` extracts `<main>` or `<article>` body; `_strip_html_tags()` removes all tags, collapses whitespace, normalizes entities.
- **Section-Based Chunking:** `_split_into_sections()` splits by header heuristics; `_break_long_section()` splits sections exceeding 1,500 characters on paragraph boundaries.
- **Metadata Enrichment:** Each chunk includes: `province`, `program`, `stream`, `source_type`, `source_url`, `section_or_title`, `effective_date_or_last_updated_or_unknown`, `accessed_at`.
- **Deduplication:** Deterministic chunk IDs via SHA-256 hash skip already-persisted chunks.
- **Persistence:** Appends to `data/processed/chunks.jsonl` (JSONL format).
- **Batch Mode:** `ingest_all()` processes entire URL registry with optional priority filter.

### 2. `src/retrieval_module.py`

**Status:** Created & Fully Implemented.

- Hybrid retrieval per frozen decision D-004.
- **BM25 Index:** In-memory `BM25Index` class (k1=1.5, b=0.75) with section title boosting.
- **Vector Retrieval:** ChromaDB persistent vector store with cosine similarity and automatic index rebuilding.
- **Hybrid Blending:** BM25 weight 0.6 + Vector weight 0.4, min-max normalized on union of candidates.
- **Reranker:** Post-hybrid stage combining hybrid score (0.70), query-term coverage (0.25), and exact phrase boost (0.05).
- **Metadata Filtering:** Supports province, program, stream, source_type filters with fallback.
- **Citation Output:** Each result includes `source_url`, `section_or_title`, `effective_date_or_last_updated_or_unknown`, `accessed_at` per D-007.

### 3. `data/processed/chunks.jsonl`

- Phase 1 (Apr 8): 533 chunks from 11 P0 sources.
- Phase 2 (Apr 9): Expanded to all 43 scrapable sources.

### 4. `data/raw/` (Raw HTML Archive)

- Stored raw HTML for all 43 scraped sources for reproducibility and audit.

---

## Commit History

| Date | Commit | Description |
|------|--------|-------------|
| Apr 8, 2026 | `327a7e1` | Role A Phase 1: real ingestion pipeline, retrieval module, URL registry, 533 chunks from 11 P0 sources |
| Apr 9, 2026 | `f10db7c` | Role A: expand knowledge base to 50 sources |

> Hybrid retrieval finalization (ChromaDB + BM25+vector blending + reranker) was completed in commit `a9db0c3` (Apr 10) by Framework Owner.

---

## Frozen Decisions Followed

- **D-004:** Hybrid BM25 (0.6) + Vector (0.4), top-k initial=20, reranked to final=5, metadata filters.
- **D-007:** Citation fields: source_url, section_or_title, effective_date_or_last_updated_or_unknown, accessed_at.
- **D-005:** Citation quality integrated into eval; section titles normalized via `normalize_section_or_title()`.
