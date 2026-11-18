"""Testes de leizilla.sei — rodapés reais do SEI (RO), sem rede."""

from leizilla.sei import extract_sei_ids, has_sei_footer

OCR_DECRETO = """
Decreto N° 32.145
A autenticidade deste documento pode ser conferida no site portal do SEI, informando o código

verificador 77892409 e o código CRC CF91BBA1.

SEI n° 77892409

Referência: Caso responda esta Decreto, indicar expressamente o Processo n° 0035.003268/2026-43
"""

OCR_LC_COM_ZERO = (
    "A autenticidade deste documento pode ser conferida no site portal do SEl, "
    "informando o código\n\nverificador 6864395 e 0 código CRC 2C8A6E82.\n\n"
    "Referência: Caso responda esta Lei Complementar, indicar expressamente o "
    "Processo nº 0005.290562/2019-11\n\nSEl nº 6864395\n"
)

PDF_EMBUTIDO = (
    "Documento assinado eletronicamente por Beatriz Basilio Mendes, Secretário(a), "
    "em 16/03/2022, às\n15:51, conforme horário oficial de Brasília.\n\n"
    "Documento assinado eletronicamente por Marcos José Rocha dos Santos, "
    "Governador, em\n16/03/2022, às 16:08, conforme horário oficial.\n\n"
    "A autenticidade deste documento pode ser conferida no site portal do SEI, "
    "informando o código\nveriﬁcador 27366482 e o código CRC BEF99C54.\n\n"
    "Referência: Caso responda esta Decreto, indicar expressamente o Processo nº "
    "0035.067835/2022-66  SEI nº 27366482\n"
    "https://sei.sistemas.ro.gov.br/sei/controlador.php?"
    "acao=documento_imprimir_web&acao_origem=arvore_visualizar&"
    "id_documento=10744128&in…\n"
)


def test_ocr_footer():
    ids = extract_sei_ids(OCR_DECRETO)
    assert ids["verificador"] == "77892409"
    assert ids["crc"] == "CF91BBA1"
    assert ids["numero_sei"] == "77892409"
    assert ids["processo"] == "0035.003268/2026-43"
    assert ids["assinantes"] == []
    assert has_sei_footer(ids)


def test_ocr_zero_for_o_and_sel():
    ids = extract_sei_ids(OCR_LC_COM_ZERO)
    assert (ids["verificador"], ids["crc"]) == ("6864395", "2C8A6E82")
    assert ids["numero_sei"] == "6864395"
    assert ids["processo"] == "0005.290562/2019-11"


def test_embedded_pdf_text_with_ligature_signers_and_id_documento():
    ids = extract_sei_ids(PDF_EMBUTIDO)
    assert (ids["verificador"], ids["crc"]) == ("27366482", "BEF99C54")
    assert ids["id_documento"] == "10744128"
    assert ids["assinantes"] == [
        {
            "nome": "Beatriz Basilio Mendes",
            "cargo": "Secretário(a)",
            "data": "2022-03-16",
            "hora": "15:51",
        },
        {
            "nome": "Marcos José Rocha dos Santos",
            "cargo": "Governador",
            "data": "2022-03-16",
            "hora": "16:08",
        },
    ]


def test_crc_lowercase_is_uppercased():
    ids = extract_sei_ids("código verificador 1234567 e o código CRC 2c8a6e82.")
    assert ids["crc"] == "2C8A6E82"


def test_verifier_without_crc_is_not_a_footer():
    ids = extract_sei_ids("informando o código verificador 1234567 e o código CRC ??")
    assert ids["verificador"] == "1234567"
    assert ids["crc"] is None
    assert not has_sei_footer(ids)


def test_no_sei_text():
    for text in (None, "", "Art. 1º Fica criada a gratificação."):
        ids = extract_sei_ids(text)
        assert ids["verificador"] is None and ids["processo"] is None
        assert ids["assinantes"] == []
        assert not has_sei_footer(ids)


def test_first_pair_wins():
    texto = (
        "código verificador 1111111 e o código CRC AAAAAAAA. "
        "código verificador 2222222 e o código CRC BBBBBBBB."
    )
    assert extract_sei_ids(texto)["verificador"] == "1111111"
