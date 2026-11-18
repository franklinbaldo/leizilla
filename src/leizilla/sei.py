"""Identificadores do SEI lidos do texto de uma norma — só regras, sem rede.

As leis e decretos de Rondônia assinados a partir de ~2018 nascem como documentos do
SEI (Sistema Eletrônico de Informações). O PDF que a Casa Civil publica é a impressão
desse documento e traz, no rodapé, a autenticidade e as assinaturas::

    Documento assinado eletronicamente por NOME, Cargo, em 16/03/2022, às 15:51, ...
    A autenticidade deste documento pode ser conferida no site portal do SEI,
    informando o código verificador 27366482 e o código CRC BEF99C54.
    Referência: Caso responda esta Lei, indicar expressamente o Processo nº
    0035.067835/2022-66        SEI nº 27366482

``extract_sei_ids`` devolve esses campos como proveniência (RFC-0008). Nada aqui acessa
o SEI: é leitura do texto que já preservamos. Precisão antes de cobertura: campo que
não casa com o formato volta ``None``; nada é "corrigido" de OCR.
"""

from __future__ import annotations

import re
import unicodedata
import json
from typing import Any, Mapping, Optional, TypedDict

# OCR troca "I" por "l"/"1" em "SEI" e o "o" de "o código" por "0".
_VERIFICADOR_CRC = re.compile(
    r"c[óo]digo\s+verificador\s*(?:n[º°o.]*\s*)?(\d{6,10})"
    r"(?:\s*,?\s*e\s+(?:o\s+|0\s+)?c[óo]digo\s+CRC\s*(?:n[º°o.]*\s*)?"
    r"([0-9A-Fa-f]{8})\b)?",
    re.IGNORECASE,
)
_CRC_SOLTO = re.compile(r"c[óo]digo\s+CRC\s*(?:n[º°o.]*\s*)?([0-9A-Fa-f]{8})\b", re.I)
_NUMERO_SEI = re.compile(r"\bSE[IlL1]\s*n[º°o.]*\s*(\d{6,10})\b")
_PROCESSO = re.compile(r"\b(\d{4}\.\d{6}/\d{4}-\d{2})\b")
_ASSINATURA = re.compile(
    r"Documento\s+assinado\s+eletronicamente\s+por\s+(.+?),\s+(.+?),\s+em\s+"
    r"(\d{2})/(\d{2})/(\d{4}),\s+[àa]s\s+(\d{2}:\d{2})",
    re.IGNORECASE,
)


# Cabeçalho/rodapé de impressão do navegador (PDFs com texto embutido).
_ID_DOCUMENTO = re.compile(r"acao=documento_imprimir_web[^ ]*?[&?]id_documento=(\d+)")


class Assinante(TypedDict):
    nome: str
    cargo: str
    data: str  # AAAA-MM-DD
    hora: str  # HH:MM


class SeiIds(TypedDict):
    verificador: Optional[str]
    crc: Optional[str]
    numero_sei: Optional[str]
    processo: Optional[str]
    id_documento: Optional[str]
    assinantes: list[Assinante]


def extract_sei_ids(text: Optional[str]) -> SeiIds:
    """Lê verificador, CRC, ``SEI nº``, nº do processo, ``id_documento`` (só no
    cabeçalho de impressão dos PDFs com texto embutido) e assinantes do texto.

    Quando o texto traz mais de um bloco de autenticidade (um ofício impresso dentro do
    PDF, por exemplo), vale o primeiro par verificador+CRC. O CRC volta em maiúsculas.
    """
    out: SeiIds = {
        "verificador": None,
        "crc": None,
        "numero_sei": None,
        "processo": None,
        "id_documento": None,
        "assinantes": [],
    }
    if not text:
        return out
    # NFKC desfaz ligaturas do PDF ("veriﬁcador" → "verificador"); espaços coalescem.
    flat = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))

    pares = list(_VERIFICADOR_CRC.finditer(flat))
    par = next((m for m in pares if m.group(2)), pares[0] if pares else None)
    if par:
        out["verificador"] = par.group(1)
        crc = par.group(2)
        if not crc:
            solto = _CRC_SOLTO.search(flat, par.end())
            crc = solto.group(1) if solto else None
        out["crc"] = crc.upper() if crc else None

    m = _NUMERO_SEI.search(flat)
    if m:
        out["numero_sei"] = m.group(1)
    m = _PROCESSO.search(flat)
    if m:
        out["processo"] = m.group(1)

    m = _ID_DOCUMENTO.search(flat)
    if m:
        out["id_documento"] = m.group(1)

    for a in _ASSINATURA.finditer(flat):
        nome, cargo, dd, mm, aaaa, hora = a.groups()
        if len(nome) > 80 or len(cargo) > 80:
            continue
        out["assinantes"].append(
            {"nome": nome, "cargo": cargo, "data": f"{aaaa}-{mm}-{dd}", "hora": hora}
        )
    return out


def has_sei_footer(ids: SeiIds) -> bool:
    """Verdadeiro quando há verificador e CRC — o que identifica o documento no SEI."""
    return bool(ids["verificador"] and ids["crc"])


# ---------------------------------------------------------------------------
# Rodapé **próprio** da norma (proveniência na camada de texto, ADR-0015)
# ---------------------------------------------------------------------------
#
# ``extract_sei_ids`` vale o primeiro par verificador+CRC do texto, e um PDF pode trazer
# um documento SEI impresso *dentro* dele (um ofício do TJ citado numa lei de 2017, um
# requerimento numa lei complementar). Para a camada de texto só vale o rodapé da própria
# norma, e o que o distingue é a frase que o SEI imprime logo depois do código CRC:
# "Referência: Caso responda esta Lei/Decreto/Lei Complementar, indicar expressamente o
# Processo nº ...". Um ofício traz "esta Ofício", um requerimento "este(a) Requerimento".
_ATO = r"(?:lei\s+complementar|lei|decreto(?:\s*-\s*lei|\s+legislativo)?|emenda\s+constitucional)"
# OCR junta ou parte palavras ("estaLei", "nda esta Lei Complementar"): só a parte final conta.
_CAUSA_PROPRIA = re.compile(
    r"est[ae]\s*(?:\(a\)\s*)?" + _ATO + r"\s*,?\s*indicar\s+expressamente",
    re.IGNORECASE,
)
_JANELA_APOS_CRC = 400
_JANELA_ASSINATURAS = 2500
_MENCAO_ASSINATURA = re.compile(r"assinado\s+eletronicamente", re.IGNORECASE)
_FICHA_RUIM = re.compile(r"[0-9!]|\bsei\b", re.IGNORECASE)


class SeiProprio(TypedDict):
    verificador: str
    crc: str
    numero_sei: Optional[str]
    processo: Optional[str]
    assinantes: Optional[list[Assinante]]


def _nome_legivel(nome: str) -> bool:
    """Falso quando o OCR deixou uma letra solta em caixa trocada ("AFONsO", "FRANKLiN")."""
    for token in nome.split():
        if not (token.isupper() or token.islower() or token == token.capitalize()):
            return False
    return True


def _assinantes_confiaveis(segmento: str) -> Optional[list[Assinante]]:
    """Os assinantes do trecho, ou ``None`` se não dá para garantir a lista inteira.

    Precisão antes de cobertura: vale só se há tantas assinaturas lidas quantas menções a
    "assinado eletronicamente" e se cada uma tem nome legível e cargo curto sem ruído
    do SEI (o regex corta o cargo na data; quando o OCR quebra a data, o cargo engole
    a assinatura vizinha, e essa lista inteira é descartada).
    """
    mencoes = len(_MENCAO_ASSINATURA.findall(segmento))
    lidos: list[Assinante] = []
    for achado in _ASSINATURA.finditer(segmento):
        nome, cargo, dd, mm, aaaa, hora = achado.groups()
        lidos.append(
            {
                "nome": nome.strip(),
                "cargo": cargo.strip(),
                "data": f"{aaaa}-{mm}-{dd}",
                "hora": hora,
            }
        )
    if not lidos or len(lidos) != mencoes:
        return None
    for lido in lidos:
        if (
            len(lido["nome"]) > 60
            or len(lido["cargo"]) > 60
            or _FICHA_RUIM.search(lido["nome"])
            or _FICHA_RUIM.search(lido["cargo"])
            or not _nome_legivel(lido["nome"])
        ):
            return None
    return lidos


def extract_own_sei_footer(text: Optional[str]) -> Optional[SeiProprio]:
    """O rodapé do SEI **da própria norma**, ou ``None`` (o caso comum antes de 2018).

    Só vale um par verificador+CRC seguido, em até 400 caracteres, da frase "Caso
    responda esta Lei/Decreto/Lei Complementar, indicar expressamente o Processo"; um
    documento SEI impresso dentro do PDF (ofício, despacho, requerimento) não passa nessa
    guarda. Havendo mais de um, vale o último (o rodapé de uma norma fica no fim do
    arquivo). ``numero_sei`` e ``processo`` vêm só da janela depois desse par, e um ``SEI nº`` que
    difere do verificador descarta o rodapé inteiro (OCR errou um dos dois);
    ``assinantes`` só se a lista é íntegra (``_assinantes_confiaveis``).
    """
    if not text:
        return None
    flat = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))
    proprios: list[tuple[re.Match[str], int]] = []
    anterior_fim = 0
    for par in _VERIFICADOR_CRC.finditer(flat):
        if par.group(2) and _CAUSA_PROPRIA.search(
            flat, par.end(), par.end() + _JANELA_APOS_CRC
        ):
            proprios.append((par, anterior_fim))
        anterior_fim = par.end()
    if not proprios:
        return None
    par, limite = proprios[-1]
    janela = flat[par.end() : par.end() + _JANELA_APOS_CRC + 300]
    numero = _NUMERO_SEI.search(janela)
    processo = _PROCESSO.search(janela)
    if numero and numero.group(1) != par.group(1):
        # "SEI nº" é o mesmo número do código verificador: se divergem, o OCR errou um dos
        # dois e não há como saber qual. Sem verificador de confiança, a linha fica sem nada.
        return None
    inicio = max(limite, par.start() - _JANELA_ASSINATURAS)
    return {
        "verificador": par.group(1),
        "crc": par.group(2).upper(),
        "numero_sei": numero.group(1) if numero else None,
        "processo": processo.group(1) if processo else None,
        "assinantes": _assinantes_confiaveis(flat[inicio : par.start()]),
    }


def sei_columns(text: Optional[str]) -> dict[str, Optional[str]]:
    """As colunas ``sei_*`` de ``textos`` (ADR-0015, adendo 2026-11-18); tudo NULL sem rodapé."""
    footer = extract_own_sei_footer(text)
    if footer is None:
        return {
            "sei_verificador": None,
            "sei_crc": None,
            "sei_numero": None,
            "sei_processo": None,
            "sei_assinantes": None,
        }
    assinantes = footer["assinantes"]
    return {
        "sei_verificador": footer["verificador"],
        "sei_crc": footer["crc"],
        "sei_numero": footer["numero_sei"],
        "sei_processo": footer["processo"],
        "sei_assinantes": (
            None
            if assinantes is None
            else json.dumps(assinantes, ensure_ascii=False, separators=(",", ":"))
        ),
    }


def valida_assinantes_json(texto: Optional[str]) -> bool:
    """``sei_assinantes`` é um JSON ``[{"nome","cargo","data","hora"}, ...]`` não vazio."""
    try:
        value: Any = json.loads(texto or "")
    except json.JSONDecodeError:
        return False
    if not isinstance(value, list) or not value:
        return False
    chaves = {"nome", "cargo", "data", "hora"}
    return all(
        isinstance(a, Mapping)
        and set(a) == chaves
        and all(isinstance(a[k], str) and a[k] for k in chaves)
        for a in value
    )
