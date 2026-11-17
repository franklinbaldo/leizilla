"""Ratchet gate for the rule-based article reader, scored against teacher labels.

Runs the teacher comparison of ``scripts/compare_teacher_reader.py`` (imported,
not shelled out) and compares the result with a recorded baseline:

- FAIL if a norm in the baseline's ``agree_closed`` is no longer ``agree_closed``
  (or is no longer compared at all);
- FAIL if a norm is in ``disagree_closed`` now and was not in the baseline's
  ``disagree_closed``.

Anything else passes. A pass prints the before/after table per group and the
norms that newly entered ``agree_closed``.

Teacher-label errata (``docs/okf/teacher-label-errata.json``, see
``docs/okf/reader-ratchet.md``) are applied before the comparison. A stale
correction (text sha or evidence line no longer matches) is a FAIL for ``check``
and blocks ``update``, even with ``--force``: it must be fixed, not ignored.

    uv run scripts/reader_ratchet.py check  --labels LABELS_DIR --texts TEXTS_DIR \\
        [--textos-parquet PATH] [--baseline PATH] [--errata PATH | --no-errata]
    uv run scripts/reader_ratchet.py update --labels ... --texts ... \\
        [--force --reason "text"] [--reason "text"] [--labels-source "text"]

``update`` rewrites the baseline from the current run. It refuses when ``check``
would fail, unless ``--force`` is given together with ``--reason``. Every update
appends a history entry (date, reader commit, counts, forced flag, reason, errata
applied and errata sha256, and which norms left or entered the two gated groups
since the previous baseline).

Exit codes: 0 pass (or update written), 1 check failed or update refused,
2 usage or data error.

``LABELS_DIR`` is the teacher-batch output root (the directory holding ``labels/``
and ``summary.json``). ``TEXTS_DIR`` is the texts cache; no network is needed when
it is complete. When ``GITHUB_STEP_SUMMARY`` is set, a Markdown summary is appended.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ``scripts/`` is on sys.path when this file runs as a script; tests add it too.
import compare_teacher_reader as cmp

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "docs" / "okf" / "reader-ratchet-baseline.json"
READER_MODULES: tuple[str, ...] = (
    "src/leizilla/article_sequence.py",
    "src/leizilla/hierarchy_sequence.py",
)
SCHEMA_VERSION = 1
GATED_AGREE = "agree_closed"
GATED_DISAGREE = "disagree_closed"
REASON_NOT_FETCHED = "text not fetched"
REASON_SHA = "sha256 mismatch"
REASON_ABSENT = "not compared"


class RatchetError(Exception):
    """Bad input or an unusable baseline; reported as exit code 2."""


# --------------------------------------------------------------------------
# Scoreboard: one run of the teacher comparison
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Scoreboard:
    groups: dict[str, str]  # "item/uuid5" -> group, compared norms only
    not_compared: dict[str, str]  # "item/uuid5" -> reason, for the rest
    labelled: int
    labels_identity: Optional[dict[str, Any]]
    text_sources: dict[str, int]  # cache | parquet | ia | missing
    ia_requests: int
    errata_sha256: Optional[str] = None
    errata_total: int = 0
    errata_applied: list[dict[str, Any]] = field(default_factory=list)
    errata_stale: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {g: sum(1 for v in self.groups.values() if v == g) for g in cmp.GROUPS}

    def ids(self, group: str) -> list[str]:
        return sorted(k for k, v in self.groups.items() if v == group)

    def state(self, key: str) -> str:
        return self.groups.get(key) or self.not_compared.get(key, REASON_ABSENT)


def norm_key(item: str, uuid5: str) -> str:
    """Stable norm id. ``item`` alone is shared by many norms, so ``uuid5`` joins it."""
    return f"{item}/{uuid5}"


def read_labels_identity(labels_dir: Path) -> Optional[dict[str, Any]]:
    path = labels_dir / "summary.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "batch_ids": list(data.get("batch_ids", [])),
        "model": data.get("model"),
        "prompt_version": data.get("prompt_version"),
        "norms_ok": data.get("norms_ok"),
    }


def run_scoreboard(
    labels_dir: Path,
    texts_dir: Path,
    textos_parquet: Optional[Path] = None,
    ia: Optional[cmp.IaFetcher] = None,
    errata: Optional[cmp.Errata] = None,
) -> Scoreboard:
    if not labels_dir.is_dir():
        raise RatchetError(f"labels dir not found: {labels_dir}")
    norms = cmp.load_labelled_norms(labels_dir)
    if not norms:
        raise RatchetError(f"no labelled norms under {labels_dir}")
    corpus = cmp.compare_corpus(norms, texts_dir, textos_parquet, ia, errata)

    groups = {
        norm_key(str(r["identifier"]), str(r["uuid5"])): str(r["group"])
        for r in corpus.rows
    }
    missing = set(corpus.missing_keys)
    mismatched = set(corpus.mismatches)
    not_compared: dict[str, str] = {}
    for header, _labels in norms:
        key = norm_key(str(header["item"]), str(header["uuid5"]))
        if key in groups:
            continue
        text_key = f"{header['item']}/{header['txt_name']}"
        if text_key in missing:
            not_compared[key] = REASON_NOT_FETCHED
        elif text_key in mismatched:
            not_compared[key] = REASON_SHA
        else:
            not_compared[key] = REASON_ABSENT
    return Scoreboard(
        groups=groups,
        not_compared=not_compared,
        labelled=len(norms),
        labels_identity=read_labels_identity(labels_dir),
        text_sources=dict(corpus.sources),
        ia_requests=corpus.ia_requests,
        errata_sha256=errata.sha256 if errata is not None else None,
        errata_total=len(errata.corrections) if errata is not None else 0,
        errata_applied=corpus.errata_applied,
        errata_stale=corpus.errata_stale,
    )


def load_errata_arg(args: argparse.Namespace) -> Optional[cmp.Errata]:
    if args.no_errata:
        return None
    try:
        return cmp.load_errata(args.errata)
    except cmp.ErrataError as exc:
        raise RatchetError(str(exc)) from exc


# --------------------------------------------------------------------------
# Baseline file
# --------------------------------------------------------------------------


def load_baseline(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RatchetError(
            f"{path}: schema_version {data.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION}"
        )
    for name in ("counts", "agree_closed", "disagree_closed", "history"):
        if name not in data:
            raise RatchetError(f"{path}: missing field {name!r}")
    return data


def write_baseline(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def reader_commit() -> Optional[str]:
    return _git("rev-parse", "HEAD")


def reader_last_change() -> Optional[str]:
    return _git("log", "-1", "--format=%H", "--", *READER_MODULES)


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    lost_agree: list[tuple[str, str]]  # (norm, its state now)
    new_disagree: list[str]
    entered_agree: list[str]
    left_disagree: list[str]
    stale_errata: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.lost_agree or self.new_disagree or self.stale_errata)


def evaluate(baseline: dict[str, Any], board: Scoreboard) -> Verdict:
    base_agree = set(baseline["agree_closed"])
    base_disagree = set(baseline["disagree_closed"])
    lost = [
        (key, board.state(key))
        for key in sorted(base_agree)
        if board.groups.get(key) != GATED_AGREE
    ]
    cur_agree = set(board.ids(GATED_AGREE))
    cur_disagree = set(board.ids(GATED_DISAGREE))
    return Verdict(
        lost_agree=lost,
        new_disagree=sorted(cur_disagree - base_disagree),
        entered_agree=sorted(cur_agree - base_agree),
        left_disagree=sorted(base_disagree - cur_disagree),
        stale_errata=list(board.errata_stale),
    )


def _stale_line(entry: dict[str, Any]) -> str:
    return f"{entry['norm']} {entry['op']} line {entry['line']}: {entry['reason']}"


def _errata_line(board: Scoreboard) -> Optional[str]:
    if not board.errata_total:
        return None
    return (
        f"errata: {len(board.errata_applied)} applied, "
        f"{len(board.errata_stale)} stale, of {board.errata_total} "
        f"(sha256 {board.errata_sha256})"
    )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _baseline_counts(baseline: Optional[dict[str, Any]]) -> dict[str, int]:
    if baseline is None:
        return {g: 0 for g in cmp.GROUPS}
    return {g: int(baseline["counts"].get(g, 0)) for g in cmp.GROUPS}


def delta_rows(
    baseline: Optional[dict[str, Any]], board: Scoreboard
) -> list[tuple[str, int, int, int]]:
    before = _baseline_counts(baseline)
    after = board.counts()
    return [(g, before[g], after[g], after[g] - before[g]) for g in cmp.GROUPS]


def render_text(
    baseline: Optional[dict[str, Any]], board: Scoreboard, verdict: Optional[Verdict]
) -> str:
    lines = [
        f"{'group':<22}{'before':>8}{'after':>8}{'delta':>8}",
    ]
    for group, before, after, delta in delta_rows(baseline, board):
        lines.append(f"{group:<22}{before:>8}{after:>8}{delta:>+8}")
    lines.append(f"compared: {len(board.groups)} of {board.labelled} labelled norms")
    lines.append(f"texts: {board.text_sources}, IA requests: {board.ia_requests}")
    errata_line = _errata_line(board)
    if errata_line:
        lines.append(errata_line)
    if verdict is None:
        lines += [f"FAIL stale errata: {_stale_line(e)}" for e in board.errata_stale]
        return "\n".join(lines)
    for key, state in verdict.lost_agree:
        lines.append(f"FAIL agree_closed lost: {key} -> {state}")
    for key in verdict.new_disagree:
        lines.append(f"FAIL new disagree_closed: {key}")
    for entry in verdict.stale_errata:
        lines.append(f"FAIL stale errata: {_stale_line(entry)}")
    if not verdict.failed:
        lines.append(f"newly entered agree_closed: {len(verdict.entered_agree)}")
        lines.extend(f"  + {key}" for key in verdict.entered_agree)
    lines.append("PASS" if not verdict.failed else "FAIL")
    return "\n".join(lines)


def render_markdown(
    title: str,
    baseline: Optional[dict[str, Any]],
    board: Scoreboard,
    verdict: Optional[Verdict],
) -> str:
    lines = [
        f"## Reader ratchet — {title}",
        "",
        f"- labelled norms: {board.labelled}, compared: {len(board.groups)}",
        f"- reader commit: `{reader_commit() or 'unknown'}`",
    ]
    if board.labels_identity:
        batches = ", ".join(board.labels_identity.get("batch_ids") or [])
        lines.append(f"- labels: `{batches}`")
    errata_line = _errata_line(board)
    if errata_line:
        lines.append(f"- {errata_line}")
    lines += ["", "| group | before | after | delta |", "|---|---:|---:|---:|"]
    for group, before, after, delta in delta_rows(baseline, board):
        lines.append(f"| {group} | {before} | {after} | {delta:+d} |")
    if verdict is None and board.errata_stale:
        lines.append("")
        lines.append("**FAIL**")
        lines += [f"- stale errata: {_stale_line(e)}" for e in board.errata_stale]
    if verdict is not None:
        lines.append("")
        if verdict.failed:
            lines.append("**FAIL**")
            lines += [
                f"- agree_closed lost: `{key}` -> {state}"
                for key, state in verdict.lost_agree
            ]
            lines += [f"- new disagree_closed: `{key}`" for key in verdict.new_disagree]
            lines += [f"- stale errata: {_stale_line(e)}" for e in verdict.stale_errata]
        else:
            lines.append(
                f"**PASS** — {len(verdict.entered_agree)} newly entered agree_closed"
            )
            lines += [f"- `{key}`" for key in verdict.entered_agree[:50]]
    return "\n".join(lines) + "\n"


def write_step_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(text)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def build_baseline(
    board: Scoreboard,
    previous: Optional[dict[str, Any]],
    labels_source: Optional[str],
    history_entry: dict[str, Any],
) -> dict[str, Any]:
    identity = board.labels_identity or {}
    prev_labels = (previous or {}).get("labels", {})
    batch_ids = identity.get("batch_ids") or prev_labels.get("batch_ids") or []
    history = list((previous or {}).get("history", [])) + [history_entry]
    return {
        "schema_version": SCHEMA_VERSION,
        "date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "reader_commit": reader_commit(),
        "reader_last_change": reader_last_change(),
        "labels": {
            "identifier": ",".join(batch_ids) if batch_ids else None,
            "batch_ids": batch_ids,
            "norms": board.labelled,
            "model": identity.get("model") or prev_labels.get("model"),
            "prompt_version": identity.get("prompt_version")
            or prev_labels.get("prompt_version"),
            "source": labels_source
            if labels_source is not None
            else prev_labels.get("source"),
            "errata_applied": len(board.errata_applied),
            "errata_sha256": board.errata_sha256,
        },
        "counts": board.counts(),
        "agree_closed": board.ids(GATED_AGREE),
        "disagree_closed": board.ids(GATED_DISAGREE),
        "history": history,
    }


def cmd_check(args: argparse.Namespace) -> int:
    baseline = load_baseline(args.baseline)
    if baseline is None:
        raise RatchetError(f"no baseline at {args.baseline}; create it with update")
    errata = load_errata_arg(args)
    board = run_scoreboard(args.labels, args.texts, args.textos_parquet, errata=errata)
    verdict = evaluate(baseline, board)
    base_labels = baseline.get("labels") or {}
    base_ids = base_labels.get("identifier")
    cur_ids = ",".join((board.labels_identity or {}).get("batch_ids") or [])
    if base_ids and cur_ids and base_ids != cur_ids:
        print(
            f"note: labels {cur_ids} differ from the baseline's {base_ids}; "
            "the comparison is not like-for-like"
        )
    if base_labels.get("errata_sha256") != board.errata_sha256:
        print(
            "note: errata file differs from the baseline's "
            f"(baseline {base_labels.get('errata_sha256')}, "
            f"now {board.errata_sha256})"
        )
    print(render_text(baseline, board, verdict))
    write_step_summary(render_markdown("check", baseline, board, verdict))
    return 1 if verdict.failed else 0


def cmd_update(args: argparse.Namespace) -> int:
    if args.force and not args.reason:
        raise RatchetError("--force requires --reason")
    previous = load_baseline(args.baseline)
    errata = load_errata_arg(args)
    board = run_scoreboard(args.labels, args.texts, args.textos_parquet, errata=errata)
    verdict = evaluate(previous, board) if previous is not None else None
    if board.errata_stale:
        # Not overridable by --force: a stale correction is a data error to fix.
        print(render_text(previous, board, verdict))
        print(
            "update refused: stale teacher-label errata; fix or remove the entries "
            f"in {args.errata} (--force does not apply)"
        )
        write_step_summary(render_markdown("update refused", previous, board, verdict))
        return 1
    if verdict is not None and verdict.failed and not args.force:
        print(render_text(previous, board, verdict))
        print('update refused: check fails; rerun with --force --reason "..."')
        write_step_summary(render_markdown("update refused", previous, board, verdict))
        return 1

    if previous is None:
        entry_reason = args.reason or "initial baseline"
        changes: dict[str, list[str]] = {}
    else:
        assert verdict is not None
        entry_reason = args.reason
        changes = {
            "entered_agree_closed": verdict.entered_agree,
            "left_agree_closed": [k for k, _ in verdict.lost_agree],
            "entered_disagree_closed": verdict.new_disagree,
            "left_disagree_closed": verdict.left_disagree,
        }
    history_entry = {
        "date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "reader_commit": reader_commit(),
        "forced": bool(args.force),
        "reason": entry_reason,
        "counts": board.counts(),
        "errata_applied": len(board.errata_applied),
        "errata_sha256": board.errata_sha256,
        **changes,
    }
    new = build_baseline(board, previous, args.labels_source, history_entry)
    write_baseline(args.baseline, new)
    print(render_text(previous, board, verdict))
    print(f"baseline written: {args.baseline}")
    write_step_summary(render_markdown("update", previous, board, verdict))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "update"):
        p = sub.add_parser(name)
        p.add_argument("--labels", type=Path, required=True, help="labels root")
        p.add_argument("--texts", type=Path, required=True, help="texts cache dir")
        p.add_argument(
            "--textos-parquet",
            type=Path,
            default=None,
            help="published textos.parquet, checked before any IA fetch",
        )
        p.add_argument(
            "--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline JSON"
        )
        p.add_argument(
            "--errata",
            type=Path,
            default=cmp.DEFAULT_ERRATA,
            help="teacher-label errata JSON",
        )
        p.add_argument(
            "--no-errata",
            action="store_true",
            help="compare the teacher labels as they are (no corrections)",
        )
        if name == "update":
            p.add_argument("--force", action="store_true")
            p.add_argument("--reason", default=None, help="recorded in history")
            p.add_argument(
                "--labels-source",
                default=None,
                help="where the labels come from (kept from baseline if omitted)",
            )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return cmd_check(args)
        return cmd_update(args)
    except RatchetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
