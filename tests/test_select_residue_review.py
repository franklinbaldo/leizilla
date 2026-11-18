"""Residue review selection (``scripts/select_residue_review.py``): offline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import select_residue_review as srr  # noqa: E402

P = srr.PREFIX


def outcome(level: str, defect: str, status: str = "own", line: int = 1) -> Any:
    return {
        "level": level,
        "status": status,
        "defects": [defect],
        "mark": {"line": line},
        "reader": None,
    }


def test_outcome_class() -> None:
    lines = ["texto", "  III  ", "Art. 3"]
    assert srr.outcome_class(outcome("art", "status_differs"), lines) == "art_status"
    assert (
        srr.outcome_class(outcome("art", "reader_extra", "quoted"), lines)
        == "art_extra_quoted"
    )
    assert srr.outcome_class(outcome("art", "reader_extra", "own"), lines) is None
    assert (
        srr.outcome_class(outcome("inc", "reader_extra", "quoted"), lines)
        == "inc_extra_quoted"
    )
    assert (
        srr.outcome_class(outcome("inc", "reader_misses", line=2), lines)
        == "inc_miss_bare"
    )
    assert srr.outcome_class(outcome("inc", "reader_misses", line=3), lines) is None
    assert srr.outcome_class(outcome("item", "reader_extra"), lines) == "item_extra"
    assert srr.norm_classes([outcome("item", "reader_extra")], lines) == {
        "item_extra": 1
    }


def test_reference_classes() -> None:
    none = {"devices": [["par", "1", "", 0, 5]]}
    assert srr.reference_classes(none) == ["implicit_single"]
    dup = {"devices": [["art", "1", "", 0, 1], ["art", "1", "", 0, 90]]}
    assert srr.reference_classes(dup) == ["dup_copy"]
    quoted_only = {"devices": [["art", "1", "", 1, 1]]}
    assert srr.reference_classes(quoted_only) == ["implicit_single"]
    fine = {"devices": [["art", "1", "", 0, 1], ["art", "2", "", 0, 9]]}
    assert srr.reference_classes(fine) == []


def test_select_is_deterministic_and_respects_parts() -> None:
    ids = [f"{P}lei-{n:05d}" for n in range(1, 40)]
    classes = {i: {"inc_extra_own": 1} for i in ids[:20]}
    classes[ids[0]] = {"inc_extra_own": 2, "item_extra": 1}
    usable = {i: 1 for i in ids}
    usable[ids[3]] = 9  # too many parts
    kwargs: dict[str, Any] = dict(
        classes=classes,
        ref_classes={ids[30]: ["implicit_single"]},
        flagged={ids[35], ids[36]},
        usable=usable,
        named=("lei-00001", "lei-00004"),
        quotas=(("inc_extra_own", 3), ("item_extra", 1), ("implicit_single", 2)),
    )
    a, dropped = srr.select(seed="s1", **kwargs)
    b, _ = srr.select(seed="s1", **kwargs)
    assert a == b
    assert dropped == {ids[3]: "9 parts"}
    assert ids[3] not in a
    assert {ids[35], ids[36], ids[0]} <= set(a)  # flagged and named
    assert a[ids[35]] == ["flagged"]
    assert ids[30] in a and "implicit_single" in a[ids[30]]
    # 2 flagged + 1 named (lei-00004 dropped) + 3 inc + 1 item (ids[0] is named: the
    # item_extra pool is then empty) + 1 implicit
    assert sum("inc_extra_own" in r for r in a.values()) == 3


def test_select_drops_text_changed_in_layer() -> None:
    i = f"{P}lc-00001"
    chosen, dropped = srr.select(
        classes={},
        ref_classes={},
        flagged={i},
        usable={},
        seed="s",
        named=(),
        quotas=(),
    )
    assert chosen == {}
    assert "layer" in dropped[i]


def test_canary_sources() -> None:
    agree = {f"{P}lei-{n:05d}" for n in range(1, 30)}
    closing = {i: 100 for i in agree}
    closing[f"{P}lei-00001"] = 5  # too short
    got = srr.canary_sources(
        agree_all=agree,
        closing=closing,
        exclude={f"{P}lei-00002"},
        seed="s",
        count=10,
    )
    assert len(got) == 10
    assert f"{P}lei-00001" not in got and f"{P}lei-00002" not in got
    assert got == srr.canary_sources(
        agree_all=agree,
        closing=closing,
        exclude={f"{P}lei-00002"},
        seed="s",
        count=10,
    )
