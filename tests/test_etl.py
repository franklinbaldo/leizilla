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
        par_row = next(r for r in self.rows if r["dispositivo_path"] == "art-2-par-unico")
        assert par_row["dispositivo_parent_path"] == "art-2"

    def test_top_level_parent_path_is_none(self) -> None:
        ementa = next(r for r in self.rows if r["dispositivo_path"] == "ementa")
        assert ementa["dispositivo_parent_path"] is None

    def test_dispositivo_ordem(self) -> None:
        par_row = next(r for r in self.rows if r["dispositivo_path"] == "art-2-par-unico")
        assert par_row["dispositivo_ordem"] == 0  # first (and only) child of art-2

    def test_urn_dispositivo_composed(self) -> None:
        art1 = next(r for r in self.rows if r["dispositivo_path"] == "art-1")
        assert art1["urn_dispositivo"] == "urn:lex:br;rondonia:estadual:lei:1999-06-15;9999!art-1"

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
        expected = "sha256:" + hashlib.sha256(
            (art1["texto"] or "").encode("utf-8")
        ).hexdigest()
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
        self.rows = xml_to_rows(
            _WITH_ALTERACOES, "leizilla-ro-lei-01234-2003", "ro"
        )

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
        assert art3[1]["alterado_por"] == "urn:lex:br;rondonia:estadual:lei:2018-04-10;4321"

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
        self.rows = xml_to_rows(
            _WITH_REVOGACOES, "leizilla-ro-lei-00500-1990", "ro"
        )

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
        self.rows = xml_to_rows(_WITH_BLOCOS, "leizilla-federal-constituicao-1988", "federal")

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
        count = duckdb.execute("SELECT count(*) FROM read_parquet(?)", [str(out)]).fetchone()[0]  # type: ignore[index]
        assert count == len(rows)

    def test_roundtrip_columns_present(self, tmp_path: Path) -> None:
        import duckdb

        rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")
        out = tmp_path / "versoes.parquet"
        write_parquet(rows, out)
        cols = {
            row[0]
            for row in duckdb.execute(
                "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))", [str(out)]
            ).fetchall()
        }
        required = {"lei_id", "ente", "dispositivo_path", "em", "texto", "fontes"}
        assert required.issubset(cols)

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        rows = xml_to_rows(_SIMPLE, "leizilla-ro-lei-09999-1999", "ro")
        out = tmp_path / "nested" / "dir" / "versoes.parquet"
        write_parquet(rows, out)
        assert out.exists()
