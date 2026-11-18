"""Review run -> errata candidates (``scripts/review_to_errata.py``): synthetic data."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import reader_ratchet_levels as rrl  # noqa: E402
import review_to_errata as rte  # noqa: E402

LINES = [
    "LEI Nº 1",  # 1
    "Art. 1º Fica criado o fundo:",  # 2
    "I - primeiro;",  # 3
    "II - segundo;",  # 4
    "III - terceiro.",  # 5
    "Art. 2º Esta Lei entra em vigor.",  # 6
]
TEXT = "\n".join(LINES)
SHA = rrl.sha256_text(TEXT)


def off(line: int, col: int = 0) -> int:
    return sum(len(x) + 1 for x in LINES[: line - 1]) + col


def row(kind: str, n: str, line: int, quoted: int = 0, sufixo: str = "") -> list[Any]:
    return [kind, n, sufixo, quoted, off(line)]


ART1, ART2 = row("art", "1", 2), row("art", "2", 6)
INC1, INC2, INC3 = row("inc", "1", 3), row("inc", "2", 4), row("inc", "3", 5)
BASE = [ART1, INC1, INC2, INC3, ART2]


def review(
    adjustments: Optional[list[dict[str, Any]]] = None, **extra: Any
) -> dict[str, Any]:
    return {
        "texto_id": "leizilla-raw-ro-casacivil-lei-00001",
        "text_sha256": SHA,
        "verdict": "ajuste" if adjustments else "ok",
        "adjustments": adjustments or [],
        "dropped": [],
        "model": "claude-sonnet-5-5",
        "reader": {"articles": [[2, "1", False], [6, "2", False]]},
        **extra,
    }


def adj(op: str, line: int, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "op": op,
        "line": line,
        "number": None,
        "suffix": None,
        "level": None,
        "quoted": None,
        "evidence": "x",
        "reason": "because",
    }
    base.update(kw)
    return base


def classify(
    rev: dict[str, Any], ref_rows: list[list[Any]], reader_rows: list[list[Any]]
) -> dict[str, Any]:
    reader = rrl.devices_from_rows(reader_rows, TEXT)
    return rte.classify_norm(rev, TEXT, ref_rows, reader, date="2026-11-19")


def cats(result: dict[str, Any]) -> list[str]:
    return [r["category"] for r in result["rows"]]


def test_canon_numbers() -> None:
    assert rte.canon("inc", "2") == "II"
    assert rte.canon("inc", "ii") == "II"
    assert rte.canon("ali", "2") == "b"
    assert rte.canon("par", "único") == "unico"
    assert rte.canon("art", "5", "A") == "5-A"
    assert rte._same_number("inc", "IV", "4")


def test_agreement_is_silent() -> None:
    assert classify(review(), BASE, BASE)["rows"] == []


def test_adjustment_equal_to_reference_confirms_a_reader_defect() -> None:
    reader = [ART1, INC1, INC3, ART2]  # misses II
    rev = review([adj("add_node", 4, level="inciso", number="II")])
    result = classify(rev, BASE, reader)
    assert cats(result) == [rte.CONFIRMS]
    assert result["rows"][0]["pattern"].startswith("reader_misses|inc|R -|")
    assert result["proposals"] == []


def test_remove_node_confirms_an_extra() -> None:
    ref = [ART1, INC1, INC2, ART2]
    rev = review([adj("remove_node", 5, level="inciso")])
    assert cats(classify(rev, ref, BASE)) == [rte.CONFIRMS]


def test_silence_where_reader_differs_is_a_reference_error_candidate() -> None:
    ref = [ART1, INC1, INC2, ART2]  # no III in the reference; the reader has it
    result = classify(review(), ref, BASE)
    assert cats(result) == [rte.REFERENCE_ERROR]
    (entry,) = result["proposals"]
    assert entry["op"] == "add_device" and entry["kind"] == "inc"
    assert entry["n"] == "3" and entry["line"] == 5
    assert entry["verified_by"] == "sonnet-review"
    assert entry["text_sha256"] == SHA
    assert entry["evidence"].startswith("III -")
    # applying it makes the reference equal the reader
    rows, applied, stale = rrl.apply_corrections(ref, [entry], TEXT, SHA)
    assert not stale and len(applied) == 1
    assert [r for r in rows if r[0] == "inc"] == [INC1, INC2, INC3]


def test_missing_in_reader_proposes_remove_device() -> None:
    reader = [ART1, INC1, INC3, ART2]
    result = classify(review(), BASE, reader)
    assert cats(result) == [rte.REFERENCE_ERROR]
    (entry,) = result["proposals"]
    assert entry["op"] == "remove_device" and entry["line"] == 4
    rows, _, stale = rrl.apply_corrections(BASE, [entry], TEXT, SHA)
    assert not stale and INC2 not in rows


def test_number_difference_three_ways() -> None:
    reader = [ART1, INC1, INC2, row("inc", "4", 5), ART2]  # reader read III as IV
    nothing = classify(review(), BASE, reader)
    assert cats(nothing) == [rte.REFERENCE_ERROR]
    (entry,) = nothing["proposals"]
    assert entry["op"] == "set_device" and entry["set"]["n"] == "4"
    to_reference = classify(
        review([adj("set_node_number", 5, level="inciso", number="III")]), BASE, reader
    )
    assert cats(to_reference) == [rte.CONFIRMS]
    third = classify(
        review([adj("set_node_number", 5, level="inciso", number="V")]), BASE, reader
    )
    assert cats(third) == [rte.THIRD] and third["proposals"] == []


def test_status_difference_set_quoted() -> None:
    ref = [ART1, INC1, INC2, row("inc", "3", 5, quoted=1), ART2]
    result = classify(review(), ref, BASE)
    (entry,) = result["proposals"]
    assert entry["set"] == {"quoted": False}
    confirmed = classify(
        review(
            [
                adj("remove_node", 5, level="inciso"),
                adj("add_node", 5, level="inciso", number="III", quoted=True),
            ]
        ),
        ref,
        BASE,
    )
    assert cats(confirmed) == [rte.CONFIRMS]


def test_adjustment_where_reader_and_reference_agree_is_a_third_opinion() -> None:
    rev = review([adj("set_number", 6, number="3")])
    result = classify(rev, BASE, BASE)
    assert cats(result) == [rte.THIRD]
    assert result["rows"][0]["defect"] == "contradicts_both"


def test_unverified_and_partial_are_inconclusive() -> None:
    ref = [ART1, INC1, INC2, ART2]
    for flag in ({"unverified": True}, {"partial": True}):
        result = classify(review(**flag), ref, BASE)
        assert cats(result) == [rte.INCONCLUSIVE] and result["proposals"] == []


def test_dropped_adjustment_at_the_spot_is_inconclusive() -> None:
    ref = [ART1, INC1, INC2, ART2]
    rev = review(dropped=[{"op": "remove_node", "line": 5, "reason": "x"}])
    assert cats(classify(rev, ref, BASE)) == [rte.INCONCLUSIVE]


def test_kind_differs_proposes_two_entries() -> None:
    ref = [ART1, INC1, INC2, row("item", "1", 5), ART2]
    result = classify(review(), ref, BASE)
    assert cats(result) == [rte.REFERENCE_ERROR]
    assert sorted(e["op"] for e in result["proposals"]) == [
        "add_device",
        "remove_device",
    ]


def make_ref(rows: list[list[Any]]) -> rrl.Reference:
    rec = {
        "item": "i",
        "uuid5": "u",
        "tipo": "lei",
        "numero": 1,
        "text_sha256": SHA,
        "variant": "as-is",
        "flags": [],
        "devices": rows,
    }
    return rrl.Reference(
        meta={},
        norms={"leizilla-raw-ro-casacivil-lei-00001": rec},
        texts={SHA: TEXT},
        sha256=None,
    )


def test_run_and_outputs(tmp_path: Path) -> None:
    ref_rows = [ART1, INC1, INC2, ART2]  # reference lacks III
    ref = make_ref(ref_rows)
    canary = review(canary=True)
    unknown = review()
    unknown["texto_id"] = "leizilla-raw-ro-casacivil-lei-00002"
    result = rte.run(
        [review(), canary, unknown],
        ref,
        None,
        date="2026-11-19",
        reader=lambda text, tipo, numero: rrl.devices_from_rows(BASE, text),
    )
    assert result["counts"] == {rte.REFERENCE_ERROR: 1}
    assert len(result["proposals"]) == 1
    assert result["skipped"] == {
        "leizilla-raw-ro-casacivil-lei-00002": "not in the reference"
    }
    rte.write_outputs(tmp_path, result, "2026-11-19")
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["proposed_errata"] == 1
    proposed = json.loads(
        (tmp_path / "proposed-mark-reference-errata.json").read_text()
    )
    assert proposed["schema_version"] == rrl.SCHEMA_VERSION
    assert proposed["corrections"][0]["verified_by"] == "sonnet-review"
    tsv = (tmp_path / "review_errata.tsv").read_text().splitlines()
    assert tsv[0].split("\t")[:2] == ["norm", "category"]
    assert tsv[1].split("\t")[1] == rte.REFERENCE_ERROR


def test_run_skips_a_reader_that_changed() -> None:
    ref = make_ref([ART1, INC1, INC2, ART2])
    changed = review(reader={"articles": [[2, "1", False]]})
    result = rte.run(
        [changed],
        ref,
        None,
        date="2026-11-19",
        reader=lambda text, tipo, numero: rrl.devices_from_rows(BASE, text),
    )
    assert "differ" in next(iter(result["skipped"].values()))
    assert result["rows"] == []


def test_run_skips_a_text_that_is_not_the_references() -> None:
    ref = make_ref([ART1, INC1, INC2, ART2])
    result = rte.run(
        [review(text_sha256="zzz")],
        ref,
        None,
        date="2026-11-19",
        reader=lambda text, tipo, numero: rrl.devices_from_rows(BASE, text),
    )
    assert "differs" in next(iter(result["skipped"].values()))


def test_flagged_norms_are_skipped_unless_asked_or_settled() -> None:
    ref = make_ref([ART1, INC1, INC2, ART2])  # reference lacks III
    ref.norms["leizilla-raw-ro-casacivil-lei-00001"]["flags"] = ["suspect_sequence"]
    reader = lambda text, tipo, numero: rrl.devices_from_rows(BASE, text)  # noqa: E731
    skipped = rte.run([review()], ref, None, date="2026-11-19", reader=reader)
    assert "suspect flags" in next(iter(skipped["skipped"].values()))
    assert skipped["rows"] == []
    asked = rte.run(
        [review()], ref, None, date="2026-11-19", reader=reader, include_flagged=True
    )
    assert asked["counts"] == {rte.REFERENCE_ERROR: 1}
    clear = {
        "norm": "leizilla-raw-ro-casacivil-lei-00001",
        "text_sha256": SHA,
        "op": "clear_suspect",
        "flags": ["suspect_sequence"],
        "line": 2,
        "evidence": "Art. 1º",
        "reason": "settled",
        "verified_by": "x",
        "date": "2026-11-19",
    }
    settled = rte.run(
        [review()],
        ref,
        rrl.Errata([clear], "s"),
        date="2026-11-19",
        reader=reader,
    )
    assert settled["counts"] == {rte.REFERENCE_ERROR: 1}
