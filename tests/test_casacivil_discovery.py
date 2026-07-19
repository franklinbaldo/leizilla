"""Testes para discover_casacivil_laws — enumeração sem Playwright."""

from unittest.mock import patch
from leizilla.discovery import CasacivilIndexDiscovery

import pytest

from leizilla.crawler import (
    _CASACIVIL_FILES_BASE,
    _CASACIVIL_FONTE_URL,
    discover_casacivil_laws,
)


class TestDiscoverCasacivilLaws:
    def test_lei_url_pattern(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=42, end_num=42)
        assert laws[0]["url_pdf_original"] == f"{_CASACIVIL_FILES_BASE}/L42.pdf"

    def test_lc_url_pattern(self) -> None:
        laws = discover_casacivil_laws(tipo="lc", start_num=748, end_num=748)
        assert laws[0]["url_pdf_original"] == f"{_CASACIVIL_FILES_BASE}/LC748.pdf"

    def test_lei_chave(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=1, end_num=1)
        assert laws[0]["chave"] == "lei-00001"

    def test_lc_chave(self) -> None:
        laws = discover_casacivil_laws(tipo="lc", start_num=1, end_num=1)
        assert laws[0]["chave"] == "lc-00001"

    def test_chave_zero_padded_to_5_digits(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=99, end_num=99)
        assert laws[0]["chave"] == "lei-00099"

    def test_id_matches_chave(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=5, end_num=5)
        assert laws[0]["id"] == "ro-casacivil-lei-00005"

    def test_ente_and_fonte(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=1, end_num=1)
        assert laws[0]["ente"] == "ro"
        assert laws[0]["fonte"] == "casacivil"

    def test_fonte_url_is_directory(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=1, end_num=1)
        assert laws[0]["url_original"] == _CASACIVIL_FONTE_URL

    def test_range_length(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=1, end_num=10)
        assert len(laws) == 10

    def test_range_single(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=5, end_num=5)
        assert len(laws) == 1

    def test_range_empty_when_start_greater_than_end(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=10, end_num=5)
        assert laws == []

    def test_invalid_tipo_raises(self) -> None:
        # Only genuinely unknown types raise.
        with pytest.raises(ValueError, match="tipo deve ser"):
            discover_casacivil_laws(tipo="invalido", start_num=1, end_num=1)

    def test_titulo_lei(self) -> None:
        laws = discover_casacivil_laws(tipo="lei", start_num=3830, end_num=3830)
        assert "Lei" in laws[0]["titulo"]
        assert "3830" in laws[0]["titulo"]

    def test_titulo_lc(self) -> None:
        laws = discover_casacivil_laws(tipo="lc", start_num=748, end_num=748)
        assert "Complementar" in laws[0]["titulo"]
        assert "748" in laws[0]["titulo"]

    def test_no_http_requests_made(self) -> None:
        """Discovery é puramente local — sem I/O."""
        import socket

        original_getaddrinfo = socket.getaddrinfo

        def block_dns(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("discover_casacivil_laws fez I/O inesperado")

        socket.getaddrinfo = block_dns
        try:
            laws = discover_casacivil_laws(tipo="lei", start_num=1, end_num=5)
            assert len(laws) == 5
        finally:
            socket.getaddrinfo = original_getaddrinfo






class TestCasacivilIndexDiscovery:
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    @patch("leizilla.wayback.closest_snapshot", return_value=None)
    @patch("urllib.request.urlopen")
    def test_casacivil_index_discovery_enumerates_all_tipos(self, mock_urlopen, mock_snap, mock_robots):
        from unittest.mock import MagicMock
        config = {
            "strategy": "casacivil-index",
            "url": "https://ditel.casacivil.ro.gov.br/COTEL/Livros/",
        }

        with open("tests/fixtures/casacivil_index.html", "r") as f:
            html_content = f.read()

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = html_content.encode("utf-8")
        mock_urlopen.return_value = mock_resp

        discoverer = CasacivilIndexDiscovery(config, "ro", "casacivil")
        resources = discoverer.run()

        assert len(resources) == 7

        chaves = [r["chave"] for r in resources]
        assert "lei-06001" in chaves
        assert "lc-01301" in chaves
        assert "ec-00146" in chaves
        assert "decreto-00001" in chaves
        assert "decreto-lei-00002" in chaves
        assert "resolucao-00003" in chaves
        assert "portaria-00004" in chaves

        urls = [r["url"] for r in resources]
        assert "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L6001.pdf" in urls
        assert "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/EC146.pdf" in urls

    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    @patch("leizilla.wayback.closest_snapshot", return_value=None)
    @patch("urllib.request.urlopen", side_effect=Exception("Network failure"))
    def test_casacivil_index_discovery_fails_open(self, mock_urlopen, mock_snap, mock_robots):
        config = {
            "strategy": "casacivil-index",
            "url": "https://ditel.casacivil.ro.gov.br/COTEL/Livros/",
        }

        discoverer = CasacivilIndexDiscovery(config, "ro", "casacivil")
        resources = discoverer.run()

        assert resources == []
