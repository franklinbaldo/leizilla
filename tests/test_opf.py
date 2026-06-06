"""Tests for OPF fine-tune data prep (ADR-0012): sampler, pool, label space, CLI.

All IO is offline — the IA list/fetch seams are injected. See src/leizilla/opf.py.
"""

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from leizilla import opf
from leizilla.cli import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL_SPACE = REPO_ROOT / "data" / "opf" / "label_space.json"
ANNOTATE = REPO_ROOT / "scripts" / "opf_annotate.py"


class TestParseSources:
    def test_splits_and_dedups(self):
        sources = opf.parse_sources("ro", "assembleia, casacivil ,assembleia")
        assert [s.label for s in sources] == ["ro/assembleia", "ro/casacivil"]

    def test_drops_blanks(self):
        assert opf.parse_sources("ro", " , ,") == []


class TestSampleRawIds:
    def test_takes_all_when_n_exceeds(self):
        ids = {"b", "a", "c"}
        assert opf.sample_raw_ids(ids, 10, seed=1) == ["a", "b", "c"]

    def test_deterministic_for_seed(self):
        ids = [f"id-{i:03d}" for i in range(100)]
        a = opf.sample_raw_ids(ids, 5, seed=13)
        b = opf.sample_raw_ids(ids, 5, seed=13)
        assert a == b
        assert len(a) == 5

    def test_seed_changes_draw(self):
        ids = [f"id-{i:03d}" for i in range(100)]
        a = opf.sample_raw_ids(ids, 5, seed=13)
        b = opf.sample_raw_ids(ids, 5, seed=99)
        assert a != b

    def test_input_order_does_not_perturb(self):
        ids = [f"id-{i:03d}" for i in range(50)]
        forward = opf.sample_raw_ids(ids, 7, seed=5)
        backward = opf.sample_raw_ids(list(reversed(ids)), 7, seed=5)
        assert forward == backward


def _fake_list(mapping):
    return lambda ente, fonte: mapping.get((ente, fonte), set())


def _fake_fetch(texts):
    return lambda raw_id: texts.get(raw_id)


class TestBuildAnnotationPool:
    def test_stratifies_across_sources(self):
        sources = [opf.Source("ro", "assembleia"), opf.Source("ro", "casacivil")]
        list_fn = _fake_list(
            {
                ("ro", "assembleia"): {"a1", "a2"},
                ("ro", "casacivil"): {"c1", "c2"},
            }
        )
        body = "x" * 300
        fetch_fn = _fake_fetch({"a1": body, "a2": body, "c1": body, "c2": body})

        result = opf.build_annotation_pool(
            sources,
            n_per_source=2,
            seed=1,
            min_chars=200,
            list_fn=list_fn,
            fetch_fn=fetch_fn,
        )

        assert len(result.records) == 4
        fontes = {r["info"]["fonte"] for r in result.records}  # type: ignore[index]
        assert fontes == {"assembleia", "casacivil"}
        assert result.manifest["per_source"]["ro/assembleia"]["kept"] == 2

    def test_skips_short_and_missing_ocr(self):
        sources = [opf.Source("ro", "assembleia")]
        list_fn = _fake_list({("ro", "assembleia"): {"ok", "short", "missing"}})
        fetch_fn = _fake_fetch({"ok": "y" * 300, "short": "tiny", "missing": None})

        result = opf.build_annotation_pool(
            sources,
            n_per_source=3,
            seed=1,
            min_chars=200,
            list_fn=list_fn,
            fetch_fn=fetch_fn,
        )

        assert len(result.records) == 1
        assert result.records[0]["info"]["raw_id"] == "ok"  # type: ignore[index]
        counts = result.manifest["per_source"]["ro/assembleia"]
        assert counts["kept"] == 1
        assert counts["skipped"] == 2

    def test_records_are_opf_schema_with_empty_label(self):
        sources = [opf.Source("ro", "casacivil")]
        list_fn = _fake_list({("ro", "casacivil"): {"c1"}})
        fetch_fn = _fake_fetch({"c1": "z" * 300})

        result = opf.build_annotation_pool(
            sources,
            n_per_source=1,
            list_fn=list_fn,
            fetch_fn=fetch_fn,
        )

        rec = result.records[0]
        assert set(rec) == {"text", "label", "info"}
        assert rec["label"] == []
        assert rec["info"] == {"raw_id": "c1", "ente": "ro", "fonte": "casacivil"}

    def test_cap_clamps_allocation(self):
        sources = [opf.Source("ro", "assembleia")]
        ids = {f"id-{i}" for i in range(20)}
        list_fn = _fake_list({("ro", "assembleia"): ids})
        fetch_fn = lambda raw_id: "w" * 300  # noqa: E731
        result = opf.build_annotation_pool(
            sources,
            n_per_source=15,
            cap=5,
            list_fn=list_fn,
            fetch_fn=fetch_fn,
        )
        assert result.manifest["allocation"]["effective_target"] == 5
        assert len(result.records) == 5

    def test_manifest_has_reproducibility_fields(self):
        result = opf.build_annotation_pool(
            [opf.Source("ro", "x")],
            n_per_source=1,
            list_fn=_fake_list({}),
            fetch_fn=_fake_fetch({}),
        )
        m = result.manifest
        assert m["category_version"] == opf.CATEGORY_VERSION
        assert m["seed"] == 13
        assert "generated_at" in m


class TestWriteHelpers:
    def test_write_pool_and_manifest_roundtrip(self, tmp_path: Path):
        records = [{"text": "abc", "label": [], "info": {"raw_id": "r1"}}]
        pool = tmp_path / "sub" / "pool.jsonl"
        n = opf.write_pool(records, pool)
        assert n == 1
        loaded = [
            json.loads(line) for line in pool.read_text(encoding="utf-8").splitlines()
        ]
        assert loaded == records

        manifest = tmp_path / "sub" / "m.json"
        opf.write_manifest({"seed": 13}, manifest)
        assert json.loads(manifest.read_text(encoding="utf-8")) == {"seed": 13}


class TestLabelSpace:
    def test_committed_label_space_is_valid(self):
        version, names = opf.load_label_space(LABEL_SPACE)
        assert version == "leizilla_normas_v1"
        assert names[0] == "O"
        assert "art_marcador" in names

    def test_rejects_missing_background_class(self, tmp_path: Path):
        bad = tmp_path / "ls.json"
        bad.write_text(json.dumps({"span_class_names": ["art_marcador"]}))
        try:
            opf.load_label_space(bad)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "first" in str(e)


class TestCmdOpfSample:
    def test_writes_pool_and_manifest(self, tmp_path: Path, monkeypatch):
        def fake_pool(sources, **kwargs):
            return opf.PoolResult(
                records=[{"text": "t", "label": [], "info": {"raw_id": "r1"}}],
                manifest={
                    "per_source": {
                        "ro/assembleia": {
                            "available": 1,
                            "picked": 1,
                            "kept": 1,
                            "skipped": 0,
                        }
                    }
                },
            )

        monkeypatch.setattr(opf, "build_annotation_pool", fake_pool)
        out = tmp_path / "pool"
        result = runner.invoke(
            app,
            [
                "opf-sample",
                "--ente",
                "ro",
                "--fontes",
                "assembleia",
                "--out-dir",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out / "pool.jsonl").exists()
        assert (out / "sample_manifest.json").exists()

    def test_no_valid_fontes_exits_nonzero(self, tmp_path: Path):
        result = runner.invoke(app, ["opf-sample", "--fontes", " , "])
        assert result.exit_code == 1


class TestVendoredAnnotateScript:
    """The vendored helper is the CI gate on gold offsets; smoke-test it end to end."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ANNOTATE), *args],
            capture_output=True,
            text=True,
        )

    def test_validate_passes_clean_file(self, tmp_path: Path):
        rec = {
            "text": "Art. 5º Fica criado.",
            "label": [{"category": "art_marcador", "start": 0, "end": 6}],
        }
        f = tmp_path / "train.jsonl"
        f.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        r = self._run("validate", str(f), "--label-space", str(LABEL_SPACE))
        assert r.returncode == 0, r.stderr

    def test_validate_catches_bad_offsets(self, tmp_path: Path):
        rec = {
            "text": "Art. 5º",
            "label": [{"category": "art_marcador", "start": 0, "end": 999}],
        }
        f = tmp_path / "bad.jsonl"
        f.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        r = self._run("validate", str(f))
        assert r.returncode == 1
        assert "offsets" in r.stderr.lower()

    def test_validate_catches_unknown_category(self, tmp_path: Path):
        rec = {"text": "Art. 5º", "label": [{"category": "nope", "start": 0, "end": 6}]}
        f = tmp_path / "u.jsonl"
        f.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        r = self._run("validate", str(f), "--label-space", str(LABEL_SPACE))
        assert r.returncode == 1

    def test_from_spans_resolves_match_offsets(self, tmp_path: Path):
        rec = {
            "text": "Ementa: cria o fundo.",
            "finds": [{"category": "ementa", "match": "cria o fundo"}],
        }
        src = tmp_path / "raw.jsonl"
        src.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        out = tmp_path / "out.jsonl"
        r = self._run("from-spans", str(src), "--output", str(out))
        assert r.returncode == 0, r.stderr
        result = json.loads(out.read_text(encoding="utf-8").strip())
        span = result["label"][0]
        assert result["text"][span["start"] : span["end"]] == "cria o fundo"
