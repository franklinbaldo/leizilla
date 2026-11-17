"""Score a teacher-batch MARK run (offline).

``leizilla.teacher_batch collect`` in mark mode writes ``marked/`` (one marked document
per norm), ``records/`` (state and dropped marks per norm), ``anchors.jsonl`` (one row
per mark the model gave, with both anchors resolved), ``summary.json`` and
``failures.jsonl``. This script reads them (the marked documents carry their own text,
so no label or text directory is needed) and answers, in four blocks:

1. **Column accuracy.** Anchor A (the column ``c``) against anchor B (the marker
   ``t``, resolved by exact match) and, separately, against the rule reader's marker
   offset for the devices the reader also found on that line: exact-match rate, the
   A-B distribution, buckets (line length, column, non-ASCII before the column, kind),
   whether the error is a constant offset and what A would score after the best
   constant correction, how often a 3-4 character check of A against ``t`` would
   have been enough, and the token cost of ``c`` against ``t``.
2. **Agreement with the rule reader** per level (art, par, inc, ali, item), own and
   quoted: matched / only-model / only-reader, from ``marcacao.to_rows`` of both
   documents, and the article closure of the model's parse.
3. **Coverage**: the share of non-blank characters inside ``<lei>`` outside any
   element (unowned), against the reader's document of the same norm; counts per block
   kind; the share of the text that is ``ruido``.
4. **Outcomes**: states of the norms, build/verify, dropped marks by reason,
   truncations, measured cost, cost per norm against the label mode's US$0.00063.

    uv run scripts/score_mark.py --run COLLECT_DIR --out OUT_DIR [--label-cost 0.00063]
"""

from __future__ import annotations

import argparse
import bisect
import collections
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

from leizilla import marcacao, teacher_batch as tb
from leizilla import teacher_mark as tm
from leizilla.hierarchy_sequence import article_closes, read_hierarchy
from leizilla.teacher_review import chain_intact

# Measured by the label mode on the 2086-norm main run.
LABEL_MODE_USD_PER_NORM = 0.00063
DELTA_RANGE = range(-3, 4)
LEVELS: tuple[str, ...] = ("art", "par", "inc", "ali", "item")
LINE_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("<=40", 0, 40),
    ("41-80", 41, 80),
    ("81-160", 81, 160),
    (">160", 161, 10**9),
)
COLUMN_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-10", 0, 10),
    ("11-40", 11, 40),
    ("41+", 41, 10**9),
)
# The stress set (re-flowed lines of 200-400 characters) spreads the markers further.
STRESS_COLUMN_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-10", 0, 10),
    ("11-40", 11, 40),
    ("41-100", 41, 100),
    ("101-200", 101, 200),
    ("201-400", 201, 400),
    ("401+", 401, 10**9),
)


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


def load_anchors(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_documents(root: Path) -> dict[str, tuple[str, str]]:
    """``texto_id`` -> ``(xml, text)`` for every marked document under ``marked/``."""
    docs: dict[str, tuple[str, str]] = {}
    base = root / "marked"
    if not base.is_dir():
        return docs
    for path in sorted(base.rglob("*.xml")):
        xml = path.read_text(encoding="utf-8")
        attrs = marcacao.root_attributes(xml)
        docs[str(attrs.get("texto-id", path.stem))] = (xml, marcacao.strip(xml))
    return docs


def load_records(root: Path) -> list[dict[str, Any]]:
    base = root / "records"
    if not base.is_dir():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(base.rglob("*.json"))
    ]


# --------------------------------------------------------------------------
# 1. Column accuracy
# --------------------------------------------------------------------------


def _rate(hits: int, n: int) -> Optional[float]:
    return round(hits / n, 4) if n else None


def _bucket(value: int, buckets: Iterable[tuple[str, int, int]]) -> str:
    for name, lo, hi in buckets:
        if lo <= value <= hi:
            return name
    return "?"


def _exact_table(rows: list[dict[str, Any]], key: Any) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        groups[str(key(r))].append(r)
    return {
        name: {
            "n": len(g),
            "a_exact": sum(1 for r in g if r["delta"] == 0),
            "rate": _rate(sum(1 for r in g if r["delta"] == 0), len(g)),
        }
        for name, g in sorted(groups.items())
    }


def _delta_bucket(delta: int) -> str:
    if delta < DELTA_RANGE.start:
        return f"<{DELTA_RANGE.start}"
    if delta > DELTA_RANGE.stop - 1:
        return f">{DELTA_RANGE.stop - 1}"
    return f"{delta:+d}" if delta else "0"


def _json_field_chars(name: str, value: Any) -> int:
    return len(f'"{name}":') + len(json.dumps(value, ensure_ascii=False)) + 1


def token_cost(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Characters and estimated tokens (the code's conservative 2 chars/token) that
    anchor A (``c``) and anchor B (``t``) take in the response, against all the fields
    of the marks (le/x/e/nota counted as their usual null/false)."""
    # snippet mode has no ``c``: its position field is ``o`` (the occurrence)
    pos = "c" if any(r.get("c") is not None for r in rows) else "o"
    c_chars = sum(_json_field_chars(pos, r.get(pos)) for r in rows)
    t_chars = sum(_json_field_chars("t", r.get("t")) for r in rows)
    total = 0
    for r in rows:
        total += _json_field_chars("l", r.get("line"))
        total += _json_field_chars("k", r.get("kind"))
        total += _json_field_chars(pos, r.get(pos))
        total += _json_field_chars("t", r.get("t"))
        total += _json_field_chars("n", r.get("n"))
        total += _json_field_chars("s", r.get("s"))
        total += (
            _json_field_chars("le", None)
            + _json_field_chars("x", False)
            + _json_field_chars("e", None)
            + _json_field_chars("nota", None)
        )
    cpt = tb.CHARS_PER_TOKEN
    return {
        "marks": len(rows),
        "c_chars": c_chars,
        "t_chars": t_chars,
        "c_tokens": math.ceil(c_chars / cpt),
        "t_tokens": math.ceil(t_chars / cpt),
        "all_fields_tokens": math.ceil(total / cpt),
        "c_share": round(c_chars / total, 4) if total else None,
        "t_share": round(t_chars / total, 4) if total else None,
        "chars_per_token": cpt,
    }


def column_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A against B, over the marks whose B resolves EXACTLY (unique exact match) and
    whose column A is inside the line."""
    answered = [r for r in rows if r.get("kind") is not None and r.get("t")]
    ref = [
        r
        for r in answered
        if r.get("b_method") == "exact" and r.get("delta") is not None
    ]
    deltas = collections.Counter(int(r["delta"]) for r in ref)
    dist = collections.Counter(_delta_bucket(int(r["delta"])) for r in ref)
    order = [f"<{DELTA_RANGE.start}", *[_delta_bucket(d) for d in DELTA_RANGE]]
    order.append(f">{DELTA_RANGE.stop - 1}")
    exact = deltas.get(0, 0)
    errors = [r for r in ref if r["delta"] != 0]
    err_deltas = collections.Counter(int(r["delta"]) for r in errors)
    best_k, best_n = deltas.most_common(1)[0] if deltas else (0, 0)
    err_mode, err_mode_n = err_deltas.most_common(1)[0] if err_deltas else (0, 0)
    by_col: dict[str, collections.Counter[int]] = collections.defaultdict(
        collections.Counter
    )
    for r in errors:
        by_col[_bucket(int(r["b_col"]) - 1, COLUMN_BUCKETS)][int(r["delta"])] += 1

    def confirm(field: str) -> dict[str, Any]:
        have = [r for r in ref if r.get(field) is not None]
        conf = [r for r in have if r[field]]
        right = [r for r in have if r["delta"] == 0]
        wrong = [r for r in have if r["delta"] != 0]
        return {
            "n": len(have),
            "confirmed": len(conf),
            "a_right_and_confirmed": sum(1 for r in conf if r["delta"] == 0),
            "precision_when_confirmed": _rate(
                sum(1 for r in conf if r["delta"] == 0), len(conf)
            ),
            "wrong_a": len(wrong),
            "wrong_a_caught": sum(1 for r in wrong if not r[field]),
            "wrong_a_detection_rate": _rate(
                sum(1 for r in wrong if not r[field]), len(wrong)
            ),
            "right_a_wrongly_rejected": sum(1 for r in right if not r[field]),
            "enough_rate": _rate(
                sum(1 for r in conf if r["delta"] == 0)
                + sum(1 for r in wrong if not r[field]),
                len(have),
            ),
        }

    ambiguous = [r for r in answered if r.get("b_method") == "ambiguous"]
    return {
        "marks_answered": len(answered),
        "b_methods": dict(
            collections.Counter(str(r.get("b_method")) for r in answered)
        ),
        "a_out_of_range": sum(1 for r in answered if r.get("a_off") is None),
        "reference_n": len(ref),
        "a_exact": exact,
        "a_exact_rate": _rate(exact, len(ref)),
        "delta_distribution": {k: dist.get(k, 0) for k in order},
        "by_line_length": _exact_table(
            ref, lambda r: _bucket(int(r["line_len"]), LINE_BUCKETS)
        ),
        "by_column": _exact_table(
            ref, lambda r: _bucket(int(r["b_col"]) - 1, COLUMN_BUCKETS)
        ),
        "by_column_fine": _exact_table(
            ref, lambda r: _bucket(int(r["b_col"]) - 1, STRESS_COLUMN_BUCKETS)
        ),
        "by_nonascii_before": _exact_table(
            ref,
            lambda r: "non-ascii before" if r.get("nonascii_before") else "ascii only",
        ),
        "by_kind": _exact_table(ref, lambda r: r["kind"]),
        "systematic": {
            "most_common_delta": best_k if deltas else None,
            "rate_at_most_common_delta": _rate(best_n, len(ref)),
            "accuracy_after_best_constant_correction": _rate(best_n, len(ref)),
            "most_common_error_delta": err_mode if errors else None,
            "share_of_errors_with_that_delta": _rate(err_mode_n, len(errors)),
            "accuracy_if_that_delta_is_corrected": _rate(exact + err_mode_n, len(ref))
            if errors
            else _rate(exact, len(ref)),
            "error_deltas_by_column_bucket": {
                k: dict(sorted(v.items())) for k, v in sorted(by_col.items())
            },
        },
        "check_4_chars": confirm("a_confirm4"),
        "check_3_chars": confirm("a_confirm3"),
        "b_ambiguous": {
            "n": len(ambiguous),
            "a_among_candidates": sum(1 for r in ambiguous if r.get("a_in_candidates")),
        },
        "token_cost": token_cost(answered),
    }


def reader_markers(text: str, shown: Optional[str] = None) -> list[dict[str, Any]]:
    """The reader's device markers ``{line, kind, n, offset}`` of one text.

    ``shown`` is the text the model saw when it differs from ``text`` only in its
    newlines (a re-flowed variant: same length, so the offsets carry over); the lines
    are then those of ``shown``."""
    starts = [0]
    for i, ch in enumerate(shown if shown is not None else text):
        if ch == "\n":
            starts.append(i + 1)
    marks = marcacao.from_hierarchy(text, read_hierarchy(text))
    out = []
    for m in marks:
        if m.kind in marcacao.DEVICES and m.marker is not None:
            out.append(
                {
                    "line": bisect.bisect_right(starts, m.marker[0]),
                    "kind": m.kind,
                    "n": m.attrs.get("n"),
                    "offset": m.marker[0],
                }
            )
    return out


def base_text(text: str, record: dict[str, Any]) -> str:
    """The text the reader reads: ``text`` itself, or for a re-flowed stress variant
    its base (the joined newlines put back)."""
    reflow = record.get("reflow")
    return tm.unflow_text(text, reflow["joined"]) if reflow else text


def reader_reference(
    rows: list[dict[str, Any]],
    docs: dict[str, tuple[str, str]],
    records: Optional[dict[str, dict[str, Any]]] = None,
    only_reflow: Optional[bool] = None,
) -> dict[str, Any]:
    """A and B against the reader's marker offset, for the devices (with a marker)
    the reader also found on the same line with the same kind. For a re-flowed
    variant the reader reads the base text and its offsets are carried over.
    ``only_reflow``: ``True`` keeps the stress variants only, ``False`` the rest.
    Also by column bucket of the true marker in the shown line (A, B, used offset)."""
    records = records or {}
    by_norm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        by_norm[str(r.get("texto_id"))].append(r)
    n = a_n = a_ok = b_ok = b_n = used_ok = 0
    cells: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: collections.Counter()  # type: ignore[arg-type]
    )
    nonascii: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: collections.Counter()  # type: ignore[arg-type]
    )
    by_cand: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: collections.Counter()  # type: ignore[arg-type]
    )
    for texto_id, group in by_norm.items():
        if texto_id not in docs:
            continue
        rec = records.get(texto_id, {})
        if only_reflow is not None and bool(rec.get("reflow")) != only_reflow:
            continue
        shown = docs[texto_id][1]
        found = reader_markers(base_text(shown, rec), shown)
        lines = tb.split_lines(shown)
        line_starts = [0]
        for ln in lines[:-1]:
            line_starts.append(line_starts[-1] + len(ln) + 1)
        for r in group:
            if r.get("kind") not in marcacao.DEVICES or r.get("offset") is None:
                continue
            cands = [
                m
                for m in found
                if m["line"] == r.get("line") and m["kind"] == r["kind"]
            ]
            if len(cands) > 1:
                cands = [m for m in cands if str(m["n"]) == str(r.get("n"))]
            if len(cands) != 1:
                continue
            n += 1
            ref = cands[0]["offset"]
            if r.get("a_off") is not None:
                a_n += 1
                a_ok += r["a_off"] == ref
            if r.get("b_off") is not None:
                b_n += 1
                b_ok += r["b_off"] == ref
            used_ok += r.get("offset") == ref
            ln = int(cands[0]["line"])
            lead = len(lines[ln - 1]) - len(lines[ln - 1].lstrip())
            col = ref - line_starts[ln - 1] - lead
            name = _bucket(col, STRESS_COLUMN_BUCKETS)
            cell = cells[name]
            cell["n"] += 1
            cell["a_exact"] += r.get("a_off") == ref
            cell["b_resolved"] += r.get("b_off") is not None
            cell["b_exact"] += r.get("b_off") == ref
            cell["used_exact"] += r.get("offset") == ref
            cell["used_A"] += r.get("used") == "A"
            cell["used_O"] += r.get("used") == "O"
            cell["used_O_exact"] += r.get("used") == "O" and r.get("offset") == ref
            cand = int(r.get("b_candidates") or 0)
            ck = "1" if cand <= 1 else ("2-3" if cand <= 3 else "4+")
            by_cand[ck]["n"] += 1
            by_cand[ck]["used_exact"] += r.get("offset") == ref
            na = (
                "non-ascii before"
                if any(ord(ch) > 127 for ch in lines[ln - 1].strip()[: max(0, col)])
                else "ascii only"
            )
            cell = nonascii[na]
            cell["n"] += 1
            cell["a_exact"] += r.get("a_off") == ref
            cell["b_exact"] += r.get("b_off") == ref
            cell["used_exact"] += r.get("offset") == ref
    order = [name for name, _, _ in STRESS_COLUMN_BUCKETS]

    def table(src: dict[str, dict[str, int]], keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in keys:
            c = src.get(k)
            if not c:
                continue
            out[k] = {
                **dict(c),
                "a_exact_rate": _rate(c["a_exact"], c["n"]),
                "b_exact_rate": _rate(c["b_exact"], c["n"]),
                "used_exact_rate": _rate(c["used_exact"], c["n"]),
            }
        return out

    return {
        "by_true_column": table(cells, order),
        "by_nonascii_before": table(nonascii, ["ascii only", "non-ascii before"]),
        "by_occurrences_in_line": table(by_cand, ["1", "2-3", "4+"]),
        "devices_matched_to_reader": n,
        "a_exact": a_ok,
        "a_exact_rate": _rate(a_ok, a_n),
        "b_resolved": b_n,
        "b_exact": b_ok,
        "b_exact_rate": _rate(b_ok, b_n),
        "used_offset_exact": used_ok,
        "used_offset_exact_rate": _rate(used_ok, n),
    }


def snippet_resolution(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Snippet anchor mode (no column): how the marks were located. ``None`` for a
    run that gave columns. Resolved = ``used`` B (``t`` unique in the line, or a prefix
    of ``t`` that reaches the line end) or O (the model's occurrence number ``o``);
    the rest is dropped with ``ambiguous_snippet``, ``bad_occurrence`` or
    ``no_anchor``."""
    answered = [r for r in rows if r.get("kind") is not None and r.get("t")]
    if not answered or any(r.get("c") is not None for r in answered):
        return None
    resolved = [r for r in answered if r.get("used")]
    dropped = collections.Counter(
        str(r.get("drop_reason")) for r in answered if not r.get("used")
    )
    tied = [r for r in answered if int(r.get("b_candidates") or 0) > 1]
    with_o = [r for r in answered if r.get("o") is not None]
    return {
        "marks_answered": len(answered),
        "resolved": len(resolved),
        "resolved_rate": _rate(len(resolved), len(answered)),
        "used": dict(collections.Counter(str(r["used"]) for r in resolved)),
        "b_methods": dict(
            collections.Counter(str(r.get("b_method")) for r in answered)
        ),
        "dropped_by_reason": dict(sorted(dropped.items())),
        "marks_with_tie_in_line": len(tied),
        "tie_resolved_with_o": sum(1 for r in tied if r.get("used") == "O"),
        "tie_dropped_no_o": sum(
            1 for r in tied if r.get("drop_reason") == "ambiguous_snippet"
        ),
        "o_given": len(with_o),
        "o_greater_than_1": sum(1 for r in with_o if int(r["o"]) > 1),
        "o_given_but_unique": sum(
            1 for r in with_o if int(r.get("b_candidates") or 0) <= 1
        ),
    }


# --------------------------------------------------------------------------
# 2. Agreement with the rule reader
# --------------------------------------------------------------------------


def _keyed(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    seen: collections.Counter[tuple[Any, ...]] = collections.Counter()
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        if r["kind"] not in LEVELS:
            continue
        base = (r["kind"], bool(r["quoted"]), r["path"])
        seen[base] += 1
        out[(*base, seen[base])] = r
    return out


def agreement(
    model_rows: list[dict[str, Any]], reader_rows: list[dict[str, Any]], text: str
) -> dict[str, dict[str, int]]:
    """Per ``level/own|quoted``: matched, only_model, only_reader (devices matched by
    path, in order of occurrence) and ``same_start_line`` among the matched."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    mine, theirs = _keyed(model_rows), _keyed(reader_rows)
    out: dict[str, dict[str, int]] = {}

    def bucket(row: dict[str, Any]) -> dict[str, int]:
        name = f"{row['kind']}/{'quoted' if row['quoted'] else 'own'}"
        return out.setdefault(
            name,
            {"matched": 0, "only_model": 0, "only_reader": 0, "same_start_line": 0},
        )

    for key, row in mine.items():
        if key in theirs:
            b = bucket(row)
            b["matched"] += 1
            line_a = bisect.bisect_right(starts, row["start"])
            line_b = bisect.bisect_right(starts, theirs[key]["start"])
            b["same_start_line"] += line_a == line_b
        else:
            bucket(row)["only_model"] += 1
    for key, row in theirs.items():
        if key not in mine:
            bucket(row)["only_reader"] += 1
    return out


def model_closes(
    rows: list[dict[str, Any]], text: str, acts: Optional[list[tuple[int, int]]] = None
) -> bool:
    """Whether the model's own articles close (``chain_intact``), act by act: a file
    with several acts (a law and copies of its bill) closes when each act does.
    ``acts`` are the ``(start, end)`` spans of the ``lei`` elements; without them the
    whole text is one act."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    spans = acts or [(0, len(text) + 1)]
    seen = False
    for lo, hi in spans:
        arts = [
            [
                bisect.bisect_right(starts, r["start"]),
                str(r["n"]) + (f"-{r['sufixo']}" if r.get("sufixo") else ""),
                bool(r["quoted"]),
            ]
            for r in rows
            if r["kind"] == "art" and lo <= r["start"] < hi
        ]
        if not arts:
            continue
        seen = True
        if not chain_intact(arts):
            return False
    return seen


# --------------------------------------------------------------------------
# 3. Coverage
# --------------------------------------------------------------------------


def _union(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _nonblank_prefix(text: str) -> list[int]:
    prefix = [0]
    for ch in text:
        prefix.append(prefix[-1] + (0 if ch.isspace() else 1))
    return prefix


def _nonblank_in(prefix: list[int], spans: list[tuple[int, int]]) -> int:
    return sum(prefix[e] - prefix[s] for s, e in spans)


def coverage(xml: str) -> dict[str, Any]:
    """Unowned share inside ``<lei>`` (non-blank characters outside every element
    except ``lei`` itself), block-kind counts and the ``ruido`` share of the text."""
    text, marks = marcacao.parse(xml)
    prefix = _nonblank_prefix(text)
    kinds = collections.Counter(m.kind for m in marks if m.kind != "nota")
    lei = next((m for m in marks if m.kind == "lei"), None)
    spans = [
        (m.start, m.end)
        for m in marks
        if m.kind not in ("lei", "nota") and m.end > m.start
    ]
    ruido = _union([(m.start, m.end) for m in marks if m.kind == "ruido"])
    total_nb = prefix[-1]
    out: dict[str, Any] = {
        "kinds": dict(kinds),
        "has_lei": lei is not None,
        "unowned_share": None,
        "lei_nonblank": 0,
        "ruido_share": round(_nonblank_in(prefix, ruido) / total_nb, 4)
        if total_nb
        else None,
    }
    if lei is not None:
        inside = [
            (max(s, lei.start), min(e, lei.end))
            for s, e in _union(spans)
            if e > lei.start and s < lei.end
        ]
        lei_nb = prefix[lei.end] - prefix[lei.start]
        owned = _nonblank_in(prefix, inside)
        out["lei_nonblank"] = lei_nb
        out["unowned_share"] = round((lei_nb - owned) / lei_nb, 4) if lei_nb else None
    return out


def reader_document(text: str, record: dict[str, Any]) -> str:
    text = base_text(text, record)
    marks = marcacao.from_hierarchy(
        text,
        read_hierarchy(text),
        tipo=record.get("tipo"),
        numero=record.get("numero"),
    )
    return marcacao.build(text, marks)


# --------------------------------------------------------------------------
# Blocks: alteracao against the reader's quoted blocks, anexo ends, suspects
# --------------------------------------------------------------------------


def _line_numbers(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def alteracao_comparison(
    xml: str, text: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each model ``alteracao`` (line range) next to the reader's quoted blocks that
    overlap it: ``same`` when the ranges coincide, ``longer_in_reader`` when the reader
    goes on past the model's last line (the model cut the block short), ``shorter``,
    ``only_model`` (the reader found none) and ``only_reader`` rows for the reader's
    blocks no model block overlaps. Lines are those of the shown text."""
    starts = _line_numbers(text)

    def line(offset: int) -> int:
        return bisect.bisect_right(starts, max(0, offset))

    _, marks = marcacao.parse(xml)
    model = [
        (line(m.start), line(max(m.start, m.end - 1)))
        for m in marks
        if m.kind == "alteracao"
    ]
    rep = read_hierarchy(base_text(text, record))
    reader = [
        (line(n["start"]), line(max(n["start"], n["end"] - 1)))
        for n in rep["nodes"]
        if n["kind"] == "quoted_block"
    ]
    suspect_lines = {
        int(x["line"])
        for x in record.get("suspects", [])
        if x.get("type") == "suspect_alteracao"
    }
    out: list[dict[str, Any]] = []
    used: set[int] = set()
    for lo, hi in model:
        hits = [(i, r) for i, r in enumerate(reader) if r[0] <= hi and lo <= r[1]]
        used.update(i for i, _ in hits)
        status = "only_model"
        if hits:
            r_lo, r_hi = hits[0][1]
            status = (
                "same"
                if (r_lo, r_hi) == (lo, hi)
                else "longer_in_reader"
                if max(h[1][1] for h in hits) > hi
                else "shorter_in_reader"
            )
        out.append(
            {
                "model": [lo, hi],
                "reader": [list(h[1]) for h in hits],
                "status": status,
                "flagged": lo in suspect_lines,
            }
        )
    for i, r in enumerate(reader):
        if i not in used:
            out.append(
                {
                    "model": None,
                    "reader": [list(r)],
                    "status": "only_reader",
                    "flagged": False,
                }
            )
    return out


def anexo_ends(
    xml: str, text: str, rows: list[dict[str, Any]], norm_key: str
) -> list[dict[str, Any]]:
    """For each ``anexo`` of the document: the line the model gave as its end (``le``)
    and the line where the converter ended it (the next mark)."""
    starts = _line_numbers(text)
    _, marks = marcacao.parse(xml)
    gave = {
        (int(r["line"]), r["kind"]): r.get("le")
        for r in rows
        if r.get("kind") == "anexo" and r.get("used") and r.get("norm") == norm_key
    }
    out = []
    for m in marks:
        if m.kind != "anexo":
            continue
        first = bisect.bisect_right(starts, m.start)
        end = bisect.bisect_right(starts, max(m.start, m.end - 1))
        le = gave.get((first, "anexo"))
        out.append({"line": first, "model_le": le, "end_line": end})
    return out


# --------------------------------------------------------------------------
# Scoring (pure over the loaded run)
# --------------------------------------------------------------------------


def _quantiles(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = sorted(values)

    def q(p: float) -> float:
        return round(v[min(len(v) - 1, int(p * len(v)))], 4)

    return {
        "n": len(v),
        "mean": round(sum(v) / len(v), 4),
        "median": q(0.5),
        "p10": q(0.1),
        "p90": q(0.9),
    }


def score_run(
    rows: list[dict[str, Any]],
    docs: dict[str, tuple[str, str]],
    records: list[dict[str, Any]],
    summary: Optional[dict[str, Any]],
    label_cost: float = LABEL_MODE_USD_PER_NORM,
) -> dict[str, Any]:
    by_id = {str(r["texto_id"]): r for r in records}
    agree: dict[str, dict[str, int]] = {}
    closure = collections.Counter()
    unowned_model: list[float] = []
    unowned_reader: list[float] = []
    unowned_diff: list[float] = []
    kinds: collections.Counter[str] = collections.Counter()
    ruido: list[float] = []
    closure_raw: collections.Counter[str] = collections.Counter()
    blocks: dict[str, list[dict[str, Any]]] = {}
    block_status: collections.Counter[str] = collections.Counter()
    annexes: dict[str, list[dict[str, Any]]] = {}
    suspect_counts: collections.Counter[str] = collections.Counter()
    suspect_norms: dict[str, list[str]] = {}
    acts_per_norm: dict[str, int] = {}
    for texto_id, (xml, text) in sorted(docs.items()):
        record = by_id.get(texto_id, {})
        m_rows = marcacao.to_rows(xml)
        r_xml = reader_document(text, record)
        r_rows = marcacao.to_rows(r_xml)
        for name, counts in agreement(m_rows, r_rows, text).items():
            bucket = agree.setdefault(name, collections.Counter())
            bucket.update(counts)
        leis = [(m.start, m.end) for m in marcacao.parse(xml)[1] if m.kind == "lei"]
        if len(leis) > 1:
            acts_per_norm[texto_id] = len(leis)
        m_close_raw = model_closes(m_rows, text, leis)
        dropped_arts = sum(
            1 for d in record.get("dropped", []) if d.get("kind") == "art"
        )
        # an article the model gave and the converter dropped is not "closed"
        m_close = m_close_raw and not dropped_arts
        r_close = article_closes(read_hierarchy(base_text(text, record)))
        reader_state = "closes" if r_close else "open"
        closure[f"model={'closes' if m_close else 'open'}/reader={reader_state}"] += 1
        closure_raw[
            f"model={'closes' if m_close_raw else 'open'}/reader={reader_state}"
        ] += 1
        cmp_rows = alteracao_comparison(xml, text, record)
        if cmp_rows:
            blocks[texto_id] = cmp_rows
            block_status.update(c["status"] for c in cmp_rows)
        ends = anexo_ends(xml, text, rows, str(record.get("key")))
        if ends:
            annexes[texto_id] = ends
        for sus in record.get("suspects", []):
            suspect_counts[str(sus["type"])] += 1
            suspect_norms.setdefault(texto_id, []).append(str(sus["type"]))
        cov_m, cov_r = coverage(xml), coverage(r_xml)
        kinds.update(cov_m["kinds"])
        if cov_m["ruido_share"] is not None:
            ruido.append(cov_m["ruido_share"])
        if cov_m["unowned_share"] is not None:
            unowned_model.append(cov_m["unowned_share"])
        if cov_r["unowned_share"] is not None:
            unowned_reader.append(cov_r["unowned_share"])
            if cov_m["unowned_share"] is not None:
                unowned_diff.append(cov_m["unowned_share"] - cov_r["unowned_share"])
    states = collections.Counter(str(r.get("state")) for r in records)
    outcomes: dict[str, Any] = {
        "norms": len(records),
        "states": dict(sorted(states.items())),
        "built": len(docs),
    }
    if summary is not None:
        measured = summary.get("measured_usd")
        per_norm = summary.get("measured_usd_per_norm")
        outcomes.update(
            {
                "marks_answered": summary.get("marks_answered"),
                "marks_used": summary.get("marks_used"),
                "marks_dropped": summary.get("marks_dropped"),
                "dropped_by_reason": summary.get("dropped_by_reason"),
                "requests_truncated": summary.get("requests_truncated"),
                "failure_reasons": summary.get("failure_reasons"),
                "usage": summary.get("usage"),
                "measured_usd": measured,
                "measured_usd_per_norm": per_norm,
                "label_mode_usd_per_norm": label_cost,
                "ratio_to_label_mode": round(per_norm / label_cost, 3)
                if per_norm
                else None,
            }
        )
    else:
        reasons = collections.Counter(
            str(d.get("reason")) for r in records for d in r.get("dropped", [])
        )
        outcomes["dropped_by_reason"] = dict(sorted(reasons.items()))
    return {
        "column_accuracy": column_accuracy(rows),
        "snippet_resolution": snippet_resolution(rows),
        "reader_reference": reader_reference(rows, docs, by_id),
        "stress": (
            reader_reference(rows, docs, by_id, only_reflow=True)
            if any(r.get("reflow") for r in records)
            else None
        ),
        "anchors_used": dict(
            collections.Counter(str(r.get("used")) for r in rows if r.get("used"))
        ),
        "acts_per_norm": acts_per_norm,
        "suspects": {
            "by_type": dict(suspect_counts),
            "norms": suspect_norms,
        },
        "alteracao_vs_reader": {
            "status": dict(block_status),
            "blocks": blocks,
        },
        "anexo_ends": {
            "n": sum(len(v) for v in annexes.values()),
            "extended_past_model_le": sum(
                1
                for v in annexes.values()
                for a in v
                if a["model_le"] is not None and a["end_line"] > a["model_le"]
            ),
            "by_norm": annexes,
        },
        "article_closure_raw": dict(sorted(closure_raw.items())),
        "agreement_with_reader": {k: dict(v) for k, v in sorted(agree.items())},
        "article_closure": dict(sorted(closure.items())),
        "coverage": {
            "model_unowned_share": _quantiles(unowned_model),
            "reader_unowned_share": _quantiles(unowned_reader),
            "model_minus_reader_unowned": _quantiles(unowned_diff),
            "model_kinds": dict(sorted(kinds.items())),
            "ruido_share_per_norm": _quantiles(ruido),
        },
        "outcomes": outcomes,
    }


def write_markdown(path: Path, s: dict[str, Any]) -> None:
    ca, rr = s["column_accuracy"], s["reader_reference"]
    o = s["outcomes"]
    lines = ["# Mark run score", ""]
    lines += [
        "## 1. Column accuracy (A against B exact)",
        "",
        f"- marks answered {ca['marks_answered']}; B methods {ca['b_methods']}; "
        f"A out of range {ca['a_out_of_range']}",
        f"- reference (B exact) {ca['reference_n']}: A exact {ca['a_exact']} "
        f"({ca['a_exact_rate']})",
        f"- A-B distribution: {ca['delta_distribution']}",
        f"- systematic: {ca['systematic']}",
        f"- by line length: {ca['by_line_length']}",
        f"- by column: {ca['by_column']}",
        f"- by column (fine): {ca['by_column_fine']}",
        f"- by non-ASCII before: {ca['by_nonascii_before']}",
        f"- by kind: {ca['by_kind']}",
        f"- 4-char check: {ca['check_4_chars']}",
        f"- 3-char check: {ca['check_3_chars']}",
        f"- B ambiguous: {ca['b_ambiguous']}",
        f"- token cost: {ca['token_cost']}",
        f"- against the reader's marker offsets: {rr}",
        *(
            [f"- snippet mode (no column): {s['snippet_resolution']}"]
            if s.get("snippet_resolution")
            else []
        ),
        "",
        "## 2. Agreement with the rule reader",
        "",
        "| level/status | matched | only model | only reader | same start line |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, c in s["agreement_with_reader"].items():
        lines.append(
            f"| {name} | {c['matched']} | {c['only_model']} | {c['only_reader']} "
            f"| {c['same_start_line']} |"
        )
    lines += [
        "",
        f"Article closure (own articles per act, none dropped): {s['article_closure']}",
        f"Article closure of the document as built: {s['article_closure_raw']}",
        f"Norms with more than one act: {s['acts_per_norm']}",
        "",
        "## 2b. Policy, suspects, blocks",
        "",
        f"- anchors used: {s['anchors_used']}",
        f"- suspects by type: {s['suspects']['by_type']}",
        f"- suspect norms: {s['suspects']['norms']}",
        f"- alteracao against the reader's quoted blocks: "
        f"{s['alteracao_vs_reader']['status']}",
    ]
    for texto_id, cmp_rows in s["alteracao_vs_reader"]["blocks"].items():
        odd = [c for c in cmp_rows if c["status"] != "same"]
        if odd:
            lines.append(f"  - {texto_id}: {odd}")
    ae = s["anexo_ends"]
    lines += [
        f"- anexo: {ae['n']}, ended past the model's `le`: "
        f"{ae['extended_past_model_le']}",
        "",
    ]
    if s.get("stress"):
        st = s["stress"]
        lines += [
            "## 2c. Stress set (re-flowed, true offsets = the reader's, carried over)",
            "",
            f"- devices matched {st['devices_matched_to_reader']}: A exact "
            f"{st['a_exact_rate']}, B exact {st['b_exact_rate']} "
            f"(of {st['b_resolved']} resolved), used offset "
            f"{st['used_offset_exact_rate']}",
        ]
        for name, c in st["by_true_column"].items():
            lines.append(
                f"  - column {name}: n={c['n']} A {c['a_exact_rate']} "
                f"B {c['b_exact_rate']} used {c['used_exact_rate']}"
                + (f" (used O {c['used_O']})" if c.get("used_O") else "")
            )
        lines += [
            f"- by non-ASCII before: {st['by_nonascii_before']}",
            f"- by occurrences of `t` in the line: {st['by_occurrences_in_line']}",
            "",
        ]
    lines += ["## 3. Coverage", ""]
    for k, v in s["coverage"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 4. Outcomes", ""]
    for k, v in o.items():
        lines.append(f"- {k}: {v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    run_dir: Path, out_dir: Path, label_cost: float = LABEL_MODE_USD_PER_NORM
) -> dict[str, Any]:
    anchors = run_dir / "anchors.jsonl"
    if not anchors.is_file():
        raise SystemExit(f"{anchors}: not a mark collect directory")
    summary_path = run_dir / "summary.json"
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else None
    )
    result = score_run(
        load_anchors(anchors),
        load_documents(run_dir),
        load_records(run_dir),
        summary,
        label_cost,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "score_mark.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    write_markdown(out_dir / "score_mark.md", result)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", type=Path, required=True, help="collect out dir")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label-cost", type=float, default=LABEL_MODE_USD_PER_NORM)
    args = parser.parse_args(argv)
    result = run(args.run, args.out, args.label_cost)
    ca = result["column_accuracy"]
    print(
        f"marks {ca['marks_answered']}, B exact reference {ca['reference_n']}, "
        f"A exact {ca['a_exact_rate']}; states {result['outcomes']['states']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
