"""Testes das relações lidas das ementas (leizilla.relacoes) — regras, sem modelo.

As ementas são redações reais do índice oficial da Casa Civil de Rondônia. Tudo
offline e determinístico.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from leizilla import relacoes as rel


def _ler(ementa: str) -> list[tuple[str, str, Optional[int], str, Optional[str]]]:
    """``(verbo, tipo, numero, sufixo, data|ano)`` de cada relação da ementa."""
    return [
        (r.verbo, r.ref.tipo, r.ref.numero, r.ref.sufixo, r.ref.data or r.ref.ano)  # type: ignore[misc]
        for r in rel.extrair_da_ementa(ementa)
    ]


class TestFold:
    def test_keeps_length_and_strips_accents_and_ordinals(self) -> None:
        text = "Dá nova redação ao art. 3º — Lei nº 1.234, de 5 de maio de 2003"
        folded = rel.fold(text)
        assert len(folded) == len(text)
        assert folded.startswith("da nova redacao ao art. 3o")
        assert "lei no 1.234" in folded


class TestVerbosEReferencias:
    def test_altera_simples_com_data_por_extenso(self) -> None:
        assert _ler("Altera a Lei nº 1.234, de 5 de maio de 2003.") == [
            ("altera", "lei", 1234, "", "2003-05-05")
        ]

    def test_decreto_com_sei_depois_do_ponto_nao_gera_relacao_extra(self) -> None:
        got = _ler(
            "Altera dispositivos do Decreto n° 29.095, de 9 de maio de 2024. SEI N° 0033.033334/2023-87."
        )
        assert got == [("altera", "decreto", 29095, "", "2024-05-09")]

    def test_altera_e_acresce_partilham_o_alvo(self) -> None:
        got = _ler(
            "Altera e acresce dispositivos ao Decreto n° 10.114, de 20 de setembro de 2002."
        )
        assert got == [
            ("altera", "decreto", 10114, "", "2002-09-20"),
            ("acrescenta", "decreto", 10114, "", "2002-09-20"),
        ]

    def test_da_nova_redacao_com_intervalo_de_artigos(self) -> None:
        got = _ler(
            "Dá nova redação aos arts. 3º e 4º da Lei Complementar nº 68, de 9 de dezembro de 1992."
        )
        assert got == [("da-nova-redacao", "lc", 68, "", "1992-12-09")]

    def test_altera_a_redacao_e_da_nova_redacao_nao_viram_altera(self) -> None:
        got = _ler(
            "Altera redação do artigo 4º-A da Lei n° 1.558, de 26 de dezembro de 2005."
        )
        assert [g[0] for g in got] == ["da-nova-redacao"]

    def test_revoga_e_regulamenta_e_prorroga(self) -> None:
        assert _ler("Revoga o Decreto nº 5.678.")[0][:3] == ("revoga", "decreto", 5678)
        assert _ler("Regulamenta a Lei nº 2182, de 25 de novembro de 2009.") == [
            ("regulamenta", "lei", 2182, "", "2009-11-25")
        ]
        assert _ler(
            "Prorroga a Lei nº 970, de 14 de março de 2001, e dá outras providências."
        ) == [("prorroga", "lei", 970, "", "2001-03-14")]

    def test_outro_so_para_o_conjunto_fechado(self) -> None:
        assert _ler(
            "Retifica o inciso VII, do artigo 1º, do Decreto n 20.208, de 7 de outubro de 2015."
        ) == [("outro", "decreto", 20208, "", "2015-10-07")]
        assert _ler(
            "Altera e suprime dispositivos da Lei Complementar n.º 168, de 27 de dezembro de 1996."
        )[1][:3] == ("outro", "lc", 168)

    def test_introduz_alteracoes_e_fica_alterado(self) -> None:
        assert _ler(
            "Introduz alterações na Lei nº 912, de 12 de julho de 2000, que dispõe sobre a estrutura."
        ) == [("altera", "lei", 912, "", "2000-07-12")]
        assert _ler("Fica revogado o Decreto nº 100, de 3 de março de 1990.")[0][
            :3
        ] == (
            "revoga",
            "decreto",
            100,
        )


class TestListasEFormas:
    def test_lista_de_numeros_com_ns(self) -> None:
        got = _ler("Revoga as Leis nºs 100, 200 e 300 e o Decreto nº 5.678.")
        assert [(g[1], g[2]) for g in got] == [
            ("lei", 100),
            ("lei", 200),
            ("lei", 300),
            ("decreto", 5678),
        ]

    def test_lista_com_marca_repetida_e_datas(self) -> None:
        got = _ler(
            "Revoga as Leis n° 121, de 21 de julho de 1986, e n° 315, de 3 de julho de 1991."
        )
        assert got == [
            ("revoga", "lei", 121, "", "1986-07-21"),
            ("revoga", "lei", 315, "", "1991-07-03"),
        ]

    def test_lista_com_barra_de_ano_e_ns_sem_o(self) -> None:
        got = _ler(
            "Nomeia os membros e revoga os Decretos n.ºs 5981/93, 6033/93, 6358/94 e 6357/94."
        )
        assert [(g[2], g[4]) for g in got] == [
            (5981, 1993),
            (6033, 1993),
            (6358, 1994),
            (6357, 1994),
        ]
        assert [
            g[2]
            for g in _ler(
                "Revoga os Decretos ns. 16.926, de 19 de julho de 2012 e 16.946, de 26 de julho de 2012."
            )
        ] == [16926, 16946]

    def test_lc_abreviada_com_barra(self) -> None:
        assert _ler("Altera a LC 68/92.") == [("altera", "lc", 68, "", 1992)]

    def test_numero_sem_marca_e_barra_curta(self) -> None:
        assert _ler(
            "Acrescenta dispositivos ao decreto 14053/09 para disciplinar o arquivamento."
        ) == [("acrescenta", "decreto", 14053, "", 2009)]

    def test_sufixo_de_letra(self) -> None:
        got = _ler("Altera o Decreto Lei nº 9A, de 3.2.82.")
        assert got == [("altera", "decreto-lei", 9, "A", "1982-02-03")]

    def test_data_numerica_e_ano_com_ponto(self) -> None:
        assert _ler("Altera o Decreto nº 6, de 31.12.81.")[0][4] == "1981-12-31"
        assert (
            _ler(
                "Dá nova redação ao art. 1º do Decreto n° 2.566 de 02 de janeiro de 1.985."
            )[0][4]
            == "1985-01-02"
        )

    def test_data_sem_de_antes_do_mes(self) -> None:
        got = _ler("Altera o Decreto nº 933, de 22 agosto de 1.978.")
        assert got[0][4] == "1978-08-22"

    def test_virgula_sem_de_antes_do_dia(self) -> None:
        assert (
            _ler(
                "Altera e acresce dispositivos ao Decreto n° 28.613, 28 de novembro de 2023."
            )[0][4]
            == "2023-11-28"
        )

    def test_data_ilegivel_nunca_vira_resolvida(self) -> None:
        r = rel.extrair_da_ementa("Altera a Lei nº 100 de 15 dias.")[0]
        assert r.ref.data_ilegivel is True
        idx = rel.Indice.de_linhas([_row("lei", 100, "2003-05-05")])
        assert rel.resolver(r.ref, idx, ator_data=None, ator_id=None)[1:] == (
            rel.CONFIANCA_NAO_RESOLVIDA,
            "data-ilegivel",
        )


class TestEscopo:
    def test_oracao_relativa_nao_gera_alvo_nem_verbo(self) -> None:
        got = _ler(
            "Altera o Art. 2º do Decreto nº 4603, de 10 de abril de 1990, que “Dispõe sobre a desativação, e revoga a Lei nº 5”."
        )
        assert got == [("altera", "decreto", 4603, "", "1990-04-10")]
        assert _ler("Altera a Lei nº 100, que revoga o Decreto nº 7.") == [
            ("altera", "lei", 100, "", None)
        ]

    def test_participio_passivo_nao_e_alvo(self) -> None:
        got = _ler(
            "Altera dispositivos da Lei nº 301, de 21 de dezembro de 1990, alterada pela Lei nº 475, de 26 de abril de 1993."
        )
        assert [g[2] for g in got] == [301]

    def test_aprovado_pelo_decreto_nao_e_alvo(self) -> None:
        assert (
            _ler(
                "Altera dispositivo do RICMS/RO, aprovado pelo Decreto nº 8321, de 30 de abril de 1998."
            )
            == []
        )

    def test_instituido_por_nao_e_alvo(self) -> None:
        assert (
            _ler(
                "Prorroga o prazo para adesão ao Programa instituído pela Lei n° 6.329, de 4 de fevereiro de 2026."
            )
            == []
        )

    def test_prorroga_prazo_estabelecido_no_decreto_e_alvo(self) -> None:
        assert _ler(
            "Prorroga prazo estabelecido no Decreto nº 7763, de 19 de março de 1997."
        ) == [("prorroga", "decreto", 7763, "", "1997-03-19")]

    def test_verbo_desconhecido_encerra_o_escopo(self) -> None:
        got = _ler(
            "Altera dispositivos da Lei nº 5.073, de 22 de julho de 2021 e cria Ação nas Leis n° 5.246, de 10 de janeiro de 2022 e n° 4.647, de 18 de novembro de 2019."
        )
        assert [g[2] for g in got] == [5073]

    def test_substantivo_depois_de_e_nao_corta(self) -> None:
        got = _ler(
            "Altera o Código de Organização e Divisão Judiciária – Decreto-Lei nº 8, de 25 de janeiro de 1982."
        )
        assert got == [("altera", "decreto-lei", 8, "", "1982-01-25")]

    def test_adjunto_nao_derruba_verbo_coordenado(self) -> None:
        got = _ler(
            "Regulamenta o pagamento, nos termos do § 1° do artigo 102 do ADCT, e revoga o Decreto n° 23.311, de 3 de maio de 2018."
        )
        assert got == [("revoga", "decreto", 23311, "", "2018-05-03")]

    def test_texto_entre_aspas_e_ignorado(self) -> None:
        assert _ler("Cria o Comitê, nos termos do “Altera a Lei nº 9”.") == []

    def test_ementa_inteira_entre_aspas_vale(self) -> None:
        assert (
            _ler(
                "“Altera e revoga dispositivos da Lei n° 547, de 30 de dezembro de 1993”."
            )[0][2]
            == 547
        )

    def test_autoriza_nos_termos_da_lei_nao_e_relacao(self) -> None:
        assert (
            _ler(
                "Autoriza o Poder Executivo a contratar, nos termos da Lei nº 1.234, de 5 de maio de 2003."
            )
            == []
        )

    def test_verbo_nominal_nao_conta(self) -> None:
        assert _ler("Dispõe sobre a revogação do Decreto nº 5.678.") == []
        assert _ler("Autoriza a alterar o Decreto nº 5.678.") == []

    def test_o_primeiro_verbo_sem_alvo_empresta_o_do_seguinte(self) -> None:
        got = _ler(
            "Altera o art. 6° e acrescenta os §§ 1° e 2° ao art. 5°, ambos da Lei Estadual n° 5.734, de 9 de janeiro de 2024."
        )
        assert [g[0] for g in got] == ["altera", "acrescenta"]

    def test_parcial(self) -> None:
        total = rel.extrair_da_ementa(
            "Revoga o Decreto nº 5.678, de 3 de maio de 2003."
        )[0]
        parcial = rel.extrair_da_ementa(
            "Revoga o inciso II do art. 8º do Decreto nº 14.103, de 16 de fevereiro de 2009."
        )[0]
        assert (total.parcial, parcial.parcial) == (False, True)
        assert rel.extrair_da_ementa(
            "Acrescenta dispositivos à Lei nº 1.042, de 20 de janeiro de 2002."
        )[0].parcial


class TestForaDoCatalogo:
    def test_federal_e_constituicao_nunca_resolvem(self) -> None:
        idx = rel.Indice.de_linhas([_row("lei", 8666, "1993-06-21")])
        refs = rel.extrair_da_ementa(
            "Altera a Lei Federal nº 8.666, de 21 de junho de 1993, e a Constituição Estadual."
        )
        got = [
            rel.resolver(r.ref, idx, ator_data="2020-01-01", ator_id=None)[1:]
            for r in refs
        ]
        assert got == [
            (rel.CONFIANCA_NAO_RESOLVIDA, "federal"),
            (rel.CONFIANCA_NAO_RESOLVIDA, "constituicao-estadual"),
        ]

    def test_tipos_sem_indice(self) -> None:
        idx = rel.Indice()
        r = rel.extrair_da_ementa("Revoga a Resolução nº 12, de 3 de maio de 2003.")[0]
        assert r.ref.tipo == "resolucao"
        assert (
            rel.resolver(r.ref, idx, ator_data=None, ator_id=None)[2]
            == "tipo-sem-indice"
        )
        r = rel.extrair_da_ementa("Altera a Emenda Constitucional nº 25.")[0]
        assert (
            rel.resolver(r.ref, idx, ator_data=None, ator_id=None)[2]
            == "tipo-sem-indice"
        )

    def test_qualificador_federal_depois_do_numero(self) -> None:
        r = rel.extrair_da_ementa(
            "Altera a Lei nº 4.320, federal, de 17 de março de 1964."
        )[0]
        assert r.ref.categoria == rel.CAT_FEDERAL


def _row(
    tipo: str,
    numero: int,
    data: Optional[str],
    sufixo: str = "",
    incerta: bool = False,
    ementa: str = "",
) -> dict[str, Any]:
    return {
        "situacao": "listada",
        "norma_id": f"leizilla-raw-ro-casacivil-{tipo}-{numero:05d}{sufixo.lower()}",
        "tipo": tipo,
        "numero": numero,
        "sufixo": sufixo,
        "data": data,
        "ano": int(data[:4]) if data else None,
        "ementa": ementa,
        "titulo": f"{tipo} {numero}",
        "identidade_incerta": incerta,
    }


class TestResolucao:
    def _alvo(
        self, text: str, rows: list[dict[str, Any]], ator: str = "2030-01-01"
    ) -> tuple[Optional[str], str, Optional[str]]:
        ref = rel.extrair_da_ementa(text)[0].ref
        return rel.resolver(
            ref, rel.Indice.de_linhas(rows), ator_data=ator, ator_id=None
        )

    def test_resolvida_com_data_igual(self) -> None:
        rows = [_row("lei", 1234, "2003-05-05")]
        assert self._alvo("Altera a Lei nº 1.234, de 5 de maio de 2003.", rows) == (
            "leizilla-raw-ro-casacivil-lei-01234",
            "resolvida",
            None,
        )

    def test_numero_igual_com_data_de_outro_ano_nao_resolve(self) -> None:
        rows = [_row("lei", 4320, "2018-03-10")]
        assert self._alvo("Altera a Lei nº 4.320, de 17 de março de 1964.", rows)[
            1:
        ] == (
            "nao-resolvida",
            "data-diverge",
        )

    def test_mesmo_ano_com_dia_diferente_resolve_com_nota(self) -> None:
        rows = [_row("decreto", 25194, "2020-06-03")]
        got = self._alvo("Altera o Decreto n° 25.194, de 3 de julho de 2020.", rows)
        assert got[1:] == ("resolvida", "data-diverge-mesmo-ano")

    def test_sem_data_resolve_com_nota_sem_data(self) -> None:
        rows = [_row("lei", 100, "1990-01-01")]
        assert self._alvo("Altera a Lei nº 100.", rows)[1:] == ("resolvida", "sem-data")

    def test_ausente_do_indice(self) -> None:
        assert self._alvo("Altera a Lei nº 100.", [])[1:] == (
            "nao-resolvida",
            "ausente-do-indice",
        )

    def test_cronologia_uma_norma_nao_altera_outra_posterior(self) -> None:
        rows = [_row("lei", 100, "2031-01-01")]
        assert self._alvo("Altera a Lei nº 100.", rows)[1:] == (
            "nao-resolvida",
            "cronologia",
        )

    def test_sufixo_diverge_e_ambigua(self) -> None:
        rows = [_row("lei", 88, "1986-01-07", sufixo="M")]
        got = self._alvo(
            "Dá nova redação a dispositivos da Lei nº 88 de 07 de janeiro de 1986.",
            rows,
        )
        assert (
            got[0] is None
            and got[1] == "ambigua"
            and "sufixo-diverge" in (got[2] or "")
        )

    def test_sufixo_exato_resolve_entre_irmaos(self) -> None:
        rows = [
            _row("decreto-lei", 9, "1982-01-01"),
            _row("decreto-lei", 9, "1982-02-03", sufixo="A"),
        ]
        got = self._alvo("Altera o Decreto Lei nº 9A, de 3.2.82.", rows)
        assert got[0] == "leizilla-raw-ro-casacivil-decreto-lei-00009a"

    def test_identidade_incerta_do_alvo_e_ambigua(self) -> None:
        rows = [_row("decreto", 10373, "2003-02-17", incerta=True)]
        got = self._alvo("Revoga o Decreto nº 10373, de 17 de fevereiro de 2003.", rows)
        assert got[1:] == ("ambigua", "identidade-incerta")
        assert got[0] is not None

    def test_autorreferencia(self) -> None:
        rows = [_row("lei", 100, "1990-01-01")]
        ref = rel.extrair_da_ementa("Altera a Lei nº 100.")[0].ref
        got = rel.resolver(
            ref,
            rel.Indice.de_linhas(rows),
            ator_data=None,
            ator_id="leizilla-raw-ro-casacivil-lei-00100",
        )
        assert got[1:] == ("nao-resolvida", "autorreferencia")


class TestConstruirRelacoes:
    def _rows(self) -> list[dict[str, Any]]:
        return [
            _row("lei", 100, "1990-01-01", ementa="Dispõe sobre X."),
            _row(
                "lei",
                200,
                "1995-05-05",
                ementa="Altera a Lei nº 100, de 1 de janeiro de 1990, e a Lei Federal nº 8.666.",
            ),
            _row(
                "decreto",
                300,
                "1996-06-06",
                ementa="Revoga o Decreto nº 5.678.",
            ),
            _row(
                "decreto",
                400,
                "1997-07-07",
                ementa="Abre crédito. REVOGADO PELO DECRETO N° 500, DE 9/7/2020.",
            ),
            _row(
                "decreto", 500, "2020-07-09", ementa="Declara a revogação de Decretos."
            ),
        ]

    def test_linhas_do_contrato(self) -> None:
        out = rel.construir_relacoes(self._rows())
        assert set(out[0]) == set(rel.RELACOES_SCHEMA)
        assert {r["verbo"] for r in out} <= set(rel.VERBOS)
        assert {r["confianca"] for r in out} <= set(rel.CONFIANCAS)
        assert len({r["relacao_id"] for r in out}) == len(out)

    def test_resolvida_naoresolvida_e_anotacao_invertida(self) -> None:
        out = rel.construir_relacoes(self._rows())
        by = {(r["origem_id"][-9:], r["verbo"], r["alvo_numero"]): r for r in out}
        ok = by[("lei-00200", "altera", 100)]
        assert (ok["confianca"], ok["alvo_id"]) == (
            "resolvida",
            "leizilla-raw-ro-casacivil-lei-00100",
        )
        fed = by[("lei-00200", "altera", 8666)]
        assert (fed["confianca"], fed["alvo_id"], fed["nota"]) == (
            "nao-resolvida",
            None,
            "federal",
        )
        ausente = by[("eto-00300", "revoga", 5678)]
        assert ausente["nota"] == "ausente-do-indice"
        # Anotação "REVOGADO PELO DECRETO N° 500": a origem é o 500, o alvo é o 400.
        ann = by[("eto-00500", "revoga", 400)]
        assert ann["fonte_relacao"] == "anotacao-do-indice"
        assert ann["alvo_id"] == "leizilla-raw-ro-casacivil-decreto-00400"
        assert ann["confianca"] == "resolvida"

    def test_anotacao_com_origem_nao_resolvida_nao_emite(self) -> None:
        rows = [
            _row(
                "decreto",
                400,
                "1997-07-07",
                ementa="X. REVOGADO PELO DECRETO N° 999, DE 9/7/2020.",
            )
        ]
        assert rel.construir_relacoes(rows) == []

    def test_anotacao_nao_duplica_a_relacao_da_ementa(self) -> None:
        rows = [
            _row(
                "decreto",
                400,
                "1997-07-07",
                ementa="X. REVOGADO PELO DECRETO N° 500, DE 9/7/2020.",
            ),
            _row(
                "decreto",
                500,
                "2020-07-09",
                ementa="Revoga o Decreto nº 400, de 7 de julho de 1997.",
            ),
        ]
        out = rel.construir_relacoes(rows)
        assert len(out) == 1 and out[0]["fonte_relacao"] == "ementa"

    def test_origem_com_identidade_incerta_nunca_e_resolvida(self) -> None:
        rows = [
            _row("lei", 100, "1990-01-01"),
            _row(
                "lei",
                200,
                "1995-05-05",
                incerta=True,
                ementa="Altera a Lei nº 100, de 1 de janeiro de 1990.",
            ),
        ]
        out = rel.construir_relacoes(rows)
        assert (out[0]["confianca"], out[0]["nota"]) == (
            "ambigua",
            "origem-identidade-incerta",
        )

    def test_ementa_vazia_e_orfa_sao_ignoradas(self) -> None:
        rows = [_row("lei", 100, "1990-01-01", ementa="")]
        rows.append(
            {
                **_row("lei", 7, None, ementa="Revoga a Lei nº 1."),
                "situacao": "fora-do-indice",
            }
        )
        assert rel.construir_relacoes(rows) == []

    def test_parquet_round_trip(self, tmp_path: Any) -> None:
        import duckdb

        out = rel.construir_relacoes(self._rows())
        path = tmp_path / "relacoes.parquet"
        rel.write_relacoes_parquet(out, path)
        conn = duckdb.connect()
        try:
            cols = [
                d[0]
                for d in conn.execute(
                    "SELECT * FROM read_parquet(?) LIMIT 0", [str(path)]
                ).description
            ]
            n = conn.execute(
                "SELECT COUNT(*) FROM read_parquet(?)", [str(path)]
            ).fetchone()[0]  # type: ignore[index]
        finally:
            conn.close()
        assert cols == list(rel.RELACOES_SCHEMA)
        assert n == len(out)


@pytest.mark.parametrize(
    "ementa",
    [
        "Abre no Orçamento-Programa Anual do Estado de Rondônia, Crédito Adicional Suplementar no valor de R$ 100.000,00 para reforço de dotações.",
        "Fica alterada a Programação das Quotas Trimestrais no Orçamento Vigente.",
        "Prorroga cedência de Praça da Polícia Militar de Rondônia e dá outras providências. SEI N° 0014.000642/2025-16.",
        "Aprova o Regimento Interno do Conselho Penitenciário, criado pelo Decreto nº 19, de 31 de dezembro de 1981.",
    ],
)
def test_ementas_sem_alvo_nao_geram_relacao(ementa: str) -> None:
    assert rel.extrair_da_ementa(ementa) == []
