"""Testes para cmd_scrape --skip-existing."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from leizilla.cli import app

runner = CliRunner()

_LAW_CASACIVIL = {
    "ente": "ro",
    "fonte": "casacivil",
    "chave": "lei-00001",
    "titulo": "Lei 1",
    "url_original": "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L1.pdf",
    "url_pdf_original": "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L1.pdf",
    "id": "ro-casacivil-lei-00001",
}

_UPLOAD_OK = {
    "success": True,
    "ia_id": "leizilla-raw-ro-casacivil-lei-00001",
    "ia_url": "https://archive.org/details/leizilla-raw-ro-casacivil-lei-00001",
}


class TestCmdScrapeSkipExisting:
    def _ia_resp(self, items):
        """Helper: urlopen mock que retorna lista de identifiers do IA."""
        payload = json.dumps({"items": items}).encode()

        class _R:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return _R()

    @patch("leizilla.cli.asyncio.run")
    @patch("leizilla.publisher.list_raw_ids", return_value=set())
    def test_no_skip_with_no_skip_existing_flag(self, mock_list, mock_asyncio):
        """Com --no-skip-existing, list_raw_ids não é chamado."""
        runner.invoke(
            app,
            [
                "scrape",
                "--ente",
                "ro",
                "--fonte",
                "casacivil",
                "--start",
                "1",
                "--end",
                "1",
                "--no-skip-existing",
            ],
        )
        mock_list.assert_not_called()

    @patch("leizilla.cli.asyncio.run")
    @patch(
        "leizilla.publisher.list_raw_ids",
        return_value={"leizilla-raw-ro-casacivil-lei-00001"},
    )
    def test_skip_existing_flag_calls_list_raw_ids(self, mock_list, mock_asyncio):
        """Com --skip-existing, list_raw_ids é chamado com ente/fonte corretos."""
        runner.invoke(
            app,
            [
                "scrape",
                "--ente",
                "ro",
                "--fonte",
                "casacivil",
                "--start",
                "1",
                "--end",
                "1",
                "--skip-existing",
            ],
        )
        mock_list.assert_called_once_with("ro", "casacivil")

    @patch("leizilla.scraper.scrape_one_html")
    @patch("leizilla.publisher.InternetArchivePublisher")
    @patch(
        "leizilla.publisher.list_raw_ids",
        return_value={"leizilla-raw-federal-planalto-lei-00001"},
    )
    @patch("leizilla.fontes.federal.discover_planalto_laws")
    def test_planalto_skips_existing_item(
        self, mock_discover, mock_list, mock_pub_cls, mock_scrape
    ):
        """Itens planalto já no IA são pulados; scrape_one_html não é chamado."""
        mock_discover.return_value = [
            {
                "ente": "federal",
                "fonte": "planalto",
                "chave": "lei-00001",
                "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L1.htm",
            }
        ]
        mock_pub_cls.return_value = MagicMock()

        result = runner.invoke(
            app,
            [
                "scrape",
                "--ente",
                "federal",
                "--fonte",
                "planalto",
                "--tipo",
                "lei",
                "--start",
                "1",
                "--end",
                "1",
                "--skip-existing",
            ],
        )
        mock_scrape.assert_not_called()
        assert "pulados (já existem)" in result.output

    @patch("leizilla.scraper.scrape_one_html")
    @patch("leizilla.publisher.InternetArchivePublisher")
    @patch("leizilla.publisher.list_raw_ids", return_value=set())
    @patch("leizilla.fontes.federal.discover_planalto_laws")
    def test_planalto_scrapes_new_item(
        self, mock_discover, mock_list, mock_pub_cls, mock_scrape
    ):
        """Item planalto não existente → scrape_one_html é chamado."""
        mock_discover.return_value = [
            {
                "ente": "federal",
                "fonte": "planalto",
                "chave": "lei-00002",
                "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L2.htm",
            }
        ]
        mock_pub_cls.return_value = MagicMock()
        mock_scrape.return_value = _UPLOAD_OK

        runner.invoke(
            app,
            [
                "scrape",
                "--ente",
                "federal",
                "--fonte",
                "planalto",
                "--tipo",
                "lei",
                "--start",
                "2",
                "--end",
                "2",
                "--skip-existing",
            ],
        )
        mock_scrape.assert_called_once()

    @patch("leizilla.scraper.scrape_one_html")
    @patch("leizilla.publisher.InternetArchivePublisher")
    @patch(
        "leizilla.publisher.list_raw_ids",
        return_value={"leizilla-raw-federal-planalto-lei-00001"},
    )
    @patch("leizilla.fontes.federal.discover_planalto_laws")
    def test_planalto_limit(
        self, mock_discover, mock_list, mock_pub_cls, mock_scrape
    ):
        """Testa se o limit interrompe corretamente os novos itens, sem contar os pulados."""
        mock_discover.return_value = [
            {
                "ente": "federal",
                "fonte": "planalto",
                "chave": "lei-00001",
                "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L1.htm",
            },
            {
                "ente": "federal",
                "fonte": "planalto",
                "chave": "lei-00002",
                "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L2.htm",
            },
            {
                "ente": "federal",
                "fonte": "planalto",
                "chave": "lei-00003",
                "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L3.htm",
            },
        ]
        mock_pub_cls.return_value = MagicMock()
        mock_scrape.return_value = _UPLOAD_OK

        result = runner.invoke(
            app,
            [
                "scrape",
                "--ente",
                "federal",
                "--fonte",
                "planalto",
                "--tipo",
                "lei",
                "--start",
                "1",
                "--end",
                "3",
                "--skip-existing",
                "--limit",
                "1",
            ],
        )

        # O item 1 deve ser pulado, o item 2 deve ser processado, o item 3 deve ser interrompido pelo limit.
        mock_scrape.assert_called_once()
        assert "1 pulados" in result.output
        assert "1/3 com sucesso" in result.output

    @patch("leizilla.scraper.scrape_one")
    @patch("leizilla.publisher.InternetArchivePublisher")
    @patch(
        "leizilla.publisher.list_raw_ids",
        return_value={"leizilla-raw-ro-casacivil-lei-00001"},
    )
    @patch("leizilla.crawler.discover_casacivil_laws")
    def test_casacivil_limit(
        self, mock_discover, mock_list, mock_pub_cls, mock_scrape
    ):
        """Testa se o limit interrompe corretamente os PDFs, sem contar os pulados."""
        mock_discover.return_value = [
            {
                "ente": "ro",
                "fonte": "casacivil",
                "chave": "lei-00001",
                "url_original": "http://ditel/L1.pdf",
                "url_pdf_original": "http://ditel/L1.pdf",
            },
            {
                "ente": "ro",
                "fonte": "casacivil",
                "chave": "lei-00002",
                "url_original": "http://ditel/L2.pdf",
                "url_pdf_original": "http://ditel/L2.pdf",
            },
            {
                "ente": "ro",
                "fonte": "casacivil",
                "chave": "lei-00003",
                "url_original": "http://ditel/L3.pdf",
                "url_pdf_original": "http://ditel/L3.pdf",
            },
        ]
        mock_pub_cls.return_value = MagicMock()
        mock_scrape.return_value = _UPLOAD_OK

        with patch("leizilla.discovery.WaybackCdxDiscovery.run", return_value=[]), \
             patch("leizilla.discovery.load_manifest", return_value={"fontes": {"casacivil": {"probe": [{"templates": ["http://ditel/L{num}.pdf"], "start": 1}]}}}):

            with patch("leizilla.cli.asyncio.run") as mock_asyncio:
                # Simular o comportamento do asyncio.run chamando a corrotina
                def side_effect(coro):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        return loop.run_until_complete(coro)
                    finally:
                        loop.close()
                mock_asyncio.side_effect = side_effect

                result = runner.invoke(
                    app,
                    [
                        "scrape",
                        "--ente",
                        "ro",
                        "--fonte",
                        "casacivil",
                        "--tipo",
                        "lei",
                        "--start",
                        "1",
                        "--end",
                        "3",
                        "--skip-existing",
                        "--limit",
                        "1",
                    ],
                )

        # O item 1 deve ser pulado, o item 2 deve ser processado, o item 3 deve ser interrompido pelo limit.
        mock_scrape.assert_called_once()
        assert "1 pulados" in result.output
        assert "1/3 com sucesso" in result.output

    @patch("leizilla.publisher.list_raw_ids", return_value=set())
    def test_skip_existing_reports_ia_count_in_output(self, mock_list):
        """Com --skip-existing, output inclui contagem de itens existentes no IA."""
        with patch("leizilla.cli.asyncio.run"):
            result = runner.invoke(
                app,
                [
                    "scrape",
                    "--ente",
                    "ro",
                    "--fonte",
                    "casacivil",
                    "--start",
                    "1",
                    "--end",
                    "1",
                    "--skip-existing",
                ],
            )
        assert "0 itens existentes encontrados" in result.output
