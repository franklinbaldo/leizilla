"""Identificadores do SEI como proveniência na camada de texto (colunas ``sei_*``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from leizilla import sei, textlayer
from test_textlayer import CLOSING, _build, _default_ia
from test_textlayer import _no_network_no_sleep as _offline  # noqa: F401

SEI_COLS = (
    "sei_verificador",
    "sei_crc",
    "sei_numero",
    "sei_processo",
    "sei_assinantes",
)

BODY = "Art. 1º Fica criada a coisa.\nArt. 2º Esta Lei entra em vigor.\n"

LEI_FOOTER = (
    "Documento assinado eletronicamente por Marcos José Rocha dos Santos, "
    "Governador, em 16/03/2022, às 15:51, conforme horário oficial de Brasília, "
    "com fundamento no artigo 18 caput e seus §§ 1° e 2°, do Decreto n° 21.794, "
    "de 5 Abril de 2017.\n"
    "A autenticidade deste documento pode ser conferida no site portal do SEI, "
    "informando o código verificador 27366482 e o código CRC BEF99C54.\n"
    "Referência: Caso responda esta Lei, indicar expressamente o Processo nº\n"
    "0035.067835/2022-66        SEI nº 27366482\n"
)

# Ofício do TJ impresso dentro de uma lei de 2017 (forma de lei-01403 e lei-01635).
OFICIO_CITADO = (
    "Documento assinado eletronicamente por FRANKLIN SILVEIRA BALDO, Assessor(a), "
    "em 06/12/2017, às 14:22, conforme horário oficial de Brasília.\n"
    "A autenticidade deste documento pode ser conferida no site "
    "http://sei.sistemas.ro.gov.br/sei/controlador_externo.php?acao=documento_conferir, "
    "informando o código verificador 0437113 e o código CRC 93CE8724.\n"
    "SEI nº 0437113 Referência: Caso responda este Ofício, indicar expressamente o "
    "Processo nº 0020.064169/2017-14\n"
)

DESPACHO_CITADO = (
    "A autenticidade deste documento pode ser conferida no site portal do SEI, "
    "informando o código verificador 1364102 e o código CRC 8BE9F0E6. "
    "Referência: Caso responda este Despacho, indicar expressamente o Processo nº "
    "0014.099712/2018-56 SEI nº 1364102\n"
)


def _cols(text: str) -> dict[str, Any]:
    return sei.sei_columns(text)


def test_own_footer_fills_every_column() -> None:
    cols = _cols(BODY + LEI_FOOTER)
    assert cols["sei_verificador"] == "27366482"
    assert cols["sei_crc"] == "BEF99C54"
    assert cols["sei_numero"] == "27366482"
    assert cols["sei_processo"] == "0035.067835/2022-66"
    assert json.loads(cols["sei_assinantes"]) == [
        {
            "nome": "Marcos José Rocha dos Santos",
            "cargo": "Governador",
            "data": "2022-03-16",
            "hora": "15:51",
        }
    ]


@pytest.mark.parametrize("quoted", [OFICIO_CITADO, DESPACHO_CITADO])
def test_a_sei_document_printed_inside_the_norm_stays_null(quoted: str) -> None:
    # Lei 1403, Lei 1635 (ofício) e Lei 3935 (despacho): o extrator geral acha o par,
    # mas ele não é o rodapé da própria norma.
    text = "LEI Nº 1403\n" + BODY + quoted
    assert sei.has_sei_footer(sei.extract_sei_ids(text))
    assert all(v is None for v in _cols(text).values())


def test_own_footer_wins_over_a_quoted_document_before_it() -> None:
    cols = _cols(BODY + OFICIO_CITADO + BODY + LEI_FOOTER)
    assert cols["sei_verificador"] == "27366482"
    assert cols["sei_crc"] == "BEF99C54"
    # O ofício citado não vaza para os assinantes da norma.
    assert [a["nome"] for a in json.loads(cols["sei_assinantes"])] == [
        "Marcos José Rocha dos Santos"
    ]


@pytest.mark.parametrize(
    "garbled",
    [
        "Caso responda estaLei, indicar expressamente",  # OCR cola as palavras
        "nda esta Lei Complementar, indicar expressamente",  # começo da frase perdido
        "Caso responda este Decreto, indicar expressamente",
    ],
)
def test_ocr_damage_to_the_cue_still_counts_as_the_own_footer(garbled: str) -> None:
    text = LEI_FOOTER.replace("Caso responda esta Lei, indicar expressamente", garbled)
    assert _cols(BODY + text)["sei_verificador"] == "27366482"


def test_verifier_without_crc_or_with_a_disagreeing_sei_number_is_not_filled() -> None:
    sem_crc = LEI_FOOTER.replace(" e o código CRC BEF99C54", "")
    assert all(v is None for v in _cols(BODY + sem_crc).values())
    divergente = LEI_FOOTER.replace("SEI nº 27366482", "SEI nº 2736648")
    assert all(v is None for v in _cols(BODY + divergente).values())


def test_missing_process_or_sei_number_leaves_just_those_columns_null() -> None:
    sem = LEI_FOOTER.replace("0035.067835/2022-66        SEI nº 27366482", "")
    cols = _cols(BODY + sem)
    assert cols["sei_verificador"] == "27366482"
    assert cols["sei_numero"] is None and cols["sei_processo"] is None


def test_signers_are_left_out_when_the_list_cannot_be_trusted() -> None:
    # Duas menções, uma só lida (o OCR quebrou a data da primeira).
    quebrada = (
        "Documento assinado eletronicamente por Beatriz Basilio Mendes, "
        "Secretário(a), em sei! 02/09/2026, às 10:36, conforme horário.\n"
    )
    cols = _cols(BODY + quebrada + LEI_FOOTER)
    assert cols["sei_verificador"] == "27366482"
    assert cols["sei_assinantes"] is None
    # Nome com letra solta em caixa trocada.
    sujo = LEI_FOOTER.replace("Marcos José Rocha dos Santos", "PEDRO ANTONIO AFONsO")
    assert _cols(BODY + sujo)["sei_assinantes"] is None
    assert _cols(BODY + sujo)["sei_verificador"] == "27366482"


def test_two_signers_keep_their_order() -> None:
    dois = (
        "Documento assinado eletronicamente por Beatriz Basilio Mendes, "
        "Secretário(a), em 06/11/2026, às 16:47, conforme horário oficial.\n"
    )
    cols = _cols(BODY + dois + LEI_FOOTER)
    assert [a["nome"] for a in json.loads(cols["sei_assinantes"])] == [
        "Beatriz Basilio Mendes",
        "Marcos José Rocha dos Santos",
    ]


def test_text_without_footer_is_all_null() -> None:
    assert all(v is None for v in _cols(CLOSING.decode()).values())
    assert all(v is None for v in _cols("").values())
    assert sei.extract_own_sei_footer(None) is None


def test_annotate_row_recomputes_the_columns_of_a_reused_row() -> None:
    row = {"texto": BODY + LEI_FOOTER, "sei_verificador": "00000000"}
    out = textlayer.annotate_row(row)
    assert out["sei_verificador"] == "27366482"
    stale = {"texto": BODY, "sei_verificador": "27366482", "sei_crc": "BEF99C54"}
    assert textlayer.annotate_row(stale)["sei_verificador"] is None


def test_contract_has_the_new_nullable_columns() -> None:
    for col in SEI_COLS:
        assert textlayer.TEXTOS_SCHEMA[col] == "VARCHAR"


def test_built_rows_carry_the_columns_and_validate(tmp_path: Path) -> None:
    rows, _ = _build(_default_ia())
    assert all(r[c] is None for r in rows for c in SEI_COLS)
    rows[0] = textlayer.annotate_row({**rows[0], "texto": BODY + LEI_FOOTER})
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    assert textlayer.validate_textos_parquet(out) == []
    back = textlayer.read_textos_parquet(out)
    filled = [r for r in back.values() if r["sei_verificador"]]
    assert [r["sei_crc"] for r in filled] == ["BEF99C54"]


@pytest.mark.parametrize(
    "bad",
    [
        {"sei_crc": None},  # verificador sem CRC
        {"sei_crc": "bef99c54"},  # minúsculas
        {"sei_verificador": "12ab"},
        {"sei_numero": "99999999"},  # diferente do verificador
        {"sei_processo": "123"},
        {"sei_assinantes": "not json"},
        {"sei_assinantes": json.dumps([{"nome": "x"}])},
    ],
)
def test_validator_rejects_broken_sei_columns(
    tmp_path: Path, bad: dict[str, Any]
) -> None:
    rows, _ = _build(_default_ia())
    ok = textlayer.annotate_row({**rows[0], "texto": BODY + LEI_FOOTER})
    rows[0] = {**ok, **bad}
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    assert textlayer.validate_textos_parquet(out) != []


def test_columns_without_a_verifier_must_all_be_null(tmp_path: Path) -> None:
    rows, _ = _build(_default_ia())
    rows[0] = {**rows[0], "sei_processo": "0035.067835/2022-66"}
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    assert any("sei_" in p for p in textlayer.validate_textos_parquet(out))
