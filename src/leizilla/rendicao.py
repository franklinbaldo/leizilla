"""Rendição de um arquivo da lista anual oficial, pelo nome (ADR-0010/0011).

Uma norma do Consulegis (Casa Civil/RO) pode listar mais de um arquivo: o texto
original (``L6572.pdf``) e/ou versões derivadas ("L6500 - COMPILADA.pdf",
"D31884 - REVOGADO.pdf", "DEC31990 - RETIFICADO.pdf"). A identidade da norma é
``(tipo, número)``; a rendição é **metadado** (coluna ``rendicao`` do
``index.csv``), nunca caminho nem fronteira de range.

Módulo-folha (sem dependências do pacote): o ``storage`` o usa para priorizar a
fila de colheita e o ``discovery`` para classificar a lista anual, sem importação
circular.
"""

import re
import urllib.parse

RENDICAO_ORIGINAL = "original"
RENDICAO_COMPILADA = "compilada"
RENDICAO_REVOGADO = "revogado"
RENDICAO_RETIFICADO = "retificado"
RENDICAO_OUTRA = "outra"

#: Prefixo de identidade do nome do arquivo: ``L6572``, ``DEC31990``, ``LC68``,
#: ``DL9A`` e também o número puro (``15597.pdf``), que a lista oficial usa em
#: poucas entradas e é o texto original.
_FILE_STEM_IDENTITY = re.compile(r"^[A-Za-z]*\s*\d[\d.]*[A-Za-z]?(?![A-Za-z])")
#: Resíduo de ferramenta de PDF no nome, sem valor semântico: ``L1865_compressed``
#: é o ``L1865.pdf`` recomprimido (257 arquivos "outra" no catálogo de 2026-11-18).
_TOOL_NOISE = re.compile(r"\b(?:COMPRESSED|MERGED|OPTIMIZED|OTIMIZADO)\b")
_RENDICOES_DECLARADAS = frozenset(
    {RENDICAO_COMPILADA, RENDICAO_REVOGADO, RENDICAO_RETIFICADO}
)
_COMPILADA = re.compile(r"COMPIL|CONSOLID|\bCOMP\b")


def year_index_rendicao(filename: str) -> str:
    """Rendição de um arquivo da lista anual, pelo sufixo do nome.

    ``L6572.pdf`` / ``L1865_compressed.pdf`` → ``original``; ``L6500 -
    COMPILADA.pdf`` / ``DEC15816 - COMP.pdf`` / ``DL9A - COMPILADO_merged.pdf`` →
    ``compilada``; ``… - REVOGADO|REVOGADA`` → ``revogado``; ``… - RETIFICADO`` →
    ``retificado``. Qualquer outro sufixo não vazio ("SEM EFEITO", "ADI",
    "REPUB") → ``outra``: o arquivo é listado, só não classificado.
    """
    stem = urllib.parse.unquote(filename).rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    rest = _FILE_STEM_IDENTITY.sub("", stem.strip(), count=1)
    rest = re.sub(r"[\s_\-]+", " ", rest).strip().upper()
    rest = _TOOL_NOISE.sub(" ", rest).strip()
    if not rest:
        return RENDICAO_ORIGINAL
    if _COMPILADA.search(rest):
        return RENDICAO_COMPILADA
    if "REVOG" in rest:
        return RENDICAO_REVOGADO
    if "RETIF" in rest:
        return RENDICAO_RETIFICADO
    return RENDICAO_OUTRA


def rendicao_da_url(url: str) -> str:
    """Rendição pelo nome do arquivo de uma URL de colheita; ``""`` se não se aplica.

    Nomes no padrão de identidade da lista oficial (``L6500 - COMPILADA.pdf``) são
    classificados por inteiro. Fora do padrão (``ESTRUTURA-LC224-Compilada.pdf``,
    ``coddoc`` da ALRO, Planalto, ``.html``) só uma palavra inequívoca
    (compilada/revogado/retificado) conta; o resto devolve ``""`` — "sem rendição
    declarada", tratado como original. O resultado é o que a colheita grava na
    coluna ``rendicao`` do ``index.csv`` e usa para ordenar a fila.
    """
    name = urllib.parse.unquote(url.split("?", 1)[0]).rsplit("/", 1)[-1].strip()
    if "." not in name:
        return ""
    rendicao = year_index_rendicao(name)
    if _FILE_STEM_IDENTITY.match(name) or rendicao in _RENDICOES_DECLARADAS:
        return rendicao
    return ""


def rendicao_para_fila(url: str) -> str:
    """Rendição de um recurso para ordenar a fila: ``original`` quando indefinida."""
    return rendicao_da_url(url) or RENDICAO_ORIGINAL
