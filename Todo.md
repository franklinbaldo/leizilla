# Leizilla Project Todo List

## Configuration and Setup
- [x] Task 1: Investigate the purpose of `.claude/settings.local.json` and its role in the project.
- [x] Task 2: Document the permissions granted in `.claude/settings.local.json`.
- [x] Task 3: Create a `.env` file from `.env.example` and populate it with actual values. (Security note: AI should not handle actual secret keys).
- [ ] Task 4: Document how to obtain `IA_ACCESS_KEY` and `IA_SECRET_KEY` for Internet Archive.
- [ ] Task 5: Add validation for environment variables in `config.py` to ensure they are set and have correct types.
- [ ] Task 6: Consider adding more comments to `.env.example` to explain each variable's purpose.
- [ ] Task 21: Ensure Python version `3.12` consistency across project files (`.python-version`, `lint.yml`, `pyproject.toml`).

## Git & Version Control
- [ ] Task 11: Decide if `.claude/settings.local.json` should be in `.gitignore`. If so, remove from index.
- [ ] Task 12: Decide if `uv.lock` should be tracked. If so, ensure it's not in `.gitignore`. (Currently tracked, line in `.gitignore` is commented out).
- [ ] Task 13: Decide if `.python-version` should be in `.gitignore`. (Currently tracked, line in `.gitignore` is commented out).
- [ ] Task 14: Review "Leizilla specific" section in `.gitignore` for continued correctness.
- [ ] Task 15: Review `temp/` and `logs/` entries in `.gitignore` for appropriateness and specificity.
- [ ] Task 16: Clean up unused commented-out entries for lock files (e.g., `Pipfile.lock`, `poetry.lock`) in `.gitignore`.

## CI/CD & Linting/Formatting
- [ ] Task 7: Verify `python-version` in `.github/workflows/lint.yml` ('3.12') matches `project.requires-python` in `pyproject.toml`.
- [ ] Task 8: Add a Mypy type checking step to the `.github/workflows/lint.yml` workflow.
- [ ] Task 9: Investigate if enabling caching for `astral-sh/setup-uv@v1` in `.github/workflows/lint.yml` would speed up the workflow.
- [ ] Task 10: Confirm if `main` is the only default/target branch in `.github/workflows/lint.yml` or if others (e.g., `develop`) should be included.
- [ ] Task 17: Align Ruff version in `.pre-commit-config.yaml` (currently `v0.4.4`) with version in `pyproject.toml`.
- [ ] Task 18: Clarify `args: []` (commented out) for `ruff-format` hook in `.pre-commit-config.yaml`; remove if no args needed.
- [ ] Task 19: Ensure `autofix_commit_msg` and `autoupdate_commit_msg` in `.pre-commit-config.yaml` align with project's commit message conventions (e.g., Conventional Commits).
- [ ] Task 20: Add a Mypy pre-commit hook to `.pre-commit-config.yaml`.
- [ ] Task 27: Ensure Mypy is configured for strict checking as stated in `CLAUDE.md` and integrated into CI/pre-commit hooks.
- [ ] Task 28: Enforce Conventional Commits format (mentioned in `CLAUDE.md`), possibly via a linter in pre-commit or CI.

## Documentation & Commands
- [ ] Task 22: Re-confirm decision on tracking `.python-version` in git (related to Task 13).
- [ ] Task 23: Standardize the `leizilla-setup` command across documentation (`uv run leizilla-setup` vs `uv run leizilla dev setup`). Verify correct command.
- [ ] Task 24: Clarify and standardize CLI command syntax between `CLAUDE.md` and `README.md` (e.g., `leizilla discover --origem rondonia` vs `leizilla-discover rondonia`). Determine preferred syntax.
- [ ] Task 25: Document or consolidate the two CLI usage methods (direct `uv run leizilla <command>` vs simplified `uv run leizilla-<action>`) described in `CLAUDE.md`.
- [ ] Task 26: Investigate `just` commands mentioned in `CLAUDE.md` (`just test`, `just check`) vs `uv run leizilla dev ...` commands. Check for a `Justfile` and clarify primary task runner.
- [ ] Task 29: Remove or update potentially outdated line number references for key files in `CLAUDE.md`'s "Development Status" section.
- [ ] Task 30: Clarify current status of Rondônia indexing (is it "Implementado" as per `README.md` or "Q3/2025" target as per `CLAUDE.md`?). Update documentation for consistency.
