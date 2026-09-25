from __future__ import annotations

from typer.testing import CliRunner

from leizilla.cli import app


runner = CliRunner()


def test_wayback_save_max_submissions_bounds_dry_run(monkeypatch) -> None:
    manifest = {
        "fontes": {
            "casacivil": {
                "discovery": [
                    {"strategy": "wayback-cdx", "prefix": "https://example.test/"}
                ],
                "probe": [
                    {
                        "templates": ["https://example.test/lei{num}.pdf"],
                        "start": 1,
                        "head_check": False,
                    }
                ],
            }
        }
    }
    monkeypatch.setattr("leizilla.discovery.load_manifest", lambda _ente: manifest)
    monkeypatch.setattr(
        "leizilla.discovery.parse_filename", lambda _name: ("lei", 1)
    )
    monkeypatch.setattr(
        "leizilla.wayback.fetch_cdx_archived_urls", lambda _prefix: set()
    )

    result = runner.invoke(
        app,
        [
            "wayback-save",
            "--ente",
            "ro",
            "--fonte",
            "casacivil",
            "--tipo",
            "lei",
            "--start",
            "1",
            "--probe-window",
            "10",
            "--skip-head-check",
            "--dry-run",
            "--max-submissions",
            "3",
            "--delay",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.count("[DRY-RUN] Enviaria para salvar") == 3
    assert "URLs novas enviadas para salvar: 3" in result.output
    assert "Orçamento de submissões atingido (3)" in result.output


def test_wayback_save_rejects_non_positive_budget() -> None:
    result = runner.invoke(app, ["wayback-save", "--max-submissions", "0"])
    assert result.exit_code != 0
