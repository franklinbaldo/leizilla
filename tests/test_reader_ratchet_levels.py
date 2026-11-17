"""Offline tests for scripts/reader_ratchet_levels.py (per-level ratchet gate)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import reader_ratchet_levels as rl  # noqa: E402

TEXT = "Art. 1º Texto.\n§ 1º Um.\nI - dois;\nII - tres.\n"
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


def _dev(kind: str, n: str, line: int, quoted: bool = False) -> dict[str, Any]:
    starts = [0]
    starts += [i + 1 for i, ch in enumerate(TEXT) if ch == "\n"]
    return {
        "kind": kind,
        "n": n,
        "sufixo": "",
        "quoted": quoted,
        "marker": "",
        "offset": starts[line - 1],
        "line": line,
        "path": "",
    }


REF_ROWS = [
    ["art", "1", "", 0, 0],
    ["par", "1", "", 0, 15],
    ["inc", "1", "", 0, 24],
    ["inc", "2", "", 0, 34],
]


def _ref(flags: list[str] | None = None) -> rl.Reference:
    rec = {
        "item": "i",
        "uuid5": "u",
        "tipo": "lei",
        "numero": "1",
        "text_sha256": SHA,
        "variant": "as-is",
        "flags": flags or [],
        "devices": REF_ROWS,
    }
    return rl.Reference({}, {"n1": rec}, {SHA: TEXT}, "refsha")


def _reader(devs: list[dict[str, Any]]) -> Any:
    return lambda text, tipo, numero: devs


PERFECT = [
    _dev("art", "1", 1),
    _dev("par", "1", 2),
    _dev("inc", "1", 3),
    _dev("inc", "2", 4),
]


def test_perfect_reader_agrees_at_every_level_with_devices() -> None:
    board = rl.run_board(_ref(), reader=_reader(PERFECT))
    assert board.agree("art") == ["n1"]
    assert board.agree("inc") == ["n1"]
    assert board.groups["ali"] == {}  # the reference lacks the level: no unit


def test_missing_and_extra_devices_break_the_level() -> None:
    missing = rl.run_board(_ref(), reader=_reader(PERFECT[:3]))
    assert missing.groups["inc"]["n1"] == "reader_misses"
    assert missing.groups["par"]["n1"] == "agree"
    extra = rl.run_board(_ref(), reader=_reader(PERFECT + [_dev("ali", "a", 4)]))
    assert extra.groups["ali"]["n1"] == "reader_extra"


def test_flagged_norms_are_outside_the_gate() -> None:
    board = rl.run_board(_ref(["suspect_number"]), reader=_reader([]))
    assert board.flagged == ["n1"]
    assert all(not g for g in board.groups.values())


def test_text_sha_mismatch_is_not_compared() -> None:
    ref = _ref()
    ref.texts[SHA] = TEXT + "x"
    board = rl.run_board(ref, reader=_reader(PERFECT))
    assert "n1" in board.not_compared


def test_verdict_fails_only_when_an_agree_unit_leaves() -> None:
    good = rl.run_board(_ref(), reader=_reader(PERFECT))
    baseline = {"agree": {lv: good.agree(lv) for lv in rl.LEVELS}}
    assert not rl.evaluate(baseline, good).failed
    worse = rl.run_board(_ref(), reader=_reader(PERFECT[:3]))
    verdict = rl.evaluate(baseline, worse)
    assert verdict.failed
    assert verdict.lost == [("inc", "n1", "reader_misses")]
    # a better reader than the baseline only enters units
    base_low = {"agree": {lv: [] for lv in rl.LEVELS}}
    better = rl.evaluate(base_low, good)
    assert not better.failed
    assert ("par", "n1") in better.entered


def _corr(**kw: Any) -> dict[str, Any]:
    base = {
        "norm": "n1",
        "text_sha256": SHA,
        "kind": "inc",
        "line": 4,
        "evidence": "II - tres",
        "reason": "r",
        "verified_by": "leitura do texto",
        "date": "2026-11-17",
    }
    base.update(kw)
    return base


def test_errata_ops_apply() -> None:
    add = _corr(op="add_device", kind="ali", n="a", line=4, evidence="tres")
    rows, applied, stale = rl.apply_corrections(REF_ROWS, [add], TEXT, SHA)
    assert applied and not stale
    assert ["ali", "a", "", 0, TEXT.index("tres")] in rows
    rem = _corr(op="remove_device")
    rows, applied, stale = rl.apply_corrections(REF_ROWS, [rem], TEXT, SHA)
    assert applied and len(rows) == 3
    setq = _corr(op="set_device", set={"quoted": True, "n": "9"})
    rows, applied, stale = rl.apply_corrections(REF_ROWS, [setq], TEXT, SHA)
    assert ["inc", "9", "", 1, 34] in rows
    assert REF_ROWS[3][3] == 0  # the input rows are not mutated


def test_errata_go_stale() -> None:
    wrong_sha = _corr(op="remove_device", text_sha256="0" * 64)
    wrong_line = _corr(op="remove_device", evidence="not here")
    ambiguous = _corr(op="remove_device", line=3, kind="par")
    for c in (wrong_sha, wrong_line, ambiguous):
        rows, applied, stale = rl.apply_corrections(REF_ROWS, [c], TEXT, SHA)
        assert stale and not applied and rows == REF_ROWS


def test_stale_errata_fail_the_gate() -> None:
    errata = rl.Errata([_corr(op="remove_device", evidence="not here")], "s")
    board = rl.run_board(_ref(), errata, reader=_reader(PERFECT))
    verdict = rl.evaluate(None, board)
    assert verdict.failed and verdict.stale


def test_errata_change_the_reference() -> None:
    # the reference wrongly lacks inc II: an erratum adds it and the reader agrees
    rows = [r for r in REF_ROWS if r[:2] != ["inc", "2"]]
    ref = _ref()
    ref.norms["n1"]["devices"] = rows
    assert rl.run_board(ref, reader=_reader(PERFECT)).groups["inc"]["n1"] != "agree"
    errata = rl.Errata([_corr(op="add_device", n="2", evidence="II -")], "s")
    board = rl.run_board(ref, errata, reader=_reader(PERFECT))
    assert board.groups["inc"]["n1"] == "agree"
    assert len(board.errata_applied) == 1


def test_committed_baseline_passes_with_the_live_reader() -> None:
    ref = rl.load_reference(rl.DEFAULT_REFERENCE)
    errata = rl.load_errata(rl.DEFAULT_ERRATA)
    baseline = rl.load_baseline(rl.DEFAULT_BASELINE)
    assert baseline is not None
    board = rl.run_board(ref, errata)
    verdict = rl.evaluate(baseline, board)
    assert not verdict.failed, verdict.lost[:5]
    assert baseline["reference_sha256"] == ref.sha256


def test_cli_check_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert rl.main(["check"]) == 0
    assert rl.main(["check", "--baseline", "/nonexistent/baseline.json"]) == 2
