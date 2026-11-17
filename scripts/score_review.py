"""Score a teacher-batch REVIEW run against the main teacher labels (offline).

``leizilla.teacher_batch collect`` in review mode writes ``reviews/`` (one JSON
per norm: the reader's reading, the model's verdict and its validated
adjustments) and ``summary.json``. This script compares them with the teacher's
own article labels (errata applied, exactly as ``compare_teacher_reader.py``
does), so that the reviewer is measured on norms whose answer is known:

1. norms where the reader disagrees with the teacher: did the reviewer say
   ``ajuste``? does reader + adjustments equal the teacher (``fully_fixed``),
   come closer (``partly_fixed``), change nothing (``no_change``) or move away
   (``wrong_direction``)?
2. norms where the reader agrees with the teacher (``agree_closed`` first): the
   false-alarm rate, and the list of those norms, since some will be real errors
   that reader and teacher both missed (they need a human reading, never an
   automatic "the reviewer was wrong");
3. canary recall by kind, from the planted errors;
4. cost per norm against the label mode's measured US$0.00063 per norm.

Only norms whose review text sha256 equals the label's are scored. Norms whose
result was INVALID, and ``ok`` verdicts of requests whose canary was missed
(``unverified``), are reported apart and never silently counted as agreement.

    uv run scripts/score_review.py --reviews COLLECT_DIR --labels LABELS_DIR \\
        --texts TEXTS_DIR [--textos-parquet PATH] --out OUT_DIR \\
        [--errata PATH | --no-errata] [--label-cost 0.00063]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any, Optional

# ``scripts/`` is on sys.path when this file runs as a script; tests add it too.
import compare_teacher_reader as cmp

from leizilla.teacher_review import CANARY_KINDS, apply_adjustments

# Measured by the label mode on the 2086-norm main run (batch
# msgbatch_01VYBeV9AWA7A2QeNaYfJZAC).
LABEL_MODE_USD_PER_NORM = 0.00063

AGREE_GROUPS: tuple[str, ...] = ("agree_closed", "agree_open")
DISAGREE_OUTCOMES: tuple[str, ...] = (
    "fully_fixed",
    "partly_fixed",
    "no_change",
    "wrong_direction",
    "missed",
    "invalid",
    "truncated",
)
# Outcomes with no usable answer: never counted as agreement or as a fix.
UNUSABLE_OUTCOMES: tuple[str, ...] = ("invalid", "truncated")
CANARY_OUTCOMES: tuple[str, ...] = (
    "caught",
    "partly",
    "missed",
    "invalid",
    "truncated",
)


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


def load_reviews(root: Path) -> list[dict[str, Any]]:
    """Every review JSON under ``root/reviews`` (or ``root`` itself)."""
    base = root / "reviews" if (root / "reviews").is_dir() else root
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(base.rglob("*.json"))
        if path.name not in ("summary.json", "manifest.json")
    ]


def _text_for(
    header: dict[str, Any], texts_dir: Path, parquet: "cmp.ParquetTexts"
) -> Optional[str]:
    """The text the teacher saw: cache, then the published parquet. No network."""
    path = cmp._cache_file(texts_dir, header)
    if path.is_file():
        return path.read_bytes().decode("utf-8")
    sha = str(header["text_sha256"])
    text = parquet.get(sha)
    if text is not None and cmp.sha256_text(text) == sha:
        return text
    return None


def teacher_sets(
    labels_dir: Path,
    texts_dir: Path,
    textos_parquet: Optional[Path],
    errata: Optional["cmp.Errata"],
    wanted: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """``(item, uuid5)`` -> the teacher's own article set (errata applied), its
    text sha256 and whether its own numbers read 1..N, for the wanted norms."""
    parquet = cmp.ParquetTexts(textos_parquet)
    by_norm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    if errata is not None:
        for correction in errata.corrections:
            by_norm[str(correction["norm"])].append(correction)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for header, labels in cmp.load_labelled_norms(labels_dir):
        ident = (str(header["item"]), str(header["uuid5"]))
        if ident not in wanted:
            continue
        text = _text_for(header, texts_dir, parquet)
        if text is None or cmp.sha256_text(text) != header["text_sha256"]:
            out[ident] = {"text_sha256": str(header["text_sha256"]), "own": None}
            continue
        corrections = by_norm.get(cmp.norm_id(header), [])
        if corrections:
            labels, _applied, _stale = cmp.apply_corrections(labels, corrections, text)
        own: set[cmp.ArticleKey] = set()
        for label in labels:
            if label.get("category") == "artigo" and not label.get("quoted"):
                own.add((int(label["line"]), cmp.normalize_number(label.get("number"))))
        out[ident] = {
            "text_sha256": str(header["text_sha256"]),
            "own": own,
            "consistent": cmp.teacher_numbers_consistent(own),
        }
    return out


# --------------------------------------------------------------------------
# Scoring (pure)
# --------------------------------------------------------------------------


def _own_set(articles: list[Any]) -> set[cmp.ArticleKey]:
    return {
        (int(line), cmp.normalize_number(number))
        for line, number, quoted in articles
        if not quoted
    }


def score_norm(review: dict[str, Any], teacher: dict[str, Any]) -> dict[str, Any]:
    """Group, outcome and distances of one non-canary review against the teacher."""
    reader = review["reader"]
    r_own = _own_set(reader["articles"])
    t_own: set[cmp.ArticleKey] = teacher["own"]
    group = cmp.classify(t_own, r_own, bool(reader["closes"]), teacher["consistent"])
    after = _own_set(
        [list(a) for a in apply_adjustments(reader["articles"], review["adjustments"])]
    )
    before_gap = len(r_own ^ t_own)
    after_gap = len(after ^ t_own)
    verdict = review["verdict"]
    agrees = group in AGREE_GROUPS
    if verdict in UNUSABLE_OUTCOMES:
        outcome = verdict
    elif review.get("partial"):
        # Some parts of a chunked norm are missing: its own bucket, not scored.
        outcome = "partial"
    elif agrees:
        if verdict == "ok":
            outcome = "true_ok"
        else:
            outcome = "false_alarm" if after != t_own else "alarm_article_set_intact"
    elif verdict == "ok":
        outcome = "missed"
    elif after == t_own:
        outcome = "fully_fixed"
    elif after_gap < before_gap:
        outcome = "partly_fixed"
    elif after_gap == before_gap:
        outcome = "no_change"
    else:
        outcome = "wrong_direction"
    return {
        "key": review["key"],
        "texto_id": review["texto_id"],
        "group": group,
        "verdict": verdict,
        "outcome": outcome,
        "unverified": bool(review.get("unverified")),
        "partial": bool(review.get("partial")),
        "reader_gap": before_gap,
        "gap_after_adjustments": after_gap,
        "adjustments": review["adjustments"],
    }


def _recall_row(counts: dict[str, int]) -> dict[str, Any]:
    n = sum(counts.values())
    return {
        "n": n,
        **{k: counts.get(k, 0) for k in CANARY_OUTCOMES},
        "recall": round(counts.get("caught", 0) / n, 4) if n else None,
    }


def canary_table(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Recall by planted kind, and split by whether the mutated own-article chain is
    still gap-free (``chain_intact``: a reviewer can see a gap by reading) or broken.
    """
    kinds: dict[str, dict[str, int]] = {k: {} for k in CANARY_KINDS}
    chains: dict[str, dict[str, int]] = {"intact": {}, "broken": {}}
    for review in reviews:
        if not review.get("canary"):
            continue
        kind = review["canary_plan"]["kind"]
        name = str(review["canary_outcome"])
        kinds.setdefault(kind, {})
        kinds[kind][name] = kinds[kind].get(name, 0) + 1
        intact = review.get("canary_chain_intact")
        if intact is not None:
            bucket = chains["intact" if intact else "broken"]
            bucket[name] = bucket.get(name, 0) + 1
    table: dict[str, Any] = {}
    total: dict[str, int] = {}
    for kind, counts in kinds.items():
        table[kind] = _recall_row(counts)
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
    table["all"] = _recall_row(total)
    table["chain_intact"] = _recall_row(chains["intact"])
    table["chain_broken"] = _recall_row(chains["broken"])
    return table


def score(
    reviews: list[dict[str, Any]],
    teachers: dict[tuple[str, str], dict[str, Any]],
    summary: Optional[dict[str, Any]],
    label_cost: float = LABEL_MODE_USD_PER_NORM,
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    not_scored: dict[str, list[str]] = collections.defaultdict(list)
    for review in reviews:
        if review.get("canary"):
            continue
        ident = (str(review["item"]), str(review["uuid5"]))
        teacher = teachers.get(ident)
        if teacher is None:
            not_scored["not_labelled"].append(review["key"])
        elif teacher["own"] is None:
            not_scored["teacher_text_unavailable"].append(review["key"])
        elif teacher["text_sha256"] != review["text_sha256"]:
            not_scored["sha_differs_from_label"].append(review["key"])
        else:
            scored.append(score_norm(review, teacher))

    partial_rows = [r for r in scored if r["outcome"] == "partial"]
    scored_ok = [
        r for r in scored if r["outcome"] not in ("partial", *UNUSABLE_OUTCOMES)
    ]
    by_group: dict[str, dict[str, int]] = {}
    for row in scored:
        bucket = by_group.setdefault(row["group"], {})
        bucket[row["outcome"]] = bucket.get(row["outcome"], 0) + 1
        bucket["n"] = bucket.get("n", 0) + 1
        if row["unverified"]:
            bucket["unverified_ok"] = bucket.get("unverified_ok", 0) + 1

    disagree = [
        r
        for r in scored
        if r["group"] not in AGREE_GROUPS and r["outcome"] != "partial"
    ]
    d_counts = collections.Counter(r["outcome"] for r in disagree)
    d_valid = [r for r in disagree if r["outcome"] not in UNUSABLE_OUTCOMES]
    flagged = [r for r in d_valid if r["verdict"] == "ajuste"]

    def agree_report(group: str) -> dict[str, Any]:
        rows = [r for r in scored_ok if r["group"] == group]
        alarms = [r for r in rows if r["verdict"] == "ajuste"]
        return {
            "norms": len(rows),
            "ajuste": len(alarms),
            "false_alarm_rate": round(len(alarms) / len(rows), 4) if rows else None,
            "breaking_the_article_set": sum(
                1 for r in alarms if r["outcome"] == "false_alarm"
            ),
            "unverified_ok": sum(1 for r in rows if r["unverified"]),
            "alarms": [
                {
                    "key": r["key"],
                    "texto_id": r["texto_id"],
                    "outcome": r["outcome"],
                    "adjustments": [
                        {
                            "op": a["op"],
                            "line": a["line"],
                            "number": a.get("number"),
                            "reason": a["reason"],
                        }
                        for a in r["adjustments"]
                    ],
                }
                for r in alarms
            ],
        }

    measured = summary.get("measured_usd") if summary else None
    per_norm = summary.get("measured_usd_per_norm") if summary else None
    per_entry = summary.get("measured_usd_per_entry") if summary else None
    return {
        "reviews": len(reviews),
        "scored": len(scored),
        "not_scored": {k: len(v) for k, v in sorted(not_scored.items())},
        "not_scored_keys": {k: v[:20] for k, v in sorted(not_scored.items())},
        "by_group": {g: by_group[g] for g in sorted(by_group)},
        "reader_disagrees": {
            "norms": len(disagree),
            "invalid": d_counts.get("invalid", 0),
            "truncated": d_counts.get("truncated", 0),
            "said_ajuste": len(flagged),
            "said_ajuste_rate": (
                round(len(flagged) / len(d_valid), 4) if d_valid else None
            ),
            "outcomes": {k: d_counts.get(k, 0) for k in DISAGREE_OUTCOMES},
            "fully_fixed_rate": (
                round(d_counts.get("fully_fixed", 0) / len(d_valid), 4)
                if d_valid
                else None
            ),
            "unverified_ok": sum(
                1 for r in d_valid if r["verdict"] == "ok" and r["unverified"]
            ),
        },
        "partial": {
            "norms": len(partial_rows),
            "with_adjustments": sum(
                1 for r in partial_rows if r["verdict"] == "ajuste"
            ),
            "by_group": dict(collections.Counter(r["group"] for r in partial_rows)),
            "note": "chunked norms with some parts missing: not scored as agreement "
            "or disagreement",
        },
        "dropped": {
            "adjustments": sum(len(r.get("dropped") or []) for r in reviews),
            "downgraded_norms": sum(1 for r in reviews if r.get("downgraded")),
            "note": "adjustments that did not fit the reading (evidence, op, no-op): "
            "dropped with their reason, the rest of the norm still counts",
        },
        "reader_agrees": {g: agree_report(g) for g in AGREE_GROUPS},
        "canaries": canary_table(reviews),
        "cost": {
            "measured_usd": measured,
            "usd_per_norm": per_norm,
            "usd_per_entry": per_entry,
            "label_mode_usd_per_norm": label_cost,
            "ratio_to_label_mode": (
                round(per_norm / label_cost, 3) if per_norm and label_cost else None
            ),
            "note": "usd_per_norm divides the whole run (canaries included) by the "
            "real norms reviewed.",
        },
        "rows": scored,
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def _pct(value: Optional[float]) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def to_markdown(result: dict[str, Any]) -> str:
    lines = ["# Review run scored against the main teacher labels", ""]
    lines.append(
        f"{result['reviews']} reviews, {result['scored']} real norms scored; "
        f"not scored: {result['not_scored'] or 'none'}."
    )
    lines += ["", "## By scoreboard group", ""]
    lines.append("| group | norms | outcomes |")
    lines.append("|---|---|---|")
    for group, bucket in result["by_group"].items():
        outcomes = ", ".join(
            f"{k} {v}" for k, v in sorted(bucket.items()) if k not in ("n",)
        )
        lines.append(f"| {group} | {bucket['n']} | {outcomes} |")
    dis = result["reader_disagrees"]
    lines += ["", "## Reader disagrees with the teacher", ""]
    lines.append(
        f"{dis['norms']} norms ({dis['invalid']} invalid). The reviewer said "
        f"`ajuste` on {dis['said_ajuste']} ({_pct(dis['said_ajuste_rate'])}); "
        f"fully fixed {_pct(dis['fully_fixed_rate'])}. "
        f"`ok` verdicts on unverified requests: {dis['unverified_ok']}."
    )
    lines += ["", "| outcome | norms |", "|---|---|"]
    for name, count in dis["outcomes"].items():
        lines.append(f"| {name} | {count} |")
    lines += ["", "## Reader agrees with the teacher: false alarms", ""]
    lines.append(
        "| group | norms | ajuste | rate | breaks article set | unverified ok |"
    )
    lines.append("|---|---|---|---|---|---|")
    for group, rep in result["reader_agrees"].items():
        lines.append(
            f"| {group} | {rep['norms']} | {rep['ajuste']} | "
            f"{_pct(rep['false_alarm_rate'])} | {rep['breaking_the_article_set']} | "
            f"{rep['unverified_ok']} |"
        )
    alarms = result["reader_agrees"]["agree_closed"]["alarms"]
    if alarms:
        lines += [
            "",
            "Alarms on `agree_closed` norms (read each one: reader and teacher may "
            "both have missed a real error):",
            "",
        ]
        for alarm in alarms:
            ops = "; ".join(
                f"{a['op']} L{a['line']}"
                + (f" ={a['number']}" if a["number"] else "")
                + f" ({a['reason']})"
                for a in alarm["adjustments"]
            )
            lines.append(f"- `{alarm['key']}` [{alarm['outcome']}]: {ops}")
    lines += ["", "## Canary recall by planted kind", ""]
    lines.append(
        "| kind | n | caught | partly | missed | invalid | truncated | recall |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for kind, row in result["canaries"].items():
        if kind in ("chain_intact", "chain_broken"):
            continue
        lines.append(
            f"| {kind} | {row['n']} | {row['caught']} | {row['partly']} | "
            f"{row['missed']} | {row['invalid']} | {row['truncated']} | "
            f"{_pct(row['recall'])} |"
        )
    intact = result["canaries"]["chain_intact"]
    broken = result["canaries"]["chain_broken"]
    lines.append("")
    lines.append(
        f"Recall with the mutated own-article chain still gap-free (a reader sees no "
        f"gap): {_pct(intact['recall'])} of {intact['n']}; with a gap: "
        f"{_pct(broken['recall'])} of {broken['n']}."
    )
    dropped = result["dropped"]
    lines.append("")
    lines.append(
        f"Dropped adjustments (did not fit the reading): {dropped['adjustments']}; "
        f"norms downgraded from ajuste to ok: {dropped['downgraded_norms']}."
    )
    part = result["partial"]
    if part["norms"]:
        lines += [
            "",
            f"Partial chunked norms (some parts missing): {part['norms']}, of which "
            f"{part['with_adjustments']} carry adjustments from the valid parts.",
        ]
    cost = result["cost"]
    lines += ["", "## Cost", ""]
    lines.append(
        f"Measured US${cost['measured_usd']}; US${cost['usd_per_norm']} per real "
        f"norm (US${cost['usd_per_entry']} per entry, canaries included) against "
        f"US${cost['label_mode_usd_per_norm']} per norm in label mode "
        f"(ratio {cost['ratio_to_label_mode']})."
    )
    return "\n".join(lines) + "\n"


def run(
    reviews_root: Path,
    labels_dir: Path,
    texts_dir: Path,
    out_dir: Path,
    textos_parquet: Optional[Path] = None,
    errata: Optional["cmp.Errata"] = None,
    label_cost: float = LABEL_MODE_USD_PER_NORM,
) -> dict[str, Any]:
    reviews = load_reviews(reviews_root)
    summary_path = reviews_root / "summary.json"
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else None
    )
    wanted = {(str(r["item"]), str(r["uuid5"])) for r in reviews if not r.get("canary")}
    teachers = teacher_sets(labels_dir, texts_dir, textos_parquet, errata, wanted)
    result = score(reviews, teachers, summary, label_cost)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "score_review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "score_review.md").write_text(to_markdown(result), encoding="utf-8")
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reviews", type=Path, required=True, help="collect out dir")
    parser.add_argument("--labels", type=Path, required=True, help="main labels root")
    parser.add_argument("--texts", type=Path, required=True, help="texts cache dir")
    parser.add_argument("--out", type=Path, required=True, help="output dir")
    parser.add_argument("--textos-parquet", type=Path, default=None)
    parser.add_argument("--errata", type=Path, default=cmp.DEFAULT_ERRATA)
    parser.add_argument("--no-errata", action="store_true")
    parser.add_argument(
        "--label-cost", type=float, default=LABEL_MODE_USD_PER_NORM, help="US$/norm"
    )
    args = parser.parse_args(argv)
    try:
        errata = None if args.no_errata else cmp.load_errata(args.errata)
    except cmp.ErrataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = run(
        args.reviews,
        args.labels,
        args.texts,
        args.out,
        textos_parquet=args.textos_parquet,
        errata=errata,
        label_cost=args.label_cost,
    )
    print(
        json.dumps(
            {
                "scored": result["scored"],
                "not_scored": result["not_scored"],
                "reader_disagrees": result["reader_disagrees"],
                "false_alarm_agree_closed": result["reader_agrees"]["agree_closed"][
                    "false_alarm_rate"
                ],
                "canary_recall": result["canaries"]["all"]["recall"],
                "cost": result["cost"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
