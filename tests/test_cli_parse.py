"""Tests for CLI parse and parse-all commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from leizilla.cli import app
from leizilla.parser import ParseResult

runner = CliRunner()

_IA_ID = "leizilla-raw-ro-assembleia-coddoc-00001"
_PARSED_ID = "leizilla-ro-lei-00042-2024"
_VALID_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
    ' urn-lex="urn:lex:br;rondonia:estadual:lei:2024-01-01;42"'
    ' vigente-em="2026-05-22">'
    '<dispositivo path="ementa">'
    "<versao><texto>Lei de teste.</texto>"
    f'<fonte ia-id="{_IA_ID}"/></versao>'
    "</dispositivo>"
    "</lei>"
)
_PARSED_META = {
    "leizilla_meta_version": "0.1",
    "ia_id_raw": _IA_ID,
    "ia_id_parsed": _PARSED_ID,
    "parse_method": "claude-haiku-4-5",
    "confianca_parse_global": 0.9,
    "ente": "ro",
    "tipo": "lei",
}


def _make_parse_result() -> ParseResult:
    return ParseResult(
        xml=_VALID_XML,
        parsed_meta=_PARSED_META,
        confidence=0.9,
        ia_id_parsed=_PARSED_ID,
        input_tokens=100,
        output_tokens=200,
    )


class TestCmdParseUpload:
    def test_parse_without_upload_does_not_call_publisher(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_make_parse_result()),
        ):
            result = runner.invoke(
                app,
                ["parse", "--raw-id", _IA_ID, "--ente", "ro", "--no-upload"],
            )
        assert result.exit_code == 0
        assert "Parse OK" in result.output
        assert "Upload" not in result.output

    def test_parse_with_upload_calls_publisher(self):
        upload_result = {
            "success": True,
            "ia_id": _PARSED_ID,
            "ia_url": f"https://archive.org/details/{_PARSED_ID}",
        }
        mock_publisher = MagicMock()
        mock_publisher.upload_parsed.return_value = upload_result

        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_make_parse_result()),
            patch(
                "leizilla.publisher.InternetArchivePublisher",
                return_value=mock_publisher,
            ),
        ):
            result = runner.invoke(
                app,
                ["parse", "--raw-id", _IA_ID, "--ente", "ro", "--upload"],
            )

        assert result.exit_code == 0
        assert "Parse OK" in result.output
        assert "Upload OK" in result.output
        mock_publisher.upload_parsed.assert_called_once_with(
            _PARSED_ID, _VALID_XML, _PARSED_META
        )

    def test_parse_upload_failure_reported(self):
        mock_publisher = MagicMock()
        mock_publisher.upload_parsed.return_value = {
            "success": False,
            "error": "credentials missing",
        }

        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_make_parse_result()),
            patch(
                "leizilla.publisher.InternetArchivePublisher",
                return_value=mock_publisher,
            ),
        ):
            result = runner.invoke(
                app,
                ["parse", "--raw-id", _IA_ID, "--ente", "ro", "--upload"],
            )

        assert result.exit_code == 0
        assert "Upload falhou" in result.output

    def test_parse_no_ocr_exits_1(self):
        with patch("leizilla.parser.fetch_ocr", return_value=None):
            result = runner.invoke(
                app,
                ["parse", "--raw-id", _IA_ID, "--ente", "ro"],
            )
        assert result.exit_code == 1
        assert "OCR não disponível" in result.output

    def test_parse_low_confidence_exits_1(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=None),
        ):
            result = runner.invoke(
                app,
                ["parse", "--raw-id", _IA_ID, "--ente", "ro"],
            )
        assert result.exit_code == 1
        assert "Parse falhou" in result.output


class TestCmdParseAll:
    def _pending_lei(self) -> dict:
        return {
            "id": "ro-lei-2024-001",
            "titulo": "Lei 42/2024",
            "ente": "ro",
            "url_pdf_ia": f"https://archive.org/details/{_IA_ID}",
        }

    def test_no_pending_exits_cleanly(self, tmp_path):
        with patch(
            "leizilla.storage.DuckDBStorage.get_leis_pending_parse",
            return_value=[],
        ):
            result = runner.invoke(app, ["parse-all", "--ente", "ro"])

        assert result.exit_code == 0
        assert "Nenhuma lei pendente" in result.output

    def test_processes_pending_and_updates_db(self, tmp_path):
        upload_result = {
            "success": True,
            "ia_id": _PARSED_ID,
            "ia_url": f"https://archive.org/details/{_PARSED_ID}",
        }
        mock_publisher = MagicMock()
        mock_publisher.upload_parsed.return_value = upload_result
        mock_db = MagicMock()
        mock_db.get_leis_pending_parse.return_value = [self._pending_lei()]

        with (
            patch("leizilla.storage.DuckDBStorage", return_value=mock_db),
            patch(
                "leizilla.publisher.InternetArchivePublisher",
                return_value=mock_publisher,
            ),
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_make_parse_result()),
        ):
            result = runner.invoke(app, ["parse-all", "--ente", "ro"])

        assert result.exit_code == 0
        assert "1/1 com sucesso" in result.output
        mock_db.update_lei.assert_called_once_with(
            "ro-lei-2024-001",
            {"url_parsed_ia": f"https://archive.org/details/{_PARSED_ID}"},
        )

    def test_skips_lei_when_no_ocr(self):
        mock_publisher = MagicMock()
        mock_db = MagicMock()
        mock_db.get_leis_pending_parse.return_value = [self._pending_lei()]

        with (
            patch("leizilla.storage.DuckDBStorage", return_value=mock_db),
            patch(
                "leizilla.publisher.InternetArchivePublisher",
                return_value=mock_publisher,
            ),
            patch("leizilla.parser.fetch_ocr", return_value=None),
        ):
            result = runner.invoke(app, ["parse-all", "--ente", "ro"])

        assert result.exit_code == 0
        assert "OCR não disponível" in result.output
        assert "0/1 com sucesso" in result.output
        mock_publisher.upload_parsed.assert_not_called()

    def test_skips_lei_when_parse_fails(self):
        mock_publisher = MagicMock()
        mock_db = MagicMock()
        mock_db.get_leis_pending_parse.return_value = [self._pending_lei()]

        with (
            patch("leizilla.storage.DuckDBStorage", return_value=mock_db),
            patch(
                "leizilla.publisher.InternetArchivePublisher",
                return_value=mock_publisher,
            ),
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=None),
        ):
            result = runner.invoke(app, ["parse-all", "--ente", "ro"])

        assert result.exit_code == 0
        assert "Parse falhou" in result.output
        assert "0/1 com sucesso" in result.output
        mock_publisher.upload_parsed.assert_not_called()

    def test_exits_1_on_runtime_error(self):
        mock_db = MagicMock()
        mock_db.get_leis_pending_parse.return_value = [self._pending_lei()]
        mock_publisher = MagicMock()

        with (
            patch("leizilla.storage.DuckDBStorage", return_value=mock_db),
            patch(
                "leizilla.publisher.InternetArchivePublisher",
                return_value=mock_publisher,
            ),
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch(
                "leizilla.parser.parse_law",
                side_effect=RuntimeError("ANTHROPIC_API_KEY not configured"),
            ),
        ):
            result = runner.invoke(app, ["parse-all", "--ente", "ro"])

        assert result.exit_code == 1
        assert "Erro de configuração" in result.output
