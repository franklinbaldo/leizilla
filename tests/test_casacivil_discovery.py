"""Testes para discover_casacivil_laws — enumeração sem Playwright."""

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
        # decreto is now valid (lei/lc/decreto); only genuinely unknown types raise.
        with pytest.raises(ValueError, match="tipo deve ser"):
            discover_casacivil_laws(tipo="portaria", start_num=1, end_num=1)

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
