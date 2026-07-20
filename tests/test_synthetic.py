"""Tests for the synthetic norma generator (OPF Phase 2.5, Path 4).

The load-bearing property is offset exactness by construction:
``text[start:end] == surface`` for every span, no overlaps, categories in the
committed label space. Surfaces must also stay in-regime with segmenter.py's
own cue patterns (so synthetic doesn't drift from the conventions gold uses).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, cast

from typer.testing import CliRunner

from leizilla import synthetic
from leizilla.cli import app
from leizilla.opf import load_label_space
from leizilla.segmenter import _REVOGA_OPERATIVE, _VIGENCIA_CUE, segment

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL_SPACE = REPO_ROOT / "data" / "opf" / "label_space.json"


class TestBuildNorma:
    def test_offsets_are_exact_by_construction(self) -> None:
        for seed in range(10):
            text, spans = synthetic.build_norma(seed)
            for sp in spans:
                surface = text[sp["start"] : sp["end"]]
                assert surface == surface.strip()
                assert surface

    def test_no_overlapping_spans(self) -> None:
        for seed in range(10):
            _text, spans = synthetic.build_norma(seed)
            for a, b in zip(spans, spans[1:]):
                assert b["start"] >= a["end"], (a, b)

    def test_categories_in_committed_label_space(self) -> None:
        _version, names = load_label_space(LABEL_SPACE)
        _text, spans = synthetic.build_norma(7)
        for sp in spans:
            assert sp["category"] in names

    def test_deterministic_for_seed(self) -> None:
        assert synthetic.build_norma(42) == synthetic.build_norma(42)
        assert synthetic.build_norma(42) != synthetic.build_norma(43)

    def test_feeds_starved_categories_on_demand(self) -> None:
        _text, spans = synthetic.build_norma(1, ali_per_inciso=4)
        cats = [s["category"] for s in spans]
        assert cats.count("ali_marcador") >= 4
        assert "vigencia" in cats
        assert "revogacao" in cats
        assert "ementa" in cats

    def test_vigencia_revogacao_surfaces_match_segmenter_cues(self) -> None:
        """Synthetic surfaces must stay in-regime with the real cue patterns."""
        text, spans = synthetic.build_norma(3)
        for sp in spans:
            surface = text[sp["start"] : sp["end"]]
            if sp["category"] == "vigencia":
                assert _VIGENCIA_CUE.search(surface)
            if sp["category"] == "revogacao":
                assert _REVOGA_OPERATIVE.search(surface)

    def test_hard_negatives_present_but_unlabeled(self) -> None:
        text, spans = synthetic.build_norma(5, hard_negatives=True)
        # at least one hard-negative surface must appear in the text...
        present = [neg for neg, _why in synthetic._HARD_NEGATIVES if neg in text]
        assert present, "no hard negative was injected"
        # ...and no span may cover the marker-shaped part inside it.
        for neg in present:
            neg_start = text.index(neg)
            neg_end = neg_start + len(neg)
            for sp in spans:
                assert not (sp["start"] >= neg_start and sp["end"] <= neg_end), (
                    f"span {sp} labels inside hard negative {neg!r}"
                )

    def test_clean_profile_agrees_with_regex_baseline_on_markers(self) -> None:
        """On clean (no OCR noise) text the regex baseline should re-find the
        marker spans — synthetic that regex can't parse would be off-regime.
        (Cue-clause boundaries legitimately differ; markers must not.)
        """
        text, spans = synthetic.build_norma(11, ocr_noise=False, hard_negatives=False)
        regex_spans = {
            (s["category"], s["start"], s["end"])
            for s in segment(text)
            if s["category"].endswith("_marcador")
        }
        for sp in spans:
            if sp["category"].endswith("_marcador"):
                assert (sp["category"], sp["start"], sp["end"]) in regex_spans, (
                    sp,
                    text[sp["start"] : sp["end"]],
                )

    def test_ocr_noise_produces_off_regex_surfaces(self) -> None:
        """The OCR-noise regime must produce at least some marker surfaces the
        regex misses — that residual is the model's whole territory."""
        missed_any = False
        for seed in range(20):
            text, spans = synthetic.build_norma(seed, ocr_noise=True)
            regex_found = {(s["category"], s["start"], s["end"]) for s in segment(text)}
            for sp in spans:
                if (
                    sp["category"].endswith("_marcador")
                    and (sp["category"], sp["start"], sp["end"]) not in regex_found
                ):
                    missed_any = True
        assert missed_any


class TestBuildDataset:
    def test_records_are_opf_schema_with_provenance(self) -> None:
        records, manifest = synthetic.build_dataset(5, seed=13)
        assert len(records) == 5
        for rec_obj in records:
            rec = cast(Dict[str, Any], rec_obj)
            assert set(rec) == {"text", "label", "info"}
            assert rec["info"]["source"] == "synthetic"
            assert "seed" in rec["info"]
        assert manifest["n"] == 5
        assert "training-mix only" in str(manifest["usage"])

    def test_manifest_counts_match_records(self) -> None:
        records, manifest = synthetic.build_dataset(4, seed=1)
        counted: Dict[str, int] = {}
        for rec_obj in records:
            rec = cast(Dict[str, Any], rec_obj)
            labels = cast(List[Dict[str, Any]], rec["label"])
            for sp in labels:
                counted[sp["category"]] = counted.get(sp["category"], 0) + 1
        assert manifest["spans_per_category"] == dict(sorted(counted.items()))

    def test_deterministic(self) -> None:
        a_records, _a = synthetic.build_dataset(3, seed=7)
        b_records, _b = synthetic.build_dataset(3, seed=7)
        assert a_records == b_records


class TestCmdOpfSynth:
    def test_writes_jsonl_and_manifest(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["opf-synth", "--n", "3", "--out-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        synth = tmp_path / "synthetic.jsonl"
        manifest = tmp_path / "synthetic_manifest.json"
        assert synth.exists() and manifest.exists()
        lines = synth.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        rec = json.loads(lines[0])
        assert rec["info"]["source"] == "synthetic"
        assert "NUNCA val/test" in result.output
