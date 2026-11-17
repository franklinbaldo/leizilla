"""Select the mark-mode reference set (offline, deterministic).

Reads the label-mode teacher's labelled set and the current text layer
(``textos.parquet``), and writes a selection file (one ``texto_id`` per line, under
``docs/okf/review-samples/``) of ``--count`` norms that

- are in BOTH (the identity is ``(item, uuid5)``) and need at most ``--max-parts``
  parts under the mark mode chunking (150 lines / 14 000 characters);
- include every norm of ``--include`` (the pilot), whatever its features;
- are stratified by type (``lei``, ``lc``, ``decreto``, ``decreto-lei``) and by length
  tercile of the pool (non-blank lines), in proportion to the pool;
- contain at least ``--min-sub-disagree`` norms with sub-level devices (``par inc ali
  item``) on which the rule reader and the label-mode teacher disagree (own or quoted,
  by line and number), so the sub-level comparison has signal. Only norms whose text is
  the one the teacher saw can count (the teacher labels belong to that text);
- contain at least ``--min-quoted`` norms with quoted blocks (the reader finds one).

Order inside every stratum is ``sha256(seed|id)``; the same inputs give the same file.

    uv run scripts/select_mark_reference.py --labels LABELS_DIR --textos textos.parquet \\
        --include docs/okf/review-samples/mark-pilot-2026-11.txt \\
        --out docs/okf/review-samples/mark-reference-2026-11.txt
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import sys
from pathlib import Path
from typing import Any, Optional

import compare_mark_reader as cmr
import compare_teacher_reader as ctr

from leizilla import marcacao
from leizilla import teacher_batch as tb
from leizilla import teacher_mark as tm
from leizilla import teacher_review as tr
from leizilla.hierarchy_sequence import read_hierarchy

TIPOS: tuple[str, ...] = ("lei", "lc", "decreto", "decreto-lei")
TERCILES: tuple[str, ...] = ("short", "medium", "long")


def digest(seed: str, texto_id: str) -> str:
    return hashlib.sha256(f"{seed}|{texto_id}".encode("utf-8")).hexdigest()


def features(
    labels_dir: Path, textos: Path, max_parts: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One feature row per norm of (labelled set x text layer) that is eligible."""
    corpus = tb.load_textos(textos)
    teacher = {
        (h["item"], h["uuid5"]): (h, labs)
        for h, labs in ctr.load_labelled_norms(labels_dir)
    }
    dropped: collections.Counter[str] = collections.Counter()
    rows: list[dict[str, Any]] = []
    for rec in corpus.records:
        found = teacher.get((rec.ref.item, rec.ref.uuid5))
        if found is None:
            dropped["not labelled"] += 1
            continue
        header, labels = found
        lines = tb.split_lines(rec.text)
        if (
            len(
                tb.chunk_document(
                    lines, max_lines=tm.MARK_MAX_LINES, max_chars=tm.MARK_MAX_CHARS
                )
            )
            > max_parts
        ):
            dropped[f"more than {max_parts} parts"] += 1
            continue
        if not lines or not any(ln.strip() for ln in lines):
            dropped["empty"] += 1
            continue
        report = read_hierarchy(rec.text)
        valid = header["text_sha256"] == rec.text_sha256
        sub_disagree = False
        if valid:
            r_xml = marcacao.build(
                rec.text,
                marcacao.from_hierarchy(
                    rec.text, report, tipo=rec.ref.tipo, numero=rec.ref.numero
                ),
            )
            r_devs = cmr.devices(r_xml, rec.text)
            for level in cmr.SUB_LEVELS:
                for quoted in (False, True):
                    if cmr.teacher_set(labels, level, quoted) != cmr.device_set(
                        r_devs, level, quoted
                    ):
                        sub_disagree = True
        rows.append(
            {
                "id": str(rec.texto_id),
                "tipo": rec.ref.tipo,
                "nonblank": sum(1 for ln in lines if ln.strip()),
                "quoted": bool(report["quoted_blocks"]),
                "teacher_text": valid,
                "sub_disagree": sub_disagree,
            }
        )
    return rows, dict(dropped)


def assign_terciles(rows: list[dict[str, Any]]) -> None:
    order = sorted(rows, key=lambda r: (r["nonblank"], r["id"]))
    n = len(order)
    for i, r in enumerate(order):
        r["tercile"] = TERCILES[min(2, 3 * i // n)]


def select(
    rows: list[dict[str, Any]],
    *,
    count: int,
    seed: str,
    include: list[str],
    min_sub: int,
    min_quoted: int,
) -> list[dict[str, Any]]:
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in include if i not in by_id]
    if missing:
        raise SystemExit(
            f"{len(missing)} --include ids are not eligible (first {missing[:3]})"
        )
    cells = collections.Counter((r["tipo"], r["tercile"]) for r in rows)
    target = {c: count * n / len(rows) for c, n in cells.items()}
    chosen: dict[str, dict[str, Any]] = {i: by_id[i] for i in include}
    taken = collections.Counter((r["tipo"], r["tercile"]) for r in chosen.values())

    def pick(pred: Any) -> bool:
        """Add one norm satisfying ``pred`` from the cell most below its quota."""
        cands = [r for r in rows if r["id"] not in chosen and pred(r)]
        if not cands:
            return False
        best = min(
            cands,
            key=lambda r: (
                taken[(r["tipo"], r["tercile"])] - target[(r["tipo"], r["tercile"])],
                digest(seed, r["id"]),
            ),
        )
        chosen[best["id"]] = best
        taken[(best["tipo"], best["tercile"])] += 1
        return True

    for pred, minimum in (
        (lambda r: r["sub_disagree"], min_sub),
        (lambda r: r["quoted"], min_quoted),
    ):
        while sum(1 for r in chosen.values() if pred(r)) < minimum:
            if not pick(pred):
                raise SystemExit(
                    f"cannot reach {minimum} norms: only {len(chosen)} found"
                )
    while len(chosen) < count:
        if not pick(lambda r: True):
            raise SystemExit(f"the pool has only {len(chosen)} norms")
    return sorted(chosen.values(), key=lambda r: digest(seed, r["id"]))


def header(
    chosen: list[dict[str, Any]],
    *,
    seed: str,
    pool: int,
    dropped: dict[str, int],
    include: Path,
    n_included: int,
    textos: Path,
) -> list[str]:
    tip = collections.Counter(r["tipo"] for r in chosen)
    ter = collections.Counter(r["tercile"] for r in chosen)
    cross = collections.Counter((r["tipo"], r["tercile"]) for r in chosen)
    return [
        f"# Mark-mode reference set mark-reference-2026-11 (texto_id per line), seed {seed}.",
        "# Built by scripts/select_mark_reference.py from the label-mode labelled set x the",
        f"# current text layer ({textos.name}); pool {pool} norms (dropped: {dict(sorted(dropped.items()))}).",
        f"# Includes the {n_included} norms of {include.name}. Order: sha256(seed|id).",
        f"# {len(chosen)} norms: by type {dict(sorted(tip.items()))}; length terciles of the pool",
        f"# (non-blank lines) {dict(sorted(ter.items()))};",
        f"# with sub-level devices where reader and label-mode teacher disagree: "
        f"{sum(1 for r in chosen if r['sub_disagree'])};",
        f"# with quoted blocks (reader): {sum(1 for r in chosen if r['quoted'])};",
        f"# type x tercile: { {f'{t}/{q}': n for (t, q), n in sorted(cross.items())} }",
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--textos", type=Path, required=True)
    parser.add_argument("--include", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--seed", default="20261119")
    parser.add_argument("--max-parts", type=int, default=tm.PILOT_MAX_PARTS)
    parser.add_argument("--min-sub-disagree", type=int, default=60)
    parser.add_argument("--min-quoted", type=int, default=40)
    args = parser.parse_args(argv)
    rows, dropped = features(args.labels, args.textos, args.max_parts)
    assign_terciles(rows)
    include = tr.read_ids_file(args.include)
    chosen = select(
        rows,
        count=args.count,
        seed=args.seed,
        include=include,
        min_sub=args.min_sub_disagree,
        min_quoted=args.min_quoted,
    )
    lines = header(
        chosen,
        seed=args.seed,
        pool=len(rows),
        dropped=dropped,
        include=args.include,
        n_included=len(include),
        textos=args.textos,
    )
    args.out.write_text(
        "\n".join([*lines, *(r["id"] for r in chosen)]) + "\n", encoding="utf-8"
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
