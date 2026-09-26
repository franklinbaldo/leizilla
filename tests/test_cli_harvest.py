"""CLI wiring for `harvest`: failure-reason visibility (issue #297).

Per-item print()/logger.warning() calls inside the harvest loop produced zero
output in a live CI run for federal/planalto (10/10 failures, no diagnostic
line surfaced despite both mechanisms being confirmed present and configured).
`stats["items"]` already carries a `reason` per failed item regardless of
whether any per-iteration output survives — `cmd_harvest` must print a
breakdown of it after the loop, at the same point where the "Sucesso"/"Falhas"
counts are already proven to show up reliably in CI.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from leizilla.cli import app

runner = CliRunner()


def _stats(items):
    success = sum(1 for i in items if i["status"] == "ok")
    failed = sum(1 for i in items if i["status"] == "failed")
    robots = sum(1 for i in items if i["status"] == "robots-blocked")
    return {
        "success": success,
        "failed": failed,
        "robots-blocked": robots,
        "items": items,
    }


def test_harvest_prints_failure_reason_breakdown():
    stats = _stats(
        [
            {"status": "failed", "chave": "mpv-1", "reason": "fetch-failed"},
            {"status": "failed", "chave": "mpv-2", "reason": "fetch-failed"},
            {"status": "failed", "chave": "mpv-3", "reason": "upload-failed"},
            {"status": "ok", "chave": "mpv-4", "ia_id": "x"},
        ]
    )
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = runner.invoke(app, ["harvest"])

    assert result.exit_code == 0
    assert "Falhas: 3" in result.output
    assert "fetch-failed: 2" in result.output
    assert "upload-failed: 1" in result.output


def test_harvest_omits_reason_breakdown_when_no_failures():
    stats = _stats([{"status": "ok", "chave": "mpv-1", "ia_id": "x"}])
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = runner.invoke(app, ["harvest"])

    assert result.exit_code == 0
    assert "Falhas: 0" in result.output
    assert "reason" not in result.output.lower()
