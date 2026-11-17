"""Compare the LLM teacher's article labels with the rule-based hierarchy reader.

For every norm labelled by ``leizilla.teacher_batch`` this script:

1. obtains the exact text the teacher saw (local cache first, then the published
   ``textos.parquet`` when given, then the Internet Archive with a 1 s throttle),
   and verifies its sha256 against the label header; a mismatch is counted and the
   norm is skipped, never compared;
2. runs ``leizilla.hierarchy_sequence.read_hierarchy`` on that text;
3. compares article level by ``(line, number)``: the teacher's ``artigo`` labels
   with ``quoted: false`` against the reader's article nodes with status ``own``.

Each norm lands in exactly one group:

- ``agree_closed``: the sets are equal and the reader closes the article level;
- ``agree_open``: the sets are equal and the reader does not close;
- ``disagree_closed``: the reader closes but the sets differ (the dangerous group);
- ``disagree_open``: the reader does not close and the sets differ;
- ``teacher_inconsistent``: the reader closes with a different set and the
  teacher's own article numbers do not read 1..N (suffixes like ``5-A`` ignored).

The ``teacher_inconsistent`` flag is also written for every norm.

Line numbers follow the teacher's convention: 1-based indexes into
``text.split("\\n")``. Reader offsets are converted with the same rule.

    uv run scripts/compare_teacher_reader.py --labels LABELS_DIR --texts TEXTS_DIR \\
        --out OUT_DIR [--textos-parquet PATH] [--limit N]

The texts cache is laid out as ``TEXTS_DIR/{item}/{txt_name}`` and stores the
UTF-8 bytes of the text the teacher hashed. Norms whose text could not be fetched
are listed in ``TEXTS_DIR/_missing.txt`` so that a re-run does not call the network
for them again.

Outputs in ``--out``: ``groups.csv`` (one row per norm), ``details.jsonl`` (the
per-norm differences), ``summary.json`` and ``summary.md``.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import duckdb

from leizilla.hierarchy_sequence import read_hierarchy
from leizilla.teacher_batch import NormRef, fetch_text

MIN_INTERVAL_S = 1.0
GROUPS: tuple[str, ...] = (
    "agree_closed",
    "agree_open",
    "disagree_closed",
    "disagree_open",
    "teacher_inconsistent",
)
DISAGREE_GROUPS: tuple[str, ...] = ("disagree_closed", "disagree_open")

KIND_STATUS = "own-vs-quoted status difference"
KIND_SAME_LINE = "same line, different number"
KIND_START = "teacher-only at start of chain"
KIND_MIDDLE = "teacher-only in middle of chain"
KIND_END = "teacher-only at end of chain"
KIND_NO_READER = "teacher-only, reader has no own article"
KIND_READER_ONLY = "reader-only article"
DIFF_KINDS: tuple[str, ...] = (
    KIND_STATUS,
    KIND_SAME_LINE,
    KIND_START,
    KIND_MIDDLE,
    KIND_END,
    KIND_NO_READER,
    KIND_READER_ONLY,
)

TEXT_TRUNC = 120
PREFIX_LEN = 8
TOP_PREFIXES = 15

ArticleKey = tuple[int, str]  # (1-based line, normalised number)


@dataclass(frozen=True)
class Diff:
    kind: str
    side: str  # "teacher" | "reader"
    line: int
    number: str


# --------------------------------------------------------------------------
# Numbers and lines
# --------------------------------------------------------------------------


def normalize_number(raw: Optional[str]) -> str:
    """Canonical article number: digits, optionally ``-LETTER``; ``?`` if unknown."""
    if raw is None:
        return "?"
    text = raw.strip().upper()
    match = re.fullmatch(r"(\d+)\s*-?\s*([A-Z])", text)
    if match:
        return f"{int(match.group(1))}-{match.group(2)}"
    match = re.fullmatch(r"(\d+)", text)
    if match:
        return str(int(match.group(1)))
    return text or "?"


def reader_number(number: Optional[int], suffix: Optional[str]) -> str:
    if number is None:
        return "?"
    if suffix:
        return normalize_number(f"{number}-{suffix.strip().lstrip('-').strip()}")
    return normalize_number(str(number))


def teacher_numbers_consistent(items: Iterable[ArticleKey]) -> bool:
    """True when the teacher's own numbers read 1..N in line order.

    Articles with a letter suffix (``5-A``) are ignored. An unknown or unparseable
    number makes the sequence inconsistent.
    """
    bases: list[int] = []
    for _line, number in sorted(items):
        if number == "?":
            return False
        match = re.fullmatch(r"(\d+)(?:-([A-Z]))?", number)
        if match is None:
            return False
        if match.group(2):
            continue
        bases.append(int(match.group(1)))
    return bases == list(range(1, len(bases) + 1))


def line_of_offsets(text: str) -> Callable[[int], int]:
    newlines = [i for i, ch in enumerate(text) if ch == "\n"]
    return lambda pos: bisect.bisect_left(newlines, pos) + 1


def marker_prefix(line_text: str) -> str:
    stripped = line_text.strip()[:PREFIX_LEN].lower()
    return re.sub(r"\d", "9", stripped)


# --------------------------------------------------------------------------
# Pure classification (no I/O, no reader)
# --------------------------------------------------------------------------


def diff_kinds(
    t_own: set[ArticleKey],
    t_quoted: set[ArticleKey],
    r_own: set[ArticleKey],
    r_quoted: set[ArticleKey],
) -> list[Diff]:
    """Explain every article present on only one side, in order of precedence.

    1. The same (line, number) is own for one side and quoted for the other.
    2. A teacher-only and a reader-only article share a line (number differs).
    3. Remaining teacher-only articles are placed relative to the reader's own
       article lines: before the first, after the last, or in between.
    4. Remaining reader-only articles.
    """
    diffs: list[Diff] = []
    teacher_only = sorted(t_own - r_own)
    reader_only = sorted(r_own - t_own)
    rest_t: list[ArticleKey] = []
    rest_r: list[ArticleKey] = list(reader_only)

    for line, number in teacher_only:
        if (line, number) in r_quoted:
            diffs.append(Diff(KIND_STATUS, "teacher", line, number))
        else:
            rest_t.append((line, number))
    for line, number in list(rest_r):
        if (line, number) in t_quoted:
            diffs.append(Diff(KIND_STATUS, "reader", line, number))
            rest_r.remove((line, number))

    remaining_t: list[ArticleKey] = []
    for line, number in rest_t:
        partner = next((r for r in rest_r if r[0] == line), None)
        if partner is None:
            remaining_t.append((line, number))
            continue
        rest_r.remove(partner)
        diffs.append(Diff(KIND_SAME_LINE, "teacher", line, number))

    own_lines = sorted({line for line, _ in r_own})
    for line, number in remaining_t:
        if not own_lines:
            kind = KIND_NO_READER
        elif line < own_lines[0]:
            kind = KIND_START
        elif line > own_lines[-1]:
            kind = KIND_END
        else:
            kind = KIND_MIDDLE
        diffs.append(Diff(kind, "teacher", line, number))
    for line, number in rest_r:
        diffs.append(Diff(KIND_READER_ONLY, "reader", line, number))
    return diffs


def classify(
    t_own: set[ArticleKey],
    r_own: set[ArticleKey],
    closes: bool,
    teacher_consistent: bool,
) -> str:
    if t_own == r_own:
        return "agree_closed" if closes else "agree_open"
    if closes and not teacher_consistent:
        return "teacher_inconsistent"
    return "disagree_closed" if closes else "disagree_open"


# --------------------------------------------------------------------------
# Per-norm comparison
# --------------------------------------------------------------------------


def compare_norm(
    header: dict[str, Any], labels: list[dict[str, Any]], text: str
) -> dict[str, Any]:
    lines = text.split("\n")
    line_of = line_of_offsets(text)

    t_own: set[ArticleKey] = set()
    t_quoted: set[ArticleKey] = set()
    for label in labels:
        if label.get("category") != "artigo":
            continue
        key = (int(label["line"]), normalize_number(label.get("number")))
        (t_quoted if label.get("quoted") else t_own).add(key)

    report = read_hierarchy(text)
    r_own: set[ArticleKey] = set()
    r_quoted: set[ArticleKey] = set()
    for node in report["nodes"]:
        if node["kind"] != "artigo":
            continue
        key = (line_of(node["start"]), reader_number(node["number"], node["suffix"]))
        (r_own if node["status"] == "own" else r_quoted).add(key)

    closes = bool(report["levels"]["artigo"]["closes"])
    consistent = teacher_numbers_consistent(t_own)
    group = classify(t_own, r_own, closes, consistent)
    diffs = diff_kinds(t_own, t_quoted, r_own, r_quoted)
    first_line: Optional[int] = min((d.line for d in diffs), default=None)
    first_text = ""
    if first_line is not None and 1 <= first_line <= len(lines):
        first_text = lines[first_line - 1].strip()[:TEXT_TRUNC]

    return {
        "identifier": header["item"],
        "file": header["txt_name"],
        "uuid5": header["uuid5"],
        "tipo": header["tipo"],
        "numero": header["numero"],
        "group": group,
        "teacher_inconsistent": not consistent,
        "n_teacher_articles": len(t_own),
        "n_reader_articles": len(r_own),
        "reader_closes_articles": closes,
        "final_clause_placed": bool(report["final_clause_placed"]),
        "tail_clean": bool(report["tail_clean"]),
        "n_chunks": header.get("chunks"),
        "first_disagreement_line": first_line,
        "first_disagreement_text": first_text,
        "diffs": [
            {
                "kind": d.kind,
                "side": d.side,
                "line": d.line,
                "number": d.number,
                "prefix": marker_prefix(lines[d.line - 1])
                if d.side == "teacher" and 1 <= d.line <= len(lines)
                else None,
            }
            for d in diffs
        ],
    }


# --------------------------------------------------------------------------
# Inputs: labels and texts
# --------------------------------------------------------------------------


def load_labelled_norms(
    labels_dir: Path,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Read every norm file (header record + label records); skip failures.jsonl."""
    norms: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for path in sorted(labels_dir.rglob("*.jsonl")):
        if path.name == "failures.jsonl":
            continue
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not records or records[0].get("record") != "norm":
            continue
        labels = [r for r in records[1:] if r.get("record") == "label"]
        norms.append((records[0], labels))
    return norms


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ParquetTexts:
    """Lookup of the published ``textos.parquet`` by ``sha256_texto``; loaded lazily."""

    def __init__(self, path: Optional[Path]) -> None:
        self.path = path
        self._by_sha: Optional[dict[str, str]] = None

    def get(self, sha: str) -> Optional[str]:
        if self.path is None:
            return None
        if self._by_sha is None:
            con = duckdb.connect()
            try:
                rows = con.execute(
                    "select sha256_texto, texto from read_parquet(?) "
                    "where texto is not null and sha256_texto is not null",
                    [str(self.path)],
                ).fetchall()
            finally:
                con.close()
            self._by_sha = {str(s): str(t) for s, t in rows}
        return self._by_sha.get(sha)


class IaFetcher:
    """Sequential Internet Archive fetches, at least ``MIN_INTERVAL_S`` apart."""

    def __init__(
        self,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sleep = sleep
        self._clock = clock
        self._last: Optional[float] = None
        self.requests = 0

    def __call__(self, header: dict[str, Any]) -> Optional[str]:
        if self._last is not None:
            wait = MIN_INTERVAL_S - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1
        ref = NormRef(
            item=str(header["item"]),
            fonte=str(header["fonte"]),
            tipo=str(header["tipo"]),
            numero=int(header["numero"]),
            uuid5=str(header["uuid5"]),
            txt_name=str(header["txt_name"]),
        )
        return fetch_text(ref)


def _cache_file(texts_dir: Path, header: dict[str, Any]) -> Path:
    return texts_dir / str(header["item"]) / str(header["txt_name"])


def get_text(
    header: dict[str, Any],
    texts_dir: Path,
    parquet: ParquetTexts,
    missing: set[str],
    ia: IaFetcher,
) -> tuple[Optional[str], str]:
    """Return (text, source). Source is cache, parquet, ia or missing."""
    path = _cache_file(texts_dir, header)
    if path.is_file():
        return path.read_bytes().decode("utf-8"), "cache"
    sha = str(header["text_sha256"])
    from_parquet = parquet.get(sha)
    if from_parquet is not None and sha256_text(from_parquet) == sha:
        _write_cache(path, from_parquet)
        return from_parquet, "parquet"
    key = f"{header['item']}/{header['txt_name']}"
    if key in missing:
        return None, "missing"
    fetched = ia(header)
    if fetched is None:
        missing.add(key)
        texts_dir.mkdir(parents=True, exist_ok=True)
        with (texts_dir / "_missing.txt").open("a", encoding="utf-8") as fh:
            fh.write(key + "\n")
        return None, "missing"
    _write_cache(path, fetched)
    return fetched, "ia"


def _write_cache(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def read_missing(texts_dir: Path) -> set[str]:
    path = texts_dir / "_missing.txt"
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


# --------------------------------------------------------------------------
# Aggregation and output
# --------------------------------------------------------------------------


def summarise(
    rows: list[dict[str, Any]],
    labelled: int,
    mismatches: list[str],
    missing_keys: list[str],
    sources: collections.Counter[str],
    ia_requests: int,
) -> dict[str, Any]:
    compared = len(rows)
    groups = collections.Counter(r["group"] for r in rows)
    group_table = {
        g: {
            "count": groups.get(g, 0),
            "pct": round(100.0 * groups.get(g, 0) / compared, 2) if compared else 0.0,
        }
        for g in GROUPS
    }
    breakdown: dict[str, Any] = {}
    prefixes: dict[str, list[tuple[str, int]]] = {}
    for group in (*DISAGREE_GROUPS, "teacher_inconsistent"):
        items = collections.Counter()
        norms_with = collections.Counter()
        prefix_count: collections.Counter[str] = collections.Counter()
        for r in rows:
            if r["group"] != group:
                continue
            seen: set[str] = set()
            for d in r["diffs"]:
                items[d["kind"]] += 1
                seen.add(d["kind"])
                if d["side"] == "teacher" and d["prefix"] is not None:
                    prefix_count[d["prefix"]] += 1
            for kind in seen:
                norms_with[kind] += 1
        breakdown[group] = {
            kind: {"items": items.get(kind, 0), "norms": norms_with.get(kind, 0)}
            for kind in DIFF_KINDS
        }
        prefixes[group] = prefix_count.most_common(TOP_PREFIXES)
    combined: collections.Counter[str] = collections.Counter()
    for r in rows:
        if r["group"] in DISAGREE_GROUPS:
            for d in r["diffs"]:
                if d["side"] == "teacher" and d["prefix"] is not None:
                    combined[d["prefix"]] += 1
    return {
        "labelled_norms": labelled,
        "compared": compared,
        "skipped_sha_mismatch": len(mismatches),
        "skipped_sha_mismatch_keys": mismatches,
        "skipped_missing_text": len(missing_keys),
        "skipped_missing_text_keys": missing_keys,
        "text_sources": dict(sources),
        "ia_requests": ia_requests,
        "groups": group_table,
        "disagreement_breakdown": breakdown,
        "top_teacher_only_prefixes_disagree": combined.most_common(TOP_PREFIXES),
        "top_teacher_only_prefixes_by_group": prefixes,
        "teacher_inconsistent_flag_norms": sum(
            1 for r in rows if r["teacher_inconsistent"]
        ),
    }


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Teacher vs reader, article level",
        "",
        f"- labelled norms: {summary['labelled_norms']}",
        f"- compared: {summary['compared']}",
        f"- skipped, sha mismatch: {summary['skipped_sha_mismatch']}",
        f"- skipped, text missing: {summary['skipped_missing_text']}",
        f"- text sources: {summary['text_sources']}",
        f"- teacher_inconsistent flag (any group): "
        f"{summary['teacher_inconsistent_flag_norms']}",
        "",
        "## Groups",
        "",
        "| group | norms | % |",
        "|---|---:|---:|",
    ]
    for g in GROUPS:
        row = summary["groups"][g]
        lines.append(f"| {g} | {row['count']} | {row['pct']:.2f} |")
    for group in DISAGREE_GROUPS:
        lines += [
            "",
            f"## Disagreement kinds: {group}",
            "",
            "| kind | items | norms |",
            "|---|---:|---:|",
        ]
        for kind in DIFF_KINDS:
            row = summary["disagreement_breakdown"][group][kind]
            lines.append(f"| {kind} | {row['items']} | {row['norms']} |")
    lines += [
        "",
        "## Teacher-only marker prefixes (disagree groups)",
        "",
        "| prefix | count |",
        "|---|---:|",
    ]
    for prefix, count in summary["top_teacher_only_prefixes_disagree"]:
        lines.append(f"| `{prefix}` | {count} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Corpus:
    """Result of comparing every labelled norm; ``rows`` has one entry per norm."""

    rows: list[dict[str, Any]]
    mismatches: list[str]
    missing_keys: list[str]
    sources: collections.Counter[str]
    ia_requests: int


def compare_corpus(
    norms: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    texts_dir: Path,
    textos_parquet: Optional[Path] = None,
    ia: Optional[IaFetcher] = None,
) -> Corpus:
    """Fetch each norm's text (cache, parquet, IA) and compare it with the reader.

    Shared by ``run`` and ``scripts/reader_ratchet.py``. Norms whose text is
    missing or whose sha256 does not match are reported, never compared.
    """
    texts_dir.mkdir(parents=True, exist_ok=True)
    parquet = ParquetTexts(textos_parquet)
    fetcher = ia or IaFetcher()
    missing = read_missing(texts_dir)
    sources: collections.Counter[str] = collections.Counter()
    mismatches: list[str] = []
    missing_keys: list[str] = []
    rows: list[dict[str, Any]] = []

    for header, labels in norms:
        key = f"{header['item']}/{header['txt_name']}"
        text, source = get_text(header, texts_dir, parquet, missing, fetcher)
        sources[source] += 1
        if text is None:
            missing_keys.append(key)
            continue
        if sha256_text(text) != header["text_sha256"]:
            mismatches.append(key)
            continue
        rows.append(compare_norm(header, labels, text))

    return Corpus(
        rows=rows,
        mismatches=mismatches,
        missing_keys=missing_keys,
        sources=sources,
        ia_requests=fetcher.requests,
    )


def run(
    labels_dir: Path,
    texts_dir: Path,
    out_dir: Path,
    textos_parquet: Optional[Path] = None,
    limit: int = 0,
    ia: Optional[IaFetcher] = None,
) -> dict[str, Any]:
    norms = load_labelled_norms(labels_dir)
    if limit:
        norms = norms[:limit]
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus = compare_corpus(norms, texts_dir, textos_parquet, ia)
    rows = corpus.rows

    summary = summarise(
        rows,
        len(norms),
        corpus.mismatches,
        corpus.missing_keys,
        corpus.sources,
        corpus.ia_requests,
    )
    fields = [
        "identifier",
        "file",
        "tipo",
        "numero",
        "group",
        "teacher_inconsistent",
        "n_teacher_articles",
        "n_reader_articles",
        "reader_closes_articles",
        "final_clause_placed",
        "tail_clean",
        "n_chunks",
        "first_disagreement_line",
        "first_disagreement_text",
    ]
    with (out_dir / "groups.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    with (out_dir / "details.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(out_dir / "summary.md", summary)
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--labels", type=Path, required=True, help="labels root")
    parser.add_argument("--texts", type=Path, required=True, help="texts cache dir")
    parser.add_argument("--out", type=Path, required=True, help="output dir")
    parser.add_argument(
        "--textos-parquet",
        type=Path,
        default=None,
        help="published textos.parquet, checked before any IA fetch",
    )
    parser.add_argument("--limit", type=int, default=0, help="first N norms only")
    args = parser.parse_args(argv)
    summary = run(
        args.labels,
        args.texts,
        args.out,
        textos_parquet=args.textos_parquet,
        limit=args.limit,
    )
    print(
        json.dumps(
            {
                "compared": summary["compared"],
                "groups": {g: summary["groups"][g]["count"] for g in GROUPS},
                "skipped_sha_mismatch": summary["skipped_sha_mismatch"],
                "skipped_missing_text": summary["skipped_missing_text"],
                "text_sources": summary["text_sources"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
