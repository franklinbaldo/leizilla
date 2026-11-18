"""Per-level ratchet gate for the rule reader, scored against mark-mode documents.

``scripts/reader_ratchet.py`` gates the reader at ARTICLE level against the
label-mode teacher. This script gates it BELOW article level (and again at article
level) against a second reference: the **mark-mode documents** of the 300 norms of
``docs/okf/review-samples/mark-reference-2026-11.txt`` (see ``docs/okf/teacher-mark.md``
and the "Gate por nível" section of ``docs/okf/reader-ratchet.md``).

The reference is committed, compact, under ``docs/okf/mark-reference/``:

- ``reference.json``: per norm (``texto_id``), the device rows of the marked document
  (``[kind, n, sufixo, quoted, offset]`` for ``art par inc ali item``), the sha256 of
  the text they index, the suspect flags that remain on the document and which variant
  (``as-is`` / ``repaired``) was taken; the header pins the published ``textos.parquet``
  revision the texts come from;
- ``texts.json.gz``: ``text_sha256 -> text`` of the original 300 norms (public
  legislation, ~280 KB compressed): the offline fast path (unit tests, no download).

The texts of the other norms are NOT in the repository: ``check --textos PATH`` loads
them by sha256 from a local ``textos.parquet`` (the pinned revision; the workflow
downloads and caches it). A norm whose text is missing or whose sha256 differs is "not
comparable" and does not fail the gate; more than ``--max-not-comparable`` (default 2%)
of the reference does. Without ``--textos`` only the offline 300 are checked.

Unit = (norm, level). The unit is ``agree`` when the reader's devices at that level
(own and quoted together) pair one-to-one with the reference's with the same number,
suffix and status (pairing: ``compare_mark_reader.pair_devices``). Norms with suspect
flags are outside the gate, and a level the reference lacks in a norm is not a unit.

Gate: FAIL if a (norm, level) in the baseline's ``agree`` is no longer ``agree`` (or
the norm can no longer be compared: text sha256 mismatch), or if a reference erratum
is stale. Anything else passes and prints the table before -> after and the units that
entered ``agree``. Reference errata (``docs/okf/mark-reference-errata.json``) correct
a mistake of the reference with evidence and the text sha256, like
``teacher-label-errata.json``.

    uv run scripts/reader_ratchet_levels.py check [--textos PATH]
    uv run scripts/reader_ratchet_levels.py update [--textos PATH] [--force --reason TEXT]
    uv run scripts/reader_ratchet_levels.py build-reference --run COLLECT_DIR [--run ...]
        [--textos PATH --textos-revision ID]

Exit codes: 0 pass (or written), 1 check failed or update refused, 2 usage/data error.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import compare_mark_reader as cmr

from leizilla import marcacao
from leizilla.hierarchy_sequence import read_hierarchy

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = REPO_ROOT / "docs" / "okf" / "mark-reference"
DEFAULT_BASELINE = REPO_ROOT / "docs" / "okf" / "mark-ratchet-baseline.json"
DEFAULT_ERRATA = REPO_ROOT / "docs" / "okf" / "mark-reference-errata.json"
READER_MODULES: tuple[str, ...] = (
    "src/leizilla/article_sequence.py",
    "src/leizilla/hierarchy_sequence.py",
    "src/leizilla/marcacao.py",
)
SCHEMA_VERSION = 1
LEVELS = cmr.LEVELS
AGREE = "agree"
OPS = ("add_device", "remove_device", "set_device")
MAX_NOT_COMPARABLE = 0.02
# Tournament hold-out: a seeded 20% of the reference norms (``split_of``) is the TEST
# split that candidate rules are never designed or judged on; the gate and the baseline
# still cover 100% of the reference.
HISTORY_LIST_MAX = 200
SPLIT_SEED = "leizilla-mark-tournament-2026-11-18"
SPLIT_TEST_PERCENT = 20


class RatchetError(Exception):
    """Bad input or unusable baseline/reference; exit code 2."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def split_of(texto_id: str) -> str:
    """``test`` for a seeded 20% of the norms, else ``train`` (stable, text-free)."""
    digest = hashlib.sha256(f"{SPLIT_SEED}:{texto_id}".encode("utf-8")).digest()
    return (
        "test"
        if int.from_bytes(digest[:4], "big") % 100 < SPLIT_TEST_PERCENT
        else "train"
    )


# --------------------------------------------------------------------------
# Reference
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Reference:
    meta: dict[str, Any]
    norms: dict[str, dict[str, Any]]  # texto_id -> record
    texts: dict[str, str]  # text_sha256 -> text (the committed offline subset)
    sha256: Optional[str]


def load_reference(directory: Path) -> Reference:
    ref_path = directory / "reference.json"
    texts_path = directory / "texts.json.gz"
    if not ref_path.is_file() or not texts_path.is_file():
        raise RatchetError(f"reference not found under {directory}")
    data = json.loads(ref_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RatchetError(f"{ref_path}: unexpected schema_version")
    texts = json.loads(gzip.decompress(texts_path.read_bytes()).decode("utf-8"))
    return Reference(
        meta=dict(data.get("source", {})),
        norms=dict(data["norms"]),
        texts=texts,
        sha256=sha256_file(ref_path),
    )


def read_textos_parquet(path: Path, shas: set[str]) -> dict[str, str]:
    """``sha256 -> text`` for the rows of a published ``textos.parquet`` whose text has
    one of ``shas``. The sha256 is recomputed from the text, never trusted from the
    column."""
    import duckdb

    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT texto FROM read_parquet(?) WHERE texto IS NOT NULL", [str(path)]
        ).fetchall()
    finally:
        con.close()
    out: dict[str, str] = {}
    for (text,) in rows:
        sha = sha256_text(text)
        if sha in shas:
            out[sha] = text
    return out


def with_textos(ref: Reference, textos: Optional[Path]) -> Reference:
    """The reference with the committed texts plus those found in ``textos`` by sha256."""
    if textos is None:
        return ref
    wanted = {r["text_sha256"] for r in ref.norms.values()} - set(ref.texts)
    found = read_textos_parquet(textos, wanted)
    return Reference(ref.meta, ref.norms, {**ref.texts, **found}, ref.sha256)


def write_reference(
    directory: Path, meta: dict[str, Any], norms: dict[str, dict[str, Any]], texts: dict
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = ['{"schema_version": %d,' % SCHEMA_VERSION]
    lines.append(
        ' "source": %s,' % json.dumps(meta, ensure_ascii=False, sort_keys=True)
    )
    lines.append(' "norms": {')
    items = sorted(norms.items())
    for i, (key, rec) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(
            "  %s: %s%s"
            % (
                json.dumps(key),
                json.dumps(
                    rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                comma,
            )
        )
    lines += [" }", "}"]
    (directory / "reference.json").write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = json.dumps(texts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    (directory / "texts.json.gz").write_bytes(gzip.compress(payload, 9, mtime=0))


def norm_record(
    rec: dict[str, Any], xml: str, text: str, variant: str, suspects: list[Any]
) -> dict[str, Any]:
    flags = sorted({str(s["type"]) for s in suspects if s["type"] in cmr.SUSPECT_TYPES})
    rows = [
        [
            r["kind"],
            str(r["n"]),
            r.get("sufixo") or "",
            1 if r["quoted"] else 0,
            r["start"],
        ]
        for r in marcacao.to_rows(xml)
        if r["kind"] in LEVELS
    ]
    return {
        "item": rec["item"],
        "uuid5": rec["uuid5"],
        "tipo": rec.get("tipo"),
        "numero": rec.get("numero"),
        "text_sha256": sha256_text(text),
        "variant": variant,
        "flags": flags,
        "devices": rows,
    }


def cmd_build_reference(args: argparse.Namespace) -> int:
    """Add the norms of one or more mark collect dirs to the reference. Norms already
    in the reference keep their record (and the offline texts stay); new norms enter
    without text. ``--textos`` verifies every new sha256 against the published layer."""
    import score_mark

    existing: Optional[Reference] = None
    try:
        existing = load_reference(args.reference)
    except RatchetError:
        pass
    norms: dict[str, dict[str, Any]] = dict(existing.norms) if existing else {}
    texts: dict[str, str] = dict(existing.texts) if existing else {}
    meta: dict[str, Any] = dict(existing.meta) if existing else {}
    added: dict[str, dict[str, Any]] = {}
    runs_meta: list[dict[str, Any]] = list(meta.get("runs", []))
    dropped: collections.Counter[str] = collections.Counter()
    reflow = 0
    for run in args.run:
        docs = score_mark.load_documents(run)
        fixed = score_mark.load_documents(run, "marked-repaired")
        records = {str(r["texto_id"]): r for r in score_mark.load_records(run)}
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        dropped.update(summary.get("dropped_by_reason", {}))
        runs_meta.append(
            {
                "batch_ids": summary.get("batch_ids", []),
                "model": summary.get("model"),
                "prompt_version": summary.get("prompt_version"),
                "collected_git_sha": summary.get("collected_git_sha"),
                "norms": summary.get("norms_total"),
                "states": summary.get("states"),
                "marks_answered": summary.get("marks_answered"),
                "marks_used": summary.get("marks_used"),
                "dropped_by_reason": summary.get("dropped_by_reason"),
            }
        )
        for texto_id, (xml, text) in sorted(docs.items()):
            if texto_id in norms:
                continue
            rec = records[texto_id]
            if rec.get("reflow"):
                reflow += 1
                continue
            variant, suspects = "as-is", rec.get("suspects", [])
            if texto_id in fixed:
                xml, text = fixed[texto_id]
                variant, suspects = "repaired", rec.get("repaired_suspects", [])
            added[texto_id] = norm_record(rec, xml, text, variant, suspects)
    norms.update(added)
    if args.textos:
        shas = {r["text_sha256"] for r in added.values()}
        found = read_textos_parquet(args.textos, shas)
        missing = sorted(t for t, r in added.items() if r["text_sha256"] not in found)
        print(
            f"textos check: {len(added) - len(missing)}/{len(added)} new norms found "
            f"in {args.textos.name} by sha256; {len(missing)} not found"
        )
        for t in missing[:10]:
            print(f"  not in the layer: {t}")
    meta.update(
        {
            "kind": "mark-mode documents",
            "norms": len(norms),
            "variant_policy": "repaired where the converter made a variant, else as-is",
            "row": "[kind, n, sufixo, quoted, offset]",
            "ids_file": "docs/okf/review-samples/mark-reference-2026-11.txt",
            "texts_in_repo": "texts.json.gz holds only the original 300 norms",
            "textos_revision": args.textos_revision or meta.get("textos_revision"),
            "textos_url": (
                f"https://archive.org/download/{args.textos_revision}/textos.parquet"
                if args.textos_revision
                else meta.get("textos_url")
            ),
            "runs": runs_meta,
        }
    )
    write_reference(args.reference, meta, norms, texts)
    print(
        f"reference written: {args.reference} ({len(norms)} norms, "
        f"{len(added)} added, {reflow} reflow skipped); dropped marks {dict(dropped)}"
    )
    return 0


# --------------------------------------------------------------------------
# Errata of the reference
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Errata:
    corrections: list[dict[str, Any]]
    sha256: Optional[str]


def load_errata(path: Optional[Path]) -> Optional[Errata]:
    if path is None:
        return None
    if not path.is_file():
        return Errata([], None)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RatchetError(f"{path}: unexpected schema_version")
    for c in data.get("corrections", []):
        if c.get("op") not in OPS:
            raise RatchetError(f"{path}: unknown op {c.get('op')!r}")
    return Errata(list(data.get("corrections", [])), sha256_file(path))


def apply_corrections(
    rows: list[list[Any]], corrections: list[dict[str, Any]], text: str, sha: str
) -> tuple[list[list[Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """``(rows, applied, stale)``. A correction applies only when the text sha256
    matches and the evidence is on the cited line; otherwise it is stale."""
    lines = text.split("\n")
    starts = cmr.line_starts(text)
    rows = [list(r) for r in rows]
    applied: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []

    def bad(c: dict[str, Any], why: str) -> None:
        stale.append(
            {"norm": c["norm"], "op": c["op"], "line": c.get("line"), "reason": why}
        )

    for c in corrections:
        line = int(c.get("line", 0))
        if c.get("text_sha256") != sha:
            bad(c, "text sha256 differs")
            continue
        if (
            not 1 <= line <= len(lines)
            or str(c.get("evidence", "")) not in lines[line - 1]
        ):
            bad(c, "evidence not on the cited line")
            continue
        base = starts[line - 1]
        kind = c["kind"]
        on_line = [
            r
            for r in rows
            if r[0] == kind and bisect.bisect_right(starts, r[4]) == line
        ]
        if c["op"] == "add_device":
            offset = base + lines[line - 1].index(str(c["evidence"]))
            if any(r[0] == kind and r[4] == offset for r in rows):
                bad(c, "device already in the reference")
                continue
            rows.append(
                [
                    kind,
                    str(c["n"]),
                    c.get("sufixo", ""),
                    1 if c.get("quoted") else 0,
                    offset,
                ]
            )
            rows.sort(key=lambda r: r[4])
            applied.append(c)
            continue
        if "n" in c:
            on_line = [r for r in on_line if r[1] == str(c["n"])]
        if len(on_line) != 1:
            bad(c, f"{len(on_line)} reference devices match (need exactly 1)")
            continue
        target = on_line[0]
        if c["op"] == "remove_device":
            rows.remove(target)
        else:
            new = c.get("set", {})
            if "n" in new:
                target[1] = str(new["n"])
            if "sufixo" in new:
                target[2] = new["sufixo"]
            if "quoted" in new:
                target[3] = 1 if new["quoted"] else 0
        applied.append(c)
    return rows, applied, stale


# --------------------------------------------------------------------------
# Scoreboard
# --------------------------------------------------------------------------


def devices_from_rows(rows: list[list[Any]], text: str) -> list[dict[str, Any]]:
    starts = cmr.line_starts(text)
    return [
        {
            "kind": kind,
            "n": str(n),
            "sufixo": sufixo or "",
            "quoted": bool(quoted),
            "marker": "",
            "offset": offset,
            "line": bisect.bisect_right(starts, offset),
            "path": "",
        }
        for kind, n, sufixo, quoted, offset in rows
    ]


def reader_devices(text: str, tipo: Any, numero: Any) -> list[dict[str, Any]]:
    marks = marcacao.from_hierarchy(
        text, read_hierarchy(text), tipo=tipo, numero=numero
    )
    return cmr.devices(marcacao.build(text, marks), text)


def level_group(outcomes: list[dict[str, Any]]) -> str:
    defects = {d for o in outcomes for d in o["defects"]}
    if not defects:
        return AGREE
    return next(iter(defects)) if len(defects) == 1 else "mixed"


@dataclass
class Board:
    groups: dict[str, dict[str, str]] = field(
        default_factory=dict
    )  # level->norm->group
    devices: dict[str, collections.Counter[str]] = field(default_factory=dict)
    flagged: list[str] = field(default_factory=list)
    not_compared: dict[str, str] = field(default_factory=dict)
    errata_total: int = 0
    errata_applied: list[dict[str, Any]] = field(default_factory=list)
    errata_stale: list[dict[str, Any]] = field(default_factory=list)
    errata_sha256: Optional[str] = None
    reference_sha256: Optional[str] = None
    reader_outcomes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reference_norms: int = 0
    textos_given: bool = True

    def agree(self, level: str) -> list[str]:
        return sorted(n for n, g in self.groups[level].items() if g == AGREE)


def run_board(
    ref: Reference,
    errata: Optional[Errata] = None,
    reader: Any = None,
    keep_outcomes: bool = True,
    only: Optional[set[str]] = None,
) -> Board:
    """Score the reader against the reference. ``reader(text, tipo, numero)`` returns
    the reader's devices (default: the live ``read_hierarchy`` pipeline)."""
    reader = reader or reader_devices
    board = Board(
        groups={lv: {} for lv in LEVELS},
        devices={lv: collections.Counter() for lv in LEVELS},
        errata_sha256=errata.sha256 if errata else None,
        errata_total=len(errata.corrections) if errata else 0,
        reference_sha256=ref.sha256,
        reference_norms=len(ref.norms),
    )
    by_norm: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for c in errata.corrections if errata else []:
        by_norm[str(c["norm"])].append(c)
    known = set(ref.norms)
    for c in errata.corrections if errata else []:
        if c["norm"] not in known:
            board.errata_stale.append(
                {
                    "norm": c["norm"],
                    "op": c["op"],
                    "line": c.get("line"),
                    "reason": "norm not in reference",
                }
            )
    for texto_id, rec in sorted(ref.norms.items()):
        if only is not None and texto_id not in only:
            continue
        text = ref.texts.get(rec["text_sha256"])
        if text is None or sha256_text(text) != rec["text_sha256"]:
            board.not_compared[texto_id] = "text missing or sha256 mismatch"
            continue
        rows = rec["devices"]
        if by_norm.get(texto_id):
            rows, applied, stale = apply_corrections(
                rows, by_norm[texto_id], text, rec["text_sha256"]
            )
            board.errata_applied += applied
            board.errata_stale += stale
        if rec.get("flags"):
            board.flagged.append(texto_id)
            continue
        m_devs = devices_from_rows(rows, text)
        r_devs = reader(text, rec.get("tipo"), rec.get("numero"))
        pairs, m_only, r_only = cmr.pair_devices(m_devs, r_devs)
        outcomes = cmr.classify_pairs(pairs, m_only, r_only)
        if keep_outcomes:
            board.reader_outcomes[texto_id] = outcomes
        for level in LEVELS:
            lv = [o for o in outcomes if o["level"] == level]
            if not lv:
                continue
            board.groups[level][texto_id] = level_group(lv)
            for o in lv:
                if o["defects"]:
                    for d in o["defects"]:
                        board.devices[level][d] += 1
                else:
                    board.devices[level]["agree"] += 1
    return board


# --------------------------------------------------------------------------
# Baseline, verdict, reporting
# --------------------------------------------------------------------------


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def load_baseline(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RatchetError(f"{path}: unexpected schema_version")
    return data


def table(
    board: Board, subset: Optional[Callable[[str], bool]] = None
) -> dict[str, dict[str, int]]:
    """Per level: units (norms), units_agree, and the device outcomes. ``subset`` keeps
    only the norms it accepts (a split)."""
    out: dict[str, dict[str, int]] = {}
    for lv in LEVELS:
        groups = {
            n: g for n, g in board.groups[lv].items() if subset is None or subset(n)
        }
        row = {
            "units": len(groups),
            "units_agree": sum(1 for g in groups.values() if g == AGREE),
        }
        if subset is None:
            counts = board.devices[lv]
        else:
            counts = collections.Counter()
            for norm, outcomes in board.reader_outcomes.items():
                if not subset(norm):
                    continue
                for o in outcomes:
                    if o["level"] != lv:
                        continue
                    for d in o["defects"] or ["agree"]:
                        counts[d] += 1
        row.update({k: int(v) for k, v in sorted(counts.items())})
        out[lv] = row
    return out


@dataclass(frozen=True)
class Verdict:
    lost: list[tuple[str, str, str]]  # (level, norm, state now)
    entered: list[tuple[str, str]]
    stale: list[dict[str, Any]]
    not_comparable: int = 0
    not_comparable_max: int = 0  # allowed count; -1 = not enforced (offline subset)

    @property
    def too_many_not_comparable(self) -> bool:
        return self.not_comparable_max >= 0 and (
            self.not_comparable > self.not_comparable_max
        )

    @property
    def failed(self) -> bool:
        return bool(self.lost or self.stale or self.too_many_not_comparable)


def evaluate(
    baseline: Optional[dict[str, Any]],
    board: Board,
    max_not_comparable: float = MAX_NOT_COMPARABLE,
) -> Verdict:
    """A norm that cannot be compared (text missing or sha256 differs) is reported but
    does not lose its units; too many of them (``max_not_comparable`` of the reference)
    fail the gate. Without ``--textos`` (offline subset) the count is not enforced."""
    lost: list[tuple[str, str, str]] = []
    entered: list[tuple[str, str]] = []
    for lv in LEVELS:
        before = set(((baseline or {}).get("agree") or {}).get(lv, []))
        now = set(board.agree(lv))
        for norm in sorted(before - now):
            if norm in board.not_compared:
                continue
            state = board.groups[lv].get(norm) or (
                "flagged" if norm in board.flagged else "level gone"
            )
            lost.append((lv, norm, state))
        entered += [(lv, n) for n in sorted(now - before)]
    allowed = (
        int(max_not_comparable * board.reference_norms) if board.textos_given else -1
    )
    return Verdict(
        lost, entered, list(board.errata_stale), len(board.not_compared), allowed
    )


def render_table(
    now: dict[str, dict[str, int]], before: Optional[dict[str, dict[str, int]]] = None
) -> list[str]:
    head = f"{'level':<6}{'units':>6}{'agree.before':>13}{'agree.now':>10}"
    head += f"{'dev agree':>11}{'misses':>8}{'extra':>7}{'number':>8}{'status':>8}{'kind':>6}"
    lines = [head]
    for lv in LEVELS:
        r = now[lv]
        b = (before or {}).get(lv, {}).get("units_agree", 0)
        lines.append(
            f"{lv:<6}{r['units']:>6}{b:>13}{r['units_agree']:>10}"
            f"{r.get('agree', 0):>11}{r.get('reader_misses', 0):>8}"
            f"{r.get('reader_extra', 0):>7}{r.get('number_differs', 0):>8}"
            f"{r.get('status_differs', 0):>8}{r.get('kind_differs', 0):>6}"
        )
    return lines


def render_text(
    baseline: Optional[dict[str, Any]],
    board: Board,
    verdict: Verdict,
    splits: bool = False,
) -> str:
    now = table(board)
    lines = render_table(now, (baseline or {}).get("table", {}))
    lines.append(
        f"norms: {len(board.groups['art'])} with articles, flagged (outside the gate): "
        f"{len(board.flagged)}, not comparable: {len(board.not_compared)} of "
        f"{board.reference_norms}"
        + (
            f" (allowed {verdict.not_comparable_max})"
            if verdict.not_comparable_max >= 0
            else " (offline subset: no --textos, count not enforced)"
        )
    )
    lines.append(
        f"errata: {len(board.errata_applied)} applied, {len(board.errata_stale)} stale, "
        f"of {board.errata_total}"
    )
    if splits:
        for name in ("train", "test"):
            lines.append(f"-- split {name} ({SPLIT_TEST_PERCENT}% test, seeded)")
            lines += render_table(table(board, lambda n, k=name: split_of(n) == k))
    for lv, norm, state in verdict.lost:
        lines.append(f"FAIL agree lost: {lv} {norm} -> {state}")
    for e in verdict.stale:
        lines.append(
            f"FAIL stale errata: {e['norm']} {e['op']} line {e['line']}: {e['reason']}"
        )
    if verdict.too_many_not_comparable:
        lines.append(
            f"FAIL not comparable: {verdict.not_comparable} > "
            f"{verdict.not_comparable_max} (text missing or sha256 differs)"
        )
    if not verdict.failed:
        lines.append(f"newly agree: {len(verdict.entered)}")
        lines += [f"  + {lv} {norm}" for lv, norm in verdict.entered[:50]]
        if len(verdict.entered) > 50:
            lines.append(f"  ... and {len(verdict.entered) - 50} more")
    lines.append("PASS" if not verdict.failed else "FAIL")
    return "\n".join(lines)


def write_step_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("```\n" + text + "\n```\n")


def _prepare(args: argparse.Namespace) -> tuple[Reference, Optional[Errata], Board]:
    ref = load_reference(args.reference)
    given = args.textos is not None
    if given and not args.textos.is_file():
        raise RatchetError(f"--textos {args.textos}: no such file")
    ref = with_textos(ref, args.textos)
    errata = None if args.no_errata else load_errata(args.errata)
    board = run_board(ref, errata)
    board.textos_given = given
    return ref, errata, board


def cmd_check(args: argparse.Namespace) -> int:
    baseline = load_baseline(args.baseline)
    if baseline is None:
        raise RatchetError(f"no baseline at {args.baseline}; create it with update")
    ref, errata, board = _prepare(args)
    if baseline.get("reference_sha256") != ref.sha256:
        print("note: reference.json differs from the baseline's (not like-for-like)")
    if baseline.get("errata_sha256") != board.errata_sha256:
        print("note: errata file differs from the baseline's")
    verdict = evaluate(baseline, board, args.max_not_comparable)
    text = render_text(baseline, board, verdict, splits=args.splits)
    print(text)
    write_step_summary(text)
    return 1 if verdict.failed else 0


def cmd_update(args: argparse.Namespace) -> int:
    if args.force and not args.reason:
        raise RatchetError("--force requires --reason")
    previous = load_baseline(args.baseline)
    ref, errata, board = _prepare(args)
    verdict = evaluate(previous, board, args.max_not_comparable)
    if not board.textos_given:
        raise RatchetError("update needs --textos (the full reference, not the subset)")
    if board.not_compared and not args.force:
        print(render_text(previous, board, verdict))
        print(
            f"update refused: {len(board.not_compared)} norms not comparable would "
            "drop out of the baseline; fix the texts or rerun with --force --reason"
        )
        return 1
    if board.errata_stale:
        print(render_text(previous, board, verdict))
        print("update refused: stale reference errata (--force does not apply)")
        return 1
    if previous is not None and verdict.failed and not args.force:
        print(render_text(previous, board, verdict))
        print('update refused: check fails; rerun with --force --reason "..."')
        return 1
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    entry = {
        "date": today,
        "reader_commit": _git("rev-parse", "HEAD"),
        "forced": bool(args.force),
        "reason": args.reason or ("initial baseline" if previous is None else None),
        "table": table(board),
        "entered_count": len(verdict.entered),
        "left_count": len(verdict.lost),
        "entered": [f"{lv} {n}" for lv, n in verdict.entered[:HISTORY_LIST_MAX]],
        "left": [f"{lv} {n}" for lv, n, _ in verdict.lost[:HISTORY_LIST_MAX]],
    }
    new = {
        "schema_version": SCHEMA_VERSION,
        "date": today,
        "reader_commit": _git("rev-parse", "HEAD"),
        "reader_last_change": _git("log", "-1", "--format=%H", "--", *READER_MODULES),
        "reference": ref.meta,
        "reference_sha256": ref.sha256,
        "errata_sha256": board.errata_sha256,
        "errata_applied": len(board.errata_applied),
        "flagged": sorted(board.flagged),
        "table": table(board),
        "agree": {lv: board.agree(lv) for lv in LEVELS},
        "history": list((previous or {}).get("history", [])) + [entry],
    }
    args.baseline.parent.mkdir(parents=True, exist_ok=True)
    args.baseline.write_text(
        json.dumps(new, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(render_text(previous, board, verdict))
    print(f"baseline written: {args.baseline}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "update", "build-reference"):
        p = sub.add_parser(name)
        p.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
        if name == "build-reference":
            p.add_argument(
                "--run", type=Path, action="append", required=True, help="collect dir"
            )
            p.add_argument("--textos", type=Path, default=None)
            p.add_argument("--textos-revision", default=None)
            continue
        p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
        p.add_argument("--errata", type=Path, default=DEFAULT_ERRATA)
        p.add_argument("--no-errata", action="store_true")
        p.add_argument(
            "--textos",
            type=Path,
            default=None,
            help="published textos.parquet (pinned revision); texts are matched by "
            "sha256. Without it only the 300 offline texts are checked",
        )
        p.add_argument("--max-not-comparable", type=float, default=MAX_NOT_COMPARABLE)
        p.add_argument(
            "--splits", action="store_true", help="also print the train/test tables"
        )
        if name == "update":
            p.add_argument("--force", action="store_true")
            p.add_argument("--reason", default=None)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build-reference":
            return cmd_build_reference(args)
        if args.command == "check":
            return cmd_check(args)
        return cmd_update(args)
    except RatchetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
