"""Tests for Internet Archive range, bounds, parsing and url resolution utility functions."""

from leizilla.ia_utils import (
    parse_chave_numeric,
    get_range_bounds,
    get_range_identifier,
    resolve_ia_id_to_url,
)


class TestParseChaveNumeric:
    def test_numeric_law(self):
        assert parse_chave_numeric("lei-05120") == ("lei", 5120)
        assert parse_chave_numeric("decreto-0042") == ("decreto", 42)

    def test_complex_document_type(self):
        assert parse_chave_numeric("lei-complementar-0004") == ("lei-complementar", 4)
        assert parse_chave_numeric("decreto-lei-99") == ("decreto-lei", 99)

    def test_non_numeric(self):
        assert parse_chave_numeric("lei-decretada-a") == ("documento", 0)
        assert parse_chave_numeric("some-arbitrary-text") == ("documento", 0)


class TestGetRangeBounds:
    def test_standard_boundaries(self):
        # 1-1000 bounds
        assert get_range_bounds(1) == (1, 1000)
        assert get_range_bounds(500) == (1, 1000)
        assert get_range_bounds(1000) == (1, 1000)

        # 1001-2000 bounds
        assert get_range_bounds(1001) == (1001, 2000)
        assert get_range_bounds(2000) == (1001, 2000)

    def test_large_boundaries(self):
        # 9001-10000 bounds (end is 5-digit)
        assert get_range_bounds(9999) == (9001, 10000)
        assert get_range_bounds(10000) == (9001, 10000)

        # 10001-11000 bounds (both are 5-digit)
        assert get_range_bounds(10001) == (10001, 11000)

    def test_invalid_values(self):
        assert get_range_bounds(0) == (1, 1000)
        assert get_range_bounds(-42) == (1, 1000)


class TestGetRangeIdentifier:
    def test_generates_correct_slug(self):
        assert (
            get_range_identifier("ro", "casacivil", "lei", 5120)
            == "leizilla_ro_casacivil_lei_5001-6000"
        )
        assert (
            get_range_identifier("RO", "CasaCivil", "Lei-Complementar", 42)
            == "leizilla_ro_casacivil_lei-complementar_0001-1000"
        )


class TestResolveIaIdToUrl:
    def test_legacy_or_external_id(self):
        # IDs that don't start with 'leizilla-raw-' should pass through untouched
        assert (
            resolve_ia_id_to_url("external-archive-item", "_djvu.txt")
            == "https://archive.org/download/external-archive-item/external-archive-item_djvu.txt"
        )

    def test_numeric_range_resolution(self):
        ia_id = "leizilla-raw-ro-casacivil-lei-05120"
        # Resolves to numeric range bucket with underscores and lowers filename
        expected = "https://archive.org/download/leizilla_ro_casacivil_lei_5001-6000/lei-05120_djvu.txt"
        assert resolve_ia_id_to_url(ia_id, "_djvu.txt") == expected

    def test_complex_numeric_range_resolution(self):
        ia_id = "leizilla-raw-ro-casacivil-lei-complementar-00042"
        expected = "https://archive.org/download/leizilla_ro_casacivil_lei-complementar_0001-1000/lei-complementar-00042.html"
        assert resolve_ia_id_to_url(ia_id, ".html") == expected

    def test_fallback_resolution(self):
        ia_id = "leizilla-raw-ro-casacivil-lei-decretada-a"
        # Resolves to fallback item with underscores
        expected = "https://archive.org/download/leizilla-raw_ro_casacivil_fallback/lei-decretada-a_djvu.txt"
        assert resolve_ia_id_to_url(ia_id, "_djvu.txt") == expected

    def test_malformed_ia_id_fallback(self):
        # Starts with leizilla-raw- but doesn't conform to pattern (has no dash)
        bad_id = "leizilla-raw-ro"
        assert (
            resolve_ia_id_to_url(bad_id, "_djvu.txt")
            == f"https://archive.org/download/{bad_id}/{bad_id}_djvu.txt"
        )
