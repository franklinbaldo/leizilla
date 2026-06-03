# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What Leizilla is

Leizilla crawls, parses, and republishes Brazilian legislation as open datasets.
It is deliberately **infrastructure-minimal and Internet-Archive-centric**: there
are no servers to run. The Internet Archive (IA) provides free OCR, permanent
storage, a CDN, and automatic torrents; everything else is a local pipeline that
produces files and pushes them to IA and GitHub.

Coverage starts with **Rondônia (RO)** and expands to federal (Planalto) and
other states over time.

## Source of truth

**`IMPLEMENTATION.md` holds the canonical milestone status** — what is done,
in-progress, or blocked. Read it before planning work. Do not reintroduce a
separate TODO/status doc; status lives in `IMPLEMENTATION.md` and design lives
in `docs/adr/` and `docs/SCHEMA.md`.

Current state: milestones **M0–M12.2 are done** (discovery, scraping, IA upload,
OCR fetch, LLM parsing, ETL→Parquet, dataset release, frontend foundation).
**M5.3** (DuckDB-WASM benchmark + FTS) is blocked pending a large published
dataset. **M13** (frontend polish) is in flight.

## Development setup

Uses **uv** for dependency management (Python 3.12):

```bash
uv venv
source .venv/bin/activate           # .venv\Scripts\activate on Windows
uv sync --extra dev                 # installs ruff/mypy/pytest/pre-commit (the `dev` extra); matches CI
uv run pre-commit install           # install git hooks
```

Or just `uv run leizilla dev setup`, which runs both.

CI runs `uv sync --frozen --extra dev`. Use `--extra dev` (not `--dev`) — the
linters/type-checker live in the optional `dev` extra, while `--dev` only pulls
the `dev` dependency group.

## Everyday commands

```bash
uv run leizilla dev check    # lint (ruff) + format-check + tests (pytest)
uv run leizilla dev fix      # auto-fix: ruff --fix + ruff format
uv run leizilla dev test     # pytest
uv run leizilla dev lint     # ruff check
uv run leizilla dev format   # ruff format
uv run leizilla dev clean    # remove build/cache artifacts

uv run mypy src/ --ignore-missing-imports   # type-check (CI runs this separately)
uv run pytest tests/test_etl.py -v          # a single test file
```

Note: `dev check` does **not** run mypy — CI (`.github/workflows/lint.yml`) runs
ruff, mypy, and pytest. Run mypy yourself before pushing type-sensitive changes.

## Architecture: the pipeline

```
discover ──> harvest/scrape ──> fetch-ocr ──> parse ──> consolidate ──> release-dataset ──> frontend
(manifest)   (robots→Wayback    (IA _djvu.txt  (Claude   (XML→Parquet)   (Parquet→IA)        (DuckDB-WASM
             →IA upload,         →clean/         Haiku                                        in browser)
             SHA-256 bucket)     normalize)      →XML)
```

1. **Discover** — manifest-driven (`manifests/{ente}.json`) strategies enqueue
   resources into DuckDB (`discovered_resources`).
2. **Harvest/scrape** — respect robots.txt, save to Wayback then fetch from it
   (fail-open to direct download), upload raw bytes to IA.
3. **OCR fetch** — pull IA-generated `_djvu.txt`, clean and normalize.
4. **Parse** — Claude Haiku turns OCR/HTML into validated Leizilla XML.
5. **Consolidate** — XML → Parquet (`versoes` table).
6. **Release** — publish the Parquet dataset to IA.
7. **Search** — `web/` runs DuckDB-WASM against the published Parquet in-browser.

The scheduled GitHub Actions run this chain weekly: **Sat** discover-harvest →
**Sun** crawl → **Mon** parse/release, plus a **Mon/Thu** Claude maintenance
routine.

## Source layout

```
src/leizilla/
├── config.py        # env + path config (DUCKDB_PATH, IA/Anthropic keys, crawler timeouts)
├── entes.py         # federative entity catalog (27 states + federal)
├── storage.py       # DuckDB schema + CRUD (leis, discovered_resources)
├── discovery.py     # manifest-driven discovery strategies (WaybackCdx/Sequential/Playwright)
├── crawler.py       # Playwright + direct PDF download
├── scraper.py       # robots → Wayback → IA orchestration; per-host rate limiting
├── wayback.py       # Wayback Machine save/fetch (fail-open)
├── robots.py        # robots.txt enforcement (ADR-0008)
├── publisher.py     # IA upload + content-addressing (ADR-0010) + dataset release  [largest, ~900 LOC]
├── ia_utils.py      # SHA-256 addressing, index.csv, IA identifier helpers
├── parser.py        # OCR/HTML → Leizilla XML via Claude (confidence-gated)
├── ocr.py           # OCR text cleaning + normalization
├── etl.py           # Leizilla XML → Parquet (versioning + revogação cascade)
├── cli.py           # Typer CLI, ~20 commands  [largest user-facing, ~1300 LOC]
└── fontes/          # source-specific discovery: ro.py (done), federal.py (Planalto), sp.py (stub)
manifests/           # per-ente discovery manifests (currently ro.json)
web/                 # Astro + Svelte 5 + Pico CSS + DuckDB-WASM frontend
docs/adr/            # Architecture Decision Records
docs/SCHEMA.md       # canonical data model (dispositivo-centric)
docs/routines/       # Claude maintenance-prompt for automated sessions
tests/               # pytest suite (~530 tests, all external calls mocked)
data/                # local DuckDB + artifacts (gitignored)
```

## Key design decisions (see `docs/adr/`)

- **ADR-0001 — IA as central pillar.** Free OCR, permanent storage, torrents.
- **ADR-0004 — Wayback as primary fetch.** Be gentle to fragile gov.br sites.
- **ADR-0008 — robots.txt + rate limiting.** Permanent reject on disallow; ~1 req/s.
- **ADR-0009 — LGPD/ethics.** Brazilian laws are public; no despublication.
- **ADR-0010 — content-addressed raw, URN-keyed parsed.** Raw bytes are stored by
  SHA-256 (source-agnostic, dedup-by-construction); parsed norms are keyed by
  URN-LEX. The harvest key (`coddoc`, URL path, …) is metadata in an `index.csv`,
  never a path or range boundary. ADR-0010 supersedes ADR-0005's raw-item scheme.
- **ADR-0011 — identity-keyed navigable catalog; identity is evidence, not an
  ingestion gate.** The raw IA item is a navigable range bucket per `(ente, fonte,
  tipo, número)` with content-addressed files inside. **Extracting `(tipo, número)`
  from discovery *context* is the primary job and resolves >90%** — the number lives
  in the page metadata / lead-in listing pages / URL-filename pattern (ALRO title,
  casacivil `L{N}.pdf`, Planalto URL path), read *before* fetching the PDF; the
  identified resource goes straight to the catalog. "Un-numbered" shouldn't happen
  on the normal path — if it does often for a source, strengthen that source's
  discovery strategy. The residual <10% needs a deliberate **special strategy** per
  source (e.g. fetch → IA OCR → parse); meanwhile those bytes are **preserved** in a
  `leizilla_{ente}_{fonte}_unidentified` holding area (the exception, never
  discarded) and promoted by reconciliation. Capture is decided by context, not by
  reading the document.

The codebase is **fail-open by design**: Wayback save failures, missing
robots.txt, and IA query errors return empty/None rather than aborting batch jobs.

## CLI reference

All commands run as `uv run leizilla <command>`. Most take `--ente` (default `ro`).

| Command | Purpose |
|---|---|
| `discover --ente ro` | run manifest discovery → enqueue resources |
| `harvest --ente ro --limit 100` | process the pending queue (scrape + upload) |
| `reconcile --ente ro [--fonte assembleia]` | promote `_unidentified` holding files into range items once discovery context yields `(tipo, número)` (ADR-0011 §1) |
| `scrape --ente ro --fonte casacivil --tipo lei --start-coddoc 1 --end-coddoc 10` | range scrape one source |
| `bundle-raw --ente ro --fonte casacivil` | consolidate raw PDFs into one IA item (torrents) |
| `fetch-ocr --ente ro --limit 100` | pull IA OCR text into DuckDB |
| `parse --ente ro --raw-id leizilla-raw-ro-casacivil-lei-05120` | LLM parse one raw item → XML (`--upload`, `--input-type ocr\|html`) |
| `parse-all --ente ro --start-coddoc 1 --end-coddoc 100` | batch parse a range (`--upload`, `--skip-existing`, `--error-threshold`, `--output-dir`) |
| `fetch-all-parsed --ente ro --output-dir data/parsed` | download all parsed XML from IA |
| `consolidate data/parsed --output out.parquet --ente ro` | XML dir (positional) → Parquet |
| `release-dataset out.parquet --ente ro --version 0` | publish Parquet (positional) dataset to IA |
| `export --ente ro --year 2020` | export local Parquet |
| `search --ente ro` / `stats --ente ro` | local search / IA item counts |
| `pipeline --ente ro --limit 5` | orchestrate discover→harvest→export |

Source-specific discovery currently exists for RO (`fontes/ro.py`) and federal
Planalto (`fontes/federal.py`); `fontes/sp.py` is a stub, and only `ro.json`
manifest exists.

## Data & schema

- **Local DB:** `data/leizilla.duckdb` (auto-created, gitignored). Tables: `leis`
  (law records) and `discovered_resources` (discovery queue).
- **Canonical data model:** `docs/SCHEMA.md` — the **dispositivo** (article/clause)
  is the unit; tipo/rótulo are derived from path, vigência inherited, revogação is
  a structured event. XML is validated against `docs/schemas/leizilla-v0.1.xsd`.
- **Distribution formats:** Parquet (`versoes` table, primary), plus IA torrents.

## Testing & CI

- ~530 pytest tests; **all network/IA/Anthropic/subprocess calls are mocked** —
  there are no live-network tests. Keep new tests offline/deterministic.
- `lint.yml` gates every PR: ruff check, ruff format-check, mypy, pytest.
- `schema-validate.yml` runs xmllint/xsltproc + the consistency checker when
  schema, fixtures, or related tests change.
- Weakly covered today: `ocr.py`; `config.py` and `entes.py` have no direct tests.

## Conventions

- **Types:** all functions need type hints; mypy is part of CI.
- **Style:** ruff format, 88-char lines, double quotes, target py312.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, …).
- **ADRs:** add an ADR in `docs/adr/` for architectural decisions; update
  `docs/SCHEMA.md` for data-model changes (and re-run the schema validation).
- **Pre-commit** mirrors CI (ruff, ruff-format, mypy, hygiene hooks).

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `IA_ACCESS_KEY` / `IA_SECRET_KEY` | Internet Archive auth (required for upload) | — |
| `ANTHROPIC_API_KEY` | Claude API for parsing | — |
| `DUCKDB_PATH` | local DB location | `data/leizilla.duckdb` |
| `DATA_DIR` | data directory | `data/` |
| `CRAWLER_DELAY` / `CRAWLER_RETRIES` / `CRAWLER_TIMEOUT` | crawler tuning (ms/count/ms) | `2000` / `3` / `30000` |

See `.env.example`. Permissions for the Claude Code assistant live in
`.claude/settings.local.json`.

## Roadmap

- **Q3/2025** — complete Rondônia indexing.
- **Q4/2025** — federal legislation (1988–present).
- **Q1/2026** — static DuckDB-WASM search frontend.
- **Q2/2026** — semantic search with embeddings in DuckDB.

Guiding principles throughout: cost-zero operation, radical transparency, and
distributed resilience over cloud infrastructure.
