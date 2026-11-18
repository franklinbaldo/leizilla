"""Turn a collected review run into errata candidates (offline, nothing is applied).

Review mode shows a model the READER's parse as tags and asks only for adjustments.
With a strong model (``claude-sonnet-5-5``) it is the adjudicator between the rule
reader and the mark-mode reference where they still disagree. Given a collected review
run (``teacher_batch collect --mode review``: ``reviews/*.json``), the mark reference
(``docs/okf/mark-reference/`` plus ``mark-reference-errata.json``) and the texts, this
script classifies every spot where the two disagree, and every adjustment the model
made:

- ``confirms_reference``: the adjustment turns the reader's reading into the
  reference's. The reader is wrong: a reader defect, listed by pattern
  (``patterns.tsv``) as a candidate for the next rule tournament;
- ``reference_error_candidate``: reader and reference differ and the model, answering
  completely and verified, made NO adjustment there: it agrees with the reader. The
  reference may be wrong: one proposed ``mark-reference-errata.json`` entry
  (``verified_by: "sonnet-review"``) that makes the reference equal the reader;
- ``third_opinion``: an adjustment that equals neither the reader nor the reference
  (including one where they agree): a human decides;
- ``inconclusive``: the silence cannot be read as agreement (``unverified``: a canary
  of the request was missed; ``partial``: parts missing; ``dropped``: an adjustment at
  that spot was discarded by the validator).

Outputs, under ``--out``: ``review_errata.tsv`` (one row per spot and per stray
adjustment), ``patterns.tsv`` (``confirms_reference`` by defect/level/marker shape/where),
``proposed-mark-reference-errata.json`` (same format as the reference errata; every entry
is checked by applying it to the reference rows: a stale one is dropped and reported) and
``summary.json``. A model's opinion is evidence, not a verdict: the proposed errata are
for a person to read against the text before they are merged, never for the gate to
swallow.

    uv run scripts/review_to_errata.py --reviews COLLECT_DIR --out OUT_DIR \\
        [--textos textos.parquet] [--date 2026-11-19]
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import compare_mark_reader as cmr
import compare_teacher_reader as ctr
import reader_ratchet_levels as rrl

LEVEL_SHORT = {
    "artigo": "art",
    "paragrafo": "par",
    "inciso": "inc",
    "alinea": "ali",
    "item": "item",
}
CONFIRMS = "confirms_reference"
REFERENCE_ERROR = "reference_error_candidate"
THIRD = "third_opinion"
INCONCLUSIVE = "inconclusive"
CATEGORIES = (CONFIRMS, REFERENCE_ERROR, THIRD, INCONCLUSIVE)
SKIP_VERDICTS = ("invalid", "truncated")
VERIFIED_BY = "sonnet-review"
SNIPPET = 24
TSV_COLUMNS = (
    "norm",
    "category",
    "defect",
    "level",
    "line",
    "reader",
    "reference",
    "adjustment",
    "model_reason",
    "pattern",
    "proposal",
    "note",
)


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------


def _roman_value(text: str) -> Optional[int]:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    s = text.upper()
    if not s or any(ch not in values for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = values[ch]
        total += -v if i + 1 < len(s) and values[s[i + 1]] > v else v
    return total


def canon(level: str, number: Any, sufixo: str = "") -> str:
    """One written form of a number per level: ``art`` ``5``/``5-A``; ``inc`` roman
    capitals; ``ali`` a lower-case letter; ``par`` ``unico`` or digits; ``item`` digits.
    Accepts both the reference's form (``inc`` arabic) and the model's (roman)."""
    n = "" if number is None else str(number).strip()
    if level == "art":
        return ctr.normalize_number(f"{n}-{sufixo}" if sufixo else n)
    if level == "inc":
        if n.isdigit():
            return cmr._roman(int(n))
        return n.upper()
    if level == "ali":
        if n.isdigit() and 1 <= int(n) <= 26:
            return chr(96 + int(n))
        return n.lower()
    if level == "par":
        folded = n.lower().replace("ú", "u")
        return "unico" if folded.startswith(("unico", "único")) else n
    return n


def _same_number(level: str, a: str, b: str) -> bool:
    if canon(level, a) == canon(level, b):
        return True
    if level == "inc":
        ra, rb = _roman_value(a), _roman_value(b)
        return ra is not None and ra == rb
    return False


# --------------------------------------------------------------------------
# One norm
# --------------------------------------------------------------------------


def printed_at(text: str, offset: int) -> str:
    """The marker as printed at ``offset``: the first two tokens, at most 16 chars."""
    head = text[offset : offset + 40].split("\n", 1)[0]
    match = re.match(r"\S+(?:\s+\S+)?", head)
    return (match.group(0) if match else head)[:16]


def where_of(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    return "mid-line" if text[line_start:offset].strip() else "line start"


def _dev_text(d: Optional[dict[str, Any]]) -> str:
    if d is None:
        return ""
    sfx = f"-{d['sufixo']}" if d.get("sufixo") and d["kind"] != "art" else ""
    return (
        f"{d['kind']} {canon(d['kind'], d['n'], d.get('sufixo') or '')}{sfx}"
        + (" Q" if d["quoted"] else "")
        + f" @{d['line']}"
    )


def _adj_text(adj: dict[str, Any]) -> str:
    parts = [str(adj["op"]), f"line {adj['line']}"]
    if adj.get("level"):
        parts.append(str(adj["level"]))
    if adj.get("number") is not None:
        parts.append(f"n={adj['number']}")
    if adj.get("quoted") is not None:
        parts.append(f"quoted={adj['quoted']}")
    return " ".join(parts)


def _adj_level(adj: dict[str, Any]) -> str:
    return (
        "art"
        if adj["op"].endswith("article")
        or adj["op"]
        in (
            "set_number",
            "set_quoted",
        )
        else LEVEL_SHORT.get(str(adj.get("level")), "")
    )


def _claim(d: dict[str, Any]) -> tuple[str, str, Optional[bool]]:
    return (d["kind"], canon(d["kind"], d["n"], d.get("sufixo") or ""), d["quoted"])


def _claims_equal(
    a: list[tuple[str, str, Optional[bool]]], b: list[tuple[str, str, Optional[bool]]]
) -> bool:
    """Same multiset of (kind, number); a ``None`` quoted status matches any."""
    left = list(b)
    for kind, number, quoted in a:
        hit = next(
            (
                x
                for x in left
                if x[0] == kind
                and _same_number(kind, x[1], number)
                and (quoted is None or x[2] is None or x[2] == quoted)
            ),
            None,
        )
        if hit is None:
            return False
        left.remove(hit)
    return not left


def _apply(
    reader: Optional[dict[str, Any]], adjs: list[dict[str, Any]]
) -> list[tuple[str, str, Optional[bool]]]:
    """The claims at one spot after the adjustments: what the model says is there."""
    claims: list[tuple[str, str, Optional[bool]]] = (
        [_claim(reader)] if reader is not None else []
    )
    for adj in adjs:
        op, level = adj["op"], _adj_level(adj)
        if op in ("add_own_article", "add_node"):
            quoted: Optional[bool] = False if op == "add_own_article" else adj["quoted"]
            claims.append((level, canon(level, adj["number"]), quoted))
        elif op in ("remove_article", "remove_node"):
            claims = [c for c in claims if c[0] != level]
        elif op in ("set_number", "set_node_number"):
            claims = [
                (c[0], canon(level, adj["number"]), c[2]) if c[0] == level else c
                for c in claims
            ]
        elif op == "set_quoted":
            claims = [
                (c[0], c[1], bool(adj["quoted"])) if c[0] == level else c
                for c in claims
            ]
    return claims


def _evidence_for(text: str, line: int, offset: int, unique_at: bool) -> Optional[str]:
    """A literal piece of ``line`` starting at ``offset``. With ``unique_at`` the
    piece must first occur in the line exactly there (``add_device`` takes the offset
    from the first occurrence); ``None`` when no such piece exists."""
    row = text.split("\n")[line - 1]
    col = offset - (text.rfind("\n", 0, offset) + 1)
    for size in (SNIPPET, 40, len(row) - col):
        piece = row[col : col + size].rstrip()
        if not piece:
            continue
        if not unique_at or row.index(piece) == col:
            return piece
    return None


def _entry(
    review: dict[str, Any],
    unit: dict[str, Any],
    op: str,
    dev: dict[str, Any],
    text: str,
    reason: str,
    date: str,
) -> Optional[dict[str, Any]]:
    evidence = _evidence_for(text, dev["line"], dev["offset"], op == "add_device")
    if evidence is None:
        return None
    out: dict[str, Any] = {
        "date": date,
        "evidence": evidence,
        "kind": dev["kind"],
        "line": dev["line"],
        "norm": review["texto_id"],
        "op": op,
        "reason": reason,
        "text_sha256": review["text_sha256"],
        "verified_by": VERIFIED_BY,
    }
    if op == "add_device":
        out["n"] = str(dev["n"])
        out["sufixo"] = dev.get("sufixo") or ""
        out["quoted"] = bool(dev["quoted"])
    else:
        out["n"] = str(dev["n"])
    return out


def proposals_for(
    review: dict[str, Any],
    unit: dict[str, Any],
    text: str,
    date: str,
    why: str,
) -> list[dict[str, Any]]:
    """The errata entries that make the reference equal the reader at this spot."""
    ref, rdr, defect = unit["ref"], unit["reader"], unit["defect"]
    out: list[dict[str, Any]] = []
    if defect == "reader_extra" and rdr is not None:
        e = _entry(review, unit, "add_device", rdr, text, why, date)
        out += [e] if e else []
    elif defect == "reader_misses" and ref is not None:
        e = _entry(review, unit, "remove_device", ref, text, why, date)
        out += [e] if e else []
    elif defect == "kind_differs" and ref is not None and rdr is not None:
        for op, dev in (("remove_device", ref), ("add_device", rdr)):
            e = _entry(review, unit, op, dev, text, why, date)
            out += [e] if e else []
    elif defect in ("number_differs", "status_differs") and ref and rdr:
        e = _entry(review, unit, "set_device", ref, text, why, date)
        if e is not None:
            new: dict[str, Any] = {}
            if (ref["n"], ref["sufixo"]) != (rdr["n"], rdr["sufixo"]):
                new["n"] = str(rdr["n"])
                new["sufixo"] = rdr["sufixo"]
            if ref["quoted"] != rdr["quoted"]:
                new["quoted"] = bool(rdr["quoted"])
            e["set"] = new
            out.append(e)
    return out


def classify_norm(
    review: dict[str, Any],
    text: str,
    ref_rows: list[list[Any]],
    reader_devs: list[dict[str, Any]],
    *,
    date: str,
) -> dict[str, Any]:
    """Classify one review record against the reference and the reader.

    ``ref_rows``: the reference rows ``[kind, n, sufixo, quoted, offset]`` (errata
    applied); ``reader_devs``: the reader's devices (``cmr.devices`` form).
    Returns ``{"rows": [...], "proposals": [...], "notes": [...]}``.
    """
    adjustments = list(review.get("adjustments") or [])
    verdict = review.get("verdict")
    unverified = bool(review.get("unverified"))
    partial = bool(review.get("partial")) or verdict == "partial"
    dropped_lines = {int(d["line"]) for d in review.get("dropped") or [] if "line" in d}
    ref_devs = rrl.devices_from_rows(ref_rows, text)
    pairs, m_only, r_only = cmr.pair_devices(ref_devs, reader_devs)
    outcomes = cmr.classify_pairs(pairs, m_only, r_only)
    units: list[dict[str, Any]] = []
    for o in outcomes:
        if not o["defects"]:
            continue
        for defect in o["defects"]:
            units.append(
                {"defect": defect, "ref": o["mark"], "reader": o["reader"], "adjs": []}
            )
    used: set[int] = set()

    def spots(u: dict[str, Any]) -> list[tuple[str, int]]:
        return [(d["kind"], d["line"]) for d in (u["ref"], u["reader"]) if d]

    for index, adj in enumerate(adjustments):
        level, line = _adj_level(adj), int(adj["line"])
        hits = [u for u in units if (level, line) in spots(u)]
        if len(hits) > 1 and adj.get("number") is not None:
            narrowed = [
                u
                for u in hits
                if any(
                    d
                    and d["kind"] == level
                    and _same_number(level, d["n"], adj["number"])
                    for d in (u["ref"], u["reader"])
                )
            ]
            hits = narrowed or hits
        for u in hits:
            u["adjs"].append(adj)
            used.add(index)

    rows: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    notes: list[str] = []
    for u in units:
        ref, rdr = u["ref"], u["reader"]
        anchor = rdr or ref
        level = anchor["kind"]
        printed = printed_at(text, (ref or rdr)["offset"])
        pattern = "|".join(
            [
                u["defect"],
                level,
                cmr.marker_shape(level, printed),
                where_of(text, (ref or rdr)["offset"]),
            ]
        )
        row = {
            "norm": review["texto_id"],
            "defect": u["defect"],
            "level": level,
            "line": anchor["line"],
            "reader": _dev_text(rdr),
            "reference": _dev_text(ref),
            "adjustment": "; ".join(_adj_text(a) for a in u["adjs"]),
            "model_reason": " / ".join(str(a.get("reason", "")) for a in u["adjs"])[
                :200
            ],
            "pattern": "",
            "proposal": "",
            "note": "",
        }
        if u["adjs"]:
            after = _apply(rdr, u["adjs"])
            target = [_claim(ref)] if ref is not None else []
            if _claims_equal(after, target):
                row["category"], row["pattern"] = CONFIRMS, pattern
            else:
                row["category"] = THIRD
                row["note"] = (
                    "the adjustment equals neither the reader nor the reference"
                )
        elif unverified or partial:
            row["category"] = INCONCLUSIVE
            row["note"] = "unverified" if unverified else "partial"
        elif any(ln in dropped_lines for _, ln in spots(u)):
            row["category"] = INCONCLUSIVE
            row["note"] = "dropped adjustment at this spot"
        else:
            row["category"] = REFERENCE_ERROR
            why = (
                "Sonnet review ({model}) left the reader's reading unchanged where it "
                "differs from the mark reference ({defect}: reader {rdr}; reference "
                "{ref}); the evidence line is the marker as printed.".format(
                    model=review.get("model", "?"),
                    defect=u["defect"],
                    rdr=_dev_text(rdr) or "none",
                    ref=_dev_text(ref) or "none",
                )
            )
            made = proposals_for(review, u, text, date, why)
            expected = 2 if u["defect"] == "kind_differs" else 1
            if len(made) != expected:
                row["note"] = "no unambiguous evidence for an errata entry"
            else:
                proposals += made
                row["proposal"] = f"{len(made)} entry"
        rows.append(row)
    for index, adj in enumerate(adjustments):
        if index in used:
            continue
        rows.append(
            {
                "norm": review["texto_id"],
                "category": THIRD,
                "defect": "contradicts_both",
                "level": _adj_level(adj),
                "line": int(adj["line"]),
                "reader": "",
                "reference": "",
                "adjustment": _adj_text(adj),
                "model_reason": str(adj.get("reason", ""))[:200],
                "pattern": "",
                "proposal": "",
                "note": "reader and reference agree here; the adjustment changes both",
            }
        )
    return {"rows": rows, "proposals": proposals, "notes": notes}


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def reader_article_set(devs: list[dict[str, Any]]) -> set[tuple[int, str, bool]]:
    return {
        (d["line"], canon("art", d["n"], d.get("sufixo") or ""), bool(d["quoted"]))
        for d in devs
        if d["kind"] == "art"
    }


def recorded_article_set(review: dict[str, Any]) -> set[tuple[int, str, bool]]:
    return {
        (int(a[0]), canon("art", a[1]), bool(a[2]))
        for a in review.get("reader", {}).get("articles", [])
    }


def run(
    reviews: list[dict[str, Any]],
    ref: rrl.Reference,
    errata: Optional[rrl.Errata],
    *,
    date: str,
    reader: Any = None,
) -> dict[str, Any]:
    """Classify every usable review; returns rows, proposals, patterns and counts."""
    reader = reader or rrl.reader_devices
    by_norm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for c in errata.corrections if errata else []:
        by_norm[str(c["norm"])].append(c)
    rows: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}
    counts: collections.Counter[str] = collections.Counter()
    for review in reviews:
        norm = str(review.get("texto_id"))
        if review.get("canary"):
            continue
        if review.get("verdict") in SKIP_VERDICTS:
            skipped[norm] = f"verdict {review.get('verdict')}"
            continue
        rec = ref.norms.get(norm)
        if rec is None:
            skipped[norm] = "not in the reference"
            continue
        if rec.get("flags"):
            skipped[norm] = "suspect flags in the reference (outside the gate)"
            continue
        sha = rec["text_sha256"]
        text = ref.texts.get(sha)
        if text is None or review.get("text_sha256") != sha:
            skipped[norm] = "text missing or differs from the reference's"
            continue
        ref_rows = rec["devices"]
        if by_norm.get(norm):
            ref_rows, _applied, _stale = rrl.apply_corrections(
                ref_rows, by_norm[norm], text, sha
            )
        devs = reader(text, rec.get("tipo"), rec.get("numero"))
        if reader_article_set(devs) != recorded_article_set(review):
            skipped[norm] = "the reader's articles differ from the ones the model saw"
            continue
        result = classify_norm(review, text, ref_rows, devs, date=date)
        # every proposal must apply cleanly to the reference rows
        ok_entries: list[dict[str, Any]] = []
        if result["proposals"]:
            _rows, applied, stale = rrl.apply_corrections(
                ref_rows, result["proposals"], text, sha
            )
            ok_entries = applied
            for s in stale:
                result["notes"].append(f"proposal dropped, stale: {s}")
        proposals += ok_entries
        rows += result["rows"]
        for r in result["rows"]:
            counts[r["category"]] += 1
    patterns: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["category"] == CONFIRMS:
            p = patterns.setdefault(r["pattern"], {"count": 0, "norms": set()})
            p["count"] += 1
            p["norms"].add(r["norm"])
    return {
        "rows": rows,
        "proposals": proposals,
        "patterns": patterns,
        "skipped": skipped,
        "counts": dict(counts),
    }


def write_outputs(out: Path, result: dict[str, Any], date: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(TSV_COLUMNS)]
    for r in sorted(
        result["rows"], key=lambda r: (r["category"], r["norm"], int(r["line"]))
    ):
        lines.append(
            "\t".join(str(r.get(c, "")).replace("\t", " ") for c in TSV_COLUMNS)
        )
    (out / "review_errata.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    plines = ["pattern\tcount\tnorms"]
    for pattern, p in sorted(
        result["patterns"].items(), key=lambda kv: (-kv[1]["count"], kv[0])
    ):
        plines.append(f"{pattern}\t{p['count']}\t{','.join(sorted(p['norms']))}")
    (out / "patterns.tsv").write_text("\n".join(plines) + "\n", encoding="utf-8")
    proposed = {
        "schema_version": rrl.SCHEMA_VERSION,
        "note": "PROPOSED by scripts/review_to_errata.py from a review run; not applied. "
        "Read each entry against the text before merging it into "
        "docs/okf/mark-reference-errata.json.",
        "generated": date,
        "corrections": sorted(
            result["proposals"], key=lambda c: (c["norm"], c["line"], c["op"])
        ),
    }
    (out / "proposed-mark-reference-errata.json").write_text(
        json.dumps(proposed, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "categories": result["counts"],
        "proposed_errata": len(result["proposals"]),
        "patterns": len(result["patterns"]),
        "skipped": result["skipped"],
        "reader_drift": result.get("reader_drift", {}),
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


READER_FILES = (
    "src/leizilla/article_sequence.py",
    "src/leizilla/hierarchy_sequence.py",
    "src/leizilla/marcacao.py",
    "src/leizilla/teacher_review.py",
)


def reader_drift(reviews: list[dict[str, Any]]) -> dict[str, Optional[bool]]:
    """``git_sha -> True`` when the reader's code changed between the commit the run
    used and the working tree (the sub-level tags the model saw are not stored in the
    review records, so they are re-derived with the CURRENT reader: a changed reader
    makes the sub-level classification unreliable); ``None`` when git cannot tell."""
    out: dict[str, Optional[bool]] = {}
    for sha in sorted({str(r["git_sha"]) for r in reviews if r.get("git_sha")}):
        try:
            done = subprocess.run(
                ["git", "diff", "--quiet", sha, "--", *READER_FILES],
                cwd=rrl.REPO_ROOT,
                capture_output=True,
                check=False,
            )
        except OSError:
            out[sha] = None
            continue
        out[sha] = None if done.returncode > 1 else done.returncode == 1
    return out


def load_reviews(root: Path) -> list[dict[str, Any]]:
    base = root / "reviews" if (root / "reviews").is_dir() else root
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(base.rglob("*.json"))
        if path.name not in ("summary.json", "manifest.json", "review-adjustments.json")
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reviews", type=Path, required=True, help="collect out dir")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--textos", type=Path, default=None)
    parser.add_argument("--reference", type=Path, default=rrl.DEFAULT_REFERENCE)
    parser.add_argument("--errata", type=Path, default=rrl.DEFAULT_ERRATA)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args(argv)

    ref = rrl.with_textos(rrl.load_reference(args.reference), args.textos)
    errata = rrl.load_errata(args.errata)
    reviews = load_reviews(args.reviews)
    result = run(reviews, ref, errata, date=args.date)
    result["reader_drift"] = reader_drift(reviews)
    write_outputs(args.out, result, args.date)
    if any(result["reader_drift"].values()):
        print(
            "WARNING: the reader changed since the run's commit "
            f"({result['reader_drift']}); sub-level results are not like-for-like. "
            "Check out the run's commit (the review records' git_sha) and run again."
        )
    print(f"reviews read: {len(reviews)}; skipped: {len(result['skipped'])}")
    for cat in CATEGORIES:
        print(f"  {cat}: {result['counts'].get(cat, 0)}")
    print(f"proposed errata entries: {len(result['proposals'])}")
    print(f"reader-defect patterns: {len(result['patterns'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
