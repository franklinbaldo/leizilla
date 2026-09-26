"""Tests for M10.1: fetch-all-parsed — list_parsed_ia_ids + fetch_parsed_xml + CLI."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from leizilla.cli import app
from leizilla.publisher import fetch_parsed_xml, list_parsed_ia_ids

runner = CliRunner()


@pytest.fixture(autouse=True)
def _not_superseded_by_default():
    """Issue #308's superseded-check adds one network call per candidate id
    in cmd_fetch_all_parsed; default it to "not superseded" (fail-open value)
    so every pre-existing test in this file stays offline/deterministic
    without having to know about it. Tests that actually exercise the
    superseded-skip path override this explicitly."""
    with patch("leizilla.publisher.get_parsed_superseded_by", return_value=None):
        yield


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
        assert (
            "Baixados: 2, Pulados (já existiam): 0, "
            "Substituídos (superseded): 0, Erros: 0" in result.output
        )
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
        assert (
            "Baixados: 0, Pulados (já existiam): 1, "
            "Substituídos (superseded): 0, Erros: 0" in result.output
        )
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
        assert (
            "Baixados: 1, Pulados (já existiam): 0, "
            "Substituídos (superseded): 0, Erros: 1" in result.output
        )

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

    def test_skips_items_marked_superseded(self, tmp_path: Path):
        """Issue #308: an item marked superseded_by another id must be
        excluded from the download (and therefore from consolidate's
        Parquet) instead of being fetched and double-counted."""
        ids = ["leizilla-ro-lei-00000-1984", "leizilla-ro-lei-00025-1984"]

        def superseded_side(ia_id: str):
            return (
                "leizilla-ro-lei-00025-1984"
                if ia_id == "leizilla-ro-lei-00000-1984"
                else None
            )

        with (
            patch("leizilla.publisher.list_parsed_ia_ids", return_value=ids),
            patch(
                "leizilla.publisher.get_parsed_superseded_by",
                side_effect=superseded_side,
            ),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                ["fetch-all-parsed", "--ente", "ro", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert (
            "Baixados: 1, Pulados (já existiam): 0, "
            "Substituídos (superseded): 1, Erros: 0" in result.output
        )
        assert "[SUPERSEDED] leizilla-ro-lei-00000-1984" in result.output
        mock_fetch.assert_called_once_with(
            "leizilla-ro-lei-00025-1984",
            tmp_path / "leizilla-ro-lei-00025-1984.xml",
        )


class TestCmdRetractParsed:
    def test_marks_old_item_superseded(self):
        with patch(
            "leizilla.publisher.InternetArchivePublisher.mark_parsed_superseded",
            return_value={
                "success": True,
                "ia_id": "leizilla-ro-lei-00000-1984",
                "superseded_by": "leizilla-ro-lei-00025-1984",
            },
        ) as mock_mark:
            result = runner.invoke(
                app,
                [
                    "retract-parsed",
                    "--ia-id-old",
                    "leizilla-ro-lei-00000-1984",
                    "--ia-id-new",
                    "leizilla-ro-lei-00025-1984",
                    "--reason",
                    "numero corrigido, ver #308",
                ],
            )

        assert result.exit_code == 0
        assert "OK" in result.output
        mock_mark.assert_called_once_with(
            "leizilla-ro-lei-00000-1984",
            "leizilla-ro-lei-00025-1984",
            reason="numero corrigido, ver #308",
        )

    def test_exits_nonzero_on_failure(self):
        with patch(
            "leizilla.publisher.InternetArchivePublisher.mark_parsed_superseded",
            return_value={"success": False, "error": "boom"},
        ):
            result = runner.invoke(
                app,
                [
                    "retract-parsed",
                    "--ia-id-old",
                    "leizilla-ro-lei-00000-1984",
                    "--ia-id-new",
                    "leizilla-ro-lei-00025-1984",
                ],
            )

        assert result.exit_code == 1
        assert "boom" in result.output


class TestCmdFetchAllParsedExtraIdsFile:
    """--extra-ids-file: union hand-off para fechar o lag de indexação do IA
    (issue #233) — fetch_parsed_xml busca por id direto, não pela busca."""

    def test_unions_extra_ids_not_yet_indexed_by_search(self, tmp_path: Path):
        # A busca do IA (list_parsed_ia_ids) ainda não indexou o item recém
        # uploadado nesta mesma run; o extra-ids-file supre o gap.
        ids_from_search = ["leizilla-ro-lei-00001-2001"]
        extra_ids_file = tmp_path / "extra-ids.txt"
        extra_ids_file.write_text("leizilla-ro-lei-00002-2002\n", encoding="utf-8")

        with (
            patch(
                "leizilla.publisher.list_parsed_ia_ids", return_value=ids_from_search
            ),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                [
                    "fetch-all-parsed",
                    "--ente",
                    "ro",
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--extra-ids-file",
                    str(extra_ids_file),
                ],
            )

        assert result.exit_code == 0
        fetched_ids = {call.args[0] for call in mock_fetch.call_args_list}
        assert fetched_ids == {
            "leizilla-ro-lei-00001-2001",
            "leizilla-ro-lei-00002-2002",
        }
        assert mock_fetch.call_count == 2

    def test_does_not_double_download_id_already_in_search_results(
        self, tmp_path: Path
    ):
        ids_from_search = ["leizilla-ro-lei-00001-2001"]
        extra_ids_file = tmp_path / "extra-ids.txt"
        # Mesmo id já presente na busca — não deve gerar download duplicado.
        extra_ids_file.write_text("leizilla-ro-lei-00001-2001\n", encoding="utf-8")

        with (
            patch(
                "leizilla.publisher.list_parsed_ia_ids", return_value=ids_from_search
            ),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                [
                    "fetch-all-parsed",
                    "--ente",
                    "ro",
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--extra-ids-file",
                    str(extra_ids_file),
                ],
            )

        assert result.exit_code == 0
        assert mock_fetch.call_count == 1

    def test_missing_extra_ids_file_is_ignored_fail_open(self, tmp_path: Path):
        ids_from_search = ["leizilla-ro-lei-00001-2001"]
        missing_file = tmp_path / "does-not-exist.txt"

        with (
            patch(
                "leizilla.publisher.list_parsed_ia_ids", return_value=ids_from_search
            ),
            patch("leizilla.publisher.fetch_parsed_xml", return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "fetch-all-parsed",
                    "--ente",
                    "ro",
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--extra-ids-file",
                    str(missing_file),
                ],
            )

        assert result.exit_code == 0
        assert "Encontrados 1 itens" in result.output

    def test_empty_extra_ids_file_is_ignored(self, tmp_path: Path):
        ids_from_search = ["leizilla-ro-lei-00001-2001"]
        empty_file = tmp_path / "extra-ids.txt"
        empty_file.write_text("", encoding="utf-8")

        with (
            patch(
                "leizilla.publisher.list_parsed_ia_ids", return_value=ids_from_search
            ),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                [
                    "fetch-all-parsed",
                    "--ente",
                    "ro",
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--extra-ids-file",
                    str(empty_file),
                ],
            )

        assert result.exit_code == 0
        assert mock_fetch.call_count == 1

    def test_extra_ids_alone_are_enough_even_if_search_finds_nothing(
        self, tmp_path: Path
    ):
        # Se list_parsed_ia_ids falhar/vier vazio (fail-open) mas ainda assim
        # tivermos um hand-off da mesma run, não devemos desistir.
        extra_ids_file = tmp_path / "extra-ids.txt"
        extra_ids_file.write_text("leizilla-ro-lei-00099-2020\n", encoding="utf-8")

        with (
            patch("leizilla.publisher.list_parsed_ia_ids", return_value=[]),
            patch(
                "leizilla.publisher.fetch_parsed_xml", return_value=True
            ) as mock_fetch,
        ):
            result = runner.invoke(
                app,
                [
                    "fetch-all-parsed",
                    "--ente",
                    "ro",
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--extra-ids-file",
                    str(extra_ids_file),
                ],
            )

        assert result.exit_code == 0
        mock_fetch.assert_called_once_with(
            "leizilla-ro-lei-00099-2020",
            tmp_path / "out" / "leizilla-ro-lei-00099-2020.xml",
        )
