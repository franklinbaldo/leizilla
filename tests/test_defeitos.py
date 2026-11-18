"""Defeitos da fonte: a lista commitada, a fila nao-fecha e a coluna ``defeito_fonte``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from leizilla import defeitos, reocr, textlayer
from test_reocr import KZ, MANY_OPEN, _row

SHA_LEI_1296 = "7d46ebb7e564fb3aae6f3e665f1da3e6cdfe04e678c2e8225dd25f457d500065"


def _entry(row: dict[str, Any], **over: Any) -> dict[str, Any]:
    entry = {
        "texto_id": row["texto_id"],
        "sha256_fonte": row["sha256_fonte"],
        "tipo": "arquivo-incompleto",
        "nota": "O arquivo oficial salta do art. 2º para o art. 6º.",
        "motivo": "falta uma folha",
        "evidencia": "3 páginas lidas",
        "data": "2026-11-18",
        "verificado_por": "olho",
    }
    entry.update(over)
    return entry


def _write(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "defeitos.json"
    path.write_text(
        json.dumps({"schema_version": 1, "defeitos": entries}), encoding="utf-8"
    )
    return path


def test_committed_list_is_valid_and_names_lei_1296() -> None:
    loaded = defeitos.load_defeitos(defeitos.DEFAULT_PATH)
    entry = loaded["leizilla-raw-ro-casacivil-lei-01296"]
    assert entry["sha256_fonte"] == SHA_LEI_1296
    assert entry["tipo"] == "arquivo-incompleto"
    assert "art. 6º" in entry["nota"]


def test_queue_skips_a_registered_defect_and_counts_it() -> None:
    row = _row(1296, MANY_OPEN)
    other = _row(7, MANY_OPEN)
    stats = reocr.ReocrStats()
    queue = reocr.select_queue(
        [row, other],
        [],
        kreuzberg_version=KZ,
        stats=stats,
        defeitos={row["texto_id"]: _entry(row)},
    )
    assert [r["texto_id"] for r in queue] == [other["texto_id"]]
    assert stats.defeitos_da_fonte == 1
    assert stats.nao_fecham == 2


def test_new_capture_of_the_same_norm_goes_back_to_the_queue() -> None:
    row = _row(1296, MANY_OPEN)
    registered = {row["texto_id"]: _entry(row, sha256_fonte="0" * 64)}
    queue = reocr.select_queue([row], [], kreuzberg_version=KZ, defeitos=registered)
    assert [r["texto_id"] for r in queue] == [row["texto_id"]]


def test_queue_without_a_list_is_unchanged() -> None:
    row = _row(1296, MANY_OPEN)
    assert reocr.select_queue([row], [], kreuzberg_version=KZ, defeitos=None)
    assert reocr.select_queue([row], [], kreuzberg_version=KZ, defeitos={})


def test_defect_does_not_mark_the_norm_as_closing() -> None:
    row = _row(1296, MANY_OPEN)
    fecha, _ = textlayer.read_closure(row["texto"])
    assert fecha is False
    annotated = textlayer.annotate_row(
        dict(row), defeitos={row["texto_id"]: _entry(row)}
    )
    assert annotated["defeito_fonte"].startswith("O arquivo oficial")
    assert textlayer.read_closure(annotated["texto"])[0] is False


def test_annotate_clears_a_note_that_no_longer_applies() -> None:
    row = {**_row(1296, MANY_OPEN), "defeito_fonte": "nota velha"}
    assert textlayer.annotate_row(dict(row), defeitos=None)["defeito_fonte"] is None
    stale = {row["texto_id"]: _entry(row, sha256_fonte="f" * 64)}
    assert textlayer.annotate_row(dict(row), defeitos=stale)["defeito_fonte"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"nota": ""},
        {"tipo": "outro"},
        {"sha256_fonte": "ABC"},
        {"verificado_por": None},
    ],
)
def test_validation_rejects_incomplete_entries(
    tmp_path: Path, bad: dict[str, Any]
) -> None:
    path = _write(tmp_path, [_entry(_row(1296, MANY_OPEN), **bad)])
    with pytest.raises(ValueError):
        defeitos.load_defeitos(path)


def test_duplicate_texto_id_and_unreadable_file_are_errors(tmp_path: Path) -> None:
    e = _entry(_row(1296, MANY_OPEN))
    with pytest.raises(ValueError, match="repetido"):
        defeitos.load_defeitos(_write(tmp_path, [e, e]))
    broken = tmp_path / "x.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="ilegível"):
        defeitos.load_defeitos(broken)
    with pytest.raises(ValueError, match="não encontrado"):
        defeitos.load_defeitos(tmp_path / "ausente.json")
