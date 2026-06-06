"""Tests for the regex baseline segmenter (ADR-0012 / docs/opf-finetune.md Pattern B)."""

from leizilla.segmenter import (
    Span,
    evaluate_against_gold,
    format_report,
    segment,
)


def _cats(text: str) -> list[tuple[str, str]]:
    return [(s["category"], text[s["start"] : s["end"]]) for s in segment(text)]


class TestSegmentMarkers:
    def test_article_and_paragraph_and_inciso_and_alinea(self):
        text = "Art. 1º Fica criado. § 1º Aplica-se. I - um caso; a) item."
        found = _cats(text)
        assert ("art_marcador", "Art. 1º") in found
        assert ("par_marcador", "§ 1º") in found
        assert ("inc_marcador", "I -") in found
        assert ("ali_marcador", "a)") in found

    def test_lowercase_art_reference_is_not_a_marker(self):
        # "o art. 5º da Constituição" is a cross-reference, not a dispositivo opening.
        text = "Regula o art. 5º da Constituição Federal."
        assert not any(c == "art_marcador" for c, _ in _cats(text))

    def test_paragraph_cross_reference_is_dropped(self):
        text = "No caso do § 2º deste artigo, aplica-se a regra."
        assert not any(c == "par_marcador" for c, _ in _cats(text))

    def test_article_marker_with_letter_suffix(self):
        text = "Art. 8º-A. Aplica-se também."
        assert any(c == "art_marcador" and "8º-A" in s for c, s in _cats(text))

    def test_paragrafo_unico(self):
        text = "Art. 2º Texto. Parágrafo único. Exceção."
        assert any(
            c == "par_marcador" and "Parágrafo único" in s for c, s in _cats(text)
        )


class TestSegmentClauses:
    def test_vigencia_sentence_detected(self):
        text = "Art. 9º Esta Lei entra em vigor na data de sua publicação."
        assert any(c == "vigencia" and "em vigor" in s for c, s in _cats(text))

    def test_revogacao_sentence_detected(self):
        text = "Art. 10. Revogam-se as disposições em contrário."
        assert any(
            c == "revogacao" and s.startswith("Revogam-se") for c, s in _cats(text)
        )

    def test_ementa_between_header_and_enacting_clause(self):
        text = (
            "LEI Nº 9.455, DE 7 DE ABRIL DE 1997. "
            "Define os crimes de tortura. "
            "O PRESIDENTE DA REPÚBLICA Faço saber"
        )
        ementas = [s for c, s in _cats(text) if c == "ementa"]
        assert ementas and "Define os crimes de tortura" in ementas[0]


class TestEvaluateAgainstGold:
    def test_exact_and_overlap_counts(self):
        text = "Art. 1º Fica criado."
        gold: list[Span] = [{"category": "art_marcador", "start": 0, "end": 7}]
        scores = evaluate_against_gold([(text, gold)])
        s = scores["art_marcador"]
        assert s["gold"] == 1 and s["pred"] == 1
        assert s["exact_tp"] == 1
        assert s["overlap_tp_pred"] == 1 and s["overlap_tp_gold"] == 1

    def test_boundary_drift_is_overlap_not_exact(self):
        # gold tags "Art. 10" (no period); regex emits "Art. 10." — detected, not exact.
        text = "Art. 10. Disposições finais."
        gold: list[Span] = [{"category": "art_marcador", "start": 0, "end": 7}]
        scores = evaluate_against_gold([(text, gold)])
        s = scores["art_marcador"]
        assert s["exact_tp"] == 0
        assert s["overlap_tp_gold"] == 1  # boundary differs but the span is found

    def test_false_positive_lowers_precision(self):
        # A spurious extra prediction with no matching gold span.
        text = "a) primeiro; b) segundo."
        gold: list[Span] = [{"category": "ali_marcador", "start": 0, "end": 2}]
        scores = evaluate_against_gold([(text, gold)])
        s = scores["ali_marcador"]
        assert s["pred"] == 2 and s["gold"] == 1
        assert s["overlap_tp_pred"] == 1  # only one prediction overlaps gold

    def test_format_report_runs(self):
        text = "Art. 1º Fica criado."
        gold: list[Span] = [{"category": "art_marcador", "start": 0, "end": 7}]
        report = format_report(evaluate_against_gold([(text, gold)]))
        assert "art_marcador" in report and "MICRO" in report
