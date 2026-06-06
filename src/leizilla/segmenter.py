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
from typing import Dict, List, Optional, Tuple, TypedDict


class Span(TypedDict):
    category: str
    start: int
    end: int


# --- marker patterns (short anchors) ---------------------------------------------------
# Ordinal indicator is any of º (U+00BA), ° (U+00B0) or a bare 'o'/'a'; numbering may
# carry a letter suffix ("Art. 8º-A", "§ 2º-B"); a trailing period may or may not be
# present in the source (we capture it when adjacent, then note boundary drift in eval).
_ORD = r"(?:\s*[ºo°ªa])?"
# Markers are short anchors and exclude the trailing period (the period is the clause
# separator, not part of the marker) — the gold follows the same convention.
_ART = re.compile(rf"Art\.\s*\d+{_ORD}(?:-[A-Z])?")
_PAR_NUM = re.compile(rf"§\s*\d+{_ORD}(?:-[A-Z])?")
_PAR_UNICO = re.compile(r"Parágrafo\s+único")
_INC = re.compile(r"\b[IVXLCDM]+\b\s*[-–—]+")
_ALI = re.compile(r"\b[a-z]\)")

# --- clause patterns (cue-driven sentences) -------------------------------------------
# Clauses (vigência/revogação) are detected by scanning sentence units (abbreviation- and
# number-aware: "art.", "nº 8.069", "13.07.1990" carry interior periods that do NOT end a
# sentence) and keeping the ones that carry the cue. Revogação additionally requires an
# *operative* verb form, so compiled-text annotations "(Revogado pela Lei nº …)" — which
# are amendment history, not a revocation dispositivo — are excluded.
_ABBREV = {
    "art",
    "arts",
    "inc",
    "incs",
    "n",
    "no",
    "dec",
    "dr",
    "sr",
    "sra",
    "al",
    "fl",
    "fls",
    "p",
    "pp",
    "cf",
    "ec",
    "lc",
    "par",
    "cc",
    "cpc",
    "cpp",
    "ctn",
}
_VIGENCIA_CUE = re.compile(r"\bem\s+vigor\b", re.IGNORECASE)
_REVOGA_OPERATIVE = re.compile(
    r"(?:Fica(?:m)?\s+revogad[oa]s?"
    r"|Revoga(?:m)?-se"
    r"|Revogad[oa]s?\s+(?:as\s+disposições|os\s+|o\s+art|a\s+Lei))",
    re.IGNORECASE,
)
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
# Right-context cues that mark a § occurrence as a reference ("§ 7º do art. 226",
# "§ 2º deste artigo") or a vetoed placeholder ("§ 2º (VETADO).") — not a marker.
_PAR_XREF_RIGHT = re.compile(
    r"^\s*(?:(?:do|da|dos|das|deste|desta|destes|destas)\b|\(VETADO|\(Vetado)",
    re.IGNORECASE,
)
# A clause sentence often opens with the article/§ marker it belongs to
# ("Art. 3º Esta Lei entra em vigor…"); strip that leading marker so the clause span
# starts at the clause itself (the marker is emitted separately by its own pass).
_LEADING_MARKER = re.compile(
    rf"^(?:Art\.\s*\d+{_ORD}(?:-[A-Z])?\.?|§\s*\d+{_ORD}(?:-[A-Z])?"
    rf"|Parágrafo\s+único\.?)\s+"
)


def _strip_leading_marker(text: str, s: int, e: int) -> int:
    """Return a start offset past a leading Art./§/Parágrafo marker, if any."""
    m = _LEADING_MARKER.match(text[s:e])
    if m and s + m.end() < e:
        return s + m.end()
    return s


def _xref(text: str, start: int) -> bool:
    """True if the match at `start` looks like a cross-reference (drop it)."""
    return bool(_XREF_LEFT.search(text[max(0, start - 24) : start]))


def _par_ref_right(text: str, end: int) -> bool:
    """True if what follows a `§ N` match marks it as a reference / vetoed placeholder."""
    return bool(_PAR_XREF_RIGHT.match(text[end : end + 14]))


def _sentence_spans(text: str) -> List[Tuple[int, int]]:
    """Split into sentence units, abbreviation- and number-aware (see clause comment).

    A period ends a sentence only when it is not part of an abbreviation ("art.") or a
    number ("8.069", "13.07.1990") and is followed by whitespace + a capital/§ (or end of
    text). Leading/trailing whitespace is trimmed from each span.
    """
    raw: List[Tuple[int, int]] = []
    start = 0
    n = len(text)
    for i, ch in enumerate(text):
        if ch != ".":
            continue
        j = i - 1
        while j >= 0 and text[j].isalpha():
            j -= 1
        word = text[j + 1 : i].lower()
        k = i + 1
        while k < n and text[k].isspace():
            k += 1
        nxt = text[k] if k < n else ""
        terminal = word not in _ABBREV and (
            k >= n or (k > i + 1 and (nxt.isupper() or nxt in "§("))
        )
        if terminal:
            raw.append((start, i + 1))
            start = i + 1
    if text[start:].strip():
        raw.append((start, n))
    out: List[Tuple[int, int]] = []
    for s, e in raw:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if s < e:
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
        if not _xref(text, m.start()) and not _par_ref_right(text, m.end()):
            add("par_marcador", m)
    for m in _PAR_UNICO.finditer(text):
        add("par_marcador", m)
    for m in _INC.finditer(text):
        if not _xref(text, m.start()):
            add("inc_marcador", m)
    for m in _ALI.finditer(text):
        add("ali_marcador", m)
    for s0, e in _sentence_spans(text):
        s = _strip_leading_marker(text, s0, e)
        sent = text[s:e]
        if _VIGENCIA_CUE.search(sent):
            spans.append({"category": "vigencia", "start": s, "end": e})
        if _REVOGA_OPERATIVE.search(sent):
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


# --- error finder ---------------------------------------------------------------------
class SpanError(TypedDict):
    doc: str
    category: str
    kind: str  # "false_positive" | "false_negative" | "boundary"
    pred: str  # predicted surface ("" when a miss)
    gold: str  # gold surface ("" when a spurious prediction)
    context: str


def _ctx(text: str, start: int, end: int, pad: int = 30) -> str:
    """A one-line context window with the span bracketed: …left⟦span⟧right…."""
    left = text[max(0, start - pad) : start].replace("\n", " ")
    right = text[end : end + pad].replace("\n", " ")
    lead = "…" if start - pad > 0 else ""
    tail = "…" if end + pad < len(text) else ""
    return f"{lead}{left}⟦{text[start:end]}⟧{right}{tail}"


def find_errors(
    docs: List[Tuple[str, List[Span]]],
    ids: Optional[List[str]] = None,
) -> List[SpanError]:
    """Diff `segment()` against gold and return the concrete disagreements.

    Per document and category, exact (start, end) matches are correct and dropped; what
    remains is classified as:

    - **boundary**: a gold span and a prediction overlap but their offsets differ (right
      region, wrong edges);
    - **false_negative**: a gold span no prediction overlaps (a miss);
    - **false_positive**: a prediction no gold span overlaps (a spurious tag).

    `ids[i]` labels doc *i* (e.g. the raw_id); falls back to "doc{i}".
    """
    errors: List[SpanError] = []
    for di, (text, gold) in enumerate(docs):
        doc_id = ids[di] if ids and di < len(ids) else f"doc{di}"
        pred = segment(text)
        cats = {s["category"] for s in gold} | {s["category"] for s in pred}
        for cat in sorted(cats):
            g = [s for s in gold if s["category"] == cat]
            p = [s for s in pred if s["category"] == cat]
            gkeys = {(s["start"], s["end"]) for s in g}
            pkeys = {(s["start"], s["end"]) for s in p}
            g_left = [s for s in g if (s["start"], s["end"]) not in pkeys]
            p_left = [s for s in p if (s["start"], s["end"]) not in gkeys]
            used: set[int] = set()
            for gs in g_left:
                hit = next(
                    (
                        idx
                        for idx, ps in enumerate(p_left)
                        if idx not in used and _overlaps(gs, ps)
                    ),
                    None,
                )
                if hit is not None:
                    used.add(hit)
                    ps = p_left[hit]
                    errors.append(
                        {
                            "doc": doc_id,
                            "category": cat,
                            "kind": "boundary",
                            "pred": text[ps["start"] : ps["end"]],
                            "gold": text[gs["start"] : gs["end"]],
                            "context": _ctx(text, gs["start"], gs["end"]),
                        }
                    )
                else:
                    errors.append(
                        {
                            "doc": doc_id,
                            "category": cat,
                            "kind": "false_negative",
                            "pred": "",
                            "gold": text[gs["start"] : gs["end"]],
                            "context": _ctx(text, gs["start"], gs["end"]),
                        }
                    )
            for idx, ps in enumerate(p_left):
                if idx in used:
                    continue
                errors.append(
                    {
                        "doc": doc_id,
                        "category": cat,
                        "kind": "false_positive",
                        "pred": text[ps["start"] : ps["end"]],
                        "gold": "",
                        "context": _ctx(text, ps["start"], ps["end"]),
                    }
                )
    return errors


def format_errors(errors: List[SpanError]) -> str:
    """Render found errors grouped by (kind, category) with counts and context."""
    if not errors:
        return "no errors — predictions match the gold exactly 🎯"
    order = {"false_positive": 0, "false_negative": 1, "boundary": 2}
    by_group: Dict[Tuple[str, str], List[SpanError]] = {}
    for e in errors:
        by_group.setdefault((e["kind"], e["category"]), []).append(e)
    rows: List[str] = []
    counts: Dict[str, int] = {}
    for kind, cat in sorted(by_group, key=lambda kc: (order.get(kc[0], 9), kc[1])):
        group = by_group[(kind, cat)]
        counts[kind] = counts.get(kind, 0) + len(group)
        rows.append(f"\n### {kind}  [{cat}]  ×{len(group)}")
        for e in group:
            if kind == "boundary":
                rows.append(f"  pred={e['pred']!r}  gold={e['gold']!r}")
            elif kind == "false_positive":
                rows.append(f"  spurious={e['pred']!r}")
            else:
                rows.append(f"  missed={e['gold']!r}")
            rows.append(f"    {e['doc']}: {e['context']}")
    head = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    return f"{len(errors)} error(s) — {head}\n" + "\n".join(rows)


# --- whole-norma structural validation (no gold needed) -------------------------------
class StructuralFinding(TypedDict):
    kind: str
    detail: str


_ART_NUMBER = re.compile(r"Art\.\s*(\d+)")


def validate_structure(text: str) -> List[StructuralFinding]:
    """Sanity-check a whole norma's segmentation *without* a gold reference.

    Answers "did we find all the article boundaries?" and a few sibling questions from
    the sequence of detected markers alone:

    - **missing_articles**: gaps in the article numbering 1..max — a boundary we failed
      to find (or one genuinely absent from the source);
    - **out_of_order**: an article number lower than an earlier one — a misparse, or a
      reference mis-tagged as a marker;
    - **no_articles / no_ementa / no_vigencia**: expected structure absent.

    Heuristics, not proof: an `-A` renumbering (`Art. 8º-A`) shares its base number, so it
    is not flagged. Use the findings to flag a norma for review, not to reject it.
    """
    spans = segment(text)
    findings: List[StructuralFinding] = []

    numbers: List[int] = []
    for s in spans:
        if s["category"] != "art_marcador":
            continue
        m = _ART_NUMBER.match(text[s["start"] : s["end"]])
        if m:
            numbers.append(int(m.group(1)))

    if not numbers:
        findings.append(
            {"kind": "no_articles", "detail": "nenhum art_marcador detectado"}
        )
    else:
        mx = max(numbers)
        present = set(numbers)
        missing = [n for n in range(1, mx + 1) if n not in present]
        if missing:
            findings.append(
                {
                    "kind": "missing_articles",
                    "detail": f"lacunas em Art. 1..{mx}: {missing}",
                }
            )
        running = 0
        out_of_order: List[int] = []
        for n in numbers:
            if n < running:
                out_of_order.append(n)
            else:
                running = n
        if out_of_order:
            findings.append(
                {
                    "kind": "out_of_order",
                    "detail": f"artigos fora de ordem: {out_of_order}",
                }
            )

    if not any(s["category"] == "ementa" for s in spans):
        findings.append({"kind": "no_ementa", "detail": "nenhuma ementa detectada"})
    if not any(s["category"] == "vigencia" for s in spans):
        findings.append(
            {"kind": "no_vigencia", "detail": "nenhuma cláusula de vigência detectada"}
        )
    return findings


def format_structure(findings: List[StructuralFinding]) -> str:
    """Render structural findings (or a clean-bill line when there are none)."""
    if not findings:
        return "estrutura OK — sem lacunas/anomalias detectadas ✅"
    return "\n".join(f"  [{f['kind']}] {f['detail']}" for f in findings)
