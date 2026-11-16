"""Sequence-aware reading of article markers in OCR text.

`segmenter.segment` reads each "Art. N" on its own, so it inherits every OCR misread of
the ordinal indicator. On the RO corpus the "º" after an article number comes out as
``o``, ``Q``, ``°``, ``^``, ``-``, ``?`` or as an extra digit ("Art. 42" for "Art. 4º"),
and "1º" comes out as "Io". Read alone those are ambiguous; read in sequence they are
not: between Art. 3 and Art. 5, "42" is 4º.

This module keeps the text verbatim and only decides how to *read* each candidate:

1. find loose candidates (`Art` + a number-like token, tolerant of OCR glyphs);
2. give each a small set of plausible readings;
3. pick the chain of consecutive numbers that explains most candidates (the norm's own
   articles), by dynamic programming;
4. label what is left as ``quoted`` (opened by a quotation mark: an article of another
   norm cited by an amending law) or ``unexplained`` (the hard cases worth a decision
   model or a human).

It is a measurement and review aid for the `boundary-decision-parser` research front
(docs/okf/project-dag.md), not part of the production parser.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import Sequence, TypedDict

# "Art" + optional separator + number-like token. The token allows the letters OCR
# substitutes for digits (I, l for 1; O for 0). Whitespace may include line breaks:
# typewritten scans come out one word per line.
#
# The prefix: "Art"/"ART"/"Artigo"/"ARTIGO" (lowercase "art." stays a mid-sentence
# citation, never a marker), plus OCR variants. "Ait", "Alt" only count at the start of
# a line and only before a number-like token, so "Alto Paraíso" and "Alta Floresta" are
# not markers; "A r/t." is OCR for "Art.".
#
# The letter suffix ("Art. 5º-A") is a single capital glued to the number by a hyphen
# and followed by a non-letter that ends the marker: ".", ":", a dash, end of line, or a
# dash after spaces. "Art. 2º - A Comissão" and "Art. 25-O Tesoureiro" are a separator
# plus the first word of the caput, not a suffix.
ARTICLE_CANDIDATE = re.compile(
    r"(?:"
    r"\b(?:ART(?:IGO)?|Art(?:igo)?|AH|Arl|Aft)"
    r"|(?<![^\n])[ \t]*(?:Ait|Alt)(?=\.?\s*[0-9Il])"
    r"|\bA\s?r/t(?=\.?\s*[0-9Il])"
    r")"
    r"\s*[.,:;»«„“”\"'^™_]{0,3}\s*(?P<num>[0-9IlO]{1,4})"
    r"(?P<ord>\s?[ºo°ªQ^?])?"
    r"(?:-(?P<suffix>[A-Z])(?=[.:\-–—]|[ \t]*[\-–—]|[ \t]*(?:\n|\Z)))?"
)
_OCR_DIGITS = str.maketrans({"I": "1", "l": "1", "O": "0"})
# Digits the ordinal indicator is misread as when glued to the number ("4º" -> "42").
_ORDINAL_AS_DIGIT = "029"
_GLUED_ORDINAL_PAIRS = frozenset({"20", "90", "00"})
QUOTE_CHARS = "\"“”‘'«"
_QUOTE_OPEN = re.compile(rf"[{QUOTE_CHARS}]\s*$")
# A capitalised "Art." right after one of these words is a citation inside a sentence
# ("nos termos do Art. 42 da Constituição"), not a marker. Decided before the chain is
# built, so a citation can never be absorbed as one of the norm's own articles.
_REFERENCE_LEFT = re.compile(
    r"\b(?:d?o|n?o|ao|d?os|n?os|aos|pelos?|e|ou|§\s?\S{1,3})\s+$", re.IGNORECASE
)
# A connector that opens its line, after at most three tokens of OCR debris and no
# word, is a stray glyph ("e" over an article), not the start of a sentence citing the
# article: "e Art. 6º - Revogam-se" is the last article of a norm.
_LINE_CONNECTOR = frozenset({"e", "ou"})
_WORD = re.compile(r"[^\W\d_]{2,}")

_GAP_PENALTY = 0.5
_LOOKBACK = 80
_INF = 1 << 62


class ArticleRead(TypedDict):
    start: int
    end: int
    raw: str
    number: int | None
    suffix: str | None
    status: str  # own | quoted | reference | unexplained
    corrected: bool  # the chosen reading differs from the literal one


class SequenceReport(TypedDict):
    articles: list[ArticleRead]
    own: int
    last: int
    missing: list[int]
    quoted: int
    references: int
    unexplained: int
    corrected: int
    closes: bool


def article_readings(num: str, has_ordinal: bool) -> list[int]:
    """Plausible article numbers for a raw token, literal reading first."""
    digits = num.translate(_OCR_DIGITS)
    literal = int(digits)
    out = [literal] if literal > 0 else []
    # Ordinal indicators are only used up to 9º, so a glued misread always leaves a
    # single digit behind: "42" -> 4, "10" -> 1, "19" -> 1.
    if not has_ordinal and len(digits) == 2 and digits[1] in _ORDINAL_AS_DIGIT:
        alt = int(digits[0])
        if alt > 0 and alt not in out:
            out.append(alt)
    # Three digits: a two-digit article with its ordinal glued as a digit ("109" is
    # "10º"), or a one-digit article whose "º" came out as "20", "90" or "00" ("220",
    # "290" are "2º"). Only the chain can tell these readings apart from real numbers.
    if not has_ordinal and len(digits) == 3:
        if digits[2] in _ORDINAL_AS_DIGIT:
            alt = int(digits[:2])
            if alt > 0 and alt not in out:
                out.append(alt)
        if digits[1:] in _GLUED_ORDINAL_PAIRS:
            alt = int(digits[0])
            if alt > 0 and alt not in out:
                out.append(alt)
    return out


def is_reference(text: str, start: int) -> bool:
    """True when the "Art." at ``start`` sits inside a sentence as a citation.

    The connector before it ("do", "no", "e", "§ 2º") marks a citation, except when the
    connector is a lone glyph opening its line: then the marker is read on its own.
    """
    window_start = max(0, start - 12)
    found = _REFERENCE_LEFT.search(text[window_start:start])
    if found is None:
        return False
    connector = found.group(0).split()[0].lower()
    if connector in _LINE_CONNECTOR:
        conn_start = window_start + found.start()
        line_start = text.rfind("\n", 0, conn_start) + 1
        before = text[line_start:conn_start].split()
        if len(before) <= 3 and not any(_WORD.search(tok) for tok in before):
            return False
    return True


def best_chain(
    cands: Sequence[Sequence[int]],
    suffixed: Sequence[bool],
    *,
    anchored: bool = True,
    free_skips: frozenset[int] = frozenset(),
) -> list[int | None]:
    """Pick one reading per candidate (or None) forming the best increasing chain.

    Score: +1 per candidate taken, minus a penalty per skipped number. A candidate may
    repeat the previous number only when it carries a letter suffix ("Art. 8º-A").

    ``anchored`` charges the numbers skipped before the first member, so the chain is
    pulled towards starting at 1 (a norm's own numbering). An unanchored chain may start
    anywhere (a fragment quoted from another norm). Numbers in ``free_skips`` may be
    skipped at no cost (alíneas of older norms skip k, w and y).
    """

    def skipped(lo: int, hi: int) -> int:
        """How many chargeable numbers lie strictly between lo and hi."""
        count = hi - lo - 1
        if free_skips and count > 0:
            count -= sum(1 for k in free_skips if lo < k < hi)
        return count

    n = len(cands)
    best: list[dict[int, float]] = [{} for _ in range(n)]
    back: list[dict[int, tuple[int, int] | None]] = [{} for _ in range(n)]
    for i in range(n):
        for v in cands[i]:
            score = 1.0 - (_GAP_PENALTY * skipped(0, v) if anchored else 0.0)
            prev: tuple[int, int] | None = None
            for j in range(max(0, i - _LOOKBACK), i):
                for u, s in best[j].items():
                    if v > u:
                        cand = s + 1.0 - _GAP_PENALTY * skipped(u, v)
                    elif v == u and suffixed[i]:
                        cand = s + 1.0
                    else:
                        continue
                    if cand > score:
                        score, prev = cand, (j, u)
            best[i][v] = score
            back[i][v] = prev

    chosen: list[int | None] = [None] * n
    end: tuple[int, int] | None = None
    top = 0.0
    for i in range(n):
        for v, s in best[i].items():
            if s > top:
                top, end = s, (i, v)
    while end is not None:
        i, v = end
        chosen[i] = v
        end = back[i][v]
    return chosen


def _in_spans(pos: int, spans: Sequence[tuple[int, int]]) -> bool:
    """True when ``pos`` falls inside one of the sorted, disjoint ``spans``."""
    k = bisect_right(spans, (pos, _INF)) - 1
    return k >= 0 and spans[k][0] <= pos < spans[k][1]


def read_articles(
    text: str, quoted_spans: Sequence[tuple[int, int]] = ()
) -> SequenceReport:
    """Read the article markers of one norm, resolving OCR ambiguity by sequence.

    ``quoted_spans`` are sorted, disjoint character ranges already known to be text
    quoted from another norm (see `hierarchy_sequence`); a candidate inside one is
    ``quoted`` up front and can never join the norm's own chain.
    """
    matches = list(ARTICLE_CANDIDATE.finditer(text))
    cands: list[list[int]] = []
    is_ref: list[bool] = []
    is_quoted: list[bool] = []
    for m in matches:
        quoted = bool(quoted_spans) and _in_spans(m.start(), quoted_spans)
        ref = not quoted and is_reference(text, m.start())
        is_ref.append(ref)
        is_quoted.append(quoted)
        cands.append(
            []
            if ref or quoted
            else article_readings(m.group("num"), m.group("ord") is not None)
        )
    chosen = best_chain(cands, [m.group("suffix") is not None for m in matches])

    articles: list[ArticleRead] = []
    own_numbers: set[int] = set()
    for m, readings, value, ref, quoted in zip(
        matches, cands, chosen, is_ref, is_quoted
    ):
        if ref:
            status = "reference"
        elif quoted:
            status = "quoted"
        elif value is not None:
            status = "own"
            own_numbers.add(value)
        elif _QUOTE_OPEN.search(text[max(0, m.start() - 4) : m.start()]):
            status = "quoted"
        else:
            status = "unexplained"
        articles.append(
            {
                "start": m.start(),
                "end": m.end(),
                "raw": m.group(0),
                "number": value,
                "suffix": m.group("suffix"),
                "status": status,
                "corrected": value is not None
                and bool(readings)
                and value != readings[0],
            }
        )

    last = max(own_numbers) if own_numbers else 0
    missing = [k for k in range(1, last + 1) if k not in own_numbers]
    n_quoted = sum(1 for a in articles if a["status"] == "quoted")
    unexplained = sum(1 for a in articles if a["status"] == "unexplained")
    return {
        "articles": articles,
        "own": sum(1 for a in articles if a["status"] == "own"),
        "last": last,
        "missing": missing,
        "quoted": n_quoted,
        "references": sum(1 for a in articles if a["status"] == "reference"),
        "unexplained": unexplained,
        "corrected": sum(1 for a in articles if a["corrected"]),
        # Closing means the whole candidate set is explained: a full 1..N chain and
        # nothing left over except quoted articles and in-sentence citations. A short
        # chain that merely ignores unreadable candidates does not close.
        "closes": last > 0 and not missing and unexplained == 0,
    }
