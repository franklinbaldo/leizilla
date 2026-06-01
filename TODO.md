# Leizilla – Master TODO List

> This master list combines previous tasks with new, advanced suggestions. All tasks are opt-in. To avoid paralysis, only move a task to "In Progress" after opening a linked GitHub Issue or Pull Request.
>
> **Source of truth for what's shipped: the milestone table in `IMPLEMENTATION.md`.** Everything through M12.2 is done — crawler, OCR fetch + normalization, ETL→Parquet, IA upload, and the frontend foundation. Items below that overlap with completed milestones are checked off and annotated with the milestone that delivered them.

---

## 0️⃣ Meta: Project Management

- [ ] **Lifecycle**: When a task is completed, move it to a `DONE.md` file with the completion date and commit SHA for a project changelog.
- [ ] **Labels**: Standardize issue labels on GitHub (e.g., `priority:critical`, `type:bug`, `component:crawler`).

---

## 1️⃣ High-Priority Blockers (MVP Completion) — ✅ DONE

The core pipeline is functional; these former blockers all shipped.

- [x] **Implement Real Crawler** — functional crawlers for the Rondônia sources (assembleia + casacivil lei/lc) via `scraper.py` / `discovery.py` (M2.2, M2.5, M10.A).
- [x] **Implement OCR Text Retrieval** — `leizilla fetch-ocr` downloads IA `_djvu.txt` into DuckDB (`ocr.py` + `cmd_fetch_ocr`, M10.C / #61).
- [x] **Implement Text Normalization** — `clean_ocr_text` + `normalize_text` populate the normalized text column, with Portuguese charset handling (M10.C / #61).

---

## 2️⃣ Config & Setup

- [ ] **Document Credentials**: Clearly document how to obtain `IA_ACCESS_KEY` and `IA_SECRET_KEY` in `DEVELOPMENT.md`.
- [ ] **Validate Environment**: Add runtime validation in `src/config.py` to ensure all required environment variables are set.
- [ ] **Improve `.env.example`**: Expand the example file with comments explaining each variable and its default value.
- [ ] **Create Health Check Script**: Add a `./scripts/doctor.sh` script that verifies all local prerequisites are met (uv, Playwright browsers, etc.).
- [ ] **Provide Cross-Platform Installer**: Create simple `install.ps1` (Windows) and `install.sh` (Linux/macOS) scripts for a smoother setup.

---

## 3️⃣ Crawler & ETL

- [ ] **Implement Crawl Resume**: Use status flags in the database (e.g., `crawling_status: downloaded`) to allow the crawler to be stopped and resumed without re-processing completed items.
- [x] **Add Automatic Rate-Limiting**: Per-host rate limiting via `make_rate_limiter` (M2.4); parallel scraping of multiple sources without serializing.
- [ ] **Save HTML Snapshots**: For each law discovered, save the source HTML page for provenance and easier debugging of the parser.
- [ ] **Parallelize ETL**: Use `anyio.TaskGroup` to parallelize network-bound tasks like downloading PDFs or fetching OCR text, significantly speeding up the pipeline.
- [ ] **Crawler Tool Flexibility**: Evaluate and implement alternative crawling tools (e.g., `requests` + `BeautifulSoup`) when Playwright is not the most appropriate or efficient for a given source.

---

## 4️⃣ Database & Schema

- [ ] **Introduce Migrations**: Implement a lightweight, `Alembic`-style migration system within `src/storage.py` to manage schema changes over time.
- [ ] **Enable Full-Text Search**: Add support for DuckDB's FTS extension and create indices as soon as it officially supports Portuguese.
- [ ] **Prepare for Semantic Search**: Integrate the `vector()` extension to prepare the schema for future semantic search capabilities.
- [ ] **Verify Data Integrity**: Implement a process to periodically verify the checksums of local/exported files against the files stored on Internet Archive.

---

## 5️⃣ CLI & User Experience

- [ ] **Add `validate` Command**: Create a new command `leizilla validate` that runs a sanity check on generated datasets (e.g., checks for missing values, validates schema).
- [ ] **Implement Progress Bars**: Use a library like `rich` or `tqdm` to display progress bars for long-running operations like `download` and `fetch-ocr`.
- [ ] **Improve Output Formatting**: Use `rich` for colored, well-structured table outputs for commands like `stats` and `search`.
- [x] **Add `justfile`**: `justfile` in the repo root wraps `uv run leizilla dev …` (setup/lint/format/test/typecheck/check/fix/clean/ci), matching the `just` commands referenced in `CLAUDE.md`.

---

## 6️⃣ Tests & Quality

- [ ] **Enforce 80% Test Coverage**: Configure `pytest-cov` to enforce a minimum test coverage of 80% and fail the CI build if it drops below the threshold.
- [ ] **Use VCR for Integration Tests**: Implement `VCR.py` to record and replay HTTP requests for crawler and publisher tests, making them fast, deterministic, and network-independent.
- [ ] **Add Windows to CI**: Add a Windows runner to the GitHub Actions workflow to ensure cross-platform compatibility.
- [ ] **Refine Ruff Configuration**: Fine-tune the `ruff.toml` rules, for example, deciding on the line-length rule (`E501`).

---

## 7️⃣ Pipeline & CI/CD

- [ ] **Schedule Weekly Pipeline Runs**: Create a GitHub Actions workflow that runs on a weekly `cron` schedule to automatically discover and process new legislation.
- [ ] **Cache Playwright Browsers in CI**: Configure the CI pipeline to cache the Playwright browser binaries to speed up workflow execution.
- [ ] **Implement Nightly DB Backup**: Create a nightly CI job that uploads the entire `leizilla.duckdb` file to a versioned item on Internet Archive (e.g., `leizilla-db-backup-YYYY-MM-DD`).
- [ ] **Generate Checksums for Releases**: Automate the generation of a `SHA256SUMS` file and include it as an asset in every GitHub Release.

---

## 8️⃣ Static Frontend

- [ ] **Build Minimalist Skeleton**: Create the initial `index.html`, CSS, and JavaScript files required to load DuckDB-WASM.
- [ ] **Add Query Templates**: Implement a dropdown menu with pre-written SQL query examples to guide users.
- [ ] **Implement Data Export**: Add buttons to allow users to export the results of their queries to CSV or JSON format directly from the browser.
- [ ] **Conduct Accessibility Audit**: Ensure the frontend meets WCAG AA standards for accessibility.

---

## 9️⃣ Documentation

- [ ] **Create Style Guide**: Add a `STYLE_GUIDE.md` defining project conventions for code style, docstrings, and Conventional Commits.
- [ ] **Add High-Level Diagram**: Create and embed a Mermaid diagram in the `README.md` illustrating the complete data flow architecture.
- [ ] **Consolidate Docs**: Refactor `README.md` and `docs/DEVELOPMENT.md` to reduce duplication and create a clear "getting started" path.
- [ ] **Create FAQ**: Add a section in the documentation or a new file answering frequently asked questions, especially regarding the usage limits and best practices for the Internet Archive.
