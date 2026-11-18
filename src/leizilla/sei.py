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
from typing import Optional, TypedDict

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
