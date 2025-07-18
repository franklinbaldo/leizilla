# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Leizilla is a **working** legal document indexing system that crawls, processes, and distributes Brazilian laws as open datasets. It's a sister project to CausaGanha, focused exclusively on indexing all Brazilian laws starting with Rondônia state. The project operates with minimal infrastructure, radical transparency, and a 100% static architecture - no servers or backends to maintain.

## Development Setup

This project uses **uv** for dependency management and follows modern Python packaging standards:

```bash
# Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
uv sync --dev

# Setup pre-commit hooks and complete environment
uv run leizilla dev setup
```

## Development Commands

The project uses uv scripts for all development operations:

```bash
# Essential commands
uv run leizilla dev setup    # Complete development environment setup
uv run leizilla dev check    # Run all pre-commit checks (lint, format-check, typecheck, test)
uv run leizilla dev fix      # Apply automatic fixes (ruff + formatting)

# Individual operations
uv run leizilla dev lint     # Lint with ruff
uv run leizilla dev format   # Format with ruff
uv run leizilla dev test     # Run pytest
uv run leizilla dev clean    # Clean build artifacts and caches

# Leizilla pipeline commands
uv run leizilla discover --origem rondonia --start-coddoc 1 --end-coddoc 10 --crawler-type simple    # Discover laws from a specific range of coddocs using the simple crawler
uv run leizilla download --origem rondonia --limit 5       # Download up to 5 PDFs
uv run leizilla upload --limit 3                  # Upload up to 3 PDFs to Internet Archive
uv run leizilla export --origem rondonia --year 2020      # Export dataset to Parquet
uv run leizilla pipeline --origem rondonia --start-coddoc 1 --end-coddoc 10 --limit 5 --crawler-type simple  # Complete pipeline for state/year/limit

# Single test execution
uv run pytest tests/test_specific.py -v
```

## CLI Usage

The project has a complete command-line interface. All commands are executed via `uv run leizilla <command>`.

## Core Architecture

### Internet Archive as Central Pillar

The project's architecture is built around Internet Archive as the foundational component, validated by the CausaGanha project which successfully processed 21+ years of judicial decisions. This approach provides:

- **Free OCR**: Automatic text extraction from uploaded PDFs
- **Permanent storage**: Zero-cost hosting with global CDN
- **Automatic torrents**: P2P distribution generated by IA
- **Shared database**: Distributed DuckDB via IA with conflict prevention

### Data Flow Pipeline

1. **Crawler** (Playwright + AnyIO): Downloads PDFs from official sources (.gov.br)
2. **Internet Archive Upload**: Immediate archival triggers automatic OCR and torrent generation
3. **ETL Processing** (DuckDB): Local processing of OCR text into structured data
4. **Dataset Publication**: Export to Parquet + JSON Lines formats
5. **Distribution**: GitHub Releases, IA mirrors, and P2P torrents
6. **Client-side Search**: DuckDB-WASM enables SQL queries in browser

### Technology Stack

- **Python 3.12**: Core language with strict type checking (mypy)
- **Playwright + AnyIO**: Async web crawling for JavaScript-heavy government sites
- **DuckDB**: Embedded analytical database, exports Parquet natively
- **Internet Archive**: OCR, permanent storage, and torrent distribution
- **uv**: Fast Python package management
- **ruff**: Linting and formatting
- **GitHub Actions**: Complete CI/CD automation

## Project Structure

```
src/                   # Flat source structure
├── config.py         # Centralized configuration management
├── storage.py         # DuckDB schema and database operations
├── crawler.py         # Playwright-based web crawling
├── publisher.py       # Internet Archive integration and exports
└── cli.py             # Complete command-line interface
docs/adr/              # Architecture Decision Records
docs/plans/            # Future feature planning documents
docs/DEVELOPMENT.md    # Detailed technical development guide
tests/                 # Test suite (pytest-based)
data/                  # Local data directory (gitignored)
  └─ leizilla.duckdb   # Local DuckDB database (auto-created)
```

## Development Status

**Current Phase**: Working MVP with complete pipeline

The project has a **complete implementation** including:

- ✅ Full CLI interface with discover/download/upload/export/search commands
- ✅ DuckDB schema with complete CRUD operations (storage.py:1-247)
- ✅ Playwright-based async crawler (crawler.py:1-180)
- ✅ Internet Archive integration (publisher.py:1-150)
- ✅ Centralized configuration management (config.py:1-45)
- ✅ Complete test suite for core modules
- ✅ Modern CLI with subcommands for pipeline automation
- ✅ Development environment with type checking and linting

## Data Architecture

### Local DuckDB Database

- **Location**: `data/leizilla.duckdb` (auto-created, gitignored)
- **Purpose**: Local ETL processing and staging
- **Schema**: Complete `leis` table with full-text content, metadata, JSON support, and search indices
- **Export**: Native Parquet export for distribution

### Current Data Formats

- **Parquet**: Columnar analytics format (primary)
- **JSON Lines**: Pipeline-compatible streaming format
- **Torrents**: P2P distribution via Internet Archive

## Quality Standards

- **Type Safety**: All functions require type hints, mypy strict checking
- **Code Style**: ruff formatting with 88-character line length
- **Testing**: pytest with coverage requirements
- **Commits**: Conventional Commits format required
- **Documentation**: ADRs for architectural decisions, clear docstrings for public APIs

## Environment Variables

The project uses configuration from environment variables:

- `IA_ACCESS_KEY` / `IA_SECRET_KEY`: Internet Archive credentials (required for upload)
- `DUCKDB_PATH`: Database location (defaults to `data/leizilla.duckdb`)
- `DATA_DIR`: Data directory path (defaults to `data/`)

## Claude Assistant Permissions

The `.claude/settings.local.json` file defines the permissions for the Claude Code AI assistant when working in this repository. These permissions are specified as allowed Bash commands:

- `Bash(git checkout:*)`: Allows checking out branches or paths.
- `Bash(rm:*)`: Allows removing files or directories.
- `Bash(git add:*)`: Allows adding file contents to the index.
- `Bash(mkdir:*)`: Allows creating new directories.
- `Bash(touch:*)`: Allows creating empty files or updating timestamps.
- `Bash(mv:*)`: Allows moving or renaming files and directories.
- `Bash(find:*)`: Allows searching for files in a directory hierarchy.
- `Bash(PYTHONPATH=src python -c "import config; print('✅ Config loaded'); import storage; print('✅ Storage loaded')")`: Allows running a specific Python command to check if `config` and `storage` modules can be loaded. This is likely a health check or a way to ensure the core components are importable.
- `Bash(uv run:*)`: Allows running any `uv run` scripts defined in `pyproject.toml`. This is crucial for development, testing, and pipeline execution tasks.
- `Bash(rg:*)`: Allows using `ripgrep` for searching text patterns in files.
- `Bash(grep:*)`: Allows using `grep` for searching text patterns in files.

Currently, there are no explicitly denied commands in the `deny` list.

## Key Implementation Files

- **config.py:1-45**: Environment configuration and path management
- **storage.py:1-247**: Complete DuckDB schema and operations
- **crawler.py:1-180**: Async web crawling with Playwright
- **publisher.py:1-150**: Internet Archive uploads and dataset exports
- **cli.py:1-200**: Full command-line interface implementation

## Testing and Quality

Run the complete test suite:

```bash
just test              # Run all tests
just check             # Run linting, formatting, and type checking
just ci                # Complete CI pipeline
```

Current test coverage includes:

- Storage operations (DuckDB schema validation)
- Configuration loading
- CLI argument parsing
- Core module imports

## Roadmap Context

- **Q3/2025**: Complete Rondônia state laws indexing
- **Q4/2025**: Federal legislation coverage (1988-present)
- **Q1/2026**: Static frontend (HTML/JS) with DuckDB-WASM search
- **Q2/2026**: Semantic search with embeddings stored in DuckDB

The project emphasizes cost-zero operation, radical transparency, and distributed resilience over traditional cloud-based approaches.
