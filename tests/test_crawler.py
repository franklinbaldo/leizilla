"""Tests for crawler pure helpers (no network/Playwright)."""

from leizilla.crawler import parse_titulo_identity


class TestParseTituloIdentity:
    def test_lei_ordinaria(self):
        assert parse_titulo_identity("LEI Nº 5.120, DE 22 DE JUNHO DE 1999") == (
            "lei",
            5120,
        )

    def test_lei_complementar_before_lei(self):
        assert parse_titulo_identity("LEI COMPLEMENTAR Nº 42, DE 2001") == ("lc", 42)

    def test_decreto(self):
        assert parse_titulo_identity("DECRETO Nº 1.234, DE 2010") == ("decreto", 1234)

    def test_decreto_lei_before_decreto(self):
        assert parse_titulo_identity("DECRETO-LEI Nº 99") == ("decreto-lei", 99)

    def test_resolucao_accented(self):
        assert parse_titulo_identity("Resolução nº 7, de 2020") == ("resolucao", 7)

    def test_number_anchored_to_n_not_year(self):
        # The year (1999) must not be mistaken for the law number.
        assert parse_titulo_identity("Lei nº 5120, de 1999") == ("lei", 5120)

    def test_no_number_returns_none(self):
        assert parse_titulo_identity("Lei sem número identificável") is None

    def test_no_tipo_returns_none(self):
        assert parse_titulo_identity("Documento avulso nº 123") is None

    def test_empty_returns_none(self):
        assert parse_titulo_identity("") is None
