"""Tests for the ``textos`` text source, label exclusion and label sets.

Offline and deterministic: the published text layer is a parquet written into
``tmp_path``; the Internet Archive is patched at ``_download_to``; the Anthropic
client is a ``MagicMock`` (the batch wire shape is covered in test_teacher_batch).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import duckdb
import pytest
from typer.testing import CliRunner

from leizilla import teacher_batch as tb

_SCRIPT = Path(__file__).parents[1] / "scripts" / "compare_teacher_reader.py"
_spec = importlib.util.spec_from_file_location("compare_teacher_reader", _SCRIPT)
assert _spec is not None and _spec.loader is not None
cmp = importlib.util.module_from_spec(_spec)
sys.modules["compare_teacher_reader"] = cmp
_spec.loader.exec_module(cmp)

ITEM = "leizilla_ro_casacivil_lei_0001-1000"
ITEM2 = "leizilla_ro_casacivil_decreto_0001-1000"

TEXT_A = (
    "GOVERNO DO ESTADO\nLEI Nº 7\nArt. 1º - Fica criada a coisa.\nArt. 2º - Vigora."
)
TEXT_A2 = TEXT_A + "\nArt. 3º - Texto refeito pelo OCR."
TEXT_B = "Art. 1º - Outra norma.\nArt. 2º - Fim."
TEXT_C = "DECRETO Nº 9\nArt. 1º - Terceira norma."

_COLS = [
    "texto_id",
    "ia_item",
    "fonte",
    "tipo",
    "numero",
    "texto_url",
    "pdf_url",
    "sha256_texto",
    "ocr_motor",
    "texto",
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row(
    item: str = ITEM,
    tipo: str = "lei",
    numero: int = 7,
    uuid5: str = "aaaaaaaa",
    text: str = TEXT_A,
    *,
    pdf_only: bool = False,
    sha: Optional[str] = None,
    motor: Optional[str] = "tesseract",
) -> Dict[str, Any]:
    base = f"{tipo}-{numero:05d}_{uuid5}"
    url = f"https://archive.org/download/{item}/{base}_djvu.txt"
    pdf = f"https://archive.org/download/{item}/{base}.pdf"
    return {
        "texto_id": f"leizilla-raw-ro-casacivil-{tipo}-{numero:05d}",
        "ia_item": item,
        "fonte": "casacivil",
        "tipo": tipo,
        "numero": numero,
        "texto_url": None if pdf_only else url,
        "pdf_url": pdf,
        "sha256_texto": _sha(text) if sha is None else sha,
        "ocr_motor": motor,
        "texto": text,
    }


def _write_textos(path: Path, rows: List[Dict[str, Any]]) -> Path:
    con = duckdb.connect()
    try:
        con.execute(
            "create table t (texto_id varchar, ia_item varchar, fonte varchar, "
            "tipo varchar, numero integer, texto_url varchar, pdf_url varchar, "
            "sha256_texto varchar, ocr_motor varchar, texto varchar)"
        )
        for row in rows:
            con.execute(
                "insert into t values (?,?,?,?,?,?,?,?,?,?)",
                [row[c] for c in _COLS],
            )
        con.execute(f"copy t to '{path}' (format parquet)")
    finally:
        con.close()
    return path


def _write_label(
    root: Path, item: str, tipo: str, numero: int, uuid5: str, sha: str
) -> None:
    header = {
        "record": "norm",
        "ente": "ro",
        "fonte": "casacivil",
        "item": item,
        "uuid5": uuid5,
        "tipo": tipo,
        "numero": numero,
        "txt_name": f"{tipo}-{numero:05d}_{uuid5}_djvu.txt",
        "text_sha256": sha,
    }
    path = root / item / f"{tipo}-{numero:05d}_{uuid5}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(header)
        + "\n"
        + json.dumps({"record": "label", "line": 1, "category": "artigo"})
        + "\n",
        encoding="utf-8",
    )


def _prepare_kwargs(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = dict(
        ente="ro",
        fonte="casacivil",
        tipo=None,
        limit=None,
        shuffle_seed=None,
        cache_dir=None,
        retry_failures=None,
        max_lines=tb.DEFAULT_MAX_LINES,
        max_chars=tb.DEFAULT_MAX_CHARS,
        max_tokens_cap=tb.MAX_TOKENS_CAP,
        fetch_delay=0.0,
    )
    base.update(over)
    return base


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("lei-00331_672fe440_djvu.txt", "672fe440"),
        ("000001_df90ea45_djvu.txt", "df90ea45"),
        ("decreto-32194_faa3b3e6.pdf", "faa3b3e6"),
        ("2783b58e.pdf", "2783b58e"),
        ("lei-00331_672fe440_djvu.xml", None),
        ("lei-00331_NOTHEX!!_djvu.txt", None),
    ],
)
def test_uuid5_from_filename(name: str, expected: Optional[str]) -> None:
    assert tb.uuid5_from_filename(name) == expected


# --------------------------------------------------------------------------
# textos loader
# --------------------------------------------------------------------------


class TestLoadTextos:
    def test_identity_text_and_skips(self, tmp_path: Path) -> None:
        rows = [
            _row(),  # djvu url
            _row(ITEM2, "decreto", 9, "bbbbbbbb", TEXT_C, pdf_only=True),
            _row(ITEM, "lei", 8, "cccccccc", TEXT_B, sha="0" * 64),  # bad sha
            _row(ITEM, "lei", 10, "dddddddd", TEXT_B),
        ]
        rows[-1]["texto"] = None  # not a text: dropped by the query
        rows.append(
            dict(_row(ITEM, "lei", 11, "eeeeeeee"), texto_url=None, pdf_url=None)
        )  # no identity at all
        path = _write_textos(tmp_path / "textos.parquet", rows)

        corpus = tb.load_textos(path)

        assert corpus.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert corpus.skipped == {"sha_mismatch": 1, "no_identity": 1}
        by_key = {r.ref.key: r for r in corpus.records}
        assert set(by_key) == {f"{ITEM}/aaaaaaaa", f"{ITEM2}/bbbbbbbb"}

        djvu = by_key[f"{ITEM}/aaaaaaaa"]
        assert djvu.ref.txt_name == "lei-00007_aaaaaaaa_djvu.txt"
        assert (djvu.ref.tipo, djvu.ref.numero, djvu.ref.fonte) == (
            "lei",
            7,
            "casacivil",
        )
        assert djvu.text == TEXT_A and djvu.text_sha256 == _sha(TEXT_A)
        assert djvu.ocr_motor == "tesseract"

        pdf = by_key[f"{ITEM2}/bbbbbbbb"]
        assert pdf.ref.txt_name == "decreto-00009_bbbbbbbb_djvu.txt"
        assert pdf.text_sha256 == _sha(TEXT_C)

    def test_duplicate_identity_is_an_error(self, tmp_path: Path) -> None:
        # Same (item, uuid5) under two numbers: a broken corpus, never guessed.
        rows = [
            _row(),
            dict(_row(numero=8, text=TEXT_B), texto_url=_row()["texto_url"]),
        ]
        path = _write_textos(tmp_path / "dup.parquet", rows)
        with pytest.raises(tb.TeacherBatchError, match="duplicate identity"):
            tb.load_textos(path)


# --------------------------------------------------------------------------
# Text sources produce the same request, and the same hash as the comparison
# --------------------------------------------------------------------------


class TestTextSourceParity:
    def test_textos_request_matches_ia_request_for_the_same_text(
        self, tmp_path: Path
    ) -> None:
        path = _write_textos(tmp_path / "t.parquet", [_row(text=TEXT_A)])
        textos_plan = tb._prepare(**_prepare_kwargs(text_source="textos", textos=path))
        ref = tb.NormRef(
            item=ITEM,
            fonte="casacivil",
            tipo="lei",
            numero=7,
            uuid5="aaaaaaaa",
            txt_name="lei-00007_aaaaaaaa_djvu.txt",
        )
        ia_plan = tb.build_plan([ref], lambda _: TEXT_A)

        assert len(textos_plan.requests) == len(ia_plan.requests) == 1
        t_req, i_req = textos_plan.requests[0], ia_plan.requests[0]
        assert t_req.custom_id == i_req.custom_id
        assert t_req.user_text == i_req.user_text
        assert t_req.text_sha256 == i_req.text_sha256
        spec = tb.MODELS[tb.DEFAULT_MODEL]
        assert tb.build_request_params(t_req, spec, "medium", True) == (
            tb.build_request_params(i_req, spec, "medium", True)
        )

    def test_header_sha_is_the_comparison_script_hash_and_reads_back(
        self, tmp_path: Path
    ) -> None:
        path = _write_textos(tmp_path / "t.parquet", [_row(text=TEXT_A)])
        plan = tb._prepare(**_prepare_kwargs(text_source="textos", textos=path))
        client = MagicMock()
        client.messages.batches.create.return_value = SimpleNamespace(id="msgbatch_1")
        spec = tb.MODELS[tb.DEFAULT_MODEL]
        estimate = tb.estimate_cost(plan, spec, "medium", True)
        manifest = tb.build_manifest(
            plan,
            estimate,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1.0,
            guard="ceiling",
        )
        tb.submit_batches(
            client,
            plan,
            spec,
            manifest,
            tmp_path / "m.json",
            effort="medium",
            cache=True,
        )
        cid = plan.requests[0].custom_id
        payload = {"labels": [], "amends": []}
        client.messages.batches.results.return_value = [
            {
                "custom_id": cid,
                "result": {
                    "type": "succeeded",
                    "message": {
                        "content": [{"type": "text", "text": json.dumps(payload)}],
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                },
            }
        ]
        out = tmp_path / "out"
        tb.collect_results(client, manifest, out)

        norms = cmp.load_labelled_norms(out / "labels")
        assert len(norms) == 1
        header, _ = norms[0]
        # The hash the comparison script computes over the textos text...
        assert cmp.sha256_text(TEXT_A) == header["text_sha256"] == _sha(TEXT_A)
        # ...and the text it finds back in textos.parquet by that hash.
        assert cmp.ParquetTexts(path).get(header["text_sha256"]) == TEXT_A
        assert header["label_set"] == "main"


# --------------------------------------------------------------------------
# Exclusion of norms already labelled
# --------------------------------------------------------------------------


class TestExclusion:
    def test_status_rules(self) -> None:
        index = {(ITEM, "aaaaaaaa"): {_sha(TEXT_A)}}
        same = tb.label_status((ITEM, "aaaaaaaa"), _sha(TEXT_A), index)
        changed = tb.label_status((ITEM, "aaaaaaaa"), _sha(TEXT_A2), index)
        fresh = tb.label_status((ITEM, "bbbbbbbb"), _sha(TEXT_B), index)
        assert (same, changed, fresh) == ("excluded", "new_text", "new_norm")
        assert tb.label_status((ITEM, "aaaaaaaa"), _sha(TEXT_A), None) is None

    def test_labelled_same_text_is_excluded_changed_text_is_selected(
        self, tmp_path: Path
    ) -> None:
        labels = tmp_path / "labels"
        _write_label(labels, ITEM, "lei", 1, "aaaaaaaa", _sha(TEXT_B))  # same text
        _write_label(labels, ITEM, "lei", 2, "bbbbbbbb", _sha(TEXT_A))  # old text
        path = _write_textos(
            tmp_path / "t.parquet",
            [
                _row(numero=1, uuid5="aaaaaaaa", text=TEXT_B),
                _row(numero=2, uuid5="bbbbbbbb", text=TEXT_A2),
                _row(numero=3, uuid5="cccccccc", text=TEXT_C),
            ],
        )
        plan = tb._prepare(
            **_prepare_kwargs(
                text_source="textos", textos=path, exclude_labelled=str(labels)
            )
        )
        assert plan.available == 3
        assert plan.labelled_excluded == [f"{ITEM}/aaaaaaaa"]
        assert sorted(n.key for n in plan.norms) == [
            f"{ITEM}/bbbbbbbb",
            f"{ITEM}/cccccccc",
        ]
        assert plan.status == {
            f"{ITEM}/bbbbbbbb": "new_text",
            f"{ITEM}/cccccccc": "new_norm",
        }
        assert plan.sources["exclude_labelled"]["labelled_norms"] == 2
        breakdown = tb._selection_breakdown(plan)
        assert breakdown["by_status"] == {"new_norm": 1, "new_text": 1}
        assert breakdown["by_tipo"] == {"lei": 2}

    def test_limit_counts_only_selected_norms(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels"
        _write_label(labels, ITEM, "lei", 1, "aaaaaaaa", _sha(TEXT_B))
        path = _write_textos(
            tmp_path / "t.parquet",
            [
                _row(numero=1, uuid5="aaaaaaaa", text=TEXT_B),
                _row(numero=2, uuid5="bbbbbbbb", text=TEXT_C),
            ],
        )
        plan = tb._prepare(
            **_prepare_kwargs(
                text_source="textos",
                textos=path,
                exclude_labelled=str(labels),
                limit=1,
            )
        )
        assert [n.key for n in plan.norms] == [f"{ITEM}/bbbbbbbb"]

    def test_ia_source_excludes_by_sha_after_fetch(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels"
        _write_label(labels, ITEM, "lei", 1, "aaaaaaaa", _sha(TEXT_B))
        _write_label(labels, ITEM, "lei", 2, "bbbbbbbb", _sha(TEXT_A))
        ref1 = tb.NormRef(
            ITEM, "casacivil", "lei", 1, "aaaaaaaa", "lei-00001_aaaaaaaa_djvu.txt"
        )
        ref2 = tb.NormRef(
            ITEM, "casacivil", "lei", 2, "bbbbbbbb", "lei-00002_bbbbbbbb_djvu.txt"
        )
        texts = {ref1: TEXT_B, ref2: TEXT_A2}  # ref2's text changed since labelling
        with (
            patch(
                "leizilla.teacher_batch.enumerate_norms",
                return_value=tb.Enumeration(norms=[ref1, ref2]),
            ),
            patch(
                "leizilla.teacher_batch.fetch_text",
                side_effect=lambda ref, cache_dir=None: texts[ref],
            ),
        ):
            plan = tb._prepare(
                **_prepare_kwargs(text_source="ia", exclude_labelled=str(labels))
            )
        assert plan.labelled_excluded == [ref1.key]
        assert [n.key for n in plan.norms] == [ref2.key]
        assert plan.status == {ref2.key: "new_text"}
        assert plan.available == 2

    def test_default_textos_download_is_loaded(self, tmp_path: Path) -> None:
        source = _write_textos(tmp_path / "published.parquet", [_row(text=TEXT_A)])

        def fake_download(url: str, dest: Path, **_: Any) -> None:
            assert url == tb.DEFAULT_TEXTOS_URL
            dest.write_bytes(source.read_bytes())

        with patch("leizilla.teacher_batch._download_to", side_effect=fake_download):
            corpus = tb._load_textos_corpus(None)
        assert [r.ref.key for r in corpus.records] == [f"{ITEM}/aaaaaaaa"]

    def test_label_index_from_ia_item_archive(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _write_label(src / "labels", ITEM, "lei", 1, "aaaaaaaa", _sha(TEXT_B))
        archive = tmp_path / "labels.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(src / "labels", arcname="labels")

        def fake_download(url: str, dest: Path, **_: Any) -> None:
            assert url.endswith("/leizilla-teacher-labels-ro-x/labels.tar.gz")
            dest.write_bytes(archive.read_bytes())

        with patch("leizilla.teacher_batch._download_to", side_effect=fake_download):
            index = tb.load_label_index("leizilla-teacher-labels-ro-x")
        assert index == {(ITEM, "aaaaaaaa"): {_sha(TEXT_B)}}

    def test_exclude_source_must_be_dir_or_item(self) -> None:
        with pytest.raises(tb.TeacherBatchError, match="neither a directory"):
            tb.load_label_index("not a valid/source")


# --------------------------------------------------------------------------
# Label sets
# --------------------------------------------------------------------------


class TestLabelSet:
    def test_name_rules(self) -> None:
        assert tb.check_label_set("holdout-2026-11") == "holdout-2026-11"
        for bad in ("", "Holdout", "a b", "x" * 33, "-x"):
            with pytest.raises(tb.TeacherBatchError):
                tb.check_label_set(bad)

    def test_identifier_keeps_main_unchanged(self) -> None:
        assert tb.ia_identifier("RO", "r1") == "leizilla-teacher-labels-ro-r1"
        assert (
            tb.ia_identifier("ro", "r1", "holdout-2026-11")
            == "leizilla-teacher-labels-ro-holdout-2026-11-r1"
        )

    def test_label_set_flows_into_manifest_summary_and_headers(
        self, tmp_path: Path
    ) -> None:
        path = _write_textos(tmp_path / "t.parquet", [_row(text=TEXT_A)])
        plan = tb._prepare(**_prepare_kwargs(text_source="textos", textos=path))
        spec = tb.MODELS[tb.DEFAULT_MODEL]
        estimate = tb.estimate_cost(plan, spec, "medium", True)
        manifest = tb.build_manifest(
            plan,
            estimate,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1.0,
            guard="ceiling",
            label_set="holdout-2026-11",
        )
        assert manifest["label_set"] == "holdout-2026-11"
        assert manifest["sources"]["text_source"] == "textos"

        client = MagicMock()
        client.messages.batches.create.return_value = SimpleNamespace(id="msgbatch_1")
        tb.submit_batches(
            client,
            plan,
            spec,
            manifest,
            tmp_path / "m.json",
            effort="medium",
            cache=True,
        )
        cid = plan.requests[0].custom_id
        client.messages.batches.results.return_value = [
            {
                "custom_id": cid,
                "result": {
                    "type": "succeeded",
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"labels":[],"amends":[]}'}
                        ],
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                },
            }
        ]
        summary = tb.collect_results(client, manifest, tmp_path / "out")
        assert summary["label_set"] == "holdout-2026-11"
        header = json.loads(
            next((tmp_path / "out" / "labels").rglob("*.jsonl"))
            .read_text()
            .splitlines()[0]
        )
        assert header["label_set"] == "holdout-2026-11"

    def test_upload_names_the_label_set(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        (out / "labels" / ITEM).mkdir(parents=True)
        (out / "labels" / ITEM / "lei-00001_aaaaaaaa.jsonl").write_text("{}\n")
        for name in ("failures.jsonl", "summary.json", "manifest.json"):
            (out / name).write_text("{}")
        seen: List[List[str]] = []

        def fake_upload(self: Any, args: List[str]) -> None:
            seen.append(args)

        summary = {
            "ente": "ro",
            "norms_ok": 1,
            "labels": 3,
            "label_set": "holdout-2026-11",
        }
        with patch.object(
            tb.publisher.InternetArchivePublisher, "_run_ia_upload", fake_upload
        ):
            result = tb.upload_to_ia(out, summary, revision="r1")
        assert result["ia_id"] == "leizilla-teacher-labels-ro-holdout-2026-11-r1"
        assert "subject:leis;leizilla;ro;labels;gold;holdout-2026-11" in seen[0]

    def test_collect_refuses_a_different_label_set(self, tmp_path: Path) -> None:
        manifest = tmp_path / "m.json"
        manifest.write_text(
            json.dumps(
                {
                    "manifest_version": tb.MANIFEST_VERSION,
                    "label_set": "holdout-2026-11",
                    "batches": [{"id": "msgbatch_1", "custom_ids": []}],
                }
            ),
            encoding="utf-8",
        )
        client = MagicMock()
        with patch("leizilla.teacher_batch._client", return_value=client):
            result = CliRunner().invoke(
                tb.app,
                [
                    "collect",
                    "--manifest",
                    str(manifest),
                    "--out-dir",
                    str(tmp_path / "o"),
                    "--label-set",
                    "main",
                ],
            )
        assert result.exit_code == 2 and "does not match" in result.output
        client.messages.batches.retrieve.assert_not_called()


# --------------------------------------------------------------------------
# CLI: plan spends nothing; the cost guard still refuses
# --------------------------------------------------------------------------


class TestCLI:
    runner = CliRunner()

    def test_plan_on_textos_calls_no_api_and_reports_counts(
        self, tmp_path: Path
    ) -> None:
        labels = tmp_path / "labels"
        _write_label(labels, ITEM, "lei", 1, "aaaaaaaa", _sha(TEXT_B))
        path = _write_textos(
            tmp_path / "t.parquet",
            [
                _row(numero=1, uuid5="aaaaaaaa", text=TEXT_B),
                _row(numero=2, uuid5="bbbbbbbb", text=TEXT_C, motor="kreuzberg"),
            ],
        )
        out = tmp_path / "plan.json"
        client_factory = MagicMock(side_effect=AssertionError("no API client"))
        with patch("leizilla.teacher_batch._client", client_factory):
            result = self.runner.invoke(
                tb.app,
                [
                    "plan",
                    "--text-source",
                    "textos",
                    "--textos",
                    str(path),
                    "--exclude-labelled",
                    str(labels),
                    "--model",
                    tb.DEFAULT_MODEL,
                    "--effort",
                    "medium",
                    "--out",
                    str(out),
                    "--fetch-delay",
                    "0",
                ],
            )
        assert result.exit_code == 0, result.output
        assert (
            "texts available: 2; excluded as labelled: 1; selected: 1" in result.output
        )
        assert "(new norms 1, new texts of labelled norms 0)" in result.output
        assert "claude-haiku-5-5 effort=medium" in result.output
        client_factory.assert_not_called()
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["text_source"] == "textos" and saved["label_set"] == "main"
        assert saved["excluded_as_labelled"] == 1
        assert saved["selection"]["by_ocr_motor"] == {"kreuzberg": 1}

    def test_cost_guard_still_refuses_on_textos(self, tmp_path: Path) -> None:
        path = _write_textos(
            tmp_path / "t.parquet",
            [_row(text="\n".join(f"Art. {i} - linha {i}" for i in range(1, 401)))],
        )
        manifest = tmp_path / "m.json"
        client_factory = MagicMock(side_effect=AssertionError("no API client"))
        with patch("leizilla.teacher_batch._client", client_factory):
            result = self.runner.invoke(
                tb.app,
                [
                    "submit",
                    "--text-source",
                    "textos",
                    "--textos",
                    str(path),
                    "--max-usd",
                    "0.0001",
                    "--manifest",
                    str(manifest),
                ],
            )
        assert result.exit_code == 2 and "cost guard" in result.output
        assert not manifest.exists()
        client_factory.assert_not_called()
