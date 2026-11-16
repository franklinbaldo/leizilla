"""Testes do catálogo oficial como produto (leizilla.catalogo, ADR-0017).

Offline: o catálogo vem de registros pequenos no formato de
``discovery.parse_casacivil_year_catalog`` e o IA nunca é consultado.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from leizilla import catalogo
from leizilla import completeness as comp
from leizilla import relacoes
from leizilla.cli import app

BASE = "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/"


def _rec(
    tipo: str,
    numero: int,
    data: str,
    ementa: str,
    files: list[tuple[str, str]],
    sufixo: str = "",
    incerta: bool = False,
    coddoc: int = 1,
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "numero": numero,
        "sufixo": sufixo,
        "titulo": f"{tipo} n. {numero}, de {data}",
        "data": data,
        "ano": int(data[:4]),
        "ementa": ementa,
        "coddoc": coddoc,
        "arquivos": [
            {"nome": n, "url": BASE + n, "rendicao": rend} for n, rend in files
        ],
        "numero_divergente": None,
        "identidade_incerta": incerta,
    }


def _catalog(records: list[dict[str, Any]]) -> comp.Catalog:
    pages: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in records:
        pages.setdefault((r["tipo"], r["ano"]), []).append(r)
    return comp.Catalog(
        ente="ro",
        fonte="casacivil",
        pages=[
            comp.YearPage(
                tipo,
                ano,
                "u",
                comp.STATUS_OK,
                fetched_at="2026-11-16T00:00:00+00:00",
                declarados=len(recs),
                records=recs,
            )
            for (tipo, ano), recs in sorted(pages.items())
        ],
    )


RECORDS = [
    _rec(
        "lei",
        100,
        "1990-01-01",
        "Autoriza o Poder Executivo a abrir crédito suplementar.",
        [("L100.pdf", "original")],
    ),
    _rec(
        "lei",
        200,
        "1995-05-05",
        "Altera a Lei nº 100, de 1 de janeiro de 1990, que dispõe sobre plano de carreira.",
        [("L200.pdf", "original"), ("L200 - COMPILADA.pdf", "compilada")],
    ),
    _rec(
        "decreto",
        300,
        "1996-06-06",
        "Abre crédito. REVOGADO PELO DECRETO N° 400, DE 7/7/1997.",
        [("D300.pdf", "original")],
    ),
    _rec(
        "decreto",
        400,
        "1997-07-07",
        "Declara a revogação de Decretos.",
        [("D400.pdf", "original"), ("D400 - RETIFICADO.pdf", "retificado")],
        incerta=True,
    ),
    _rec(
        "lc",
        50,
        "1992-02-02",
        "Dispõe sobre X.",
        [("LC50 - REVOGADO.pdf", "revogado")],
    ),
]


def _rows(holdings: Optional[comp.Holdings] = None) -> list[dict[str, Any]]:
    return comp.build_ledger(
        _catalog(RECORDS), holdings or comp.Holdings(ok_s2_s3=False)
    )


class TestNormalizarBusca:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("Lei nº 1.234 — Crédito Suplementar", "lei n 1 234 credito suplementar"),
            ("  AÇÃO   Pública, §2º  ", "acao publica 2"),
            ("Decreto-Lei n. 9A", "decreto lei n 9a"),
            ("Orçamento-Programa (ICMS/RO)", "orcamento programa icms ro"),
            ("", ""),
            ("ç ã é ü ñ", "c a e u n"),
        ],
    )
    def test_casos(self, texto: str, esperado: str) -> None:
        # Os mesmos casos estão em web/src/lib/catalogo.test.ts: o portal aplica
        # exatamente este algoritmo à consulta.
        assert catalogo.normalizar_busca(texto) == esperado

    def test_campo_busca_junta_titulo_e_ementa(self) -> None:
        assert catalogo.campo_busca("Lei n. 80, de 1983", "Crédito Suplementar") == (
            "lei n 80 de 1983 credito suplementar"
        )


class TestSituacaoDaNorma:
    def test_sem_indicacao(self) -> None:
        assert catalogo.situacao_da_norma(["original"], "Dispõe sobre X.") == (
            "sem-indicacao-de-revogacao",
            [],
        )

    def test_rendicao_revogado_e_anotacao(self) -> None:
        assert catalogo.situacao_da_norma(["revogado"], "X.") == (
            "revogada",
            ["rendicao-revogado"],
        )
        assert catalogo.situacao_da_norma(
            ["original"], "Abre crédito. REVOGADO PELO DECRETO N° 25210, DE 9/7/2020"
        ) == ("revogada", ["anotacao-na-ementa"])

    def test_parcialmente_revogado_nao_e_revogada(self) -> None:
        assert (
            catalogo.situacao_da_norma(
                ["original"], "X. REVOGADO PARCIALMENTE PELA LEI N° 5, DE 1/1/2000"
            )[0]
            == "sem-indicacao-de-revogacao"
        )

    def test_prioridade_e_evidencias_completas(self) -> None:
        situacao, ev = catalogo.situacao_da_norma(
            ["original", "compilada", "retificado", "revogado"], ""
        )
        assert situacao == "revogada"
        assert ev == ["rendicao-revogado", "rendicao-retificado", "rendicao-compilada"]
        assert (
            catalogo.situacao_da_norma(["retificado", "compilada"], "")[0]
            == "retificada"
        )
        assert catalogo.situacao_da_norma(["compilada"], "")[0] == "tem-compilada"

    def test_rendicao_outra_nao_altera_a_situacao(self) -> None:
        assert (
            catalogo.situacao_da_norma(["outra"], "")[0] == "sem-indicacao-de-revogacao"
        )


class TestLedgerExtendido:
    def test_colunas_derivadas(self) -> None:
        rows = {r["norma_id"].split("casacivil-")[1]: r for r in _rows()}
        lei200 = rows["lei-00200"]
        assert lei200["situacao_norma"] == "tem-compilada"
        assert lei200["rendicoes"] == "compilada,original"
        assert lei200["url_oficial"] == BASE + "L200.pdf"
        assert lei200["link_publico"] == BASE + "L200.pdf"  # sem IA: link oficial
        assert lei200["url_ia"] is None
        assert lei200["busca"] == catalogo.campo_busca(
            lei200["titulo"], lei200["ementa"]
        )
        assert "plano de carreira" in lei200["busca"]
        assert rows["decreto-00300"]["situacao_norma"] == "revogada"
        assert rows["decreto-00300"]["situacao_evidencias"] == "anotacao-na-ementa"
        assert rows["decreto-00400"]["situacao_norma"] == "retificada"
        assert rows["decreto-00400"]["identidade_incerta"] is True
        assert rows["lc-00050"]["situacao_norma"] == "revogada"
        assert rows["lc-00050"]["url_oficial"] == BASE + "LC50 - REVOGADO.pdf"

    def test_link_publico_prefere_o_pdf_no_ia(self) -> None:
        held = comp.Holdings(
            held={
                ("lei", 100): comp.Held(
                    ia_item="leizilla_ro_casacivil_lei_0001-1000",
                    captures=[
                        comp.Capture(
                            key="l100.pdf",
                            sha256="a",
                            has_text=True,
                            pdf_name="lei-00100_abc.pdf",
                        )
                    ],
                )
            }
        )
        rows = {r["norma_id"]: r for r in _rows(held)}
        r = rows["leizilla-raw-ro-casacivil-lei-00100"]
        assert r["url_ia"] == (
            "https://archive.org/download/leizilla_ro_casacivil_lei_0001-1000/"
            "lei-00100_abc.pdf"
        )
        assert r["link_publico"] == r["url_ia"]
        assert r["url_oficial"] == BASE + "L100.pdf"

    def test_orfa_tem_busca_minima(self) -> None:
        held = comp.Holdings(
            held={
                ("lei", 7): comp.Held(
                    ia_item="i", captures=[comp.Capture("k", "s", None)]
                )
            }
        )
        orfa = next(r for r in _rows(held) if r["situacao"] != "listada")
        assert orfa["busca"] == "lei 7"
        assert orfa["situacao_norma"] is None

    def test_parquet_tem_todas_as_colunas_do_contrato(self, tmp_path: Path) -> None:
        import duckdb

        path = tmp_path / "completeness.parquet"
        comp.write_ledger_parquet(_rows(), path)
        conn = duckdb.connect()
        try:
            cols = [
                d[0]
                for d in conn.execute(
                    "SELECT * FROM read_parquet(?) LIMIT 0", [str(path)]
                ).description
            ]
        finally:
            conn.close()
        assert cols == list(comp.LEDGER_SCHEMA)


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    rows = _rows()
    ledger = tmp_path / "completeness.parquet"
    comp.write_ledger_parquet(rows, ledger)
    rel_rows = relacoes.construir_relacoes(rows)
    rel_path = tmp_path / "relacoes.parquet"
    relacoes.write_relacoes_parquet(rel_rows, rel_path)
    summary = tmp_path / "completeness.json"
    summary.write_text(
        json.dumps({"normas_listadas": sum(r["situacao"] == "listada" for r in rows)}),
        encoding="utf-8",
    )
    return ledger, rel_path, summary


class TestGates:
    def test_arquivos_validos_passam(self, files: tuple[Path, Path, Path]) -> None:
        assert catalogo.validate_catalogo_files(files[0], files[1]) == []

    def test_relacao_com_origem_fora_do_catalogo_falha(
        self, tmp_path: Path, files: tuple[Path, Path, Path]
    ) -> None:
        bad = relacoes.construir_relacoes(_rows())
        bad[0] = {**bad[0], "origem_id": "leizilla-raw-ro-casacivil-lei-99999"}
        path = tmp_path / "bad.parquet"
        relacoes.write_relacoes_parquet(bad, path)
        problems = catalogo.validate_catalogo_files(files[0], path)
        assert any("origem_id fora do catálogo" in p for p in problems)

    def test_resolvida_sem_alvo_e_confianca_incoerente(
        self, tmp_path: Path, files: tuple[Path, Path, Path]
    ) -> None:
        bad = relacoes.construir_relacoes(_rows())
        bad[0] = {**bad[0], "confianca": "resolvida", "alvo_id": None}
        path = tmp_path / "bad.parquet"
        relacoes.write_relacoes_parquet(bad, path)
        assert any(
            "incoerente" in p for p in catalogo.validate_catalogo_files(files[0], path)
        )

    def test_verbo_fora_do_conjunto(
        self, tmp_path: Path, files: tuple[Path, Path, Path]
    ) -> None:
        bad = relacoes.construir_relacoes(_rows())
        bad[0] = {**bad[0], "verbo": "inventa"}
        path = tmp_path / "bad.parquet"
        relacoes.write_relacoes_parquet(bad, path)
        assert any(
            "verbo" in p for p in catalogo.validate_catalogo_files(files[0], path)
        )

    def test_norma_id_duplicado_e_situacao_fora_do_dominio(
        self, tmp_path: Path, files: tuple[Path, Path, Path]
    ) -> None:
        rows = _rows()
        rows.append({**rows[0]})
        rows[1] = {**rows[1], "situacao_norma": "vigente"}
        path = tmp_path / "dup.parquet"
        comp.write_ledger_parquet(rows, path)
        problems = catalogo.validate_catalogo_files(path, files[1])
        assert any("duplicado" in p for p in problems)
        assert any("situacao_norma fora do domínio" in p for p in problems)

    def test_coluna_ausente(
        self, tmp_path: Path, files: tuple[Path, Path, Path]
    ) -> None:
        import duckdb

        path = tmp_path / "old.parquet"
        conn = duckdb.connect()
        try:
            conn.execute(
                f"COPY (SELECT * EXCLUDE (busca) FROM read_parquet('{files[0]}')) "
                f"TO '{path}' (FORMAT parquet)"
            )
        finally:
            conn.close()
        assert any(
            "busca" in p for p in catalogo.validate_catalogo_files(path, files[1])
        )

    def test_piso_publicado(self) -> None:
        assert catalogo.published_floor({"normas_listadas": 12}) == 12
        assert (
            catalogo.published_floor(
                {"tipos": [{"listadas": 3}, {"listadas": None}, {"listadas": 4}]}
            )
            == 7
        )
        assert catalogo.published_floor({"tipos": []}) is None
        assert catalogo.published_floor({}) is None


class TestReleaseCatalogoCli:
    def _run(self, files: tuple[Path, Path, Path], *extra: str) -> Any:
        return CliRunner().invoke(
            app,
            [
                "release-catalogo",
                str(files[0]),
                str(files[1]),
                "--summary",
                str(files[2]),
                *extra,
            ],
        )

    def test_dry_run_valida_sem_subir(self, files: tuple[Path, Path, Path]) -> None:
        result = self._run(files, "--dry-run")
        assert result.exit_code == 0, result.output
        assert "5 normas listadas" in result.output
        assert "nenhum upload" in result.output

    def test_contrato_violado_aborta(
        self, tmp_path: Path, files: tuple[Path, Path, Path]
    ) -> None:
        bad = relacoes.construir_relacoes(_rows())
        bad[0] = {**bad[0], "verbo": "inventa"}
        broken = tmp_path / "broken.parquet"
        relacoes.write_relacoes_parquet(bad, broken)
        result = self._run((files[0], broken, files[2]), "--dry-run")
        assert result.exit_code == 1
        assert "Gate de release falhou" in result.output

    def test_piso_barra_queda(self, files: tuple[Path, Path, Path]) -> None:
        with patch("leizilla.catalogo.fetch_published_floor", return_value=9000):
            result = self._run(files)
        assert result.exit_code == 1
        assert "abaixo do piso publicado de 9000" in result.output

    def test_piso_indeterminado_barra(self, files: tuple[Path, Path, Path]) -> None:
        with patch(
            "leizilla.catalogo.fetch_published_floor",
            side_effect=RuntimeError("HTTP 503"),
        ):
            result = self._run(files)
        assert result.exit_code == 1
        assert "não foi possível verificar o piso" in result.output

    def test_publica_nomes_fixos_no_ponteiro_latest(
        self, files: tuple[Path, Path, Path]
    ) -> None:
        calls: list[list[str]] = []

        def fake_upload(self: Any, args: list[str]) -> None:
            calls.append([a if i < 3 else Path(a).name for i, a in enumerate(args)])

        with (
            patch("leizilla.catalogo.fetch_published_floor", return_value=None),
            patch("leizilla.config.IA_ACCESS_KEY", "k"),
            patch("leizilla.config.IA_SECRET_KEY", "s"),
            patch(
                "leizilla.publisher.InternetArchivePublisher._run_ia_upload",
                fake_upload,
            ),
        ):
            result = self._run(files)
        assert result.exit_code == 0, result.output
        assert calls == [
            [
                "ia",
                "upload",
                "leizilla-dataset-ro-v0-latest",
                "completeness.parquet",
                "completeness.json",
                "relacoes.parquet",
                "--no-derive",
            ]
        ]

    def test_allow_lower_count_publica_mesmo_assim(
        self, files: tuple[Path, Path, Path]
    ) -> None:
        with (
            patch("leizilla.catalogo.fetch_published_floor", return_value=9000),
            patch("leizilla.config.IA_ACCESS_KEY", "k"),
            patch("leizilla.config.IA_SECRET_KEY", "s"),
            patch(
                "leizilla.publisher.InternetArchivePublisher._run_ia_upload",
                lambda self, args: None,
            ),
        ):
            result = self._run(files, "--allow-lower-count")
        assert result.exit_code == 0, result.output
        assert "ignorado" in result.output


def test_completeness_cli_escreve_relacoes_sem_ia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``completeness --sem-ia`` não toca no IA e grava catálogo + relações."""
    snapshot = tmp_path / "snap.json.gz"
    comp.write_catalog_snapshot(_catalog(RECORDS), snapshot)

    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("o IA não deve ser consultado")

    monkeypatch.setattr(comp, "collect_holdings", boom)
    monkeypatch.setattr(comp, "fetch_published_textos", boom)
    monkeypatch.setattr(
        comp,
        "year_index_configs",
        lambda ente, fonte: [{"strategy": "casacivil-year-index"}],
    )
    monkeypatch.setattr(comp, "fontes_with_official_index", lambda ente: ["casacivil"])
    monkeypatch.setattr(
        comp,
        "fetch_catalog",
        lambda ente, fonte, **k: _catalog(RECORDS),
    )
    result = CliRunner().invoke(
        app,
        [
            "completeness",
            "--sem-ia",
            "--output",
            str(tmp_path / "completeness.parquet"),
            "--catalog-snapshot",
            str(snapshot),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "relacoes.parquet").exists()
    summary = json.loads((tmp_path / "completeness.json").read_text("utf-8"))
    assert summary["normas_listadas"] == 5
    assert summary["relacoes"]["total"] == 1
    assert summary["relacoes"]["por_confianca"]["resolvida"] == 1

    with_upload = CliRunner().invoke(
        app,
        [
            "completeness",
            "--sem-ia",
            "--upload",
            "--output",
            str(tmp_path / "x.parquet"),
        ],
    )
    assert with_upload.exit_code == 1
