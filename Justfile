# Justfile for Leizilla project

# Default task: print available tasks
default:
    @just --list

# Setup development environment
setup:
    @echo "Setting up development environment..."
    uv sync --dev
    @echo "Installing pre-commit hooks..."
    uv run pre-commit install
    @echo "Setup complete."

# Lint the codebase
lint:
    @echo "Linting code with Ruff..."
    uv run ruff check .

# Format the codebase
format:
    @echo "Formatting code with Ruff..."
    uv run ruff format .

# Run linters and formatters (useful before committing)
check: lint format-check typecheck test
    @echo "All checks completed!"

# Run formatters and apply fixes
fix:
    @echo "Applying Ruff fixes..."
    uv run ruff check . --fix --exit-non-zero-on-fix
    @echo "Applying Ruff formatting..."
    uv run ruff format .

# Alias for lint
style: lint

# Check formatting without applying
format-check:
    @echo "Checking formatting with Ruff..."
    uv run ruff format . --check

# Run tests with pytest
test:
    @echo "Running tests with pytest..."
    uv run pytest

# Type checking with mypy
typecheck:
    @echo "Type checking with mypy..."
    uv run mypy .

# Clean build artifacts and caches
clean:
    @echo "Cleaning up project..."
    find . -type f -name '*.py[co]' -delete
    find . -type d -name '__pycache__' -delete
    rm -rf .mypy_cache
    rm -rf .pytest_cache
    rm -rf .ruff_cache
    # Add other clean commands as needed (e.g., build directories)

# Comprehensive CI check (what GitHub Actions will run)
ci: clean lint format-check typecheck test
    @echo "✅ All CI checks passed!"

# List available tasks (alternative to default)
list:
    @just --list --unsorted
