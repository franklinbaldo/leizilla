"""Offline tests for scripts/reader_ratchet.py (the reader ratchet gate).

Gate logic is tested on synthetic scoreboards. ``run_scoreboard`` is exercised once
end to end against a pre-filled texts cache with an IA fetcher that fails the test
if it is called, so nothing touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

_SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

spec = importlib.util.spec_from_file_location(
    "reader_ratchet", _SCRIPTS / "reader_ratchet.py"
)
assert spec and spec.loader
rr = importlib.util.module_from_spec(spec)
sys.modules["reader_ratchet"] = rr
spec.loader.exec_module(rr)

import compare_teacher_reader as cmp  # noqa: E402

BATCH = "msgbatch_TEST"


def _board(
    groups: dict[str, str],
    not_compared: Optional[dict[str, str]] = None,
    labelled: Optional[int] = None,
) -> Any:
    return rr.Scoreboard(
        groups=groups,
        not_compared=not_compared or {},
        labelled=labelled if labelled is not None else len(groups),
        labels_identity={"batch_ids": [BATCH], "model": "m", "prompt_version": "v"},
        text_sources={"cache": len(groups)},
        ia_requests=0,
    )


@pytest.fixture(autouse=True)
def _fixed_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rr, "reader_commit", lambda: "c0ffee")
    monkeypatch.setattr(rr, "reader_last_change", lambda: "beef")


def _baseline(board: Any) -> dict[str, Any]:
    """Build a baseline the way ``update`` does, from a synthetic board."""
    return rr.build_baseline(
        board,
        previous=None,
        labels_source="test",
        history_entry={"date": "2026-01-01", "forced": False, "reason": "initial"},
    )


BASE_GROUPS = {
    "it/a1": "agree_closed",
    "it/a2": "agree_closed",
    "it/o1": "agree_open",
    "it/d1": "disagree_closed",
    "it/x1": "disagree_open",
}


def test_identical_run_passes() -> None:
    board = _board(dict(BASE_GROUPS))
    verdict = rr.evaluate(_baseline(board), board)
    assert not verdict.failed
    assert verdict.lost_agree == []
    assert verdict.new_disagree == []
    assert verdict.entered_agree == []


def test_improvement_passes_and_lists_new_agree_closed() -> None:
    base = _board(dict(BASE_GROUPS))
    improved = dict(BASE_GROUPS, **{"it/o1": "agree_closed", "it/x1": "disagree_open"})
    current = _board(improved)
    verdict = rr.evaluate(_baseline(base), current)
    assert not verdict.failed
    assert verdict.entered_agree == ["it/o1"]


def test_agree_closed_norm_that_leaves_fails_and_is_named() -> None:
    current_groups = dict(BASE_GROUPS, **{"it/a2": "agree_open"})
    verdict = rr.evaluate(_baseline(_board(dict(BASE_GROUPS))), _board(current_groups))
    assert verdict.failed
    assert verdict.lost_agree == [("it/a2", "agree_open")]


def test_agree_closed_norm_no_longer_compared_fails_with_reason() -> None:
    groups = {k: v for k, v in BASE_GROUPS.items() if k != "it/a1"}
    current = _board(groups, not_compared={"it/a1": rr.REASON_NOT_FETCHED})
    verdict = rr.evaluate(_baseline(_board(dict(BASE_GROUPS))), current)
    assert verdict.failed
    assert verdict.lost_agree == [("it/a1", rr.REASON_NOT_FETCHED)]


def test_new_disagree_closed_fails_and_is_named() -> None:
    groups = dict(BASE_GROUPS, **{"it/o1": "disagree_closed"})
    verdict = rr.evaluate(_baseline(_board(dict(BASE_GROUPS))), _board(groups))
    assert verdict.failed
    assert verdict.new_disagree == ["it/o1"]


def test_disagree_closed_already_in_baseline_is_not_new() -> None:
    verdict = rr.evaluate(
        _baseline(_board(dict(BASE_GROUPS))), _board(dict(BASE_GROUPS))
    )
    assert verdict.new_disagree == []


def test_disagree_closed_that_shrinks_passes_and_is_reported() -> None:
    groups = dict(BASE_GROUPS, **{"it/d1": "disagree_open"})
    verdict = rr.evaluate(_baseline(_board(dict(BASE_GROUPS))), _board(groups))
    assert not verdict.failed
    assert verdict.left_disagree == ["it/d1"]


def _run_main(monkeypatch: pytest.MonkeyPatch, board: Any, argv: list[str]) -> int:
    monkeypatch.setattr(rr, "run_scoreboard", lambda *a, **k: board)
    return rr.main(argv)


def _argv(command: str, baseline: Path, *extra: str) -> list[str]:
    return [
        command,
        "--labels",
        "unused-labels",
        "--texts",
        "unused-texts",
        "--baseline",
        str(baseline),
        *extra,
    ]


def test_update_refuses_when_check_fails_and_leaves_baseline_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    before = path.read_text(encoding="utf-8")
    bad = _board(dict(BASE_GROUPS, **{"it/a2": "agree_open"}))
    code = _run_main(monkeypatch, bad, _argv("update", path))
    assert code == 1
    assert path.read_text(encoding="utf-8") == before


def test_update_force_requires_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    bad = _board(dict(BASE_GROUPS, **{"it/a2": "agree_open"}))
    assert _run_main(monkeypatch, bad, _argv("update", path, "--force")) == 2


def test_forced_update_records_reason_and_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    bad = _board(dict(BASE_GROUPS, **{"it/a2": "agree_open"}))
    code = _run_main(
        monkeypatch,
        bad,
        _argv("update", path, "--force", "--reason", "accept a2 after review"),
    )
    assert code == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "it/a2" not in data["agree_closed"]
    entry = data["history"][-1]
    assert entry["forced"] is True
    assert entry["reason"] == "accept a2 after review"
    assert entry["left_agree_closed"] == ["it/a2"]
    assert len(data["history"]) == 2


def test_passing_update_is_written_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    improved = _board(dict(BASE_GROUPS, **{"it/o1": "agree_closed"}))
    assert _run_main(monkeypatch, improved, _argv("update", path)) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["agree_closed"] == ["it/a1", "it/a2", "it/o1"]
    entry = data["history"][-1]
    assert entry["forced"] is False
    assert entry["reason"] is None
    assert entry["entered_agree_closed"] == ["it/o1"]


def test_check_passes_on_identical_run_and_fails_on_regression(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    assert _run_main(monkeypatch, _board(dict(BASE_GROUPS)), _argv("check", path)) == 0
    regressed = _board(dict(BASE_GROUPS, **{"it/a1": "disagree_open"}))
    assert _run_main(monkeypatch, regressed, _argv("check", path)) == 1


def test_check_without_baseline_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = _run_main(
        monkeypatch,
        _board(dict(BASE_GROUPS)),
        _argv("check", tmp_path / "missing.json"),
    )
    assert code == 2


def test_step_summary_is_written_when_env_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _run_main(monkeypatch, _board(dict(BASE_GROUPS)), _argv("check", path))
    text = summary.read_text(encoding="utf-8")
    assert "Reader ratchet — check" in text
    assert "| agree_closed |" in text
    assert "**PASS**" in text


def test_baseline_is_deterministic_and_newline_terminated(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.loads(text)["agree_closed"] == ["it/a1", "it/a2"]
    rr.write_baseline(path, json.loads(text))
    assert path.read_text(encoding="utf-8") == text


def test_run_scoreboard_end_to_end_uses_cache_only(tmp_path: Path) -> None:
    """Real comparison on a pre-filled cache; the IA fetcher must never be called."""
    text = "Art. 1º Primeiro.\nArt. 2º Segundo.\n"
    header = {
        "record": "norm",
        "item": "leizilla_ro_test_lei_0001-1000",
        "fonte": "casacivil",
        "uuid5": "u-1",
        "tipo": "lei",
        "numero": 1,
        "txt_name": "L1.txt",
        "text_sha256": cmp.sha256_text(text),
        "chunks": 1,
    }
    labels_dir = tmp_path / "labels"
    norm_dir = labels_dir / "labels" / header["item"]
    norm_dir.mkdir(parents=True)
    records = [header]
    for line, number in ((1, "1"), (2, "2")):
        records.append(
            {
                "record": "label",
                "line": line,
                "category": "artigo",
                "number": number,
                "quoted": False,
            }
        )
    (norm_dir / "u-1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    (labels_dir / "summary.json").write_text(
        json.dumps({"batch_ids": [BATCH], "model": "m", "prompt_version": "v"}),
        encoding="utf-8",
    )
    texts_dir = tmp_path / "texts"
    cache = texts_dir / header["item"] / header["txt_name"]
    cache.parent.mkdir(parents=True)
    cache.write_bytes(text.encode("utf-8"))

    class NoNetwork:
        requests = 0

        def __call__(self, _header: dict[str, Any]) -> Optional[str]:
            raise AssertionError("IA must not be called when the cache is complete")

    board = rr.run_scoreboard(labels_dir, texts_dir, None, ia=NoNetwork())  # type: ignore[arg-type]

    key = f"{header['item']}/{header['uuid5']}"
    assert set(board.groups) == {key}
    assert board.not_compared == {}
    assert board.text_sources == {"cache": 1}
    assert board.labels_identity is not None
    assert board.labels_identity["batch_ids"] == [BATCH]


# --------------------------------------------------------------------------
# Teacher-label errata in the gate
# --------------------------------------------------------------------------

STALE = {
    "norm": "it/a1",
    "op": "add_own_article",
    "line": 4,
    "reason": "evidence text is not on the recorded line",
}


def test_stale_errata_fails_check_and_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import dataclasses

    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    stale_board = dataclasses.replace(_board(dict(BASE_GROUPS)), errata_stale=[STALE])
    assert _run_main(monkeypatch, stale_board, _argv("check", path)) == 1
    out = capsys.readouterr().out
    assert "FAIL stale errata: it/a1 add_own_article line 4" in out


def test_stale_errata_blocks_update_even_with_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dataclasses

    path = tmp_path / "baseline.json"
    rr.write_baseline(path, _baseline(_board(dict(BASE_GROUPS))))
    before = path.read_text(encoding="utf-8")
    stale_board = dataclasses.replace(_board(dict(BASE_GROUPS)), errata_stale=[STALE])
    code = _run_main(
        monkeypatch,
        stale_board,
        _argv("update", path, "--force", "--reason", "try anyway"),
    )
    assert code == 1
    assert path.read_text(encoding="utf-8") == before


def _errata_fixture(
    tmp_path: Path, sha: str
) -> tuple[Path, Path, Path, dict[str, Any]]:
    text = "Art. 1º Primeiro.\nArt. 2º Segundo.\nRevogam-se.\n"
    header = {
        "record": "norm",
        "item": "leizilla_ro_test_lei_0001-1000",
        "fonte": "casacivil",
        "uuid5": "u-1",
        "tipo": "lei",
        "numero": 1,
        "txt_name": "L1.txt",
        "text_sha256": cmp.sha256_text(text),
        "chunks": 1,
    }
    labels_dir = tmp_path / "labels"
    norm_dir = labels_dir / "labels" / header["item"]
    norm_dir.mkdir(parents=True)
    records: list[dict[str, Any]] = [header]
    for line, number in ((1, "1"), (2, "2")):
        records.append(
            {
                "record": "label",
                "line": line,
                "category": "artigo",
                "number": number,
                "quoted": False,
            }
        )
    (norm_dir / "u-1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    (labels_dir / "summary.json").write_text(
        json.dumps({"batch_ids": [BATCH], "model": "m", "prompt_version": "v"}),
        encoding="utf-8",
    )
    texts_dir = tmp_path / "texts"
    cache = texts_dir / header["item"] / header["txt_name"]
    cache.parent.mkdir(parents=True)
    cache.write_bytes(text.encode("utf-8"))
    errata_path = tmp_path / "errata.json"
    corr = {
        "norm": f"{header['item']}/{header['uuid5']}",
        "text_sha256": sha,
        "op": "add_own_article",
        "line": 3,
        "number": "3",
        "evidence": "Revogam-se",
        "reason": "test",
        "verified_by": "leitura do texto",
        "date": "2026-11-17",
    }
    errata_path.write_text(
        json.dumps({"schema_version": 1, "corrections": [corr]}), encoding="utf-8"
    )
    return labels_dir, texts_dir, errata_path, header


def test_end_to_end_check_fails_on_stale_errata_and_passes_without(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_path = tmp_path / "baseline.json"
    labels_dir, texts_dir, errata_path, header = _errata_fixture(tmp_path, sha="0" * 64)
    base = rr.run_scoreboard(labels_dir, texts_dir, None, ia=None)
    rr.write_baseline(baseline_path, _baseline(base))
    common = [
        "check",
        "--labels",
        str(labels_dir),
        "--texts",
        str(texts_dir),
        "--baseline",
        str(baseline_path),
    ]

    assert rr.main([*common, "--no-errata"]) == 0
    capsys.readouterr()

    assert rr.main([*common, "--errata", str(errata_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL stale errata: leizilla_ro_test_lei_0001-1000/u-1" in out
    assert "sha256 mismatch" in out

    # malformed errata file is a usage error, not a pass
    errata_path.write_text("{not json", encoding="utf-8")
    assert rr.main([*common, "--errata", str(errata_path)]) == 2


def test_valid_errata_is_applied_and_recorded_in_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "Art. 1º Primeiro.\nArt. 2º Segundo.\nRevogam-se.\n"
    labels_dir, texts_dir, errata_path, _header_unused = _errata_fixture(
        tmp_path, sha=cmp.sha256_text(text)
    )
    errata = cmp.load_errata(errata_path)
    board = rr.run_scoreboard(labels_dir, texts_dir, None, ia=None, errata=errata)
    assert board.errata_stale == []
    assert len(board.errata_applied) == 1

    baseline_path = tmp_path / "baseline.json"
    common = [
        "--labels",
        str(labels_dir),
        "--texts",
        str(texts_dir),
        "--baseline",
        str(baseline_path),
        "--errata",
        str(errata_path),
    ]
    assert rr.main(["update", *common, "--reason", "initial"]) == 0
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert data["labels"]["errata_applied"] == 1
    assert data["labels"]["errata_sha256"] == errata.sha256
    assert data["history"][-1]["errata_applied"] == 1
    assert rr.main(["check", *common]) == 0
    assert "errata: 1 applied, 0 stale" in capsys.readouterr().out
