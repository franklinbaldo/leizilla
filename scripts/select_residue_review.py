"""Select the norms for the Sonnet review of the reader/reference residue (offline).

Review mode shows the model the READER's parse as tags and asks only for adjustments;
with a stronger model it is the adjudicator between the rule reader and the mark-mode
reference (``docs/okf/mark-reference/``) where they still disagree. This script picks
the norms worth that spend, deterministically, from the reference and the live text
layer, scoring the reader at HEAD (``reader_ratchet_levels.run_board``):

1. ``flagged``: the norms carrying suspect flags in the reference (outside the gate);
2. ``named``: norms the owner and the last tournament report singled out;
3. a seeded sample of each residue class of the last tournament report, taking norms
   that still have non-agree units in that class at HEAD:
   ``inc_extra_own`` (own inciso extras, tables read as incisos), ``inc_extra_quoted``,
   ``inc_miss_bare`` (a bare roman numeral on its own line, missed), ``item_extra``,
   ``art_extra_quoted``, ``art_status`` (own/quoted status of articles differs),
   ``implicit_single`` (the reference has no own article: one-article decrees without
   an ``Art.`` marker), ``dup_copy`` (an own article number repeated: the same text
   copied twice in one file).

A norm is dropped when it needs more than ``--max-parts`` review parts, when its text
in the live layer is not the one the reference was made from (the review would show a
different text), or when the layer does not have it. The canary sources
(``--canaries``) are norms the reader reads in full agreement with the reference at
every level, closing, one part, able to carry a planted error, and not otherwise selected: a planted error in their
tags has one unambiguous reading.

    uv run scripts/select_residue_review.py --textos textos.parquet \\
        --out docs/okf/review-samples/residue-review-2026-11.txt \\
        --canaries docs/okf/review-samples/residue-review-2026-11-canaries.txt
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

import reader_ratchet_levels as rrl

from leizilla import teacher_batch as tb
from leizilla import teacher_review as tr

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = (
    REPO_ROOT / "docs" / "okf" / "review-samples" / "residue-review-2026-11.txt"
)
DEFAULT_CANARIES = (
    REPO_ROOT
    / "docs"
    / "okf"
    / "review-samples"
    / "residue-review-2026-11-canaries.txt"
)
SEED = "20261118"
MAX_PARTS = 6
PREFIX = "leizilla-raw-ro-casacivil-"
# Singled out by the owner / the tournament report: two Art. 49-A style chains, one
# law whose article 6 closes a short chain, whole-norm quoted-vs-own status, and files
# that carry the same text twice.
NAMED: tuple[str, ...] = (
    "lc-01174",
    "lei-01296",
    "lei-04989",
    "lei-00262",
    "lei-00432",
    "lei-00452",
    "lc-01211",
    "lei-00131",
    "decreto-01004",
)
QUOTAS: tuple[tuple[str, int], ...] = (
    ("inc_extra_own", 6),
    ("inc_extra_quoted", 6),
    ("inc_miss_bare", 5),
    ("item_extra", 4),
    ("art_extra_quoted", 4),
    ("art_status", 2),
    ("implicit_single", 4),
    ("dup_copy", 3),
)
CANARY_COUNT = 16
CANARY_LINES = (30, 250)
_BARE_ROMAN = re.compile(r"^\W*[IVXLCivxlc1l|!]+\W*$")


def full_id(short: str) -> str:
    return short if short.startswith("leizilla-raw-") else PREFIX + short


def seeded(seed: str, label: str, key: str) -> str:
    return hashlib.sha256(f"{seed}|{label}|{key}".encode("utf-8")).hexdigest()


def outcome_class(outcome: dict[str, Any], lines: list[str]) -> Optional[str]:
    """The residue class of one non-agree outcome, or ``None`` when it is in none."""
    level, status = outcome["level"], outcome["status"]
    for defect in outcome["defects"]:
        if level == "art" and defect == "status_differs":
            return "art_status"
        if level == "art" and defect == "reader_extra" and status == "quoted":
            return "art_extra_quoted"
        if level == "inc" and defect == "reader_extra":
            return f"inc_extra_{status}"
        if level == "inc" and defect == "reader_misses":
            line = int(outcome["mark"]["line"])
            if 1 <= line <= len(lines) and _BARE_ROMAN.match(lines[line - 1]):
                return "inc_miss_bare"
        if level == "item" and defect == "reader_extra":
            return "item_extra"
    return None


def norm_classes(
    outcomes: Iterable[dict[str, Any]], lines: list[str]
) -> dict[str, int]:
    """Count of outcomes per residue class, for one norm."""
    out: collections.Counter[str] = collections.Counter()
    for outcome in outcomes:
        if outcome["defects"]:
            cls = outcome_class(outcome, lines)
            if cls is not None:
                out[cls] += 1
    return dict(out)


def reference_classes(rec: dict[str, Any]) -> list[str]:
    """Classes that come from the reference rows alone (no reader needed)."""
    own = [d for d in rec["devices"] if d[0] == "art" and not d[3]]
    out: list[str] = []
    if not own:
        out.append("implicit_single")
    counts = collections.Counter((d[1], d[2]) for d in own)
    if any(v > 1 for v in counts.values()):
        out.append("dup_copy")
    return out


def review_parts(text: str) -> int:
    lines = tb.split_lines(text)
    return len(
        tb.chunk_document(
            lines,
            max_lines=tr.REVIEW_MAX_LINES,
            max_chars=tr.DEFAULT_REVIEW_MAX_CHARS,
            context_lines=tb.DEFAULT_CONTEXT_LINES,
            head_lines=tb.DEFAULT_HEAD_LINES,
        )
    )


def select(
    *,
    classes: dict[str, dict[str, int]],
    ref_classes: dict[str, list[str]],
    flagged: set[str],
    usable: dict[str, int],
    seed: str,
    named: Iterable[str] = NAMED,
    quotas: Iterable[tuple[str, int]] = QUOTAS,
    max_parts: int = MAX_PARTS,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """``(chosen, dropped)``: id -> reasons, id -> why a wanted norm was dropped.

    ``usable``: id -> review parts, for ids whose live text is the reference's.
    """
    chosen: dict[str, list[str]] = {}
    dropped: dict[str, str] = {}

    def add(i: str, reason: str) -> bool:
        if i not in usable:
            dropped[i] = "text missing or changed in the live layer"
            return False
        if usable[i] > max_parts:
            dropped[i] = f"{usable[i]} parts"
            return False
        chosen.setdefault(i, []).append(reason)
        return True

    for i in sorted(flagged):
        add(i, "flagged")
    for short in named:
        add(full_id(short), "named")
    for cls, quota in quotas:
        pool = [
            i
            for i in sorted(set(classes) | set(ref_classes))
            if i not in flagged
            and i not in chosen
            and i in usable
            and usable[i] <= max_parts
            and (cls in classes.get(i, {}) or cls in ref_classes.get(i, []))
        ]
        pool.sort(key=lambda i: seeded(seed, cls, i))
        for i in pool[:quota]:
            add(i, cls)
    # a norm already chosen also records the classes it carries (for the table)
    for i in chosen:
        for cls in classes.get(i, {}):
            if cls not in chosen[i]:
                chosen[i].append("also:" + cls)
        for cls in ref_classes.get(i, []):
            if cls not in chosen[i]:
                chosen[i].append("also:" + cls)
    return chosen, dropped


def canary_sources(
    *,
    agree_all: set[str],
    closing: dict[str, int],
    exclude: set[str],
    seed: str,
    count: int = CANARY_COUNT,
) -> list[str]:
    """``count`` norms that agree everywhere and close, seeded, not in ``exclude``;
    ``closing``: id -> non-blank lines, for single-part closing norms that admit at
    least one planted error."""
    lo, hi = CANARY_LINES
    pool = [
        i
        for i in sorted(agree_all)
        if i in closing and i not in exclude and lo <= closing[i] <= hi
    ]
    pool.sort(key=lambda i: seeded(seed, "canary", i))
    return sorted(pool[:count])


def write_ids(path: Path, header: list[str], ids: list[str]) -> None:
    path.write_text(
        "\n".join([*(f"# {h}" for h in header), *sorted(ids)]) + "\n", encoding="utf-8"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--textos", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=rrl.DEFAULT_REFERENCE)
    parser.add_argument("--errata", type=Path, default=rrl.DEFAULT_ERRATA)
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--max-parts", type=int, default=MAX_PARTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--canaries", type=Path, default=DEFAULT_CANARIES)
    parser.add_argument("--table", type=Path, default=None, help="TSV of the choice")
    args = parser.parse_args(argv)

    ref = rrl.load_reference(args.reference)
    ref = rrl.with_textos(ref, args.textos)
    errata = rrl.load_errata(args.errata)
    board = rrl.run_board(ref, errata)
    corpus = tb.load_textos(args.textos)
    layer = {str(r.texto_id): r for r in corpus.records if r.texto_id}

    classes: dict[str, dict[str, int]] = {}
    agree_all: set[str] = set()
    for texto_id, outcomes in board.reader_outcomes.items():
        text = ref.texts[ref.norms[texto_id]["text_sha256"]]
        found = norm_classes(outcomes, text.split("\n"))
        if found:
            classes[texto_id] = found
        if not any(o["defects"] for o in outcomes):
            agree_all.add(texto_id)
    by_norm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for c in errata.corrections if errata else []:
        by_norm[str(c["norm"])].append(c)
    ref_classes: dict[str, list[str]] = {}
    for i, rec in ref.norms.items():
        rows = rec["devices"]
        applied: list[dict[str, Any]] = []
        if by_norm.get(i) and ref.texts.get(rec["text_sha256"]) is not None:
            rows, applied, _stale = rrl.apply_corrections(
                rows,
                by_norm[i],
                ref.texts[rec["text_sha256"]],
                rec["text_sha256"],
                rec.get("flags", []),
            )
        if rrl.open_flags(rec, applied):
            continue
        found = [
            c
            for c in reference_classes({"devices": rows})
            # dup_copy only counts when the reader still disagrees somewhere
            if c != "dup_copy" or i in classes or i in NAMED_FULL
        ]
        if found:
            ref_classes[i] = found
    flagged = set(board.flagged)

    usable: dict[str, int] = {}
    closing: dict[str, int] = {}
    for i, rec in ref.norms.items():
        layer_rec = layer.get(i)
        if layer_rec is None or layer_rec.text_sha256 != rec["text_sha256"]:
            continue
        parts = review_parts(layer_rec.text)
        usable[i] = parts
        if parts == 1 and i in agree_all:
            view = tr.build_view(layer_rec.text)
            if view.closes and tr.feasible_kinds(view, tb.split_lines(layer_rec.text)):
                closing[i] = sum(1 for ln in layer_rec.text.split("\n") if ln.strip())
    chosen, dropped = select(
        classes=classes,
        ref_classes=ref_classes,
        flagged=flagged,
        usable=usable,
        seed=args.seed,
        max_parts=args.max_parts,
    )
    canaries = canary_sources(
        agree_all=agree_all, closing=closing, exclude=set(chosen), seed=args.seed
    )
    by_reason: collections.Counter[str] = collections.Counter()
    for reasons in chosen.values():
        for r in reasons:
            if not r.startswith("also:"):
                by_reason[r] += 1
    header = [
        "residue-review-2026-11",
        "Norms for a Sonnet review (review mode) of the reader/reference residue, built "
        "by scripts/select_residue_review.py",
        f"from {args.textos.name} and docs/okf/mark-reference/ (reader at HEAD), seed "
        f"{args.seed}, at most {args.max_parts} review parts per norm.",
        f"{len(chosen)} norms; by reason {dict(sorted(by_reason.items()))}.",
        f"Dropped when wanted: {dict(sorted(dropped.items())) or 'none'}.",
    ]
    write_ids(args.out, header, list(chosen))
    write_ids(
        args.canaries,
        [
            "residue-review-2026-11-canaries",
            "Canary sources for residue-review-2026-11: norms the reader reads in full "
            "agreement with the reference at every level,",
            f"closing, one review part with a feasible canary kind, {CANARY_LINES[0]}-{CANARY_LINES[1]} non-blank "
            f"lines, none of them in the review set; seed {args.seed}.",
            f"{len(canaries)} norms.",
        ],
        canaries,
    )
    if args.table is not None:
        rows = ["id\tparts\treasons\tclasses"]
        for i in sorted(chosen):
            rows.append(
                f"{i}\t{usable[i]}\t{','.join(chosen[i])}\t"
                f"{json.dumps(classes.get(i, {}), sort_keys=True)}"
            )
        args.table.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(header[3])
    print(header[4])
    print(f"canary sources: {len(canaries)}")
    return 0


NAMED_FULL: frozenset[str] = frozenset(full_id(s) for s in NAMED)

if __name__ == "__main__":
    sys.exit(main())
