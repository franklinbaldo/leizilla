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
    c_chars = sum(_json_field_chars("c", r.get("c")) for r in rows)
    t_chars = sum(_json_field_chars("t", r.get("t")) for r in rows)
    total = 0
    for r in rows:
        total += _json_field_chars("l", r.get("line"))
        total += _json_field_chars("k", r.get("kind"))
        total += _json_field_chars("c", r.get("c"))
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


def reader_markers(text: str) -> list[dict[str, Any]]:
    """The reader's device markers ``{line, kind, n, offset}`` of one text."""
    starts = [0]
    for i, ch in enumerate(text):
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


def reader_reference(
    rows: list[dict[str, Any]], docs: dict[str, tuple[str, str]]
) -> dict[str, Any]:
    """A and B against the reader's marker offset, for the devices (with a marker)
    the reader also found on the same line with the same kind."""
    by_norm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        by_norm[str(r.get("texto_id"))].append(r)
    n = a_ok = b_ok = b_n = used_ok = 0
    for texto_id, group in by_norm.items():
        if texto_id not in docs:
            continue
        found = reader_markers(docs[texto_id][1])
        for r in group:
            if r.get("kind") not in marcacao.DEVICES or r.get("a_off") is None:
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
            a_ok += r["a_off"] == ref
            if r.get("b_off") is not None:
                b_n += 1
                b_ok += r["b_off"] == ref
            used_ok += r.get("offset") == ref
    return {
        "devices_matched_to_reader": n,
        "a_exact": a_ok,
        "a_exact_rate": _rate(a_ok, n),
        "b_resolved": b_n,
        "b_exact": b_ok,
        "b_exact_rate": _rate(b_ok, b_n),
        "used_offset_exact": used_ok,
        "used_offset_exact_rate": _rate(used_ok, n),
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


def model_closes(rows: list[dict[str, Any]], text: str) -> bool:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    arts = [
        [
            bisect.bisect_right(starts, r["start"]),
            str(r["n"]) + (f"-{r['sufixo']}" if r.get("sufixo") else ""),
            bool(r["quoted"]),
        ]
        for r in rows
        if r["kind"] == "art"
    ]
    return bool(arts) and chain_intact(arts)


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
    marks = marcacao.from_hierarchy(
        text,
        read_hierarchy(text),
        tipo=record.get("tipo"),
        numero=record.get("numero"),
    )
    return marcacao.build(text, marks)


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
    for texto_id, (xml, text) in sorted(docs.items()):
        record = by_id.get(texto_id, {})
        m_rows = marcacao.to_rows(xml)
        r_xml = reader_document(text, record)
        r_rows = marcacao.to_rows(r_xml)
        for name, counts in agreement(m_rows, r_rows, text).items():
            bucket = agree.setdefault(name, collections.Counter())
            bucket.update(counts)
        m_close = model_closes(m_rows, text)
        r_close = article_closes(read_hierarchy(text))
        closure[
            f"model={'closes' if m_close else 'open'}/reader="
            f"{'closes' if r_close else 'open'}"
        ] += 1
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
        "reader_reference": reader_reference(rows, docs),
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
        f"- by non-ASCII before: {ca['by_nonascii_before']}",
        f"- by kind: {ca['by_kind']}",
        f"- 4-char check: {ca['check_4_chars']}",
        f"- 3-char check: {ca['check_3_chars']}",
        f"- B ambiguous: {ca['b_ambiguous']}",
        f"- token cost: {ca['token_cost']}",
        f"- against the reader's marker offsets: {rr}",
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
    lines += ["", f"Article closure: {s['article_closure']}", ""]
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
