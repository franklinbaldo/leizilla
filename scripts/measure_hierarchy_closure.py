"""Measure how much of a corpus the sequence-aware hierarchy reader closes.

Runs `leizilla.hierarchy_sequence.read_hierarchy` over a directory of OCR texts and
prints, with no model involved:

- closure per level (articles / paragraphs / incisos / alíneas) and overall, against two
  baselines for the article level (the naive regex of `segmenter.validate_structure`
  and the article-only `article_sequence.read_articles`);
- the same table per tipo, when a metadata file maps texts to tipos; the last column
  also asks for a vigência/revogação clause at the end, which catches texts cut short;
- how each marker was read (literal, known OCR confusion, single-gap fill) and the
  caveats on the closed set (weak candidates ignored, no final clause);
- the residual taxonomy: why norms stay open, and the most frequent unexplained marker
  shapes;
- how many closures lean on a quoted block that was opened without a quotation mark or
  never closed (the least certain part of the reading).

It also writes one JSON line per unexplained candidate, with context: the work queue
for the decision models of the `boundary-decision-parser` front.

    uv run scripts/measure_hierarchy_closure.py CORPUS_DIR \\
        --metadata CORPUS_DIR/results.json --out /tmp/unexplained.jsonl
    uv run scripts/measure_hierarchy_closure.py --gold data/opf/gold

Text files are matched as ``txt_{item}_{uuid5}.txt`` when metadata is given, else every
``*.txt`` in the directory is read. The corpus is only read, never copied.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from leizilla.article_sequence import read_articles
from leizilla.hierarchy_sequence import HierarchyReport, marker_spans, read_hierarchy
from leizilla.segmenter import (
    Span,
    evaluate_against_gold,
    format_report,
    validate_structure,
)

LEVELS = ("artigo", "paragrafo", "inciso", "alinea")
MARKER_CATEGORIES = {"art_marcador", "par_marcador", "inc_marcador", "ali_marcador"}
_NAIVE_OPEN = {"no_articles", "missing_articles", "out_of_order"}


def _load(corpus: Path, metadata: Path | None) -> list[tuple[str, str, Path]]:
    """Return (doc id, tipo, path) for every text available."""
    if metadata is None:
        return [(p.stem, "-", p) for p in sorted(corpus.glob("*.txt"))]
    docs: list[tuple[str, str, Path]] = []
    for row in json.loads(metadata.read_text(encoding="utf-8")):
        path = corpus / f"txt_{row['item']}_{row['uuid5']}.txt"
        if path.exists():
            doc_id = f"{row.get('tipo', '-')}-{row.get('numero', '?')}/{row['uuid5']}"
            docs.append((doc_id, str(row.get("tipo", "-")), path))
    return docs


def _shape(raw: str) -> str:
    """Collapse a marker to its shape so look-alikes group together."""
    return re.sub(r"\s+", " ", re.sub(r"\d", "9", raw)).strip()


def _context(text: str, start: int, end: int, pad: int = 80) -> dict[str, str]:
    return {
        "left": text[max(0, start - pad) : start],
        "marker": text[start:end],
        "right": text[end : end + pad],
    }


def _why_open(report: HierarchyReport, kind: str) -> str:
    level = report["levels"][kind]
    if level["closes"]:
        return "closed"
    if kind == "artigo" and level["nodes"] == 0:
        return "no_article_read"
    if kind == "artigo" and report["open_tail_block"]:
        return "unclosed_quote_to_the_end"
    if kind != "artigo" and report["levels"]["artigo"]["nodes"] == 0:
        return "no_article_read"
    conflict = any(s["conflict"] for s in report["scopes"] if s["kind"] == kind)
    if level["missing"] and level["unexplained"]:
        return "missing_and_unexplained"
    if level["unexplained"]:
        return "unexplained_only"
    if level["missing"]:
        return "missing_only"
    return "unico_with_numbered" if conflict else "other"


def _table(title: str, rows: dict[str, Counter[str]], columns: list[str]) -> None:
    print(f"\n{title}")
    print(f"{'':12s} {'n':>5s} " + " ".join(f"{c:>18s}" for c in columns))
    for name, row in rows.items():
        n = row["n"]
        cells = " ".join(
            f"{row[c]:>6d} ({100 * row[c] / n:5.1f}%)    " if n else f"{'-':>18s}"
            for c in columns
        )
        print(f"{name:12s} {n:>5d} {cells}")


def _gold(gold_dir: Path) -> int:
    """Score the reader's own markers against the committed gold, next to the regex."""
    docs: list[tuple[str, list[Span]]] = []
    for split in ("train", "val", "test"):
        path = gold_dir / f"{split}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                keep = [s for s in rec["label"] if s["category"] in MARKER_CATEGORIES]
                docs.append((rec["text"], keep))
    if not docs:
        print(f"no gold found under {gold_dir}", file=sys.stderr)
        return 1

    def regex_markers(text: str) -> list[Span]:
        from leizilla.segmenter import segment

        return [s for s in segment(text) if s["category"] in MARKER_CATEGORIES]

    print(f"Gold: {len(docs)} docs, marker categories only\n")
    print("regex baseline (segmenter.segment)")
    print(format_report(evaluate_against_gold(docs, regex_markers)))
    print("\nsequence-aware hierarchy reader (own nodes only)")
    print(format_report(evaluate_against_gold(docs, marker_spans)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("corpus", type=Path, nargs="?", help="directory of OCR texts")
    parser.add_argument("--gold", type=Path, help="score against a gold dir instead")
    parser.add_argument("--metadata", type=Path, help="results.json (item/tipo/uuid5)")
    parser.add_argument("--out", type=Path, help="JSONL of unexplained candidates")
    parser.add_argument("--limit", type=int, default=0, help="read at most N texts")
    parser.add_argument("--top", type=int, default=25, help="residual shapes to print")
    args = parser.parse_args()
    if args.gold:
        return _gold(args.gold)
    if args.corpus is None:
        parser.error("give a corpus directory or --gold")

    docs = _load(args.corpus, args.metadata)
    if args.limit:
        docs = docs[: args.limit]
    if not docs:
        print("no texts found", file=sys.stderr)
        return 1

    columns = ["naive_art", "seq_art", *LEVELS, "all_levels", "all+clause"]
    overall: dict[str, Counter[str]] = {"TOTAL": Counter()}
    why: dict[str, Counter[str]] = {k: Counter() for k in LEVELS}
    shapes: dict[str, Counter[str]] = {k: Counter() for k in (*LEVELS, "item")}
    leftovers: Counter[str] = Counter()
    nodes: Counter[str] = Counter()
    corrected: Counter[str] = Counter()
    present: Counter[str] = Counter()
    present_closed: Counter[str] = Counter()
    quoted = Counter[str]()
    read_by: Counter[str] = Counter()
    hints: Counter[str] = Counter()
    caveats: Counter[str] = Counter()
    queue: list[dict[str, object]] = []
    slowest = (0.0, "")
    started = time.perf_counter()

    for doc_id, tipo, path in docs:
        text = path.read_text(encoding="utf-8", errors="replace")
        t0 = time.perf_counter()
        report = read_hierarchy(text)
        slowest = max(slowest, (time.perf_counter() - t0, f"{doc_id} ({len(text)}c)"))
        naive = not any(f["kind"] in _NAIVE_OPEN for f in validate_structure(text))
        seq = read_articles(text)["closes"]

        for row in (overall["TOTAL"], overall.setdefault(tipo, Counter())):
            row["n"] += 1
            row["naive_art"] += naive
            row["seq_art"] += seq
            row["all_levels"] += report["closes"]
            row["all+clause"] += report["closes"] and report["final_clause"]
            for kind in LEVELS:
                row[kind] += report["levels"][kind]["closes"]
        for kind in LEVELS:
            level = report["levels"][kind]
            why[kind][_why_open(report, kind)] += 1
            nodes[kind] += level["nodes"]
            corrected[kind] += level["corrected"]
            if level["nodes"]:
                present[kind] += 1
                present_closed[kind] += level["closes"]
        nodes["item"] += report["levels"]["item"]["nodes"]
        nodes["quoted"] += sum(1 for n in report["nodes"] if n["status"] == "quoted")

        for node in report["nodes"]:
            if node["status"] == "own":
                where = "closed" if report["closes"] else "open"
                read_by[f"{node['kind']}:{node['read_by']}:{where}"] += 1
        caveats["open_tail_block"] += report["open_tail_block"]
        if report["closes"]:
            caveats["closed"] += 1
            caveats["closed_without_final_clause"] += not report["final_clause"]
            ignored = {
                left["kind"]
                for left in report["leftovers"]
                if left["status"] == "ignored" and left["kind"] != "item"
            }
            caveats["closed_with_ignored_candidates"] += bool(ignored)
            for kind in ignored:
                caveats[f"closed_with_ignored_{kind}"] += 1
            sub = sum(report["levels"][k]["nodes"] for k in LEVELS[1:])
            caveats["closed_with_no_sublevel"] += sub == 0

        blocks = report["quoted_blocks"]
        if blocks:
            quoted["norms_with_blocks"] += 1
            quoted["blocks"] += len(blocks)
            quoted["blocks_cue_only"] += sum(b["opened_by"] == "cue" for b in blocks)
            quoted["blocks_unclosed"] += sum(not b["closed"] for b in blocks)
            if report["closes"]:
                quoted["closed_norms_with_blocks"] += 1
                if any(b["opened_by"] == "cue" or not b["closed"] for b in blocks):
                    quoted["closed_norms_leaning_on_uncertain_block"] += 1

        for left in report["leftovers"]:
            leftovers[f"{left['kind']}:{left['status']}"] += 1
            if left["status"] != "unexplained":
                continue
            shapes[left["kind"]][_shape(left["raw"])] += 1
            hints[f"{left['kind']}:{left['hint']}"] += 1
            scope = left["scope"]
            queue.append(
                {
                    "doc": doc_id,
                    "tipo": tipo,
                    "file": path.name,
                    "kind": left["kind"],
                    "hint": left["hint"],
                    "start": left["start"],
                    "end": left["end"],
                    "scope_path": report["nodes"][scope]["path"]
                    if scope is not None
                    else None,
                    **_context(text, left["start"], left["end"]),
                }
            )

    elapsed = time.perf_counter() - started
    print(
        f"{len(docs)} texts read in {elapsed:.1f}s; slowest {slowest[1]}: "
        f"{slowest[0]:.2f}s"
    )
    _table(
        "Closure (norms whose level closes: full chain in every scope, nothing "
        "unexplained)",
        overall,
        columns,
    )
    print("\nNorms that actually have the level, and how many of those close it")
    for kind in LEVELS:
        n = present[kind]
        share = f"{100 * present_closed[kind] / n:.1f}%" if n else "-"
        print(
            f"  {kind:10s} present in {n:5d} norms, closed in "
            f"{present_closed[kind]:5d} ({share}); {nodes[kind]} nodes, "
            f"{corrected[kind]} readings corrected by sequence"
        )
    print(
        f"  itens read: {nodes['item']}; nodes inside quoted blocks: {nodes['quoted']}"
    )
    print("\nHow own markers were read (closed norms / open norms)")
    for kind in (*LEVELS, "item"):
        parts = []
        for how in ("literal", "confusion", "gap"):
            closed_n = read_by[f"{kind}:{how}:closed"]
            open_n = read_by[f"{kind}:{how}:open"]
            parts.append(f"{how}={closed_n}/{open_n}")
        print(f"  {kind:10s} " + ", ".join(parts))
    print("\nCaveats on the closed set (norms)")
    for key, count in sorted(caveats.items()):
        print(f"  {key:42s} {count}")
    print("\nWhy a level stays open (norms)")
    for kind in LEVELS:
        reasons = ", ".join(f"{k}={v}" for k, v in why[kind].most_common())
        print(f"  {kind:10s} {reasons}")
    print("\nLeftover candidates by kind:status")
    for key, count in sorted(leftovers.items()):
        print(f"  {key:24s} {count}")
    print("\nUnexplained candidates against the chain of their scope (kind:hint)")
    for key, count in sorted(hints.items()):
        print(f"  {key:24s} {count}")
    print("\nQuoted blocks (amending laws)")
    for key, count in sorted(quoted.items()):
        print(f"  {key:42s} {count}")
    print(f"\nTop unexplained marker shapes (digits shown as 9), top {args.top}")
    for kind in (*LEVELS, "item"):
        if shapes[kind]:
            top = ", ".join(f"{s!r}×{c}" for s, c in shapes[kind].most_common(args.top))
            print(f"  {kind:10s} {top}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for entry in queue:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"\n{len(queue)} unexplained candidates written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
