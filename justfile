# Leizilla — task shortcuts.
#
# Thin wrappers over `uv run leizilla dev ...` so the CLI stays the single
# source of truth for dev tasks. Run `just` (no args) to list recipes.
#
# Install just: https://github.com/casey/just  (e.g. `cargo install just`,
# `brew install just`, or `uv tool install rust-just`).

# List available recipes.
default:
    @just --list

# Complete development environment setup (deps + pre-commit hooks).
setup:
    uv run leizilla dev setup

# Lint with ruff.
lint:
    uv run leizilla dev lint

# Format with ruff.
format:
    uv run leizilla dev format

# Run the test suite with pytest.
test:
    uv run leizilla dev test

# Type-check with mypy (matches the CI lint-test job).
typecheck:
    uv run mypy src/ --ignore-missing-imports

# Run all pre-commit checks: lint, format-check, test.
check:
    uv run leizilla dev check

# Apply automatic fixes (ruff lint --fix + format).
fix:
    uv run leizilla dev fix

# Clean build artifacts and caches.
clean:
    uv run leizilla dev clean

# Full CI pipeline: checks + type-checking.
ci: check typecheck
