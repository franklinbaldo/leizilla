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


# --------------------------------------------------------------------------
# Errata: corrections to the teacher's article labels
# --------------------------------------------------------------------------

# The reader closes on this text and reads an extra article on the "Revogam" line
# (the orphan closing sentence). A teacher who labels 1..3 misses article 4.
ERRATA_TEXT = (
    "Art. 1º - Fica criado o órgão de controle.\n"
    "Art. 2º - Os recursos serão aplicados na forma da lei.\n"
    "Art. 3º - Os recursos serão aplicados na forma da lei.\n"
    "Revogam-se as disposições em contrário.\n"
)
ERRATA_LABELS = [_label(1, "1"), _label(2, "2"), _label(3, "3")]


def _correction(
    text: str,
    line: int,
    evidence: str,
    op: str = "add_own_article",
    norm: str = "item_a/abcd1234",
    **extra: Any,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "norm": norm,
        "text_sha256": cmp.sha256_text(text),
        "op": op,
        "line": line,
        "evidence": evidence,
        "reason": "test",
        "verified_by": "leitura do texto",
        "date": "2026-11-17",
    }
    if op in ("add_own_article", "set_number"):
        raw.setdefault("number", "4")
    raw.update(extra)
    return raw


def _errata(*raw: dict[str, Any]) -> Any:
    corrections = tuple(
        cmp.validate_correction(r, f"test[{i}]") for i, r in enumerate(raw)
    )
    return cmp.Errata(
        path=Path("errata.json"), sha256="0" * 64, corrections=corrections
    )


def _corpus(
    tmp_path: Path,
    text: str,
    labels: list[dict[str, Any]],
    errata: Any = None,
    cached: bool = True,
) -> Any:
    texts_dir = tmp_path / "texts"
    if cached:
        cache = texts_dir / "item_a"
        cache.mkdir(parents=True)
        (cache / "lei-00030_abcd1234_djvu.txt").write_bytes(text.encode("utf-8"))
    header = _header("item_a", "lei-00030_abcd1234_djvu.txt", text)
    stub = _StubIa(lambda _h: None)
    return cmp.compare_corpus(
        [(header, labels)],
        texts_dir,
        ia=stub,  # type: ignore[arg-type]
        errata=errata,
    )


def test_errata_applied_when_sha_matches_and_changes_group(tmp_path: Path) -> None:
    before = _corpus(tmp_path / "a", ERRATA_TEXT, ERRATA_LABELS)
    assert before.rows[0]["group"] == "disagree_closed"

    errata = _errata(_correction(ERRATA_TEXT, 4, "Revogam-se"))
    after = _corpus(tmp_path / "b", ERRATA_TEXT, ERRATA_LABELS, errata=errata)
    assert after.rows[0]["group"] == "agree_closed"
    assert after.errata_applied == [
        {"norm": "item_a/abcd1234", "op": "add_own_article", "line": 4}
    ]
    assert after.errata_stale == []
    # the caller's labels are not modified
    assert len(ERRATA_LABELS) == 3


def test_no_errata_reproduces_the_old_behaviour(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, ERRATA_TEXT, ERRATA_LABELS, errata=None)
    assert corpus.rows[0]["group"] == "disagree_closed"
    assert corpus.errata_applied == []
    assert corpus.errata_stale == []


def test_correction_for_other_text_is_stale_not_applied(tmp_path: Path) -> None:
    raw = _correction(ERRATA_TEXT, 4, "Revogam-se")
    raw["text_sha256"] = cmp.sha256_text("outro texto\n")
    corpus = _corpus(tmp_path, ERRATA_TEXT, ERRATA_LABELS, errata=_errata(raw))
    assert corpus.rows[0]["group"] == "disagree_closed"
    assert corpus.errata_applied == []
    assert corpus.errata_stale == [
        {
            "norm": "item_a/abcd1234",
            "op": "add_own_article",
            "line": 4,
            "reason": "sha256 mismatch",
        }
    ]


def test_evidence_not_on_the_recorded_line_is_stale(tmp_path: Path) -> None:
    raw = _correction(ERRATA_TEXT, 4, "Esta Lei entra em vigor")
    corpus = _corpus(tmp_path, ERRATA_TEXT, ERRATA_LABELS, errata=_errata(raw))
    assert corpus.rows[0]["group"] == "disagree_closed"
    assert corpus.errata_applied == []
    assert [s["reason"] for s in corpus.errata_stale] == [
        "evidence text is not on the recorded line"
    ]


def test_correction_for_unlabelled_norm_is_stale(tmp_path: Path) -> None:
    raw = _correction(ERRATA_TEXT, 4, "Revogam-se", norm="item_zz/abcd1234")
    corpus = _corpus(tmp_path, ERRATA_TEXT, ERRATA_LABELS, errata=_errata(raw))
    assert corpus.errata_applied == []
    assert corpus.errata_stale[0]["reason"] == cmp.REASON_CORR_NOT_LABELLED


def test_correction_for_norm_without_text_is_stale(tmp_path: Path) -> None:
    raw = _correction(ERRATA_TEXT, 4, "Revogam-se")
    corpus = _corpus(
        tmp_path, ERRATA_TEXT, ERRATA_LABELS, errata=_errata(raw), cached=False
    )
    assert corpus.rows == []
    assert corpus.errata_stale[0]["reason"] == cmp.REASON_CORR_NOT_FETCHED


def test_add_own_article_already_labelled_is_stale() -> None:
    labels = [_label(1, "1"), _label(2, "2")]
    raw = _correction(ERRATA_TEXT, 1, "Fica criado", number="1")
    applied, stale = cmp.apply_corrections(labels, [raw], ERRATA_TEXT)[1:]
    assert applied == []
    assert stale[0]["reason"] == "teacher already labels this article at this line"
    assert len(labels) == 2


def test_set_number_and_set_quoted_change_only_the_target() -> None:
    labels = [_label(1, "1"), _label(2, "2")]
    number = _correction(
        ERRATA_TEXT, 2, "Art. 2º", op="set_number", number="2", suffix="A"
    )
    quoted = _correction(ERRATA_TEXT, 3, "Art. 3º", op="set_quoted", quoted=True)
    out, applied, stale = cmp.apply_corrections(labels, [number, quoted], ERRATA_TEXT)
    # line 3 has no teacher article: set_quoted is stale, set_number applies
    assert [a["op"] for a in applied] == ["set_number"]
    assert stale[0]["reason"].startswith("expected one teacher article")
    assert out[1]["number"] == "2-A"
    assert out[0] == labels[0]
    assert labels[1]["number"] == "2"

    quoted_ok = _correction(ERRATA_TEXT, 2, "Art. 2º", op="set_quoted", quoted=True)
    out, applied, stale = cmp.apply_corrections(labels, [quoted_ok], ERRATA_TEXT)
    assert applied and not stale
    assert out[1]["quoted"] is True


def test_load_errata_rejects_unknown_op_and_fields(tmp_path: Path) -> None:
    def write(corr: dict[str, Any]) -> Path:
        path = tmp_path / "errata.json"
        path.write_text(
            json.dumps({"schema_version": 1, "corrections": [corr]}), encoding="utf-8"
        )
        return path

    with pytest.raises(cmp.ErrataError, match="unknown op"):
        cmp.load_errata(write(_correction(ERRATA_TEXT, 4, "x", op="remove_label")))
    with pytest.raises(cmp.ErrataError, match="not allowed"):
        cmp.load_errata(write(_correction(ERRATA_TEXT, 4, "x", quoted=True)))
    with pytest.raises(cmp.ErrataError, match="date"):
        bad = _correction(ERRATA_TEXT, 4, "x")
        bad["date"] = "17/11/2026"
        cmp.load_errata(write(bad))


def test_repo_errata_file_is_canonical_and_loads() -> None:
    errata = cmp.load_errata(cmp.DEFAULT_ERRATA)
    assert len(errata.corrections) == 9
    text = cmp.DEFAULT_ERRATA.read_text(encoding="utf-8")
    data = json.loads(text)
    assert text == json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_run_summary_records_applied_norms(tmp_path: Path) -> None:
    labels_dir = tmp_path / "labels"
    header = _header("item_a", "lei-00030_abcd1234_djvu.txt", ERRATA_TEXT)
    _write_norm(labels_dir, header, ERRATA_LABELS)
    texts_dir = tmp_path / "texts"
    cache = texts_dir / "item_a"
    cache.mkdir(parents=True)
    (cache / "lei-00030_abcd1234_djvu.txt").write_bytes(ERRATA_TEXT.encode("utf-8"))
    errata = _errata(_correction(ERRATA_TEXT, 4, "Revogam-se"))

    summary = cmp.run(
        labels_dir,
        texts_dir,
        tmp_path / "out",
        ia=_StubIa(lambda _h: None),  # type: ignore[arg-type]
        errata=errata,
    )
    assert summary["errata"]["applied"] == 1
    assert summary["errata"]["applied_norms"] == ["item_a/abcd1234"]
    assert summary["errata"]["stale"] == 0
    assert summary["groups"]["agree_closed"]["count"] == 1
    md = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "errata: 1 applied to 1 norms, 0 stale" in md
