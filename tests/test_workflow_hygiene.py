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

import re
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

_DISCOVER_RE = re.compile(r"\bleizilla\s+discover\b")


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
