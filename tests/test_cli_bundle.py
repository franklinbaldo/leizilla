"""Testes para o comando cmd_bundle_raw."""

from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from leizilla.cli import app

runner = CliRunner()


def test_bundle_raw_no_downloaded_resources(tmp_path):
    with (
        patch("leizilla.storage.DuckDBStorage") as mock_db_class,
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        mock_db = MagicMock()
        mock_db.get_downloaded_resources.return_value = []
        mock_db_class.return_value = mock_db

        result = runner.invoke(
            app,
            ["bundle-raw", "--ente", "ro", "--fonte", "casacivil", "--limit", "10"],
        )
    assert result.exit_code == 0
    assert "Nenhum recurso com status 'downloaded' encontrado" in result.output


def test_bundle_raw_success(tmp_path):
    res_data = [
        {
            "url": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf",
            "ente": "ro",
            "fonte": "casacivil",
            "tipo_documento": "lei",
            "chave": "L5120",
            "wayback_snapshot": "http://web.archive.org/web/L5120.pdf",
        }
    ]

    with (
        patch("leizilla.storage.DuckDBStorage") as mock_db_class,
        patch("leizilla.publisher.InternetArchivePublisher") as mock_pub_class,
        patch("leizilla.wayback.fetch_bytes", return_value=b"pdf content"),
    ):
        mock_db = MagicMock()
        mock_db.get_downloaded_resources.return_value = res_data
        mock_db_class.return_value = mock_db

        mock_pub = MagicMock()
        mock_pub.upload_to_archive.return_value = {"success": True}
        mock_pub_class.return_value = mock_pub

        result = runner.invoke(
            app,
            ["bundle-raw", "--ente", "ro", "--fonte", "casacivil", "--limit", "10"],
        )
    assert result.exit_code == 0
    assert "Consolidação concluída: 1 com sucesso, 0 falhas" in result.output
    mock_db.update_resource_status.assert_called_once_with(
        res_data[0]["url"], "bundled"
    )
    mock_pub.upload_to_archive.assert_called_once()
