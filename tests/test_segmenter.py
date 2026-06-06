"""Tests for the regex baseline segmenter (ADR-0012 / docs/opf-finetune.md Pattern B)."""

from leizilla.segmenter import (
    Span,
    evaluate_against_gold,
    find_errors,
    format_report,
    format_structure,
    segment,
    validate_structure,
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


class TestComplexRules:
    def test_compiled_revogado_annotation_is_excluded(self):
        # "(Revogado pela Lei …)" is amendment history, not a revocation dispositivo.
        text = "Art. 5º Os contratos. (Revogado pela Lei nº 12.288, de 2010)."
        assert not any(c == "revogacao" for c, _ in _cats(text))

    def test_operative_revogacao_is_included(self):
        text = "Art. 9º Ficam revogados os arts. 5º a 8º desta Lei."
        assert any(c == "revogacao" for c, _ in _cats(text))

    def test_paragraph_right_context_reference_dropped(self):
        # "§ 7º do art. 226" inside an ementa/body is a reference, not a marker.
        text = "Regula o § 7º do art. 226 da Constituição Federal."
        assert not any(c == "par_marcador" for c, _ in _cats(text))

    def test_vetado_paragraph_dropped_keeps_real_one(self):
        text = "§ 2º (VETADO). § 2º A instalação do dispositivo faz-se."
        pars = [s for c, s in _cats(text) if c == "par_marcador"]
        assert pars == ["§ 2º"]  # only the real opening, the VETADO placeholder dropped

    def test_clause_span_strips_leading_marker(self):
        text = "Art. 3º Esta Lei entra em vigor na data de sua publicação."
        vig = [s for c, s in _cats(text) if c == "vigencia"]
        assert vig == ["Esta Lei entra em vigor na data de sua publicação."]

    def test_sentence_not_split_on_interior_abbreviations(self):
        # "art.", "nº 8.069" and the date carry interior periods that must NOT end the
        # sentence — the revogação clause is captured whole.
        text = (
            "Art. 4º Revoga-se o art. 233 da Lei nº 8.069, de 13 de julho de 1990 - "
            "Estatuto da Criança e do Adolescente."
        )
        rev = [s for c, s in _cats(text) if c == "revogacao"]
        assert rev == [
            "Revoga-se o art. 233 da Lei nº 8.069, de 13 de julho de 1990 - "
            "Estatuto da Criança e do Adolescente."
        ]


class TestEvaluateAgainstGold:
    def test_exact_and_overlap_counts(self):
        text = "Art. 1º Fica criado."
        gold: list[Span] = [{"category": "art_marcador", "start": 0, "end": 7}]
        scores = evaluate_against_gold([(text, gold)])
        s = scores["art_marcador"]
        assert s["gold"] == 1 and s["pred"] == 1
        assert s["exact_tp"] == 1
        assert s["overlap_tp_pred"] == 1 and s["overlap_tp_gold"] == 1

    def test_marker_excludes_trailing_period(self):
        # The regex emits the marker WITHOUT the trailing period (gold convention).
        text = "Art. 10. Disposições finais."
        assert any(c == "art_marcador" and s == "Art. 10" for c, s in _cats(text))

    def test_boundary_drift_is_overlap_not_exact(self):
        # gold tags "Art. 10." (with period); regex emits "Art. 10" — detected, not exact.
        text = "Art. 10. Disposições finais."
        gold: list[Span] = [{"category": "art_marcador", "start": 0, "end": 8}]
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


class TestFindErrors:
    def test_false_positive_is_reported(self):
        # gold has only "a)"; the segmenter also tags "b)" — a spurious prediction.
        text = "a) primeiro; b) segundo."
        gold: list[Span] = [{"category": "ali_marcador", "start": 0, "end": 2}]
        errs = find_errors([(text, gold)], ids=["doc"])
        fps = [e for e in errs if e["kind"] == "false_positive"]
        assert len(fps) == 1 and fps[0]["pred"] == "b)"
        assert fps[0]["doc"] == "doc"

    def test_boundary_is_reported_with_both_surfaces(self):
        text = "Art. 10. Foo."
        gold: list[Span] = [{"category": "art_marcador", "start": 0, "end": 8}]
        errs = find_errors([(text, gold)])
        boundary = [e for e in errs if e["kind"] == "boundary"]
        assert len(boundary) == 1
        assert boundary[0]["pred"] == "Art. 10" and boundary[0]["gold"] == "Art. 10."

    def test_false_negative_when_marker_missing(self):
        # gold claims an article the text doesn't actually open as a marker.
        text = "uma referência ao art. 99 da outra lei."
        gold: list[Span] = [{"category": "art_marcador", "start": 18, "end": 25}]
        errs = find_errors([(text, gold)])
        assert any(e["kind"] == "false_negative" for e in errs)


class TestValidateStructure:
    def test_detects_missing_article(self):
        text = "Art. 1º um. Art. 3º três."
        findings = validate_structure(text)
        kinds = {f["kind"]: f["detail"] for f in findings}
        assert "missing_articles" in kinds and "2" in kinds["missing_articles"]

    def test_contiguous_articles_have_no_gap(self):
        text = "Art. 1º um. Art. 2º dois. Art. 3º três."
        assert not any(
            f["kind"] == "missing_articles" for f in validate_structure(text)
        )

    def test_letter_suffix_is_not_a_gap(self):
        # "Art. 1º-A" shares base number 1 — must not create a gap or out-of-order.
        text = "Art. 1º um. Art. 1º-A inserido. Art. 2º dois."
        findings = validate_structure(text)
        assert not any(f["kind"] == "missing_articles" for f in findings)
        assert not any(f["kind"] == "out_of_order" for f in findings)

    def test_out_of_order_flagged(self):
        text = "Art. 1º a. Art. 2º b. Art. 1º c."
        assert any(f["kind"] == "out_of_order" for f in validate_structure(text))

    def test_no_articles(self):
        findings = validate_structure("Apenas um texto sem dispositivos.")
        assert any(f["kind"] == "no_articles" for f in findings)

    def test_clean_norma_formats_ok(self):
        text = (
            "LEI Nº 1, DE 1 DE JANEIRO DE 2020. Dispõe sobre algo. Faço saber "
            "Art. 1º Fica criado. Art. 2º Esta Lei entra em vigor na data de sua "
            "publicação."
        )
        findings = validate_structure(text)
        assert not any(f["kind"] == "missing_articles" for f in findings)
        assert "✅" in format_structure([])
