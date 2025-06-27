# Justfile for Leizilla project

# Default task: print available tasks
default:
    @just --list

# Setup development environment
setup:
    @echo "Setting up development environment..."
    uv sync --dev
    @echo "Installing pre-commit hooks..."
    pre-commit install
    @echo "Setup complete."

# Lint the codebase
lint:
    @echo "Linting code with Ruff..."
    ruff check .

# Format the codebase
format:
    @echo "Formatting code with Ruff..."
    ruff format .

# Run linters and formatters (useful before committing)
check: lint format-check
    @echo "Running all checks..."
    # Placeholder for mypy if added as a separate check later
    # mypy .

# Run formatters and apply fixes
fix:
    @echo "Applying Ruff fixes..."
    ruff check . --fix --exit-non-zero-on-fix
    @echo "Applying Ruff formatting..."
    ruff format .

# Alias for lint
style: lint

# Check formatting without applying
format-check:
    @echo "Checking formatting with Ruff..."
    ruff format . --check

# Placeholder for tests when they are added
test:
    @echo "No tests configured yet. Placeholder for: pytest"
    # pytest

# Placeholder for mypy checks
typecheck:
    @echo "Type checking with mypy..."
    mypy . --config-file pyproject.toml

# Clean build artifacts and caches
clean:
    @echo "Cleaning up project..."
    find . -type f -name '*.py[co]' -delete
    find . -type d -name '__pycache__' -delete
    rm -rf .mypy_cache
    rm -rf .pytest_cache
    rm -rf .ruff_cache
    # Add other clean commands as needed (e.g., build directories)

# List available tasks (alternative to default)
list:
    @just --list --unsorted
