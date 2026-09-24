"""Testes para o comando `consolidate` (issue #118: gate XSD no boundary do ETL)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from leizilla.cli import app

runner = CliRunner()

_VALID_XML = (
    Path(__file__).parent / "fixtures" / "leizilla_xml" / "simple.xml"
).read_text(encoding="utf-8")


def test_consolidate_succeeds_on_valid_xml(tmp_path: Path) -> None:
    xml_dir = tmp_path / "parsed"
    xml_dir.mkdir()
    (xml_dir / "leizilla-ro-lei-00001-2020.xml").write_text(
        _VALID_XML, encoding="utf-8"
    )
    output = tmp_path / "out.parquet"

    result = runner.invoke(
        app, ["consolidate", str(xml_dir), "--output", str(output), "--ente", "ro"]
    )

    assert result.exit_code == 0, result.output
    assert output.exists()


def test_consolidate_rejects_structurally_invalid_xml(tmp_path: Path) -> None:
    """A XML that fails the XSD gate must not reach the published Parquet."""
    xml_dir = tmp_path / "parsed"
    xml_dir.mkdir()
    (xml_dir / "leizilla-ro-lei-00001-2020.xml").write_text(
        _VALID_XML, encoding="utf-8"
    )
    (xml_dir / "leizilla-ro-lei-00002-2020.xml").write_text(
        "<not-a-lei-document/>", encoding="utf-8"
    )
    output = tmp_path / "out.parquet"

    result = runner.invoke(
        app, ["consolidate", str(xml_dir), "--output", str(output), "--ente", "ro"]
    )

    assert result.exit_code == 1
    assert "leizilla-ro-lei-00002-2020.xml" in result.output


def test_consolidate_skips_but_reports_xsd_failure(tmp_path: Path) -> None:
    """Simulates the gate rejecting one of several files (mocked, no real xmllint)."""
    xml_dir = tmp_path / "parsed"
    xml_dir.mkdir()
    (xml_dir / "a.xml").write_text(_VALID_XML, encoding="utf-8")
    (xml_dir / "b.xml").write_text(_VALID_XML, encoding="utf-8")
    output = tmp_path / "out.parquet"

    def fake_gate(xml_content: str, warn_prefix: str = "") -> bool:
        return "b.xml" not in warn_prefix

    with patch("leizilla.cli._xsd_gate", side_effect=fake_gate):
        result = runner.invoke(
            app,
            ["consolidate", str(xml_dir), "--output", str(output), "--ente", "ro"],
        )

    assert result.exit_code == 1
    assert "1/2" in result.output
    assert output.exists()  # the valid file alone still gets published
