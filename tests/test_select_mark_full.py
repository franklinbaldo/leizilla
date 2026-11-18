"""Whole-layer mark selection (``scripts/select_mark_full.py``): offline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import select_mark_full as smf  # noqa: E402

from leizilla import teacher_batch as tb  # noqa: E402


def row(i: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": i,
        "tipo": "lei",
        "source": "ia",
        "sha": f"sha-{i}",
        "nonblank": 10,
        "chars": 100,
        "parts": 1,
        "median": 30.0,
        "p95": 80.0,
        "max": 100,
        "share200": 0.0,
    }
    base.update(kw)
    return base


def test_percentile_and_source() -> None:
    assert smf.percentile([1, 2, 3, 4], 50) == 2.5
    assert smf.percentile([7], 95) == 7
    assert smf.source_of(None) == "ia"
    assert smf.source_of("kreuzberg+paddleocr (re-OCR)") == "own-reocr"
    assert smf.source_of("tesseract 5.3") == "own-tesseract"
    assert smf.source_of("pdf-to-hocr (x)") == "pdf-text"


def test_profile_record_lengths() -> None:
    text = "Art. 1\n\n" + "x" * 250 + "\nArt. 2"
    rec = tb.TextoRecord(
        ref=tb.NormRef(
            item="i", fonte="f", tipo="lei", numero=1, uuid5="u", txt_name="t"
        ),
        text=text,
        text_sha256="s",
        ocr_motor=None,
        texto_id="lei-1",
    )
    p = smf.profile_record(rec)
    assert p["nonblank"] == 3
    assert p["max"] == 250
    assert p["parts"] == 1
    assert abs(p["share200"] - 1 / 3) < 1e-9


def test_classify_priorities_and_changed_reference() -> None:
    rows = [
        row("ref-same"),
        row("ref-changed"),
        row("big", parts=9),
        row("long-max", max=201),
        row("long-p95", p95=151.0),
        row("ok"),
        row("ref-big", parts=12),
    ]
    out = smf.classify(
        rows,
        reference_ids=["ref-same", "ref-changed", "ref-big", "gone"],
        reference_sha={
            "ref-same": "sha-ref-same",
            "ref-changed": "old",
            "ref-big": "sha-ref-big",
        },
        max_parts=8,
        long_line=200,
        long_p95=150,
    )
    assert [r["id"] for r in out["reference"]] == ["ref-same", "ref-big"]
    assert [r["id"] for r in out["changed"]] == ["ref-changed"]
    assert out["missing"] == ["gone"]
    assert [r["id"] for r in out["parts"]] == ["big"]
    assert [r["id"] for r in out["longlines"]] == ["long-max", "long-p95"]
    assert [r["id"] for r in out["main"]] == ["ref-changed", "ok"]


def test_split_in_two_is_deterministic_and_balanced() -> None:
    rows = [row(f"n{i}", chars=i * 10) for i in range(7)]
    a, b = smf.split_in_two(rows)
    assert [r["id"] for r in a] == ["n0", "n2", "n4", "n6"]
    assert [r["id"] for r in b] == ["n1", "n3", "n5"]
    assert smf.split_in_two(list(reversed(rows))) == (a, b)


def test_rendicao_restricts_the_layer_and_names_the_files(tmp_path: Path) -> None:
    import duckdb

    textos = tmp_path / "textos.parquet"
    con = duckdb.connect()
    con.execute(
        "create table t as select * from (values "
        "('a', 'compilada'), ('b', 'original'), ('c', NULL)) v(texto_id, rendicao)"
    )
    con.execute(f"copy t to '{textos}' (format parquet)")
    got = smf.rendicao_of(textos)
    assert got == {"a": "compilada", "b": "original", "c": "original"}
    # no rendicao column (an old layer): nothing is filtered by it, nothing breaks
    old = tmp_path / "old.parquet"
    con.execute(f"copy (select texto_id from t) to '{old}' (format parquet)")
    assert smf.rendicao_of(old) == {}
