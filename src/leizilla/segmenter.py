"""Regex baseline segmenter for Leizilla normas — the Pattern-B counterpart to OPF.

The `opf-finetune` skill (ontology-recipes.md, Pattern B) is explicit: for a known
formatting regime a **regex baseline on the structural markers is strong**, and the
trained model only "earns its keep" on the messy cases — OCR noise, inconsistent
numbering, a marker quoted inside a cross-reference. This module is that baseline.

It detects the same `leizilla_normas_v1` categories OPF is trained on, so the two are
directly comparable on the committed gold (`data/opf/gold/`). `evaluate_against_gold`
scores predictions per category at two strictnesses:

- **exact**: predicted (start, end, category) equals a gold span — sensitive to boundary
  drift (the inconsistent "Art. 10" vs "Art. 10." period, spaced "§ 1 o", …).
- **overlap**: predicted span overlaps a gold span of the same category — pure detection,
  ignoring boundaries.

The gap between the two, and the per-category precision, is the honest "where does regex
suffice / where must the model earn its keep" map (ADR-0012, docs/opf-finetune.md).

Design choices that matter:
- The article pattern is **capitalised** ("Art."); lowercase "art." (as in "o art. 233 da
  Lei nº 8.069") is a cross-reference and is *not* a marker — capitalisation alone filters
  most article references.
- `§` and roman-numeral incisos *do* recur inside references ("no caso do § 2º",
  "inciso XII"); a small left-context guard drops the obvious ones. This is deliberately
  imperfect — the residual false positives are the model's territory.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple, TypedDict


class Span(TypedDict):
    category: str
    start: int
    end: int


# --- marker patterns (short anchors) ---------------------------------------------------
# Ordinal indicator is any of º (U+00BA), ° (U+00B0) or a bare 'o'/'a'; numbering may
# carry a letter suffix ("Art. 8º-A", "§ 2º-B"); a trailing period may or may not be
# present in the source (we capture it when adjacent, then note boundary drift in eval).
_ORD = r"(?:\s*[ºo°ªa])?"
_ART = re.compile(rf"Art\.\s*\d+{_ORD}(?:-[A-Z])?\.?")
_PAR_NUM = re.compile(rf"§\s*\d+{_ORD}(?:-[A-Z])?")
_PAR_UNICO = re.compile(r"Parágrafo\s+único\.?")
_INC = re.compile(r"\b[IVXLCDM]+\b\s*[-–—]+")
_ALI = re.compile(r"\b[a-z]\)")

# --- clause patterns (cue-driven sentences) -------------------------------------------
# Clauses (vigência/revogação) are detected by scanning sentence-ish units and keeping
# the ones that carry the cue — more robust than one monster regex on legal punctuation
# ("art.", "nº 8.069", "13.07.1990" all carry interior periods).
_SENTENCE = re.compile(r"[^.]*\.")
_VIGENCIA_CUE = re.compile(r"em\s+vigor", re.IGNORECASE)
_REVOGACAO_CUE = re.compile(r"\brevoga", re.IGNORECASE)
_EMENTA = re.compile(
    # text between the "... DE <ano>." header line and the enacting clause.
    r"DE\s+\d{4}\s*\.\s*(?P<ementa>.+?)\s*"
    r"(?=O\s+PRESIDENTE|A\s+PRESIDENTE|O\s+VICE|Faço\s+saber|O\s+CONGRESSO|"
    r"AS\s+MESAS|As\s+Mesas)",
    re.DOTALL,
)

# Left-context cues that mark a § / inciso occurrence as a cross-reference, not a marker.
_XREF_LEFT = re.compile(
    r"(?:inciso|incisos|do|da|no|na|ao|à|nos|nas|caso\s+do|hipótese\s+do|"
    r"termos\s+do|previsto\s+no|na\s+forma\s+do|§)\s*$",
    re.IGNORECASE,
)


def _xref(text: str, start: int) -> bool:
    """True if the match at `start` looks like a cross-reference (drop it)."""
    return bool(_XREF_LEFT.search(text[max(0, start - 24) : start]))


def _cue_sentences(text: str, cue: re.Pattern[str]) -> List[Tuple[int, int]]:
    """Yield (start, end) of sentence-ish units carrying `cue`, leading space trimmed."""
    out: List[Tuple[int, int]] = []
    for m in _SENTENCE.finditer(text):
        s, e = m.start(), m.end()
        while s < e and text[s].isspace():
            s += 1
        if s < e and cue.search(text[s:e]):
            out.append((s, e))
    return out


def segment(text: str) -> List[Span]:
    """Detect structural-marker / cue spans in `text`. Returns spans sorted by start.

    Non-overlapping by construction within a category; across categories overlaps are
    not expected for these markers. Naive by design — the guards drop only the obvious
    cross-references so the residual error is an honest signal of regex's ceiling.
    """
    spans: List[Span] = []

    def add(cat: str, m: re.Match[str]) -> None:
        spans.append({"category": cat, "start": m.start(), "end": m.end()})

    for m in _ART.finditer(text):
        add("art_marcador", m)
    for m in _PAR_NUM.finditer(text):
        if not _xref(text, m.start()):
            add("par_marcador", m)
    for m in _PAR_UNICO.finditer(text):
        add("par_marcador", m)
    for m in _INC.finditer(text):
        if not _xref(text, m.start()):
            add("inc_marcador", m)
    for m in _ALI.finditer(text):
        add("ali_marcador", m)
    for s, e in _cue_sentences(text, _VIGENCIA_CUE):
        spans.append({"category": "vigencia", "start": s, "end": e})
    for s, e in _cue_sentences(text, _REVOGACAO_CUE):
        spans.append({"category": "revogacao", "start": s, "end": e})
    em = _EMENTA.search(text)
    if em and em.group("ementa"):
        spans.append(
            {"category": "ementa", "start": em.start("ementa"), "end": em.end("ementa")}
        )

    spans.sort(key=lambda s: (s["start"], s["end"]))
    return spans


# --- evaluation against gold ----------------------------------------------------------
class CatScore(TypedDict):
    gold: int
    pred: int
    exact_tp: int
    overlap_tp_pred: int  # predicted spans that overlap some gold (precision numerator)
    overlap_tp_gold: int  # gold spans covered by some prediction (recall numerator)


def _prf(tp: int, pred: int, gold: int) -> Tuple[float, float, float]:
    p = tp / pred if pred else 0.0
    r = tp / gold if gold else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def _overlaps(a: Span, b: Span) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def evaluate_against_gold(
    docs: List[Tuple[str, List[Span]]],
) -> Dict[str, CatScore]:
    """Score `segment()` over (text, gold_spans) pairs. Returns per-category counts.

    `exact_tp` = predicted span equal to a gold span; `overlap_tp_*` = detection ignoring
    boundaries (counted separately on the pred and gold side, since one pred may overlap
    several gold spans and vice-versa).
    """
    scores: Dict[str, CatScore] = {}

    def slot(cat: str) -> CatScore:
        return scores.setdefault(
            cat,
            {
                "gold": 0,
                "pred": 0,
                "exact_tp": 0,
                "overlap_tp_pred": 0,
                "overlap_tp_gold": 0,
            },
        )

    for text, gold in docs:
        pred = segment(text)
        by_cat_gold: Dict[str, List[Span]] = {}
        by_cat_pred: Dict[str, List[Span]] = {}
        for s in gold:
            by_cat_gold.setdefault(s["category"], []).append(s)
        for s in pred:
            by_cat_pred.setdefault(s["category"], []).append(s)

        for cat in set(by_cat_gold) | set(by_cat_pred):
            g = by_cat_gold.get(cat, [])
            p = by_cat_pred.get(cat, [])
            sc = slot(cat)
            sc["gold"] += len(g)
            sc["pred"] += len(p)
            gold_keys = {(s["start"], s["end"]) for s in g}
            sc["exact_tp"] += sum(1 for s in p if (s["start"], s["end"]) in gold_keys)
            sc["overlap_tp_pred"] += sum(
                1 for ps in p if any(_overlaps(ps, gs) for gs in g)
            )
            sc["overlap_tp_gold"] += sum(
                1 for gs in g if any(_overlaps(gs, ps) for ps in p)
            )

    return scores


def format_report(scores: Dict[str, CatScore]) -> str:
    """Render a per-category exact/overlap P/R/F1 table (+ micro totals)."""
    rows = [
        "category        gold pred | exact  P     R     F1   | overlap P     R     F1",
        "-" * 86,
    ]
    tot = {
        "gold": 0,
        "pred": 0,
        "exact_tp": 0,
        "overlap_tp_pred": 0,
        "overlap_tp_gold": 0,
    }
    for cat in sorted(scores):
        s = scores[cat]
        ep, er, ef = _prf(s["exact_tp"], s["pred"], s["gold"])
        op = s["overlap_tp_pred"] / s["pred"] if s["pred"] else 0.0
        orr = s["overlap_tp_gold"] / s["gold"] if s["gold"] else 0.0
        of = 2 * op * orr / (op + orr) if (op + orr) else 0.0
        rows.append(
            f"{cat:15s} {s['gold']:4d} {s['pred']:4d} | "
            f"{s['exact_tp']:4d}  {ep:.2f}  {er:.2f}  {ef:.2f} | "
            f"      {op:.2f}  {orr:.2f}  {of:.2f}"
        )
        for k in tot:
            tot[k] += s[k]  # type: ignore[literal-required]
    ep, er, ef = _prf(tot["exact_tp"], tot["pred"], tot["gold"])
    op = tot["overlap_tp_pred"] / tot["pred"] if tot["pred"] else 0.0
    orr = tot["overlap_tp_gold"] / tot["gold"] if tot["gold"] else 0.0
    of = 2 * op * orr / (op + orr) if (op + orr) else 0.0
    rows.append("-" * 86)
    rows.append(
        f"{'MICRO':15s} {tot['gold']:4d} {tot['pred']:4d} | "
        f"{tot['exact_tp']:4d}  {ep:.2f}  {er:.2f}  {ef:.2f} | "
        f"      {op:.2f}  {orr:.2f}  {of:.2f}"
    )
    return "\n".join(rows)
