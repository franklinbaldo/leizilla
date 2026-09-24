"""Testes unitários para leizilla.coverage — funil S1-S4 (issue #174).

Todo acesso de rede é mockado via os wrappers públicos de publisher.py
(``scrape_identifiers``, ``fetch_existing_index``, ``fetch_item_filenames``,
``list_parsed_raw_ids_strict``) — nenhuma chamada real ao Internet Archive.
"""

from unittest.mock import patch

from leizilla.coverage import (
    CoverageReport,
    FonteCoverage,
    TipoCoverage,
    _tipo_from_raw_id,
    compute_coverage,
    compute_fonte_coverage,
)
from leizilla.publisher import IndexFetchError

_INDEX_HEADER = "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"


def _index_csv(*rows: str) -> str:
    return _INDEX_HEADER + "\n".join(rows) + ("\n" if rows else "")


class TestTipoFromRawId:
    def test_extracts_tipo(self):
        assert (
            _tipo_from_raw_id("leizilla-raw-ro-casacivil-lei-00005", "ro", "casacivil")
            == "lei"
        )

    def test_none_when_prefix_does_not_match(self):
        assert (
            _tipo_from_raw_id("leizilla-raw-ro-assembleia-lei-00005", "ro", "casacivil")
            is None
        )

    def test_none_when_chave_malformed(self):
        assert (
            _tipo_from_raw_id(
                "leizilla-raw-ro-casacivil-naoconformeaqui", "ro", "casacivil"
            )
            is None
        )

    def test_case_insensitive_ente_fonte(self):
        assert (
            _tipo_from_raw_id(
                "leizilla-raw-ro-casacivil-decreto-00099", "RO", "Casacivil"
            )
            == "decreto"
        )


class TestComputeFonteCoverageNetworkFailures:
    def test_scrape_identifiers_none_marks_not_ok(self):
        with (
            patch("leizilla.publisher.scrape_identifiers", return_value=None),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is False
        assert fc.s1_total is None
        assert fc.s2_total is None
        assert fc.s3_total is None
        assert fc.s4_total == 0  # S4 é independente — não afetado pela falha em S1-S3

    def test_no_items_is_a_real_zero(self):
        """Fonte sem nenhum item IA ainda: ok=True, contadores 0 (zero real, não erro)."""
        with (
            patch("leizilla.publisher.scrape_identifiers", return_value=[]),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is True
        assert fc.s1_total == 0
        assert fc.s4_total == 0

    def test_transient_index_error_marks_not_ok(self):
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch(
                "leizilla.publisher.fetch_existing_index",
                side_effect=IndexFetchError("HTTP 503"),
            ),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is False
        assert fc.ok_s1_s3 is False
        assert fc.s1_total is None

    def test_confirmed_404_index_is_skipped_not_an_error(self):
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=None),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is True
        assert fc.s1_total == 0

    def test_metadata_fetch_failure_marks_not_ok(self):
        index_csv = _index_csv(
            "lei,1,,pdf,u1,h1,2026-05-30T00:00:00+00:00,",
        )
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=index_csv),
            patch("leizilla.publisher.fetch_item_filenames", return_value=None),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is False
        assert fc.ok_s1_s3 is False

    def test_parsed_lookup_failure_marks_not_ok(self):
        with (
            patch("leizilla.publisher.scrape_identifiers", return_value=[]),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=None),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is False
        assert fc.ok_s4 is False
        assert fc.s4_total is None

    def test_s1_s3_and_s4_failures_are_independent(self):
        """Falha em S1-S3 não deve impedir uma medição de S4 bem-sucedida, e vice-versa."""
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch(
                "leizilla.publisher.fetch_existing_index",
                side_effect=IndexFetchError("timeout"),
            ),
            patch(
                "leizilla.publisher.list_parsed_raw_ids_strict",
                return_value={"leizilla-raw-ro-casacivil-lei-00001"},
            ),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok_s1_s3 is False
        assert fc.ok_s4 is True
        assert fc.s1_total is None  # S1-S3: não confiável
        assert fc.s4_total == 1  # S4: medido com sucesso mesmo assim


class TestComputeFonteCoverageAggregation:
    def test_unidentified_item_counts_as_s1_only(self):
        index_csv = _index_csv(
            "documento,,,pdf,u1,h1,2026-05-30T00:00:00+00:00,harvest-key-1",
            "documento,,,pdf,u2,h2,2026-05-30T00:00:00+00:00,harvest-key-2",
        )
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_unidentified"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=index_csv),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is True
        assert fc.unidentified_arquivadas == 2
        assert fc.s1_total == 2
        assert fc.s2_total == 0  # não identificado != identificado
        assert fc.por_tipo == {}

    def test_html_row_counts_as_text_without_metadata_fetch(self):
        index_csv = _index_csv(
            "lei,1,atual,html,u1,h1,2026-05-30T00:00:00+00:00,",
        )
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=index_csv),
            patch("leizilla.publisher.fetch_item_filenames", return_value=set()) as m,
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.ok is True
        t = fc.por_tipo["lei"]
        assert (t.s1_arquivadas, t.s2_identificadas, t.s3_com_texto) == (1, 1, 1)
        m.assert_called_once_with("leizilla_ro_casacivil_lei_0001-1000")

    def test_pdf_row_with_djvu_derivative_counts_as_text(self):
        index_csv = _index_csv(
            "lei,5,,pdf,abc123,h1,2026-05-30T00:00:00+00:00,",
        )
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=index_csv),
            patch(
                "leizilla.publisher.fetch_item_filenames",
                return_value={"lei-00005_abc123.pdf", "lei-00005_abc123_djvu.txt"},
            ),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        t = fc.por_tipo["lei"]
        assert (t.s1_arquivadas, t.s2_identificadas, t.s3_com_texto) == (1, 1, 1)

    def test_pdf_row_without_djvu_derivative_not_yet_text(self):
        index_csv = _index_csv(
            "lei,5,,pdf,abc123,h1,2026-05-30T00:00:00+00:00,",
        )
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=index_csv),
            patch(
                "leizilla.publisher.fetch_item_filenames",
                return_value={"lei-00005_abc123.pdf"},
            ),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        t = fc.por_tipo["lei"]
        assert fc.ok is True
        assert (t.s1_arquivadas, t.s2_identificadas, t.s3_com_texto) == (1, 1, 0)

    def test_dedupes_multiple_rows_of_same_identity(self):
        """Duas rendições da mesma (tipo, numero) contam como 1 norma, não 2."""
        index_csv = _index_csv(
            "lei,1,,pdf,u1,h1,2026-05-30T00:00:00+00:00,",
            "lei,1,atual,html,u2,h2,2026-05-31T00:00:00+00:00,",
        )
        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch("leizilla.publisher.fetch_existing_index", return_value=index_csv),
            patch("leizilla.publisher.fetch_item_filenames", return_value=set()),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        t = fc.por_tipo["lei"]
        assert (t.s1_arquivadas, t.s2_identificadas, t.s3_com_texto) == (1, 1, 1)

    def test_s4_grouped_by_tipo_and_filtered_by_fonte(self):
        with (
            patch("leizilla.publisher.scrape_identifiers", return_value=[]),
            patch(
                "leizilla.publisher.list_parsed_raw_ids_strict",
                return_value={
                    "leizilla-raw-ro-casacivil-lei-00001",
                    "leizilla-raw-ro-casacivil-lei-00002",
                    "leizilla-raw-ro-casacivil-decreto-00001",
                },
            ),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.por_tipo["lei"].s4_estruturadas == 2
        assert fc.por_tipo["decreto"].s4_estruturadas == 1
        assert fc.s4_total == 3

    def test_multiple_range_items_accumulate(self):
        idx1 = _index_csv("lei,1,,pdf,u1,h1,2026-05-30T00:00:00+00:00,")
        idx2 = _index_csv("lei,1001,,pdf,u2,h2,2026-05-30T00:00:00+00:00,")

        def fake_fetch_existing_index(item_id):
            return {
                "leizilla_ro_casacivil_lei_0001-1000": idx1,
                "leizilla_ro_casacivil_lei_1001-2000": idx2,
            }[item_id]

        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=[
                    "leizilla_ro_casacivil_lei_0001-1000",
                    "leizilla_ro_casacivil_lei_1001-2000",
                ],
            ),
            patch(
                "leizilla.publisher.fetch_existing_index",
                side_effect=fake_fetch_existing_index,
            ),
            patch("leizilla.publisher.fetch_item_filenames", return_value=set()),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
        ):
            fc = compute_fonte_coverage("ro", "casacivil")
        assert fc.por_tipo["lei"].s1_arquivadas == 2


class TestComputeCoverage:
    def test_aggregates_multiple_fontes_with_git_sha(self):
        with (
            patch("leizilla.publisher.scrape_identifiers", return_value=[]),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
            patch("leizilla.publisher.get_git_sha", return_value="deadbeef"),
        ):
            report = compute_coverage("ro", ["casacivil", "assembleia"])
        assert isinstance(report, CoverageReport)
        assert report.ente == "ro"
        assert report.git_sha == "deadbeef"
        assert [f.fonte for f in report.fontes] == ["casacivil", "assembleia"]
        assert report.generated_at  # ISO timestamp presente

    def test_to_dict_is_json_serializable(self):
        import json

        with (
            patch(
                "leizilla.publisher.scrape_identifiers",
                return_value=["leizilla_ro_casacivil_lei_0001-1000"],
            ),
            patch(
                "leizilla.publisher.fetch_existing_index",
                return_value=_index_csv("lei,1,,html,u1,h1,2026-05-30T00:00:00+00:00,"),
            ),
            patch("leizilla.publisher.fetch_item_filenames", return_value=set()),
            patch("leizilla.publisher.list_parsed_raw_ids_strict", return_value=set()),
            patch("leizilla.publisher.get_git_sha", return_value=None),
        ):
            report = compute_coverage("ro", ["casacivil"])
        payload = report.to_dict()
        encoded = json.dumps(payload)  # não deve levantar
        decoded = json.loads(encoded)
        assert decoded["ente"] == "ro"
        assert decoded["fontes"][0]["s1_arquivadas"] == 1
        assert decoded["fontes"][0]["por_tipo"][0]["tipo"] == "lei"


class TestDataclassDefaults:
    def test_tipo_coverage_starts_zeroed(self):
        t = TipoCoverage(tipo="lei")
        assert (
            t.s1_arquivadas,
            t.s2_identificadas,
            t.s3_com_texto,
            t.s4_estruturadas,
        ) == (
            0,
            0,
            0,
            0,
        )

    def test_fonte_coverage_starts_ok_and_empty(self):
        fc = FonteCoverage(fonte="casacivil")
        assert fc.ok is True
        assert fc.por_tipo == {}
        assert fc.s1_total == 0
