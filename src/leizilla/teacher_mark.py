"""Mark mode of the teacher batch (DAG node ``boundary-decision-parser``).

Third teacher mode, next to ``label`` (``teacher_batch.py``) and ``review``
(``teacher_review.py``). The model does the FULL parse of a norm, independently of
the rule-based reader (it sees no reader tags), and answers with ONLY where the marks
go: one short JSON entry per mark, never the text. Code builds the marked document
(``marcacao.build``, docs/okf/documento-marcado.md) and checks it (``marcacao.verify``).

Every mark carries TWO anchors in the same response, so that the owner can measure
whether the model can point at the exact character position inside a line:

* anchor A, ``c``: the 1-based column of the first character of the printed marker in
  the line as shown;
* anchor B, ``t``: the marker itself, copied verbatim (it is also the ``<m>`` span).

The converter resolves both independently (exact match in the line, then a tolerant one:
accent, case, whitespace and punctuation folded), records which was used and whether
they agree, builds with B when it resolves uniquely in the line, else A, else drops the
mark with a reason. Ends of devices and organisational headings are never asked: code
derives them from the next sibling/ancestor start and the parent's end. Blocks (epígrafe,
ementa, preâmbulo, fecho, assinatura, anexo, ruído, alteração) give their start and
their end line.

Same three resumable steps, cost guard, prompt caching, truncation handling and
manifest as the review mode; ``submit`` writes ``"mode": "mark"`` and ``collect``
dispatches on it. Nothing here touches a label, an errata file or the reader.

Design notes that are easy to get wrong:

* The strip invariant can never fail by construction: ``build`` only inserts tags into
  the untouched text and this module asserts ``strip(xml) == text`` on every document.
  What can fail is the GRAMMAR (nesting): then the offending mark is dropped and
  recorded, never the whole norm.
* ``n`` is the INTERPRETED number; the printed text is never altered.
* The manifest carries the (compressed) texts: ``collect`` needs the text to build the
  document and must not depend on a re-download of the text layer.
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import math
import random
import re
import subprocess
import tarfile
import tempfile
import unicodedata
import zlib
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast

import typer

from leizilla import marcacao
from leizilla import publisher
from leizilla import teacher_batch as tb
from leizilla import teacher_review as tr
from leizilla.hierarchy_sequence import read_hierarchy
from leizilla.marcacao import Mark

# --------------------------------------------------------------------------
# Contract versions and constants
# --------------------------------------------------------------------------

MARK_PROMPT_VERSION = "teacher-mark-v2"
MARK_SCHEMA_VERSION = "1"
DEFAULT_MARK_LABEL_SET = "mark"
MODE = "mark"

DEVICE_KINDS: tuple[str, ...] = marcacao.DEVICES
ORG_KINDS: tuple[str, ...] = marcacao.ORG
BLOCK_KINDS: tuple[str, ...] = (
    "epigrafe",
    "ementa",
    "preambulo",
    "fecho",
    "assinatura",
    "anexo",
    "ruido",
    "alteracao",
)
MARK_KINDS: tuple[str, ...] = (*ORG_KINDS, *DEVICE_KINDS, *BLOCK_KINDS)
STRUCTURAL_KINDS = frozenset((*ORG_KINDS, *DEVICE_KINDS))
# Blocks that live at ``lei`` level (or at the root) and close every open device.
PART_KINDS = frozenset(marcacao.PARTS)
BARRIERS = frozenset(("alteracao", "anexo"))
TAIL_KINDS = frozenset(("fecho", "assinatura", "anexo"))
NOTA_BY = "modelo"
NOTA_TIPO = "teacher-mark"

# Chunking (a norm longer than this is cut in parts, one request per part).
MARK_MAX_LINES = 150
MARK_MAX_CHARS = 14_000
DEFAULT_MARK_BUDGET_CHARS = 16_000
DEFAULT_MARK_MAX_NORMS = 4
# The plan skips nothing; the pilot selection excludes norms over this many parts.
PILOT_MAX_PARTS = 4

# Output-token model. One mark of the response, serialized with every field
# (``{"l":12,"k":"art","c":1,"t":"Art. 5º","n":"5","s":null,"le":null,"x":false,
# "e":null,"nota":null}``) is ~100 characters: 50 tokens at the code's conservative
# 2 characters per token.
TOKENS_PER_MARK = 50
EST_TOKENS_PER_MARK = 40
MARK_FRAMING_TOKENS = 100
# Per norm in a request: thinking room, and the ceiling's marks (one per shown line).
MARK_THINKING_PER_NORM = 1024
MARK_MAX_TOKENS_BASE = 8192
MARK_MAX_TOKENS_CAP = 32_000
RETRY_BUDGET_FACTOR = 1.5
# No measurement of the mark mode exists yet: the estimate reuses the review mode's
# measured thinking (2070 tokens per request at effort medium) as the per-request base.
MARK_BASE_OUTPUT_TOKENS = tr.MEASURED_OUTPUT_TOKENS_PER_REQUEST

ESTADOS = ("vetado",)
STATES: tuple[str, ...] = (
    "ok",
    "degraded",
    "partial",
    "truncated",
    "invalid",
    "build_failed",
)

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_N_ARABIC = re.compile(r"[0-9]{1,4}")
_N_LETTER = re.compile(r"[a-z]{1,2}")
_SUFFIX = re.compile(r"[A-Za-z]{1,3}")
_MARKER_SNIPPET = 20

# --------------------------------------------------------------------------
# Response schema (structured output; same constraints as LABEL_SCHEMA)
# --------------------------------------------------------------------------

_NULLABLE_STRING = tb._NULLABLE_STRING
_NULLABLE_INTEGER = tb._NULLABLE_INTEGER
MARK_FIELDS: tuple[str, ...] = ("l", "k", "c", "t", "n", "s", "le", "x", "e", "nota")

MARK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "norms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "marks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "l": {"type": "integer"},
                                "k": {"type": "string", "enum": list(MARK_KINDS)},
                                "c": {"type": "integer"},
                                "t": {"type": "string"},
                                "n": _NULLABLE_STRING,
                                "s": _NULLABLE_STRING,
                                "le": _NULLABLE_INTEGER,
                                "x": {"type": "boolean"},
                                "e": {
                                    "anyOf": [
                                        {"type": "string", "enum": list(ESTADOS)},
                                        {"type": "null"},
                                    ]
                                },
                                "nota": _NULLABLE_STRING,
                            },
                            "required": list(MARK_FIELDS),
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "marks"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["norms"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# The worked example in the prompt (built from data, so its columns are right)
# --------------------------------------------------------------------------

EXAMPLE_LINES: Dict[int, str] = {
    3: "GOVERNO DO ESTADO DE RONDÔNIA",
    4: "LEI Nº 7 DE 5 DE ABRIL DE 1985",
    6: "Dispõe sobre a coisa e dá outras providências.",
    8: "O GOVERNADOR DO ESTADO DE RONDÔNIA faço saber que a Assembléia "
    "Legislativa decreta e eu sanciono a seguinte Lei:",
    10: "Art. 1º - A coisa será gerida pela Secretaria, nos termos do art. 9º "
    "da Lei Federal.",
    11: "§ 1º - Compete à Secretaria:",
    12: "I - regulamentar a coisa;",
    13: "a) por decreto, às terças; b) por portaria;",
    14: "Il - fiscalizar a coisa.",
    15: "Art. 2º - O art. 5º da Lei nº 100 passa a vigorar com a seguinte redação:",
    16: '"Art. 5º - Fica proibido o uso de fogo.',
    17: 'Parágrafo único - A multa é de 10 UFIR." (NR)',
    18: "Esta Lei entra em vigor na data de sua publicação.",
    20: "Porto Velho, 5 de abril de 1985.",
    21: "OSWALDO FILHO - Governador",
}
# (line, kind, marker/first characters, n, suffix, end line, no marker, nota)
_EXAMPLE_SPEC: tuple[tuple[Any, ...], ...] = (
    (3, "ruido", "GOVERNO DO ESTADO", None, None, 3, False, None),
    (4, "epigrafe", "LEI Nº 7", None, None, 4, False, None),
    (6, "ementa", "Dispõe sobre a coisa", None, None, 6, False, None),
    (8, "preambulo", "O GOVERNADOR DO ESTADO", None, None, 8, False, None),
    (10, "art", "Art. 1º", "1", None, None, False, None),
    (11, "par", "§ 1º", "1", None, None, False, None),
    (12, "inc", "I -", "1", None, None, False, None),
    (13, "ali", "a)", "a", None, None, False, None),
    (13, "ali", "b)", "b", None, None, False, None),
    (14, "inc", "Il -", "2", None, None, False, "impresso Il, lido II"),
    (15, "art", "Art. 2º", "2", None, None, False, None),
    (16, "alteracao", '"Art. 5º - Fica', None, None, 17, False, None),
    (16, "art", "Art. 5º", "5", None, None, False, None),
    (17, "par", "Parágrafo único", "unico", None, None, False, None),
    (18, "art", "Esta Lei entra em vigor", "3", None, None, True, "marcador perdido"),
    (20, "fecho", "Porto Velho", None, None, 20, False, None),
    (21, "assinatura", "OSWALDO FILHO", None, None, 21, False, None),
)


def _example_mark(spec: Sequence[Any]) -> Dict[str, Any]:
    line, kind, t, n, s, le, no_marker, nota = spec
    col = EXAMPLE_LINES[line].find(t) + 1
    assert col >= 1, (line, t)
    return {
        "l": line,
        "k": kind,
        "c": col,
        "t": t,
        "n": n,
        "s": s,
        "le": le,
        "x": no_marker,
        "e": None,
        "nota": nota,
    }


def example_response() -> Dict[str, Any]:
    return {
        "norms": [{"id": "N01", "marks": [_example_mark(s) for s in _EXAMPLE_SPEC]}]
    }


def example_listing() -> str:
    return "\n".join(f"{n}\t{text}" for n, text in sorted(EXAMPLE_LINES.items()))


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def example_json() -> str:
    """The example answer, one mark per line (what the model should emit is the
    compact form; one per line is only for reading)."""
    marks = example_response()["norms"][0]["marks"]
    body = ",\n".join(" " + _compact(m) for m in marks)
    return '{"norms":[{"id":"N01","marks":[\n' + body + "\n]}]}"


_PROMPT_TEMPLATE = """\
Você é um anotador especialista em técnica legislativa brasileira. Sua tarefa é LER \
a estrutura de normas do Estado de Rondônia e dizer ONDE cada parte começa (e, para \
alguns blocos, onde termina). Você nunca reescreve nem devolve o texto da norma: um \
programa insere as marcas no texto original a partir da sua resposta.

# Entrada

Cada requisição traz uma ou mais normas, ou uma parte de uma norma longa. O texto vem \
de OCR de documentos digitalizados (muitos datilografados nos anos 1980): os sinais \
ordinais e os algarismos saem estragados ("Art. Io" é o artigo 1; "Art. 42" entre o 3 \
e o 5 é o artigo 4; "1Q", "3°", "2-", "Il -" são 1, 3, 2 e o inciso II), palavras \
partidas no fim da linha, cabeçalhos e rodapés repetidos a cada página.

Cada norma começa com uma linha de cabeçalho e termina com `### fim ID`:

`### N03 | lei 123 | 85 linhas`

`N03` é o identificador da norma NESTA requisição; use-o na resposta, sem alterar. \
Partes de norma longa trazem `parte 2/3` e só as linhas de `[linhas a marcar]` podem \
receber marca; `[contexto, somente leitura]` serve para se situar (um dispositivo ou \
um bloco citado pode ter começado na parte anterior).

Cada linha vem como `NÚMERO<TAB>TEXTO`. O TEXTO está sem espaços nas pontas. Linhas \
em branco foram omitidas, por isso a numeração tem saltos: use sempre o número que \
acompanha a linha, nunca conte linhas. A COLUNA conta caracteres a partir do primeiro \
caractere depois do TAB, começando em 1 (um caractere acentuado conta 1).

# O que marcar

Cada marca diz onde algo COMEÇA no texto. Marque apenas o que o texto traz; não invente.

Dispositivos (só o início; o programa deduz o fim a partir do próximo dispositivo do \
mesmo nível ou de nível acima):

- `art` artigo; `par` parágrafo (`§ 2º`, `Parágrafo único`); `inc` inciso (romano: \
`III -`); `ali` alínea (`a)`); `item` item (`1.`, `1)`). Hierarquia: art ⊃ par | inc | \
ali | item; par ⊃ inc | ali | item; inc ⊃ ali | item; ali ⊃ item.
- Títulos organizacionais, só o início: `parte`, `liv` (livro), `tit` (título), \
`cap` (capítulo), `sec` (seção), `subsec` (subseção). Marque a linha do cabeçalho \
("CAPÍTULO II"), não o nome do capítulo na linha seguinte.

Blocos (começo E fim; `le` é a linha em que o bloco termina, e ele vai até o fim \
dessa linha):

- `epigrafe` ("LEI Nº 7 DE 5 DE ABRIL DE 1985"); `ementa` (resumo que vem depois); \
`preambulo` (a autoridade e a fórmula "decreta e eu sanciono", até o primeiro \
dispositivo); `fecho` (local e data depois do corpo); `assinatura` (nomes e cargos); \
`anexo` (anexos, tabelas e quadros, `n` se numerado: depois do corpo, ou entre dois \
dispositivos; o programa acaba o anexo na marca seguinte, então `le` só precisa chegar \
à última linha que você vê dele).
- `ruido`: tudo que NÃO é texto da norma: cabeçalho e rodapé de página, carimbos, \
numeração de página, lixo de OCR. Repete-se a cada página: marque cada ocorrência, \
uma marca por bloco de linhas.
- `alteracao`: texto transcrito de OUTRA norma (depois de "passa a vigorar com a \
seguinte redação:", "acrescido do seguinte artigo:"). Os dispositivos transcritos \
dentro dele são marcados normalmente (`art`, `par`...) e ficam dentro do bloco; não \
há marca de "próprio" ou "citado". O bloco inclui as aspas que o abrem e vai até a \
ASPA DE FECHAMENTO ou o "(NR)", que pode estar dezenas de linhas adiante: só o \
primeiro dispositivo transcrito traz aspas de abertura, os seguintes (`Art. 9º`, \
`Art. 10`... do mesmo bloco) NÃO têm aspas próprias e continuam citados até a aspa que \
fecha. Procure a aspa de fechamento antes de pôr `le`; o dispositivo próprio que vem \
depois dela NÃO entra no bloco. Sinal de que você cortou o bloco cedo: depois dele a \
numeração dos artigos "próprios" repete ou volta atrás (9, 10, 2, 3).

Um arquivo pode trazer mais de uma norma (a lei e, depois da assinatura, cópias do \
projeto de lei): marque `epigrafe`, `ementa` e `preambulo` de cada uma; a numeração dos \
artigos recomeça em 1 e o programa abre ali uma norma nova. `fecho`, `assinatura` e \
`anexo` podem aparecer no meio do corpo, entre dois artigos.

Todo texto que sobra, sem marca, fica sem dono: tudo bem. Não marque citações no meio \
de frase ("nos termos do art. 9º") nem números de página.

# Os campos de cada marca

Toda marca tem sempre os dez campos; o que não se aplica vai como `null` (ou `false`):

- `l`: número da linha onde a marca COMEÇA;
- `k`: o tipo;
- `c`: COLUNA: 1-based, contada em caracteres, do primeiro caractere do marcador \
impresso nessa linha (para um bloco, do primeiro caractere dele, aspa de abertura \
inclusive). É ela que vale: um marcador no meio da linha (`b)` depois de `a) ...;`) \
tem a coluna do meio da linha, não 1; conte os caracteres da linha até ele;
- `t`: TRECHO que confere a coluna: o marcador exatamente como está impresso, copiado \
caractere por caractere: `Art. 5º`, `§ 2º`, `Parágrafo único`, `III -`, `a)`, `1.` \
(com o erro de OCR, se houver: `Il -`). Sem copiar a palavra que vem depois. Para um \
bloco, no máximo os ~15 primeiros caracteres da PRIMEIRA linha dele, nunca o que vem \
na linha seguinte;
- `n`: o número INTERPRETADO, como texto: algarismos arábicos para `art`, `par`, \
`item`, organizacionais e anexo (`"5"`); o VALOR do romano para `inc` e organizacionais \
(`III` é `"3"`, `Il` é `"2"`); a letra minúscula para `ali` (`"a"`); `"unico"` para \
parágrafo único. `null` nos blocos. Nunca altere o texto impresso: o número impresso \
pode estar errado e o interpretado ser outro (corrija pela sequência: "Art. 42" entre \
3 e 5 é `"4"`). Cuidado com o sinal ordinal lido como DÍGITO: o `º` de `9º` sai do OCR \
como `2`, `0`, `9`, `o` ou `Q` colado ao número, e o artigo 9 aparece como `Art. 92`, o \
10 como `Art. 102`, o 5 como `Art. 52`, o 6 como `Art. 60`, o 8 como `Art. 80`. Decida \
pela sequência: depois do 8 vem o 9, nunca o 92; só leia dois dígitos quando a \
sequência os pede (depois do 78 vem o 79). Se mudou o número, diga em `nota` ("impresso \
92, lido 9");
- `s`: sufixo de letra maiúscula do "Art. 5º-A" (`"A"`), ou `null`;
- `le`: linha final do bloco (para `epigrafe`, `ementa`, `preambulo`, `fecho`, \
`assinatura`, `anexo`, `ruido`, `alteracao`); `null` nos dispositivos e títulos;
- `x`: `true` quando o dispositivo NÃO tem marcador legível (o OCR o destruiu e você o \
deduziu pela sequência, como a cláusula "Esta Lei entra em vigor..." sem "Art. 3º"); \
nesse caso `t` são as primeiras palavras da frase (uns 20 caracteres) e `c` a coluna \
onde ela começa. Senão `false`;
- `e`: `"vetado"` quando o dispositivo diz que foi vetado; senão `null`;
- `nota`: observação curta nossa (até 12 palavras), use raramente: por exemplo \
"impresso 42, lido 4" quando o número impresso difere do interpretado. Senão `null`.

# Saída

Responda apenas com o objeto JSON do esquema: `norms` com UMA entrada para CADA norma \
da requisição, exatamente uma vez cada, na ordem em que aparecem, e `marks` com as \
marcas em ordem de linha e coluna. Um id que falta ou repetido invalida a norma. Uma \
marca cujo trecho e coluna não localizam o marcador na linha, ou que não cabe na \
hierarquia, é DESCARTADA e registrada; as demais continuam valendo.

# Exemplo

Entrada:

```
### N01 | lei 7 | 16 linhas
{{EXEMPLO_ENTRADA}}
### fim N01
```

Resposta certa (compacta, uma marca por linha aqui só para ler):

```
{{EXEMPLO_SAIDA}}
```

Na linha 10 a citação "art. 9º" no meio da frase não é marca. Na linha 13 há duas alíneas: `b)` \
está no meio da linha, na coluna {{COL_B}}, e não na 1. A linha 14 imprime \
`Il -` (OCR) e o inciso é o 2. A linha 16 abre a transcrição (`alteracao` de 16 a 17), \
com o artigo e o parágrafo citados dentro dela; o artigo 3 da própria norma, na linha \
18, é próprio porque vem depois do fim do bloco, e como perdeu o marcador leva `x` \
verdadeiro e o início da frase em `t`.
"""

MARK_SYSTEM_PROMPT = (
    _PROMPT_TEMPLATE.replace("{{EXEMPLO_ENTRADA}}", example_listing())
    .replace("{{EXEMPLO_SAIDA}}", example_json())
    .replace("{{COL_B}}", str(EXAMPLE_LINES[13].find("b)") + 1))
)


def mark_prompt_sha256() -> str:
    """Hash of everything that defines the mark contract sent to the model."""
    blob = MARK_SYSTEM_PROMPT + "\n" + json.dumps(MARK_SCHEMA, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Folding and locating an anchor in a line
# --------------------------------------------------------------------------

_ORDINALS = {"°": "o", "º": "o", "ª": "a"}
# Quote characters are never folded away: a tolerant match that skipped the opening
# quote of a quoted block put the block one column late (pilot, lc-00074 line 51).
_QUOTES = frozenset("\"\u201c\u201d\u201e\u201f\u00ab\u00bb'\u2018\u2019\u201a")
CONFIRM_CHARS = 4


def fold_with_map(s: str) -> tuple[str, List[int]]:
    """Fold ``s`` for the tolerant match and map each folded char to its index.

    Accents (NFKD, combining marks dropped), case, whitespace and punctuation/symbols
    are folded away; ordinal signs fold to ``o``/``a`` so that ``5º`` and ``5o`` (a
    frequent OCR reading) meet.
    """
    out: List[str] = []
    idx: List[int] = []
    for i, ch in enumerate(s):
        ch = _ORDINALS.get(ch, ch)
        for d in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(d) or d.isspace():
                continue
            if d in _QUOTES:
                out.append('"')
                idx.append(i)
                continue
            if unicodedata.category(d)[0] in "PSZC":
                continue
            for c in d.casefold():
                out.append(c)
                idx.append(i)
    return "".join(out), idx


def _find_all(haystack: str, needle: str) -> List[int]:
    found: List[int] = []
    i = haystack.find(needle)
    while i >= 0:
        found.append(i)
        i = haystack.find(needle, i + 1)
    return found


def locate(line: str, t: str) -> tuple[str, List[tuple[int, int]]]:
    """Resolve anchor B (the marker ``t``) in the shown line.

    Returns ``(method, spans)``: ``exact`` (one exact occurrence), ``tolerant`` (no
    exact one, exactly one tolerant one), ``ambiguous`` (several, of the exact kind if
    any exact one exists, else of the tolerant kind) or ``none``. ``spans`` are the
    ``[start, end)`` character spans in ``line`` of the occurrences.
    """
    if not t:
        return "none", []
    exact = _find_all(line, t)
    if exact:
        spans = [(i, i + len(t)) for i in exact]
        return ("exact" if len(spans) == 1 else "ambiguous"), spans
    ft, _ = fold_with_map(t)
    if len(ft) < 2:
        return "none", []
    fl, idx = fold_with_map(line)
    tol = _find_all(fl, ft)
    spans = [(idx[i], idx[i + len(ft) - 1] + 1) for i in tol]
    if not spans:
        return "none", []
    return ("tolerant" if len(spans) == 1 else "ambiguous"), spans


# --------------------------------------------------------------------------
# Converter: response -> marks
# --------------------------------------------------------------------------


def _trim_end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _line_starts(lines: Sequence[str]) -> List[int]:
    starts: List[int] = []
    pos = 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1
    return starts


@dataclass
class _Rec:
    """One accepted mark before the ends are derived."""

    idx: int
    kind: str
    start: int
    end_expl: Optional[int]
    attrs: Dict[str, str]
    marker: Optional[tuple[int, int]]
    note: str
    row: Dict[str, Any]


def _rank(kind: str) -> float:
    if kind in PART_KINDS and kind != "anexo":
        return -1.0
    if kind == "anexo":
        return -1.0
    if kind == "alteracao":
        return -0.5
    if kind == "ruido":
        return -0.4
    if kind in ORG_KINDS:
        return float(ORG_KINDS.index(kind))
    return float(len(ORG_KINDS) + DEVICE_KINDS.index(kind))


def _roman_value(s: str) -> Optional[int]:
    s = s.lower()
    if not s or any(ch not in _ROMAN for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total


def _clean_number(kind: str, raw: Any) -> tuple[Optional[str], Optional[str]]:
    """``(n, problem)``: the interpreted number as the marked document wants it."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "number_missing"
    n = raw.strip()
    low = n.lower()
    if kind == "ali":
        return (low, None) if _N_LETTER.fullmatch(low) else (None, "bad_number")
    if low == "unico" or low == "único":
        return ("unico", None) if kind in ("par", *ORG_KINDS) else (None, "bad_number")
    if _N_ARABIC.fullmatch(n):
        return str(int(n)), None
    if kind in ("inc", *ORG_KINDS):
        value = _roman_value(low)
        if value:
            return str(value), None
    return None, "bad_number"


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _confirm_fold(s: str) -> str:
    """Whitespace out, every quote character as ``"``: what the confirmation of the
    column compares (the model writes a straight quote for a curly one)."""
    return "".join('"' if ch in _QUOTES else ch for ch in s if not ch.isspace())


def confirms(shown: str, idx: int, t: str, k: int = CONFIRM_CHARS) -> bool:
    """Whether ``shown`` at ``idx`` starts with the first ``k`` characters of ``t``
    (whitespace-folded: ``t`` copied across a line break still confirms, up to the end
    of the line)."""
    want = _confirm_fold(t)[:k]
    have = _confirm_fold(shown[idx : idx + 3 * k])[:k]
    n = min(len(want), len(have))
    return n > 0 and have[:n] == want[:n]


def _resolve_anchors(
    raw: Dict[str, Any], lines: Sequence[str], starts: Sequence[int]
) -> Dict[str, Any]:
    """Anchor A and anchor B of one mark, independently; the policy is applied by
    the caller. Returns the anchor row (offsets are absolute in the text)."""
    line_no = cast(int, raw["l"])
    shown = lines[line_no - 1].strip()
    lead = len(lines[line_no - 1]) - len(lines[line_no - 1].lstrip())
    base = starts[line_no - 1] + lead
    t = str(raw["t"]).strip()
    col = cast(int, raw["c"])
    a_idx = col - 1 if 0 <= col - 1 < len(shown) else None
    method, spans = locate(shown, t)
    b_idx = spans[0][0] if method in ("exact", "tolerant") else None
    row: Dict[str, Any] = {
        "line": line_no,
        "le": _as_int(raw["le"]),
        "kind": raw["k"],
        "n": raw["n"],
        "s": raw["s"],
        "c": col,
        "t": t,
        "line_len": len(shown),
        "a_off": base + a_idx if a_idx is not None else None,
        "b_off": base + b_idx if b_idx is not None else None,
        "a_col": a_idx + 1 if a_idx is not None else None,
        "b_col": b_idx + 1 if b_idx is not None else None,
        "b_method": method,
        "b_candidates": len(spans),
        "agree": None,
        "delta": None,
        "a_in_candidates": None,
        "nonascii_before": None,
        "a_confirm3": None,
        "a_confirm4": None,
        "used": None,
        "offset": None,
        "drop_reason": None,
    }
    row["a_confirm"] = None
    if a_idx is not None:
        k3, k4 = min(3, len(t)), min(4, len(t))
        row["a_confirm3"] = shown[a_idx : a_idx + k3] == t[:k3]
        row["a_confirm4"] = shown[a_idx : a_idx + k4] == t[:k4]
        row["a_confirm"] = confirms(shown, a_idx, t)
    if a_idx is not None and b_idx is not None:
        row["agree"] = a_idx == b_idx
        row["delta"] = a_idx - b_idx
    if a_idx is not None and method == "ambiguous":
        row["a_in_candidates"] = any(s == a_idx for s, _ in spans)
    ref_idx = b_idx if b_idx is not None else a_idx
    if ref_idx is not None:
        row["nonascii_before"] = any(ord(ch) > 127 for ch in shown[:ref_idx])
    # Policy (teacher-mark-v2): A (the column) is primary, confirmed by the first
    # characters of ``t`` at that column; else B when it resolves uniquely; else drop.
    span_len: Optional[int] = None
    if a_idx is not None and row["a_confirm"]:
        row["used"] = "A"
        row["offset"] = base + a_idx
        span_len = min(len(shown) - a_idx, len(t))
        for s0, e0 in spans:
            if s0 == a_idx:
                span_len = e0 - s0
    elif b_idx is not None:
        row["used"] = "B"
        row["offset"] = base + b_idx
        span_len = spans[0][1] - spans[0][0]
    else:
        row["drop_reason"] = "line_blank" if not shown else "no_anchor"
    row["_span_len"] = span_len
    return row


def _parse_raw(raw: Any, n_lines: int, owned: Optional[set[int]]) -> Optional[str]:
    """``None`` when the mark is well formed, else the drop reason."""
    if not isinstance(raw, dict) or not set(MARK_FIELDS) <= set(raw):
        return "bad_shape"
    if raw["k"] not in MARK_KINDS:
        return "bad_kind"
    if _as_int(raw["l"]) is None or not 1 <= raw["l"] <= n_lines:
        return "bad_line"
    if owned is not None and raw["l"] not in owned:
        return "line_not_owned"
    if _as_int(raw["c"]) is None:
        return "bad_column"
    if not isinstance(raw["t"], str) or not raw["t"].strip():
        return "empty_snippet"
    return None


_DROP_PRIORITY = {"nota": 0, "ruido": 1, "alteracao": 2}


def _drop_priority(kind: str) -> int:
    if kind in _DROP_PRIORITY:
        return _DROP_PRIORITY[kind]
    if kind in PART_KINDS:
        return 3
    if kind in ORG_KINDS:
        return 4
    return 5


FRONT_KINDS = frozenset(("epigrafe", "ementa", "preambulo"))
BODY_KINDS = STRUCTURAL_KINDS | FRONT_KINDS


def _anexo_ends(text: str, recs: Sequence[_Rec]) -> List[_Rec]:
    """The records with each ``anexo`` ended where the next mark begins.

    The model's ``le`` for an annex came out too early in the pilot (7 of 24): the
    end is the start of the next mark that is not ``ruido`` (or the end of the text);
    ``le`` stays as a lower bound, so marks inside the line range the model gave are
    still inside the annex.
    """
    starts = sorted(r.start for r in recs if r.kind != "ruido")
    out: List[_Rec] = []
    for r in recs:
        if r.kind == "anexo" and r.end_expl is not None:
            at = bisect.bisect_left(starts, r.end_expl)
            nxt = starts[at] if at < len(starts) else len(text)
            end = max(r.end_expl, _trim_end(text, r.start, nxt))
            r = dataclasses.replace(r, end_expl=end)
        out.append(r)
    return out


def _interior_annexes(recs: Sequence[_Rec]) -> set[int]:
    """Indexes of the ``anexo`` records followed by a body device of the norm (not
    one quoted inside an ``alteracao``): a table between two paragraphs of an
    article. They stay inside the open devices; the annexes after the last device
    (the usual case) close them and sit outside the ``lei``."""
    quoted = [(r.start, r.end_expl) for r in recs if r.kind == "alteracao"]
    devices = sorted(
        r.start
        for r in recs
        if r.kind in STRUCTURAL_KINDS
        and not any(s <= r.start < cast(int, e) for s, e in quoted)
    )
    out: set[int] = set()
    for r in recs:
        if r.kind == "anexo" and r.end_expl is not None:
            if bisect.bisect_left(devices, r.end_expl) < len(devices):
                out.add(r.idx)
    return out


def _top_level(marks: Sequence[Mark]) -> List[Mark]:
    """The marks that are not inside an ``alteracao`` or an ``anexo`` block."""
    out: List[Mark] = []
    cover = -1
    for m in sorted(marks, key=lambda m: (m.start, -m.end)):
        if m.kind in ("nota", "ruido", "lei"):
            continue
        if m.start < cover:
            continue
        out.append(m)
        if m.kind in BARRIERS:
            cover = m.end
    return out


def _own_number(m: Mark) -> Optional[int]:
    n = m.attrs.get("n", "")
    return int(n) if n.isdigit() else None


def acts(marks: Sequence[Mark]) -> List[tuple[int, Optional[int]]]:
    """The acts (one ``lei`` each) of a file: ``(start, next act start or None)``.

    A new act starts at the first body mark after a ``fecho``/``assinatura`` when it
    is an ``epigrafe``/``ementa``/``preambulo`` or an ``art`` whose number does not
    go up (the article numbering restarts: a law followed by copies of its bill).
    An ``anexo``, a ``fecho`` or an ``assinatura`` between devices does not end the
    act; text after the last body device is outside every ``lei``.
    """
    starts: List[int] = []
    tail = False
    last_art: Optional[int] = None
    for m in _top_level(marks):
        if m.kind in ("fecho", "assinatura"):
            tail = tail or bool(starts)
            continue
        if m.kind not in BODY_KINDS:
            continue
        n = _own_number(m) if m.kind == "art" else None
        restart = n is not None and last_art is not None and n <= last_art
        if not starts or (tail and (m.kind in FRONT_KINDS or restart)):
            starts.append(m.start)
            last_art = None
        tail = False
        if m.kind == "art" and n is not None:
            last_art = n
    return [
        (s, starts[i + 1] if i + 1 < len(starts) else None)
        for i, s in enumerate(starts)
    ]


_CLOSING_QUOTE = re.compile("[\"\u201d\u00bb]|''")
_OPENING_QUOTE = '"\u201c\u00ab'


def _line_of(starts: Sequence[int], offset: int) -> int:
    return bisect.bisect_right(starts, max(0, offset))


def suspects(text: str, marks: Sequence[Mark]) -> List[Dict[str, Any]]:
    """Deterministic suspicions about a built document; flagged, never repaired.

    * ``suspect_alteracao``: the own articles of an act (a ``lei``) stop going up (the
      number repeats or goes back: the 9, 10, 2, 3 of a quoted block that was cut short
      and whose later articles became "own"), and the last ``alteracao`` that ends before
      the offending article is blamed. ``closing_quote`` says whether that block's last
      line has a closing quote (``None``: it does not open with a quote either).
    * ``suspect_sequence``: the same break with no ``alteracao`` before it.
    * ``suspect_number``: an own article number far above the previous one that fits
      ``previous`` or ``previous + 1`` once its last digit is dropped: the ordinal sign
      read as a digit (``Art. 92`` for 9, ``Art. 102`` for 10).
    """
    starts = _line_starts(tb.split_lines(text))
    top = _top_level(marks)
    alts = [m for m in marks if m.kind == "alteracao"]
    out: List[Dict[str, Any]] = []
    for lei in (m for m in marks if m.kind == "lei"):
        arts = [
            m
            for m in top
            if m.kind == "art"
            and lei.start <= m.start < lei.end
            and _own_number(m) is not None
        ]
        prev: Optional[Mark] = None
        prev_n: Optional[int] = None
        for art in arts:
            n = cast(int, _own_number(art))
            sfx = art.attrs.get("sufixo", "")
            if prev is not None and prev_n is not None:
                same = n == prev_n and sfx != prev.attrs.get("sufixo", "")
                if n < prev_n or (n == prev_n and not same):
                    out.append(_break_suspect(text, starts, alts, lei, art, prev, n))
                elif n >= 10 and n > prev_n + 1 and n // 10 in (prev_n, prev_n + 1):
                    out.append(
                        {
                            "type": "suspect_number",
                            "line": _line_of(starts, art.start),
                            "n": n,
                            "previous": prev_n,
                            "detail": f"art {n} after {prev_n}: {n // 10}?",
                        }
                    )
                    n = n // 10
            prev, prev_n = art, n
    return out


def _break_suspect(
    text: str,
    starts: Sequence[int],
    alts: Sequence[Mark],
    lei: Mark,
    art: Mark,
    prev: Mark,
    n: int,
) -> Dict[str, Any]:
    before = [a for a in alts if lei.start <= a.start and a.end <= art.start]
    detail = f"own article {n} after {prev.attrs.get('n')}"
    if not before:
        return {
            "type": "suspect_sequence",
            "line": _line_of(starts, art.start),
            "n": n,
            "detail": detail,
        }
    blame = max(before, key=lambda a: a.end)
    # the last line of the block, without the opening quote when it is the only line
    last = text[max(text.rfind("\n", 0, blame.end) + 1, blame.start + 1) : blame.end]
    opens = text[blame.start : blame.start + 1] in _OPENING_QUOTE
    return {
        "type": "suspect_alteracao",
        "line": _line_of(starts, blame.start),
        "end_line": _line_of(starts, blame.end - 1),
        "n": n,
        "closing_quote": bool(_CLOSING_QUOTE.search(last)) if opens else None,
        "detail": detail,
    }


def _lei_marks(
    text: str,
    marks: Sequence[Mark],
    tipo: Optional[str],
    numero: Any,
    owner: Dict[int, int],
) -> List[Mark]:
    """One ``lei`` per act: from its first mark (the first act: from the first
    non-blank character) to the end of the last body device of the act."""
    out: List[Mark] = []
    segments = acts(marks)
    body = [m for m in _top_level(marks) if m.kind in BODY_KINDS]
    for i, (start, nxt) in enumerate(segments):
        last = max(
            (
                m.start
                for m in body
                if m.start >= start and (nxt is None or m.start < nxt)
            )
        )
        inside = [
            m
            for m in marks
            if m.kind not in ("nota", "lei") and start <= m.start <= last
        ]
        lead = len(text) - len(text.lstrip())
        lei_start = min(lead, start) if i == 0 else start
        attrs: Dict[str, str] = {}
        if tipo:
            attrs["tipo"] = str(tipo)
        if numero is not None:
            attrs["numero"] = str(numero)
        lei = Mark("lei", lei_start, max(m.end for m in inside), attrs)
        owner[id(lei)] = -1
        out.append(lei)
    return out


@dataclass
class _Entry:
    rec: _Rec
    rank: float
    expl: Optional[int]


def _derive_marks(
    text: str, recs: Sequence[_Rec], tipo: Optional[str], numero: Any
) -> tuple[List[Mark], Dict[int, int]]:
    """Order, nest and derive the ends. Returns the marks (with ``lei``) and a map from
    ``id(mark)`` to the index of the record it came from (``-1`` for ``lei``)."""
    ended = _anexo_ends(text, recs)
    interior_annexes = _interior_annexes(ended)
    ordered = sorted(ended, key=lambda r: (r.start, _rank(r.kind), r.idx))
    out: List[tuple[Mark, int]] = []
    stack: List[_Entry] = []

    def close(entry: _Entry, bound: int) -> None:
        rec = entry.rec
        if entry.expl is not None:
            end = entry.expl
        else:
            end = _trim_end(text, rec.start, bound)
            if rec.marker is not None:
                end = max(end, rec.marker[1])
        out.append(
            (
                Mark(rec.kind, rec.start, end, dict(rec.attrs), rec.marker),
                rec.idx,
            )
        )
        if rec.note:
            at = rec.marker[1] if rec.marker else rec.start
            out.append(
                (
                    Mark(
                        "nota",
                        at,
                        at,
                        {"por": NOTA_BY, "tipo": NOTA_TIPO},
                        None,
                        rec.note,
                    ),
                    rec.idx,
                )
            )

    def close_until(s: int) -> None:
        # A block whose explicit end is at or before ``s`` ends; the devices above it
        # end with it. Repeat from the bottom of the stack.
        while True:
            cut = next(
                (i for i, e in enumerate(stack) if e.expl is not None and e.expl <= s),
                None,
            )
            if cut is None:
                return
            bound = cast(int, stack[cut].expl)
            for e in stack[cut:]:
                close(e, bound)
            del stack[cut:]

    for rec in ordered:
        s = rec.start
        close_until(s)
        kind = rec.kind
        barrier = max(
            (i for i, e in enumerate(stack) if e.rec.kind in BARRIERS), default=-1
        )
        interior = kind == "anexo" and rec.idx in interior_annexes
        if kind in STRUCTURAL_KINDS or (kind in PART_KINDS and not interior):
            floor = _rank(kind) if kind in STRUCTURAL_KINDS else -2.0
            while len(stack) - 1 > barrier:
                top = stack[-1]
                if top.rec.kind not in STRUCTURAL_KINDS or top.rank < floor:
                    break
                stack.pop()
                close(top, s)
        stack.append(_Entry(rec, _rank(kind), rec.end_expl))
    close_until(len(text) + 1)
    for e in reversed(stack):
        close(e, len(text))
    stack.clear()
    out.sort(key=lambda p: (p[0].start, -p[0].end))
    marks = [m for m, _ in out]
    owner = {id(m): i for m, i in out}

    marks.extend(_lei_marks(text, marks, tipo, numero, owner))
    marks.sort(key=lambda m: (m.start, -m.end, m.kind != "lei"))
    return marks, owner


@dataclass
class Conversion:
    """The result of converting one norm's response."""

    marks: List[Mark] = field(default_factory=list)
    anchors: List[Dict[str, Any]] = field(default_factory=list)
    problems: List[Dict[str, Any]] = field(default_factory=list)
    xml: Optional[str] = None
    verify_problems: List[str] = field(default_factory=list)
    suspects: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def dropped(self) -> List[Dict[str, Any]]:
        return self.problems


def _response_marks(response: Any) -> List[Any]:
    if isinstance(response, dict):
        marks = response.get("marks", [])
        return list(marks) if isinstance(marks, list) else []
    return list(response)


def convert_response(
    text: str,
    response: Any,
    *,
    texto_id: Optional[str] = None,
    tipo: Optional[str] = None,
    numero: Any = None,
    owned: Optional[Iterable[int]] = None,
) -> Conversion:
    """The model's marks of one norm -> the marked document, dropping what cannot be.

    ``response`` is the list of marks (or the ``{"id", "marks"}`` entry). ``owned``
    limits the lines a mark may start on (the parts that were answered). Every mark
    yields one anchor row; marks that are not used carry ``drop_reason``. The document
    always satisfies the strip invariant (asserted); a nesting/grammar conflict drops
    the offending mark (lowest drop priority of the two, then the later one) and
    derives again; ``xml`` is ``None`` only if ``verify`` still fails.
    """
    conv = Conversion()
    lines = tb.split_lines(text)
    starts = _line_starts(lines)
    owned_set = set(owned) if owned is not None else None
    recs: List[_Rec] = []
    seen: set[tuple[str, int]] = set()
    for i, raw in enumerate(_response_marks(response)):
        bad = _parse_raw(raw, len(lines), owned_set)
        if bad is not None:
            row: Dict[str, Any] = {
                "line": raw.get("l") if isinstance(raw, dict) else None,
                "kind": raw.get("k") if isinstance(raw, dict) else None,
                "t": raw.get("t") if isinstance(raw, dict) else None,
                "c": raw.get("c") if isinstance(raw, dict) else None,
                "used": None,
                "drop_reason": bad,
            }
            conv.anchors.append(row)
            continue
        row = _resolve_anchors(raw, lines, starts)
        conv.anchors.append(row)
        if row["drop_reason"]:
            continue
        kind = str(raw["k"])
        attrs: Dict[str, str] = {}
        reason: Optional[str] = None
        if kind in STRUCTURAL_KINDS:
            n, reason = _clean_number(kind, raw["n"])
            if n is not None:
                attrs["n"] = n
            sfx = raw["s"]
            if sfx not in (None, ""):
                if isinstance(sfx, str) and _SUFFIX.fullmatch(sfx.strip()):
                    attrs["sufixo"] = sfx.strip()
                else:
                    reason = reason or "bad_suffix"
            if raw["e"] == "vetado":
                attrs["estado"] = "vetado"
        elif kind == "anexo" and isinstance(raw["n"], str) and raw["n"].strip():
            attrs["n"] = raw["n"].strip()
        start = int(row["offset"])
        end_expl: Optional[int] = None
        if reason is None and kind in BLOCK_KINDS:
            le = _as_int(raw["le"])
            le = _as_int(raw["l"]) if le is None else le
            if le is None or le < raw["l"] or le > len(lines):
                reason = "bad_end_line"
            else:
                end_expl = _trim_end(text, start, starts[le - 1] + len(lines[le - 1]))
                if end_expl <= start:
                    reason = "empty_block"
        if reason is None and (kind, start) in seen:
            reason = "duplicate"
        if reason is not None:
            row["used"] = None
            row["drop_reason"] = reason
            continue
        seen.add((kind, start))
        marker: Optional[tuple[int, int]] = None
        if kind in STRUCTURAL_KINDS and raw["x"] is not True:
            length = row["_span_len"] or len(str(raw["t"]).strip())
            marker = (start, min(len(text), start + max(1, int(length))))
        note = raw["nota"].strip() if isinstance(raw["nota"], str) else ""
        recs.append(_Rec(i, kind, start, end_expl, attrs, marker, note, row))
    for row in conv.anchors:
        row.pop("_span_len", None)

    # Build; on a nesting/grammar error drop the offending mark and derive again.
    by_idx = {r.idx: r for r in recs}
    for _ in range(len(recs) + 2):
        marks, owner = _derive_marks(text, list(by_idx.values()), tipo, numero)
        try:
            xml = marcacao.build(text, marks, texto_id=texto_id)
        except marcacao.MarcacaoError as exc:
            culprit = _pick_culprit(exc, owner, by_idx)
            if culprit is None:
                conv.verify_problems.append(f"build: {exc}")
                conv.marks = marks
                return conv
            rec = by_idx.pop(culprit)
            rec.row["used"] = None
            rec.row["drop_reason"] = "conflict"
            conv.problems.append(
                {
                    "line": rec.row.get("line"),
                    "kind": rec.kind,
                    "n": rec.attrs.get("n"),
                    "reason": "conflict",
                    "detail": str(exc)[:200],
                }
            )
            continue
        conv.marks = marks
        assert marcacao.strip(xml) == text, "strip invariant broken by construction"
        problems = marcacao.verify(xml, text)
        if problems:
            conv.verify_problems = problems
            return conv
        conv.xml = xml
        conv.suspects = suspects(text, marks)
        break
    else:  # pragma: no cover - the loop drops one record per turn
        conv.verify_problems.append("build: did not converge")
    # Anchor rows dropped before the build also count as problems, with their reason.
    for row in conv.anchors:
        if row.get("drop_reason") and row["drop_reason"] != "conflict":
            conv.problems.append(
                {
                    "line": row.get("line"),
                    "kind": row.get("kind"),
                    "n": row.get("n"),
                    "reason": row["drop_reason"],
                    "detail": None,
                }
            )
    return conv


def _pick_culprit(
    exc: marcacao.MarcacaoError, owner: Dict[int, int], by_idx: Dict[int, _Rec]
) -> Optional[int]:
    candidates: List[int] = []
    for mark in (exc.a, exc.b):
        if mark is None:
            continue
        idx = owner.get(id(mark))
        if idx is not None and idx in by_idx:
            candidates.append(idx)
    if not candidates:
        return None
    # lowest drop priority first; on a tie the later mark (the second one named).
    best = min(
        range(len(candidates)),
        key=lambda i: (_drop_priority(by_idx[candidates[i]].kind), -i),
    )
    return candidates[best]


def marks_from_response(
    text: str, response: Any, **kwargs: Any
) -> tuple[List[Mark], List[Dict[str, Any]]]:
    """``(marks, problems)`` of one norm's response (see `convert_response`)."""
    conv = convert_response(text, response, **kwargs)
    return conv.marks, conv.problems


# --------------------------------------------------------------------------
# Responses made from the reader (tests and the dry simulation)
# --------------------------------------------------------------------------


def response_from_marks(
    text: str, marks: Sequence[Mark], rid: str = "N01"
) -> Dict[str, Any]:
    """The answer a perfect model would give for ``marks`` (reader marks): used by the
    tests and the dry simulation. A ``fecho`` is added for the text after the ``lei``,
    which is how a model marks the tail the reader leaves untagged."""
    lines = tb.split_lines(text)
    starts = _line_starts(lines)

    def line_of(offset: int) -> int:
        return bisect.bisect_right(starts, offset)

    def col_of(offset: int) -> int:
        ln = line_of(offset)
        lead = len(lines[ln - 1]) - len(lines[ln - 1].lstrip())
        return offset - starts[ln - 1] - lead + 1

    out: List[Dict[str, Any]] = []
    lei_end: Optional[int] = None
    for m in sorted(marks, key=lambda m: (m.start, -m.end)):
        if m.kind == "lei":
            lei_end = m.end
            continue
        if m.kind == "nota":
            continue
        entry: Dict[str, Any] = {
            "l": line_of(m.start),
            "k": m.kind,
            "c": col_of(m.start),
            "n": None,
            "s": None,
            "le": None,
            "x": False,
            "e": None,
            "nota": None,
        }
        if m.kind in STRUCTURAL_KINDS:
            entry["n"] = m.attrs.get("n")
            entry["s"] = m.attrs.get("sufixo")
            entry["e"] = m.attrs.get("estado")
            if m.marker is not None:
                # a marker broken across lines is given by its first line
                entry["t"] = text[m.marker[0] : m.marker[1]].split("\n")[0].rstrip()
            else:
                entry["x"] = True
                entry["t"] = text[m.start : m.start + _MARKER_SNIPPET].split("\n")[0]
        else:
            entry["le"] = line_of(max(m.start, m.end - 1))
            entry["t"] = text[m.start : m.start + 15].split("\n")[0]
        if not entry["t"].strip():
            continue
        out.append(entry)
    if lei_end is not None:
        tail = text[lei_end:]
        if tail.strip():
            start = lei_end + (len(tail) - len(tail.lstrip()))
            end = lei_end + len(tail.rstrip())
            out.append(
                {
                    "l": line_of(start),
                    "k": "fecho",
                    "c": col_of(start),
                    "t": text[start : start + 15].split("\n")[0],
                    "n": None,
                    "s": None,
                    "le": line_of(end - 1),
                    "x": False,
                    "e": None,
                    "nota": None,
                }
            )
    out.sort(key=lambda e: (e["l"], e["c"]))
    return {"id": rid, "marks": out}


# --------------------------------------------------------------------------
# Rendering, chunking and packing
# --------------------------------------------------------------------------


@dataclass
class MarkNorm:
    ref: tb.NormRef
    texto_id: str
    text: str
    text_sha256: str
    lines: List[str]
    chunks: List[tb.Chunk]
    expected_marks: int = 0
    # Set on a synthetic re-flowed variant (see ``reflow_text``): the base norm's
    # ``texto_id``/sha256 and the offsets of the newlines that were joined.
    reflow: Optional[Dict[str, Any]] = None


@dataclass
class MarkSlot:
    norm: MarkNorm
    chunk: tb.Chunk
    rid: str = ""
    size: int = 0


@dataclass
class MarkRequest:
    custom_id: str
    slots: List[MarkSlot]
    user_text: str
    max_tokens: int


@dataclass
class MarkPlan:
    requests: List[MarkRequest] = field(default_factory=list)
    norms: List[MarkNorm] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)
    selection: Dict[str, Any] = field(default_factory=dict)
    empty: List[str] = field(default_factory=list)
    packing: Dict[str, Any] = field(default_factory=dict)
    canary_notes: List[str] = field(default_factory=list)


def expected_marks(text: str) -> int:
    """A priori count of the marks a model will give: the reader's devices, plus the
    blocks of a typical norm (epígrafe, ementa, preâmbulo, fecho, assinatura) and a
    ``ruido`` per ~60 lines."""
    report = read_hierarchy(text)
    reader = sum(1 for n in report["nodes"] if n["kind"] in marcacao._KIND)
    quoted = len(report["quoted_blocks"])
    return reader + quoted + 5 + math.ceil(len(text.split("\n")) / 60)


REFLOW_SUFFIX = "~reflow"
REFLOW_MIN_CHARS = 200
REFLOW_MAX_CHARS = 400


def reflow_text(text: str, key: str) -> tuple[str, List[int]]:
    """The stress variant of ``text``: lines joined into long lines.

    Each joined newline becomes ONE space, so the variant has the length of ``text``
    and every offset (the reader's marker offsets included) is the same in both;
    ``joined`` lists the offsets of the replaced newlines, which is all that is needed
    to get ``text`` back. A run of non-blank lines (and the blank lines between them,
    which in these OCR texts only space the lines out) is joined while the line is
    shorter than a target drawn from [REFLOW_MIN_CHARS, REFLOW_MAX_CHARS] (seeded by
    ``key``) and stays within REFLOW_MAX_CHARS. Markers then fall at arbitrary columns,
    after accents and punctuation. Synthetic: nothing in the corpus looks like this.
    """
    rng = random.Random(hashlib.sha256(key.encode("utf-8")).hexdigest())
    lines = text.split("\n")
    starts = _line_starts(lines)
    content = [i for i, line in enumerate(lines) if line.strip()]
    out = list(text)
    joined: List[int] = []
    if not content:
        return text, joined
    group_start = starts[content[0]]
    target = rng.randint(REFLOW_MIN_CHARS, REFLOW_MAX_CHARS)
    for prev, nxt in zip(content, content[1:]):
        end = starts[nxt] + len(lines[nxt])
        if starts[prev] + len(lines[prev]) - group_start < target and (
            end - group_start <= REFLOW_MAX_CHARS
        ):
            for k in range(prev, nxt):
                offset = starts[k] + len(lines[k])
                out[offset] = " "
                joined.append(offset)
        else:
            group_start = starts[nxt]
            target = rng.randint(REFLOW_MIN_CHARS, REFLOW_MAX_CHARS)
    return "".join(out), joined


def unflow_text(text: str, joined: Sequence[int]) -> str:
    """The base text of a re-flowed variant (``reflow_text`` backwards)."""
    chars = list(text)
    for offset in joined:
        chars[offset] = "\n"
    return "".join(chars)


def reflow_record(record: tb.TextoRecord) -> tuple[tb.TextoRecord, Dict[str, Any]]:
    """The synthetic variant of a text-layer record, with its own ``texto_id``
    (``BASE~reflow``), uuid5 (``…-reflow``) and sha256, and the metadata that maps it to the base."""
    text, joined = reflow_text(record.text, str(record.texto_id))
    ref = dataclasses.replace(record.ref, uuid5=record.ref.uuid5 + "-reflow")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    variant = dataclasses.replace(
        record,
        ref=ref,
        text=text,
        text_sha256=sha,
        texto_id=str(record.texto_id) + REFLOW_SUFFIX,
    )
    meta = {
        "base_texto_id": record.texto_id,
        "base_text_sha256": record.text_sha256,
        "joined": joined,
        "synthetic": True,
    }
    return variant, meta


def make_norm(
    record: tb.TextoRecord,
    *,
    max_lines: int = MARK_MAX_LINES,
    max_chars: int = MARK_MAX_CHARS,
    reflow: Optional[Dict[str, Any]] = None,
) -> MarkNorm:
    lines = tb.split_lines(record.text)
    base_text = unflow_text(record.text, reflow["joined"]) if reflow else record.text
    return MarkNorm(
        ref=record.ref,
        texto_id=str(record.texto_id),
        text=record.text,
        text_sha256=record.text_sha256,
        lines=lines,
        chunks=tb.chunk_document(lines, max_lines=max_lines, max_chars=max_chars),
        expected_marks=expected_marks(base_text),
        reflow=reflow,
    )


def render_slot(slot: MarkSlot) -> str:
    norm, chunk = slot.norm, slot.chunk
    nonblank = sum(1 for ln in norm.lines if ln.strip())
    head = f"### {slot.rid} | {norm.ref.tipo} {norm.ref.numero} | {nonblank} linhas"
    parts: List[str] = []
    if chunk.total > 1:
        head += f" | parte {chunk.index + 1}/{chunk.total}"
        parts.append(
            f"[parte {chunk.index + 1}/{chunk.total}: marque somente as linhas "
            f"{chunk.first_line} a {chunk.last_line}. Um dispositivo ou um bloco "
            "citado pode ter começado antes: veja o contexto.]"
        )
        shown = [*chunk.head, *chunk.context]
        if shown:
            parts.append(
                "[contexto, somente leitura]\n"
                + tb._numbered(norm.lines, shown)
                + "\n[linhas a marcar]"
            )
    parts.append(tb._numbered(norm.lines, chunk.owned))
    return "\n".join([head, *parts, f"### fim {slot.rid}"])


def render_request(slots: Sequence[MarkSlot]) -> str:
    ids = ", ".join(s.rid for s in slots)
    intro = (
        f"Requisição com {len(slots)} norma(s): {ids}. Responda com uma entrada em "
        "`norms` para cada id, exatamente uma vez."
    )
    return "\n\n".join([intro, *(render_slot(s) for s in slots)])


def _slot_marks(slot: MarkSlot) -> int:
    """Marks the ceiling allows for a slot: one per shown line, and for a re-flowed
    variant (many marks on a line) the base norm's expected count for its share."""
    shown = len(slot.chunk.owned)
    norm = slot.norm
    if norm.reflow:
        share = norm.expected_marks * shown // max(1, len(norm.lines))
        return max(shown, int(share * 1.5))
    return shown


def mark_max_tokens(
    slots: Sequence[MarkSlot], cap: int = MARK_MAX_TOKENS_CAP, factor: float = 1.0
) -> int:
    """``max_tokens`` of a mark request: a base, then per norm the thinking room and a
    mark on every shown line at the per-mark ceiling, never above the cap."""
    per_norm = sum(
        MARK_THINKING_PER_NORM + TOKENS_PER_MARK * _slot_marks(s) for s in slots
    )
    return min(
        min(cap, MARK_MAX_TOKENS_CAP), int((MARK_MAX_TOKENS_BASE + per_norm) * factor)
    )


def pack_slots(
    slots: Sequence[MarkSlot],
    *,
    budget_chars: int = DEFAULT_MARK_BUDGET_CHARS,
    max_norms: int = DEFAULT_MARK_MAX_NORMS,
    seed: str = "0",
) -> List[List[MarkSlot]]:
    """Group slots into requests by size, deterministic given ``seed``. Every part of a
    chunked norm, and a slot above the budget, goes alone; the rest are packed greedily
    in a seeded order (a request closes at ``budget_chars`` or ``max_norms``)."""
    if budget_chars < 1 or max_norms < 1:
        raise ValueError("budget_chars and max_norms must be positive")
    ordered = sorted(
        slots, key=lambda s: (tr._hash_key(seed, s.norm.ref.key), s.chunk.index)
    )
    requests: List[List[MarkSlot]] = []
    current: List[MarkSlot] = []
    chars = 0
    for slot in ordered:
        if slot.chunk.total > 1 or slot.size > budget_chars:
            requests.append([slot])
            continue
        if current and (len(current) >= max_norms or chars + slot.size > budget_chars):
            requests.append(current)
            current, chars = [], 0
        current.append(slot)
        chars += slot.size
    if current:
        requests.append(current)
    return requests


def build_mark_plan(
    records: Sequence[tb.TextoRecord],
    *,
    seed: str = "0",
    budget_chars: int = DEFAULT_MARK_BUDGET_CHARS,
    max_norms: int = DEFAULT_MARK_MAX_NORMS,
    max_lines: int = MARK_MAX_LINES,
    max_chars: int = MARK_MAX_CHARS,
    max_tokens_cap: int = MARK_MAX_TOKENS_CAP,
    reflows: Optional[Dict[str, Dict[str, Any]]] = None,
) -> MarkPlan:
    plan = MarkPlan()
    for record in records:
        norm = make_norm(
            record,
            max_lines=max_lines,
            max_chars=max_chars,
            reflow=(reflows or {}).get(record.ref.key),
        )
        if not norm.chunks:
            plan.empty.append(record.ref.key)
            continue
        plan.norms.append(norm)
    slots: List[MarkSlot] = []
    for norm in plan.norms:
        for chunk in norm.chunks:
            slot = MarkSlot(norm=norm, chunk=chunk, rid="N01")
            slot.size = len(render_slot(slot))
            slots.append(slot)
    for index, group in enumerate(
        pack_slots(slots, budget_chars=budget_chars, max_norms=max_norms, seed=seed)
    ):
        for position, slot in enumerate(group, 1):
            slot.rid = f"N{position:02d}"
        custom_id = f"m{index:05d}"
        plan.requests.append(
            MarkRequest(
                custom_id=custom_id,
                slots=group,
                user_text=render_request(group),
                max_tokens=mark_max_tokens(group, max_tokens_cap),
            )
        )
    plan.packing = {
        "budget_chars": budget_chars,
        "max_norms": max_norms,
        "max_lines": max_lines,
        "max_chars": max_chars,
        "seed": seed,
    }
    return plan


# --------------------------------------------------------------------------
# Requests and cost
# --------------------------------------------------------------------------


def build_mark_params(
    req: MarkRequest, spec: tb.ModelSpec, effort: str, cache: bool
) -> Dict[str, Any]:
    """Messages API params for one mark request (see ``tb.build_request_params``)."""
    system_block: Dict[str, Any] = {"type": "text", "text": MARK_SYSTEM_PROMPT}
    if cache:
        system_block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    output_config: Dict[str, Any] = {
        "format": {"type": "json_schema", "schema": MARK_SCHEMA}
    }
    if spec.supports_effort:
        output_config["effort"] = effort
    return {
        "model": spec.model,
        "max_tokens": req.max_tokens,
        "system": [system_block],
        "messages": [{"role": "user", "content": req.user_text}],
        "output_config": output_config,
    }


def estimate_mark_cost(
    plan: MarkPlan,
    spec: tb.ModelSpec,
    effort: str,
    cache: bool,
    chars_per_token: float = tb.CHARS_PER_TOKEN,
) -> tb.CostEstimate:
    """The two numbers of ``tb.estimate_cost`` with the mark output model.

    Estimate: per request a base (the review mode's measured thinking, 2070 tokens at
    effort medium, or the thinking table when larger: the mark mode has no
    measurement yet, the pilot's ``summary.json`` gives the first), plus per norm the
    reader's mark count a priori (``expected_marks``) at ``EST_TOKENS_PER_MARK``,
    capped by each request's ``max_tokens``. Ceiling: every request spends its whole
    ``max_tokens`` (a mark on every shown line at ``TOKENS_PER_MARK`` plus thinking
    room), with the 1-hour cache write on the prefix and zero hits.
    """
    system_tokens = tb.estimate_tokens(len(MARK_SYSTEM_PROMPT), chars_per_token)
    n = len(plan.requests)
    user_tokens = [
        tb.estimate_tokens(len(r.user_text), chars_per_token)
        + tb.REQUEST_OVERHEAD_TOKENS
        for r in plan.requests
    ]
    input_tokens = sum(user_tokens) + system_tokens * n
    if spec.supports_effort:
        base_out = max(
            MARK_BASE_OUTPUT_TOKENS, tb.THINKING_ESTIMATE[effort] + MARK_FRAMING_TOKENS
        )
    else:
        base_out = MARK_BASE_OUTPUT_TOKENS
    est_out = 0
    for r in plan.requests:
        marks = sum(
            s.norm.expected_marks * len(s.chunk.owned) // max(1, len(s.norm.lines))
            if s.chunk.total > 1
            else s.norm.expected_marks
            for s in r.slots
        )
        est_out += min(r.max_tokens, base_out + EST_TOKENS_PER_MARK * marks)
    ceil_out = sum(r.max_tokens for r in plan.requests)
    in_price = spec.input_usd_mtok * tb.BATCH_DISCOUNT / 1e6
    out_price = spec.output_usd_mtok * tb.BATCH_DISCOUNT / 1e6
    system_mult = tb.CACHE_WRITE_1H_MULT if cache else 1.0
    estimate = input_tokens * in_price + est_out * out_price
    ceiling = (
        sum(user_tokens) * in_price
        + system_tokens * n * in_price * system_mult
        + ceil_out * out_price
    )
    return tb.CostEstimate(
        model=spec.model,
        effort=effort if spec.supports_effort else None,
        requests=n,
        norms=len(plan.norms),
        chars_per_token=chars_per_token,
        system_tokens=system_tokens,
        input_tokens=input_tokens,
        estimated_output_tokens=est_out,
        ceiling_output_tokens=ceil_out,
        estimate_usd=round(estimate, 4),
        ceiling_usd=round(ceiling, 4),
        max_request_input_tokens=(max(user_tokens) + system_tokens) if n else 0,
    )


def label_mode_estimate(
    plan: MarkPlan, spec: tb.ModelSpec, effort: str, cache: bool
) -> tb.CostEstimate:
    """What the label mode would cost for the same norms."""
    texts = {n.ref.key: n.text for n in plan.norms}
    label_plan = tb.build_plan([n.ref for n in plan.norms], lambda r: texts[r.key])
    return tb.estimate_cost(label_plan, spec, effort, cache)


def count_tokens_sample_mark(
    client: Any, plan: MarkPlan, spec: tb.ModelSpec, effort: str, sample: int
) -> Optional[Dict[str, Any]]:
    """Measure real input tokens on a deterministic sample (free endpoint)."""
    if sample <= 0 or not plan.requests:
        return None
    step = max(1, len(plan.requests) // sample)
    picked = plan.requests[::step][:sample]
    chars = tokens = 0
    for req in picked:
        params = build_mark_params(req, spec, effort, cache=False)
        counted = client.messages.count_tokens(
            model=params["model"],
            system=params["system"],
            messages=params["messages"],
            output_config=params["output_config"],
        )
        tokens += int(counted.input_tokens)
        chars += len(MARK_SYSTEM_PROMPT) + len(req.user_text)
    return {
        "model": spec.model,
        "sampled_requests": len(picked),
        "chars": chars,
        "input_tokens": tokens,
        "measured_chars_per_token": round(chars / tokens, 4) if tokens else None,
        "assumed_chars_per_token": tb.CHARS_PER_TOKEN,
    }


# --------------------------------------------------------------------------
# Manifest and submit
# --------------------------------------------------------------------------


def _pack_text(text: str) -> str:
    return base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")


def _unpack_text(blob: str) -> str:
    return zlib.decompress(base64.b64decode(blob)).decode("utf-8")


def _slot_meta(slot: MarkSlot) -> Dict[str, Any]:
    norm, chunk = slot.norm, slot.chunk
    ref = norm.ref
    return {
        "entry": ref.key,
        "key": ref.key,
        "texto_id": norm.texto_id,
        "item": ref.item,
        "fonte": ref.fonte,
        "tipo": ref.tipo,
        "numero": ref.numero,
        "uuid5": ref.uuid5,
        "txt_name": ref.txt_name,
        "text_sha256": norm.text_sha256,
        "n_lines": len(norm.lines),
        "chunk": chunk.index,
        "chunks": chunk.total,
        "first_line": chunk.first_line,
        "last_line": chunk.last_line,
        "owned": list(chunk.owned),
        "reflow": norm.reflow,
    }


def build_mark_manifest(
    plan: MarkPlan,
    estimate: tb.CostEstimate,
    *,
    ente: str,
    effort: Optional[str],
    cache: bool,
    max_usd: float,
    guard: str,
    label_set: str = DEFAULT_MARK_LABEL_SET,
) -> Dict[str, Any]:
    used = {s.norm.text_sha256: s.norm.text for r in plan.requests for s in r.slots}
    return {
        "manifest_version": tb.MANIFEST_VERSION,
        "mode": MODE,
        "created_at": tb._now(),
        "ente": ente,
        "label_set": label_set,
        "sources": plan.sources,
        "selection": plan.selection,
        "packing": plan.packing,
        "model": estimate.model,
        "effort": effort,
        "prompt_cache": cache,
        "prompt_version": MARK_PROMPT_VERSION,
        "prompt_sha256": mark_prompt_sha256(),
        "mark_schema_version": MARK_SCHEMA_VERSION,
        "git_sha": tb.git_sha(),
        "max_usd": max_usd,
        "guard": guard,
        "estimate": estimate.to_dict(),
        "empty": list(plan.empty),
        "batches": [],
        "texts": {sha: _pack_text(text) for sha, text in used.items()},
        "requests": {
            r.custom_id: {
                "max_tokens": r.max_tokens,
                "slots": {s.rid: _slot_meta(s) for s in r.slots},
            }
            for r in plan.requests
        },
    }


def submit_mark_batches(
    client: Any,
    plan: MarkPlan,
    spec: tb.ModelSpec,
    manifest: Dict[str, Any],
    manifest_path: Path,
    *,
    effort: str,
    cache: bool,
    max_requests: int = tb.DEFAULT_REQUESTS_PER_BATCH,
    max_bytes: int = tb.DEFAULT_BYTES_PER_BATCH,
) -> Dict[str, Any]:
    """Create the batch(es); the manifest is rewritten after each creation."""
    requests: List[Dict[str, Any]] = [
        {
            "custom_id": req.custom_id,
            "params": build_mark_params(req, spec, effort, cache),
        }
        for req in plan.requests
    ]
    groups = tb.split_batches(requests, max_requests, max_bytes)
    tb.write_json(manifest_path, manifest)
    for group in groups:
        batch = client.messages.batches.create(requests=group)
        manifest["batches"].append(
            {
                "id": batch.id,
                "created_at": tb._now(),
                "request_count": len(group),
                "custom_ids": [r["custom_id"] for r in group],
            }
        )
        tb.write_json(manifest_path, manifest)
    return manifest


def build_retry_plan(
    plan: MarkPlan, base: Dict[str, Any], *, depth: int, max_tokens_cap: int
) -> MarkPlan:
    """Requests that retry the truncated slots of ``base``: one norm (or part) per
    request, with the budget raised by ``RETRY_BUDGET_FACTOR`` (within the cap). The
    plan must come from the same inputs as the original submit: every slot is matched
    by ``(entry, part)`` and its text sha256 checked."""
    cids = base.get("truncated_requests")
    if cids is None:
        raise tb.TeacherBatchError(
            "the previous manifest has no truncated_requests: collect it with this "
            "code first"
        )
    if not cids:
        raise tb.TeacherBatchError("no truncated requests in the previous run")
    wanted: Dict[tuple[str, int], Dict[str, Any]] = {}
    for cid in sorted(cids):
        for meta in base["requests"][cid]["slots"].values():
            wanted[(str(meta["entry"]), int(meta["chunk"]))] = meta
    index = {(n.ref.key, c.index): (n, c) for n in plan.norms for c in n.chunks}
    absent = sorted(k for k in wanted if k not in index)
    if absent:
        raise tb.TeacherBatchError(
            f"{len(absent)} truncated parts are not in this plan (first "
            f"{absent[:3]}): use the same inputs as the original submit"
        )
    requests: List[MarkRequest] = []
    for i, key in enumerate(sorted(wanted)):
        meta = wanted[key]
        norm, chunk = index[key]
        if norm.text_sha256 != meta["text_sha256"]:
            raise tb.TeacherBatchError(
                f"{key[0]}: the text changed since the original submit; retry refused"
            )
        slot = MarkSlot(norm=norm, chunk=chunk, rid="N01")
        slot.size = len(render_slot(slot))
        requests.append(
            MarkRequest(
                custom_id=f"t{depth}-{i:05d}",
                slots=[slot],
                user_text=render_request([slot]),
                max_tokens=mark_max_tokens(
                    [slot], max_tokens_cap, factor=RETRY_BUDGET_FACTOR
                ),
            )
        )
    return MarkPlan(
        requests=requests,
        norms=plan.norms,
        sources=plan.sources,
        selection=plan.selection,
        empty=list(plan.empty),
        packing=plan.packing,
    )


# --------------------------------------------------------------------------
# Collect
# --------------------------------------------------------------------------


def interpret_mark_result(entry: Any) -> tr.ReviewRequestOutcome:
    """One batch result line -> the answered entries or a failure reason."""
    custom_id = str(tb._get(entry, "custom_id"))
    result = tb._get(entry, "result")
    result_type = tb._get(result, "type")
    if result_type != "succeeded":
        error = tb._get(result, "error")
        detail = None
        if error is not None:
            inner = tb._get(error, "error", error)
            detail = f"{tb._get(inner, 'type')}: {tb._get(inner, 'message')}"
        return tr.ReviewRequestOutcome(
            custom_id, False, f"result_{result_type}", detail
        )
    message = tb._get(result, "message")
    usage = tb._usage_dict(tb._get(message, "usage"))
    stop_reason = tb._get(message, "stop_reason")
    outcome = tr.ReviewRequestOutcome(
        custom_id, False, stop_reason=stop_reason, usage=usage
    )
    if stop_reason != "end_turn":
        outcome.reason = f"stop_reason_{stop_reason}"
        outcome.truncated = stop_reason == "max_tokens"
        return outcome
    text = next(
        (
            tb._get(block, "text")
            for block in (tb._get(message, "content") or [])
            if tb._get(block, "type") == "text"
        ),
        None,
    )
    if not isinstance(text, str) or not text.strip():
        outcome.reason = "no_text_block"
        outcome.truncated = True
        return outcome
    body = text.strip()
    fenced = tb._FENCE_RE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        outcome.reason = "invalid_json"
        outcome.detail = str(exc)
        return outcome
    if (
        not isinstance(payload, dict)
        or set(payload) != {"norms"}
        or not isinstance(payload["norms"], list)
    ):
        outcome.reason = "schema_violation"
        outcome.detail = "payload is not {norms: [...]}"
        return outcome
    outcome.ok = True
    outcome.entries = payload["norms"]
    return outcome


@dataclass
class MarkSlotResult:
    """One (norm, part) slot of a request, with its answered marks."""

    rid: str
    custom_id: str
    meta: Dict[str, Any]
    valid: bool
    marks: List[Any] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    truncated: bool = False


def evaluate_mark_request(
    custom_id: str,
    request_meta: Dict[str, Any],
    outcome: Optional[tr.ReviewRequestOutcome],
) -> tuple[List[MarkSlotResult], List[str]]:
    """Every id of one request answered exactly once; silence is never accepted."""
    results: List[MarkSlotResult] = []
    slots: Dict[str, Dict[str, Any]] = request_meta["slots"]
    if outcome is None or not outcome.ok:
        reason = "missing_result" if outcome is None else str(outcome.reason)
        cut = outcome is not None and outcome.truncated
        for rid, meta in slots.items():
            results.append(
                MarkSlotResult(
                    rid, custom_id, meta, False, problems=[reason], truncated=cut
                )
            )
        return results, []
    by_id: Dict[str, List[Any]] = {}
    for entry in outcome.entries:
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        by_id.setdefault(
            entry_id if isinstance(entry_id, str) else "<no id>", []
        ).append(entry)
    extra = sorted(k for k in by_id if k not in slots)
    for rid, meta in slots.items():
        found = by_id.get(rid, [])
        if not found:
            results.append(
                MarkSlotResult(rid, custom_id, meta, False, problems=["missing_id"])
            )
        elif len(found) > 1:
            results.append(
                MarkSlotResult(rid, custom_id, meta, False, problems=["duplicate_id"])
            )
        else:
            entry = found[0]
            if (
                not isinstance(entry, dict)
                or set(entry) != {"id", "marks"}
                or not isinstance(entry["marks"], list)
            ):
                results.append(
                    MarkSlotResult(
                        rid, custom_id, meta, False, problems=["wrong shape"]
                    )
                )
            else:
                results.append(
                    MarkSlotResult(rid, custom_id, meta, True, marks=entry["marks"])
                )
    return results, extra


@dataclass
class NormResult:
    """One norm after merging its parts and converting."""

    state: str
    conv: Optional[Conversion]
    problems: List[str]
    missing_parts: List[Dict[str, Any]]
    n_marks_answered: int


def _merge_and_convert(
    results: List[MarkSlotResult], text: str, ref: Dict[str, Any]
) -> NormResult:
    results.sort(key=lambda r: int(r.meta["chunk"]))
    valid = [r for r in results if r.valid]
    missing = [
        {
            "part": int(r.meta["chunk"]) + 1,
            "status": "truncated" if r.truncated else "invalid",
            "problems": list(r.problems),
        }
        for r in results
        if not r.valid
    ]
    problems = [
        f"part {m['part']}: {p}"
        for m in missing
        for p in cast(List[str], m["problems"])
    ]
    if not valid:
        state = "truncated" if all(r.truncated for r in results) else "invalid"
        return NormResult(state, None, problems, missing, 0)
    marks = [m for r in valid for m in r.marks]
    owned: set[int] = set()
    for r in valid:
        owned.update(int(n) for n in r.meta["owned"])
    conv = convert_response(
        text,
        marks,
        texto_id=str(ref["texto_id"]),
        tipo=str(ref["tipo"]),
        numero=ref["numero"],
        owned=owned,
    )
    if conv.xml is None:
        return NormResult(
            "build_failed", conv, conv.verify_problems, missing, len(marks)
        )
    if missing:
        return NormResult("partial", conv, problems, missing, len(marks))
    state = "degraded" if conv.problems else "ok"
    return NormResult(state, conv, [], [], len(marks))


def _all_texts(manifest: Dict[str, Any]) -> Dict[str, str]:
    """The packed texts of a manifest and of the bases it retries."""
    texts: Dict[str, str] = {}
    base = manifest.get("base")
    if base is not None:
        texts.update(_all_texts(base))
    texts.update(manifest.get("texts", {}))
    return texts


def _dropped_reason(text: str) -> str:
    return re.sub(r"\d+", "N", text)[:60]


def collect_mark(
    client: Any, manifest: Dict[str, Any], out_dir: Path
) -> Dict[str, Any]:
    """Fetch, convert, build and write ``marked/``, ``records/``, ``anchors.jsonl``.
    Assumes ended batches. A retry manifest (``base``) is merged first."""
    packed = _all_texts(manifest)
    manifest = tr.combine_manifests(manifest)
    manifest["texts"] = packed
    spec = tb.resolve_model(manifest["model"])
    requests: Dict[str, Dict[str, Any]] = manifest["requests"]
    superseded = set(manifest.get("superseded", []))
    submitted = {cid for b in manifest["batches"] for cid in b["custom_ids"]}
    texts = {sha: _unpack_text(blob) for sha, blob in packed.items()}
    outcomes: Dict[str, tr.ReviewRequestOutcome] = {}
    unknown_ids: List[str] = []
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for batch in manifest["batches"]:
        with (raw_dir / f"{batch['id']}.jsonl").open("w", encoding="utf-8") as raw:
            for entry in client.messages.batches.results(batch["id"]):
                dumped = entry.to_dict() if hasattr(entry, "to_dict") else entry
                raw.write(json.dumps(dumped, ensure_ascii=False, default=str) + "\n")
                custom_id = str(tb._get(entry, "custom_id"))
                if custom_id in superseded:
                    continue
                if custom_id not in requests:
                    unknown_ids.append(custom_id)
                    continue
                outcomes[custom_id] = interpret_mark_result(entry)
    provenance = {
        "mode": MODE,
        "label_set": manifest.get("label_set", DEFAULT_MARK_LABEL_SET),
        "model": manifest["model"],
        "effort": manifest.get("effort"),
        "prompt_version": manifest["prompt_version"],
        "prompt_sha256": manifest["prompt_sha256"],
        "mark_schema_version": manifest["mark_schema_version"],
        "git_sha": manifest.get("git_sha"),
        "collected_git_sha": tb.git_sha(),
        "batch_ids": [b["id"] for b in manifest["batches"]],
    }
    usage_total = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for outcome in outcomes.values():
        for name, value in outcome.usage.items():
            usage_total[name] = usage_total.get(name, 0) + value

    by_entry: Dict[str, List[MarkSlotResult]] = {}
    request_extra: Dict[str, List[str]] = {}
    for custom_id, meta in requests.items():
        found = outcomes.get(custom_id)
        if found is None and custom_id not in submitted:
            found = tr.ReviewRequestOutcome(custom_id, False, "not_submitted")
        slot_results, extra = evaluate_mark_request(custom_id, meta, found)
        if extra:
            request_extra[custom_id] = extra
        for r in slot_results:
            by_entry.setdefault(str(r.meta["entry"]), []).append(r)

    counts = {s: 0 for s in STATES}
    dropped_reasons: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    failures: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = {}
    marks_answered = marks_used = marks_dropped = 0
    anchor_rows = 0
    suspect_counts: Dict[str, int] = {}
    suspect_norms: List[str] = []
    anchors_used: Dict[str, int] = {}
    with (out_dir / "anchors.jsonl").open("w", encoding="utf-8") as anchors_file:
        for entry_key, results in sorted(by_entry.items()):
            first = results[0].meta
            text = texts[first["text_sha256"]]
            nr = _merge_and_convert(results, text, first)
            counts[nr.state] += 1
            request_ids = sorted({r.custom_id for r in results})
            conv = nr.conv
            dropped = conv.problems if conv else []
            record: Dict[str, Any] = {
                "record": "mark",
                "ente": manifest["ente"],
                "texto_id": first["texto_id"],
                "key": first["key"],
                "item": first["item"],
                "uuid5": first["uuid5"],
                "tipo": first["tipo"],
                "numero": first["numero"],
                "txt_name": first["txt_name"],
                "text_sha256": first["text_sha256"],
                "n_lines": first["n_lines"],
                "reflow": first.get("reflow"),
                "state": nr.state,
                "marks_answered": nr.n_marks_answered,
                "marks_used": sum(1 for a in conv.anchors if a.get("used"))
                if conv
                else 0,
                "dropped": dropped,
                "verify_problems": conv.verify_problems if conv else [],
                "suspects": conv.suspects if conv else [],
                "invalid_reasons": nr.problems,
                "partial": nr.state == "partial",
                "missing_parts": nr.missing_parts,
                "request_ids": request_ids,
                **provenance,
            }
            stem = f"{first['tipo']}-{int(first['numero']):05d}_{first['uuid5']}"
            rec_path = out_dir / "records" / str(first["item"]) / f"{stem}.json"
            rec_path.parent.mkdir(parents=True, exist_ok=True)
            rec_path.write_text(
                json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            if conv is not None and conv.xml is not None:
                xml_path = out_dir / "marked" / str(first["item"]) / f"{stem}.xml"
                xml_path.parent.mkdir(parents=True, exist_ok=True)
                xml_path.write_text(conv.xml, encoding="utf-8")
            if conv is not None:
                for sus in conv.suspects:
                    kind = str(sus["type"])
                    suspect_counts[kind] = suspect_counts.get(kind, 0) + 1
                if conv.suspects:
                    suspect_norms.append(str(first["texto_id"]))
                for row in conv.anchors:
                    anchor_rows += 1
                    anchors_file.write(
                        json.dumps(
                            {
                                "norm": first["key"],
                                "texto_id": first["texto_id"],
                                **row,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    marks_answered += 1
                    if row.get("used"):
                        anchors_used[str(row["used"])] = (
                            anchors_used.get(str(row["used"]), 0) + 1
                        )
                        marks_used += 1
                        kind_counts[str(row["kind"])] = (
                            kind_counts.get(str(row["kind"]), 0) + 1
                        )
                    else:
                        marks_dropped += 1
                for d in conv.problems:
                    why = _dropped_reason(str(d["reason"]))
                    dropped_reasons[why] = dropped_reasons.get(why, 0) + 1
            if nr.state in ("invalid", "truncated", "partial", "build_failed"):
                failures.append(
                    {
                        "key": first["key"],
                        "entry": entry_key,
                        "texto_id": first["texto_id"],
                        "request_ids": request_ids,
                        "state": nr.state,
                        "problems": nr.problems[:10],
                        "missing_parts": nr.missing_parts,
                    }
                )
                if nr.state == "truncated":
                    reasons["truncated"] = reasons.get("truncated", 0) + 1
                for part in nr.missing_parts:
                    if part["status"] == "truncated":
                        reasons["truncated_part"] = reasons.get("truncated_part", 0) + 1
                        continue
                    for problem in part["problems"]:
                        why = re.sub(r"\d+", "N", problem)[:60]
                        reasons[why] = reasons.get(why, 0) + 1
                if nr.state in ("invalid", "build_failed"):
                    for problem in nr.problems[:3]:
                        why = re.sub(r"\d+", "N", problem)[:60]
                        reasons[why] = reasons.get(why, 0) + 1
    for custom_id, extra in sorted(request_extra.items()):
        failures.append({"request": custom_id, "unknown_ids_in_answer": extra})
    answered_failures = [
        {"request": cid, "reason": o.reason, "detail": o.detail}
        for cid, o in sorted(outcomes.items())
        if not o.ok and cid not in superseded
    ]
    failures += answered_failures
    with (out_dir / "failures.jsonl").open("w", encoding="utf-8") as fh:
        for failure in failures:
            fh.write(json.dumps(failure, ensure_ascii=False) + "\n")
    measured = tb.measured_cost_usd(
        usage_total, spec, cache_1h=bool(manifest.get("prompt_cache"))
    )
    norms_total = sum(counts.values())
    truncated_requests = sorted(
        cid
        for cid, o in outcomes.items()
        if o.truncated and cid not in superseded and cid in requests
    )
    # The collected manifest keeps no texts (they are in the marked documents).
    slim = {k: v for k, v in manifest.items() if k != "texts"}
    tb.write_json(
        out_dir / "manifest.json",
        {**manifest, "truncated_requests": truncated_requests},
    )
    summary = {
        **provenance,
        "collected_at": tb._now(),
        "ente": manifest["ente"],
        "requests_total": len(requests),
        "requests_with_result": len(outcomes),
        "requests_failed": len(answered_failures),
        "requests_truncated": len(truncated_requests),
        "truncated_requests": truncated_requests,
        "unknown_custom_ids": sorted(unknown_ids),
        "norms_total": norms_total,
        "norms_ok": counts["ok"] + counts["degraded"],
        "norms_failed": counts["invalid"]
        + counts["truncated"]
        + counts["partial"]
        + counts["build_failed"],
        "states": counts,
        "marks_answered": marks_answered,
        "marks_used": marks_used,
        "marks_dropped": marks_dropped,
        "dropped_by_reason": dict(sorted(dropped_reasons.items())),
        "anchors_used": dict(sorted(anchors_used.items())),
        "suspects_by_type": dict(sorted(suspect_counts.items())),
        "norms_with_suspects": sorted(suspect_norms),
        "used_by_kind": dict(sorted(kind_counts.items())),
        "failure_reasons": dict(sorted(reasons.items())),
        "usage": usage_total,
        "measured_usd": measured,
        "measured_usd_per_request": (
            round(measured / len(outcomes), 6) if outcomes else None
        ),
        "measured_usd_per_norm": (
            round(measured / norms_total, 6) if norms_total else None
        ),
        "estimate": slim.get("estimate"),
        "sources": slim.get("sources", {}),
        "selection": slim.get("selection", {}),
        "packing": slim.get("packing", {}),
        "retry": slim.get("retry"),
        "not_marked_at_submit": {"empty": manifest.get("empty", [])},
    }
    tb.write_json(out_dir / "summary.json", summary)
    return summary


def upload_mark_to_ia(
    out_dir: Path, summary: Dict[str, Any], revision: Optional[str] = None
) -> Dict[str, Any]:
    """Upload ``marked/`` and ``records/`` (tar.gz), the anchor table, failures, summary
    and manifest as one IA data item under the label-set naming."""
    ente = str(summary["ente"])
    label_set = str(summary.get("label_set", DEFAULT_MARK_LABEL_SET))
    effective = revision or datetime.now(tz=timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    ia_id = tb.ia_identifier(ente, effective, label_set)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "marked.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for sub in ("marked", "records"):
                if (out_dir / sub).is_dir():
                    tar.add(out_dir / sub, arcname=sub)
        description = (
            f"Documentos marcados pelo professor LLM (modo mark, revisão {effective}, "
            f"conjunto {label_set}) de normas do ente {ente.upper()}, gerados pelo "
            f"projeto Leizilla. {summary['norms_total']} normas. Proveniência em "
            "summary.json; tabela de âncoras em anchors.jsonl."
        )
        args = [
            "ia",
            "upload",
            ia_id,
            str(archive),
            str(out_dir / "anchors.jsonl"),
            str(out_dir / "failures.jsonl"),
            str(out_dir / "summary.json"),
            str(out_dir / "manifest.json"),
            "--metadata",
            f"title:Leizilla Teacher Marks {ente.upper()} [{label_set}] ({effective})",
            "--metadata",
            "mediatype:data",
            "--metadata",
            f"subject:leis;leizilla;{ente};marks;{label_set}",
            "--metadata",
            "creator:leizilla-teacher-batch",
            "--metadata",
            "language:pt",
            "--metadata",
            f"description:{description}",
        ]
        try:
            publisher.InternetArchivePublisher()._run_ia_upload(
                args,
                queue_wait=publisher.IaQueueWait(
                    publisher._DATASET_QUEUE_WAIT_MIN * 60.0
                ),
            )
        except FileNotFoundError:
            return {
                "success": False,
                "ia_id": ia_id,
                "error": "ia CLI não encontrado — instale 'internetarchive'",
            }
        except subprocess.CalledProcessError as exc:
            return {"success": False, "ia_id": ia_id, "error": exc.stderr}
    return {"success": True, "ia_id": ia_id}


# --------------------------------------------------------------------------
# Selection and CLI glue (called from teacher_batch's plan / submit / collect)
# --------------------------------------------------------------------------


def check_mark_label_set(label_set: Optional[str]) -> str:
    name = label_set or DEFAULT_MARK_LABEL_SET
    tb.check_label_set(name)
    if name == tb.DEFAULT_LABEL_SET:
        raise tb.TeacherBatchError(
            "mark runs must not use the 'main' label set (marks are not labels); "
            f"use another name, the default is {DEFAULT_MARK_LABEL_SET!r}"
        )
    return name


def prepare_mark(
    *,
    ente: str,
    tipo: Optional[str],
    limit: Optional[int],
    shuffle_seed: Optional[str],
    text_source: str,
    textos: Optional[Path],
    select: str,
    ids_file: Optional[Path],
    budget_chars: int,
    max_norms: int,
    max_lines: int,
    max_chars: int,
    max_tokens_cap: int,
) -> MarkPlan:
    if text_source != "textos":
        raise tb.TeacherBatchError("mark mode needs --text-source textos")
    if select not in tr.SELECTS:
        raise tb.TeacherBatchError(f"select must be one of {', '.join(tr.SELECTS)}")
    if select == "ids-file" and ids_file is None:
        raise tb.TeacherBatchError("--select ids-file needs --ids-file PATH")
    if select != "ids-file" and ids_file is not None:
        raise tb.TeacherBatchError("--ids-file is only used with --select ids-file")
    seed = shuffle_seed if shuffle_seed is not None else "0"
    corpus = tb._load_textos_corpus(textos)
    by_id = {r.texto_id: r for r in corpus.records if r.texto_id}
    pool = list(corpus.records)
    if tipo:
        wanted = {t.lower() for t in tb._split_csv(tipo) or []}
        pool = [r for r in pool if r.ref.tipo.lower() in wanted]
    selection: Dict[str, Any] = {
        "select": select,
        "texts_in_layer": len(corpus.records),
        "after_tipo": len(pool),
    }
    reflows: Dict[str, Dict[str, Any]] = {}
    if select == "ids-file":
        assert ids_file is not None
        ids = tr.read_ids_file(ids_file)
        # ``ID~reflow``: the synthetic stress variant of a text-layer norm (long lines)
        for variant_id in [i for i in ids if i.endswith(REFLOW_SUFFIX)]:
            base = by_id.get(variant_id[: -len(REFLOW_SUFFIX)])
            if base is None:
                continue
            variant, meta = reflow_record(base)
            by_id[variant_id] = variant
            reflows[variant.ref.key] = meta
            if base in pool:
                pool.append(variant)
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise tb.TeacherBatchError(
                f"{ids_file}: {len(missing)} of {len(ids)} ids are not in the text "
                f"layer (first: {missing[:3]})"
            )
        listed = set(ids)
        pool = [r for r in pool if r.texto_id in listed]
        selection["ids_file"] = {"path": str(ids_file), "ids": len(ids)}
    elif select in ("closed", "open"):
        want_closed = select == "closed"
        pool = [r for r in pool if tr.build_view(r.text).closes == want_closed]
    selected = tb.select_norms(
        [r.ref for r in pool], limit=limit, shuffle_seed=shuffle_seed
    )
    by_key = {r.ref.key: r for r in pool}
    records = [by_key[ref.key] for ref in selected]
    selection["selected"] = len(records)
    plan = build_mark_plan(
        records,
        seed=seed,
        budget_chars=budget_chars,
        max_norms=max_norms,
        max_lines=max_lines,
        max_chars=max_chars,
        max_tokens_cap=max_tokens_cap,
        reflows=reflows,
    )
    plan.selection = selection
    plan.sources = {
        "text_source": "textos",
        "textos": {
            "file_sha256": corpus.file_sha256,
            "texts": len(corpus.records),
            "skipped": corpus.skipped,
        },
    }
    return plan


def plan_summary(plan: MarkPlan) -> Dict[str, Any]:
    sizes = sorted(len(r.slots) for r in plan.requests)
    return {
        "norms": len(plan.norms),
        "requests": len(plan.requests),
        "norms_per_request": {
            "min": sizes[0] if sizes else 0,
            "max": sizes[-1] if sizes else 0,
            "mean": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        },
        "chunked_norms": sum(1 for n in plan.norms if len(n.chunks) > 1),
        "max_parts": max((len(n.chunks) for n in plan.norms), default=0),
        "empty": len(plan.empty),
    }


def echo_mark_plan(plan: MarkPlan) -> None:
    info = plan_summary(plan)
    typer.echo(
        f"mark: {info['norms']} norms in {info['requests']} requests (norms per "
        f"request {info['norms_per_request']}); chunked norms {info['chunked_norms']}"
        f" (max parts {info['max_parts']})"
    )


def echo_mark_estimate(
    estimate: tb.CostEstimate, label_estimate: Optional[tb.CostEstimate]
) -> None:
    tb._echo_estimate(estimate)
    if label_estimate is not None:
        typer.echo(
            f"  same norms in label mode: {label_estimate.requests} requests, "
            f"estimate US${label_estimate.estimate_usd:.2f}, "
            f"ceiling US${label_estimate.ceiling_usd:.2f}"
        )


def finish_collect(
    client: Any,
    manifest: Dict[str, Any],
    out_dir: Path,
    *,
    upload_ia: bool,
    allow_failures: bool,
) -> int:
    """Collect step for a mark manifest; returns the process exit code."""
    summary = collect_mark(client, manifest, out_dir)
    s = summary["states"]
    typer.echo(
        f"{summary['norms_ok']}/{summary['norms_total']} norms marked (ok {s['ok']}, "
        f"degraded {s['degraded']}, partial {s['partial']}, truncated "
        f"{s['truncated']}, invalid {s['invalid']}, build_failed "
        f"{s['build_failed']}); marks used {summary['marks_used']}/"
        f"{summary['marks_answered']}; measured US${summary['measured_usd']:.4f}"
    )
    if upload_ia:
        if summary["norms_total"] == 0:
            typer.echo("nothing to upload", err=True)
        else:
            result = upload_mark_to_ia(out_dir, summary)
            tb.write_json(out_dir / "ia_upload.json", result)
            typer.echo(f"IA upload: {result}")
            if not result["success"]:
                return 2
    if summary["norms_failed"] and not allow_failures:
        return 4
    return 0


def run_plan(
    *,
    specs: Sequence[tb.ModelSpec],
    effort: str,
    prompt_cache: bool,
    count_sample: int = 0,
    out: Optional[Path],
    ente: str,
    label_set: str,
    **kwargs: Any,
) -> MarkPlan:
    """The ``plan`` step in mark mode. Sends nothing billable (the estimate is
    offline)."""
    plan = prepare_mark(ente=ente, **kwargs)
    echo_mark_plan(plan)
    estimates = []
    comparisons = []
    for spec in specs:
        estimate = estimate_mark_cost(plan, spec, effort, prompt_cache)
        label_estimate = label_mode_estimate(plan, spec, effort, prompt_cache)
        estimates.append(estimate)
        comparisons.append(label_estimate)
        echo_mark_estimate(estimate, label_estimate)
    measured: List[Dict[str, Any]] = []
    if count_sample > 0:
        client = tb._client()
        for spec in specs:
            sample = count_tokens_sample_mark(client, plan, spec, effort, count_sample)
            if sample:
                measured.append(sample)
                typer.echo(
                    f"{spec.model}: measured {sample['measured_chars_per_token']} "
                    f"chars/token on {sample['sampled_requests']} requests "
                    f"(estimate assumes {tb.CHARS_PER_TOKEN})"
                )
    if out is not None:
        tb.write_json(
            out,
            {
                "created_at": tb._now(),
                "mode": MODE,
                "ente": ente,
                "label_set": label_set,
                "sources": plan.sources,
                "selection": plan.selection,
                "packing": plan.packing,
                "plan": plan_summary(plan),
                "prompt_version": MARK_PROMPT_VERSION,
                "prompt_sha256": mark_prompt_sha256(),
                "git_sha": tb.git_sha(),
                "estimates": [e.to_dict() for e in estimates],
                "label_mode_estimates": [e.to_dict() for e in comparisons],
                "token_count_samples": measured,
            },
        )
    return plan


def run_submit(
    *,
    spec: tb.ModelSpec,
    manifest_path: Path,
    max_usd: float,
    guard: str,
    effort: str,
    prompt_cache: bool,
    ente: str,
    label_set: str,
    retry_truncated: Optional[Path] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """The ``submit`` step in mark mode: same guard, then the batch(es). With
    ``retry_truncated`` only the truncated slots of that collected manifest are sent
    again, one per request, and ``collect`` merges the two."""
    cap = int(kwargs.get("max_tokens_cap", MARK_MAX_TOKENS_CAP))
    plan = prepare_mark(ente=ente, **kwargs)
    base: Optional[Dict[str, Any]] = None
    depth = 0
    if retry_truncated is not None:
        base = json.loads(Path(retry_truncated).read_text(encoding="utf-8"))
        depth = int(base.get("retry_depth", 0)) + 1
        plan = build_retry_plan(plan, base, depth=depth, max_tokens_cap=cap)
        typer.echo(
            f"retry: {len(base['truncated_requests'])} truncated requests of the "
            f"previous run -> {len(plan.requests)} single-norm requests"
        )
    echo_mark_plan(plan)
    if not plan.requests:
        raise tb.TeacherBatchError("no requests to submit")
    estimate = estimate_mark_cost(plan, spec, effort, prompt_cache)
    echo_mark_estimate(estimate, label_mode_estimate(plan, spec, effort, prompt_cache))
    tb.check_cost_guard(estimate, spec, max_usd, guard)
    manifest = build_mark_manifest(
        plan,
        estimate,
        ente=ente,
        effort=estimate.effort,
        cache=prompt_cache,
        max_usd=max_usd,
        guard=guard,
        label_set=label_set,
    )
    if base is not None:
        tr.attach_retry(manifest, base, depth=depth, plan=cast(Any, plan))
    return submit_mark_batches(
        tb._client(),
        plan,
        spec,
        manifest,
        manifest_path,
        effort=effort,
        cache=prompt_cache,
    )
