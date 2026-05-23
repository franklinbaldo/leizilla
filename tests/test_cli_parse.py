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
            patch(
                "leizilla.parser.fetch_ia_html", return_value="<html>lei</html>"
            ) as mock_html,
            patch(
                "leizilla.parser.parse_law", return_value=_PARSE_RESULT
            ) as mock_parse,
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
                [
                    "parse",
                    "--raw-id",
                    "leizilla-raw-federal-planalto-lei-09503",
                    "--input-type",
                    "html",
                ],
            )
        assert result.exit_code == 1
        assert "HTML não disponível" in result.output

    def test_invalid_input_type_exits_1(self):
        """Valor inválido para --input-type retorna exit 1 com mensagem clara."""
        result = runner.invoke(
            app,
            [
                "parse",
                "--raw-id",
                "leizilla-raw-ro-assembleia-coddoc-00001",
                "--input-type",
                "pdf",
            ],
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

    def test_input_type_html_uses_fetch_ia_html(self):
        """--input-type html usa fetch_ia_html em vez de fetch_ocr."""
        fetched_html: list[str] = []

        def track_html(raw_id: str) -> str:
            fetched_html.append(raw_id)
            return "<html>lei</html>"

        with (
            patch("leizilla.parser.fetch_ia_html", side_effect=track_html),
            patch("leizilla.parser.fetch_ocr") as mock_ocr,
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch("leizilla.cli._xsd_gate", return_value=True),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "2",
                    "--input-type",
                    "html",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        assert len(fetched_html) == 2
        mock_ocr.assert_not_called()

    def test_html_unavailable_skips_item(self):
        """Items sem HTML no IA são pulados silenciosamente sem contar como falha."""
        with (
            patch("leizilla.parser.fetch_ia_html", return_value=None),
            patch("leizilla.parser.parse_law") as mock_parse,
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "3",
                    "--input-type",
                    "html",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        assert "0 parseados" in result.output
        mock_parse.assert_not_called()

    def test_federal_planalto_uses_tipo_chave(self):
        """Fonte federal/planalto gera chave tipo-NNNNN; outras fontes usam coddoc-NNNNN."""
        fetched_ids: list[str] = []

        def track_ocr(raw_id: str) -> str:
            fetched_ids.append(raw_id)
            return "ocr text"

        with (
            patch("leizilla.parser.fetch_ocr", side_effect=track_ocr),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch("leizilla.cli._xsd_gate", return_value=True),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
        ):
            runner.invoke(
                app,
                [
                    "parse-all",
                    "--ente",
                    "federal",
                    "--fonte",
                    "planalto",
                    "--tipo",
                    "lcp",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "2",
                    "--no-upload",
                ],
            )
        assert fetched_ids == [
            "leizilla-raw-federal-planalto-lcp-00001",
            "leizilla-raw-federal-planalto-lcp-00002",
        ]

    def test_non_planalto_uses_coddoc_chave(self):
        """Fontes não-planalto continuam a usar coddoc-NNNNN."""
        fetched_ids: list[str] = []

        def track_ocr(raw_id: str) -> str:
            fetched_ids.append(raw_id)
            return "ocr"

        with (
            patch("leizilla.parser.fetch_ocr", side_effect=track_ocr),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch("leizilla.cli._xsd_gate", return_value=True),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
        ):
            runner.invoke(
                app,
                [
                    "parse-all",
                    "--ente",
                    "ro",
                    "--fonte",
                    "assembleia",
                    "--start-coddoc",
                    "5",
                    "--end-coddoc",
                    "6",
                    "--no-upload",
                ],
            )
        assert fetched_ids == [
            "leizilla-raw-ro-assembleia-coddoc-00005",
            "leizilla-raw-ro-assembleia-coddoc-00006",
        ]

    def test_invalid_input_type_exits_1(self):
        """Valor inválido para --input-type retorna exit 1 antes de processar qualquer item."""
        with patch("leizilla.parser.fetch_ocr") as mock_ocr:
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc",
                    "1",
                    "--end-coddoc",
                    "5",
                    "--input-type",
                    "pdf",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 1
        assert "inválido" in result.output
        mock_ocr.assert_not_called()


    def test_output_dir_saves_xml_files(self, tmp_path):
        """--output-dir cria arquivos {ia_id_parsed}.xml para cada parse bem-sucedido."""
        call_n = {"n": 0}

        def parse_side_effect(*args, **kwargs):
            call_n["n"] += 1
            return MagicMock(
                xml=f"<lei n='{call_n['n']}'/>",
                parsed_meta={},
                confidence=0.9,
                ia_id_parsed=f"leizilla-ro-lei-0000{call_n['n']}-2000",
                input_tokens=10,
                output_tokens=10,
            )

        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr text"),
            patch("leizilla.parser.parse_law", side_effect=parse_side_effect),
            patch("leizilla.cli._xsd_gate", return_value=True),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc", "1",
                    "--end-coddoc", "2",
                    "--output-dir", str(tmp_path / "xmls"),
                ],
            )
        assert result.exit_code == 0
        xml_files = sorted((tmp_path / "xmls").glob("*.xml"))
        assert len(xml_files) == 2
        assert "<lei" in xml_files[0].read_text()

    def test_output_dir_no_files_on_parse_abort(self, tmp_path):
        """Falhas de parse não criam arquivos no output_dir."""
        out = tmp_path / "xmls"
        with (
            patch("leizilla.parser.fetch_ocr", return_value="ocr"),
            patch("leizilla.parser.parse_law", return_value=None),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc", "1",
                    "--end-coddoc", "3",
                    "--output-dir", str(out),
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        # output_dir é criado pelo mkdir(parents=True), mas sem XMLs (parse falhou)
        assert not any(out.glob("*.xml"))


class TestCmdParseAllSkipExisting:
    """Testes para --skip-existing em parse-all."""

    def test_skip_existing_skips_already_parsed_items(self):
        """Items cujo raw_id está em already_parsed são pulados sem fetch/parse."""
        raw_id = "leizilla-raw-ro-assembleia-coddoc-00001"
        with (
            patch(
                "leizilla.publisher.list_parsed_raw_ids",
                return_value={raw_id},
            ),
            patch("leizilla.parser.fetch_ocr") as mock_ocr,
            patch("leizilla.parser.parse_law") as mock_parse,
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc", "1",
                    "--end-coddoc", "1",
                    "--skip-existing",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        assert "já publicado, skip" in result.output
        mock_ocr.assert_not_called()
        mock_parse.assert_not_called()

    def test_skip_existing_reports_skipped_count_in_summary(self):
        raw_ids = {
            "leizilla-raw-ro-assembleia-coddoc-00001",
            "leizilla-raw-ro-assembleia-coddoc-00002",
        }
        with (
            patch("leizilla.publisher.list_parsed_raw_ids", return_value=raw_ids),
            patch("leizilla.parser.fetch_ocr", return_value=None),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc", "1",
                    "--end-coddoc", "2",
                    "--skip-existing",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        assert "2 pulados (já publicados)" in result.output

    def test_no_skip_existing_processes_all_items(self):
        """Sem --skip-existing, list_parsed_raw_ids não é chamado."""
        with (
            patch("leizilla.publisher.list_parsed_raw_ids") as mock_list,
            patch("leizilla.parser.fetch_ocr", return_value=None),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc", "1",
                    "--end-coddoc", "2",
                    "--no-skip-existing",
                    "--no-upload",
                ],
            )
        assert result.exit_code == 0
        mock_list.assert_not_called()

    def test_skip_existing_network_error_falls_through(self):
        """Falha de rede em list_parsed_raw_ids → empty set → nenhum skip."""
        with (
            patch(
                "leizilla.publisher.list_parsed_raw_ids",
                return_value=set(),
            ),
            patch("leizilla.parser.fetch_ocr", return_value="ocr"),
            patch("leizilla.parser.parse_law", return_value=_PARSE_RESULT),
            patch("leizilla.cli._xsd_gate", return_value=True),
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_parsed",
                return_value=_UPLOAD_OK,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "parse-all",
                    "--start-coddoc", "1",
                    "--end-coddoc", "1",
                    "--skip-existing",
                ],
            )
        assert result.exit_code == 0
        assert "1 parseados" in result.output


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


class TestCmdStats:
    """Testes para cmd_stats — consulta IA sem credenciais."""

    def test_shows_counts_from_ia(self):
        with patch("leizilla.publisher.count_ia_items") as mock_count:
            mock_count.side_effect = [10, 3, 0, 1]  # raw, parsed+, dataset, bundle
            result = runner.invoke(app, ["stats", "--ente", "ro"])
        assert result.exit_code == 0
        assert "Raw items" in result.output
        assert "10" in result.output

    def test_shows_none_on_network_error(self):
        with patch("leizilla.publisher.count_ia_items", return_value=None):
            result = runner.invoke(app, ["stats", "--ente", "ro"])
        assert result.exit_code == 0
        assert "erro de rede" in result.output

    def test_no_ia_flag_skips_network(self):
        with patch("leizilla.publisher.count_ia_items") as mock_count:
            result = runner.invoke(app, ["stats", "--ente", "ro", "--no-ia"])
        mock_count.assert_not_called()
        assert result.exit_code == 0
        assert "desabilitada" in result.output

    def test_default_ente_is_ro(self):
        with patch("leizilla.publisher.count_ia_items", return_value=0) as mock_count:
            result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        first_call_prefix = mock_count.call_args_list[0][0][0]
        assert "leizilla-raw-ro-" == first_call_prefix
