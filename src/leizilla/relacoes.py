"""Relações entre normas lidas das ementas do índice oficial — só regras, sem modelo.

As ementas das normas que alteram outras são formulaicas ("Altera a Lei nº 1.234, de
5 de maio de 2003", "Revoga o Decreto nº 5.678", "Dá nova redação ao art. 3º da Lei
Complementar nº 68…"). Este módulo extrai delas, por gramática de expressões regulares,
as relações ``origem —verbo→ alvo`` (ADR-0017) e tenta resolver cada alvo contra o
catálogo oficial. Nada aqui lê o corpo da norma nem consulta um modelo.

Princípios:

- **Precisão antes de cobertura.** Na dúvida, não se emite relação resolvida. Uma
  referência que não pôde ser ligada a uma norma do catálogo é emitida como
  ``nao-resolvida`` com uma nota do motivo (federal, constituição, tipo sem índice,
  ausente do índice, data diverge…), nunca descartada em silêncio quando o verbo e a
  referência foram lidos com segurança.
- **O verbo só vale no início da oração principal.** Tudo que vem depois de "que",
  de um particípio passivo ("alterada pela…", "aprovado pelo…"), de "conforme",
  "para" etc. descreve o alvo, não é alvo: o escopo do verbo termina ali.
- **Intervalos de artigos não são números de norma.** Só se lê número depois de uma
  palavra de tipo ("Lei", "Decreto", "LC"…): "arts. 3º e 4º da Lei nº 100" gera uma
  referência, ``Lei nº 100``.
- **Citação não é ação.** Texto entre aspas é ignorado, e "autoriza… nos termos da
  Lei nº X" ou "de que trata a Lei nº X" não geram relação (ver ADR-0017).

Também é lida a anotação editorial do índice no fim de algumas ementas ("REVOGADO
PELO DECRETO N° 25.210, DE 9/7/2020"): vira uma relação ``revoga`` cuja origem é a
norma que revogou, só quando essa norma é resolvida no catálogo.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

RELACOES_VERSION = "0.1"
RELACOES_FILENAME = "relacoes.parquet"

# Verbo canônico — o conjunto fechado do contrato (docs/SCHEMA.md §3.7).
VERBO_ALTERA = "altera"
VERBO_REVOGA = "revoga"
VERBO_ACRESCENTA = "acrescenta"
VERBO_NOVA_REDACAO = "da-nova-redacao"
VERBO_REGULAMENTA = "regulamenta"
VERBO_PRORROGA = "prorroga"
VERBO_OUTRO = "outro"
VERBOS = (
    VERBO_ALTERA,
    VERBO_REVOGA,
    VERBO_ACRESCENTA,
    VERBO_NOVA_REDACAO,
    VERBO_REGULAMENTA,
    VERBO_PRORROGA,
    VERBO_OUTRO,
)

CONFIANCA_RESOLVIDA = "resolvida"
CONFIANCA_NAO_RESOLVIDA = "nao-resolvida"
CONFIANCA_AMBIGUA = "ambigua"
CONFIANCAS = (CONFIANCA_RESOLVIDA, CONFIANCA_NAO_RESOLVIDA, CONFIANCA_AMBIGUA)

FONTE_EMENTA = "ementa"
FONTE_ANOTACAO = "anotacao-do-indice"

# Categoria do alvo — decide se ele pode ser procurado entre as normas do catálogo.
CAT_ESTADUAL = "estadual-ou-nao-qualificada"
CAT_FEDERAL = "federal"
CAT_MUNICIPAL = "municipal"
CAT_CONSTITUICAO = "constituicao"
CAT_OUTRO_TIPO = "outro-tipo"

# Tipos que o índice oficial enumera (as chaves do catálogo).
TIPOS_INDEXADOS = frozenset({"lei", "lc", "decreto", "decreto-lei"})

# Ordem e tipos das colunas do Parquet de relações (docs/SCHEMA.md §3.7).
RELACOES_SCHEMA: dict[str, str] = {
    "relacao_id": "VARCHAR",
    "origem_id": "VARCHAR",
    "verbo": "VARCHAR",
    "verbo_texto": "VARCHAR",
    "parcial": "BOOLEAN",
    "alvo_tipo": "VARCHAR",
    "alvo_categoria": "VARCHAR",
    "alvo_numero": "INTEGER",
    "alvo_sufixo": "VARCHAR",
    "alvo_data": "VARCHAR",
    "alvo_ano": "INTEGER",
    "alvo_texto": "VARCHAR",
    "alvo_id": "VARCHAR",
    "confianca": "VARCHAR",
    "nota": "VARCHAR",
    "trecho": "VARCHAR",
    "fonte_relacao": "VARCHAR",
}


# ---------------------------------------------------------------------------
# Texto: dobra sem perder posições
# ---------------------------------------------------------------------------


def fold(text: str) -> str:
    """Minúsculas, sem acento e com ordinais ``º``/``°`` → ``o`` — **mesmo tamanho**.

    Cada caractere vira exatamente um caractere, então os deslocamentos de uma
    busca no texto dobrado valem no original (o trecho citado sai do original).
    """
    out: list[str] = []
    for ch in text:
        if ch in "º°":
            out.append("o")
            continue
        base = unicodedata.normalize("NFD", ch)[0]
        low = base.lower()
        out.append(low if len(low) == 1 else base)
    return "".join(out)


def _mask_quotes(text: str) -> str:
    """Troca por espaços o que está entre aspas (mesmo tamanho): a citação de um
    texto alheio não é ação da norma. Aspas não fechadas mascaram até o fim."""
    out = list(text)
    i = 0
    opening = {"“": "”", '"': '"', "«": "»"}
    # Ementa inteira entre aspas ("“Altera e revoga dispositivos da Lei nº 547…”"): a
    # aspa de abertura não delimita citação alguma, só embrulha a ementa.
    if text[:1] in opening:
        out[0] = " "
        i = 1
    while i < len(text):
        ch = text[i]
        if ch in opening:
            close = opening[ch]
            j = text.find(close, i + 1)
            end = len(text) if j == -1 else j + 1
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Gramática das referências a normas
# ---------------------------------------------------------------------------

_MESES = (
    "janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|"
    "novembro|dezembro"
)
_MES_NUM = {
    m: i + 1
    for i, m in enumerate(
        [
            "janeiro",
            "fevereiro",
            "marco",
            "abril",
            "maio",
            "junho",
            "julho",
            "agosto",
            "setembro",
            "outubro",
            "novembro",
            "dezembro",
        ]
    )
}

# Ano com ponto de milhar opcional ("1.985") ou de dois dígitos.
_ANO4 = r"\d\.?\d{3}"
_DATA_EXTENSO = rf"(?P<d_dia>\d{{1,2}})\s*o?\s+(?:de\s+)?(?P<d_mes>{_MESES})\s+(?:de\s+)?(?P<d_ano>{_ANO4})"
_DIA_MES = rf"\d{{1,2}}\s*o?\s+(?:de\s+)?(?:{_MESES})\b"
_DATA_NUMERICA = (
    r"(?P<n_dia>\d{1,2})[/.\-](?P<n_mes>\d{1,2})[/.\-](?P<n_ano>\d{4}|\d{2})\b"
)
_DATA_MES_ANO = rf"(?P<m_mes>{_MESES})\s+de\s+(?P<m_ano>{_ANO4})"
_DATA_ANO = rf"(?P<a_ano>{_ANO4})\b(?![/.\-]\d)"
_DATA = rf"(?:{_DATA_EXTENSO}|{_DATA_NUMERICA}|{_DATA_MES_ANO}|{_DATA_ANO})"

# Número com milhar ("1.234") ou simples; sufixo de uma letra colada ("9A"); ano
# abreviado "/92" ou "/1992".
_NUM = r"(?P<num>\d{1,3}(?:\.\d{3})+|\d+)"
_SUF = r"(?P<suf>[a-np-z](?![a-z0-9]))?"
_BARRA_ANO = r"(?:\s*/\s*(?P<barra>\d{4}|\d{2})(?!\d))?"
_DE_DATA = rf"(?:\s*(?:,\s*(?={_DIA_MES})|,?\s*(?:de|do dia)\s+){_DATA})?"

# Palavra de tipo. A ordem das alternativas importa (a mais longa primeiro).
_QUALIF = r"(?:\s+(?:estadua(?:l|is)|federa(?:l|is)|municipa(?:l|is)))?"
_TIPO = (
    r"\b(?P<tipo>"
    rf"leis?\s+complementar(?:es)?{_QUALIF}"
    rf"|leis?\s+ordinari[ao]s?{_QUALIF}"
    r"|leis?\s+delegadas?"
    r"|decretos?\s*-?\s*leis?"
    r"|decretos?\s+legislativos?"
    rf"|decretos?{_QUALIF}"
    rf"|leis?{_QUALIF}"
    r"|emendas?\s+constituciona(?:l|is)(?:\s+(?:estadua(?:l|is)|federa(?:l|is)))?"
    r"|medidas?\s+provisorias?"
    r"|resolu(?:cao|coes)"
    r"|portarias?"
    r"|lc(?=\s*\d)"
    r")(?![a-z])"
)
# "nº", "n.", "n.º", "nºs", "nos" (já dobrados: º → o).
_MARCA = r"(?:n(?:\s*\.)?\s*(?:os?|s)?\s*\.?\s*)?"

_REF_CABECA = re.compile(rf"{_TIPO}\s*{_MARCA}(?=\d)")
_ITEM = re.compile(rf"{_NUM}{_SUF}{_BARRA_ANO}{_DE_DATA}")
# "…, de 21 de julho de 1986, e n° 315": a marca pode repetir em cada item da lista.
_MARCA_ITEM = re.compile(r"n(?:\s*\.)?\s*(?:os?|s)?\s*\.?\s*(?=\d)")
# Depois do item sobrou um "de …" que a gramática de datas não leu: data ilegível.
_DATA_SOBRA = re.compile(r"\s*,?\s*(?:de|do dia)\s+\d")
# Separador de lista: vírgula, "e", "ou", "," + "e".
_SEPARADOR = re.compile(r"\s*(?:,\s*(?:e|ou)\s+|,\s*|;\s*|\s+e\s+|\s+ou\s+)")
_QUALIF_POS = re.compile(
    r"\s*,?\s*\(?(?P<q>federal|estadual|municipal)\)?\b|\s+(?P<q2>da\s+uniao|do\s+municipio)\b"
)

_CONSTITUICAO = re.compile(
    r"\bconstituicao(?:\s+(?P<cq>estadual|federal|da\s+republica(?:\s+federativa\s+do\s+brasil)?"
    r"|do\s+estado(?:\s+de\s+rondonia)?))?"
)

# Anotação editorial do índice: "REVOGADO PELO DECRETO N° 25.210, DE 9/7/2020".
_ANOTACAO = re.compile(
    r"\b(?P<acao>revogad[oa]s?|tornad[oa]s?\s+sem\s+efeito)\s+(?:parcialmente\s+)?"
    r"(?:pel[oa]s?|por)\s+(?=(?:lei|decreto|lc)\b)"
)

# Verbos (sobre o texto dobrado). A ordem dá prioridade a "dá nova redação" e
# "altera a redação" sobre o "altera" simples.
_VERBOS: list[tuple[str, re.Pattern[str]]] = [
    (
        VERBO_NOVA_REDACAO,
        re.compile(
            r"\b(?:da\s+(?:a\s+)?nova\s+redacao|dando\s+nova\s+redacao"
            r"|confere\s+nova\s+redacao|altera\s+(?:a\s+)?redacao"
            r"|modifica\s+(?:a\s+)?redacao)\b"
        ),
    ),
    (
        VERBO_ALTERA,
        re.compile(
            r"\b(?:alteram?|alterando|modifica(?:m)?|modificando"
            r"|(?:introduz|introduzem|promove|promovem|efetua|efetuam)\s+alteracoes"
            r"|fica(?:m)?\s+alterad[oa]s?)\b"
        ),
    ),
    (
        VERBO_REVOGA,
        re.compile(r"\b(?:revoga(?:m)?|revogando|fica(?:m)?\s+revogad[oa]s?)\b"),
    ),
    (
        VERBO_ACRESCENTA,
        re.compile(
            r"\b(?:acrescenta(?:m)?|acrescentando|acresce(?:m)?|inclui(?:m)?"
            r"|insere|inserem|fica(?:m)?\s+acrescid[oa]s?)\b"
        ),
    ),
    (
        VERBO_REGULAMENTA,
        re.compile(r"\b(?:regulamenta(?:m)?|regulamentando)\b"),
    ),
    (
        VERBO_PRORROGA,
        re.compile(r"\b(?:prorroga(?:m)?|prorrogando|fica(?:m)?\s+prorrogad[oa]s?)\b"),
    ),
    (
        VERBO_OUTRO,
        re.compile(
            r"\b(?:suspende(?:m)?|restabelece(?:m)?|convalida(?:m)?|ratifica(?:m)?"
            r"|retifica(?:m)?|derroga(?:m)?|suprime(?:m)?|interpreta)\b"
        ),
    ),
]
# "Altera" e "acrescenta" são o mesmo grupo quando vêm colados: "Altera e acresce".
# O verbo "altera" simples só vale se não for o início de "altera a redação" (que
# a regra anterior já consumiu); a deduplicação por posição resolve isso.
_ALTERA_SIMPLES = re.compile(r"\balteram?\b|\baltera\b")

# O que encerra o escopo de um verbo: oração relativa, particípio passivo,
# referência de fundamento ou finalidade. O que vem depois descreve o alvo.
# Corta o escopo E invalida verbos que venham depois: oração relativa ou particípio
# passivo ("que dispõe…", "alterada pela…", "aprovado pelo…") descreve o alvo, e um
# verbo ali dentro não é ação da norma.
_CORTE = re.compile(
    r"\b(?:que|aprovad[oa]s?|instituid[oa]s?|criad[oa]s?|regulamentad[oa]s?"
    r"|alterad[oa]s?|modificad[oa]s?|acrescid[oa]s?|prorrogad[oa]s?|revogad[oa]s?"
    r"|previst[oa]s?|tratad[oa]s?|estabelecid[oa]s?|disciplinad[oa]s?|referid[oa]s?"
    r"|mencionad[oa]s?|autorizad[oa]s?|decorrente|dispondo"
    r"|ressalvad[oa]s?|exceto)\b"
)
# Corta só o escopo do verbo corrente: um complemento de finalidade ou fundamento
# ("para…", "nos termos do…"). Um verbo coordenado depois dele ("…, nos termos do
# § 1º, e revoga o Decreto nº 23.311") continua valendo.
_CORTE_ADJUNTO = re.compile(
    r"\b(?:conforme|consoante|segundo|nos\s+termos|de\s+acordo|em\s+conformidade"
    r"|com\s+fundamento|com\s+base|para|visando|a\s+fim|mediante|por\s+forca"
    r"|em\s+razao|em\s+virtude)\b"
)

# "… da Lei nº 5.073, de 22 de julho de 2021 e cria Ação nas Leis nº 5.246": um
# verbo que o léxico de relações não conhece (cria, institui, fixa…) encerra o escopo
# do verbo anterior — o que vem depois dele não é alvo daquele. Lista fechada, medida
# nas ementas do índice (as palavras mais frequentes depois de "e"); "dá" não entra
# porque, sem acento, é indistinguível da preposição "da".
_CORTE_CONJUNCAO = re.compile(
    r"(?:,|;)?\s+(?:e|ou)\s+(?:cria|transfere|estabelece|fixa|aprova|nomeia|renomeia"
    r"|reverte|dispoe|abre|autoriza|institui|torna|extingue|reconduz|cede|designa"
    r"|exclui|agrega|adota|disciplina|dispensa|determina|declara|concede"
    r"|transforma|define|delega|remaneja|mantem|denomina|reorganiza|reestrutura)\b"
)

_PARCIAL = re.compile(
    r"\b(?:arts?|artigos?|paragrafos?|incisos?|alineas?|dispositivos?|anexos?"
    r"|capitulos?|secoes?|tabelas?|expressao|expressoes|itens?|titulos?|livros?)\b|§"
)

_FRASE = re.compile(r"\.\s+(?=[A-ZÀ-Ú“\"(])")


@dataclass
class Referencia:
    """Uma referência a norma lida de uma ementa, como escrita."""

    tipo: str  # canônico (lei, lc, decreto, decreto-lei) ou rótulo do tipo não indexado
    categoria: str
    numero: Optional[int]
    sufixo: str
    data: Optional[str]  # ISO, só quando dia, mês e ano foram escritos
    ano: Optional[int]
    ini: int
    fim: int
    texto: str = ""
    nota: Optional[str] = None  # motivo de nunca ser resolvida (federal, constituição…)
    data_ilegivel: bool = False  # havia um "de …" depois do número que não foi lido


@dataclass
class Relacao:
    """Relação extraída de uma ementa, ainda sem resolução."""

    verbo: str
    verbo_texto: str
    parcial: bool
    ref: Referencia
    trecho: str
    fonte: str = FONTE_EMENTA


@dataclass
class NormaCatalogo:
    """O mínimo do catálogo que a resolução precisa."""

    norma_id: str
    tipo: str
    numero: int
    sufixo: str
    data: Optional[str]
    ano: Optional[int]
    identidade_incerta: bool = False


@dataclass
class Indice:
    """Catálogo indexado por ``(tipo, numero)`` para resolver alvos."""

    por_chave: dict[tuple[str, int], list[NormaCatalogo]] = field(default_factory=dict)

    @classmethod
    def de_linhas(cls, rows: Iterable[dict[str, Any]]) -> "Indice":
        idx = cls()
        for r in rows:
            if r.get("situacao") != "listada":
                continue
            n = NormaCatalogo(
                norma_id=str(r["norma_id"]),
                tipo=str(r["tipo"]),
                numero=int(r["numero"]),
                sufixo=str(r.get("sufixo") or ""),
                data=r.get("data"),
                ano=int(r["ano"]) if r.get("ano") is not None else None,
                identidade_incerta=bool(r.get("identidade_incerta")),
            )
            idx.por_chave.setdefault((n.tipo, n.numero), []).append(n)
        return idx


# ---------------------------------------------------------------------------
# Leitura das referências
# ---------------------------------------------------------------------------


def _ano_de(raw: str) -> int:
    digits = raw.replace(".", "")
    year = int(digits)
    if len(digits) == 2:
        return 2000 + year if year <= 30 else 1900 + year
    return year


def _data_do_match(
    m: re.Match[str], ano_barra: Optional[str] = None
) -> tuple[Optional[str], Optional[int]]:
    """``(data ISO | None, ano | None)`` a partir dos grupos de ``_DATA``/``_BARRA_ANO``."""
    g = m.groupdict()
    try:
        if g.get("d_dia"):
            mes = _MES_NUM[g["d_mes"]]
            ano = _ano_de(g["d_ano"])
            return _iso(ano, mes, int(g["d_dia"])), ano
        if g.get("n_dia"):
            ano = _ano_de(g["n_ano"])
            return _iso(ano, int(g["n_mes"]), int(g["n_dia"])), ano
        if g.get("m_mes"):
            return None, _ano_de(g["m_ano"])
        if g.get("a_ano"):
            return None, _ano_de(g["a_ano"])
    except (KeyError, ValueError):
        return None, None
    if ano_barra:
        return None, _ano_de(ano_barra)
    return None, None


def _iso(ano: int, mes: int, dia: int) -> Optional[str]:
    import datetime

    try:
        return datetime.date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _classificar_tipo(raw: str) -> tuple[str, str]:
    """``(tipo, categoria)`` da palavra de tipo (já dobrada)."""
    palavras = re.sub(r"[\s-]+", " ", raw.strip())
    if "federa" in palavras:
        categoria = CAT_FEDERAL
    elif "municipa" in palavras:
        categoria = CAT_MUNICIPAL
    else:
        categoria = CAT_ESTADUAL
    if palavras == "lc" or "complementar" in palavras:
        tipo = "lc"
    elif palavras.startswith("decreto") and "lei" in palavras:
        tipo = "decreto-lei"
    elif "legislativ" in palavras:
        return "decreto-legislativo", CAT_OUTRO_TIPO
    elif palavras.startswith("decreto"):
        tipo = "decreto"
    elif "delegada" in palavras:
        return "lei-delegada", CAT_OUTRO_TIPO
    elif palavras.startswith("lei"):
        tipo = "lei"
    elif palavras.startswith("emenda"):
        return (
            "emenda-constitucional",
            CAT_OUTRO_TIPO if categoria == CAT_ESTADUAL else categoria,
        )
    elif palavras.startswith("medida"):
        return "medida-provisoria", CAT_OUTRO_TIPO
    elif palavras.startswith("resolu"):
        return "resolucao", CAT_OUTRO_TIPO
    elif palavras.startswith("portaria"):
        return "portaria", CAT_OUTRO_TIPO
    else:
        return palavras, CAT_OUTRO_TIPO
    return tipo, categoria


def ler_referencias(texto: str, folded: Optional[str] = None) -> list[Referencia]:
    """Todas as referências a normas de um trecho, na ordem em que aparecem.

    ``texto`` é o original; as posições valem nele (a busca roda no texto dobrado,
    de mesmo tamanho). Lê listas ("Leis nºs 100, 200 e 300") e datas por extenso,
    numéricas ou só o ano; "LC 68/92" e "Decreto 14053/09" também.
    """
    f = folded if folded is not None else fold(texto)
    refs: list[Referencia] = []
    pos = 0
    while True:
        cab = _REF_CABECA.search(f, pos)
        if cab is None:
            break
        tipo, categoria = _classificar_tipo(cab.group("tipo"))
        ini = cab.start()
        cursor = cab.end()
        first = True
        while True:
            m = _ITEM.match(f, cursor)
            if m is None:
                break
            numero = int(m.group("num").replace(".", ""))
            if (
                not first
                and re.fullmatch(r"(?:19|20)\d\d", m.group("num"))
                and not m.group("suf")
            ):
                # ", 2003" depois de uma lista: provável ano solto, não norma.
                break
            if not first and f[m.end() : m.end() + 1] == "o":
                break  # "3º": ordinal de artigo, não número de norma
            data, ano = _data_do_match(m, m.group("barra"))
            fim = m.end()
            ilegivel = (
                data is None and ano is None and _DATA_SOBRA.match(f, fim) is not None
            )
            categoria_ref = categoria
            q = _QUALIF_POS.match(f, fim)
            if q is not None and categoria == CAT_ESTADUAL:
                word = q.group("q") or q.group("q2") or ""
                if word.startswith(("federal", "da uniao")):
                    categoria_ref = CAT_FEDERAL
                elif word.startswith(("municip", "do municip")):
                    categoria_ref = CAT_MUNICIPAL
                fim = q.end()
            refs.append(
                Referencia(
                    tipo=tipo,
                    categoria=categoria_ref,
                    numero=numero,
                    sufixo=(m.group("suf") or "").upper(),
                    data=data,
                    ano=ano,
                    ini=ini if first else m.start(),
                    fim=fim,
                    texto=texto[(ini if first else m.start()) : fim].strip(),
                    data_ilegivel=ilegivel,
                )
            )
            first = False
            sep = _SEPARADOR.match(f, fim)
            if sep is None:
                cursor = fim
                break
            marca = _MARCA_ITEM.match(f, sep.end())
            inicio_item = marca.end() if marca else sep.end()
            nxt = _ITEM.match(f, inicio_item)
            if nxt is None:
                cursor = fim
                break
            cursor = inicio_item
        pos = max(cursor, cab.end())
    # Constituições: sem número, nunca resolvidas contra normas do catálogo.
    for m in _CONSTITUICAO.finditer(f):
        qual = m.group("cq") or ""
        nota = (
            "constituicao-federal"
            if qual.startswith(("federal", "da republica"))
            else "constituicao-estadual"
            if qual.startswith(("estadual", "do estado"))
            else "constituicao"
        )
        refs.append(
            Referencia(
                tipo="constituicao",
                categoria=CAT_CONSTITUICAO,
                numero=None,
                sufixo="",
                data=None,
                ano=None,
                ini=m.start(),
                fim=m.end(),
                texto=texto[m.start() : m.end()].strip(),
                nota=nota,
            )
        )
    refs.sort(key=lambda r: r.ini)
    return refs


# ---------------------------------------------------------------------------
# Verbos e escopo
# ---------------------------------------------------------------------------


def _frases(texto: str) -> list[tuple[int, int]]:
    """Intervalos ``(ini, fim)`` das orações do texto (corte em ponto + maiúscula)."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _FRASE.finditer(texto):
        spans.append((start, m.start() + 1))
        start = m.end()
    spans.append((start, len(texto)))
    return [(a, b) for a, b in spans if b > a]


def _achar_verbos(f: str, ini: int, fim: int) -> list[tuple[int, int, str]]:
    """Verbos canônicos de ``f[ini:fim]`` como ``(início, fim, canônico)``, sem sobreposição."""
    found: list[tuple[int, int, str]] = []
    for verbo, pattern in _VERBOS:
        for m in pattern.finditer(f, ini, fim):
            found.append((m.start(), m.end(), verbo))
    # "altera" simples, quando não é "altera a redação".
    for m in _ALTERA_SIMPLES.finditer(f, ini, fim):
        found.append((m.start(), m.end(), VERBO_ALTERA))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, v in found:
        if s < last_end:
            continue
        out.append((s, e, v))
        last_end = e
    return out


_LIGACAO_PALAVRAS = frozenset(
    {
        "e", "ou", "o", "os", "a", "as", "art", "arts", "artigo", "artigos",
        "paragrafo", "paragrafos", "inciso", "incisos", "alinea", "alineas",
        "unico", "unica", "seu", "sua", "do", "da", "no", "na", "dos", "das",
        "caput", "dispositivo", "dispositivos", "anexo", "anexos", "ao", "aos",
    }
)  # fmt: skip


def _so_ligacao(gap: str) -> bool:
    """O trecho entre dois verbos só liga (conjunção) ou nomeia dispositivos
    ("altera o art. 6º e acrescenta…"): os dois verbos recaem sobre o mesmo alvo."""
    tokens = re.findall(r"[a-z]+|\d+|§", gap)
    return all(
        t in _LIGACAO_PALAVRAS or t.isdigit() or t == "§" or t == "o" for t in tokens
    )


def extrair_da_ementa(ementa: str) -> list[Relacao]:
    """Relações ``verbo → alvo`` que a ementa declara, sem resolver os alvos."""
    if not ementa or not ementa.strip():
        return []
    texto = re.sub(r"\s+", " ", ementa).strip()
    mascarado = _mask_quotes(texto)
    f = fold(mascarado)
    saida: list[Relacao] = []
    todas = ler_referencias(texto, f)
    for a, b in _frases(mascarado):
        verbos = _achar_verbos(f, a, b)
        if not verbos:
            continue
        # O primeiro "que"/passivo fecha a oração principal: verbos depois dele
        # descrevem o alvo e não valem. Um particípio que faz parte de um verbo
        # ("fica revogado") não é corte.
        limite = b
        for corte in _CORTE.finditer(f, verbos[0][1], b):
            if any(vs <= corte.start() < ve for vs, ve, _ in verbos):
                continue
            if verbos[0][2] == VERBO_PRORROGA and re.match(
                r"(?:estabelecid|fixad|previst)", f[corte.start() : corte.end()]
            ):
                continue  # "prorroga prazo estabelecido no Decreto nº X": X é o alvo
            limite = corte.start()
            break
        verbos = [v for v in verbos if v[0] < limite]
        for i, (s, e, verbo) in enumerate(verbos):
            fim_escopo = verbos[i + 1][0] if i + 1 < len(verbos) else limite
            for pattern in (_CORTE_ADJUNTO, _CORTE_CONJUNCAO):
                for soft in pattern.finditer(f, e, fim_escopo):
                    fim_escopo = soft.start()
                    break
            escopo = (e, fim_escopo)
            refs = [r for r in todas if escopo[0] <= r.ini < escopo[1]]
            # "Altera e acresce dispositivos à Lei X": verbos colados partilham o alvo.
            j = i
            while not refs and j + 1 < len(verbos):
                gap = f[verbos[j][1] : verbos[j + 1][0]]
                if not _so_ligacao(gap):
                    break
                j += 1
                fim_j = verbos[j + 1][0] if j + 1 < len(verbos) else limite
                refs = [r for r in todas if verbos[j][1] <= r.ini < fim_j]
            for r in refs:
                entre = f[e : r.ini]
                parcial = bool(_PARCIAL.search(entre)) or verbo in (
                    VERBO_NOVA_REDACAO,
                    VERBO_ACRESCENTA,
                )
                saida.append(
                    Relacao(
                        verbo=verbo,
                        verbo_texto=texto[s:e],
                        parcial=parcial,
                        ref=r,
                        trecho=texto[s : r.fim].strip(),
                    )
                )
    return saida


def extrair_anotacoes(ementa: str) -> list[Relacao]:
    """Anotação editorial do índice ("REVOGADO PELO DECRETO N° …") como relação.

    A ação recai sobre a própria norma da ementa; a referência lida é quem agiu.
    O sentido é invertido por ``construir_relacoes`` (a origem passa a ser quem
    revogou). Lê o texto inteiro, inclusive o que está entre aspas — é onde o
    índice costuma colocar a anotação.
    """
    if not ementa:
        return []
    texto = re.sub(r"\s+", " ", ementa).strip()
    f = fold(texto)
    saida: list[Relacao] = []
    for m in _ANOTACAO.finditer(f):
        refs = [r for r in ler_referencias(texto, f) if r.ini == m.end()]
        # só a primeira referência imediatamente após "pelo/pela"
        for r in refs[:1]:
            acao = m.group("acao")
            verbo = VERBO_OUTRO if "efeito" in acao else VERBO_REVOGA
            saida.append(
                Relacao(
                    verbo=verbo,
                    verbo_texto=texto[m.start() : m.end()].strip(),
                    parcial="parcialmente" in f[m.start() : m.end()],
                    ref=r,
                    trecho=texto[m.start() : r.fim].strip(),
                    fonte=FONTE_ANOTACAO,
                )
            )
    return saida


# ---------------------------------------------------------------------------
# Resolução contra o catálogo
# ---------------------------------------------------------------------------


def _mesmo_ano(ref: Referencia, cand: NormaCatalogo) -> Optional[bool]:
    """A data escrita concorda com a do catálogo? ``None`` se a referência não tem."""
    if ref.data is not None and cand.data is not None:
        return ref.data[:4] == cand.data[:4]
    if ref.ano is not None:
        cand_ano = int(cand.data[:4]) if cand.data else cand.ano
        if cand_ano is None:
            return None
        return ref.ano == cand_ano
    return None


def resolver(
    ref: Referencia,
    indice: Indice,
    *,
    ator_data: Optional[str],
    ator_id: Optional[str],
) -> tuple[Optional[str], str, Optional[str]]:
    """``(alvo_id, confianca, nota)`` de uma referência.

    ``ator_data``/``ator_id`` são a data e o id da norma que age (para a regra de
    cronologia — uma norma não altera uma posterior — e para a autorreferência).
    """
    if ref.nota:
        return None, CONFIANCA_NAO_RESOLVIDA, ref.nota
    if ref.categoria == CAT_FEDERAL:
        return None, CONFIANCA_NAO_RESOLVIDA, "federal"
    if ref.categoria == CAT_MUNICIPAL:
        return None, CONFIANCA_NAO_RESOLVIDA, "municipal"
    if ref.tipo not in TIPOS_INDEXADOS:
        return None, CONFIANCA_NAO_RESOLVIDA, "tipo-sem-indice"
    if ref.numero is None:
        return None, CONFIANCA_NAO_RESOLVIDA, "sem-numero"
    if ref.data_ilegivel:
        return None, CONFIANCA_NAO_RESOLVIDA, "data-ilegivel"

    candidatos = indice.por_chave.get((ref.tipo, ref.numero), [])
    if not candidatos:
        return None, CONFIANCA_NAO_RESOLVIDA, "ausente-do-indice"
    exatos = [c for c in candidatos if c.sufixo == ref.sufixo]
    if not exatos:
        ids = ",".join(sorted(c.norma_id for c in candidatos))
        return None, CONFIANCA_AMBIGUA, f"sufixo-diverge:{ids}"
    if len(exatos) > 1:
        ids = ",".join(sorted(c.norma_id for c in exatos))
        return None, CONFIANCA_AMBIGUA, f"candidatos:{ids}"
    cand = exatos[0]

    concorda = _mesmo_ano(ref, cand)
    if concorda is False:
        return None, CONFIANCA_NAO_RESOLVIDA, "data-diverge"
    if cand.norma_id == ator_id:
        return None, CONFIANCA_NAO_RESOLVIDA, "autorreferencia"
    if ator_data and cand.data and cand.data > ator_data:
        return None, CONFIANCA_NAO_RESOLVIDA, "cronologia"
    if cand.identidade_incerta:
        return cand.norma_id, CONFIANCA_AMBIGUA, "identidade-incerta"
    nota = None
    if concorda is None:
        nota = "sem-data"
    elif ref.data and cand.data and ref.data != cand.data:
        nota = "data-diverge-mesmo-ano"
    return cand.norma_id, CONFIANCA_RESOLVIDA, nota


def _relacao_id(
    origem: str, verbo: str, ref: Referencia, alvo_id: Optional[str]
) -> str:
    chave = "|".join(
        [
            origem,
            verbo,
            alvo_id or "",
            ref.tipo,
            str(ref.numero or ""),
            ref.sufixo,
            ref.data or str(ref.ano or ""),
        ]
    )
    return "rel-" + hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]


def construir_relacoes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Relações de todas as normas listadas do livro-razão, resolvidas e deduplicadas.

    ``rows`` são as linhas de ``completeness.build_ledger`` (precisam de
    ``norma_id``, ``tipo``, ``numero``, ``sufixo``, ``data``, ``ano``, ``ementa`` e
    ``identidade_incerta``). Devolve linhas de ``RELACOES_SCHEMA``, ordenadas por
    ``origem_id``, ``verbo`` e ``alvo``.
    """
    indice = Indice.de_linhas(rows)
    por_id = {r["norma_id"]: r for r in rows if r.get("situacao") == "listada"}
    saida: dict[tuple[str, str, str], dict[str, Any]] = {}

    def guardar(linha: dict[str, Any]) -> None:
        # Mesma ação da mesma origem sobre o mesmo alvo resolvido (ou a mesma
        # referência escrita): uma linha só; a ementa vale mais que a anotação.
        alvo_chave = linha["alvo_id"] or "|".join(
            [
                str(linha["alvo_tipo"]),
                str(linha["alvo_numero"] or ""),
                str(linha["alvo_sufixo"]),
                str(linha["alvo_data"] or linha["alvo_ano"] or ""),
            ]
        )
        chave = (linha["origem_id"], linha["verbo"], alvo_chave)
        antiga = saida.get(chave)
        if antiga is None or (
            antiga["fonte_relacao"] == FONTE_ANOTACAO
            and linha["fonte_relacao"] == FONTE_EMENTA
        ):
            saida[chave] = linha

    for row in rows:
        if row.get("situacao") != "listada" or not row.get("ementa"):
            continue
        origem_id = str(row["norma_id"])
        incerta = bool(row.get("identidade_incerta"))

        for rel in extrair_da_ementa(str(row["ementa"])):
            alvo_id, confianca, nota = resolver(
                rel.ref, indice, ator_data=row.get("data"), ator_id=origem_id
            )
            if incerta and confianca == CONFIANCA_RESOLVIDA:
                confianca, nota = CONFIANCA_AMBIGUA, "origem-identidade-incerta"
            guardar(_linha(origem_id, rel, alvo_id, confianca, nota))

        # Anotação "REVOGADO PELO X": só vira relação se X for uma norma do
        # catálogo (então X é a origem). Sem isso a ementa já mostra o texto.
        for rel in extrair_anotacoes(str(row["ementa"])):
            ator_id, confianca, nota = resolver(
                rel.ref, indice, ator_data=None, ator_id=origem_id
            )
            if ator_id is None or confianca != CONFIANCA_RESOLVIDA:
                continue
            ator = por_id.get(ator_id)
            if ator is not None and ator.get("data") and row.get("data"):
                if str(ator["data"]) < str(row["data"]):
                    continue  # quem revoga não pode ser anterior
            alvo = Referencia(
                tipo=str(row["tipo"]),
                categoria=CAT_ESTADUAL,
                numero=int(row["numero"]),
                sufixo=str(row.get("sufixo") or ""),
                data=row.get("data"),
                ano=int(row["ano"]) if row.get("ano") is not None else None,
                ini=0,
                fim=0,
                texto=str(row.get("titulo") or ""),
            )
            guardar(
                _linha(
                    ator_id,
                    Relacao(
                        verbo=rel.verbo,
                        verbo_texto=rel.verbo_texto,
                        parcial=rel.parcial,
                        ref=alvo,
                        trecho=rel.trecho,
                        fonte=FONTE_ANOTACAO,
                    ),
                    origem_id,
                    CONFIANCA_RESOLVIDA,
                    nota,
                )
            )
    # Uma relação não resolvida (ex.: data da ementa diverge do índice) cujo alvo
    # escrito a anotação do índice já resolveu para a mesma ação: fica só a resolvida.
    resolvidas = {
        (r["origem_id"], r["verbo"], r["alvo_tipo"], r["alvo_numero"], r["alvo_sufixo"])
        for r in saida.values()
        if r["confianca"] == CONFIANCA_RESOLVIDA
    }
    saida = {
        k: r
        for k, r in saida.items()
        if r["confianca"] == CONFIANCA_RESOLVIDA
        or (
            r["origem_id"],
            r["verbo"],
            r["alvo_tipo"],
            r["alvo_numero"],
            r["alvo_sufixo"],
        )
        not in resolvidas
    }
    return sorted(
        saida.values(),
        key=lambda r: (
            r["origem_id"],
            r["verbo"],
            r["alvo_id"] or "",
            r["alvo_tipo"],
            r["alvo_numero"] or 0,
            r["alvo_sufixo"],
        ),
    )


def _linha(
    origem_id: str,
    rel: Relacao,
    alvo_id: Optional[str],
    confianca: str,
    nota: Optional[str],
) -> dict[str, Any]:
    ref = rel.ref
    return {
        "relacao_id": _relacao_id(origem_id, rel.verbo, ref, alvo_id),
        "origem_id": origem_id,
        "verbo": rel.verbo,
        "verbo_texto": rel.verbo_texto,
        "parcial": rel.parcial,
        "alvo_tipo": ref.tipo,
        "alvo_categoria": ref.categoria,
        "alvo_numero": ref.numero,
        "alvo_sufixo": ref.sufixo,
        "alvo_data": ref.data,
        "alvo_ano": ref.ano,
        "alvo_texto": ref.texto,
        "alvo_id": alvo_id,
        "confianca": confianca,
        "nota": nota,
        "trecho": rel.trecho,
        "fonte_relacao": rel.fonte,
    }


def tem_verbo_de_alteracao(ementa: str) -> bool:
    """A ementa contém algum verbo do conjunto, em qualquer posição (diagnóstico)."""
    f = fold(ementa)
    return bool(_achar_verbos(f, 0, len(f)))


def rows_to_parquet(
    rows: list[dict[str, Any]],
    schema: dict[str, str],
    output_path: Any,
    order_by: str,
) -> None:
    """Grava linhas em Parquet (ZSTD) com o ``schema`` dado, ordenadas por ``order_by``.

    Passa pelas linhas como JSON delimitado por quebra de linha lido de volta pelo
    DuckDB com colunas tipadas: dezenas de milhares de linhas gravam em segundos (um
    ``executemany`` linha a linha leva minutos).
    """
    import json
    import tempfile
    from pathlib import Path

    import duckdb

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ", ".join(f"'{c}': '{t}'" for c, t in schema.items())
    with tempfile.TemporaryDirectory() as tmp:
        ndjson = Path(tmp) / "rows.ndjson"
        with ndjson.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(
                    json.dumps({c: row.get(c) for c in schema}, ensure_ascii=False)
                    + "\n"
                )
        conn = duckdb.connect()
        try:
            source = str(ndjson).replace("'", "''")
            target = str(path).replace("'", "''")
            conn.execute(
                f"COPY (SELECT * FROM read_json('{source}', format='newline_delimited', "
                f"columns={{{columns}}}) ORDER BY {order_by}) "
                f"TO '{target}' (FORMAT parquet, COMPRESSION zstd)"
            )
        finally:
            conn.close()


def write_relacoes_parquet(rows: list[dict[str, Any]], output_path: Any) -> None:
    """Grava as relações em Parquet (ZSTD), ordenadas por origem, verbo e alvo."""
    rows_to_parquet(
        rows,
        RELACOES_SCHEMA,
        output_path,
        "origem_id, verbo, alvo_id, relacao_id",
    )
