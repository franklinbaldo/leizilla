"""Hygiene check over .github/workflows/*.yml — no dependency on the CLI/YAML libs.

`leizilla discover --ente ro` (no `--fonte`) instantiates every discovery
strategy in the manifest, including `PlaywrightCrawlerDiscovery` for
`assembleia` (~5000 pages crawled sequentially). Confirmed in production
(2026-07-11 and 2026-07-12) to hang for hours and get cancelled by the job
timeout without ever reaching harvest — see issue #105. Every workflow that
invokes `discover` must pin `--fonte` so `assembleia` only runs via an
explicit manual choice.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_DISCOVER_RE = re.compile(r"\bleizilla\s+discover\b")
_LEIZILLA_INVOCATION_RE = re.compile(r"\bleizilla\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*))?")
_FLAG_RE = re.compile(r"--[a-zA-Z][\w-]*")

# `leizilla wayback-save`'s workflow used `--end`, a flag removed when the
# CLI switched to `--probe-window`-based probing — the cron ran instantly-red
# every week for months and nobody noticed (see the observability test in
# this same file). This introspects the *live* Typer app so any future
# rename/removal of a flag anywhere in the CLI is caught the same way,
# instead of relying on someone remembering to grep every workflow by hand.
_CLI_INTROSPECTION_SCRIPT = r"""
import json
import typer
from leizilla.cli import app

group = typer.main.get_command(app)


def flags_of(cmd):
    flags = set()
    for param in cmd.params:
        flags.update(getattr(param, "opts", []) or [])
        flags.update(getattr(param, "secondary_opts", []) or [])
    return sorted(f for f in flags if f.startswith("--"))


result = {}
for name, cmd in group.commands.items():
    if hasattr(cmd, "commands"):
        for sub_name, sub_cmd in cmd.commands.items():
            result[f"{name} {sub_name}"] = flags_of(sub_cmd)
    else:
        result[name] = flags_of(cmd)

print(json.dumps(result))
"""


def _cli_flag_map() -> dict[str, set[str]]:
    """{command name (e.g. "scrape" or "dev subcmd"): set of valid --flags}."""
    proc = subprocess.run(
        ["uv", "run", "python", "-c", _CLI_INTROSPECTION_SCRIPT],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {cmd: set(flags) for cmd, flags in json.loads(proc.stdout).items()}


def _workflow_files() -> list[Path]:
    """GitHub Actions accepts both `.yml` and `.yaml` — check both so a future
    workflow file doesn't silently escape this check."""
    return sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])


def _logical_lines(text: str) -> list[str]:
    """Join `\\`-continued shell lines so multi-line `run: |` commands are
    checked as one logical command, same as what the shell executes."""
    merged: list[str] = []
    buffer = ""
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
        else:
            merged.append(buffer + line)
            buffer = ""
    if buffer:
        merged.append(buffer)
    return merged


def test_workflows_dir_has_files() -> None:
    """Sanity check so a bad path above can't make the real test pass vacuously."""
    assert _workflow_files()


def test_no_workflow_invokes_discover_without_fonte() -> None:
    offenders = []
    for wf in _workflow_files():
        for line in _logical_lines(wf.read_text(encoding="utf-8")):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if _DISCOVER_RE.search(text) and "--fonte" not in text:
                offenders.append(f"{wf.name}: {text}")
    assert not offenders, (
        "workflow(s) invoke `leizilla discover` without `--fonte` — this "
        "instantiates every discovery strategy including the assembleia "
        "PlaywrightCrawlerDiscovery crawler, which hangs for hours (#105):\n"
        + "\n".join(offenders)
    )


def test_workflow_flags_match_cli_signatures() -> None:
    """Statically validate every `leizilla <cmd> ...` invocation in every
    workflow against the actual Typer command signatures, killing the whole
    class of workflow<->CLI drift bugs (e.g. wayback-save.yml's `--end`,
    which stopped existing when the CLI moved to `--probe-window`)."""
    flag_map = _cli_flag_map()
    offenders = []
    for wf in _workflow_files():
        for line in _logical_lines(wf.read_text(encoding="utf-8")):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            match = _LEIZILLA_INVOCATION_RE.search(text)
            if not match:
                continue
            cmd, maybe_sub = match.group(1), match.group(2)
            nested_key = f"{cmd} {maybe_sub}" if maybe_sub else None
            key = nested_key if nested_key in flag_map else cmd
            valid_flags = flag_map.get(key)
            if valid_flags is None:
                # Unknown command name (e.g. `leizilla --help`) — not this
                # test's job; test_workflows_dir_has_files-style typos in
                # the command itself would surface at run time regardless.
                continue
            used_flags = set(_FLAG_RE.findall(text))
            unknown = used_flags - valid_flags
            if unknown:
                offenders.append(
                    f"{wf.name}: `leizilla {key}` does not accept "
                    f"{sorted(unknown)} (valid: {sorted(valid_flags)}) — line: {text}"
                )
    assert not offenders, (
        "workflow(s) invoke leizilla commands with flags that don't exist "
        "on the current CLI signature:\n" + "\n".join(offenders)
    )
