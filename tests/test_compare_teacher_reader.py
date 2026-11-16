"""Offline tests for scripts/compare_teacher_reader.py.

No network: the Internet Archive fetcher is an in-process stub, and the synthetic
texts are tiny. The reader itself (``read_hierarchy``) is the real one.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "compare_teacher_reader.py"
spec = importlib.util.spec_from_file_location("compare_teacher_reader", _SCRIPT)
assert spec and spec.loader
cmp = importlib.util.module_from_spec(spec)
sys.modules["compare_teacher_reader"] = cmp
spec.loader.exec_module(cmp)


def _header(item: str, txt_name: str, text: str) -> dict[str, Any]:
    return {
        "record": "norm",
        "item": item,
        "fonte": "casacivil",
        "uuid5": "abcd1234",
        "tipo": "lei",
        "numero": 1,
        "txt_name": txt_name,
        "text_sha256": cmp.sha256_text(text),
        "chunks": 1,
    }


def _label(line: int, number: Optional[str], quoted: bool = False) -> dict[str, Any]:
    return {
        "record": "label",
        "line": line,
        "category": "artigo",
        "number": number,
        "quoted": quoted,
    }


class _StubIa:
    """Stands in for IaFetcher: counts calls and never touches the network."""

    def __init__(self, fn: Callable[[dict[str, Any]], Optional[str]]) -> None:
        self._fn = fn
        self.calls: list[str] = []

    @property
    def requests(self) -> int:
        return len(self.calls)

    def __call__(self, header: dict[str, Any]) -> Optional[str]:
        self.calls.append(str(header["txt_name"]))
        return self._fn(header)


# --------------------------------------------------------------------------
# Numbers, lines, prefixes
# --------------------------------------------------------------------------


def test_normalize_number_canonical_forms() -> None:
    assert cmp.normalize_number("5-A") == "5-A"
    assert cmp.normalize_number("5 a") == "5-A"
    assert cmp.normalize_number("5A") == "5-A"
    assert cmp.normalize_number("012") == "12"
    assert cmp.normalize_number("unico") == "UNICO"
    assert cmp.normalize_number(None) == "?"


def test_reader_number_joins_suffix() -> None:
    assert cmp.reader_number(5, "A") == "5-A"
    assert cmp.reader_number(5, "-A") == "5-A"
    assert cmp.reader_number(7, None) == "7"
    assert cmp.reader_number(None, None) == "?"


def test_teacher_numbers_consistent_ignores_suffixes() -> None:
    assert cmp.teacher_numbers_consistent({(1, "1"), (2, "2"), (3, "3")})
    assert cmp.teacher_numbers_consistent({(1, "1"), (4, "2"), (5, "2-A"), (9, "3")})
    assert cmp.teacher_numbers_consistent(set())


def test_teacher_numbers_consistent_flags_gaps_repeats_and_unknowns() -> None:
    assert not cmp.teacher_numbers_consistent({(1, "1"), (3, "3")})
    assert not cmp.teacher_numbers_consistent({(1, "1"), (5, "1"), (9, "2")})
    assert not cmp.teacher_numbers_consistent({(1, "1"), (2, "?")})


def test_marker_prefix_lowercases_and_masks_digits() -> None:
    assert cmp.marker_prefix("   Art. 12 - foo") == "art. 99 "
    assert cmp.marker_prefix("Art.") == "art."


# --------------------------------------------------------------------------
# Pure classification
# --------------------------------------------------------------------------


def test_classify_groups() -> None:
    same = {(1, "1"), (3, "2")}
    other = {(1, "1")}
    assert cmp.classify(same, set(same), True, True) == "agree_closed"
    assert cmp.classify(same, set(same), False, True) == "agree_open"
    assert cmp.classify(same, other, True, True) == "disagree_closed"
    assert cmp.classify(same, other, False, True) == "disagree_open"
    # teacher_inconsistent wins only when the reader closes with a different set
    assert cmp.classify(same, other, True, False) == "teacher_inconsistent"
    assert cmp.classify(same, other, False, False) == "disagree_open"
    # equal sets are agreement even when the teacher numbering looks odd
    assert cmp.classify({(1, "5")}, {(1, "5")}, True, False) == "agree_closed"


def test_diff_kinds_end_middle_start_and_reader_only() -> None:
    def kinds(diffs: list[Any]) -> list[tuple[str, str, int]]:
        return [(d.kind, d.side, d.line) for d in diffs]

    end = cmp.diff_kinds(
        {(1, "1"), (3, "3"), (5, "4")}, set(), {(1, "1"), (3, "3")}, set()
    )
    assert kinds(end) == [(cmp.KIND_END, "teacher", 5)]

    start = cmp.diff_kinds({(1, "1")}, set(), {(4, "2")}, set())
    assert kinds(start) == [
        (cmp.KIND_START, "teacher", 1),
        (cmp.KIND_READER_ONLY, "reader", 4),
    ]

    middle = cmp.diff_kinds(
        {(1, "1"), (3, "2"), (6, "3")}, set(), {(1, "1"), (6, "3")}, set()
    )
    assert kinds(middle) == [(cmp.KIND_MIDDLE, "teacher", 3)]

    reader_only = cmp.diff_kinds({(1, "1")}, set(), {(1, "1"), (9, "9")}, set())
    assert kinds(reader_only) == [(cmp.KIND_READER_ONLY, "reader", 9)]


def test_diff_kinds_status_and_same_line() -> None:
    # teacher says own, reader says quoted at the same (line, number)
    status_t = cmp.diff_kinds({(2, "2")}, set(), {(1, "1")}, {(2, "2")})
    assert [(d.kind, d.side) for d in status_t] == [
        (cmp.KIND_STATUS, "teacher"),
        (cmp.KIND_READER_ONLY, "reader"),
    ]
    # teacher says quoted, reader says own at the same (line, number)
    status_r = cmp.diff_kinds({(1, "1")}, {(2, "2")}, {(1, "1"), (2, "2")}, set())
    assert [(d.kind, d.side) for d in status_r] == [(cmp.KIND_STATUS, "reader")]
    # same line, different number: one pair, counted once on the teacher side
    same_line = cmp.diff_kinds({(2, "2")}, set(), {(2, "3")}, set())
    assert [(d.kind, d.side, d.line) for d in same_line] == [
        (cmp.KIND_SAME_LINE, "teacher", 2)
    ]


def test_diff_kinds_reader_without_articles() -> None:
    diffs = cmp.diff_kinds({(1, "1")}, set(), set(), set())
    assert [d.kind for d in diffs] == [cmp.KIND_NO_READER]


# --------------------------------------------------------------------------
# Per-norm comparison on synthetic texts
# --------------------------------------------------------------------------


def test_compare_norm_agreement() -> None:
    text = (
        "Art. 1º - Fica criado o órgão de controle.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    header = _header("item_a", "lei-00001_abcd1234_djvu.txt", text)
    row = cmp.compare_norm(header, [_label(1, "1"), _label(2, "2")], text)
    assert row["n_teacher_articles"] == row["n_reader_articles"] == 2
    assert row["group"] in {"agree_closed", "agree_open"}
    assert row["diffs"] == []
    assert row["first_disagreement_line"] is None


def test_compare_norm_end_disagreement_points_at_the_extra_line() -> None:
    text = (
        "Art. 1º - Fica criado o órgão de controle.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
        "Revogam-se as disposições em contrário.\n"
    )
    header = _header("item_a", "lei-00002_abcd1234_djvu.txt", text)
    # the teacher labels a third article on a line that is not a marker
    labels = [_label(1, "1"), _label(2, "2"), _label(3, "3")]
    row = cmp.compare_norm(header, labels, text)
    assert row["group"] not in {"agree_closed", "agree_open"}
    assert [d["kind"] for d in row["diffs"]] == [cmp.KIND_END]
    assert row["first_disagreement_line"] == 3
    assert row["first_disagreement_text"].startswith("Revogam-se")


def test_compare_norm_ignores_quoted_teacher_labels() -> None:
    text = "Art. 1º - Fica criado o órgão.\nArt. 2º - Esta Lei entra em vigor.\n"
    header = _header("item_a", "lei-00003_abcd1234_djvu.txt", text)
    labels = [_label(1, "1"), _label(2, "2", quoted=True)]
    row = cmp.compare_norm(header, labels, text)
    assert row["n_teacher_articles"] == 1
    assert not any(d["side"] == "teacher" and d["line"] == 2 for d in row["diffs"])


# --------------------------------------------------------------------------
# Inputs: cache, sha check, missing list, no refetch on re-run
# --------------------------------------------------------------------------


def _write_norm(
    labels_dir: Path, header: dict[str, Any], labels: list[dict[str, Any]]
) -> None:
    path = labels_dir / header["item"] / (header["txt_name"] + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [header, *labels]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_run_checks_sha_caches_and_never_refetches(tmp_path: Path) -> None:
    labels_dir = tmp_path / "labels"
    texts_dir = tmp_path / "texts"
    out_dir = tmp_path / "out"
    good = "Art. 1º - Fica criado o órgão.\nArt. 2º - Esta Lei entra em vigor.\n"
    other = "Art. 1º - Texto diferente.\n"
    missing = "Art. 1º - Sem texto.\n"

    h_good = _header("item_a", "lei-00010_abcd1234_djvu.txt", good)
    h_bad = _header("item_a", "lei-00011_abcd1234_djvu.txt", good)
    h_missing = _header("item_a", "lei-00012_abcd1234_djvu.txt", missing)
    _write_norm(labels_dir, h_good, [_label(1, "1"), _label(2, "2")])
    _write_norm(labels_dir, h_bad, [_label(1, "1"), _label(2, "2")])
    _write_norm(labels_dir, h_missing, [_label(1, "1")])

    cached = texts_dir / "item_a"
    cached.mkdir(parents=True)
    (cached / "lei-00010_abcd1234_djvu.txt").write_bytes(good.encode("utf-8"))
    (cached / "lei-00011_abcd1234_djvu.txt").write_bytes(other.encode("utf-8"))

    # first run: the only text not cached is refused by the stub (not found)
    first_stub = _StubIa(lambda _h: None)
    first = cmp.run(labels_dir, texts_dir, out_dir, ia=first_stub)  # type: ignore[arg-type]
    assert first["compared"] == 1
    assert first["skipped_sha_mismatch"] == 1
    assert first["skipped_missing_text"] == 1
    assert first_stub.calls == ["lei-00012_abcd1234_djvu.txt"]
    assert (texts_dir / "_missing.txt").read_text(encoding="utf-8").strip() == (
        "item_a/lei-00012_abcd1234_djvu.txt"
    )
    assert (out_dir / "groups.csv").is_file()

    # second run: nothing may reach the network, the missing norm included
    second_stub = _StubIa(lambda _h: pytest.fail("network call on re-run"))
    second = cmp.run(labels_dir, texts_dir, out_dir, ia=second_stub)  # type: ignore[arg-type]
    assert second_stub.calls == []
    assert second["compared"] == 1
    assert second["skipped_missing_text"] == 1


def test_get_text_takes_parquet_only_when_sha_matches(tmp_path: Path) -> None:
    text = "Art. 1º - Fica criado o órgão.\n"
    header = _header("item_b", "lei-00020_abcd1234_djvu.txt", text)
    texts_dir = tmp_path / "texts"
    missing: set[str] = set()

    # a parquet row keyed by the right sha but holding other content is ignored
    wrong = cmp.ParquetTexts(tmp_path / "unused.parquet")
    wrong._by_sha = {str(header["text_sha256"]): "outro texto\n"}
    stub = _StubIa(lambda _h: text)
    got, source = cmp.get_text(header, texts_dir, wrong, missing, stub)  # type: ignore[arg-type]
    assert (got, source) == (text, "ia")
    assert stub.requests == 1

    # the right content is taken from the parquet with no network call
    right = cmp.ParquetTexts(tmp_path / "unused.parquet")
    right._by_sha = {str(header["text_sha256"]): text}
    stub_none = _StubIa(lambda _h: pytest.fail("network call"))
    texts2 = tmp_path / "texts2"
    got, source = cmp.get_text(header, texts2, right, missing, stub_none)  # type: ignore[arg-type]
    assert (got, source) == (text, "parquet")
    assert stub_none.requests == 0
    assert (texts2 / "item_b" / "lei-00020_abcd1234_djvu.txt").read_bytes() == (
        text.encode("utf-8")
    )


def test_iafetcher_spaces_requests_by_one_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(cmp, "fetch_text", lambda _ref: "texto")
    fetcher = cmp.IaFetcher(sleep=sleep, clock=clock)
    header = {
        "item": "item_a",
        "fonte": "casacivil",
        "tipo": "lei",
        "numero": 1,
        "uuid5": "abcd1234",
        "txt_name": "lei-00001_abcd1234_djvu.txt",
    }
    assert fetcher(header) == "texto"
    now[0] += 0.2
    assert fetcher(header) == "texto"
    assert waits == [pytest.approx(0.8)]
    assert fetcher.requests == 2
