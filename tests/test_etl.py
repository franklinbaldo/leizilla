"""Tests for etl.py — XML v0.1 → Parquet v0.1 (tabela versoes)."""

from __future__ import annotations

import datetime
import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from leizilla.etl import (
    consolidate_xmls,
    path_to_tipo,
    write_parquet,
    xml_to_rows,
)

# ---------------------------------------------------------------------------
# Fixtures: load XML files from the leizilla_xml fixture directory
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "leizilla_xml"


def _load(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


_SIMPLE = _load("simple.xml")
_WITH_ALTERACOES = _load("with-alteracoes.xml")
_WITH_REVOGACOES = _load("with-revogacoes.xml")
_WITH_REVOGACAO_TOTAL = _load("with-revogacao-total.xml")
_WITH_REVOGACAO_CASCATA = _load("with-revogacao-cascata.xml")
_WITH_BLOCOS = _load("with-blocos-organizacionais.xml")
_WITH_PARCIAL = _load("with-parse-parcial.xml")


# ---------------------------------------------------------------------------
# path_to_tipo
# ---------------------------------------------------------------------------


class TestPathToTipo:
    def test_ementa(self) -> None:
        assert path_to_tipo("ementa") == "ementa"

    def test_artigo(self) -> None:
        assert path_to_tipo("art-1") == "artigo"

    def test_artigo_letra(self) -> None:
        assert path_to_tipo("art-5-a") == "artigo"

    def test_paragrafo_unico(self) -> None:
        assert path_to_tipo("par-unico") == "paragrafo"

    def test_paragrafo_numero(self) -> None:
        assert path_to_tipo("par-2") == "paragrafo"

    def test_composite_normativo(self) -> None:
        assert path_to_tipo("art-3-par-1") == "paragrafo"

    def test_composite_normativo_deep(self) -> None:
        assert path_to_tipo("art-5-par-2-inc-3") == "inciso"

    def test_organizacional_titulo(self) -> None:
        assert path_to_tipo("tit-1") == "titulo"

    def test_organizacional_composite(self) -> None:
        assert path_to_tipo("tit-2-cap-1") == "capitulo"

    def test_unknown_returns_none(self) -> None:
        assert path_to_tipo("foo-bar") is None

    def test_empty_returns_none(self) -> None:
        assert path_to_tipo("") is None

    def test_anexo(self) -> None:
        assert path_to_tipo("anexo-1") == "anexo"

    def test_inciso(self) -> None:
        assert path_to_tipo("inc-3") == "inciso"


# ---------------------------------------------------------------------------
# xml_to_rows — simple.xml
# ---------------------------------------------------------------------------


class TestXmlToRowsSimple:
    def setup_method(self) -> None:
        self.rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")

    def test_row_count(self) -> None:
        # ementa, art-1, art-2, art-2-par-unico, art-3 = 5 dispositivos, 1 versao each
        assert len(self.rows) == 5

    def test_lei_id_propagated(self) -> None:
        assert all(r["lei_id"] == "leizilla-ro-lei-09999-1999" for r in self.rows)

    def test_ente_propagated(self) -> None:
        assert all(r["ente"] == "ro" for r in self.rows)

    def test_tipo_lei_from_urn(self) -> None:
        assert all(r["tipo_lei"] == "lei" for r in self.rows)

    def test_ano_lei_from_urn(self) -> None:
        assert all(r["ano_lei"] == 1999 for r in self.rows)

    def test_data_publicacao_from_urn(self) -> None:
        expected = datetime.date(1999, 6, 15)
        assert all(r["data_publicacao"] == expected for r in self.rows)

    def test_em_inherits_data_publicacao(self) -> None:
        # No <versao em="..."> declared → all inherit data_publicacao
        expected = datetime.date(1999, 6, 15)
        assert all(r["em"] == expected for r in self.rows)

    def test_ate_is_none_single_versao(self) -> None:
        assert all(r["ate"] is None for r in self.rows)

    def test_versao_id_format(self) -> None:
        # Issue #119: versao_id must include lei_id to be globally unique in Parquet
        # Expected format: {lei_id}#{path}#{em}
        art1 = next(r for r in self.rows if r["dispositivo_path"] == "art-1")
        assert art1["versao_id"] == "leizilla-ro-lei-09999-1999#art-1#1999-06-15"

    def test_inicio_tipo_default(self) -> None:
        assert all(r["inicio_tipo"] == "data-publicacao" for r in self.rows)

    def test_lei_not_revogada(self) -> None:
        assert all(r["lei_revogada"] is False for r in self.rows)

    def test_dispositivo_not_revogado(self) -> None:
        assert all(r["dispositivo_revogado"] is False for r in self.rows)

    def test_dispositivo_tipos_correct(self) -> None:
        tipo_map = {r["dispositivo_path"]: r["dispositivo_tipo"] for r in self.rows}
        assert tipo_map["ementa"] == "ementa"
        assert tipo_map["art-1"] == "artigo"
        assert tipo_map["art-2"] == "artigo"
        assert tipo_map["art-2-par-unico"] == "paragrafo"
        assert tipo_map["art-3"] == "artigo"

    def test_nested_parent_path(self) -> None:
        par_row = next(
            r for r in self.rows if r["dispositivo_path"] == "art-2-par-unico"
        )
        assert par_row["dispositivo_parent_path"] == "art-2"

    def test_top_level_parent_path_is_none(self) -> None:
        ementa = next(r for r in self.rows if r["dispositivo_path"] == "ementa")
        assert ementa["dispositivo_parent_path"] is None

    def test_dispositivo_ordem(self) -> None:
        par_row = next(
            r for r in self.rows if r["dispositivo_path"] == "art-2-par-unico"
        )
        assert par_row["dispositivo_ordem"] == 0  # first (and only) child of art-2

    def test_urn_dispositivo_composed(self) -> None:
        art1 = next(r for r in self.rows if r["dispositivo_path"] == "art-1")
        assert (
            art1["urn_dispositivo"]
            == "urn:lex:br;rondonia:estadual:lei:1999-06-15;9999!art-1"
        )

    def test_fontes_json_valid(self) -> None:
        for row in self.rows:
            parsed = json.loads(row["fontes"])
            assert isinstance(parsed, list)
            assert all("ia_id" in f for f in parsed)

    def test_num_fontes_correct(self) -> None:
        for row in self.rows:
            parsed = json.loads(row["fontes"])
            assert row["num_fontes"] == len(parsed)

    def test_hash_texto_sha256(self) -> None:
        art1 = next(r for r in self.rows if r["dispositivo_path"] == "art-1")
        expected = (
            "sha256:"
            + hashlib.sha256((art1["texto"] or "").encode("utf-8")).hexdigest()
        )
        assert art1["hash_texto"] == expected

    def test_texto_normalizado_is_nfc(self) -> None:
        for row in self.rows:
            if row["texto"]:
                expected = unicodedata.normalize("NFC", row["texto"]).strip()
                assert row["texto_normalizado"] == expected


# ---------------------------------------------------------------------------
# xml_to_rows — with-alteracoes.xml (multiple versoes, ate inference)
# ---------------------------------------------------------------------------


class TestXmlToRowsComAlteracoes:
    def setup_method(self) -> None:
        self.rows = xml_to_rows(_WITH_ALTERACOES, "leizilla-ro-lei-01234-2003", "ro")

    def test_art3_has_three_versoes(self) -> None:
        art3_rows = [r for r in self.rows if r["dispositivo_path"] == "art-3"]
        assert len(art3_rows) == 3

    def test_art3_versao_ems(self) -> None:
        art3 = sorted(
            [r for r in self.rows if r["dispositivo_path"] == "art-3"],
            key=lambda r: r["em"],
        )
        assert art3[0]["em"] == datetime.date(2003, 6, 15)  # inherited
        assert art3[1]["em"] == datetime.date(2018, 4, 10)
        assert art3[2]["em"] == datetime.date(2024, 7, 30)

    def test_art3_versao_ate_inference(self) -> None:
        art3 = sorted(
            [r for r in self.rows if r["dispositivo_path"] == "art-3"],
            key=lambda r: r["em"],
        )
        assert art3[0]["ate"] == datetime.date(2018, 4, 10)
        assert art3[1]["ate"] == datetime.date(2024, 7, 30)
        assert art3[2]["ate"] is None  # last versao → still vigente

    def test_art3_alterado_por(self) -> None:
        art3 = sorted(
            [r for r in self.rows if r["dispositivo_path"] == "art-3"],
            key=lambda r: r["em"],
        )
        assert art3[0]["alterado_por"] is None
        assert (
            art3[1]["alterado_por"]
            == "urn:lex:br;rondonia:estadual:lei:2018-04-10;4321"
        )

    def test_inicio_tipo_texto_lei_alteradora(self) -> None:
        art3 = sorted(
            [r for r in self.rows if r["dispositivo_path"] == "art-3"],
            key=lambda r: r["em"],
        )
        assert art3[1]["inicio_tipo"] == "texto-lei-alteradora"

    def test_art3_par1_explicit_em(self) -> None:
        par1 = next(r for r in self.rows if r["dispositivo_path"] == "art-3-par-1")
        assert par1["em"] == datetime.date(2018, 4, 10)

    def test_art7_vacatio_legis_inicio_tipo(self) -> None:
        art7 = next(r for r in self.rows if r["dispositivo_path"] == "art-7")
        assert art7["inicio_tipo"] == "vacatio-legis"

    def test_fonte_diverge_captured(self) -> None:
        # art-3 first versao has a diverging fonte
        art3_first = min(
            (r for r in self.rows if r["dispositivo_path"] == "art-3"),
            key=lambda r: r["em"],
        )
        fontes = json.loads(art3_first["fontes"])
        diverging = [f for f in fontes if f["diverge"]]
        assert len(diverging) == 1
        assert diverging[0]["texto_divergente"] is not None
        assert art3_first["tem_divergencia"] is True


# ---------------------------------------------------------------------------
# xml_to_rows — with-revogacoes.xml
# ---------------------------------------------------------------------------


class TestXmlToRowsComRevogacoes:
    def setup_method(self) -> None:
        self.rows = xml_to_rows(_WITH_REVOGACOES, "leizilla-ro-lei-00500-1990", "ro")

    def test_art3_revogado(self) -> None:
        art3 = next(r for r in self.rows if r["dispositivo_path"] == "art-3")
        assert art3["dispositivo_revogado"] is True
        assert art3["dispositivo_revogado_em"] == datetime.date(2020, 6, 15)
        assert art3["dispositivo_revogado_tipo"] == "expressa"

    def test_art3_ate_equals_revogacao_em(self) -> None:
        art3 = next(r for r in self.rows if r["dispositivo_path"] == "art-3")
        assert art3["ate"] == datetime.date(2020, 6, 15)

    def test_art5_revogado_inconstitucionalidade(self) -> None:
        art5 = next(r for r in self.rows if r["dispositivo_path"] == "art-5")
        assert art5["dispositivo_revogado_tipo"] == "inconstitucionalidade"

    def test_art9_revogado_tacita(self) -> None:
        art9 = next(r for r in self.rows if r["dispositivo_path"] == "art-9")
        assert art9["dispositivo_revogado_tipo"] == "tacita"

    def test_art1_not_revogado(self) -> None:
        art1 = next(r for r in self.rows if r["dispositivo_path"] == "art-1")
        assert art1["dispositivo_revogado"] is False


# ---------------------------------------------------------------------------
# xml_to_rows — with-blocos-organizacionais.xml
# ---------------------------------------------------------------------------


class TestXmlToRowsComBlocos:
    def setup_method(self) -> None:
        self.rows = xml_to_rows(
            _WITH_BLOCOS, "leizilla-federal-constituicao-1988", "federal"
        )

    def test_tit1_tipo_titulo(self) -> None:
        tit1 = next(r for r in self.rows if r["dispositivo_path"] == "tit-1")
        assert tit1["dispositivo_tipo"] == "titulo"

    def test_tit2_cap1_tipo_capitulo(self) -> None:
        cap = next(r for r in self.rows if r["dispositivo_path"] == "tit-2-cap-1")
        assert cap["dispositivo_tipo"] == "capitulo"

    def test_art1_inside_tit1_has_no_org_parent(self) -> None:
        # art-1 is normativo nested under tit-1 (organizacional)
        # its parent_path is tit-1 (the immediate XML parent)
        art1 = next(r for r in self.rows if r["dispositivo_path"] == "art-1")
        assert art1["dispositivo_parent_path"] == "tit-1"

    def test_art5_inside_tit2_cap1(self) -> None:
        art5 = next(r for r in self.rows if r["dispositivo_path"] == "art-5")
        assert art5["dispositivo_parent_path"] == "tit-2-cap-1"

    def test_ente_federal(self) -> None:
        assert all(r["ente"] == "federal" for r in self.rows)


# ---------------------------------------------------------------------------
# consolidate_xmls
# ---------------------------------------------------------------------------


class TestConsolidateXmls:
    def test_two_leis_concatenated(self) -> None:
        items = [
            ("leizilla-ro-lei-09999-1999", "ro", _SIMPLE),
            ("leizilla-ro-lei-00500-1990", "ro", _WITH_REVOGACOES),
        ]
        rows = consolidate_xmls(items)
        lei_ids = {r["lei_id"] for r in rows}
        assert "leizilla-ro-lei-09999-1999" in lei_ids
        assert "leizilla-ro-lei-00500-1990" in lei_ids

    def test_versao_id_unique_across_laws(self) -> None:
        # Issue #119: Same path#em in two different laws must get distinct versao_ids
        items = [
            ("lei-1", "ro", _SIMPLE),
            ("lei-2", "ro", _SIMPLE),  # Same XML, different lei_id
        ]
        rows = consolidate_xmls(items)
        # 5 rows per law = 10 rows total, 10 unique versao_ids
        versao_ids = {r["versao_id"] for r in rows}
        assert len(versao_ids) == 10
        assert "lei-1#art-1#1999-06-15" in versao_ids
        assert "lei-2#art-1#1999-06-15" in versao_ids

    def test_duplicate_versao_id_raises(self) -> None:
        items = [
            ("lei-1", "ro", _SIMPLE),
            ("lei-1", "ro", _SIMPLE),  # Exact same lei_id and XML -> duplicate IDs
        ]
        with pytest.raises(ValueError, match="Duplicate versao_id detected"):
            consolidate_xmls(items)

    def test_empty_input(self) -> None:
        assert consolidate_xmls([]) == []


# ---------------------------------------------------------------------------
# write_parquet (roundtrip)
# ---------------------------------------------------------------------------


class TestWriteParquet:
    def test_creates_file(self, tmp_path: Path) -> None:
        rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")
        out = tmp_path / "versoes.parquet"
        write_parquet(rows, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_raises_on_empty(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            write_parquet([], tmp_path / "out.parquet")

    def test_roundtrip_row_count(self, tmp_path: Path) -> None:
        import duckdb

        rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")
        out = tmp_path / "versoes.parquet"
        write_parquet(rows, out)
        count = duckdb.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(out)]
        ).fetchone()[0]  # type: ignore[index]
        assert count == len(rows)

    def test_schema_matches_pinned(self, tmp_path: Path) -> None:
        """The exported Parquet schema must strictly match docs/SCHEMA.md §3.1."""
        import duckdb
        from leizilla.etl import PARQUET_SCHEMA

        rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")
        out = tmp_path / "versoes.parquet"
        write_parquet(rows, out)

        # Mapping from DuckDB logical types back to our generic types
        duckdb_to_our_types = {
            "VARCHAR": "VARCHAR",
            "BIGINT": "INTEGER",
            "INTEGER": "INTEGER",
            "DATE": "DATE",
            "BOOLEAN": "BOOLEAN",
        }

        actual_schema = {}
        for row in duckdb.execute(
            "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [str(out)],
        ).fetchall():
            col_name, col_type = row[0], row[1]
            actual_schema[col_name] = duckdb_to_our_types.get(col_type, col_type)

        assert actual_schema == PARQUET_SCHEMA

    def test_schema_is_stable_with_all_nulls(self, tmp_path: Path) -> None:
        """Regression test for #123: all-null columns must not infer as VARCHAR or NULL."""
        import duckdb
        from leizilla.etl import PARQUET_SCHEMA
        import datetime

        # Create a single row where all optional columns are None
        row = {
            "lei_id": "123",
            "ente": "ro",
            "tipo_lei": "lei",
            "numero_lei": "72-a",
            "ano_lei": 2020,
            "data_publicacao": datetime.date(2020, 1, 1),
            "urn_lex_lei": None,
            "vigente_em": datetime.date(2020, 1, 1),
            "lei_revogada": False,
            "lei_revogada_em": None,
            "lei_revogada_por": None,
            "lei_revogada_tipo": None,
            "dispositivo_path": "art1",
            "dispositivo_tipo": "artigo",
            "dispositivo_ordem": 0,
            "dispositivo_parent_path": None,
            "dispositivo_revogado": False,
            "dispositivo_revogado_em": None,
            "dispositivo_revogado_por": None,
            "dispositivo_revogado_tipo": None,
            "urn_dispositivo": None,
            "versao_id": "v1",
            "em": datetime.date(2020, 1, 1),
            "ate": None,
            "alterado_por": None,
            "inicio_tipo": "data-publicacao",
            "texto": None,
            "texto_normalizado": None,
            "fontes": "[]",
            "num_fontes": 0,
            "tem_divergencia": False,
            "hash_texto": None,
            "quality": None,
        }

        out = tmp_path / "nulls.parquet"
        write_parquet([row], out)

        duckdb_to_our_types = {
            "VARCHAR": "VARCHAR",
            "BIGINT": "INTEGER",
            "INTEGER": "INTEGER",
            "DATE": "DATE",
            "BOOLEAN": "BOOLEAN",
        }

        actual_schema = {}
        for r in duckdb.execute(
            "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [str(out)],
        ).fetchall():
            col_name, col_type = r[0], r[1]
            actual_schema[col_name] = duckdb_to_our_types.get(col_type, col_type)

        assert actual_schema == PARQUET_SCHEMA

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")
        out = tmp_path / "nested" / "dir" / "versoes.parquet"
        write_parquet(rows, out)
        assert out.exists()


# ---------------------------------------------------------------------------
# xml_to_rows — with-revogacao-total.xml (P1: ate inference for lei-level revogacao)
# ---------------------------------------------------------------------------


class TestXmlToRowsComRevogacaoTotal:
    """Lei-level <revogacao> must propagate to ate of all dispositivos (P1 fix)."""

    def setup_method(self) -> None:
        self.rows = xml_to_rows(
            _WITH_REVOGACAO_TOTAL, "leizilla-ro-lei-00042-1985", "ro"
        )

    def test_lei_revogada_flag(self) -> None:
        assert all(r["lei_revogada"] is True for r in self.rows)

    def test_lei_revogada_em(self) -> None:
        expected = datetime.date(2018, 12, 30)
        assert all(r["lei_revogada_em"] == expected for r in self.rows)

    def test_lei_revogada_por(self) -> None:
        expected = "urn:lex:br;rondonia:estadual:lei:2018-12-30;4500"
        assert all(r["lei_revogada_por"] == expected for r in self.rows)

    def test_ate_equals_lei_revogada_em_for_all_dispositivos(self) -> None:
        # P1 fix: dispositivos sem <revogacao> própria devem herdar lei_revogada_em
        expected = datetime.date(2018, 12, 30)
        for row in self.rows:
            assert row["ate"] == expected, (
                f"dispositivo {row['dispositivo_path']!r} tem ate={row['ate']!r}, "
                f"esperado {expected}"
            )

    def test_dispositivos_not_individually_revogados(self) -> None:
        # Revogação total é na lei; dispositivos não têm <revogacao> própria
        assert all(r["dispositivo_revogado"] is False for r in self.rows)

    def test_row_count(self) -> None:
        # ementa + art-1 + art-2 = 3 dispositivos
        assert len(self.rows) == 3


class TestParseLeiFieldsFallbackId:
    """xml_to_rows should extract tipo from fallback IA-id format (SCHEMA.md §1.3)."""

    def _rows(self, lei_id: str) -> list[dict]:  # type: ignore[type-arg]
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1">'
            '<dispositivo path="ementa"><versao><texto>Texto.</texto></versao></dispositivo>'
            "</lei>"
        )
        from leizilla.etl import xml_to_rows

        return xml_to_rows(xml, lei_id, "ro")

    def test_canonical_id_parsed(self) -> None:
        rows = self._rows("leizilla-ro-lei-01234-2003")
        assert rows[0]["tipo_lei"] == "lei"
        assert rows[0]["ano_lei"] == 2003

    def test_fallback_id_extracts_tipo(self) -> None:
        rows = self._rows("leizilla-ro-lei-fallback-casacivil-coddoc-00042")
        assert rows[0]["tipo_lei"] == "lei"
        assert rows[0]["numero_lei"] is None
        assert rows[0]["ano_lei"] == 0

    def test_fallback_id_lc_extracts_tipo(self) -> None:
        rows = self._rows("leizilla-ro-lc-fallback-assembleia-coddoc-00099")
        assert rows[0]["tipo_lei"] == "lc"
        assert rows[0]["numero_lei"] is None

    def test_unknown_id_returns_desconhecido(self) -> None:
        rows = self._rows("item-sem-padrao-conhecido")
        assert rows[0]["tipo_lei"] == "desconhecido"
        assert rows[0]["numero_lei"] is None
        assert rows[0]["ano_lei"] == 0

    def test_fallback_id_numeric_key_not_misclassified(self) -> None:
        # P2 fix: fallback key ending in -N-YYYY must not be parsed as canonical.
        # leizilla-ro-lei-fallback-casacivil-12345-1985: fallback check must
        # fire before the canonical heuristic matches tipo='casacivil'.
        rows = self._rows("leizilla-ro-lei-fallback-casacivil-12345-1985")
        assert rows[0]["tipo_lei"] == "lei"
        assert rows[0]["numero_lei"] is None
        assert rows[0]["ano_lei"] == 0


# ---------------------------------------------------------------------------
# xml_to_rows — with-revogacao-cascata.xml (P1: cascade revogacao to descendants)
# ---------------------------------------------------------------------------


class TestXmlToRowsComRevogacaoCascata:
    """§0.3 SCHEMA.md: revogação de dispositivo pai cascateia implicitamente para filhos."""

    def setup_method(self) -> None:
        self.rows = xml_to_rows(
            _WITH_REVOGACAO_CASCATA, "leizilla-ro-lei-00700-2000", "ro"
        )
        self.by_path = {r["dispositivo_path"]: r for r in self.rows}

    def test_art10_ate_equals_revogacao_em(self) -> None:
        assert self.by_path["art-10"]["ate"] == datetime.date(2015, 3, 1)

    def test_art10_par1_ate_cascateia_do_pai(self) -> None:
        # Filho direto sem <revogacao> própria herda ate do pai revogado
        assert self.by_path["art-10-par-1"]["ate"] == datetime.date(2015, 3, 1)

    def test_art10_par2_ate_cascateia_do_pai(self) -> None:
        assert self.by_path["art-10-par-2"]["ate"] == datetime.date(2015, 3, 1)

    def test_art10_par1_inc1_ate_cascateia_do_avo(self) -> None:
        # Neto (2 níveis) também herda ate do avô revogado
        assert self.by_path["art-10-par-1-inc-1"]["ate"] == datetime.date(2015, 3, 1)

    def test_art11_ate_is_none(self) -> None:
        # Dispositivo irmão não afetado pela revogação do art-10
        assert self.by_path["art-11"]["ate"] is None

    def test_children_not_individually_revogados(self) -> None:
        # Cascata fecha o ate mas não marca o filho como individualmente revogado
        assert self.by_path["art-10-par-1"]["dispositivo_revogado"] is False
        assert self.by_path["art-10-par-2"]["dispositivo_revogado"] is False
        assert self.by_path["art-10-par-1-inc-1"]["dispositivo_revogado"] is False

    def test_row_count(self) -> None:
        # art-10, art-10-par-1, art-10-par-1-inc-1, art-10-par-2, art-11 = 5
        assert len(self.rows) == 5
