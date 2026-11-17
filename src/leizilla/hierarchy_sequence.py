"""Sequence-aware reading of the full hierarchy of a norm in OCR text.

`article_sequence` reads "Art. N" by sequence instead of one marker at a time. This
module applies the same idea one level down, and then again: paragraphs restart inside
each article, incisos restart inside each caput or paragraph, alíneas inside each
inciso, itens inside each alínea. In every scope the numbering chain is the
disambiguator: after "I -" and "II -", a line opening with "HI -" is III.

The text is never rewritten. Every node carries character offsets into the original
string, the reading that was chosen and whether it differs from the literal one.

Pipeline for one text:

1. read the articles (`article_sequence.read_articles`);
2. find blocks quoted from another norm (an amending law: quotation mark after "passa a
   vigorar com a seguinte redação" and similar cues) and read the articles again with
   those blocks masked, so a quoted article can never join the host numbering;
3. inside each own article, read paragraphs, then incisos, alíneas and itens, each in
   the scope of its parent, with one chain per scope;
4. read each quoted block as a separate subtree, with chains that may start anywhere;
5. report closure per level. A level closes only when every scope holds a full 1..N
   chain and no marker-shaped candidate is left unexplained.

Three kinds of reading, recorded per node in ``read_by``: ``literal`` (as printed),
``confusion`` (a known OCR look-alike, picked by the chain) and ``gap`` (glyphs that are
unreadable or contradict the chain, read only because exactly one number was missing
between two neighbours and exactly one candidate sat there).

What keeps a scope open, besides a gap in its chain: a marker where a marker sits (line
start or after sentence punctuation) that joined no chain; a look-alike left beside a
chain ("11 —" after "II —"); any short line opener that follows "…; e" or "…;", since
the list plainly goes on. A leftover that a deeper level explains ("1 -" read as an
item) does not count. Weak candidates outside those cases are ``ignored``.

Known limits (by design, not oversights): text after the last child of a node (a
"Pena - ..." line after the incisos) stays inside that last child; organisational
blocks (TÍTULO, CAPÍTULO, Seção) are not nodes; a marker the OCR lost at the *end* of a
chain leaves no trace in the numbering. Two placement checks on the article level
(`final_clause_placed`, `tail_clean`) catch the common shapes of that loss: a closing
sentence opening a line with no article marker, and an unread article marker after the
last own article.

It is a measurement and review aid for the `boundary-decision-parser` research front
(docs/okf/project-dag.md), not part of the production parser.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Sequence, TypedDict

from leizilla.segmenter import Span

from leizilla.article_sequence import (
    ARTICLE_CANDIDATE,
    ArticleRead,
    QUOTE_CHARS,
    article_readings,
    best_chain,
    is_reference,
    read_articles,
)

# --- candidates -----------------------------------------------------------------------
# A paragraph sign followed by a number-like token. OCR reads "§" as "$", "S", "8", "9",
# "5" or "&"; the look-alike glyphs are only trusted at the start of a line.
_PAR = re.compile(
    r"(?<![A-Za-z0-9$§])"
    r"(?P<glyph>§|\$|(?:\d{1,2}|[SsqgBfE&£])(?=\s)|S(?=\d{1,2}[º°]))\s{0,3}"
    r"(?P<num>[0-9IlO]{1,3})(?:(?P<ord>\s?\.?[ºo°ªQ^?])|(?![.,]?\d))"
    r"(?:-(?P<suffix>[A-Z])\b)?"
)
# "§ T" for "§ 7º": a paragraph sign whose number is unreadable. It has no reading of
# its own and can only be read by the chain around it.
_PAR_WILD = re.compile(r"[§$]\s?[^\W\d_]{1,2}\b(?!\s?[ºo°])")
_PAR_UNICO = re.compile(
    r"\bPar[áa]gra[ft]o\s+[ÚúUuOÜü][nm][ijl]?c[oa]\b", re.IGNORECASE
)
# Roman numeral (or what OCR makes of one) followed by a separator.
_INC = re.compile(
    r"(?<![\w.])(?P<tok>[IVXLCHUTJNYKMl1|!ivxnt\]\[]{1,8})\s{0,2}"
    r"(?P<sep>[-–—~=_]{1,2}|[.):])"
)
# Any short token before a dash at the start of a line ("Vm -", "NI —", "VÊ -"): no
# reading of its own, usable only to fill a single gap in a chain.
_INC_WILD = re.compile(
    r"(?m)^[ \t]*(?P<mark>(?P<tok>[^\W_]{1,4})[ \t]{0,2}[-–—]+)(?P<gap>[ \t]*)\S"
)
_ALI = re.compile(r"(?<![\w(])(?P<let>[a-zA-Z06])\s?[)\]}]")
_ALI_WILD = re.compile(r"(?m)^[ \t]*(?P<tok>[^\s(]{1,2})[ \t]?[)\]}]")
_ITEM = re.compile(r"(?m)^[ \t]*(?P<num>\d{1,2})(?:\s?[.)]|\s?[-–—])(?=\s)(?!\s*\d)")

_PROSE = re.compile(r"[ \t]+[^\W\d_]{2}")
_PURE_ROMAN = re.compile(r"[IVXLC]+\Z")
_HAS_ROMAN_CAPITAL = re.compile(r"[IVXLCH]")
_STRONG_SEP = re.compile(r"[-–—~=_]")
# What each glyph of a roman-numeral token may stand for.
_ROMAN_GLYPHS: dict[str, tuple[str, ...]] = {
    "I": ("I",),
    "l": ("I",),
    "1": ("I",),
    "|": ("I",),
    "!": ("I",),
    "i": ("I",),
    "]": ("I",),
    "[": ("I",),
    "J": ("I",),
    "T": ("I",),
    "H": ("II", "I"),
    "U": ("II",),
    "n": ("II",),
    "V": ("V",),
    "v": ("V",),
    "X": ("X",),
    "x": ("X",),
    "L": ("L", "I"),
    "C": ("C",),
}
_MAX_ROMAN = 150
# Letters OCR swaps in an alínea marker, by reading order (literal first).
_ALI_GLYPHS: dict[str, str] = {
    "c": "ceo",
    "e": "ec",
    "o": "oce",
    "0": "oc",
    "i": "il",
    "l": "li",
    "b": "bh",
    "h": "hb",
    "6": "b",
    "g": "gq",
    "q": "qg",
}
# Alíneas of older norms skip k, w and y.
_ALI_FREE_SKIPS = frozenset({11, 23, 25})

_REF_LEFT_PAR = re.compile(
    r"(?:\b(?:d?o|n?o|ao|d?os|n?os|aos|pelos?|e|ou)|§|,)\s+$", re.IGNORECASE
)
_REF_RIGHT_PAR = re.compile(
    r"\s*(?:(?:do|da|dos|das|deste|desta|destes|destas)\b|,|e\s+(?:§|\d))"
)
_REF_LEFT_INC = re.compile(
    r"\b(?:incisos?|inc\.|itens?|item|anexos?|tabelas?|quadros?|cap[ií]tulos?"
    r"|t[ií]tulos?|se[cç](?:[aã]o|[oõ]es)|subse[cç][aã]o|livros?|partes?|grupos?"
    r"|classes?|n[ií]ve(?:l|is)|categorias?|padr(?:[aã]o|[oõ]es)|refer[eê]ncias?"
    r"|faixas?|tipos?|modelos?|s[ée]ries?)\s+$",
    re.IGNORECASE,
)
_REF_LEFT_ALI = re.compile(
    r"(?:\b(?:al[ií]neas?|letras?|itens?|item)\s+|[)\]}]\s*,\s*|[)\]}]\s+(?:e|ou)\s+)$",
    re.IGNORECASE,
)

# --- quoted blocks --------------------------------------------------------------------
_QUOTES = QUOTE_CHARS + "»"
_QUOTE_CHAR = re.compile(f"[{re.escape(_QUOTES)}]")
# The vocabulary of an amending command, searched in the host text before a quote.
_AMEND_CUE = re.compile(
    r"reda[cç][aã]o|acrescid|acrescent|altera[cç]|passam?\s+a\s+(?:vigorar|ter)"
    r"|inclu[ií]d|modificad|seguintes?\s+dispositivos?|vigorar",
    re.IGNORECASE,
)
# A marker right after an opening quote: what makes the quote a quoted *block*.
_BLOCK_HEAD = re.compile(
    r"\s{0,2}(?:Art|AH|Arl|Aft|§|\$\s?\d|Par[áa]grafo|[IVXLC]{1,7}\s?[-–—]"
    r"|[a-z]\)|CAP[IÍ]TULO|Se[cç][aã]o|SE[CÇ][AÃ]O|T[IÍ]TULO|\.{3})"
)
_CUE_COLON = re.compile(
    r"(?:reda[cç][aã]o|altera[cç][oõ]es|acr[eé]scimos?|dispositivos?|vigorar"
    r"|acrescid[oa]s?|redigid[oa]s?)[^:.;]{0,80}:\s*$",
    re.IGNORECASE,
)
_CUE_THEN = re.compile(
    r"(?:reda[cç][aã]o|altera[cç][oõ]es|acr[eé]scimos?|dispositivos?|vigorar"
    r"|acrescid[oa]s?|redigid[oa]s?)[^:.;]{0,80}:\s*",
    re.IGNORECASE,
)
_ART_WILD = re.compile(
    r"(?m)^[ \t]*(?P<word>(?:[AÁ][rRtTiIlLpPfFnh]{1,3}s?|[aáà]r[tl]?)\b[.,:;]?"
    r"[ \t]*\n?[ \t]*(?:\d\S{0,3}|[A-Z]{1,2}\b|[Il][oO0]\b))"
)
# A line opener that is an article word and number ruined together ("Art. /º - Esta
# Lei", "rti 2º — Os recursos", "Arta 29 Esta Lei"): a short art-like token, at most
# one junk or number-like token, then the first word of a caput.
_ART_GARBLE = re.compile(
    r"(?m)^[ \t_]*(?P<word>[AÁVaá]?[a-zA-Z]{2,4}[.,:;»«™\-]{0,2}[ \t]*"
    r"(?:[^\w\s]|[\dIlOo/]{1,3}[ºo°ª]?)?[ \t]*[\-–—=~.]?[ \t]*)"
    r"(?=(?:Esta|Este|Fica|Ficam|Revogam|Revoga|VETAD\w*|Os|As|Cabe|Caber\w*|"
    r"Somente|Para)\b)"
)
# The closing caput as OCR runs its words together ("entraem vigorna data").
_FINAL_LOOSE = re.compile(r"\bentr\w*\s*em\s*vigor|\brevogam-se", re.IGNORECASE)
_ART_GARBLE_TAIL = re.compile(
    r"(?m)^[ \t_]*(?P<word>[AÁVaá]?[a-zA-Z]{2,4}[.,:;»«™\-]{0,2}[ \t]*"
    r"(?:[^\w\s]|[\dIlOo/]{1,3}[ºo°ª]?|e)?[ \t]*[\-–—=~.]?[ \t]*)"
    r"(?=(?:Esta|Este|Revogam|Revoga)\b)"
)
_FINAL_CLAUSE = re.compile(r"vigo|revog", re.IGNORECASE)
_ENUM_LEFT = re.compile(r";\s*(?:(?:e|ou)\s*)?$")
_LEAD = re.compile(r"\s*[.\-–—:]{0,2}\s*")
_WORDING = re.compile(r"reda[cç][aã]o|redigid", re.IGNORECASE)
_BARE_HEAD = re.compile(r"(?:Art|AH|Arl|Aft|§|\$\s?\d|Par[áa]grafo)")
_NR = re.compile(r"\(\s?(?:NR|AC)\s?\)")
_BODY_END = re.compile(
    r"(?:^|\s)(?:Pal[áa]cio\s+do\s+Governo|Pal[áa]cio\s+[A-Z]\w+|Bras[ií]lia,\s+\d"
    r"|Porto\s+Velho,\s+\d)|(?m:^[ \t\W]{0,6}A\s?N\s?E\s?X\s?O\b)"
)

_ART_HEAD = re.compile(r"\s{0,2}(?:Art|AH|Arl|Aft)\b")
_MARGIN = 3  # stray characters tolerated before a marker at the start of a line
_SUB_LEVELS = ("paragrafo", "inciso", "alinea", "item")
_LEVELS = ("artigo", *_SUB_LEVELS)
_TOKEN = {
    "artigo": "art",
    "paragrafo": "par",
    "inciso": "inc",
    "alinea": "ali",
    "item": "item",
}


class Node(TypedDict):
    """One dispositivo. Offsets index the original text; nothing is rewritten."""

    id: int
    kind: str  # artigo | paragrafo | inciso | alinea | item | quoted_block
    number: int | None  # the chosen reading (None for a quoted block)
    suffix: str | None
    path: str | None  # docs/SCHEMA.md §4.2 token path, e.g. "art-5-par-2-inc-3"
    raw: str  # the marker exactly as it appears in the text
    start: int  # start of the marker
    text_start: int  # start of the node's own text (after the marker)
    text_end: int  # end of the node's own text (before its first child)
    end: int  # end of the whole subtree
    parent: int | None
    children: list[int]
    status: str  # own | quoted
    corrected: bool  # the chosen reading differs from the literal one
    # How the number was read: "literal" (as printed), "confusion" (a known OCR
    # look-alike, chosen by the chain), "gap" (unreadable or contradictory glyphs, read
    # only because exactly one number was missing around it) or "quoted".
    read_by: str


class Leftover(TypedDict):
    """A marker-shaped candidate that did not become a node."""

    kind: str
    start: int
    end: int
    raw: str
    status: str  # unexplained | reference | quoted | ignored
    scope: int | None  # id of the node whose scope it sits in
    # For an unexplained candidate, how it relates to the chain of its scope:
    # "duplicate" (a number the chain already has), "ahead" (beyond the chain's end),
    # "out_of_order" (a missing number, in the wrong place), "unreadable" (no reading)
    # or "no_chain" (the scope has no chain at all). Empty otherwise.
    hint: str


class ScopeReport(TypedDict):
    kind: str
    parent: int | None
    count: int
    last: int
    missing: list[int]
    unexplained: int
    conflict: bool  # "Parágrafo único" together with numbered paragraphs
    closes: bool


class LevelReport(TypedDict):
    nodes: int
    corrected: int
    scopes: int
    open_scopes: int
    missing: int
    unexplained: int
    closes: bool


class QuotedBlock(TypedDict):
    start: int
    end: int
    opened_by: str  # mark | cue
    closed: bool  # a closing quotation mark was found
    node: int


class HierarchyReport(TypedDict):
    nodes: list[Node]
    leftovers: list[Leftover]
    scopes: list[ScopeReport]
    levels: dict[str, LevelReport]
    quoted_blocks: list[QuotedBlock]
    body_end: int
    # An unclosed quoted block runs to the end of the body: host articles after it, if
    # any, cannot be told from the quoted ones. Keeps the article level open.
    open_tail_block: bool
    # The last own article carries the vigência or revogação clause, as a complete norm
    # does. Presence only: not part of `closes`. Read `closes and final_clause` as the
    # stricter verdict, or prefer `closes`, which now requires the two checks below.
    final_clause: bool
    # Every vigência/revogação sentence in the body opens an article the reader read (or
    # a prose line), never a line whose article marker was lost ("Art. T. Esta Lei...").
    # Part of the article-level `closes`.
    final_clause_placed: bool
    # Nothing after the last own article opens as an article the reader did not read
    # ("Art. T." or "49 - Revogam-se" with the next number expected). Part of `closes`.
    tail_clean: bool
    closes: bool


@dataclass(frozen=True, slots=True)
class _Cand:
    start: int
    end: int
    readings: tuple[int, ...]
    suffix: str | None = None
    strong: bool = True  # sits where a marker sits: unexplained when left over
    literal: int | None = None  # what the marker says when read at face value
    tail: bool = False  # weak, but unexplained when left over beside a chain
    ref: bool = False  # an in-sentence citation, decided before any chain
    unico: bool = False
    digit: bool = False  # an arabic token read as roman ("1 -" as I)


# --- readings -------------------------------------------------------------------------
def _roman(n: int) -> str:
    out = []
    for value, glyph in (
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ):
        while n >= value:
            out.append(glyph)
            n -= value
    return "".join(out)


_ROMAN_VALUE = {_roman(n): n for n in range(1, _MAX_ROMAN + 1)}


@lru_cache(maxsize=4096)
def roman_readings(token: str) -> tuple[int, ...]:
    """Plausible inciso numbers for a raw token, literal reading first.

    "HI" and "IH" read III, "11" reads II, "lV" reads IV. A token that is no roman
    numeral under any glyph substitution has no reading.
    """
    options = [_ROMAN_GLYPHS.get(ch) for ch in token]
    if any(o is None for o in options):
        return ()
    out: list[int] = []
    for combo in product(*(o for o in options if o is not None)):
        value = _ROMAN_VALUE.get("".join(combo))
        if value is not None and value not in out:
            out.append(value)
    return tuple(out)


def alinea_readings(letter: str) -> tuple[int, ...]:
    """Plausible alínea positions (a=1) for a raw glyph, literal reading first."""
    glyphs = _ALI_GLYPHS.get(letter.lower(), letter.lower())
    return tuple(ord(g) - 96 for g in glyphs if "a" <= g <= "z")


# --- position helpers -----------------------------------------------------------------
def _at_line_start(text: str, pos: int) -> bool:
    """True when at most a few stray characters precede ``pos`` on its line."""
    lo = max(0, pos - 40)
    k = text.rfind("\n", lo, pos)
    if k < 0 and lo > 0:
        return False
    return len(text[k + 1 : pos].strip()) <= _MARGIN


def _after_break(text: str, pos: int) -> bool:
    """True when sentence punctuation or a quotation mark precedes ``pos``."""
    left = text[max(0, pos - 6) : pos].rstrip()
    return bool(left) and (left[-1] in ".;:" or left[-1] in _QUOTES)


def _in_enumeration(text: str, pos: int) -> bool:
    """True when the previous element of a list ends right before ``pos``.

    "…; e" or "…;" before a line means the enumeration goes on: whatever opens that
    line is the next marker, however the OCR spelled it.
    """
    return _ENUM_LEFT.search(text[max(0, pos - 12) : pos]) is not None


def _left(text: str, pos: int, width: int = 16) -> str:
    return text[max(0, pos - width) : pos]


# --- candidate finders ----------------------------------------------------------------
def _paragraph_candidates(text: str) -> list[_Cand]:
    out: list[_Cand] = []
    for m in _PAR.finditer(text):
        glyph = m.group("glyph")
        has_ord = m.group("ord") is not None
        readings = tuple(article_readings(m.group("num"), has_ord))
        if not readings:
            continue
        sign = glyph in "§$"
        line_start = _at_line_start(text, m.start())
        if not sign:
            # A look-alike glyph ("S", "8", "94", "q") needs the line start and an
            # ordinal sign; the classic ones also pass with an ordinal read as a digit.
            ordinal = m.group("ord") or ""
            classic = glyph in "S895&" and (has_ord or len(readings) > 1)
            if not line_start or not (classic or ordinal[-1:] in ("º", "°")):
                continue
        # "§ 2º do art. 5º" is a citation wherever it sits; a citing word on the left
        # only counts inside a line (a marker follows the previous line's last word).
        ref = bool(_REF_RIGHT_PAR.match(text, m.end(), m.end() + 12)) or (
            not line_start and bool(_REF_LEFT_PAR.search(_left(text, m.start())))
        )
        out.append(
            _Cand(
                m.start(),
                m.end(),
                readings,
                suffix=m.group("suffix"),
                # A look-alike glyph is only accepted at a line start with an ordinal
                # sign, which is already where and how a paragraph marker sits.
                strong=not sign or line_start or _after_break(text, m.start()),
                literal=readings[0] if glyph == "§" else None,
                ref=ref,
            )
        )
    for m in _PAR_UNICO.finditer(text):
        line_start = _at_line_start(text, m.start())
        if m.group(0)[0] != "P":
            continue  # "passando o parágrafo único a ser § 1º": prose, not a marker
        ref = bool(_REF_RIGHT_PAR.match(text, m.end(), m.end() + 12)) or (
            not line_start and bool(_REF_LEFT_PAR.search(_left(text, m.start())))
        )
        out.append(_Cand(m.start(), m.end(), (1,), literal=1, ref=ref, unico=True))
    taken = {c.start for c in out}
    for m in _PAR_WILD.finditer(text):
        if m.start() not in taken and _at_line_start(text, m.start()):
            # A paragraph sign at the start of a line is a marker even when its number
            # is unreadable: left over, it keeps the scope open.
            out.append(_Cand(m.start(), m.end(), ()))
    out.sort(key=lambda c: c.start)
    return out


def _inciso_candidates(text: str) -> list[_Cand]:
    out: list[_Cand] = []
    for m in _INC.finditer(text):
        token = m.group("tok")
        readings = roman_readings(token)
        pure = _PURE_ROMAN.match(token) is not None and bool(readings)
        dash = _STRONG_SEP.match(m.group("sep")) is not None
        line_start = _at_line_start(text, m.start())
        # An OCR look-alike, or a weak separator ("I." may be an initial), is only a
        # candidate where a marker would sit.
        if (not pure or not dash) and not line_start:
            continue
        if m.group("sep") == ")" and not pure:
            continue  # "i)", "l)", "1)" are alíneas, never incisos
        glued = m.end() < len(text) and not text[m.end()].isspace()
        if glued and not (line_start and dash):
            continue  # "I-A", "V-se": only a line start makes a glued dash a marker
        if not line_start and token in ("C", "L"):
            continue  # "C -" / "L -" inside a sentence is an enumeration letter
        out.append(
            _Cand(
                m.start(),
                m.end(),
                readings,
                # Unreadable tokens, digits and lowercase look-alikes are too common
                # as page noise to be held against the norm when left over.
                strong=_in_enumeration(text, m.start())
                or (
                    dash
                    and bool(readings)
                    and (
                        (
                            _HAS_ROMAN_CAPITAL.search(token) is not None
                            and (line_start or _after_break(text, m.start()))
                        )
                        # "| — declarar": a look-alike that opens a line of prose.
                        or (
                            not token.isdigit()
                            and _PROSE.match(text, m.end()) is not None
                        )
                    )
                ),
                literal=readings[0] if pure else None,
                ref=bool(_REF_LEFT_INC.search(_left(text, m.start(), 20))),
                digit=token.isdigit(),
                tail=dash and line_start and bool(readings),
            )
        )
    taken = {c.start for c in out}
    for m in _INC_WILD.finditer(text):
        start, end = m.start("tok"), m.end("mark")
        token = m.group("tok")
        if start in taken or token.isdigit():
            continue
        if token.islower() and not m.group("gap"):
            continue  # "auto-sustentável" broken across lines
        # "WI —" after "II — …; e": unreadable, but the list plainly goes on.
        out.append(_Cand(start, end, (), strong=_in_enumeration(text, start)))
    out.sort(key=lambda c: c.start)
    return out


def _alinea_candidates(text: str) -> list[_Cand]:
    out: list[_Cand] = []
    for m in _ALI.finditer(text):
        letter = m.group("let")
        line_start = _at_line_start(text, m.start())
        if not letter.islower() and not line_start:
            continue
        readings = alinea_readings(letter)
        if not readings:
            continue
        out.append(
            _Cand(
                m.start(),
                m.end(),
                readings,
                strong=letter.islower()
                and (line_start or _after_break(text, m.start())),
                literal=ord(letter) - 96 if letter.islower() else None,
                ref=bool(_REF_LEFT_ALI.search(_left(text, m.start()))),
            )
        )
    taken = {c.start for c in out}
    for m in _ALI_WILD.finditer(text):
        start = m.start("tok")
        if start in taken or not _in_enumeration(text, start):
            continue
        # "1)" for "i)" or "l)", "))" for "j)": the list goes on, the letter is lost.
        token = m.group("tok")
        readings = (12, 9) if token == "1" else ()
        out.append(_Cand(start, m.end(), readings))
    out.sort(key=lambda c: c.start)
    return out


def _item_candidates(text: str) -> list[_Cand]:
    out: list[_Cand] = []
    for m in _ITEM.finditer(text):
        start = m.start("num")
        out.append(
            _Cand(
                start,
                m.end(),
                (int(m.group("num")),),
                strong=False,
                literal=int(m.group("num")),
                digit=True,
            )
        )
    return out


# --- quoted blocks --------------------------------------------------------------------
def _is_opening(text: str, k: int) -> bool:
    before = text[k - 1] if k > 0 else "\n"
    after = text[k + 1] if k + 1 < len(text) else " "
    if text[k] == "“":
        return True
    return (before.isspace() or before in ":(") and not after.isspace()


def _is_spaced_opening(text: str, k: int) -> bool:
    """A straight quote on its own, right before an article marker ('" Art. 1Q')."""
    before = text[k - 1] if k > 0 else "\n"
    return (
        text[k] == '"'
        and before.isspace()
        and _CUE_COLON.search(text[max(0, k - 120) : k]) is not None
        and _ART_HEAD.match(text, k + 1) is not None
    )


def _is_closing(text: str, k: int) -> bool:
    before = text[k - 1] if k > 0 else "\n"
    after = text[k + 1] if k + 1 < len(text) else " "
    if text[k] == "”" and not before.isspace():
        return True
    return not before.isspace() and (after.isspace() or after in ".,;)(")


def _article_reading(text: str, pos: int) -> int | None:
    m = ARTICLE_CANDIDATE.match(text, pos)
    if m is None:
        return None
    readings = article_readings(m.group("num"), m.group("ord") is not None)
    return readings[0] if readings else None


def _extended_close(
    text: str, k: int, limit: int, body_end: int, later_starts: Sequence[int]
) -> int | None:
    """End of a quote block that closes after the next first-pass own article."""
    depth = 1
    close = None
    for q in _QUOTE_CHAR.finditer(text, k + 1, body_end):
        j = q.start()
        if _is_closing(text, j):
            depth -= 1
            if depth == 0:
                close = j + 1
                break
        elif _is_opening(text, j):
            depth += 1
    if close is None:
        return None
    swallowed = {
        _article_reading(text, s) for s in later_starts if limit <= s < close
    } - {None}
    after = ARTICLE_CANDIDATE.search(text, close, body_end)
    if not swallowed or after is None:
        return None
    if after.start() - close > 400:
        return None
    # A short run swallowed: a long one is a second run of the host's own articles.
    if len(swallowed) > 6:
        return None
    return close if _article_reading(text, after.start()) in swallowed else None


def find_quoted_blocks(
    text: str, own_starts: Sequence[int], body_end: int
) -> list[tuple[int, int, str, bool]]:
    """Locate text quoted from another norm: ``(start, end, opened_by, closed)``.

    A block opens at a quotation mark followed by a structural marker, when the host
    article has used amending vocabulary before it (or the marker is an article, which
    a norm never quotes from itself). It also opens, without any mark, at an article
    marker right after "…a seguinte redação:" (``opened_by="cue"``): OCR drops quotation
    marks often. It closes at the matching closing mark, else at the last "(NR)", else
    at the next own article (``closed=False``).
    """
    blocks: list[tuple[int, int, str, bool]] = []
    if not own_starts:
        return blocks
    openings: list[tuple[int, str]] = []
    for m in _QUOTE_CHAR.finditer(text, own_starts[0], body_end):
        k = m.start()
        if not _is_opening(text, k) and not _is_spaced_opening(text, k):
            continue
        head = _BLOCK_HEAD.match(text, k + 1)
        if head is None and not _CUE_COLON.search(text[max(0, k - 120) : k]):
            continue
        openings.append((k, "mark"))
    for m in _CUE_THEN.finditer(text, own_starts[0], body_end):
        if m.end() < len(text) and text[m.end()] in _QUOTES:
            continue  # opened by its mark, above
        # "…a seguinte redação:" is followed by the new wording whatever it looks like
        # (often a dotted elision line); the looser cues need a marker to follow, since
        # "com as seguintes alterações:" may also introduce the host's own incisos.
        wording = _WORDING.search(m.group(0)) is not None
        if wording or _BARE_HEAD.match(text, m.end()):
            openings.append((m.end(), "cue"))
    openings.sort()

    covered = 0
    for k, opened_by in openings:
        if k < covered:
            continue
        idx = bisect_right(own_starts, k)
        if idx == 0:
            continue
        host_start = own_starts[idx - 1]
        limit = own_starts[idx] if idx < len(own_starts) else body_end
        if opened_by == "mark":
            is_article = bool(_ART_HEAD.match(text, k + 1))
            if not is_article and not _AMEND_CUE.search(text, host_start, k):
                continue
        end, closed = limit, False
        # A block opened by its cue lost only the opening mark: the closing one is
        # looked for all the same.
        depth = 1
        for q in _QUOTE_CHAR.finditer(text, k + 1, limit):
            j = q.start()
            if _is_closing(text, j):
                depth -= 1
                if depth == 0:
                    end, closed = j + 1, True
                    break
            elif _is_opening(text, j):
                depth += 1
        if not closed and idx < len(own_starts):
            # The block may run past the next "own" article: that article is then a
            # quoted one that took the host's number. Only when the mark closes the
            # block and the first article after it repeats a swallowed number.
            ext = _extended_close(text, k, limit, body_end, own_starts[idx:])
            if ext is not None:
                end, closed = ext, True
        if not closed:
            # "(NR)" ends a rewritten dispositivo even when the mark was lost.
            marks = list(_NR.finditer(text, k, limit))
            if marks:
                end, closed = marks[-1].end(), True
        if end - k < 4:
            continue
        blocks.append((k, end, opened_by, closed))
        covered = end
    blocks.extend(_unopened_blocks(text, own_starts, body_end, blocks))
    blocks.sort()
    return blocks


def _unopened_blocks(
    text: str,
    own_starts: Sequence[int],
    body_end: int,
    blocks: Sequence[tuple[int, int, str, bool]],
) -> list[tuple[int, int, str, bool]]:
    """Blocks that lost their opening mark but still close: ``registro”.``

    A closing mark that matches no opening one ends a block quoted from another norm.
    The host's own chain resumes right after it: the first article marker after the
    mark repeats the number following one of the host articles before the block. The
    articles between that host article and the mark are the quoted ones.
    """
    out: list[tuple[int, int, str, bool]] = []
    if not own_starts:
        return out
    spans = [(s, e) for s, e, _, _ in blocks]
    depth = 0
    for m in _QUOTE_CHAR.finditer(text, own_starts[0], body_end):
        j = m.start()
        if any(s <= j < e for s, e in spans):
            continue
        if not _is_closing(text, j):
            if _is_opening(text, j):
                depth += 1
            continue
        if depth > 0:
            depth -= 1
            continue
        after = ARTICLE_CANDIDATE.search(text, j + 1, body_end)
        if after is None or after.start() - j > 400:
            continue
        resume = _article_reading(text, after.start())
        before = [
            st for st in own_starts if st < j and not any(s <= st < e for s, e in spans)
        ]
        for pos in range(len(before) - 2, -1, -1):
            if _article_reading(text, before[pos]) == (resume or 0) - 1:
                first_quoted = before[pos + 1]
                if _article_reading(text, first_quoted) != resume:
                    out.append((first_quoted, j + 1, "unopened", True))
                    spans.append((first_quoted, j + 1))
                break
    return out


# --- tree builder ---------------------------------------------------------------------
class _Builder:
    def __init__(self, text: str) -> None:
        self.text = text
        self.nodes: list[Node] = []
        self.leftovers: list[Leftover] = []
        self.scopes: list[ScopeReport] = []
        self.masked: list[tuple[int, int]] = []
        self.pending: list[tuple[Leftover, int]] = []
        self.cands: dict[str, list[_Cand]] = {
            "paragrafo": _paragraph_candidates(text),
            "inciso": _inciso_candidates(text),
            "alinea": _alinea_candidates(text),
            "item": _item_candidates(text),
        }
        self.starts = {k: [c.start for c in v] for k, v in self.cands.items()}

    def add_node(
        self,
        kind: str,
        cand_start: int,
        cand_end: int,
        end: int,
        number: int | None,
        suffix: str | None,
        parent: int | None,
        status: str,
        corrected: bool,
        unico: bool = False,
        gap: bool = False,
    ) -> int:
        text = self.text
        # The node's own text starts after the marker and its separator ("Art. 2º - A
        # lei", "Parágrafo único. O prazo").
        lead = _LEAD.match(text, cand_end, end)
        text_start = lead.end() if lead else cand_end
        path: str | None = None
        if kind != "quoted_block" and number is not None:
            if unico:
                token = "par-unico"
            elif kind == "alinea":
                token = f"ali-{chr(96 + number)}"
            else:
                token = f"{_TOKEN[kind]}-{number}"
            if suffix:
                token += f"-{suffix.lower()}"
            base = self.nodes[parent]["path"] if parent is not None else None
            path = f"{base}-{token}" if base else token
        node: Node = {
            "id": len(self.nodes),
            "kind": kind,
            "number": number,
            "suffix": suffix,
            "path": path,
            "raw": text[cand_start:cand_end],
            "start": cand_start,
            "text_start": text_start,
            "text_end": end,
            "end": end,
            "parent": parent,
            "children": [],
            "status": status,
            "corrected": corrected,
            "read_by": "quoted"
            if status == "quoted"
            else "gap"
            if gap
            else "confusion"
            if corrected
            else "literal",
        }
        self.nodes.append(node)
        if parent is not None:
            self.nodes[parent]["children"].append(node["id"])
        return node["id"]

    def settle(self) -> None:
        """Decide the marker-shaped leftovers once every level has been read.

        A leftover that a deeper level turned into a node is explained ("1 -" is no
        inciso, it is an item; "i)" is no inciso, it is an alínea). Every other one is
        unexplained and keeps its scope open: "11 —" after "I —" and "II —" is most
        likely III with a stroke lost, so the chain that ends at II must not close.
        """
        explained = {n["start"] for n in self.nodes if n["kind"] != "quoted_block"}
        for leftover, scope_index in self.pending:
            if leftover["start"] in explained:
                continue
            leftover["status"] = "unexplained"
            scope = self.scopes[scope_index]
            scope["unexplained"] += 1
            scope["closes"] = False
        self.scopes = [s for s in self.scopes if s["count"] or s["unexplained"]]

    def _slice(self, kind: str, lo: int, hi: int, lenient: bool) -> list[_Cand]:
        starts = self.starts[kind]
        cands = self.cands[kind][bisect_left(starts, lo) : bisect_left(starts, hi)]
        if lenient or not self.masked:
            return cands
        return [c for c in cands if not self._is_masked(c.start)]

    def _is_masked(self, pos: int) -> bool:
        k = bisect_right(self.masked, (pos, 1 << 62)) - 1
        return k >= 0 and self.masked[k][0] <= pos < self.masked[k][1]

    def descend(
        self, lo: int, hi: int, parent: int | None, level: int, lenient: bool
    ) -> None:
        """Read level ``level`` inside ``[lo, hi)``, then recurse into each part."""
        if level >= len(_SUB_LEVELS) or lo >= hi:
            return
        kind = _SUB_LEVELS[level]
        cands = self._slice(kind, lo, hi, lenient)
        if not cands:
            self.descend(lo, hi, parent, level + 1, lenient)
            return

        arabic = self._arabic_lists(cands, lo, hi, lenient) if kind == "inciso" else ()
        readings: list[tuple[int, ...]] = [
            () if c.ref or c.start in arabic else c.readings for c in cands
        ]
        chosen = best_chain(
            readings,
            [c.suffix is not None for c in cands],
            anchored=not lenient,
            free_skips=_ALI_FREE_SKIPS if kind == "alinea" else frozenset(),
        )
        free_skips = _ALI_FREE_SKIPS if kind == "alinea" else frozenset()
        filled = (
            _fill_single_gaps(cands, chosen, free_skips) if not lenient else frozenset()
        )
        members = [i for i, v in enumerate(chosen) if v is not None]
        values = [v for v in chosen if v is not None]
        keep = bool(members)
        if (
            keep
            and not lenient
            and kind != "item"
            and not any(cands[i].strong for i in members)
        ):
            # Nothing in the chain sits where a marker sits. Only a run that starts at
            # 1 without a gap ("1 -", "11 -", "111 -" for I, II, III) is still a chain.
            keep = len(values) >= 2 and values == list(range(1, len(values) + 1))
        if keep and kind == "item":
            keep = len(values) >= 2 and values == list(range(1, len(values) + 1))
        if not keep:
            chosen = [None] * len(cands)
            members, values = [], []

        status = "quoted" if lenient else "own"
        pending: list[Leftover] = []
        for i, c in enumerate(cands):
            if chosen[i] is not None:
                continue
            if c.ref:
                left = "reference"
            elif lenient:
                left = "quoted"
            else:
                left = "ignored"
            leftover: Leftover = {
                "kind": kind,
                "start": c.start,
                "end": c.end,
                "raw": self.text[c.start : c.end],
                "status": left,
                "scope": parent,
                "hint": _hint(c.readings, values),
            }
            self.leftovers.append(leftover)
            # A marker-shaped leftover keeps its scope open, unless a deeper level
            # explains it ("1 -" left by the incisos, read as an item): decided in
            # `settle`, once the whole tree is built.
            if left == "ignored" and (c.strong or (c.tail and members)):
                pending.append(leftover)

        if not lenient and (members or pending):
            present = set(values)
            last = max(present) if present else 0
            skips = _ALI_FREE_SKIPS if kind == "alinea" else frozenset()
            missing = [
                k for k in range(1, last + 1) if k not in present and k not in skips
            ]
            conflict = len(members) > 1 and any(cands[i].unico for i in members)
            self.pending.extend((left_, len(self.scopes)) for left_ in pending)
            self.scopes.append(
                {
                    "kind": kind,
                    "parent": parent,
                    "count": len(members),
                    "last": last,
                    "missing": missing,
                    "unexplained": 0,
                    "conflict": conflict,
                    "closes": not missing and not conflict,
                }
            )

        if not members:
            self.descend(lo, hi, parent, level + 1, lenient)
            return
        self.descend(lo, cands[members[0]].start, parent, level + 1, lenient)
        for pos, i in enumerate(members):
            c = cands[i]
            value = chosen[i]
            end = cands[members[pos + 1]].start if pos + 1 < len(members) else hi
            node = self.add_node(
                kind,
                c.start,
                c.end,
                end,
                value,
                c.suffix,
                parent,
                status,
                corrected=value != c.literal,
                unico=c.unico,
                gap=i in filled,
            )
            self.descend(c.end, end, node, level + 1, lenient)

    def _arabic_lists(
        self, cands: Sequence[_Cand], lo: int, hi: int, lenient: bool
    ) -> frozenset[int]:
        """Starts of "1 -" candidates that open an arabic list, not inciso I.

        "1 -" is read as I when "II -" follows; when "2 -" follows first, it is the
        first item of a numbered list.
        """
        items = self._slice("item", lo, hi, lenient)
        twos = [i.start for i in items if self.text[i.start] == "2"]
        if not twos:
            return frozenset()
        romans = [c.start for c in cands if c.readings and not c.digit]
        out: set[int] = set()
        for c in cands:
            if not c.digit:
                continue
            two = next((t for t in twos if t > c.start), None)
            roman = next((r for r in romans if r > c.start), None)
            if two is not None and (roman is None or two < roman):
                out.add(c.start)
        return frozenset(out)

    def quoted_block(self, start: int, end: int, parent: int | None) -> int:
        """Read a quoted block as its own subtree (chains may start anywhere)."""
        block = self.add_node(
            "quoted_block", start, start, end, None, None, parent, "quoted", False
        )
        arts = [
            m
            for m in ARTICLE_CANDIDATE.finditer(self.text, start, end)
            if article_readings(m.group("num"), m.group("ord") is not None)
        ]
        if not arts:
            self.descend(start, end, block, 0, True)
            return block
        self.descend(start, arts[0].start(), block, 0, True)
        for pos, m in enumerate(arts):
            art_end = arts[pos + 1].start() if pos + 1 < len(arts) else end
            number = article_readings(m.group("num"), m.group("ord") is not None)[0]
            marker_end, suffix = _article_marker_end(self.text, m.start(), m.end())
            node = self.add_node(
                "artigo",
                m.start(),
                marker_end,
                art_end,
                number,
                suffix,
                block,
                "quoted",
                False,
            )
            self.descend(marker_end, art_end, node, 0, True)
        return block

    def deepest_at(self, pos: int, roots: Sequence[int]) -> int | None:
        """The deepest own node whose subtree contains ``pos``."""
        found: int | None = None
        level = list(roots)
        while level:
            hit = next(
                (
                    n
                    for n in level
                    if self.nodes[n]["start"] <= pos < self.nodes[n]["end"]
                    and self.nodes[n]["status"] == "own"
                ),
                None,
            )
            if hit is None:
                break
            found = hit
            level = self.nodes[hit]["children"]
        return found


def _fill_single_gaps(
    cands: Sequence[_Cand], chosen: list[int | None], free_skips: frozenset[int]
) -> frozenset[int]:
    """Read a lone leftover between k-1 and k+1 as k, whatever its glyphs say.

    "VII -" printed twice between VI and IX, or "NI —" between II and IV: when exactly
    one number is missing between two chain neighbours and exactly one candidate sits
    between them, the sequence decides the reading. Two leftovers in the gap, or two
    missing numbers, stay open. Returns the indices it filled.
    """
    filled: set[int] = set()
    members = [i for i, v in enumerate(chosen) if v is not None]
    for a, b in zip(members, members[1:]):
        lo, hi = chosen[a], chosen[b]
        if lo is None or hi is None:
            continue
        absent = [k for k in range(lo + 1, hi) if k not in free_skips]
        if len(absent) != 1:
            continue
        between = [i for i in range(a + 1, b) if not cands[i].ref]
        if len(between) == 1 and not cands[between[0]].unico:
            if cands[between[0]].digit:
                continue  # "1 -" between II and IV is a list item, not III
            chosen[between[0]] = absent[0]
            filled.add(between[0])
    return frozenset(filled)


def _hint(readings: Sequence[int], chain: Sequence[int]) -> str:
    """How a leftover candidate relates to the chain it did not join."""
    if not readings:
        return "unreadable"
    if not chain:
        return "no_chain"
    if any(r in chain for r in readings):
        return "duplicate"
    if min(readings) > max(chain):
        return "ahead"
    return "out_of_order"


def _article_numbers(text: str, start: int) -> list[int]:
    m = ARTICLE_CANDIDATE.match(text, start)
    if m is None:
        return []
    return article_readings(m.group("num"), m.group("ord") is not None)


def _article_marker_end(text: str, start: int, fallback: int) -> tuple[int, str | None]:
    """End of an article marker proper, and its letter suffix if it really has one.

    The suffix rule ("Art. 8º-A" yes, "Art. 2º - A lei" no) lives in
    ``ARTICLE_CANDIDATE``, so both readers agree on it.
    """
    m = ARTICLE_CANDIDATE.match(text, start)
    if m is None:
        return fallback, None
    suffix = m.group("suffix")
    if suffix is not None:
        return m.end(), suffix
    return (m.end("ord") if m.group("ord") is not None else m.end("num")), None


def _fill_article_gaps(
    text: str, articles: list[ArticleRead], masked: Sequence[tuple[int, int]]
) -> tuple[list[ArticleRead], frozenset[int]]:
    """Read a lone garbled article marker between Art. k-1 and Art. k+1 as Art. k.

    The article reader only sees "Art" + a number-like token. When the word itself is
    garbled ("Ait. 5o", "At. T", "Apt. 20", a lowercase "art. 30") or a number is
    printed twice, the marker is left out and the chain shows a single gap. If exactly
    one such candidate sits in that gap, the sequence reads it.
    """
    out = list(articles)
    own = [a for a in out if a["status"] == "own" and a["number"] is not None]
    known = {a["start"] for a in out}
    added: list[ArticleRead] = []
    filled: set[int] = set()
    for a, b in zip(own, own[1:]):
        if a["number"] is None or b["number"] is None:
            continue
        if b["number"] - a["number"] != 2:
            continue
        between = [
            x for x in out if a["start"] < x["start"] < b["start"] and x is not b
        ]
        if any(x["status"] == "own" for x in between):
            continue
        loose = [x for x in between if x["status"] == "unexplained"]
        loose += [
            x
            for x in between
            if x["status"] == "reference"
            and _opens_line(text, x["start"])
            and _reads_as(text, x["start"], a["number"] + 1)
        ]
        wild = [
            m
            for m in _ART_WILD.finditer(text, a["end"], b["start"])
            if m.start("word") not in known
            and not any(lo <= m.start() < hi for lo, hi in masked)
            and not is_reference(text, m.start("word"))
        ]
        garbled = [
            m
            for m in _ART_GARBLE.finditer(text, a["end"], b["start"])
            if m.start("word") not in known
            and m.start("word") not in {w.start("word") for w in wild}
            and not any(lo <= m.start() < hi for lo, hi in masked)
            and not is_reference(text, m.start("word"))
        ]
        if not loose and not wild:
            wild = garbled  # only when nothing sharper sits in the gap
        if len(loose) + len(wild) != 1:
            continue
        if loose:
            loose[0]["status"] = "own"
            loose[0]["number"] = a["number"] + 1
            loose[0]["corrected"] = True
            filled.add(loose[0]["start"])
        else:
            m = wild[0]
            added.append(
                {
                    "start": m.start("word"),
                    "end": m.end(),
                    "raw": text[m.start("word") : m.end()],
                    "number": a["number"] + 1,
                    "suffix": None,
                    "status": "own",
                    "corrected": True,
                }
            )
    head = _head_article(text, out, masked, known)
    if head is not None:
        if head["start"] in known:
            filled.add(head["start"])
        else:
            added.append(head)
    tail = _tail_article(text, out, masked, known)
    if tail is not None:
        if tail["start"] in known:
            filled.add(tail["start"])
        else:
            added.append(tail)
    out.extend(added)
    out.sort(key=lambda x: x["start"])
    return out, frozenset(filled | {x["start"] for x in added})


_ENACTING = re.compile(
    r"(?:\bLei(?:\s+Complementar)?|Decreto|Resolu\S+|decreta|promulga)"
    r"\s*[:;.,]?[ \t]*\n",
    re.IGNORECASE,
)
_HEAD_LINE = re.compile(
    r"[ \t]*(?P<word>[^\w\n]{0,2}[AaÁEe][A-Za-zÀ-ÿ]{0,5}\b(?:[^\n]|\n[ \t]*){0,30}?)"
    r"(?=\b(?:[FPTBfptb]i[cç]a[ms]?|autoriz\w*|institu\w*|declar\w*|cria\w*)\b)"
)


def _head_article(
    text: str,
    articles: list[ArticleRead],
    masked: Sequence[tuple[int, int]],
    known: set[int],
) -> ArticleRead | None:
    """Read the unreadable opening line after the enacting formula as Art. 1.

    "Seguinte Lei:" is followed by "Art. 1º - Fica ..."; when OCR ruins the article
    word and its number ("Apt. Lo pica O Governo", "Ages NO — Ficas instituido") the
    chain starts at 2. If that line, the first one after the formula, carries an
    article-like opener and the verb of an opening caput, the sequence reads it as 1.
    """
    own = [a for a in articles if a["status"] == "own" and a["number"] is not None]
    if not own or own[0]["number"] != 2:
        return None
    first = own[0]
    formula = None
    for f in _ENACTING.finditer(text, 0, first["start"]):
        formula = f
    if formula is None:
        return None
    line = formula.end()
    while line < first["start"] and text[line] in " \t\n":
        line += 1
    m = _HEAD_LINE.match(text, line)
    if m is None or m.end() > first["start"]:
        return None
    if line in known:
        loose = [a for a in articles if a["start"] == line]
        if len(loose) != 1 or loose[0]["status"] != "unexplained":
            return None
        loose[0]["status"] = "own"
        loose[0]["number"] = 1
        loose[0]["corrected"] = True
        return loose[0]
    if any(lo <= line < hi for lo, hi in masked):
        return None
    if any(a["start"] < first["start"] and a["start"] != line for a in articles):
        return None
    end = m.end("word")
    return {
        "start": line,
        "end": end,
        "raw": text[line:end],
        "number": 1,
        "suffix": None,
        "status": "own",
        "corrected": True,
    }


def _opens_line(text: str, pos: int) -> bool:
    """True when only spacing precedes ``pos`` on its line."""
    return not text[text.rfind("\n", 0, pos) + 1 : pos].strip()


def _reads_as(text: str, pos: int, number: int) -> bool:
    """True when the literal reading of the marker at ``pos`` is ``number``."""
    return _article_reading(text, pos) == number


def _tail_article(
    text: str,
    articles: list[ArticleRead],
    masked: Sequence[tuple[int, int]],
    known: set[int],
) -> ArticleRead | None:
    """Read the article marker right before the closing sentence as the next number.

    "Art. T - Revogam-se as disposições" or a lone "Art." over "Esta Lei entra em
    vigor": after the last own article, exactly one line-start article word (garbled
    or unnumbered) is followed within a few characters by the closing sentence. The
    chain only lacks that last number, so the sequence supplies it.
    """
    own = [a for a in articles if a["status"] == "own" and a["number"] is not None]
    if not own:
        return None
    last = own[-1]
    last_number = last["number"]
    if last_number is None:
        return None
    hits: list[tuple[int, int, ArticleRead | None]] = []
    for x in articles:
        if x["start"] > last["start"] and x["status"] == "unexplained":
            hits.append((x["start"], x["end"], x))
        elif (
            x["start"] > last["start"]
            and x["status"] == "reference"
            and _opens_line(text, x["start"])
            and _reads_as(text, x["start"], last_number + 1)
        ):
            hits.append((x["start"], x["end"], x))
    for m in _ART_WILD.finditer(text, last["end"]):
        st = m.start("word")
        if st not in known and not is_reference(text, st):
            hits.append((st, m.end(), None))
    if not hits:
        hits = [
            (m.start("word"), m.end(), None)
            for m in _ART_GARBLE_TAIL.finditer(text, last["end"])
            if m.start("word") not in known
        ]
    hits = [
        h
        for h in hits
        if not any(lo <= h[0] < hi for lo, hi in masked)
        and text.rfind("\n", last["end"], h[0]) != -1
        and not _QUOTE_CHAR.search(text[max(0, h[0] - 12) : h[0]])
        and not _NR.search(text[max(0, h[0] - 12) : h[0]])
    ]
    if len(hits) != 1:
        return None
    start, end, loose = hits[0]
    final = _FINAL_SENTENCE.search(text, end, end + 60) or _FINAL_LOOSE.search(
        text, end, end + 60
    )
    if final is None:
        return None
    if loose is not None:
        loose["status"] = "own"
        loose["number"] = last_number + 1
        loose["corrected"] = True
        return loose
    return {
        "start": start,
        "end": end,
        "raw": text[start:end],
        "number": last_number + 1,
        "suffix": None,
        "status": "own",
        "corrected": True,
    }


def find_body_end(text: str, last_article_start: int) -> int:
    """Where the articulated body stops: the closing formula or the first annex."""
    m = _BODY_END.search(text, last_article_start)
    return m.start() if m else len(text)


# The sentence that closes a norm, from its subject on: "Esta Lei ... entra em vigor",
# "Revogam-se as disposições em contrário". Placed by where it starts, not by where its
# keyword falls, so a long sentence is still judged by its first words.
_FINAL_SENTENCE = re.compile(
    r"\b(?:Esta|Essa|Este|Estes|Estas)\s+(?:Lei|Norma|Decreto|Portaria|Resolu\S*)\b"
    r"[^.;]{0,60}?\bentr\w*\s+em\s+vigor"
    r"|\brevog\w*(?:-se)?\s+(?:as|os|a|o)\s+disposi",
    re.IGNORECASE,
)
_BARE_ARTICLE_LINE = re.compile(
    r"[ \t]*(?:art|a\s?r/t|ait|alt|aft|arl|apt)\.?[ \t]*$", re.IGNORECASE
)
_PARAGRAPH_WORD = re.compile(r"§|par[áa]gr|[uú]nico", re.IGNORECASE)
_NOTE_MARK = re.compile(r"[()\[\]]")
# A line opener that is OCR debris rather than prose: at most three short tokens, each
# punctuation, a digit, a dotted abbreviation or a single capital ("Art. T.", "49 -").
_DEBRIS_TOKEN = re.compile(r"[\W_]*|.*\d.*|.*\..*|[A-ZÀ-Ý]")
_NUM_HEAD = re.compile(r"(?m)^[ \t]*(?P<num>\d{1,2})\s?[-–—.]\s+[A-ZÀ-Ý]")
# The article word as OCR garbles it at a line start ("Arte e Revogam-se", "Ait", "Arl").
_GARBLED_ART = re.compile(r"[AÁ][rR][tTlI]?[eEaAoO]?|Aft|Arl|Ait|Alt|Apt")


def _covered(nodes: Sequence[Node], pos: int) -> bool:
    """True when an own marker of the reader starts at or spans ``pos``."""
    return any(
        n["status"] == "own" and n["start"] <= pos < n["start"] + len(n["raw"])
        for n in nodes
    )


def _ends_marker(text: str, nodes: Sequence[Node], pos: int) -> bool:
    """True when an own marker ends just before ``pos``, with only spacing between."""
    for node in nodes:
        if node["status"] != "own":
            continue
        end = node["start"] + len(node["raw"])
        if end <= pos and pos - end <= 6 and not re.search(r"[^\W\d_]", text[end:pos]):
            return True
    return False


def _is_debris(prefix: str) -> bool:
    """True when the text before a sentence on its line is OCR debris, not prose."""
    tokens = prefix.split()
    if not 1 <= len(tokens) <= 3 or len("".join(tokens)) > 12:
        return False
    if not any(ch.isalnum() for ch in prefix):
        return False
    if _GARBLED_ART.fullmatch(tokens[0]) and all(
        tok in ("e", "ou") or _DEBRIS_TOKEN.fullmatch(tok) for tok in tokens[1:]
    ):
        return True
    return all(_DEBRIS_TOKEN.fullmatch(tok) for tok in tokens)


def _final_clause_placed(
    text: str,
    nodes: Sequence[Node],
    masked: Sequence[tuple[int, int]],
    lo: int,
    hi: int,
) -> bool:
    """A closing sentence must open an article, not sit where a lost marker would be.

    For each vigência/revogação sentence in the body (outside quoted spans): if it opens
    its line after OCR debris ("Art. T. Esta Lei ...") or opens a line whose marker the
    reader did not read, an article marker was probably lost there. A sentence that
    follows an own marker, a parenthesised note, a paragraph word or prose is fine.
    """
    for m in _FINAL_SENTENCE.finditer(text, lo, hi):
        pos = m.start()
        if any(s <= pos < e for s, e in masked):
            continue
        line = text.rfind("\n", 0, pos) + 1
        prefix = text[line:pos]
        if _ends_marker(text, nodes, pos) or _PARAGRAPH_WORD.search(prefix):
            continue
        if _NOTE_MARK.search(prefix):
            continue
        if prefix.strip() == "" or not any(ch.isalnum() for ch in prefix):
            # The sentence opens its line. Only a bare "Art." line before it means a
            # marker was lost (a plain line break inside prose is not evidence).
            if line > 0:
                prev = text.rfind("\n", 0, line - 1) + 1
                if _BARE_ARTICLE_LINE.fullmatch(text[prev : line - 1]):
                    return False
            continue
        if _is_debris(prefix):
            return False
    return True


def _tail_clean(
    text: str,
    nodes: Sequence[Node],
    masked: Sequence[tuple[int, int]],
    lo: int,
    hi: int,
    expected: int,
    known: Sequence[tuple[int, int]],
) -> bool:
    """Nothing after the last own article opens as an article the reader did not read.

    Two signatures only, both at a line start: a garbled article word followed by its
    number or letter ("Art. T."), and a bare number-dash-capital opener equal to the
    next article number ("49 - Revogam-se", with 4 expected). Anything else, including
    other numbered lines, is left alone.
    """
    for m in _ART_WILD.finditer(text, lo, hi):
        pos = m.start("word")
        if any(s <= pos < e for s, e in known) or any(s <= pos < e for s, e in masked):
            continue
        return False
    for m in _NUM_HEAD.finditer(text, lo, hi):
        pos = m.start("num")
        if int(m.group("num")) != expected or any(s <= pos < e for s, e in masked):
            continue
        if not _covered(nodes, pos):
            return False
    return True


def read_hierarchy(text: str) -> HierarchyReport:
    """Read the nested structure of one norm, resolving OCR ambiguity by sequence."""
    builder = _Builder(text)
    # An article opened by a quotation mark is never the host's own, so it is masked
    # before the first pass: otherwise it may take a place in the chain and hide the
    # host article that carries the same number.
    heads = [
        (m.start(), m.end())
        for m in ARTICLE_CANDIDATE.finditer(text)
        if m.start() > 0 and text[m.start() - 1] in _QUOTES
    ]
    first = read_articles(text, heads)
    bounds = [a["start"] for a in first["articles"] if a["status"] == "own"]
    body_end = find_body_end(text, bounds[-1]) if bounds else len(text)
    spans = find_quoted_blocks(text, bounds, body_end)
    masked = [(s, e) for s, e, _, _ in spans]
    masked += [h for h in heads if not any(s <= h[0] < e for s, e in masked)]
    masked.sort()
    second = read_articles(text, masked) if masked else first
    builder.masked = masked
    all_articles, gap_articles = _fill_article_gaps(text, second["articles"], masked)

    own = [a for a in all_articles if a["status"] == "own"]
    own_numbers = {a["number"] for a in own if a["number"] is not None}
    last_article = max(own_numbers, default=0)
    missing_articles = [k for k in range(1, last_article + 1) if k not in own_numbers]
    unexplained_articles = sum(1 for a in all_articles if a["status"] == "unexplained")
    open_tail_block = any(
        not closed and end >= body_end and (not own or start > own[-1]["start"])
        for start, end, _, closed in spans
    )
    articles_close = (
        bool(own)
        and not missing_articles
        and not unexplained_articles
        and not open_tail_block
    )
    final_clause = bool(own) and bool(
        _FINAL_CLAUSE.search(text, own[-1]["start"], body_end)
    )
    if own:
        body_end = max(find_body_end(text, own[-1]["start"]), own[-1]["end"])
    roots: list[int] = []
    for pos, art in enumerate(own):
        end = own[pos + 1]["start"] if pos + 1 < len(own) else body_end
        marker_end, suffix = _article_marker_end(text, art["start"], art["end"])
        node = builder.add_node(
            "artigo",
            art["start"],
            marker_end,
            end,
            art["number"],
            suffix,
            None,
            "own",
            art["corrected"],
            gap=art["start"] in gap_articles,
        )
        roots.append(node)
        builder.descend(marker_end, end, node, 0, False)
    for art in all_articles:
        if art["status"] not in ("own", "quoted"):
            builder.leftovers.append(
                {
                    "kind": "artigo",
                    "start": art["start"],
                    "end": art["end"],
                    "raw": art["raw"],
                    "status": art["status"],
                    "scope": None,
                    "hint": _hint(
                        tuple(_article_numbers(text, art["start"])),
                        sorted(own_numbers),
                    )
                    if art["status"] == "unexplained"
                    else "",
                }
            )

    quoted_blocks: list[QuotedBlock] = []
    for start, end, opened_by, closed in spans:
        if not own or start < own[0]["start"] or start >= body_end:
            continue
        parent = builder.deepest_at(start, roots)
        node = builder.quoted_block(start, min(end, body_end), parent)
        quoted_blocks.append(
            {
                "start": start,
                "end": min(end, body_end),
                "opened_by": opened_by,
                "closed": closed,
                "node": node,
            }
        )

    nodes = builder.nodes
    for node_ in nodes:
        first_child = min(
            (nodes[c]["start"] for c in node_["children"]), default=node_["end"]
        )
        stop = max(first_child, node_["text_start"])
        while stop > node_["text_start"] and text[stop - 1].isspace():
            stop -= 1
        node_["text_end"] = stop
        node_["children"].sort(key=lambda c: nodes[c]["start"])
    builder.settle()
    for left in builder.leftovers:
        if left["status"] != "unexplained":
            left["hint"] = ""
    builder.leftovers.sort(key=lambda left: left["start"])

    # The sequence cannot see a lost last article, so the article level also needs the
    # closing sentence to sit where an article starts and the tail to be free of
    # article markers the reader did not read.
    final_placed = True
    tail_clean = True
    if own:
        final_placed = _final_clause_placed(
            text, nodes, masked, own[0]["start"], body_end
        )
        tail_clean = _tail_clean(
            text,
            nodes,
            masked,
            own[-1]["start"],
            body_end,
            last_article + 1,
            [(a["start"], a["end"]) for a in all_articles],
        )
        articles_close = articles_close and final_placed and tail_clean

    levels: dict[str, LevelReport] = {}
    for kind in _LEVELS:
        mine = [n for n in nodes if n["kind"] == kind and n["status"] == "own"]
        if kind == "artigo":
            scopes, open_scopes = 1, 0 if articles_close else 1
            missing, unexplained = len(missing_articles), unexplained_articles
            closes = articles_close
        else:
            scoped = [s for s in builder.scopes if s["kind"] == kind]
            scopes = len(scoped)
            open_scopes = sum(1 for s in scoped if not s["closes"])
            missing = sum(len(s["missing"]) for s in scoped)
            unexplained = sum(s["unexplained"] for s in scoped)
            # Without own articles there is no scope to read the level in.
            closes = bool(own) and open_scopes == 0
        levels[kind] = {
            "nodes": len(mine),
            "corrected": sum(1 for n in mine if n["corrected"]),
            "scopes": scopes,
            "open_scopes": open_scopes,
            "missing": missing,
            "unexplained": unexplained,
            "closes": closes,
        }
    return {
        "nodes": nodes,
        "leftovers": builder.leftovers,
        "scopes": builder.scopes,
        "levels": levels,
        "quoted_blocks": quoted_blocks,
        "body_end": body_end,
        "open_tail_block": open_tail_block,
        "final_clause": final_clause,
        "final_clause_placed": final_placed,
        "tail_clean": tail_clean,
        # Conservative: every level, in every scope, a full chain and nothing
        # unexplained. Itens are too weakly marked to gate closure. The article level
        # also needs the two tail checks (see `final_clause_placed`, `tail_clean`).
        "closes": all(levels[k]["closes"] for k in _LEVELS if k != "item"),
    }


_CATEGORY = {
    "artigo": "art_marcador",
    "paragrafo": "par_marcador",
    "inciso": "inc_marcador",
    "alinea": "ali_marcador",
}


def marker_spans(text: str) -> list[Span]:
    """The norm's own markers as `segmenter` spans, for scoring against the gold.

    Quoted subtrees are left out: the gold treats text quoted from another norm as a
    hard negative. Itens have no gold category.
    """
    spans: list[Span] = []
    for node in read_hierarchy(text)["nodes"]:
        category = _CATEGORY.get(node["kind"])
        if category is None or node["status"] != "own":
            continue
        end = node["start"] + len(node["raw"])
        spans.append({"category": category, "start": node["start"], "end": end})
    spans.sort(key=lambda s: (s["start"], s["end"]))
    return spans
