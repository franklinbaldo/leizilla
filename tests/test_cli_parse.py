"""Testes para cmd_parse --upload, cmd_parse_all, e _xsd_gate."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from leizilla.cli import app, _xsd_gate

runner = CliRunner()

_PARSE_RESULT = MagicMock(
    xml="<lei/>",
    parsed_meta={"ente": "ro", "tipo": "lei"},
    confidence=0.9,
    ia_id_parsed="leizilla-ro-lei-00042-1990",
    input_tokens=100,
    output_tokens=200,
)

_UPLOAD_OK = {
    "success": True,
    "ia_id": "leizilla-ro-lei-00042-1990",
    "ia_url": "https://archive.org/details/leizilla-ro-lei-00042-1990",
}
_UPLOAD_FAIL = {
    "success": False,
    "error": "network error",
    "ia_id": "leizilla-ro-lei-00042-1990",
}


class TestXsdGate:
    def test_returns_true_when_schema_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "leizilla.cli.Path",
            lambda *a, **kw: tmp_path / "nonexistent_schema.xsd",
        )
        assert _xsd_gate("<lei/>") is True

    def test_returns_true_when_xmllint_not_found(self, tmp_path):
        schema = tmp_path / "leizilla-v0.1.xsd"
        schema.write_text("<xs:schema/>")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("leizilla.cli.Path") as mock_path:
                mock_path.return_value.__truediv__ = MagicMock(return_value=schema)
                mock_path.return_value.parents = [None, None, tmp_path]
                result = _xsd_gate("<lei/>")
        assert result is True

    def test_returns_true_on_xmllint_success(self):
        with (
            patch("subprocess.run") as mock_run,
            patch.object(Path, "exists", return_value=True),
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _xsd_gate("<lei/>")
        assert result is True

    def test_returns_false_on_xmllint_failure(self):
        with (
            patch("subprocess.run") as mock_run,
            patch.object(Path, "exists", return_value=True),
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="validation error")
            result = _xsd_gate("<bad/>")
        assert result is False


class TestCmdParseUpload:
    def _mock_parse(self, ocr_return="OCR text", parse_return=_PARSE_RESULT):
        return {
            "leizilla.cli.fetch_ocr": ocr_return,
            "leizilla.cli.parse_law": parse_return,
        }

    def test_parse_without_upload_outputs_xml(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
        ):
            result = runner.invoke(
                app, ["parse", "--raw-id", "leizilla-raw-ro-assembleia-coddoc-00042"]
            )
        assert result.exit_code == 0
        assert "<lei/>" in result.output

    def test_upload_flag_calls_upload_parsed(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
            patch("leizilla.cli._xsd_gate", return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "parse",
                    "--raw-id",
                    "leizilla-raw-ro-assembleia-coddoc-00042",
                    "--upload",
                ],
            )
        assert result.exit_code == 0
        assert "Uploaded" in result.output
        assert "archive.org" in result.output

    def test_upload_flag_exits_1_on_upload_failure(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_FAIL,
            ),
            patch("leizilla.cli._xsd_gate", return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "parse",
                    "--raw-id",
                    "leizilla-raw-ro-assembleia-coddoc-00042",
                    "--upload",
                ],
            )
        assert result.exit_code == 1
        assert "Upload falhou" in result.output

    def test_no_upload_without_flag(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed"
            ) as mock_upload,
        ):
            runner.invoke(
                app, ["parse", "--raw-id", "leizilla-raw-ro-assembleia-coddoc-00042"]
            )
        mock_upload.assert_not_called()

    def test_exits_1_on_missing_ocr(self):
        with patch("leizilla.parser.fetch_ocr", return_value=None):
            result = runner.invoke(
                app, ["parse", "--raw-id", "leizilla-raw-ro-assembleia-coddoc-99999"]
            )
        assert result.exit_code == 1
        assert "OCR não disponível" in result.output

    def test_input_type_html_uses_fetch_ia_html(self):
        """--input-type html usa fetch_ia_html e passa input_type='html' ao parse_law."""
        raw_id = "leizilla-raw-federal-planalto-lei-09503"
        with (
            patch("leizilla.parser.fetch_ia_html", return_value="<html>lei</html>") as mock_html,
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT) as mock_parse,
        ):
            result = runner.invoke(
                app, ["parse", "--raw-id", raw_id, "--input-type", "html"]
            )
        assert result.exit_code == 0
        mock_html.assert_called_once_with(raw_id)
        _, kwargs = mock_parse.call_args
        assert kwargs.get("input_type") == "html"

    def test_input_type_html_exits_1_when_html_unavailable(self):
        """Exit 1 quando HTML não está disponível no IA."""
        with patch("leizilla.parser.fetch_ia_html", return_value=None):
            result = runner.invoke(
                app,
                ["parse", "--raw-id", "leizilla-raw-federal-planalto-lei-09503", "--input-type", "html"],
            )
        assert result.exit_code == 1
        assert "HTML não disponível" in result.output

    def test_invalid_input_type_exits_1(self):
        """Valor inválido para --input-type retorna exit 1 com mensagem clara."""
        result = runner.invoke(
            app,
            ["parse", "--raw-id", "leizilla-raw-ro-assembleia-coddoc-00001", "--input-type", "pdf"],
        )
        assert result.exit_code == 1
        assert "inválido" in result.output

    def test_exits_1_on_parse_failure(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr"),
            patch("leizilla.parser.parse_law", return_value=None),
        ):
            result = runner.invoke(
                app, ["parse", "--raw-id", "leizilla-raw-ro-assembleia-coddoc-00001"]
            )
        assert result.exit_code == 1
        assert "Parse falhou" in result.output


class TestCmdParseAll:
    def test_processes_range_and_reports_summary(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
            patch("leizilla.cli._xsd_gate", return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "3",
                    "--ente",
                    "ro",
                ],
            )
        assert result.exit_code == 0
        assert "parseados" in result.output

    def test_skips_items_without_ocr(self):
        call_count = {"n": 0}

        def ocr_side_effect(raw_id: str) -> str | None:
            call_count["n"] += 1
            return None  # all items missing OCR

        with (
            patch("leizilla.parser.fetch_ocr", side_effect=ocr_side_effect),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed"
            ) as mock_upload,
        ):
            result = runner.invoke(
                app,
                ["parse-all", "--start-coddoc", "1", "--end-coddoc", "5"],
            )
        mock_upload.assert_not_called()
        assert "0 parseados" in result.output

    def test_limit_parameter(self):
        fetched: list[str] = []

        def track_ocr(raw_id: str) -> str | None:
            fetched.append(raw_id)
            return "ocr"

        with (
            patch("leizilla.parser.fetch_ocr", side_effect=track_ocr),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
            patch("leizilla.cli._xsd_gate", return_value=True),
        ):
            runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "100",
                    "--limit",
                    "3",
                ],
            )
        assert len(fetched) == 3

    def test_no_upload_with_no_upload_flag(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed"
            ) as mock_upload,
        ):
            runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "2",
                    "--no-upload",
                ],
            )
        mock_upload.assert_not_called()

    def test_counts_parse_failures_without_abort(self):
        def flaky_parse(*args, **kwargs):
            return None  # always fails

        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr"),
            patch("leizilla.parser.parse_law", side_effect=flaky_parse),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "3",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        assert "3 falhos" in result.output

    def test_exits_1_on_upload_failure(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_FAIL,
            ),
            patch("leizilla.cli._xsd_gate", return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "2",
                    "--ente",
                    "ro",
                ],
            )
        assert result.exit_code == 1
        assert "erros de upload" in result.output

    def test_exits_1_when_xsd_gate_blocks_upload(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed"
            ) as mock_upload,
            patch("leizilla.cli._xsd_gate", return_value=False),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "2",
                    "--ente",
                    "ro",
                ],
            )
        assert result.exit_code == 1
        assert "XSD inválido" in result.output
        mock_upload.assert_not_called()

    def test_api_exception_per_item_counted_not_abort(self):
        """Exceção da API (timeout, rate-limit) em um item conta como falha sem abortar o batch."""
        call_count = {"n": 0}

        def flaky_parse(*args, **kwargs):
            call_count["n"] += 1
            raise ConnectionError("API timeout")

        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr"),
            patch("leizilla.parser.parse_law", side_effect=flaky_parse),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "3",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        assert "3 falhos" in result.output
        assert call_count["n"] == 3  # todos os itens tentados


class TestCmdParseXsdGateBlocking:
    def test_parse_upload_blocked_when_xsd_fails(self):
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed"
            ) as mock_upload,
            patch("leizilla.cli._xsd_gate", return_value=False),
        ):
            result = runner.invoke(
                app,
                [
                    "parse",
                    "--raw-id",
                    "leizilla-raw-ro-assembleia-coddoc-00042",
                    "--upload",
                ],
            )
        assert result.exit_code == 1
        assert "XSD inválido" in result.output
        mock_upload.assert_not_called()
