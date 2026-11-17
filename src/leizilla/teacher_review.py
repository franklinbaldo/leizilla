"""Review mode of the teacher batch (DAG node ``boundary-decision-parser``).

In ``--mode label`` (``teacher_batch.py``) the model labels every structural line
of every norm from scratch; about 75% of the cost is output tokens. In ``--mode
review`` the rule-based reader (``hierarchy_sequence.read_hierarchy``) reads the
norms first and the model becomes an *auditor* of that reading: it receives the
schema of the reading, SEVERAL norms with the reader's tags already on the lines
where a node starts, and answers with one verdict per norm, ``ok`` or ``ajuste``
with the minimal list of corrections. The model never re-emits the text.

Same three resumable steps and the same cost guard as the label mode; ``submit``
writes a manifest with ``"mode": "review"`` and ``collect`` dispatches on it.

Design notes that are easy to get wrong:

* **The model never has to echo a long identifier.** Each request numbers its norms
  ``N01``..; the manifest maps the token to the real ``texto_id`` and text sha256.
* **Silence is never approval.** Every id of a request must be answered exactly
  once. A missing or duplicated id, a malformed entry, an operation on a line that
  was not listed, or ``ok`` with adjustments make that norm's result INVALID
  (``failures.jsonl``). A single adjustment whose evidence is not on its line, whose
  operation does not fit the tags the model saw, or that changes nothing is DROPPED
  and recorded with its reason; an ``ajuste`` left with nothing is downgraded to
  ``ok`` and flagged. A request that ended at ``max_tokens`` (or had no text) is
  TRUNCATED, not invalid, and can be retried (``--retry-truncated``).
* **Canaries measure attention.** Norms with a PLANTED error in the reader's tags
  (never in the text) are mixed into the requests; ``collect`` scores whether the
  reviewer caught them. A request whose canary was missed marks the ``ok``
  verdicts of its other norms ``unverified``.
* **Nothing is applied.** The valid adjustments of non-canary norms are written as
  a *candidate* errata-style file; no label, errata or reader is changed.
"""

from __future__ import annotations

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast

import typer

from leizilla import publisher
from leizilla import teacher_batch as tb
from leizilla.hierarchy_sequence import (
    _ART_WILD,
    _roman,
    article_closes,
    read_hierarchy,
)

# --------------------------------------------------------------------------
# Contract versions and constants
# --------------------------------------------------------------------------

REVIEW_PROMPT_VERSION = "teacher-review-v3"
REVIEW_SCHEMA_VERSION = "2"
DEFAULT_REVIEW_LABEL_SET = "review"

MODES: tuple[str, ...] = ("label", "review")
SELECTS: tuple[str, ...] = ("all", "closed", "open", "ids-file")

OPS: tuple[str, ...] = (
    "add_own_article",
    "remove_article",
    "set_number",
    "set_quoted",
    "add_node",
    "remove_node",
    "set_node_number",
)
VERDICTS: tuple[str, ...] = ("ok", "ajuste")
SUB_LEVELS: tuple[str, ...] = ("paragrafo", "inciso", "alinea", "item")
ALL_LEVELS: tuple[str, ...] = ("artigo",) + SUB_LEVELS
ARTICLE_OPS: frozenset[str] = frozenset(
    {"add_own_article", "remove_article", "set_number", "set_quoted"}
)
ERRATA_OPS: frozenset[str] = frozenset({"add_own_article", "set_number", "set_quoted"})

CANARY_KINDS: tuple[str, ...] = (
    "drop_last",
    "drop_middle",
    "renumber",
    "flip_quoted",
    "spurious",
)
# The op a reviewer must use to repair each planted error.
CANARY_OP: Dict[str, str] = {
    "drop_last": "add_own_article",
    "drop_middle": "add_own_article",
    "renumber": "set_number",
    "flip_quoted": "set_quoted",
    "spurious": "remove_article",
}

DEFAULT_BUDGET_CHARS = 24_000
DEFAULT_MAX_NORMS = 8
DEFAULT_CANARY_SHARE = 0.15
DEFAULT_REVIEW_MAX_CHARS = tb.DEFAULT_MAX_CHARS
# A norm larger than ``max_chars`` is chunked with the label mode's logic. Run 2 of the
# evaluation (240 requests): 3 hit the 10,705-token ceiling, all single-part requests
# of very long norms (decreto-lei 47: 2,736 lines in 2 parts); thinking grows with the
# lines shown. So a part is also limited in lines (``REVIEW_MAX_LINES`` non-blank
# lines), which turns the longest norms into more, smaller parts.
REVIEW_MAX_LINES = 500
MAX_EVIDENCE_CHARS = 80
MAX_REASON_CHARS = 200
_LINE_STORE_CHARS = 400
_MIN_EVIDENCE = 15

# Output-token model (the plan prints both numbers). ``ok`` entry:
# {"id":"N03","verdict":"ok","adjustments":[]}; one adjustment carries an op, a
# line, an evidence line (<= 80 chars) and a reason (<= 15 words).
TOKENS_PER_OK = 15
TOKENS_PER_ADJUSTMENT = 60
EST_ADJUSTED_SHARE = 0.2
EST_ADJUSTMENTS_PER_ADJUSTED = 2
CEILING_ADJUSTMENTS_PER_NORM = 5
# The ceiling is deliberately not the same as the estimate's unit cost: evidence
# and reason at 2 chars per token, plus the other fields.
CEILING_TOKENS_PER_ADJUSTMENT = 90
RESPONSE_FRAMING_TOKENS = 100
CEILING_TOKENS_PER_NORM = (
    TOKENS_PER_OK + CEILING_ADJUSTMENTS_PER_NORM * CEILING_TOKENS_PER_ADJUSTMENT
)
# Output budget of a review request (2026-11 evaluation, claude-haiku-5-5, effort
# medium). With the old cap (3072 + 465 per norm) 61 of 240 requests ended with
# stop_reason=max_tokens and ~95% of the output was thinking. The new cap is
# base + (thinking room per norm + the per-norm adjustment ceiling), never above
# REVIEW_MAX_TOKENS_CAP. Haiku 5.5 accepts up to 128K output, so the cap is a
# cost guard, not a model limit; ``ModelSpec`` carries no output limit field.
REVIEW_MAX_TOKENS_BASE = 8192
REVIEW_THINKING_PER_NORM = 2048
# Thinking room that grows with the lines a request shows (v3, after run 2).
REVIEW_TOKENS_PER_LINE = 4
# Raised from 16,000 (v3): the cap is a cost guard, not a model limit (Haiku 5.5
# accepts up to 128K output); the ceiling stays the sum of the max_tokens, so it
# stays an upper bound, just a higher one for the longest requests.
REVIEW_MAX_TOKENS_CAP = 32000
# A retried request gets this factor more room per retry depth (a retry at the same
# budget would hit the same ceiling).
RETRY_BUDGET_FACTOR = 1.5
# Measured output of one request, averaged over the 240 requests of the first
# review run (a single measurement, at effort medium, ~1.25 norms per request;
# thinking was ~95% of it). The estimate uses it as the per-request base.
MEASURED_OUTPUT_TOKENS_PER_REQUEST = 2070

_NUMBER_RE = re.compile(r"^\d{1,4}$")
_NUMBER_SUFFIX_RE = re.compile(r"^(\d{1,4})\s*-\s*([A-Za-z])$")
_SUFFIX_RE = re.compile(r"^[A-Za-z]$")
_CITATION_RE = re.compile(r"\b[Aa]rts?\.?\s*(\d{1,4})")
# Evidence comparison: typographic quotes and dashes fold to ASCII, and a tag
# prefix the model copied (``[art 4 Q] ...``) is dropped before comparing.
_QUOTES = {0x201C: '"', 0x201D: '"', 0x2018: "'", 0x2019: "'"}
_DASHES = {0x2013: "-", 0x2014: "-", 0x2212: "-"}
_TAG_PREFIX_RE = re.compile(r"^(\[[^\]]*\]\s*)+")

# --------------------------------------------------------------------------
# Response schema (structured output; same constraints as LABEL_SCHEMA)
# --------------------------------------------------------------------------

_NULLABLE_STRING = tb._NULLABLE_STRING
_NULLABLE_BOOLEAN: Dict[str, Any] = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
_NULLABLE_LEVEL: Dict[str, Any] = {
    "anyOf": [{"type": "string", "enum": list(SUB_LEVELS)}, {"type": "null"}]
}

ADJUSTMENT_FIELDS: tuple[str, ...] = (
    "op",
    "line",
    "number",
    "suffix",
    "level",
    "quoted",
    "evidence",
    "reason",
)

REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "adjustments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": list(OPS)},
                                "line": {"type": "integer"},
                                "number": _NULLABLE_STRING,
                                "suffix": _NULLABLE_STRING,
                                "level": _NULLABLE_LEVEL,
                                "quoted": _NULLABLE_BOOLEAN,
                                "evidence": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": list(ADJUSTMENT_FIELDS),
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "verdict", "adjustments"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}

REVIEW_SYSTEM_PROMPT = """\
Você é um revisor especialista em técnica legislativa brasileira. Um leitor \
automático por regras (o "leitor") já leu a estrutura de normas do Estado de \
Rondônia e marcou, nas linhas em que um dispositivo começa, uma etiqueta com o que \
leu. Sua tarefa é AUDITAR essa leitura: para cada norma, responder `ok` quando a \
leitura está certa, ou `ajuste` com a lista mínima de correções. Você nunca \
reescreve nem devolve o texto da norma.

# Entrada

Cada requisição traz várias normas, ou uma parte de uma norma longa. O texto vem \
de OCR de documentos digitalizados (muitos datilografados nos anos 1980): os sinais \
ordinais e os algarismos saem estragados ("Art. Io" é o artigo 1; "Art. 42" entre \
o 3 e o 5 é o artigo 4; "1Q", "3°", "2-", "Il -" são 1, 3, 2 e o inciso II).

Cada norma começa com uma linha de cabeçalho e termina com `### fim ID`:

`### N03 | lei 123 | reader: 12 own articles`

- `N03` é o identificador da norma NESTA requisição; use-o na resposta, sem \
alterar. `lei 123` é o tipo e o número, só para você se situar.
- `own articles`: quantos artigos próprios o leitor marcou. O cabeçalho não diz se \
a sequência fecha nem qual é o último artigo: leia você mesmo a sequência de \
artigos próprios (1..N, na ordem do texto) e procure a lacuna, o número repetido \
ou a ordem trocada.
- Partes de norma longa trazem `parte 2/3` no cabeçalho e uma nota com o último \
artigo próprio antes da parte e se há bloco citado aberto no início dela. Só as \
linhas de `[linhas a revisar]` podem receber ajuste; `[contexto, somente leitura]` \
serve para se situar.

Cada linha do texto vem como `NÚMERO<TAB>[etiquetas] TEXTO`. Linhas em branco \
foram omitidas, por isso a numeração tem saltos: use sempre o número que \
acompanha a linha, nunca conte linhas. As etiquetas são a leitura do leitor e não \
fazem parte do texto:

- `[art 5]` artigo 5 desta norma (próprio); `[art 5-A]` com sufixo;
- `[§ 2]` parágrafo 2; `[§ único]` parágrafo único;
- `[inc III]` inciso III (romano); `[ali a]` alínea a; `[item 1]` item 1;
- o sufixo ` Q` (`[art 5 Q]`, `[inc II Q]`) marca dispositivo CITADO (em inglês, \
"quoted"): texto de OUTRA norma transcrito por esta (por exemplo, depois de "O \
art. 5º da Lei nº 100 passa a vigorar com a seguinte redação:"). Dispositivos com \
`Q` não pertencem à sequência de artigos desta norma; sem `Q` são próprios;
- a etiqueta aparece antes do texto da linha e aponta para o marcador que \
começa nela, no início ou no meio da linha; uma linha pode ter mais de uma \
etiqueta; linha sem etiqueta é linha em que o leitor não viu dispositivo.
- `[?art]` (sem número) marca uma linha SEM etiqueta que abre com marcador de \
artigo: o leitor viu um possível artigo e não o tomou. Pode ser artigo perdido, \
citação, artigo transcrito ou cabeçalho; decida pela sequência e pelo texto, e \
não trate a marca como erro por si só.

# O que verificar

1. Todo artigo próprio tem etiqueta? Procure linhas que abrem artigo e estão sem \
`[art N]`: "Art." / "Artigo" sem etiqueta, e também a linha cujo marcador o OCR \
destruiu. Uma linha sem etiqueta que abre com `Art. Nº` ou `Artigo N` limpo quase \
sempre é um artigo que o leitor perdeu: verifique cada uma delas. Quando a sequência pede o próximo artigo e a linha abre uma frase \
completa de comando (muito comum: "Esta Lei entra em vigor ...", "Revogam-se as \
disposições em contrário" logo depois do último artigo), ela é um artigo com \
marcador perdido: `add_own_article` com o número que a sequência pede.
2. Alguma etiqueta de artigo está onde não começa artigo? Citações no meio de \
frase ("nos termos do art. 3º", "o art. 5º desta Lei"), cabeçalhos, números de \
página, linhas de tabela e ruído de OCR não abrem dispositivo: `remove_article`. Se o artigo existe mas é \
transcrição de outra norma, não remova: use `set_quoted`.
3. O número da etiqueta é o que a sequência pede? Use os vizinhos para decidir; \
um número que quebra a sequência por culpa do OCR é `set_number`.
4. Próprio ou citado (`Q`)? Um artigo dentro da transcrição de outra lei deve ter `Q`; \
um artigo da própria norma não pode ter. Corrija com `set_quoted`.
5. Parágrafos, incisos, alíneas e itens: só ajuste quando o erro é inequívoco \
(`add_node`, `remove_node`, `set_node_number`). Um número errado numa etiqueta que \
existe (o inciso `II` que a sequência pede como `I`) é `set_node_number`, nunca \
`remove_node` mais `add_node`. Os itens são o nível mais fraco: na dúvida, não ajuste.

Não aponte erro de estilo, de grafia ou de conteúdo. Na dúvida sobre uma linha, \
deixe-a como está: `ok` significa "li as etiquetas e as linhas e não encontrei \
nada certo para mudar". Ajuste só o que você consegue mostrar na própria linha.

# Saída

Responda apenas com o objeto JSON do esquema: `reviews` com UMA entrada para \
CADA norma da requisição, exatamente uma vez cada, na ordem em que aparecem:

`{"id": "N03", "verdict": "ok" | "ajuste", "adjustments": [...]}`

`ok` leva `adjustments` vazio; `ajuste` leva pelo menos um ajuste. Um id que falta, \
um id repetido, um ajuste numa linha que não está listada (ou numa linha \
fora de `[linhas a revisar]`) ou com evidência que não está na linha INVALIDA o \
resultado daquela norma inteira. Cada ajuste tem sempre os oito campos; o que a \
operação não usa vai como `null`:

- `op`, `line`: a operação e o número da linha (o número antes do TAB);
- `evidence`: o texto DESSA linha, copiado como listado (sem o número, sem as \
etiquetas e sem continuar na linha seguinte): os primeiros 80 caracteres da linha, \
no mínimo 15 (ou a linha inteira, se for menor);
- `reason`: no máximo 15 palavras.

Um ajuste cuja evidência não confere com a linha, cuja operação não cabe nas \
etiquetas mostradas ou que não muda nada é DESCARTADO e registrado; os demais \
ajustes da norma continuam valendo. Ainda assim, só responda o que você vê.

Operações e campos usados:

- `add_own_article` (`number`, `suffix`): a linha abre um artigo próprio sem \
etiqueta. `number`: algarismos, sem ordinal ("5"); `suffix`: letra maiúscula do \
"5-A", ou `null`. A linha não pode ter etiqueta de artigo.
- `remove_article` (`number` só se a linha tem duas etiquetas de artigo): a \
etiqueta de artigo não deveria existir. Não combine com outro ajuste na mesma linha.
- `set_number` (`number`, `suffix`): a linha tem exatamente uma etiqueta de \
artigo e o número dela está errado; informe o número certo. Mantenha o algarismo \
impresso na linha, a não ser que um erro de OCR explique a diferença: `Art. 4o` é \
o artigo 4, não o 6.
- `set_quoted` (`quoted`): a linha tem exatamente uma etiqueta de artigo e ela \
está do lado errado: `true` se o artigo é transcrição de outra norma (passa a \
ter `Q`), `false` se é próprio (perde o `Q`).
- `add_node` (`level`, `number`): faltou etiqueta de `paragrafo`, `inciso`, \
`alinea` ou `item` (número opcional: "2", "III", "a", "unico"...).
- `remove_node` (`level`): sobra etiqueta desse nível na linha.
- `set_node_number` (`level`, `number`): a linha tem exatamente uma etiqueta desse \
nível e o número dela está errado; informe o certo ("1", "III", "a", "unico"). É a \
única operação para renumerar um nível inferior.

Não repita a mesma operação na mesma linha.

# Exemplos

Uma requisição com três normas:

```
### N01 | lei 7 | reader: 2 own articles
3\tLEI Nº 7 DE 5 DE ABRIL DE 1985
5\tDispõe sobre a coisa.
7\t[art 1] Art. 1º - Fica criada a coisa, nos termos do art. 9º da Lei Federal.
8\t[art 2] Art. 2º - Esta Lei entra em vigor na data de sua publicação.
10\tPorto Velho, 5 de abril de 1985.
### fim N01
### N02 | lei 8 | reader: 4 own articles
4\t[art 1] Art. 1º - Fica criada a coisa.
5\t[art 2] Art. 2º - O prazo é de 30 dias.
6\t[art 3] Art. 3º - A coisa será gerida pela Secretaria.
7\t[art 42] Art. 42 - A Secretaria regulamentará esta Lei.
9\tRevogam-se as disposições em contrário.
### fim N02
### N03 | lei 9 | reader: 3 own articles
5\t[art 1] Art. 1º - O art. 5º da Lei nº 100 passa a vigorar com a seguinte \
redação:
6\t[art 5] "Art. 5º - Fica proibido o uso de fogo."
7\t[art 2] Art. 2º - Esta Lei entra em vigor na data de sua publicação.
### fim N03
```

Resposta certa:

```
{"reviews": [
 {"id": "N01", "verdict": "ok", "adjustments": []},
 {"id": "N02", "verdict": "ajuste", "adjustments": [
  {"op": "set_number", "line": 7, "number": "4", "suffix": null, "level": null, \
"quoted": null, "evidence": "Art. 42 - A Secretaria regulamentará esta Lei.", \
"reason": "o º virou 2; a sequência pede o artigo 4"},
  {"op": "add_own_article", "line": 9, "number": "5", "suffix": null, "level": null, \
"quoted": null, "evidence": "Revogam-se as disposições em contrário.", \
"reason": "marcador do Art. 5º perdido; a linha abre a cláusula revogatória"}]},
 {"id": "N03", "verdict": "ajuste", "adjustments": [
  {"op": "set_quoted", "line": 6, "number": null, "suffix": null, "level": null, \
"quoted": true, "evidence": "\\"Art. 5º - Fica proibido o uso de fogo.\\"", \
"reason": "transcrição da Lei nº 100, não é artigo desta norma"}]}
]}
```

Em N01 a citação "art. 9º" no meio da linha 7 não tem etiqueta, e está certo: \
nada a ajustar.
"""


def review_prompt_sha256() -> str:
    """Hash of everything that defines the review contract sent to the model."""
    blob = REVIEW_SYSTEM_PROMPT + "\n" + json.dumps(REVIEW_SCHEMA, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# The reader's reading, as tags per line
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Tag:
    """The reader's reading of one node: ``level``, display ``number``, own/quoted."""

    level: str
    number: str
    quoted: bool

    @property
    def label(self) -> str:
        head = {
            "artigo": "art",
            "paragrafo": "§",
            "inciso": "inc",
            "alinea": "ali",
            "item": "item",
        }[self.level]
        return f"{head} {self.number}" + (" Q" if self.quoted else "")


def article_number(number: int | None, suffix: Optional[str]) -> str:
    """Article number as the scoreboard writes it: ``5`` or ``5-A``; ``?`` if unknown."""
    if number is None:
        return "?"
    if suffix:
        return f"{number}-{suffix.strip().lstrip('-').strip().upper()}"
    return str(number)


def normalize_article_number(number: str, suffix: Optional[str] = None) -> str:
    """Canonical form of a number the model gave (``5`` + ``a`` -> ``5-A``)."""
    base = str(int(number))
    return f"{base}-{suffix.upper()}" if suffix else base


def _node_number(
    kind: str, number: Optional[int], suffix: Optional[str], path: Any
) -> str:
    if kind == "artigo":
        return article_number(number, suffix)
    if kind == "paragrafo":
        if isinstance(path, str) and path.endswith("par-unico"):
            return "único"
        return str(number) if number is not None else "?"
    if number is None:
        return "?"
    if kind == "inciso":
        return _roman(number)
    if kind == "alinea":
        return chr(96 + number) if 1 <= number <= 26 else str(number)
    return str(number)


@dataclass
class ReaderView:
    """What the reviewer is shown: tags per 1-based line (possibly mutated)."""

    n_lines: int
    tags: Dict[int, List[Tag]]
    base_closes: bool
    quoted_lines: List[tuple[int, int]] = field(default_factory=list)
    mutated: bool = False

    def copy(self) -> "ReaderView":
        return ReaderView(
            n_lines=self.n_lines,
            tags={line: list(tags) for line, tags in self.tags.items()},
            base_closes=self.base_closes,
            quoted_lines=list(self.quoted_lines),
            mutated=self.mutated,
        )

    def articles(self) -> List[tuple[int, str, bool]]:
        """Every article tag as ``(line, number, quoted)``, in line order."""
        return [
            (line, tag.number, tag.quoted)
            for line in sorted(self.tags)
            for tag in self.tags[line]
            if tag.level == "artigo"
        ]

    def own_articles(self) -> List[tuple[int, str]]:
        return [
            (line, number) for line, number, quoted in self.articles() if not quoted
        ]

    def chain_ok(self) -> bool:
        """The own numbers, suffixed ones aside, read 1..N in line order."""
        bases: List[int] = []
        for _line, number in self.own_articles():
            if "-" in number:
                continue
            if not number.isdigit():
                return False
            bases.append(int(number))
        return bases == list(range(1, len(bases) + 1))

    @property
    def closes(self) -> bool:
        return self.base_closes and (not self.mutated or self.chain_ok())

    def last_own(self) -> Optional[str]:
        own = self.own_articles()
        return own[-1][1] if own else None

    def summary(self) -> Dict[str, Any]:
        arts = self.articles()
        return {
            "own_articles": sum(1 for _l, _n, q in arts if not q),
            "quoted_articles": sum(1 for _l, _n, q in arts if q),
            "closes": self.closes,
            "last": self.last_own(),
            "articles": [[line, number, quoted] for line, number, quoted in arts],
        }

    def tags_json(self) -> Dict[str, List[List[Any]]]:
        return {
            str(line): [[t.level, t.number, t.quoted] for t in tags]
            for line, tags in sorted(self.tags.items())
        }


def _line_finder(text: str) -> Any:
    newlines = [i for i, ch in enumerate(text) if ch == "\n"]
    return lambda pos: bisect.bisect_left(newlines, pos) + 1


def build_view(text: str) -> ReaderView:
    """Run the reader on ``text`` and keep its reading as tags per line."""
    report = read_hierarchy(text)
    line_of = _line_finder(text)
    nodes = sorted(
        (n for n in report["nodes"] if n["kind"] in ALL_LEVELS),
        key=lambda n: n["start"],
    )
    tags: Dict[int, List[Tag]] = {}
    for node in nodes:
        tag = Tag(
            level=node["kind"],
            number=_node_number(
                node["kind"], node["number"], node["suffix"], node["path"]
            ),
            quoted=node["status"] != "own",
        )
        tags.setdefault(line_of(node["start"]), []).append(tag)
    quoted_lines = [
        (line_of(b["start"]), line_of(max(b["start"], b["end"] - 1)))
        for b in report["quoted_blocks"]
    ]
    return ReaderView(
        n_lines=len(text.split("\n")),
        tags=tags,
        base_closes=article_closes(report),
        quoted_lines=quoted_lines,
    )


# --------------------------------------------------------------------------
# Canaries: errors planted in the reader's tags
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CanaryPlan:
    kind: str
    line: int
    op: str
    number: Optional[str] = None
    quoted: Optional[bool] = None
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "line": self.line,
            "op": self.op,
            "number": self.number,
            "quoted": self.quoted,
            "detail": self.detail,
        }


def rng_for(seed: str, *parts: object) -> random.Random:
    digest = hashlib.sha256("|".join([seed, *map(str, parts)]).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _single_article_lines(view: ReaderView, quoted: bool) -> List[int]:
    out = []
    for line in sorted(view.tags):
        arts = [t for t in view.tags[line] if t.level == "artigo"]
        if len(arts) == 1 and arts[0].quoted == quoted:
            out.append(line)
    return out


def _spurious_candidates(
    view: ReaderView, lines: Sequence[str]
) -> List[tuple[int, Optional[str]]]:
    """Untagged lines where a spurious article tag would be plausible: citations
    first (``art. 12`` in mid-sentence), else long prose inside the body."""
    own = view.own_articles()
    if not own:
        return []
    first, last = own[0][0], own[-1][0]
    citations: List[tuple[int, Optional[str]]] = []
    prose: List[tuple[int, Optional[str]]] = []
    for n in range(first + 1, last):
        if n in view.tags or n > len(lines):
            continue
        stripped = lines[n - 1].strip()
        match = _CITATION_RE.search(stripped)
        if match and match.start() > 0:
            citations.append((n, str(int(match.group(1)))))
        elif len(stripped) >= 40:
            prose.append((n, None))
    return citations or prose


def feasible_kinds(view: ReaderView, lines: Sequence[str]) -> List[str]:
    own_lines = _single_article_lines(view, quoted=False)
    own_numbered = [
        n
        for n in own_lines
        if all(t.number.isdigit() for t in view.tags[n] if t.level == "artigo")
    ]
    kinds: List[str] = []
    if len(own_lines) >= 3:
        kinds += ["drop_last", "drop_middle"]
    if len(own_numbered) >= 3:
        kinds.append("renumber")
    if own_lines and _single_article_lines(view, quoted=True):
        kinds.append("flip_quoted")
    if len(own_lines) >= 3 and _spurious_candidates(view, lines):
        kinds.append("spurious")
    return kinds


def plant_canary(
    view: ReaderView, lines: Sequence[str], kind: str, rng: random.Random
) -> tuple[ReaderView, CanaryPlan]:
    """Plant one error of ``kind`` in a copy of ``view``; return it and the plan.

    The text is never touched: the planted error is in the reader's tags only. The
    caller guarantees ``kind`` is in ``feasible_kinds(view, lines)``.
    """
    mutated = view.copy()
    mutated.mutated = True
    own_lines = _single_article_lines(view, quoted=False)

    def art_tag(line: int) -> Tag:
        return next(t for t in mutated.tags[line] if t.level == "artigo")

    def drop(line: int) -> Tag:
        tag = art_tag(line)
        rest = [t for t in mutated.tags[line] if t is not tag]
        if rest:
            mutated.tags[line] = rest
        else:
            del mutated.tags[line]
        return tag

    if kind in ("drop_last", "drop_middle"):
        line = own_lines[-1] if kind == "drop_last" else rng.choice(own_lines[1:-1])
        tag = drop(line)
        return mutated, CanaryPlan(
            kind, line, "add_own_article", number=tag.number, detail="tag dropped"
        )
    if kind == "renumber":
        numbered = [n for n in own_lines if art_tag(n).number.isdigit()]
        line = rng.choice(numbered)
        tag = art_tag(line)
        wrong = str(int(tag.number) + 1)
        mutated.tags[line] = [
            Tag("artigo", wrong, False) if t is tag else t for t in mutated.tags[line]
        ]
        return mutated, CanaryPlan(
            kind, line, "set_number", number=tag.number, detail=f"{tag.number}->{wrong}"
        )
    if kind == "flip_quoted":
        directions = []
        if _single_article_lines(view, quoted=True):
            directions.append(True)
        if own_lines:
            directions.append(False)
        to_own = rng.choice(directions)
        line = rng.choice(_single_article_lines(view, quoted=to_own))
        tag = art_tag(line)
        mutated.tags[line] = [
            Tag("artigo", tag.number, not tag.quoted) if t is tag else t
            for t in mutated.tags[line]
        ]
        return mutated, CanaryPlan(
            kind,
            line,
            "set_quoted",
            number=tag.number,
            quoted=tag.quoted,
            detail="own->quoted" if not tag.quoted else "quoted->own",
        )
    # spurious
    candidates = _spurious_candidates(view, lines)
    line, cited = rng.choice(candidates)
    number = cited
    if number is None:
        last = view.last_own()
        number = str(int(last) + 1) if last and last.isdigit() else "1"
    mutated.tags[line] = [Tag("artigo", number, False)] + mutated.tags.get(line, [])
    return mutated, CanaryPlan(
        kind, line, "remove_article", number=number, detail="spurious tag"
    )


def assign_canary_kinds(
    feasible: Sequence[Sequence[str]], seed: str, keys: Sequence[str]
) -> List[Optional[str]]:
    """One kind per canary source, balanced across kinds: each source takes the
    feasible kind used least so far (ties broken by a seeded shuffle)."""
    used = {kind: 0 for kind in CANARY_KINDS}
    out: List[Optional[str]] = []
    for kinds, key in zip(feasible, keys):
        if not kinds:
            out.append(None)
            continue
        order = list(kinds)
        rng_for(seed, "kind", key).shuffle(order)
        pick = min(order, key=lambda k: used[k])
        used[pick] += 1
        out.append(pick)
    return out


def score_canary(
    plan: Dict[str, Any], adjustments: Optional[Sequence[Dict[str, Any]]]
) -> str:
    """``invalid`` | ``missed`` | ``caught`` | ``partly`` for one canary result.

    ``adjustments`` is ``None`` when the norm's result was invalid. ``caught``: an
    adjustment names the planted line with the op that repairs that kind of error;
    ``partly``: the verdict was ``ajuste`` but nothing matches; ``missed``: ``ok``.
    """
    if adjustments is None:
        return "invalid"
    if not adjustments:
        return "missed"
    for adj in adjustments:
        if adj["line"] == plan["line"] and adj["op"] == plan["op"]:
            return "caught"
    return "partly"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


@dataclass
class ReviewNorm:
    """One norm entry of the run: a real norm or a canary copy of one."""

    ref: tb.NormRef
    texto_id: str
    text: str
    text_sha256: str
    lines: List[str]
    view: ReaderView
    chunks: List[tb.Chunk]
    canary: Optional[CanaryPlan] = None
    reader_closes: bool = False

    @property
    def entry(self) -> str:
        return self.ref.key + ("#canary" if self.canary else "")


@dataclass
class ReviewSlot:
    norm: ReviewNorm
    chunk: tb.Chunk
    rid: str = ""
    size: int = 0


@dataclass
class ReviewRequest:
    custom_id: str
    slots: List[ReviewSlot]
    user_text: str
    max_tokens: int

    @property
    def has_canary(self) -> bool:
        return any(s.norm.canary for s in self.slots)


HINT_UNTAGGED_ARTICLE = "[?art] "


def _listing(lines: Sequence[str], view: ReaderView, numbers: Iterable[int]) -> str:
    """Numbered lines with the reader's tags. An UNTAGGED line that opens with the
    reader's loose article candidate (``_ART_WILD``) gets ``[?art]``: the reader saw
    an article-like marker and did not take it. The hint is computed from whatever
    tags the view holds, so a canary that dropped a tag shows it exactly as a real
    missed article would; the hint neither singles canaries out nor hides them."""
    out = []
    for n in numbers:
        raw = lines[n - 1]
        tags = "".join(f"[{t.label}] " for t in view.tags.get(n, ()))
        if not tags and _ART_WILD.match(raw.strip()):
            tags = HINT_UNTAGGED_ARTICLE
        out.append(f"{n}\t{tags}{raw.strip()}")
    return "\n".join(out)


def _last_own_before(view: ReaderView, line: int) -> Optional[str]:
    earlier = [number for ln, number in view.own_articles() if ln < line]
    return earlier[-1] if earlier else None


def render_slot(slot: ReviewSlot) -> str:
    norm, chunk = slot.norm, slot.chunk
    # The header carries no closes/last: they are recomputed from the tags, so with
    # a planted error they would give the canary away. Only the count is shown.
    s = norm.view.summary()
    head = (
        f"### {slot.rid} | {norm.ref.tipo} {norm.ref.numero} | reader: "
        f"{s['own_articles']} own articles"
    )
    parts = []
    if chunk.total > 1:
        head += f" | parte {chunk.index + 1}/{chunk.total}"
        prior = _last_own_before(norm.view, chunk.first_line)
        opened = any(a < chunk.first_line <= b for a, b in norm.view.quoted_lines)
        parts.append(
            f"[parte {chunk.index + 1}/{chunk.total}: revise somente as linhas "
            f"{chunk.first_line} a {chunk.last_line}. Antes desta parte o último "
            f"artigo próprio é o {prior if prior is not None else 'nenhum'} e "
            f"{'HÁ' if opened else 'NÃO há'} bloco citado aberto no início dela.]"
        )
        if chunk.context:
            parts.append(
                "[contexto, somente leitura]\n"
                + _listing(norm.lines, norm.view, chunk.context)
                + "\n[linhas a revisar]"
            )
    parts.append(_listing(norm.lines, norm.view, chunk.owned))
    return "\n".join([head, *parts, f"### fim {slot.rid}"])


def render_request(slots: Sequence[ReviewSlot]) -> str:
    ids = ", ".join(s.rid for s in slots)
    intro = (
        f"Requisição com {len(slots)} norma(s): {ids}. Responda com uma entrada em "
        "`reviews` para cada id, exatamente uma vez."
    )
    return "\n\n".join([intro, *(render_slot(s) for s in slots)])


# --------------------------------------------------------------------------
# Packing
# --------------------------------------------------------------------------


def _hash_key(seed: str, key: str) -> str:
    return hashlib.sha256(f"{seed}|pack|{key}".encode("utf-8")).hexdigest()


def pack_slots(
    slots: Sequence[ReviewSlot],
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    max_norms: int = DEFAULT_MAX_NORMS,
    seed: str = "0",
) -> List[List[ReviewSlot]]:
    """Group slots into requests by size. Deterministic given ``seed``.

    A slot above the budget, and every part of a chunked norm, goes alone. The
    other real slots are packed greedily in a seeded order: a request closes when
    the next one would pass ``budget_chars`` or ``max_norms``. Canary slots go at
    most one per request and never next to the real copy of the same norm: when
    there are fewer canaries than packed requests they are spread over requests
    with room (a canary that fits nowhere gets its own request); when there are
    at least as many, every canary opens a request that is then filled with real
    slots, so no real slot is left in a request without a canary. The order inside
    a request is shuffled (seeded).
    """
    if budget_chars < 1 or max_norms < 1:
        raise ValueError("budget_chars and max_norms must be positive")
    ordered = sorted(
        slots, key=lambda s: (_hash_key(seed, s.norm.entry), s.chunk.index)
    )
    canaries = [s for s in ordered if s.norm.canary]
    requests: List[List[ReviewSlot]] = []
    pool: List[ReviewSlot] = []
    for slot in ordered:
        if slot.norm.canary:
            continue
        if slot.chunk.total > 1 or slot.size > budget_chars:
            requests.append([slot])
        else:
            pool.append(slot)

    def greedy(items: List[ReviewSlot]) -> List[List[ReviewSlot]]:
        out: List[List[ReviewSlot]] = []
        current: List[ReviewSlot] = []
        chars = 0
        for slot in items:
            if current and (
                len(current) >= max_norms or chars + slot.size > budget_chars
            ):
                out.append(current)
                current, chars = [], 0
            current.append(slot)
            chars += slot.size
        if current:
            out.append(current)
        return out

    packed = greedy(pool)
    if canaries and len(canaries) >= len(packed):
        # Spread the real slots evenly: each canary request takes its share.
        share = max(1, math.ceil(len(pool) / len(canaries)))
        for canary in canaries:
            group = [canary]
            chars = canary.size
            while pool and len(group) <= min(share, max_norms - 1):
                nxt = next(
                    (
                        s
                        for s in pool
                        if s.norm.ref.key != canary.norm.ref.key
                        and chars + s.size <= budget_chars
                    ),
                    None,
                )
                if nxt is None:
                    break
                pool.remove(nxt)
                group.append(nxt)
                chars += nxt.size
            requests.append(group)
        requests += greedy(pool)
    else:
        requests += packed
        for canary in canaries:
            fits = [
                r
                for r in requests
                if not any(s.norm.canary for s in r)
                and len(r) < max_norms
                and all(s.chunk.total == 1 for s in r)
                and sum(s.size for s in r) + canary.size <= budget_chars
                and all(s.norm.ref.key != canary.norm.ref.key for s in r)
            ]
            if fits:
                rng_for(seed, "canary-slot", canary.norm.entry).choice(fits).append(
                    canary
                )
            else:
                requests.append([canary])

    for index, request in enumerate(requests):
        rng_for(seed, "order", index).shuffle(request)
    return requests


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------


@dataclass
class ReviewPlan:
    requests: List[ReviewRequest] = field(default_factory=list)
    norms: List[ReviewNorm] = field(default_factory=list)  # real + canary entries
    sources: Dict[str, Any] = field(default_factory=dict)
    selection: Dict[str, Any] = field(default_factory=dict)
    empty: List[str] = field(default_factory=list)
    canary_notes: List[str] = field(default_factory=list)
    packing: Dict[str, Any] = field(default_factory=dict)

    @property
    def real_norms(self) -> List[ReviewNorm]:
        return [n for n in self.norms if n.canary is None]

    @property
    def canary_norms(self) -> List[ReviewNorm]:
        return [n for n in self.norms if n.canary is not None]


def review_max_tokens(
    n_slots: int,
    cap: int = tb.MAX_TOKENS_CAP,
    *,
    lines: int = 0,
    factor: float = 1.0,
) -> int:
    """``max_tokens`` of a review request with ``n_slots`` norms showing ``lines``
    lines to review.

    Base, plus per norm the thinking room and the adjustment ceiling (5
    adjustments, the worst case the ceiling prices), plus ``REVIEW_TOKENS_PER_LINE``
    per line shown, times ``factor`` (retries), never above the cap. A ``cap`` left at
    the label default (``tb.MAX_TOKENS_CAP``, what ``--max-tokens-cap`` defaults to)
    means "unset": the review cap applies.
    """
    limit = (
        REVIEW_MAX_TOKENS_CAP
        if cap == tb.MAX_TOKENS_CAP
        else min(cap, REVIEW_MAX_TOKENS_CAP)
    )
    raw = (
        REVIEW_MAX_TOKENS_BASE
        + (REVIEW_THINKING_PER_NORM + CEILING_TOKENS_PER_NORM) * n_slots
        + REVIEW_TOKENS_PER_LINE * lines
    )
    return min(limit, int(raw * factor))


def _shown_lines(slots: Sequence["ReviewSlot"]) -> int:
    return sum(len(s.chunk.owned) for s in slots)


def read_ids_file(path: Path) -> List[str]:
    """One ``texto_id`` per line; blank lines and ``#`` comments are ignored."""
    ids: List[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line not in seen:
            seen.add(line)
            ids.append(line)
    if not ids:
        raise tb.TeacherBatchError(f"{path}: no ids")
    return ids


def make_norm(record: tb.TextoRecord) -> ReviewNorm:
    lines = tb.split_lines(record.text)
    view = build_view(record.text)
    return ReviewNorm(
        ref=record.ref,
        texto_id=str(record.texto_id),
        text=record.text,
        text_sha256=record.text_sha256,
        lines=lines,
        view=view,
        chunks=[],
        reader_closes=view.closes,
    )


def build_review_plan(
    real_records: Sequence[tb.TextoRecord],
    canary_records: Sequence[tb.TextoRecord] = (),
    *,
    canary_share: float = 0.0,
    seed: str = "0",
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    max_norms: int = DEFAULT_MAX_NORMS,
    max_chars: int = DEFAULT_REVIEW_MAX_CHARS,
    context_lines: int = tb.DEFAULT_CONTEXT_LINES,
    head_lines: int = tb.DEFAULT_HEAD_LINES,
    max_tokens_cap: int = tb.MAX_TOKENS_CAP,
) -> ReviewPlan:
    """Build the requests for the selected norms plus their canary copies.

    ``canary_records`` (``--canary-ids-file``) are all planted. Without it,
    ``round(canary_share * len(real_records))`` of the real norms whose reader
    closes and that fit a single request are COPIED and planted: the real norm is
    still reviewed as it is, the copy carries one planted error in its tags.
    """
    plan = ReviewPlan()
    real: List[ReviewNorm] = []
    for record in real_records:
        norm = make_norm(record)
        norm.chunks = tb.chunk_document(
            norm.lines,
            max_lines=REVIEW_MAX_LINES,
            max_chars=max_chars,
            context_lines=context_lines,
            head_lines=head_lines,
        )
        if not norm.chunks:
            plan.empty.append(record.ref.key)
            continue
        real.append(norm)

    # -- canary sources ------------------------------------------------
    sources: List[ReviewNorm] = []
    if canary_records:
        for record in canary_records:
            norm = make_norm(record)
            norm.chunks = tb.chunk_document(
                norm.lines, max_lines=REVIEW_MAX_LINES, max_chars=max_chars
            )
            if len(norm.chunks) != 1:
                plan.canary_notes.append(
                    f"{record.texto_id}: canary source skipped (needs "
                    f"{len(norm.chunks)} parts)"
                )
                continue
            sources.append(norm)
        want = len(sources)
    else:
        want = round(max(0.0, canary_share) * len(real))
        eligible = sorted(
            (n for n in real if n.view.closes and len(n.chunks) == 1),
            key=lambda n: _hash_key(seed, "canary-source|" + n.ref.key),
        )
        sources = eligible
        if want > len(eligible):
            plan.canary_notes.append(
                f"canary share asks for {want} canaries, only {len(eligible)} "
                "norms are eligible (reader closes, single request)"
            )
    feasible = [feasible_kinds(n.view, n.lines) for n in sources]
    keys = [n.ref.key for n in sources]
    planted: List[ReviewNorm] = []
    if canary_records:
        order = list(range(len(sources)))
    else:
        # Prefer sources with at least one feasible kind, in the seeded order.
        order = [i for i, kinds in enumerate(feasible) if kinds][:want]
    kinds_picked = assign_canary_kinds(
        [feasible[i] for i in order], seed, [keys[i] for i in order]
    )
    for i, kind in zip(order, kinds_picked):
        if kind is None:
            plan.canary_notes.append(f"{keys[i]}: no feasible canary kind, skipped")
            continue
        src = sources[i]
        mutated, canary = plant_canary(
            src.view, src.lines, kind, rng_for(seed, "plant", src.ref.key)
        )
        planted.append(
            ReviewNorm(
                ref=src.ref,
                texto_id=src.texto_id,
                text=src.text,
                text_sha256=src.text_sha256,
                lines=src.lines,
                view=mutated,
                chunks=src.chunks,
                canary=canary,
                reader_closes=src.view.closes,
            )
        )

    plan.norms = real + planted

    # -- slots, sizes, packing -----------------------------------------
    slots: List[ReviewSlot] = []
    for norm in plan.norms:
        for chunk in norm.chunks:
            slot = ReviewSlot(norm=norm, chunk=chunk, rid="N00")
            slot.size = len(render_slot(slot))
            slots.append(slot)
    groups = pack_slots(
        slots, budget_chars=budget_chars, max_norms=max_norms, seed=seed
    )
    for index, group in enumerate(groups):
        for position, slot in enumerate(group, 1):
            slot.rid = f"N{position:02d}"
        custom_id = f"r{index:05d}"
        if not tb._CUSTOM_ID_RE.match(custom_id):
            raise tb.TeacherBatchError(f"invalid custom_id {custom_id!r}")
        plan.requests.append(
            ReviewRequest(
                custom_id=custom_id,
                slots=group,
                user_text=render_request(group),
                max_tokens=review_max_tokens(
                    len(group), max_tokens_cap, lines=_shown_lines(group)
                ),
            )
        )
    plan.packing = {
        "budget_chars": budget_chars,
        "max_norms": max_norms,
        "max_chars": max_chars,
        "seed": seed,
        "canary_share": canary_share,
        "canary_mode": "ids-file" if canary_records else "share",
    }
    return plan


# --------------------------------------------------------------------------
# Requests and cost
# --------------------------------------------------------------------------


def build_review_params(
    req: ReviewRequest, spec: tb.ModelSpec, effort: str, cache: bool
) -> Dict[str, Any]:
    """Messages API params for one review request (see ``build_request_params``)."""
    system_block: Dict[str, Any] = {"type": "text", "text": REVIEW_SYSTEM_PROMPT}
    if cache:
        system_block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    output_config: Dict[str, Any] = {
        "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}
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


def expected_tokens_per_norm() -> int:
    """Expected output per norm: an ``ok`` entry, plus 2 adjustments for 20%."""
    return math.ceil(
        TOKENS_PER_OK
        + EST_ADJUSTED_SHARE * EST_ADJUSTMENTS_PER_ADJUSTED * TOKENS_PER_ADJUSTMENT
    )


def estimate_review_cost(
    plan: ReviewPlan,
    spec: tb.ModelSpec,
    effort: str,
    cache: bool,
    chars_per_token: float = tb.CHARS_PER_TOKEN,
) -> tb.CostEstimate:
    """Same two numbers as ``estimate_cost``, with the review output model.

    Estimate: the measured output of a request (``MEASURED_OUTPUT_TOKENS_PER_REQUEST``)
    + ``expected_tokens_per_norm`` per norm (an ``ok`` ~15 tokens, 20% of the norms
    with 2 adjustments of ~60), capped by each request's ``max_tokens``. Ceiling:
    every request spends its whole ``max_tokens``, which assumes 5 adjustments on
    every norm (~90 tokens each), and pays the 1-hour cache write on the prefix
    with zero hits. The ceiling is an upper bound because output never exceeds
    ``max_tokens``.
    """
    system_tokens = tb.estimate_tokens(len(REVIEW_SYSTEM_PROMPT), chars_per_token)
    n = len(plan.requests)
    user_tokens = [
        tb.estimate_tokens(len(r.user_text), chars_per_token)
        + tb.REQUEST_OVERHEAD_TOKENS
        for r in plan.requests
    ]
    input_tokens = sum(user_tokens) + system_tokens * n
    # Per-request base: the measured figure (effort medium). For another effort the
    # thinking table is used when it is larger, since the measurement says nothing
    # about it; a model without effort has no thinking to add.
    if spec.supports_effort:
        base_out = max(
            MEASURED_OUTPUT_TOKENS_PER_REQUEST,
            tb.THINKING_ESTIMATE[effort] + RESPONSE_FRAMING_TOKENS,
        )
    else:
        base_out = MEASURED_OUTPUT_TOKENS_PER_REQUEST
    est_out = sum(
        min(
            r.max_tokens,
            base_out + expected_tokens_per_norm() * len(r.slots),
        )
        for r in plan.requests
    )
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
    plan: ReviewPlan, spec: tb.ModelSpec, effort: str, cache: bool
) -> tb.CostEstimate:
    """What the label mode would cost for the same real norms (no canaries)."""
    real = plan.real_norms
    texts = {n.ref.key: n.text for n in real}
    label_plan = tb.build_plan([n.ref for n in real], lambda ref: texts[ref.key])
    return tb.estimate_cost(label_plan, spec, effort, cache)


def count_tokens_sample_review(
    client: Any, plan: ReviewPlan, spec: tb.ModelSpec, effort: str, sample: int
) -> Optional[Dict[str, Any]]:
    """Measure real input tokens on a deterministic sample (free endpoint)."""
    if sample <= 0 or not plan.requests:
        return None
    step = max(1, len(plan.requests) // sample)
    picked = plan.requests[::step][:sample]
    chars = tokens = 0
    for req in picked:
        params = build_review_params(req, spec, effort, cache=False)
        counted = client.messages.count_tokens(
            model=params["model"],
            system=params["system"],
            messages=params["messages"],
            output_config=params["output_config"],
        )
        tokens += int(counted.input_tokens)
        chars += len(REVIEW_SYSTEM_PROMPT) + len(req.user_text)
    return {
        "model": spec.model,
        "sampled_requests": len(picked),
        "chars": chars,
        "input_tokens": tokens,
        "measured_chars_per_token": round(chars / tokens, 4) if tokens else None,
        "assumed_chars_per_token": tb.CHARS_PER_TOKEN,
    }


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def _slot_meta(slot: ReviewSlot) -> Dict[str, Any]:
    norm, chunk = slot.norm, slot.chunk
    ref = norm.ref
    return {
        "entry": norm.entry,
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
        # Everything ``collect`` needs to validate an answer without the text.
        "lines": {
            str(n): norm.lines[n - 1].strip()[:_LINE_STORE_CHARS] for n in chunk.owned
        },
        "tags": norm.view.tags_json(),
        "reader": norm.view.summary(),
        "reader_closes_unmutated": norm.reader_closes,
        "canary": norm.canary.as_dict() if norm.canary else None,
    }


def build_review_manifest(
    plan: ReviewPlan,
    estimate: tb.CostEstimate,
    *,
    ente: str,
    effort: Optional[str],
    cache: bool,
    max_usd: float,
    guard: str,
    label_set: str = DEFAULT_REVIEW_LABEL_SET,
) -> Dict[str, Any]:
    return {
        "manifest_version": tb.MANIFEST_VERSION,
        "mode": "review",
        "created_at": tb._now(),
        "ente": ente,
        "label_set": label_set,
        "sources": plan.sources,
        "selection": plan.selection,
        "packing": plan.packing,
        "model": estimate.model,
        "effort": effort,
        "prompt_cache": cache,
        "prompt_version": REVIEW_PROMPT_VERSION,
        "prompt_sha256": review_prompt_sha256(),
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "git_sha": tb.git_sha(),
        "max_usd": max_usd,
        "guard": guard,
        "estimate": estimate.to_dict(),
        "empty": list(plan.empty),
        "canary_notes": list(plan.canary_notes),
        "batches": [],
        "requests": {
            r.custom_id: {
                "max_tokens": r.max_tokens,
                "has_canary": r.has_canary,
                "slots": {s.rid: _slot_meta(s) for s in r.slots},
            }
            for r in plan.requests
        },
    }


def submit_review_batches(
    client: Any,
    plan: ReviewPlan,
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
            "params": build_review_params(req, spec, effort, cache),
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


# --------------------------------------------------------------------------
# Validation of an answer
# --------------------------------------------------------------------------


def _tags_at(meta: Dict[str, Any], line: int) -> List[List[Any]]:
    return list(meta["tags"].get(str(line), []))


def _parse_number(raw: Any, suffix: Any) -> tuple[Optional[str], List[str]]:
    """``(normalised article number, problems)`` for a model-given number/suffix."""
    problems: List[str] = []
    if not isinstance(raw, str) or not raw.strip():
        return None, ["number is missing"]
    text = raw.strip()
    sfx: Optional[str] = None
    match = _NUMBER_SUFFIX_RE.match(text)
    if match:
        text, sfx = match.group(1), match.group(2)
    if not _NUMBER_RE.match(text):
        return None, [f"number {raw!r} is not an arabic numeral"]
    if suffix is not None:
        if not isinstance(suffix, str) or not _SUFFIX_RE.match(suffix.strip()):
            return None, [f"suffix {suffix!r} is not a single letter"]
        sfx = suffix.strip()
    return normalize_article_number(text, sfx.upper() if sfx else None), problems


def _fold(text: str) -> str:
    """Whitespace-free, quote/dash-normalised form used to compare evidence."""
    text = text.translate({**_QUOTES, **_DASHES})
    return re.sub(r"\s+", "", text)


_MIN_FUZZY_CHARS = 10


def _fold_loose(text: str) -> str:
    """The tolerant fold of the evidence check (v3): accents, case, whitespace and
    punctuation/symbols folded away (``Organizaçao, para`` = ``Organizaçao para``,
    OCR ``Parâgrafo`` = ``Parágrafo``)."""
    out: List[str] = []
    for ch in unicodedata.normalize("NFKD", text):
        if unicodedata.combining(ch) or ch.isspace():
            continue
        if unicodedata.category(ch)[0] in "PSZC":
            continue
        out.append(ch.casefold())
    return "".join(out)


def _evidence_match(evidence: str, shown: str) -> Optional[str]:
    """How the evidence matches the line: ``"lenient"`` (the v2 rules), ``"fuzzy"``
    (only the tolerant fold of ``_fold_loose``, as a substring or as the start of a
    longer evidence, at least ``_MIN_FUZZY_CHARS`` folded characters), or ``None``.

    A skipped or added WORD still does not match (``poderã ser eleva`` against
    ``poderã eleva``): the folded strings differ, which is the safe side — the
    evidence is the proof that the model read this line.
    """
    if _evidence_matches_lenient(evidence, shown):
        return "lenient"
    folded_shown = _fold_loose(shown)
    if not folded_shown:
        return None
    for candidate in (evidence, _TAG_PREFIX_RE.sub("", evidence)):
        folded = _fold_loose(candidate)
        if len(folded) < min(_MIN_FUZZY_CHARS, len(folded_shown)):
            continue
        if folded in folded_shown or folded.startswith(folded_shown):
            return "fuzzy"
    return None


def _evidence_matches(evidence: str, shown: str) -> bool:
    """Does the evidence match the line, leniently or fuzzily (see above)?"""
    return _evidence_match(evidence, shown) is not None


def _evidence_matches_lenient(evidence: str, shown: str) -> bool:
    """Lenient evidence check, measured on the 2026-11 run.

    Accepted: the evidence is on the line (whitespace, quotes and dashes folded);
    the model copied the ``[art 4 Q]`` tag, so the tag prefix is stripped and the
    rest checked; or the evidence runs past the end of a short line into the next
    one, and the whole line is its start. The matching part is always at least the
    whole line or the 15-character minimum, enforced by the caller's length check.
    """
    if evidence in shown:
        return True
    folded_shown = _fold(shown)
    if not folded_shown:
        return False
    for candidate in (evidence, _TAG_PREFIX_RE.sub("", evidence)):
        folded = _fold(candidate)
        if not folded:
            continue
        if folded in folded_shown:
            return True
        if folded.startswith(folded_shown):
            return True
    return False


def _line_problem(
    adj: Dict[str, Any], meta: Dict[str, Any]
) -> tuple[Optional[str], bool, bool]:
    """``(problem, structural, fuzzy)`` for the line of one adjustment; ``fuzzy`` says
    the evidence matched only by the tolerant fold (``_evidence_match``).

    A line that was not listed is structural (the answer points outside what it
    was shown); an empty or non-matching evidence is a bad individual adjustment.
    """
    line = adj["line"]
    shown = meta["lines"].get(str(line))
    if shown is None:
        return (
            f"line {line} is not a listed line to review "
            f"({meta['first_line']}-{meta['last_line']}, blank lines omitted)",
            True,
            False,
        )
    evidence = adj["evidence"].strip()
    if not evidence:
        return f"line {line}: empty evidence", False, False
    how = _evidence_match(evidence, shown)
    if how is None:
        return f"line {line}: evidence is not on the line", False, False
    if len(evidence) < min(_MIN_EVIDENCE, len(shown)):
        return f"line {line}: evidence too short to identify the line", False, False
    return None, False, how == "fuzzy"


def _same_node_number(level: str, given: str, shown: str) -> bool:
    """Is the number the model gave the one the tag shows? A numeral given as arabic
    for an inciso (``2``) or an alínea (``2`` = b) reads as the tag's roman/letter."""
    g = given.strip()
    if g.isdigit():
        if level == "inciso":
            g = _roman(int(g))
        elif level == "alinea" and 1 <= int(g) <= 26:
            g = chr(96 + int(g))
    fold = lambda x: _fold_loose(x).replace("unico", "")  # noqa: E731
    return fold(g) == fold(shown) or g.casefold() == shown.casefold()


def _adjustment_check(
    raw: Any, meta: Dict[str, Any], where: str
) -> tuple[Optional[Dict[str, Any]], List[str], bool]:
    """``(adjustment or None, problems, structural)`` for one raw adjustment.

    ``structural`` problems (wrong shape, unknown op, non-integer line, a line that
    was not listed) invalidate the whole norm. Other problems mean the adjustment
    does not fit the reading and is dropped by the caller.
    """
    if not isinstance(raw, dict) or set(raw) != set(ADJUSTMENT_FIELDS):
        return None, [f"{where}: wrong shape"], True
    op, line = raw["op"], raw["line"]
    if op not in OPS:
        return None, [f"{where}: unknown op {op!r}"], True
    if isinstance(line, bool) or not isinstance(line, int):
        return None, [f"{where}: line is not an integer"], True
    if not isinstance(raw["evidence"], str) or not isinstance(raw["reason"], str):
        return None, [f"{where}: evidence and reason must be strings"], True
    problem, structural, fuzzy = _line_problem(raw, meta)
    if problem:
        return None, [f"{where}: {problem}"], structural
    tags = _tags_at(meta, line)
    art = [t for t in tags if t[0] == "artigo"]
    out: Dict[str, Any] = {
        "op": op,
        "line": line,
        "number": None,
        "suffix": None,
        "level": None,
        "quoted": None,
        "evidence": raw["evidence"].strip()[:MAX_EVIDENCE_CHARS],
        "reason": raw["reason"].strip()[:MAX_REASON_CHARS],
    }
    problems: List[str] = []
    if op == "add_own_article":
        if art:
            problems.append("the line already has an article tag")
        number, bad = _parse_number(raw["number"], raw["suffix"])
        problems += bad
        out["number"] = number
    elif op == "remove_article":
        if not art:
            problems.append("the line has no article tag")
        elif len(art) > 1:
            number, bad = _parse_number(raw["number"], raw["suffix"])
            if bad or not any(t[1] == number for t in art):
                problems.append("two article tags on the line: say which number")
            out["number"] = number
    elif op in ("set_number", "set_quoted"):
        if len(art) != 1:
            problems.append(f"expected one article tag on the line, found {len(art)}")
        elif op == "set_number":
            number, bad = _parse_number(raw["number"], raw["suffix"])
            problems += bad
            if not bad and number == art[0][1]:
                problems.append("the number is already the tag's")
            out["number"] = number
        else:
            if not isinstance(raw["quoted"], bool):
                problems.append("quoted must be true or false")
            elif raw["quoted"] == bool(art[0][2]):
                problems.append("the tag already has that quoted value")
            out["quoted"] = raw["quoted"]
    else:  # add_node / remove_node / set_node_number
        level = raw["level"]
        if level not in SUB_LEVELS:
            problems.append(f"level must be one of {', '.join(SUB_LEVELS)}")
        else:
            here = [t for t in tags if t[0] == level]
            if op == "add_node" and here:
                problems.append(f"the line already has a {level} tag")
            if op == "remove_node" and not here:
                problems.append(f"the line has no {level} tag")
            if op == "set_node_number":
                given = raw["number"]
                if len(here) != 1:
                    problems.append(
                        f"expected one {level} tag on the line, found {len(here)}"
                    )
                elif not isinstance(given, str) or not given.strip():
                    problems.append("number is missing")
                elif _same_node_number(level, given, str(here[0][1])):
                    problems.append("the number is already the tag's")
            out["level"] = level
            if op in ("add_node", "set_node_number") and isinstance(raw["number"], str):
                out["number"] = raw["number"].strip() or None
    if problems:
        return None, [f"{where}: {p}" for p in problems], False
    if fuzzy:
        out["evidence_fuzzy"] = True
    return out, [], False


def validate_adjustment(
    raw: Any, meta: Dict[str, Any], where: str
) -> tuple[Optional[Dict[str, Any]], List[str]]:
    """One adjustment against the line list and the tags the model was shown."""
    adj, problems, _structural = _adjustment_check(raw, meta, where)
    return adj, problems


@dataclass
class EntryCheck:
    """One answered id, checked against what its request showed the model."""

    verdict: Optional[str]
    adjustments: List[Dict[str, Any]]
    problems: List[str]  # structural: the norm is INVALID
    dropped: List[Dict[str, Any]] = field(default_factory=list)
    downgraded: bool = False


def _merge_node_pairs(raw_adjustments: List[Any]) -> List[tuple[int, Any, bool]]:
    """``(index, adjustment, from_pair)`` for each raw adjustment, where a
    ``remove_node`` and an ``add_node`` of the SAME level on the SAME line (given once
    each) are one renumbering: the pair becomes a single ``set_node_number`` taking the
    ``add_node``'s number, evidence and reason (``from_pair``). Run 2 of the evaluation:
    norm 74e9a7e2 line 770 (inciso II should be I) came as the pair and only the remove
    took effect."""
    where: Dict[tuple[int, Any], Dict[str, List[int]]] = {}
    for i, raw in enumerate(raw_adjustments):
        if (
            isinstance(raw, dict)
            and raw.get("op") in ("remove_node", "add_node")
            and isinstance(raw.get("line"), int)
            and not isinstance(raw.get("line"), bool)
            and raw.get("level") in SUB_LEVELS
        ):
            where.setdefault((raw["line"], raw["level"]), {}).setdefault(
                raw["op"], []
            ).append(i)
    removed: set[int] = set()
    added: set[int] = set()
    for ops in where.values():
        if len(ops.get("remove_node", [])) == 1 and len(ops.get("add_node", [])) == 1:
            removed.add(ops["remove_node"][0])
            added.add(ops["add_node"][0])
    out: List[tuple[int, Any, bool]] = []
    for i, raw in enumerate(raw_adjustments):
        if i in removed:
            continue
        if i in added:
            out.append((i, {**raw, "op": "set_node_number"}, True))
        else:
            out.append((i, raw, False))
    return out


def check_entry(entry: Any, meta: Dict[str, Any]) -> EntryCheck:
    """Structural problems invalidate the norm; a bad individual adjustment is
    DROPPED with its reason; an ``ajuste`` whose adjustments were all dropped is
    downgraded to ``ok`` (``downgraded``), so nothing is silently accepted."""
    if not isinstance(entry, dict) or set(entry) != {"id", "verdict", "adjustments"}:
        return EntryCheck(None, [], ["wrong shape"])
    verdict, raw_adjustments = entry["verdict"], entry["adjustments"]
    if verdict not in VERDICTS:
        return EntryCheck(None, [], [f"unknown verdict {verdict!r}"])
    if not isinstance(raw_adjustments, list):
        return EntryCheck(None, [], ["adjustments is not an array"])
    if verdict == "ok" and raw_adjustments:
        return EntryCheck(verdict, [], ["verdict ok carries adjustments"])
    if verdict == "ajuste" and not raw_adjustments:
        return EntryCheck(verdict, [], ["verdict ajuste carries no adjustment"])
    adjustments: List[Dict[str, Any]] = []
    problems: List[str] = []
    dropped: List[Dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for i, raw, paired in _merge_node_pairs(raw_adjustments):
        adj, bad, structural = _adjustment_check(raw, meta, f"adjustments[{i}]")
        if adj is None:
            if structural:
                problems += bad
            else:
                dropped += [
                    {
                        "index": i,
                        "op": raw.get("op") if isinstance(raw, dict) else None,
                        "line": raw.get("line") if isinstance(raw, dict) else None,
                        "reason": msg,
                    }
                    for msg in bad
                ]
            continue
        if paired:
            adj["from_pair"] = True
        key = (adj["op"], adj["line"], adj["level"])
        if key in seen:
            problems.append(
                f"adjustments[{i}]: repeats {adj['op']} on line {adj['line']}"
            )
            continue
        seen.add(key)
        adjustments.append(adj)
    removed = {a["line"] for a in adjustments if a["op"] == "remove_article"}
    for adj in adjustments:
        if adj["line"] in removed and adj["op"] in ("set_number", "set_quoted"):
            problems.append(
                f"line {adj['line']}: remove_article conflicts with {adj['op']}"
            )
    adjustments.sort(key=lambda a: (a["line"], a["op"]))
    downgraded = False
    if verdict == "ajuste" and not adjustments and dropped and not problems:
        verdict = "ok"
        downgraded = True
    return EntryCheck(verdict, adjustments, problems, dropped, downgraded)


def validate_entry(
    entry: Any, meta: Dict[str, Any]
) -> tuple[Optional[str], List[Dict[str, Any]], List[str]]:
    """``(verdict, adjustments, problems)`` for one answered id (see ``check_entry``)."""
    check = check_entry(entry, meta)
    return check.verdict, check.adjustments, check.problems


def apply_adjustments(
    articles: Sequence[Sequence[Any]], adjustments: Iterable[Dict[str, Any]]
) -> List[tuple[int, str, bool]]:
    """The reader's article tags ``(line, number, quoted)`` with the adjustments
    applied; sub-level operations do not touch the article set."""
    out: List[tuple[int, str, bool]] = [
        (int(a[0]), str(a[1]), bool(a[2])) for a in articles
    ]
    for adj in adjustments:
        line, op = adj["line"], adj["op"]
        if op == "add_own_article":
            out.append((line, str(adj["number"]), False))
        elif op == "remove_article":
            for i, art in enumerate(out):
                if art[0] == line and (adj["number"] in (None, art[1])):
                    del out[i]
                    break
        elif op == "set_number":
            out = [(a[0], str(adj["number"]), a[2]) if a[0] == line else a for a in out]
        elif op == "set_quoted":
            out = [
                (a[0], a[1], bool(adj["quoted"])) if a[0] == line else a for a in out
            ]
    return sorted(out)


# --------------------------------------------------------------------------
# Collect
# --------------------------------------------------------------------------


@dataclass
class ReviewRequestOutcome:
    custom_id: str
    ok: bool
    reason: Optional[str] = None
    detail: Optional[str] = None
    stop_reason: Optional[str] = None
    entries: List[Any] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    # Ended at max_tokens, or with no text to parse: the answer was cut (thinking
    # ate the budget), not wrong. Kept apart from ``invalid`` so it can be retried.
    truncated: bool = False


def interpret_review_result(entry: Any) -> ReviewRequestOutcome:
    """One batch result line -> the list of answered entries or a failure reason."""
    custom_id = str(tb._get(entry, "custom_id"))
    result = tb._get(entry, "result")
    result_type = tb._get(result, "type")
    if result_type != "succeeded":
        error = tb._get(result, "error")
        detail = None
        if error is not None:
            inner = tb._get(error, "error", error)
            detail = f"{tb._get(inner, 'type')}: {tb._get(inner, 'message')}"
        return ReviewRequestOutcome(custom_id, False, f"result_{result_type}", detail)
    message = tb._get(result, "message")
    usage = tb._usage_dict(tb._get(message, "usage"))
    stop_reason = tb._get(message, "stop_reason")
    outcome = ReviewRequestOutcome(
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
        or set(payload) != {"reviews"}
        or not isinstance(payload["reviews"], list)
    ):
        outcome.reason = "schema_violation"
        outcome.detail = "payload is not {reviews: [...]}"
        return outcome
    outcome.ok = True
    outcome.entries = payload["reviews"]
    return outcome


@dataclass
class SlotResult:
    """Validated result of one (norm, part) slot of a request."""

    rid: str
    custom_id: str
    meta: Dict[str, Any]
    valid: bool
    verdict: Optional[str] = None
    adjustments: List[Dict[str, Any]] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    truncated: bool = False
    dropped: List[Dict[str, Any]] = field(default_factory=list)
    downgraded: bool = False


def evaluate_request(
    custom_id: str,
    request_meta: Dict[str, Any],
    outcome: Optional[ReviewRequestOutcome],
) -> tuple[List[SlotResult], List[str]]:
    """Validate every id of one request; silence is never approval.

    Returns the slot results and request-level problems (ids the model invented).
    A request that was cut (``truncated``) gives every slot a truncated result.
    """
    results: List[SlotResult] = []
    extra: List[str] = []
    slots: Dict[str, Dict[str, Any]] = request_meta["slots"]
    if outcome is None or not outcome.ok:
        reason = "missing_result" if outcome is None else str(outcome.reason)
        cut = outcome is not None and outcome.truncated
        for rid, meta in slots.items():
            results.append(
                SlotResult(
                    rid, custom_id, meta, False, problems=[reason], truncated=cut
                )
            )
        return results, extra
    by_id: Dict[str, List[Any]] = {}
    for entry in outcome.entries:
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        key = entry_id if isinstance(entry_id, str) else "<no id>"
        by_id.setdefault(key, []).append(entry)
    extra = sorted(k for k in by_id if k not in slots)
    for rid, meta in slots.items():
        found = by_id.get(rid, [])
        if not found:
            results.append(
                SlotResult(rid, custom_id, meta, False, problems=["missing_id"])
            )
            continue
        if len(found) > 1:
            results.append(
                SlotResult(rid, custom_id, meta, False, problems=["duplicate_id"])
            )
            continue
        check = check_entry(found[0], meta)
        valid = not check.problems
        results.append(
            SlotResult(
                rid,
                custom_id,
                meta,
                valid,
                check.verdict if valid else None,
                check.adjustments if valid else [],
                check.problems,
                dropped=check.dropped,
                downgraded=check.downgraded,
            )
        )
    return results, extra


@dataclass
class EntryMerge:
    """One norm (all its parts) after merging.

    ``verdict``: ``ok`` | ``ajuste`` | ``partial`` | ``truncated`` | ``invalid``.
    ``partial`` (a chunked norm with some parts missing): ``ajuste`` when the valid
    parts carry adjustments, else ``partial``; never ``ok``.
    """

    verdict: str
    valid: bool  # has a usable answer (ok, ajuste or partial)
    adjustments: List[Dict[str, Any]]
    problems: List[str]
    dropped: List[Dict[str, Any]]
    downgraded: bool
    partial: bool
    missing_parts: List[Dict[str, Any]]


def _merge_entry(slot_results: List[SlotResult]) -> EntryMerge:
    """Merge the parts of one norm. Only a norm whose every part is ok is ``ok``."""
    slot_results.sort(key=lambda r: int(r.meta["chunk"]))
    dropped = [
        {**d, "part": int(r.meta["chunk"]) + 1} for r in slot_results for d in r.dropped
    ]
    downgraded = any(r.downgraded for r in slot_results)
    valid = [r for r in slot_results if r.valid]
    missing: List[Dict[str, Any]] = [
        {
            "part": int(r.meta["chunk"]) + 1,
            "status": "truncated" if r.truncated else "invalid",
            "problems": list(r.problems),
        }
        for r in slot_results
        if not r.valid
    ]
    problems = [
        f"part {m['part']}: {p}"
        for m in missing
        for p in cast(List[str], m["problems"])
    ]
    adjustments = sorted(
        (a for r in valid for a in r.adjustments),
        key=lambda a: (a["line"], a["op"]),
    )
    if not valid:
        verdict = "truncated" if all(r.truncated for r in slot_results) else "invalid"
        return EntryMerge(
            verdict, False, [], problems, dropped, downgraded, False, missing
        )
    if not missing:
        verdict = "ajuste" if adjustments else "ok"
        return EntryMerge(
            verdict, True, adjustments, [], dropped, downgraded, False, []
        )
    verdict = "ajuste" if adjustments else "partial"
    return EntryMerge(
        verdict, True, adjustments, problems, dropped, downgraded, True, missing
    )


def chain_intact(articles: Iterable[Sequence[Any]]) -> bool:
    """The own article numbers, suffixed ones aside, read 1..N in line order.

    ``articles`` are ``[line, number, quoted]`` triples, as the manifest stores
    them. Used for the canary recall split: a reviewer can see a gap by reading.
    """
    bases: List[int] = []
    for _line, number, quoted in sorted(articles, key=lambda a: int(a[0])):
        if quoted:
            continue
        number = str(number)
        if "-" in number:
            continue
        if not number.isdigit():
            return False
        bases.append(int(number))
    return bases == list(range(1, len(bases) + 1))


def _recall(counts: Dict[str, int]) -> Dict[str, Any]:
    total = sum(counts.values())
    return {
        **counts,
        "n": total,
        "recall": round(counts.get("caught", 0) / total, 4) if total else None,
    }


def combine_manifests(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """A retry manifest carries its base (the collected manifest it retries) under
    ``base``. Returns one manifest whose batches are the base's plus its own, whose
    requests are the base's minus the truncated ones it supersedes, plus its own.
    A manifest without ``base`` is returned unchanged."""
    base = manifest.get("base")
    if base is None:
        return manifest
    base = combine_manifests(base)
    superseded = set((manifest.get("retry") or {}).get("truncated_requests", []))
    requests = {
        cid: meta for cid, meta in base["requests"].items() if cid not in superseded
    }
    requests.update(manifest["requests"])
    combined = {k: v for k, v in manifest.items() if k != "base"}
    combined["requests"] = requests
    combined["batches"] = [*base["batches"], *manifest["batches"]]
    combined["superseded"] = sorted({*base.get("superseded", []), *superseded})
    return combined


def build_retry_plan(
    plan: ReviewPlan, base: Dict[str, Any], *, depth: int, max_tokens_cap: int
) -> ReviewPlan:
    """The requests that retry the truncated slots of ``base``, one norm (or one
    part) per request with the capped budget. ``plan`` must be built from the same
    inputs as the original submit: every slot is matched by ``(entry, chunk)`` and
    its text sha256 checked, so a changed input stops the retry instead of mixing
    two readings."""
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
    index: Dict[tuple[str, int], tuple[ReviewNorm, tb.Chunk]] = {
        (norm.entry, chunk.index): (norm, chunk)
        for norm in plan.norms
        for chunk in norm.chunks
    }
    absent = sorted(k for k in wanted if k not in index)
    if absent:
        raise tb.TeacherBatchError(
            f"{len(absent)} truncated parts are not in this plan (first "
            f"{absent[:3]}): use the same inputs as the original submit"
        )
    requests: List[ReviewRequest] = []
    for i, key in enumerate(sorted(wanted)):
        meta = wanted[key]
        norm, chunk = index[key]
        if norm.text_sha256 != meta["text_sha256"]:
            raise tb.TeacherBatchError(
                f"{key[0]}: the text changed since the original submit; retry refused"
            )
        slot = ReviewSlot(norm=norm, chunk=chunk, rid="N01")
        slot.size = len(render_slot(slot))
        requests.append(
            ReviewRequest(
                custom_id=f"t{depth}-{i:05d}",
                slots=[slot],
                user_text=render_request([slot]),
                max_tokens=review_max_tokens(
                    1,
                    max_tokens_cap,
                    lines=_shown_lines([slot]),
                    factor=RETRY_BUDGET_FACTOR**depth,
                ),
            )
        )
    return ReviewPlan(
        requests=requests,
        norms=plan.norms,
        sources=plan.sources,
        selection=plan.selection,
        empty=list(plan.empty),
        canary_notes=list(plan.canary_notes),
        packing=plan.packing,
    )


def attach_retry(
    manifest: Dict[str, Any], base: Dict[str, Any], *, depth: int, plan: ReviewPlan
) -> None:
    """Make ``manifest`` a retry of ``base``: ``collect`` merges the two."""
    manifest["base"] = base
    manifest["retry_depth"] = depth
    manifest["retry"] = {
        "truncated_requests": list(base["truncated_requests"]),
        "slots": sum(len(r.slots) for r in plan.requests),
    }


def _dropped_reason(text: str) -> str:
    """A dropped reason with its numbers and the ``adjustments[i]`` prefix removed,
    so the same kind of drop groups together in the summary."""
    return re.sub(r"\d+", "N", re.sub(r"^adjustments\[\d+\]: ", "", text))[:60]


def collect_review(
    client: Any, manifest: Dict[str, Any], out_dir: Path
) -> Dict[str, Any]:
    """Fetch, validate, score canaries and write ``reviews/``. Assumes ended batches.

    A retry manifest (``base``) is merged first: its results replace the truncated
    requests of the base, which are then not validated at all.
    """
    manifest = combine_manifests(manifest)
    spec = tb.resolve_model(manifest["model"])
    requests: Dict[str, Dict[str, Any]] = manifest["requests"]
    superseded = set(manifest.get("superseded", []))
    submitted = {cid for b in manifest["batches"] for cid in b["custom_ids"]}
    outcomes: Dict[str, ReviewRequestOutcome] = {}
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
                outcomes[custom_id] = interpret_review_result(entry)

    provenance = {
        "mode": "review",
        "label_set": manifest.get("label_set", DEFAULT_REVIEW_LABEL_SET),
        "model": manifest["model"],
        "effort": manifest.get("effort"),
        "prompt_version": manifest["prompt_version"],
        "prompt_sha256": manifest["prompt_sha256"],
        "review_schema_version": manifest["review_schema_version"],
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

    # -- validate every slot of every request ---------------------------------
    by_entry: Dict[str, List[SlotResult]] = {}
    request_results: Dict[str, List[SlotResult]] = {}
    request_extra: Dict[str, List[str]] = {}
    for custom_id, meta in requests.items():
        found = outcomes.get(custom_id)
        if found is None and custom_id not in submitted:
            found = ReviewRequestOutcome(custom_id, False, "not_submitted")
        slot_results, extra = evaluate_request(custom_id, meta, found)
        request_results[custom_id] = slot_results
        if extra:
            request_extra[custom_id] = extra
        for r in slot_results:
            by_entry.setdefault(str(r.meta["entry"]), []).append(r)

    # -- canary outcome per entry, then per request ---------------------------
    merged: Dict[str, EntryMerge] = {}
    canary_outcome: Dict[str, str] = {}
    for entry_key, results in by_entry.items():
        merged[entry_key] = _merge_entry(results)
        plan = results[0].meta["canary"]
        if plan is not None:
            m = merged[entry_key]
            if m.verdict == "truncated":
                canary_outcome[entry_key] = "truncated"
            else:
                usable = m.verdict in ("ok", "ajuste")
                canary_outcome[entry_key] = score_canary(
                    plan, m.adjustments if usable else None
                )
    unverified_requests: set[str] = set()
    for custom_id, results in request_results.items():
        for r in results:
            if r.meta["canary"] is not None and canary_outcome.get(
                str(r.meta["entry"])
            ) in ("missed", "invalid", "truncated"):
                unverified_requests.add(custom_id)

    # -- write one JSON per entry ---------------------------------------------
    reviews_dir = out_dir / "reviews"
    failures: List[Dict[str, Any]] = []
    counts = {"ok": 0, "ajuste": 0, "partial": 0, "truncated": 0, "invalid": 0}
    unverified_count = 0
    canary_counts: Dict[str, Dict[str, int]] = {k: {} for k in CANARY_KINDS}
    chain_counts: Dict[str, Dict[str, int]] = {"intact": {}, "broken": {}}
    candidate: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = {}
    dropped_reasons: Dict[str, int] = {}
    dropped_total = downgraded_total = 0
    adjustments_by_op: Dict[str, int] = {}
    real_total = canary_total = 0
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    for entry_key, results in sorted(by_entry.items()):
        first = results[0].meta
        canary = first["canary"]
        em = merged[entry_key]
        request_ids = sorted({r.custom_id for r in results})
        in_unverified = any(cid in unverified_requests for cid in request_ids)
        has_canary_in_request = any(
            requests[cid].get("has_canary") for cid in request_ids
        )
        chain = chain_intact(first["reader"]["articles"]) if canary else None
        record: Dict[str, Any] = {
            "record": "review",
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
            "reader": first["reader"],
            "verdict": em.verdict,
            "adjustments": em.adjustments,
            "invalid_reasons": em.problems,
            "dropped": em.dropped,
            "downgraded": em.downgraded,
            "partial": em.partial,
            "missing_parts": em.missing_parts,
            "canary": canary is not None,
            "canary_plan": canary,
            "canary_outcome": canary_outcome.get(entry_key),
            "canary_chain_intact": chain,
            "request_ids": request_ids,
            "canary_in_request": bool(has_canary_in_request),
            "unverified": bool(em.verdict == "ok" and canary is None and in_unverified),
            **provenance,
        }
        path = (
            reviews_dir
            / str(first["item"])
            / (
                f"{first['tipo']}-{int(first['numero']):05d}_{first['uuid5']}"
                + ("_canary" if canary else "")
                + ".json"
            )
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        for d in em.dropped:
            dropped_total += 1
            why = _dropped_reason(str(d["reason"]))
            dropped_reasons[why] = dropped_reasons.get(why, 0) + 1
        if em.downgraded:
            downgraded_total += 1
        if em.verdict in ("invalid", "truncated", "partial"):
            failures.append(
                {
                    "key": first["key"],
                    "entry": entry_key,
                    "texto_id": first["texto_id"],
                    "canary": canary is not None,
                    "request_ids": request_ids,
                    "verdict": em.verdict,
                    "problems": em.problems[:10],
                    "missing_parts": em.missing_parts,
                }
            )
        if em.verdict == "truncated":
            reasons["truncated"] = reasons.get("truncated", 0) + 1
        for part in em.missing_parts:
            if part["status"] == "truncated":
                reasons["truncated_part"] = reasons.get("truncated_part", 0) + 1
                continue
            for problem in part["problems"]:
                why = re.sub(r"\d+", "N", problem)[:60]
                reasons[why] = reasons.get(why, 0) + 1
        if canary is not None:
            canary_total += 1
            name = canary_outcome[entry_key]
            bucket = canary_counts[canary["kind"]]
            bucket[name] = bucket.get(name, 0) + 1
            chain_bucket = chain_counts["intact" if chain else "broken"]
            chain_bucket[name] = chain_bucket.get(name, 0) + 1
            continue
        real_total += 1
        counts[em.verdict] += 1
        if record["unverified"]:
            unverified_count += 1
        if not em.valid:
            continue
        for adj in em.adjustments:
            adjustments_by_op[adj["op"]] = adjustments_by_op.get(adj["op"], 0) + 1
            candidate.append(
                {
                    "norm": first["key"],
                    "texto_id": first["texto_id"],
                    "text_sha256": first["text_sha256"],
                    **{k: v for k, v in adj.items() if v is not None or k == "quoted"},
                    "errata_compatible": adj["op"] in ERRATA_OPS,
                    "unverified": record["unverified"],
                    "verified_by": "revisão automática (LLM), não verificada",
                    "date": today,
                }
            )

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
    tb.write_json(
        out_dir / "review-adjustments.json",
        {
            "schema_version": 1,
            "status": "candidate: generated by the review mode, NOT applied to "
            "any label, errata file or reader. Each entry needs a human reading "
            "of the text before it can become an errata correction.",
            "label_set": provenance["label_set"],
            "corrections": candidate,
        },
    )
    measured = tb.measured_cost_usd(
        usage_total, spec, cache_1h=bool(manifest.get("prompt_cache"))
    )
    entries_total = real_total + canary_total
    canary_by_kind = {k: _recall(v) for k, v in canary_counts.items()}
    canary_all: Dict[str, int] = {}
    for bucket in canary_counts.values():
        for name, n in bucket.items():
            canary_all[name] = canary_all.get(name, 0) + n
    truncated_requests = sorted(
        cid
        for cid, o in outcomes.items()
        if o.truncated and cid not in superseded and cid in requests
    )
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
        "norms_total": real_total,
        "norms_ok": counts["ok"] + counts["ajuste"],
        "norms_partial": counts["partial"],
        "norms_truncated": counts["truncated"],
        "norms_failed": counts["invalid"] + counts["truncated"] + counts["partial"],
        "verdicts": {"ok": counts["ok"], "ajuste": counts["ajuste"]},
        "partial": counts["partial"],
        "truncated": counts["truncated"],
        "invalid": counts["invalid"],
        "unverified": unverified_count,
        "downgraded": downgraded_total,
        "dropped_adjustments": dropped_total,
        "dropped_by_reason": dict(sorted(dropped_reasons.items())),
        "adjustments_by_op": dict(sorted(adjustments_by_op.items())),
        "canaries": {"total": canary_total, **_recall(canary_all)},
        "canary_by_kind": canary_by_kind,
        "canary_recall_chain_intact": _recall(chain_counts["intact"]),
        "canary_recall_chain_broken": _recall(chain_counts["broken"]),
        "unverified_requests": sorted(unverified_requests),
        "failure_reasons": dict(sorted(reasons.items())),
        "usage": usage_total,
        "measured_usd": measured,
        "measured_usd_per_request": (
            round(measured / len(outcomes), 6) if outcomes else None
        ),
        "measured_usd_per_norm": (
            round(measured / real_total, 6) if real_total else None
        ),
        "measured_usd_per_entry": (
            round(measured / entries_total, 6) if entries_total else None
        ),
        "estimate": manifest.get("estimate"),
        "sources": manifest.get("sources", {}),
        "selection": manifest.get("selection", {}),
        "packing": manifest.get("packing", {}),
        "retry": manifest.get("retry"),
        "not_reviewed_at_submit": {"empty": manifest.get("empty", [])},
    }
    tb.write_json(out_dir / "summary.json", summary)
    return summary


# --------------------------------------------------------------------------
# Publication to the Internet Archive
# --------------------------------------------------------------------------


def upload_review_to_ia(
    out_dir: Path, summary: Dict[str, Any], revision: Optional[str] = None
) -> Dict[str, Any]:
    """Upload ``reviews/`` (one tar.gz), failures, summary, candidate adjustments
    and the manifest as one IA data item, under the label-set naming (a label set
    other than ``main`` gets its name in the identifier)."""
    ente = str(summary["ente"])
    label_set = str(summary.get("label_set", DEFAULT_REVIEW_LABEL_SET))
    effective = revision or datetime.now(tz=timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    ia_id = tb.ia_identifier(ente, effective, label_set)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "reviews.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(out_dir / "reviews", arcname="reviews")
        description = (
            f"Revisões do leitor por regras feitas por LLM (modo review, revisão "
            f"{effective}, conjunto {label_set}) de normas do ente {ente.upper()}, "
            f"geradas pelo projeto Leizilla. {summary['norms_total']} normas, "
            f"{summary['canaries']['total']} canários. Proveniência em summary.json; "
            "os ajustes candidatos NÃO foram aplicados."
        )
        args = [
            "ia",
            "upload",
            ia_id,
            str(archive),
            str(out_dir / "failures.jsonl"),
            str(out_dir / "summary.json"),
            str(out_dir / "review-adjustments.json"),
            str(out_dir / "manifest.json"),
            "--metadata",
            f"title:Leizilla Teacher Reviews {ente.upper()} [{label_set}] ({effective})",
            "--metadata",
            "mediatype:data",
            "--metadata",
            f"subject:leis;leizilla;{ente};reviews;{label_set}",
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


def check_review_label_set(label_set: Optional[str]) -> str:
    name = label_set or DEFAULT_REVIEW_LABEL_SET
    tb.check_label_set(name)
    if name == tb.DEFAULT_LABEL_SET:
        raise tb.TeacherBatchError(
            "review runs must not use the 'main' label set (reviews are not labels); "
            f"use another name, the default is {DEFAULT_REVIEW_LABEL_SET!r}"
        )
    return name


def prepare_review(
    *,
    ente: str,
    tipo: Optional[str],
    limit: Optional[int],
    shuffle_seed: Optional[str],
    text_source: str,
    textos: Optional[Path],
    exclude_labelled: Optional[str],
    select: str,
    ids_file: Optional[Path],
    canary_share: float,
    canary_ids_file: Optional[Path],
    budget_chars: int,
    max_norms: int,
    max_chars: int,
    max_tokens_cap: int,
) -> ReviewPlan:
    if text_source != "textos":
        raise tb.TeacherBatchError("review mode needs --text-source textos")
    if select not in SELECTS:
        raise tb.TeacherBatchError(f"select must be one of {', '.join(SELECTS)}")
    if select == "ids-file" and ids_file is None:
        raise tb.TeacherBatchError("--select ids-file needs --ids-file PATH")
    if select != "ids-file" and ids_file is not None:
        raise tb.TeacherBatchError("--ids-file is only used with --select ids-file")
    if not (0.0 <= canary_share <= 1.0):
        raise tb.TeacherBatchError("--canary-share must be between 0 and 1")
    seed = shuffle_seed if shuffle_seed is not None else "0"
    labelled = tb.load_label_index(exclude_labelled) if exclude_labelled else None
    corpus = tb._load_textos_corpus(textos)
    by_id = {r.texto_id: r for r in corpus.records if r.texto_id}
    pool = [
        r
        for r in corpus.records
        if tb.label_status(r.ref.ident, r.text_sha256, labelled) != "excluded"
    ]
    if tipo:
        wanted = {t.lower() for t in tb._split_csv(tipo) or []}
        pool = [r for r in pool if r.ref.tipo.lower() in wanted]
    selection: Dict[str, Any] = {
        "select": select,
        "texts_in_layer": len(corpus.records),
        "after_exclusion_and_tipo": len(pool),
    }
    if select == "ids-file":
        assert ids_file is not None
        ids = read_ids_file(ids_file)
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise tb.TeacherBatchError(
                f"{ids_file}: {len(missing)} of {len(ids)} ids are not in the text "
                f"layer (first: {missing[:3]})"
            )
        listed = set(ids)
        pool = [r for r in pool if r.texto_id in listed]
        selection["ids_file"] = {"path": str(ids_file), "ids": len(ids)}
        if len(pool) != len(ids):
            selection["ids_file"]["dropped_by_exclusion_or_tipo"] = len(ids) - len(pool)
    elif select in ("closed", "open"):
        want_closed = select == "closed"
        pool = [r for r in pool if build_view(r.text).closes == want_closed]
    selected_refs = tb.select_norms(
        [r.ref for r in pool], limit=limit, shuffle_seed=shuffle_seed
    )
    by_key = {r.ref.key: r for r in pool}
    real_records = [by_key[ref.key] for ref in selected_refs]
    selection["selected"] = len(real_records)
    canary_records: List[tb.TextoRecord] = []
    if canary_ids_file is not None:
        cids = read_ids_file(canary_ids_file)
        missing = [i for i in cids if i not in by_id]
        if missing:
            raise tb.TeacherBatchError(
                f"{canary_ids_file}: {len(missing)} of {len(cids)} ids are not in "
                f"the text layer (first: {missing[:3]})"
            )
        canary_records = [by_id[i] for i in cids]
        selection["canary_ids_file"] = {"path": str(canary_ids_file), "ids": len(cids)}
    plan = build_review_plan(
        real_records,
        canary_records,
        canary_share=0.0 if canary_ids_file else canary_share,
        seed=seed,
        budget_chars=budget_chars,
        max_norms=max_norms,
        max_chars=max_chars,
        max_tokens_cap=max_tokens_cap,
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
    if labelled is not None:
        plan.sources["exclude_labelled"] = {
            "source": exclude_labelled,
            "labelled_norms": len(labelled),
        }
    return plan


def plan_summary(plan: ReviewPlan) -> Dict[str, Any]:
    kinds: Dict[str, int] = {}
    for norm in plan.canary_norms:
        assert norm.canary is not None
        kinds[norm.canary.kind] = kinds.get(norm.canary.kind, 0) + 1
    sizes = sorted(len(r.slots) for r in plan.requests)
    return {
        "real_norms": len(plan.real_norms),
        "canary_norms": len(plan.canary_norms),
        "canaries_by_kind": dict(sorted(kinds.items())),
        "requests": len(plan.requests),
        "norms_per_request": {
            "min": sizes[0] if sizes else 0,
            "max": sizes[-1] if sizes else 0,
            "mean": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        },
        "requests_with_canary": sum(1 for r in plan.requests if r.has_canary),
        "chunked_norms": sum(1 for n in plan.real_norms if len(n.chunks) > 1),
        "empty": len(plan.empty),
    }


def echo_review_plan(plan: ReviewPlan) -> None:
    info = plan_summary(plan)
    typer.echo(
        f"review: {info['real_norms']} norms + {info['canary_norms']} canaries "
        f"in {info['requests']} requests (norms per request "
        f"{info['norms_per_request']}); chunked norms {info['chunked_norms']}"
    )
    typer.echo(f"canaries by kind: {info['canaries_by_kind']}")
    for note in plan.canary_notes[:5]:
        typer.echo(f"WARNING {note}", err=True)


def echo_review_estimate(
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
    """Collect step for a review manifest; returns the process exit code."""
    summary = collect_review(client, manifest, out_dir)
    c = summary["canaries"]
    typer.echo(
        f"{summary['norms_ok']}/{summary['norms_total']} norms reviewed "
        f"(ok {summary['verdicts']['ok']}, ajuste {summary['verdicts']['ajuste']}, "
        f"partial {summary['partial']}, truncated {summary['truncated']}, "
        f"invalid {summary['invalid']}, unverified {summary['unverified']}, "
        f"dropped adjustments {summary['dropped_adjustments']}); "
        f"canaries {c.get('caught', 0)}/{c['total']} caught "
        f"(recall {c['recall']}), measured US${summary['measured_usd']:.4f}"
    )
    if upload_ia:
        if summary["norms_total"] == 0:
            typer.echo("nothing to upload", err=True)
        else:
            result = upload_review_to_ia(out_dir, summary)
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
    count_sample: int,
    out: Optional[Path],
    ente: str,
    label_set: str,
    **kwargs: Any,
) -> ReviewPlan:
    """The ``plan`` step in review mode. Sends nothing billable: the Anthropic
    client is created only for ``--count-sample`` (the free token counter)."""
    plan = prepare_review(
        ente=ente,
        exclude_labelled=kwargs.pop("exclude_labelled"),
        tipo=kwargs.pop("tipo"),
        limit=kwargs.pop("limit"),
        shuffle_seed=kwargs.pop("shuffle_seed"),
        text_source=kwargs.pop("text_source"),
        textos=kwargs.pop("textos"),
        select=kwargs.pop("select"),
        ids_file=kwargs.pop("ids_file"),
        canary_share=kwargs.pop("canary_share"),
        canary_ids_file=kwargs.pop("canary_ids_file"),
        budget_chars=kwargs.pop("budget_chars"),
        max_norms=kwargs.pop("max_norms"),
        max_chars=kwargs.pop("max_chars"),
        max_tokens_cap=kwargs.pop("max_tokens_cap"),
    )
    echo_review_plan(plan)
    estimates = []
    comparisons = []
    for spec in specs:
        estimate = estimate_review_cost(plan, spec, effort, prompt_cache)
        label_estimate = label_mode_estimate(plan, spec, effort, prompt_cache)
        estimates.append(estimate)
        comparisons.append(label_estimate)
        echo_review_estimate(estimate, label_estimate)
    measured: List[Dict[str, Any]] = []
    if count_sample > 0:
        client = tb._client()
        for spec in specs:
            sample = count_tokens_sample_review(
                client, plan, spec, effort, count_sample
            )
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
                "mode": "review",
                "ente": ente,
                "label_set": label_set,
                "sources": plan.sources,
                "selection": plan.selection,
                "packing": plan.packing,
                "plan": plan_summary(plan),
                "prompt_version": REVIEW_PROMPT_VERSION,
                "prompt_sha256": review_prompt_sha256(),
                "git_sha": tb.git_sha(),
                "estimates": [e.to_dict() for e in estimates],
                "label_mode_estimates": [e.to_dict() for e in comparisons],
                "token_count_samples": measured,
                "canary_notes": plan.canary_notes,
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
    """The ``submit`` step in review mode: same guard, then the batch(es).

    With ``retry_truncated`` (the collected ``manifest.json`` of an earlier run, which
    lists ``truncated_requests``) only those norms are sent again, one per request,
    and the new manifest carries the base so that ``collect`` merges the two.
    """
    cap = int(kwargs.get("max_tokens_cap", tb.MAX_TOKENS_CAP))
    plan = prepare_review(
        ente=ente,
        exclude_labelled=kwargs.pop("exclude_labelled"),
        tipo=kwargs.pop("tipo"),
        limit=kwargs.pop("limit"),
        shuffle_seed=kwargs.pop("shuffle_seed"),
        text_source=kwargs.pop("text_source"),
        textos=kwargs.pop("textos"),
        select=kwargs.pop("select"),
        ids_file=kwargs.pop("ids_file"),
        canary_share=kwargs.pop("canary_share"),
        canary_ids_file=kwargs.pop("canary_ids_file"),
        budget_chars=kwargs.pop("budget_chars"),
        max_norms=kwargs.pop("max_norms"),
        max_chars=kwargs.pop("max_chars"),
        max_tokens_cap=kwargs.pop("max_tokens_cap"),
    )
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
    echo_review_plan(plan)
    if not plan.requests:
        raise tb.TeacherBatchError("no requests to submit")
    estimate = estimate_review_cost(plan, spec, effort, prompt_cache)
    echo_review_estimate(
        estimate, label_mode_estimate(plan, spec, effort, prompt_cache)
    )
    tb.check_cost_guard(estimate, spec, max_usd, guard)
    manifest = build_review_manifest(
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
        attach_retry(manifest, base, depth=depth, plan=plan)
    return submit_review_batches(
        tb._client(),
        plan,
        spec,
        manifest,
        manifest_path,
        effort=effort,
        cache=prompt_cache,
    )
