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
from typing import TypedDict

# "Art" + optional separator + number-like token. The token allows the letters OCR
# substitutes for digits (I, l for 1; O for 0). Whitespace may include line breaks:
# typewritten scans come out one word per line.
_CANDIDATE = re.compile(
    r"\b(?:Art|AH|Arl|Aft)\s*[.,:]?\s*(?P<num>[0-9IlO]{1,4})"
    r"(?P<ord>\s?[ºo°ªQ^?])?"
    r"(?:\s?-\s?(?P<suffix>[A-Z])\b)?"
)
_OCR_DIGITS = str.maketrans({"I": "1", "l": "1", "O": "0"})
# Digits the ordinal indicator is misread as when glued to the number ("4º" -> "42").
_ORDINAL_AS_DIGIT = "029"
_QUOTE_OPEN = re.compile(r"[\"“”‘'«]\s*$")
# A capitalised "Art." right after one of these words is a citation inside a sentence
# ("nos termos do Art. 42 da Constituição"), not a marker. Decided before the chain is
# built, so a citation can never be absorbed as one of the norm's own articles.
_REFERENCE_LEFT = re.compile(
    r"\b(?:d?o|n?o|ao|d?os|n?os|aos|pelos?|e|ou|§\s?\S{1,3})\s+$", re.IGNORECASE
)

_GAP_PENALTY = 0.5
_LOOKBACK = 80


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


def _readings(num: str, has_ordinal: bool) -> list[int]:
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
    return out


def _best_chain(cands: list[list[int]], suffixed: list[bool]) -> list[int | None]:
    """Pick one reading per candidate (or None) forming the best increasing chain.

    Score: +1 per candidate taken, minus a penalty per skipped number. A candidate may
    repeat the previous number only when it carries a letter suffix ("Art. 8º-A").
    """
    n = len(cands)
    best: list[dict[int, float]] = [{} for _ in range(n)]
    back: list[dict[int, tuple[int, int] | None]] = [{} for _ in range(n)]
    for i in range(n):
        for v in cands[i]:
            score = 1.0 - _GAP_PENALTY * (v - 1)
            prev: tuple[int, int] | None = None
            for j in range(max(0, i - _LOOKBACK), i):
                for u, s in best[j].items():
                    if v > u:
                        cand = s + 1.0 - _GAP_PENALTY * (v - u - 1)
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


def read_articles(text: str) -> SequenceReport:
    """Read the article markers of one norm, resolving OCR ambiguity by sequence."""
    matches = list(_CANDIDATE.finditer(text))
    cands: list[list[int]] = []
    is_ref: list[bool] = []
    for m in matches:
        ref = bool(_REFERENCE_LEFT.search(text[max(0, m.start() - 12) : m.start()]))
        is_ref.append(ref)
        cands.append(
            [] if ref else _readings(m.group("num"), m.group("ord") is not None)
        )
    chosen = _best_chain(cands, [m.group("suffix") is not None for m in matches])

    articles: list[ArticleRead] = []
    own_numbers: set[int] = set()
    for m, readings, value, ref in zip(matches, cands, chosen, is_ref):
        if ref:
            status = "reference"
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
    quoted = sum(1 for a in articles if a["status"] == "quoted")
    unexplained = sum(1 for a in articles if a["status"] == "unexplained")
    return {
        "articles": articles,
        "own": sum(1 for a in articles if a["status"] == "own"),
        "last": last,
        "missing": missing,
        "quoted": quoted,
        "references": sum(1 for a in articles if a["status"] == "reference"),
        "unexplained": unexplained,
        "corrected": sum(1 for a in articles if a["corrected"]),
        # Closing means the whole candidate set is explained: a full 1..N chain and
        # nothing left over except quoted articles and in-sentence citations. A short chain that merely
        # ignores unreadable candidates does not close.
        "closes": last > 0 and not missing and unexplained == 0,
    }
