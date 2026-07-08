> [!WARNING]
> **ARQUIVADO** (2026-07-07): snapshot gerado por ferramenta para sessões "Jules",
> hoje desatualizado (placeholders de rate-limit da API do GitHub, milestones vencidos).
> Movido da raiz para `docs/archive/` conforme
> [RFC-0002 — Governança documental](../rfc/0002-governanca-documental.md); status
> canônico de milestones vive em `IMPLEMENTATION.md`. Preservado como histórico;
> conteúdo original intacto abaixo.

# MANAGER-INTEL.md

## Overview
Leizilla is a legal monitoring tool designed to index Brazilian legal documents and release open datasets, starting with the state of Rondônia. Described as the "dinosaur that devours legal PDFs and spits out open data", it provides a 100% static pipeline—without a backend server—leveraging the Internet Archive for free OCR and P2P distribution. Currently at a functional MVP stage, it features a complete CLI, an asynchronous web crawler, embedded analytics via DuckDB, and an automated data publication workflow. It is targeted at researchers, developers, and the legal industry, acting as a sister project to Franklin Baldo's CausaGanha.

## Stack
- **Language**: Python 3.12
- **Frameworks/Libs**: Typer (CLI), Playwright & AnyIO (Crawling), DuckDB (ETL & Storage)
- **Test Runner**: pytest (with pytest-cov)
- **Package Manager**: uv
- **CI Setup**: GitHub Actions (Linting, Testing, and scheduled automated crawler jobs like Rondonia, Parse Release, and Claude Routine)
- **Code Quality**: Ruff (Linting & Formatting) and Mypy (Type checking)

## Open Issues
*(Not accessible due to GitHub API rate limiting in the current environment. However, the `IMPLEMENTATION.md` logs extensive planning and milestone tracking.)*

## Open PRs
*(Not accessible due to GitHub API rate limiting in the current environment.)*

## Jules History
The repository has a history of Jules sessions, evidenced by the presence of branch names such as `jules-6988357649938047230-6eae23ca` in the Git history. Jules sessions are also automated in CI via `.github/workflows/claude-routine.yml`, which triggers a Claude Routine Maintenance task twice a week to manage the repository based on `docs/routines/maintenance-prompt.md`. Additionally, an earlier Jules-initiated migration for LiteLLM was observed and tracked.

## Recommended Next Jules Sessions
Based on the `IMPLEMENTATION.md` milestone status:
1. **M5.3 — Benchmark DuckDB-WASM real + FTS**: Implement or refine the in-browser DuckDB benchmark. Currently marked as blocked until a real dataset is published, but the test scaffolding and optimization queries can be prepared.
2. **M14.3 — OPF Treino/Eval for fine-tuning**: Re-activate and complete the token-classifier training in `notebooks/opf_train_colab.ipynb` for structural span-tagging, preparing the integration pipeline.
3. **Federal/Planalto full pipeline coverage**: Expand the federal HTML parsing to handle the rest of the federal portal beyond the initial year-scoped URLs and stubs, preparing the full data export mechanism.

## Risks
- **High Reliance on External Credentials**: Full pipeline execution (crawling, parsing, uploading) requires valid `IA_ACCESS_KEY`, `IA_SECRET_KEY` (Internet Archive), and `ANTHROPIC_API_KEY` (Claude). This makes it difficult for Jules to run end-to-end tests or debug live API failures without these secrets configured in the sandbox.
- **Strict Architecture Principles**: The project has rigid, "load-bearing" principles defined in `IMPLEMENTATION.md` and `SCHEMA.md` (e.g., separating raw and parsed items, adhering strictly to the Leizilla XML v0.1 format, unique path mapping). Unintentional violations of these rules by Jules could cause CI pipeline or consistency checker failures.
- **Intricate XML Schema and Tooling**: Custom invariants are checked by `scripts/check_schema_consistency.py`, and there is a strict XSLT export mechanism to LexML. Modifying anything structural requires meticulous updates to schemas, fixtures, XSLT scripts, and validation tests.