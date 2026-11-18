"""Select the whole-layer mark-mode run (offline, deterministic).

Profiles the current text layer (``textos.parquet``) and writes selection files (one
``texto_id`` per line, under ``docs/okf/review-samples/``) for one mark-mode run over the
layer, minus three exclusions, in this priority order (a norm is listed under the first
reason that applies):

1. ``reference``: in ``mark-reference-2026-11.txt`` AND its text sha256 is unchanged in
   the layer (the sha recorded in ``docs/okf/mark-reference/reference.json``). A
   reference norm whose text changed is NOT excluded (it is listed in the header);
2. ``parts``: needs more than ``--max-parts`` (8) parts under mark-mode chunking
   (150 lines / 14 000 characters); these get their own treatment later;
3. ``longlines``: a line longer than ``--long-line`` characters (200) or p95 of the
   non-blank line lengths above ``--long-p95`` (150). The pilot (median 36, max 128)
   worked; the re-flow set (every line 200-400) truncated 48 of 48. Those norms go to a
   separate file for ``anchors=snippet``.

``--rendicao compilada`` restricts the layer to the norms whose reading text is that
rendition (the ``rendicao`` column of ``textos.parquet``) and writes
``mark-compiladas-2026-11`` / ``mark-compiladas-longlines-2026-11`` instead (same three
exclusions; the norms with more than ``--max-parts`` are listed in the file header, not
silently dropped).

The main file can be split in two of similar cost (``--split``): norms sorted by
(characters, id) and dealt alternately to ``-a`` and ``-b``.

    uv run scripts/select_mark_full.py --textos textos.parquet \\
        --out-dir docs/okf/review-samples --split --profile-json profile.json
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

import duckdb

from leizilla import teacher_batch as tb
from leizilla import teacher_mark as tm
from leizilla import teacher_review as tr

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_IDS = (
    REPO_ROOT / "docs" / "okf" / "review-samples" / "mark-reference-2026-11.txt"
)
DEFAULT_REFERENCE_JSON = (
    REPO_ROOT / "docs" / "okf" / "mark-reference" / "reference.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "okf" / "review-samples"
MAX_PARTS = 8
LONG_LINE = 200
LONG_P95 = 150
STEM = "mark-full-2026-11"
LONG_STEM = "mark-full-longlines-2026-11"


def percentile(values: list[int], p: float) -> float:
    """Linear-interpolated percentile (``p`` in 0..100) of a non-empty list."""
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def source_of(motor: Optional[str]) -> str:
    """Group the ``ocr_motor`` column: IA text (null), own OCR, text layer of the PDF."""
    if not motor:
        return "ia"
    if motor.startswith("kreuzberg"):
        return "own-reocr"
    if motor.startswith("tesseract"):
        return "own-tesseract"
    if motor.startswith("pdf-to-hocr"):
        return "pdf-text"
    return "other"


def profile_record(rec: tb.TextoRecord) -> dict[str, Any]:
    lines = tb.split_lines(rec.text)
    lengths = [len(ln.strip()) for ln in lines if ln.strip()]
    parts = len(
        tb.chunk_document(
            lines, max_lines=tm.MARK_MAX_LINES, max_chars=tm.MARK_MAX_CHARS
        )
    )
    n = len(lengths)
    return {
        "id": str(rec.texto_id),
        "tipo": rec.ref.tipo,
        "numero": rec.ref.numero,
        "source": source_of(rec.ocr_motor),
        "motor": rec.ocr_motor,
        "sha": rec.text_sha256,
        "nonblank": n,
        "chars": len(rec.text),
        "parts": parts,
        "median": statistics.median(lengths) if n else 0.0,
        "p95": percentile(lengths, 95) if n else 0.0,
        "max": max(lengths) if n else 0,
        "share120": sum(1 for x in lengths if x > 120) / n if n else 0.0,
        "share200": sum(1 for x in lengths if x > 200) / n if n else 0.0,
    }


def rendicao_of(textos: Path) -> dict[str, str]:
    """``texto_id`` -> ``rendicao`` of the reading text (empty when the column is absent)."""
    con = duckdb.connect()
    try:
        cols = {
            r[0]
            for r in con.execute(
                "describe select * from read_parquet(?)", [str(textos)]
            ).fetchall()
        }
        if "rendicao" not in cols:
            return {}
        return {
            str(i): str(r or "original")
            for i, r in con.execute(
                "select texto_id, rendicao from read_parquet(?)", [str(textos)]
            ).fetchall()
        }
    finally:
        con.close()


def profile_layer(textos: Path, rendicao: Optional[str] = None) -> list[dict[str, Any]]:
    corpus = tb.load_textos(textos)
    keep = rendicao_of(textos) if rendicao else {}
    rows = [
        profile_record(rec)
        for rec in corpus.records
        if rec.texto_id and (not rendicao or keep.get(str(rec.texto_id)) == rendicao)
    ]
    return sorted(rows, key=lambda r: r["id"])


def classify(
    rows: list[dict[str, Any]],
    *,
    reference_ids: list[str],
    reference_sha: dict[str, str],
    max_parts: int,
    long_line: int,
    long_p95: float,
) -> dict[str, Any]:
    """Partition the layer: ``main``, ``reference``, ``parts``, ``longlines``.

    ``changed`` lists reference norms whose text changed (they stay in play and are
    classified like any other norm); ``missing`` those no longer in the layer.
    """
    by_id = {r["id"]: r for r in rows}
    out: dict[str, list[dict[str, Any]]] = {
        "main": [],
        "reference": [],
        "parts": [],
        "longlines": [],
    }
    changed: list[dict[str, Any]] = []
    ref = set(reference_ids)
    missing = sorted(i for i in ref if i not in by_id)
    for r in rows:
        if r["id"] in ref:
            if reference_sha.get(r["id"]) == r["sha"]:
                out["reference"].append(r)
                continue
            changed.append(r)
        if r["parts"] > max_parts:
            out["parts"].append(r)
        elif r["max"] > long_line or r["p95"] > long_p95:
            out["longlines"].append(r)
        else:
            out["main"].append(r)
    return {**out, "changed": changed, "missing": missing}


def split_in_two(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda r: (r["chars"], r["id"]))
    return ordered[0::2], ordered[1::2]


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(collections.Counter(str(r[key]) for r in rows).items()))


def write_ids(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    ids = sorted(r["id"] for r in rows)
    path.write_text(
        "\n".join([*(f"# {h}" for h in header), *ids]) + "\n", encoding="utf-8"
    )


def describe(rows: list[dict[str, Any]]) -> str:
    return (
        f"{len(rows)} norms; by type {_counts(rows, 'tipo')}; "
        f"by source {_counts(rows, 'source')}; "
        f"chars {sum(r['chars'] for r in rows)}; "
        f"max parts {max((r['parts'] for r in rows), default=0)}"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--textos", type=Path, required=True)
    parser.add_argument("--reference-ids", type=Path, default=DEFAULT_REFERENCE_IDS)
    parser.add_argument("--reference-json", type=Path, default=DEFAULT_REFERENCE_JSON)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-parts", type=int, default=MAX_PARTS)
    parser.add_argument("--long-line", type=int, default=LONG_LINE)
    parser.add_argument("--long-p95", type=float, default=LONG_P95)
    parser.add_argument(
        "--split", action="store_true", help="write the main file as -a and -b"
    )
    parser.add_argument(
        "--rendicao",
        default=None,
        help="only norms whose reading text is this rendition (e.g. compilada); "
        "output stem becomes mark-<rendicao>s-2026-11",
    )
    parser.add_argument("--profile-json", type=Path, default=None)
    parser.add_argument("--exclusions-md", type=Path, default=None)
    args = parser.parse_args(argv)

    rows = profile_layer(args.textos, args.rendicao)
    ref_ids = tr.read_ids_file(args.reference_ids)
    ref_doc = json.loads(args.reference_json.read_text(encoding="utf-8"))
    ref_sha = {k: v["text_sha256"] for k, v in ref_doc["norms"].items()}
    part = classify(
        rows,
        reference_ids=ref_ids,
        reference_sha=ref_sha,
        max_parts=args.max_parts,
        long_line=args.long_line,
        long_p95=args.long_p95,
    )
    if args.rendicao:
        part["missing"] = []  # every reference id is "missing" from a restricted subset
    base = [
        f"Whole-layer mark-mode selection, built by scripts/select_mark_full.py from "
        f"{args.textos.name} ({len(rows)} norms).",
        f"Exclusions in order: reference norms with unchanged text sha "
        f"({len(part['reference'])}), more than {args.max_parts} parts "
        f"({len(part['parts'])}), line > {args.long_line} chars or p95 > "
        f"{args.long_p95:g} ({len(part['longlines'])}).",
        f"Reference norms whose text changed (kept in play): "
        f"{[r['id'] for r in part['changed']] or 'none'}; "
        f"reference ids missing from the layer: {part['missing'] or 'none'}.",
    ]
    stem, long_stem = STEM, LONG_STEM
    if args.rendicao:
        stem = f"mark-{args.rendicao}s-2026-11"
        long_stem = f"mark-{args.rendicao}s-longlines-2026-11"
        base.append(
            f"Restricted to rendicao={args.rendicao}. Over {args.max_parts} parts "
            f"(excluded, listed): "
            + (
                ", ".join(
                    f"{r['id']} ({r['parts']} parts)"
                    for r in sorted(part["parts"], key=lambda r: r["id"])
                )
                or "none"
            )
        )
    out = args.out_dir
    written: dict[str, list[dict[str, Any]]] = {}
    if args.split:
        a, b = split_in_two(part["main"])
        written[f"{stem}-a"] = a
        written[f"{stem}-b"] = b
    else:
        written[stem] = part["main"]
    written[long_stem] = part["longlines"]
    for name, sel in written.items():
        write_ids(out / f"{name}.txt", [name, *base, describe(sel)], sel)
        print(f"{name}: {describe(sel)}")
    print(
        f"excluded: reference {len(part['reference'])}, parts {len(part['parts'])}, "
        f"longlines {len(part['longlines'])}; reference changed "
        f"{len(part['changed'])}, missing {len(part['missing'])}"
    )
    if args.exclusions_md is not None:
        lines = ["# parts > %d (id, parts, chars)" % args.max_parts]
        lines += [
            f"{r['id']}\t{r['parts']}\t{r['chars']}"
            for r in sorted(part["parts"], key=lambda r: (-r["parts"], r["id"]))
        ]
        lines += ["", "# long lines (id, max, p95, median, share>200, nonblank)"]
        lines += [
            f"{r['id']}\t{r['max']}\t{r['p95']:.0f}\t{r['median']:.0f}\t"
            f"{r['share200']:.3f}\t{r['nonblank']}"
            for r in sorted(part["longlines"], key=lambda r: (-r["max"], r["id"]))
        ]
        args.exclusions_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.profile_json is not None:
        args.profile_json.write_text(
            json.dumps(
                {
                    "rows": rows,
                    "reference": [r["id"] for r in part["reference"]],
                    "changed": [r["id"] for r in part["changed"]],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
