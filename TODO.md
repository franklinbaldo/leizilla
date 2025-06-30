# Leizilla Project Todo List

## Configuration and Setup
- [ ] Document how to obtain `IA_ACCESS_KEY` and `IA_SECRET_KEY` for Internet Archive.
- [ ] Add validation for environment variables in `config.py` to ensure they are set and have correct types.
- [ ] Consider adding more comments to `.env.example` to explain each variable's purpose.
- [ ] Ensure Python version consistency across all relevant project files (e.g., `.python-version`, `lint.yml`, `pyproject.toml`).

## Git & Version Control
- [ ] Review "Leizilla specific" section in `.gitignore` for continued correctness.
- [ ] Review `temp/` and `logs/` entries in `.gitignore` for appropriateness and specificity.

## CI/CD & Linting/Formatting
- [ ] Investigate if enabling caching for `astral-sh/setup-uv@v1` in `.github/workflows/lint.yml` would speed up the workflow.
- [ ] Confirm if `main` is the only default/target branch in `.github/workflows/lint.yml` or if others (e.g., `develop`) should be included.
- [ ] Clarify `args: []` (commented out) for `ruff-format` hook in `.pre-commit-config.yaml`; remove if no args needed.
- [ ] Ensure `autofix_commit_msg` and `autoupdate_commit_msg` in `.pre-commit-config.yaml` align with project's commit message conventions (e.g., Conventional Commits).
- [ ] Ensure Mypy is configured for strict checking as stated in `CLAUDE.md` and integrated into CI/pre-commit hooks.
- [ ] Enforce Conventional Commits format (mentioned in `CLAUDE.md`), possibly via a linter in pre-commit or CI.

## Documentation & Commands
- [ ] Remove or update potentially outdated line number references for key files in `CLAUDE.md`'s "Development Status" section.
- [ ] Clarify current status of Rondônia indexing (is it "Implementado" as per `README.md` or "Q3/2025" target as per `CLAUDE.md`?). Update documentation for consistency.