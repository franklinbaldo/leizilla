# DITEL ingestion — Rondônia laws & decrees (Phase 0 map + plan)

Goal: ingest the **laws, complementary laws, and decrees of Rondônia published by DITEL**
(Casa Civil's COTEL system) through the existing crawl → Wayback → IA → OCR → parse →
consolidate pipeline, producing the project's normal structured output (the Parquet
`versoes` table, queryable in DuckDB). This is the Phase 0 diagnosis required before
building; it is a **separate track from the OPF/span-tagging work** (PR #84) — that track is
untouched here.

## 1. The pipeline and where a new source plugs in

```
manifests/ro.json
  → discovery.py strategies (wayback-cdx | sequential | playwright)  → discovered_resources (DuckDB ledger)
  → scraper.harvest_pending_resources:
        robots.is_allowed → wayback.save_page → wayback.check_available → fetch snapshot
        (fail-open: direct fetch, rate-limited per host) → publisher.upload_raw → IA raw item
  → IA auto-OCR (_djvu.txt)
  → parser.fetch_ocr + parser.parse_law (Claude Haiku) → Leizilla XML  (dispositivo-centric;
        rótulo derived from `path` via the SCHEMA §4.2 token map)
  → etl.consolidate (xml_to_rows + write_parquet) → Parquet `versoes`  (grain: lei × dispositivo × versão)
  → publisher.upload_dataset → IA dataset item → web/ DuckDB-WASM frontend
```

**The seam for a new source is two points:**
1. a `fontes` block in `src/leizilla/manifests/ro.json`;
2. a **discovery strategy** (`discovery.py`) that emits `discovered_resources` rows
   `{url, ente, fonte, tipo_documento, chave, status, wayback_snapshot}`.

Everything downstream (harvest, OCR, parse, consolidate, release) is **source-agnostic and
already built** for PDF sources. Text enters as the IA OCR `_djvu.txt`; structure is
assigned by the parse stage; the structured rows land in Parquet `versoes`. The local
`data/leizilla.duckdb` `leis` table is only a scrape ledger, not the structured output.

Conventions are dict-based + stdlib `logging` + DuckDB + `internetarchive` — **not** Pydantic
/ structlog. New code follows the existing style.

## 2. DITEL characterized (two layers: live source + Wayback)

**Live source.** `https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/{prefix}{n}.pdf`:
- `L{n}.pdf` = lei ordinária, `LC{n}.pdf` = lei complementar, `D{n}.pdf` = **decreto**.
- **Born-digital PDFs** (`%PDF-1.4/1.3`, embedded Times-Roman fonts — *not* scanned), so the
  OCR/format risk is low; a text layer is extractable directly.
- Served over **HTTPS**. The plain-`http://` URL **403s** behind a WAF ("Request Rejected").
- Probed live: `L5120` ✓, `LC1000` ✓, `D5000`/`D1000`/`D100` ✓ (all `200 application/pdf`).

**Wayback layer.** Coverage is **sparse and inconsistent** (availability API):
- `http://…/L5120.pdf` → archived 2024-12-08; `…/D1000.pdf` → archived 2022-09-03;
- `…/LC1000.pdf` → **not archived**; `https://` variants → not archived.
- So for most norms the first job is **Save Page Now** to populate Wayback, then ingest.
  Snapshots are keyed by the *submitted* URL (http vs https matters for lookup).

**Metadata.** `(tipo, número)` come from the filename (`parse_filename`) and/or the PDF
title page (`parse_titulo_identity`, already implemented); `data`/`ementa` come from the
parsed text. The Wayback **snapshot timestamp** is the provenance/version key.

## 3. The gap

| # | Missing / wrong | Why it matters |
|---|---|---|
| 1 | `manifests/ro.json` + `crawler.py` use `http://` | DITEL's WAF 403s on http → the pipeline can't fetch a single byte today |
| 2 | no **decreto** enumeration (`discover_casacivil_laws` rejects non lei/lc; manifest has only `L`/`LC` templates) | the task wants laws **and** decrees; `D{n}.pdf` exists and `parse_filename` already maps `D`→decreto |
| 3 | Wayback not populated for most DITEL URLs | need SPN-first, then ingest (decision: SPN-first, reuse any existing snapshot) |
| 4 | `wayback.check_available` only accepts snapshots < 24 h old | it ignores the existing 2022/2024 archives and refetches direct, losing provenance; we want to **use & record any snapshot's timestamp** |
| 5 | never run end-to-end (IA has 0 `leizilla-raw-ro` items) | Phase 2 must produce a real, verified batch |
| 6 | parser quirks for RO statutes | likely none — RO follows LC 95/1998, highly regular `Art./§/inciso/alínea`; verify in Phase 2, **no model** |

**Not gaps:** no new fetcher framework (reuse `wayback.py` + `scraper.py` + `publisher.py`),
no new format adapter (PDF is already handled), no Pydantic/structlog, no OPF.

## 4. Plan (decisions: new branch off main · full pipeline → Parquet · SPN-first/any-snapshot)

**Phase 1 — adapter, built to the existing seam, offline-tested:**
- `manifests/ro.json`: `http`→`https`; add a `D{num}.pdf` sequential template (decreto); fix
  the wayback-cdx prefix.
- `crawler.py`: `_CASACIVIL_*` base URLs → `https`; `discover_casacivil_laws` accepts
  `decreto` (prefix `D`).
- `wayback.py`: provenance helpers — `closest_snapshot` returns **(URL + timestamp), any
  age, querying both http and https** (the availability API is scheme-sensitive and DITEL's
  historical captures are http-keyed while live downloads need https); `ensure_archived` is
  SPN-first and reads the new snapshot **from the Save-Page-Now response** (`Content-Location`)
  rather than an immediate re-query (SPN exposes snapshots asynchronously). CDX discovery
  queries scheme-agnostically (SURT urlkey) for the same reason, and **normalizes each
  discovered URL's scheme to the manifest's** (https) so the http-keyed captures dedup
  against the sequential strategy's URLs (the resource ledger is keyed by literal URL) —
  the actual http snapshot is kept in `wayback_snapshot`.
- carry the Wayback timestamp as provenance, **serialized into the raw-item `_meta.json`**
  (`provenance_wayback.wayback_timestamp`): `harvest` captures it explicitly (from the
  resolved pair or recovered from a pre-discovered ledger URL via `snapshot_timestamp`);
  `build_raw_meta` writes it, falling back to extracting it from the snapshot URL. The CLI
  `scrape` path carries the CDX-discovered http snapshot into `scrape_one` so its historical
  capture (and timestamp) is reused rather than lost to a scheme-sensitive lookup.
- `cmd_scrape`: decreto support; the casacivil branch enumerates the **whole range** and
  merges CDX snapshots in (DITEL coverage is sparse — a CDX hit must not truncate the range,
  or unarchived numbers are silently skipped); `scrape_one` uses `ensure_archived` for items
  without a pre-discovered snapshot (SPN-first provenance, not an immediate availability check).
- tests: discovery URL generation (incl. decreto + https), `parse_filename` decreto, and the
  Wayback provenance helper, all offline (IO seams mocked/injectable).

**Phase 2 — run a small real batch & verify:** the **fetch** stage runs here (Wayback/direct,
no creds); **IA upload + IA OCR + Claude parse + Parquet** require `IA_*` / `ANTHROPIC_API_KEY`
and so run in the **scheduled GitHub Actions** (`discover-harvest.yml`, `parse-release.yml`),
which hold the secrets. We verify every sandbox-reachable step, report counts, and hand the
credentialed stages to CI.

### Phase 2 results (small real batch — 2 leis + 2 decretos, fetched via the `wayback` client)

| chave | tipo | bytes | provenance | local text layer | structure |
|---|---|---|---|---|---|
| lei-05120 | lei | 424 KB | direct (not yet archived) | **born-digital** | `Art. 1°–6°` + ementa ✓ |
| lei-05121 | lei | 184 KB | `wayback@20241208221945` | **born-digital** | `Art. 1°–5°` + ementa ✓ |
| decreto-01000 | decreto | 391 KB | `wayback@20220903083131` | none (scanned) | — needs IA OCR |
| decreto-01001 | decreto | 773 KB | `wayback@20220903083119` | none (scanned) | — needs IA OCR |

`COUNTS: fetched 4/4 · born-digital-text 2 · article-structure-detected 2.`

**Key finding (Phase 0 #6 resolved with data):** RO **laws are born-digital** (clean text
layer; `Art./§/inciso` extract directly — LC 95 regularity confirmed, no model needed), but
the **older decretos are scanned image PDFs** with no text layer. They are *not* a blocker —
the pipeline's IA-OCR stage exists precisely for this (`parser.fetch_ocr` reads the IA
`_djvu.txt`). So decretos ride the same path; they just depend on IA OCR where laws could
even be parsed from the embedded text. Hand-verified L5120: ementa *"Institui a Campanha
Permanente de Conscientização da depressão Infantil…"* + `Art. 1°` … `Art. 6° VETADO.`

The **Wayback provenance** worked end-to-end: existing snapshots were reused (timestamps
above are the immutable version keys), and unarchived URLs fall through to direct fetch
(and would be submitted via Save-Page-Now in the harvest path). The credentialed stages
(IA upload → OCR → Claude parse → Parquet `versoes`) run unchanged in the scheduled
workflows.
