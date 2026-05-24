"""Tests for M10.1: fetch-all-parsed — list_parsed_ia_ids + fetch_parsed_xml + CLI."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from leizilla.cli import app
from leizilla.publisher import fetch_parsed_xml, list_parsed_ia_ids

runner = CliRunner()


def _scrape_response(identifiers: list[str], cursor: str | None = None) -> bytes:
    data: dict = {"items": [{"identifier": id_} for id_ in identifiers]}
    if cursor:
        data["cursor"] = cursor
    return json.dumps(data).encode()


class TestListParsedIaIds:
    def test_basic_returns_parsed_ids(self):
        response = _scrape_response(
            ["leizilla-ro-lei-00001-2001", "leizilla-ro-lei-00002-2002"]
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ids = list_parsed_ia_ids("ro")

        assert ids == ["leizilla-ro-lei-00001-2001", "leizilla-ro-lei-00002-2002"]

    def test_paginates_via_cursor(self):
        page1 = _scrape_response(["leizilla-ro-lei-00001-2001"], cursor="abc123")
        page2 = _scrape_response(["leizilla-ro-lei-00002-2002"])

        call_count = 0

        def urlopen_side(req, timeout=None):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.read.return_value = page1 if call_count == 1 else page2
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=urlopen_side):
            ids = list_parsed_ia_ids("ro")

        assert ids == ["leizilla-ro-lei-00001-2001", "leizilla-ro-lei-00002-2002"]
        assert call_count == 2

    def test_network_error_returns_empty_list(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            ids = list_parsed_ia_ids("ro")
        assert ids == []

    def test_empty_collection(self):
        response = _scrape_response([])
        mock_resp = MagicMock()
        mock_resp.read.return_value = response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ids = list_parsed_ia_ids("ro")

        assert ids == []


class TestFetchParsedXml:
    def test_success_writes_file(self, tmp_path: Path):
        xml_content = (
            b"<lei><header urn='urn:lex:br;rondonia:estadual:lei:2001-01-01;1'/></lei>"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = xml_content
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        dest = tmp_path / "leizilla-ro-lei-00001-2001.xml"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_parsed_xml("leizilla-ro-lei-00001-2001", dest)

        assert result is True
        assert dest.read_bytes() == xml_content

    def test_network_error_returns_false(self, tmp_path: Path):
        dest = tmp_path / "leizilla-ro-lei-00001-2001.xml"
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = fetch_parsed_xml("leizilla-ro-lei-00001-2001", dest)

        assert result is False
        assert not dest.exists()

    def test_uses_correct_url(self, tmp_path: Path):
        captured_url = []

        def urlopen_side(req, timeout=None):
            captured_url.append(req.full_url)
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"<lei/>"
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        dest = tmp_path / "leizilla-ro-lei-00042-2003.xml"
        with patch("urllib.request.urlopen", side_effect=urlopen_side):
            fetch_parsed_xml("leizilla-ro-lei-00042-2003", dest)

        assert (
            captured_url[0]
            == "https://archive.org/download/leizilla-ro-lei-00042-2003/law.xml"
        )


class TestCmdFetchAllParsed:
    def test_downloads_xmls_to_output_dir(self, tmp_path: Path):
        ids = ["leizilla-ro-lei-00001-2001", "leizilla-ro-lei-00002-2002"]

        with (
            patch("leizilla.publisher.list_parsed_ia_ids", return_value=ids),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                ["fetch-all-parsed", "--ente", "ro", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert "Encontrados 2 itens" in result.output
        assert "Baixados: 2, Pulados (já existiam): 0, Erros: 0" in result.output
        assert mock_fetch.call_count == 2

    def test_skips_already_existing_files(self, tmp_path: Path):
        ids = ["leizilla-ro-lei-00001-2001"]
        existing = tmp_path / "leizilla-ro-lei-00001-2001.xml"
        existing.write_text("<lei/>")

        with (
            patch("leizilla.publisher.list_parsed_ia_ids", return_value=ids),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                ["fetch-all-parsed", "--ente", "ro", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert "Baixados: 0, Pulados (já existiam): 1, Erros: 0" in result.output
        mock_fetch.assert_not_called()

    def test_counts_errors_per_item(self, tmp_path: Path):
        ids = ["leizilla-ro-lei-00001-2001", "leizilla-ro-lei-00002-2002"]

        def fetch_side(ia_id: str, path: Path) -> bool:
            return ia_id != "leizilla-ro-lei-00001-2001"

        with (
            patch("leizilla.publisher.list_parsed_ia_ids", return_value=ids),
            patch("leizilla.publisher.fetch_parsed_xml", side_effect=fetch_side),
        ):
            result = runner.invoke(
                app,
                ["fetch-all-parsed", "--ente", "ro", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert "Baixados: 1, Pulados (já existiam): 0, Erros: 1" in result.output

    def test_no_items_found_exits_cleanly(self, tmp_path: Path):
        with patch("leizilla.publisher.list_parsed_ia_ids", return_value=[]):
            result = runner.invoke(
                app,
                ["fetch-all-parsed", "--ente", "ro", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert "Nenhum item parsed encontrado" in result.output

    def test_creates_output_dir_if_missing(self, tmp_path: Path):
        new_dir = tmp_path / "subdir" / "xmls"
        assert not new_dir.exists()

        with (
            patch("leizilla.publisher.list_parsed_ia_ids", return_value=[]),
        ):
            result = runner.invoke(
                app,
                ["fetch-all-parsed", "--ente", "ro", "--output-dir", str(new_dir)],
            )

        assert result.exit_code == 0
        assert new_dir.exists()
