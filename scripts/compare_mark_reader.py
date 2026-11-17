"""Compare the rule reader with the mark-mode documents, PER LEVEL (offline).

A collected mark run (``teacher_batch collect --mode mark``: ``marked/``, optionally
``marked-repaired/``, ``records/``) holds, for each norm, the model's marked document
and the text it marks. This script builds the rule reader's document for the same text
and compares the two with ``marcacao.to_rows`` at every level (``art par inc ali item``)
and for own and quoted devices apart. Mark mode reads each device independently and is
better than the reader at the sub-levels (pilot: ~0 model errors in 230 devices on clean
norms), so here the mark document is the reference and the reader is the one scored; the
ranked defect list at the end is the input for a rule tournament at the sub-levels.

Devices are paired by kind: first by the same marker offset, then in order on the same
line, then by the same number within two lines (a marker split across lines). Per pair:

- ``agree``: same number (and suffix) and same own/quoted status;
- ``number_differs`` / ``status_differs``: paired but one of the two differs;
- ``reader_misses``: a mark device the reader did not find;
- ``reader_extra``: a reader device the mark document does not have;
- ``kind_differs``: a miss and an extra on the same line of different kinds (the reader
  read an ``inc`` where the model has an ``item``, a ``par`` where it has an ``art``).

Per norm and level the group is ``agree``, one of the five defects, or ``mixed``.
Norms with suspect flags (``suspect_alteracao``, ``suspect_sequence``, ``suspect_number``)
are tallied apart and left out of the "clean" table; ``--variant repaired`` takes the
repaired document where the converter made one (and its remaining suspects).

With ``--labels`` (the label-mode teacher, a ``teacher_batch collect`` directory) each
level also gets the agreement of the mark document and of the reader with the teacher,
per norm, on the norms whose text is the one the teacher saw.

    uv run scripts/compare_mark_reader.py --run COLLECT_DIR --out OUT_DIR \\
        [--variant as-is|repaired] [--labels LABELS_DIR] [--examples 3]
"""

from __future__ import annotations

import argparse
import bisect
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

import compare_teacher_reader as ctr
import score_mark

from leizilla import marcacao

LEVELS: tuple[str, ...] = ("art", "par", "inc", "ali", "item")
SUB_LEVELS: tuple[str, ...] = ("par", "inc", "ali", "item")
DEFECTS: tuple[str, ...] = (
    "reader_misses",
    "reader_extra",
    "number_differs",
    "status_differs",
    "kind_differs",
)
TEACHER_CATEGORY = {
    "art": "artigo",
    "par": "paragrafo",
    "inc": "inciso",
    "ali": "alinea",
    "item": "item",
}
SUSPECT_TYPES = ("suspect_alteracao", "suspect_sequence", "suspect_number")
LINE_TOLERANCE = 2
CONTEXT = 70

_ROMAN = "IVXLCDMivxlcdm"
_ROMAN_LOOKALIKE = set(_ROMAN) | set("1l|!")


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------


def line_starts(text: str) -> list[int]:
    return [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]


def devices(xml: str, text: str) -> list[dict[str, Any]]:
    """The devices of a marked document (``art par inc ali item``), with the line of
    the marker (or of the start when there is no marker)."""
    starts = line_starts(text)
    out: list[dict[str, Any]] = []
    for row in marcacao.to_rows(xml):
        if row["kind"] not in LEVELS:
            continue
        at = row["start"]
        out.append(
            {
                "kind": row["kind"],
                "n": str(row["n"]),
                "sufixo": row.get("sufixo") or "",
                "quoted": bool(row["quoted"]),
                "marker": row.get("marker") or "",
                "offset": at,
                "line": bisect.bisect_right(starts, at),
                "path": row["path"],
            }
        )
    return out


def pair_devices(
    mark: list[dict[str, Any]], reader: list[dict[str, Any]]
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any]]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """``(pairs, mark_only, reader_only)`` (see the module docstring for the order)."""
    taken_m: set[int] = set()
    taken_r: set[int] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def take(i: int, j: int) -> None:
        taken_m.add(i)
        taken_r.add(j)
        pairs.append((mark[i], reader[j]))

    by_offset = {(d["kind"], d["offset"]): j for j, d in enumerate(reader)}
    for i, d in enumerate(mark):
        j = by_offset.get((d["kind"], d["offset"]))
        if j is not None and j not in taken_r:
            take(i, j)
    for kind in LEVELS:
        lines = {d["line"] for d in mark if d["kind"] == kind}
        for line in sorted(lines):
            ms = [
                i
                for i, d in enumerate(mark)
                if d["kind"] == kind and d["line"] == line and i not in taken_m
            ]
            rs = [
                j
                for j, d in enumerate(reader)
                if d["kind"] == kind and d["line"] == line and j not in taken_r
            ]
            for i, j in zip(ms, rs):
                take(i, j)
    for i, d in enumerate(mark):
        if i in taken_m:
            continue
        for j, r in enumerate(reader):
            if (
                j not in taken_r
                and r["kind"] == d["kind"]
                and (r["n"], r["sufixo"]) == (d["n"], d["sufixo"])
                and abs(r["line"] - d["line"]) <= LINE_TOLERANCE
            ):
                take(i, j)
                break
    mark_only = [d for i, d in enumerate(mark) if i not in taken_m]
    reader_only = [d for j, d in enumerate(reader) if j not in taken_r]
    return pairs, mark_only, reader_only


def status(d: dict[str, Any]) -> str:
    return "quoted" if d["quoted"] else "own"


def classify_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    mark_only: list[dict[str, Any]],
    reader_only: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One outcome per device (a pair counts once, under the mark's status; extras
    under the reader's). ``defects`` lists what is wrong (empty: ``agree``)."""
    out: list[dict[str, Any]] = []
    for m, r in pairs:
        defects = []
        if (m["n"], m["sufixo"]) != (r["n"], r["sufixo"]):
            defects.append("number_differs")
        if m["quoted"] != r["quoted"]:
            defects.append("status_differs")
        out.append(
            {
                "level": m["kind"],
                "status": status(m),
                "mark": m,
                "reader": r,
                "defects": defects,
            }
        )
    left_m, left_r = list(mark_only), list(reader_only)
    for m in list(left_m):
        r = next((r for r in left_r if r["line"] == m["line"]), None)
        if r is not None:
            left_m.remove(m)
            left_r.remove(r)
            out.append(
                {
                    "level": m["kind"],
                    "status": status(m),
                    "mark": m,
                    "reader": r,
                    "defects": ["kind_differs"],
                }
            )
    for m in left_m:
        out.append(
            {
                "level": m["kind"],
                "status": status(m),
                "mark": m,
                "reader": None,
                "defects": ["reader_misses"],
            }
        )
    for r in left_r:
        out.append(
            {
                "level": r["kind"],
                "status": status(r),
                "mark": None,
                "reader": r,
                "defects": ["reader_extra"],
            }
        )
    return out


# --------------------------------------------------------------------------
# Defect patterns (what the reader gets wrong, by the printed marker)
# --------------------------------------------------------------------------


def marker_shape(kind: str, marker: str) -> str:
    """The printed marker reduced to its shape: digits as ``9``, a valid roman numeral
    as ``R``, a roman look-alike that is not one (``Il``, ``lII``, ``1V``) as ``R~``,
    so the OCR damage and the layout are what is counted, not the number."""
    m = " ".join(marker.split())
    if not m:
        return "(no marker)"
    if kind == "inc":
        head = re.match(r"[^\s\-–—.)]+", m)
        if head:
            word = head.group(0)
            valid = word.isalpha() and word.upper() == word and _valid_roman(word)
            if valid:
                return "R" + m[len(word) :]
            if set(word) <= _ROMAN_LOOKALIKE:
                return "R~" + m[len(word) :]
    if kind in ("par", "art"):
        # the digit of "§ 1º" read as a roman look-alike ("§ Io."): 9~; the ordinal
        # sign as it came out (º ° o) is one thing
        m = re.sub(r"^[sS5]\b", "§~", m)  # the section sign read as a letter
        m = re.sub(r"(?<=[§.~]\s)[Il|]+(?=[º°oO]?\b)", "9~", m)
        m = re.sub(r"(?<=\d)[º°oO]", "º", m)
        m = re.sub(r"(?<=9~)[º°oO]", "º", m)
    return re.sub(r"\d+", "9", m)


def _valid_roman(word: str) -> bool:
    return bool(
        re.fullmatch(
            r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})", word.upper()
        )
    ) and bool(word)


def context_tag(
    dev: dict[str, Any],
    text: str,
    anexos: list[tuple[int, int]],
    ruidos: list[tuple[int, int]],
) -> str:
    """Where a reader device sits in the mark document's text: ``in anexo/table`` (the
    model made it an annex), ``in ruido``, ``mid-line`` (text before it on the line: a
    mention inside a sentence) or ``line start``."""
    at = dev["offset"]
    if any(s <= at < e for s, e in anexos):
        return "in anexo/table"
    if any(s <= at < e for s, e in ruidos):
        return "in ruido"
    line_start = text.rfind("\n", 0, at) + 1
    return "mid-line" if text[line_start:at].strip() else "line start"


def snippet(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start : end if end >= 0 else len(text)].strip()[:CONTEXT]


class Patterns:
    """Counts the reader's sub-level defects by (defect, level, shape) and by
    (defect, level, context), keeping a few examples of each."""

    def __init__(self, examples: int) -> None:
        self.examples = examples
        self.by_shape: collections.Counter[tuple[str, str, str]] = collections.Counter()
        self.by_context: collections.Counter[tuple[str, str, str]] = (
            collections.Counter()
        )
        self.shape_examples: dict[tuple[str, str, str], list[dict[str, Any]]] = (
            collections.defaultdict(list)
        )
        self.context_examples: dict[tuple[str, str, str], list[dict[str, Any]]] = (
            collections.defaultdict(list)
        )

    def add(
        self,
        norm: str,
        text: str,
        outcome: dict[str, Any],
        anexos: list[tuple[int, int]],
        ruidos: list[tuple[int, int]],
    ) -> None:
        level = outcome["level"]
        if level not in SUB_LEVELS:
            return
        m, r = outcome["mark"], outcome["reader"]
        for defect in outcome["defects"]:
            # the printed marker: the reader's for an extra, else the mark document's
            printed = (r if defect == "reader_extra" else m)["marker"]
            if defect == "number_differs":
                kind_tag = f"{(m or r)['n']}->{(r or m)['n']}"
            elif defect == "kind_differs":
                kind_tag = f"{(m or r)['kind']}->{(r or m)['kind']}"
            else:
                kind_tag = ""
            shape = marker_shape(level, printed)
            ctx = (
                context_tag(r, text, anexos, ruidos)
                if defect == "reader_extra" and r
                else (context_tag(m, text, anexos, ruidos) if m else "?")
            )
            key = (defect, level, shape)
            self.by_shape[key] += 1
            ckey = (defect, level, ctx)
            self.by_context[ckey] += 1
            ex = {
                "norm": norm,
                "line": (r if defect == "reader_extra" else m)["line"],
                "printed": printed,
                "mark_n": m["n"] if m else None,
                "reader_n": r["n"] if r else None,
                "number_pair": kind_tag or None,
                "context": ctx,
                "text": snippet(text, (r if defect == "reader_extra" else m)["offset"]),
            }
            if len(self.shape_examples[key]) < self.examples:
                self.shape_examples[key].append(ex)
            if len(self.context_examples[ckey]) < self.examples:
                self.context_examples[ckey].append(ex)

    def ranked(self, which: str, top: int) -> list[dict[str, Any]]:
        counter = self.by_shape if which == "shape" else self.by_context
        examples = self.shape_examples if which == "shape" else self.context_examples
        return [
            {
                "defect": d,
                "level": lv,
                which: label,
                "count": n,
                "examples": examples[(d, lv, label)],
            }
            for (d, lv, label), n in counter.most_common(top)
        ]


# --------------------------------------------------------------------------
# Teacher
# --------------------------------------------------------------------------


def _roman(n: int) -> str:
    out = ""
    for value, sym in (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
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
            out += sym
            n -= value
    return out


def teacher_number(level: str, d: dict[str, Any]) -> str:
    """The number of a mark/reader device as the teacher writes it (``inc``: roman,
    ``item``: none, ``art``: ``5`` or ``5-A``)."""
    if level == "item":
        return "None"
    n, sfx = d["n"], d["sufixo"]
    if level == "inc":
        return _roman(int(n)) if n.isdigit() else n.upper()
    if level == "art":
        return ctr.normalize_number(f"{n}-{sfx}" if sfx else n)
    return n


def device_set(
    devs: Iterable[dict[str, Any]], level: str, quoted: bool
) -> set[tuple[int, str]]:
    return {
        (d["line"], teacher_number(level, d))
        for d in devs
        if d["kind"] == level and d["quoted"] == quoted
    }


def teacher_set(
    labels: list[dict[str, Any]], level: str, quoted: bool
) -> set[tuple[int, str]]:
    cat = TEACHER_CATEGORY[level]
    out: set[tuple[int, str]] = set()
    for lab in labels:
        if lab.get("category") != cat or bool(lab.get("quoted")) != quoted:
            continue
        num = lab.get("number")
        if level == "art":
            num = ctr.normalize_number(num)
        elif level == "item" or num is None:
            num = "None"
        out.add((int(lab["line"]), str(num)))
    return out


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------


def _blank_level() -> dict[str, Any]:
    return {
        "devices": collections.Counter(),
        "norm_groups": collections.Counter(),
        "norms_with": collections.Counter(),
    }


def _empty_table() -> dict[str, dict[str, Any]]:
    return {f"{lv}/{st}": _blank_level() for lv in LEVELS for st in ("own", "quoted")}


def _tally(table: dict[str, dict[str, Any]], outcomes: list[dict[str, Any]]) -> None:
    per_norm: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for o in outcomes:
        key = f"{o['level']}/{o['status']}"
        cell = table[key]
        cell["devices"]["total_outcomes"] += 1
        if o["mark"] is not None:
            cell["devices"]["mark_devices"] += 1
        if o["reader"] is not None and o["mark"] is not None:
            cell["devices"]["paired"] += 1
        if not o["defects"]:
            cell["devices"]["agree"] += 1
        for defect in o["defects"]:
            cell["devices"][defect] += 1
            per_norm[key][defect] += 1
        per_norm[key]["_seen"] += 1
    for key, c in per_norm.items():
        defects = [d for d in DEFECTS if c[d]]
        group = (
            "agree" if not defects else (defects[0] if len(defects) == 1 else "mixed")
        )
        table[key]["norm_groups"][group] += 1
        for d in defects:
            table[key]["norms_with"][d] += 1


def _render(table: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, cell in table.items():
        d = cell["devices"]
        if not d["total_outcomes"]:
            continue
        out[key] = {
            "mark_devices": d["mark_devices"],
            "paired": d["paired"],
            "agree": d["agree"],
            **{defect: d[defect] for defect in DEFECTS},
            "norm_groups": dict(cell["norm_groups"]),
            "norms_with": dict(cell["norms_with"]),
        }
    return out


def block_spans(xml: str, kind: str) -> list[tuple[int, int]]:
    return [(m.start, m.end) for m in marcacao.parse(xml)[1] if m.kind == kind]


def load_teacher(
    labels_dir: Path, errata_path: Optional[Path]
) -> tuple[
    dict[tuple[str, str], tuple[dict[str, Any], list[dict[str, Any]]]],
    Optional[ctr.Errata],
]:
    norms = ctr.load_labelled_norms(labels_dir)
    errata = ctr.load_errata(errata_path) if errata_path is not None else None
    return {(h["item"], h["txt_name"]): (h, labs) for h, labs in norms}, errata


def compare_run(
    run_dir: Path,
    *,
    variant: str = "as-is",
    labels_dir: Optional[Path] = None,
    errata_path: Optional[Path] = ctr.DEFAULT_ERRATA,
    examples: int = 3,
    top: int = 25,
) -> dict[str, Any]:
    docs = score_mark.load_documents(run_dir)
    fixed = score_mark.load_documents(run_dir, "marked-repaired")
    records = {str(r["texto_id"]): r for r in score_mark.load_records(run_dir)}
    teacher: dict[tuple[str, str], tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    errata: Optional[ctr.Errata] = None
    if labels_dir is not None:
        teacher, errata = load_teacher(labels_dir, errata_path)
    corrections: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    if errata is not None:
        for c in errata.corrections:
            corrections[str(c["norm"])].append(c)

    clean = _empty_table()
    flagged = _empty_table()
    everything = _empty_table()
    patterns = Patterns(examples)
    norm_rows: list[dict[str, Any]] = []
    vs_teacher: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    skipped: dict[str, list[str]] = collections.defaultdict(list)
    closure: collections.Counter[str] = collections.Counter()

    for texto_id, (xml, text) in sorted(docs.items()):
        rec = records.get(texto_id, {})
        if rec.get("reflow"):
            skipped["reflow variant"].append(texto_id)
            continue
        used = "as-is"
        suspects = rec.get("suspects", [])
        if variant == "repaired" and texto_id in fixed:
            xml, text = fixed[texto_id]
            used = "repaired"
            suspects = rec.get("repaired_suspects", [])
        flags = sorted({str(s["type"]) for s in suspects if s["type"] in SUSPECT_TYPES})
        m_devs = devices(xml, text)
        r_xml = score_mark.reader_document(text, rec)
        r_devs = devices(r_xml, text)
        pairs, m_only, r_only = pair_devices(m_devs, r_devs)
        outcomes = classify_pairs(pairs, m_only, r_only)
        _tally(everything, outcomes)
        _tally(flagged if flags else clean, outcomes)
        if not flags:
            anexos = block_spans(xml, "anexo")
            ruidos = block_spans(xml, "ruido")
            for o in outcomes:
                patterns.add(texto_id, text, o, anexos, ruidos)
        closed = rec.get("closure", {})
        closure[
            f"{used}: closes={closed.get('repaired' if used == 'repaired' else 'model')}"
        ] += 1
        row: dict[str, Any] = {
            "texto_id": texto_id,
            "variant": used,
            "flags": flags,
            "repairs": [r["kind"] for r in rec.get("repairs", [])]
            if used == "repaired"
            else [],
            "defects": dict(
                collections.Counter(
                    d for o in outcomes for d in o["defects"] if o["level"] in LEVELS
                )
            ),
        }
        # the label-mode teacher, where it saw this very text
        t = teacher.get((str(rec.get("item")), str(rec.get("txt_name"))))
        if t is not None:
            header, labels = t
            if header["text_sha256"] == ctr.sha256_text(text) or header[
                "text_sha256"
            ] == rec.get("text_sha256"):
                if corrections.get(ctr.norm_id(header)):
                    labels, _, _ = ctr.apply_corrections(
                        labels, corrections[ctr.norm_id(header)], text
                    )
                for level in LEVELS:
                    for quoted in (False, True):
                        key = f"{level}/{'quoted' if quoted else 'own'}"
                        ts = teacher_set(labels, level, quoted)
                        ms = device_set(m_devs, level, quoted)
                        rs = device_set(r_devs, level, quoted)
                        if not (ts or ms or rs):
                            continue
                        c = vs_teacher[key]
                        c["norms"] += 1
                        c["mark_eq_teacher"] += ms == ts
                        c["reader_eq_teacher"] += rs == ts
                        c["mark_eq_reader"] += ms == rs
                        c["mark_only_right"] += (ms == ts) and (rs != ts)
                        c["reader_only_right"] += (rs == ts) and (ms != ts)
                        c["teacher_devices"] += len(ts)
                        c["mark_devices_in_teacher"] += len(ms & ts)
                        c["reader_devices_in_teacher"] += len(rs & ts)
                        c["mark_devices"] += len(ms)
                        c["reader_devices"] += len(rs)
                        if level == "art" and not quoted:
                            row["art_mark_eq_teacher"] = ms == ts
                            row["art_reader_eq_teacher"] = rs == ts
                            row["art_mark_eq_reader"] = ms == rs
            else:
                skipped["teacher saw another text"].append(texto_id)
        norm_rows.append(row)

    return {
        "run": str(run_dir),
        "variant": variant,
        "norms": len(norm_rows),
        "norms_with_flags": sum(1 for r in norm_rows if r["flags"]),
        "flagged_norms": {r["texto_id"]: r["flags"] for r in norm_rows if r["flags"]},
        "repaired_norms": [
            r["texto_id"] for r in norm_rows if r["variant"] == "repaired"
        ],
        "skipped": {k: v for k, v in skipped.items()},
        "own_article_closure": dict(closure),
        "clean": _render(clean),
        "flagged": _render(flagged),
        "all": _render(everything),
        "vs_teacher": {k: dict(v) for k, v in sorted(vs_teacher.items())},
        "patterns_by_shape": patterns.ranked("shape", top),
        "patterns_by_context": patterns.ranked("context", top),
        "per_norm": norm_rows,
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def _level_table(title: str, table: dict[str, Any]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| level/status | mark devices | agree | reader misses | reader extra | number differs | status differs | kind differs | norm groups |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for key, c in table.items():
        groups = ", ".join(f"{k} {v}" for k, v in sorted(c["norm_groups"].items()))
        lines.append(
            f"| {key} | {c['mark_devices']} | {c['agree']} | {c['reader_misses']} | "
            f"{c['reader_extra']} | {c['number_differs']} | {c['status_differs']} | "
            f"{c['kind_differs']} | {groups} |"
        )
    lines.append("")
    return lines


def write_markdown(path: Path, s: dict[str, Any]) -> None:
    lines = [
        "# Reader against mark mode, per level",
        "",
        f"- run `{s['run']}`, variant `{s['variant']}`: {s['norms']} norms, "
        f"{s['norms_with_flags']} with suspect flags (tallied apart)",
        f"- repaired documents used: {s['repaired_norms']}",
        f"- own-article closure of the compared document: {s['own_article_closure']}",
        f"- skipped: { {k: len(v) for k, v in s['skipped'].items()} }",
        "",
        "## Per level",
        "",
    ]
    lines += _level_table("Clean norms (no suspect flag)", s["clean"])
    if s["flagged"]:
        lines += _level_table("Flagged norms", s["flagged"])
        lines.append(f"Flagged: {s['flagged_norms']}")
        lines.append("")
    if s["vs_teacher"]:
        lines += [
            "## Against the label-mode teacher (norms whose text it saw)",
            "",
            "| level/status | norms | mark = teacher | reader = teacher | mark = reader | only mark right | only reader right |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for key, c in s["vs_teacher"].items():
            lines.append(
                f"| {key} | {c['norms']} | {c['mark_eq_teacher']} | {c['reader_eq_teacher']} | "
                f"{c['mark_eq_reader']} | {c['mark_only_right']} | {c['reader_only_right']} |"
            )
        lines.append("")
    for which, title in (
        ("shape", "by printed marker shape"),
        ("context", "by where it sits"),
    ):
        lines += [f"## Reader sub-level defects {title} (clean norms)", ""]
        for i, p in enumerate(s[f"patterns_by_{which}"], 1):
            lines.append(
                f"{i}. **{p['count']}** x {p['defect']} / {p['level']} / `{p[which]}`"
            )
            for ex in p["examples"]:
                lines.append(
                    f"   - {ex['norm']} l.{ex['line']}: `{ex['printed']}` mark={ex['mark_n']} "
                    f"reader={ex['reader_n']} ({ex['context']}) | {ex['text']}"
                )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", type=Path, required=True, help="collect out dir")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variant", choices=("as-is", "repaired"), default="as-is")
    parser.add_argument("--labels", type=Path, help="label-mode collect dir (teacher)")
    parser.add_argument("--errata", type=Path, default=ctr.DEFAULT_ERRATA)
    parser.add_argument("--no-errata", action="store_true")
    parser.add_argument("--examples", type=int, default=3)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args(argv)
    result = compare_run(
        args.run,
        variant=args.variant,
        labels_dir=args.labels,
        errata_path=None if args.no_errata else args.errata,
        examples=args.examples,
        top=args.top,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "compare_mark_reader.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    write_markdown(args.out / "compare_mark_reader.md", result)
    clean = result["clean"]
    print(
        f"{result['norms']} norms ({result['norms_with_flags']} flagged); clean: "
        + "; ".join(
            f"{k} agree {c['agree']}/{c['mark_devices']}" for k, c in clean.items()
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
