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
    board.textos_given = False  # offline subset: only the 300 committed texts
    verdict = rl.evaluate(baseline, board)
    assert not verdict.failed, verdict.lost[:5]
    assert baseline["reference_sha256"] == ref.sha256
    assert len(ref.texts) == 300 < len(ref.norms)
    assert len(board.not_compared) == len(ref.norms) - len(ref.texts)


def test_cli_check_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert rl.main(["check"]) == 0
    assert rl.main(["check", "--baseline", "/nonexistent/baseline.json"]) == 2


def _write_parquet(
    path: Path, texts: list[str], sha_col: list[str] | None = None
) -> None:
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE TABLE t (texto VARCHAR, sha256_texto VARCHAR)")
    for i, text in enumerate(texts):
        sha = (sha_col or [hashlib.sha256(t.encode()).hexdigest() for t in texts])[i]
        con.execute("INSERT INTO t VALUES (?, ?)", [text, sha])
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    con.close()


def test_textos_parquet_is_matched_by_recomputed_sha(tmp_path: Path) -> None:
    other = "Art. 2º Outro.\n"
    # the sha256 column of the second row lies: the text is matched by its own hash
    parquet = tmp_path / "textos.parquet"
    _write_parquet(parquet, [TEXT, other], [SHA, SHA])
    found = rl.read_textos_parquet(parquet, {SHA, "f" * 64})
    assert found == {SHA: TEXT}


def test_reference_without_committed_text_uses_textos(tmp_path: Path) -> None:
    ref = _ref()
    bare = rl.Reference(ref.meta, ref.norms, {}, ref.sha256)
    assert "n1" in rl.run_board(bare, reader=_reader(PERFECT)).not_compared
    parquet = tmp_path / "textos.parquet"
    _write_parquet(parquet, [TEXT])
    full = rl.with_textos(bare, parquet)
    assert full.texts == {SHA: TEXT}
    assert rl.run_board(full, reader=_reader(PERFECT)).agree("art") == ["n1"]


def test_not_comparable_threshold() -> None:
    norms = {}
    for i in range(100):
        rec = dict(_ref().norms["n1"])
        rec["text_sha256"] = SHA if i < 97 else f"missing{i}"
        norms[f"n{i}"] = rec
    ref = rl.Reference({}, norms, {SHA: TEXT}, "s")
    board = rl.run_board(ref, reader=_reader(PERFECT))
    assert len(board.not_compared) == 3
    # 3 of 100 > 2%: fails; the units of the missing norms are not "lost" though
    verdict = rl.evaluate({"agree": {lv: [] for lv in rl.LEVELS}}, board)
    assert verdict.too_many_not_comparable and verdict.failed and not verdict.lost
    assert not rl.evaluate({}, board, max_not_comparable=0.05).failed
    board.textos_given = False
    assert not rl.evaluate({}, board).failed  # offline subset: not enforced
    # a baseline agree unit of a norm that cannot be compared is not a loss
    base = {"agree": {"art": ["n99"]}}
    assert rl.evaluate(base, board).lost == []


def test_split_is_stable_and_about_a_fifth() -> None:
    ids = [f"leizilla-raw-ro-casacivil-lei-{i:05d}" for i in range(2000)]
    first = [rl.split_of(i) for i in ids]
    assert first == [rl.split_of(i) for i in ids]
    share = first.count("test") / len(ids)
    assert 0.17 < share < 0.23


def test_table_by_split() -> None:
    board = rl.run_board(_ref(), reader=_reader(PERFECT[:3]))
    everything = rl.table(board)
    assert everything["inc"]["units"] == 1
    none = rl.table(board, lambda n: False)
    assert none["inc"]["units"] == 0 and none["inc"].get("agree", 0) == 0
    only = rl.table(board, lambda n: True)
    assert only == everything


def test_cli_textos_and_update_guards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # update without --textos is a usage error: it would shrink the baseline
    assert rl.main(["update", "--baseline", str(tmp_path / "b.json")]) == 2
    # a --textos that holds none of the reference texts: too many not comparable
    parquet = tmp_path / "textos.parquet"
    _write_parquet(parquet, [TEXT])
    assert rl.main(["check", "--textos", str(parquet)]) == 1
    assert "FAIL not comparable" in capsys.readouterr().out
    assert rl.main(["check", "--textos", str(tmp_path / "nope.parquet")]) == 2
