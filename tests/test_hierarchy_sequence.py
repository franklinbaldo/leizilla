"""Tests for the sequence-aware hierarchy reader (offline, deterministic)."""

import time

import pytest

from leizilla.hierarchy_sequence import (
    HierarchyReport,
    alinea_readings,
    article_closes,
    marker_spans,
    read_hierarchy,
    roman_readings,
)
from leizilla.segmenter import evaluate_against_gold


def _paths(report: HierarchyReport, status: str = "own") -> list[str | None]:
    nodes = sorted(report["nodes"], key=lambda n: n["start"])
    return [n["path"] for n in nodes if n["status"] == status and n["path"]]


def _node(report: HierarchyReport, path: str, status: str = "own") -> dict:
    hits = [n for n in report["nodes"] if n["path"] == path and n["status"] == status]
    assert len(hits) == 1, f"{path}: {len(hits)} nodes"
    return dict(hits[0])


def _unexplained(report: HierarchyReport) -> list[str]:
    return [x["raw"] for x in report["leftovers"] if x["status"] == "unexplained"]


CLEAN = (
    "Art. 1º Constitui crime:\n"
    "I - constranger alguém:\n"
    "a) com o fim de obter;\n"
    "b) para provocar;\n"
    "II - submeter alguém.\n"
    "§ 1º Na mesma pena incorre.\n"
    "§ 2º Aquele que se omite:\n"
    "I - primeiro;\n"
    "II - segundo.\n"
    "Art. 2º Esta Lei entra em vigor.\n"
    "Palácio do Governo, 7 de abril de 1997."
)


# --- the tree ---------------------------------------------------------------------
def test_clean_norm_builds_the_nested_tree_and_closes() -> None:
    report = read_hierarchy(CLEAN)
    assert _paths(report) == [
        "art-1",
        "art-1-inc-1",
        "art-1-inc-1-ali-a",
        "art-1-inc-1-ali-b",
        "art-1-inc-2",
        "art-1-par-1",
        "art-1-par-2",
        "art-1-par-2-inc-1",
        "art-1-par-2-inc-2",
        "art-2",
    ]
    assert report["closes"]
    assert all(level["closes"] for level in report["levels"].values())
    assert not report["leftovers"]
    assert not any(n["corrected"] for n in report["nodes"])


def test_offsets_are_verbatim_and_parents_link_both_ways() -> None:
    report = read_hierarchy(CLEAN)
    nodes = report["nodes"]
    for node in nodes:
        assert CLEAN[node["start"] : node["start"] + len(node["raw"])] == node["raw"]
        assert node["start"] <= node["text_start"] <= node["text_end"] <= node["end"]
        for child in node["children"]:
            assert nodes[child]["parent"] == node["id"]
            assert node["start"] <= nodes[child]["start"] < node["end"]
    alinea = _node(report, "art-1-inc-1-ali-b")
    assert CLEAN[alinea["text_start"] : alinea["text_end"]] == "para provocar;"
    inciso = _node(report, "art-1-inc-1")
    assert CLEAN[inciso["text_start"] : inciso["text_end"]] == "constranger alguém:"
    assert nodes[alinea["parent"]]["path"] == "art-1-inc-1"
    # The last article stops at the closing formula, not at the end of the file.
    assert CLEAN[report["body_end"] :].lstrip().startswith("Palácio")
    assert _node(report, "art-2")["end"] == report["body_end"]


def test_article_dash_is_a_separator_not_a_letter_suffix() -> None:
    text = "Art. 1º - A lei vale.\nArt. 2º - O prazo corre."
    report = read_hierarchy(text)
    first = _node(report, "art-1")
    assert first["raw"] == "Art. 1º"
    assert first["suffix"] is None
    assert text[first["text_start"] : first["text_end"]] == "A lei vale."


def test_single_line_text_is_read_like_a_wrapped_one() -> None:
    text = (
        "Art. 1º Constitui crime: I - constranger alguém: a) com o fim; b) para "
        "provocar; II - submeter. § 1º Na mesma pena. § 2º Aquele que. "
        "Art. 2º Vigora."
    )
    report = read_hierarchy(text)
    assert _paths(report) == [
        "art-1",
        "art-1-inc-1",
        "art-1-inc-1-ali-a",
        "art-1-inc-1-ali-b",
        "art-1-inc-2",
        "art-1-par-1",
        "art-1-par-2",
        "art-2",
    ]
    assert report["closes"]


# --- paragraphs -------------------------------------------------------------------
def test_paragraph_sign_ocr_variants_are_read() -> None:
    text = (
        "Art. 1º Texto.\n$ 1º Um.\nS 2º Dois.\n8 3º Três.\n§4º Quatro.\n"
        "94 5º Cinco.\nArt. 2º Fim."
    )
    report = read_hierarchy(text)
    assert _paths(report)[1:6] == [f"art-1-par-{n}" for n in range(1, 6)]
    assert report["levels"]["paragrafo"]["closes"]
    # A glyph that is not "§" is a corrected reading; the glued "§4º" is literal.
    assert _node(report, "art-1-par-1")["corrected"]
    assert _node(report, "art-1-par-5")["corrected"]
    assert not _node(report, "art-1-par-4")["corrected"]


def test_paragraph_ordinal_misreads_are_resolved_by_sequence() -> None:
    # "Io" is 1º, "22" between 1 and 3 is 2º, "3Q" is 3º.
    text = "Art. 1º Texto.\n§ Io Um.\n§ 22 Dois.\n§ 3Q Três.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert _paths(report)[1:4] == ["art-1-par-1", "art-1-par-2", "art-1-par-3"]
    assert _node(report, "art-1-par-2")["corrected"]
    assert not _node(report, "art-1-par-3")["corrected"]
    assert report["closes"]


def test_paragraphs_restart_in_every_article() -> None:
    text = (
        "Art. 1º A.\n§ 1º Um.\n§ 2º Dois.\n"
        "Art. 2º B.\n§ 1º Um.\n§ 2º Dois.\n§ 3º Três.\n"
        "Art. 3º C.\nParágrafo único. Só um."
    )
    report = read_hierarchy(text)
    assert _paths(report) == [
        "art-1",
        "art-1-par-1",
        "art-1-par-2",
        "art-2",
        "art-2-par-1",
        "art-2-par-2",
        "art-2-par-3",
        "art-3",
        "art-3-par-unico",
    ]
    assert report["closes"]
    unico = _node(report, "art-3-par-unico")
    assert text[unico["text_start"] : unico["text_end"]] == "Só um."


def test_paragrafo_unico_next_to_numbered_paragraphs_does_not_close() -> None:
    text = "Art. 1º Fica.\nParágrafo único. Um.\n§ 2º Dois.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert not report["levels"]["paragrafo"]["closes"]
    assert not report["closes"]


def test_unreadable_paragraph_number_is_read_in_a_single_gap() -> None:
    # "§ T" is what OCR makes of "§ 7º".
    lines = [f"§ {n}º Texto." for n in range(1, 7)] + ["§ T Texto.", "§ 8º Texto."]
    report = read_hierarchy("Art. 1º Caput.\n" + "\n".join(lines) + "\nArt. 2º Fim.")
    seventh = _node(report, "art-1-par-7")
    assert seventh["raw"] == "§ T"
    assert seventh["corrected"]
    assert report["closes"]


# --- incisos ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("I", 1),
        ("l", 1),
        ("1", 1),
        ("|", 1),
        ("H", 2),
        ("11", 2),
        ("Il", 2),
        ("HI", 3),
        ("IH", 3),
        ("111", 3),
        ("Ill", 3),
        ("lV", 4),
        ("TV", 4),
        ("VH", 7),
        ("VHI", 8),
        ("XLIV", 44),
    ],
)
def test_roman_readings_cover_the_ocr_confusions(token: str, expected: int) -> None:
    assert roman_readings(token)[0] == expected


def test_roman_readings_keep_the_ambiguity_for_the_chain() -> None:
    assert set(roman_readings("IH")) == {2, 3}
    assert roman_readings("Vm") == ()
    assert roman_readings("IIII") == ()


def test_inciso_look_alikes_are_read_by_sequence() -> None:
    text = (
        "Art. 1º Compete:\nl - um;\nH - dois;\nHI - três;\nlV - quatro;\nV - cinco.\n"
        "Art. 2º Também:\n1 - um;\n11 - dois;\n111 - três.\n"
        "Art. 3º Ainda:\nI - um;\nIH - dois;\nHI - três."
    )
    report = read_hierarchy(text)
    assert _paths(report) == [
        "art-1",
        *(f"art-1-inc-{n}" for n in range(1, 6)),
        "art-2",
        *(f"art-2-inc-{n}" for n in range(1, 4)),
        "art-3",
        *(f"art-3-inc-{n}" for n in range(1, 4)),
    ]
    assert _node(report, "art-1-inc-2")["corrected"]
    assert not _node(report, "art-1-inc-5")["corrected"]
    # "IH" could be III; after "I" and before "HI" it is II.
    assert _node(report, "art-3-inc-2")["raw"] == "IH -"
    assert report["closes"]


def test_incisos_restart_in_the_caput_and_in_each_paragraph() -> None:
    text = (
        "Art. 1º Caput:\nI - a;\nII - b.\n"
        "§ 1º Primeiro:\nI - c;\nII - d;\nIII - e.\n"
        "§ 2º Segundo:\nI - f;\nII - g.\n"
        "Art. 2º Outro:\nI - h;\nII - i."
    )
    report = read_hierarchy(text)
    assert report["levels"]["inciso"]["scopes"] == 4
    assert (
        _node(report, "art-1-par-1-inc-3")["parent"]
        == _node(report, "art-1-par-1")["id"]
    )
    assert "art-2-inc-2" in _paths(report)
    assert report["closes"]


def test_duplicated_and_garbled_numerals_fill_a_single_gap() -> None:
    text = (
        "Art. 1º Compete:\nI - um;\nII - dois;\nNI — três;\nIV - quatro;\n"
        "V - cinco;\nVI - seis;\nVII - sete;\nVII - oito;\nIX - nove.\nArt. 2º Fim."
    )
    report = read_hierarchy(text)
    third = _node(report, "art-1-inc-3")
    eighth = _node(report, "art-1-inc-8")
    assert (third["raw"], third["corrected"]) == ("NI —", True)
    assert (eighth["raw"], eighth["corrected"]) == ("VII -", True)
    assert not _node(report, "art-1-inc-7")["corrected"]
    assert report["closes"]


def test_two_missing_incisos_are_not_invented() -> None:
    text = "Art. 1º Compete:\nI - um;\nXX - ruído;\nIV - quatro.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert not report["levels"]["inciso"]["closes"]
    assert not report["closes"]


def test_glued_dash_is_a_marker_only_at_the_line_start() -> None:
    text = (
        "Art. 1º Compõem o quadro:\nI-01 gerente;\nII-05 chefes.\n"
        "Art. 2º O anexo V-A e a tabela I-B ficam mantidos."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-1-inc-1", "art-1-inc-2", "art-2"]
    assert report["closes"]


# --- alíneas and itens ------------------------------------------------------------
def test_alinea_readings_cover_the_ocr_confusions() -> None:
    assert alinea_readings("c") == (3, 5, 15)
    assert alinea_readings("o")[:2] == (15, 3)
    assert 2 in alinea_readings("6")
    assert 2 in alinea_readings("h")
    assert alinea_readings("l") == (12, 9)


def test_alineas_restart_in_every_inciso_and_are_read_by_sequence() -> None:
    text = (
        "Art. 1º Compete:\nI - um:\na) x;\nb) y;\no) z;\nd) w;\n"
        "II - dois:\na) x;\n6) y;\nc) z.\nArt. 2º Fim."
    )
    report = read_hierarchy(text)
    assert _paths(report) == [
        "art-1",
        "art-1-inc-1",
        *(f"art-1-inc-1-ali-{x}" for x in "abcd"),
        "art-1-inc-2",
        *(f"art-1-inc-2-ali-{x}" for x in "abc"),
        "art-2",
    ]
    assert _node(report, "art-1-inc-1-ali-c")["raw"] == "o)"
    assert _node(report, "art-1-inc-1-ali-c")["corrected"]
    assert _node(report, "art-1-inc-2-ali-b")["raw"] == "6)"
    assert report["closes"]


def test_alineas_may_hang_directly_from_a_caput_or_paragraph() -> None:
    text = "Art. 1º São símbolos:\na) a bandeira;\nb) o hino.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-1-ali-a", "art-1-ali-b", "art-2"]
    assert report["closes"]


def test_alineas_may_skip_k() -> None:
    letters = "abcdefghijlm"
    body = "\n".join(f"{x}) texto;" for x in letters)
    report = read_hierarchy(f"Art. 1º Lista:\n{body}\nArt. 2º Fim.")
    assert report["levels"]["alinea"]["nodes"] == len(letters)
    assert report["levels"]["alinea"]["closes"]


def test_itens_are_read_inside_an_alinea() -> None:
    text = (
        "Art. 1º Compete:\nI - um:\na) x:\n1. primeiro;\n2. segundo;\n3. terceiro;\n"
        "b) y.\nArt. 2º Fim."
    )
    report = read_hierarchy(text)
    assert [p for p in _paths(report) if p and "item" in p] == [
        f"art-1-inc-1-ali-a-item-{n}" for n in (1, 2, 3)
    ]
    assert (
        _node(report, "art-1-inc-1-ali-b")["parent"]
        == _node(report, "art-1-inc-1")["id"]
    )
    assert report["closes"]


def test_arabic_list_is_not_mistaken_for_incisos() -> None:
    text = "Art. 1º Lista:\n1 - um;\n2 - dois;\n3 - três.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert report["levels"]["inciso"]["nodes"] == 0
    assert _paths(report) == [
        "art-1",
        "art-1-item-1",
        "art-1-item-2",
        "art-1-item-3",
        "art-2",
    ]


# --- citations --------------------------------------------------------------------
def test_in_sentence_citations_are_references_at_every_level() -> None:
    text = (
        "Art. 1º Aplica-se o § 2º do art. 5º e o inciso II - da lei, alíneas a) e "
        "b), ao caso.\nParágrafo único. Vale o disposto no\n§ 3º deste artigo.\n"
        "Art. 2º Fim."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-1-par-unico", "art-2"]
    kinds = sorted((x["kind"], x["status"]) for x in report["leftovers"])
    assert kinds == [
        ("alinea", "reference"),
        ("alinea", "reference"),
        ("inciso", "reference"),
        ("paragrafo", "reference"),
        ("paragrafo", "reference"),
    ]
    assert report["closes"]


# --- amending laws ----------------------------------------------------------------
def test_quoted_block_is_a_separate_subtree() -> None:
    text = (
        "Art. 1º O art. 15 da Lei nº 10 passa a vigorar com a seguinte redação:\n"
        '"Art. 15. Novo texto:\nI - um;\nII - dois.\n§ 3º Outro texto." (NR)\n'
        "Parágrafo único. Regra do hospedeiro.\n"
        "Art. 2º Esta Lei entra em vigor."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-1-par-unico", "art-2"]
    assert _paths(report, "quoted") == [
        "art-15",
        "art-15-inc-1",
        "art-15-inc-2",
        "art-15-par-3",
    ]
    (block,) = report["quoted_blocks"]
    assert (block["opened_by"], block["closed"]) == ("mark", True)
    root = report["nodes"][block["node"]]
    assert root["kind"] == "quoted_block"
    assert report["nodes"][root["parent"]]["path"] == "art-1"
    assert _node(report, "art-15", "quoted")["parent"] == root["id"]
    # The quoted § 3º neither breaks nor joins the host numbering.
    assert report["levels"]["paragrafo"]["nodes"] == 1
    assert report["closes"]


def test_quoted_article_with_the_hosts_number_does_not_take_its_place() -> None:
    text = (
        "Art. 1º O art. 2º da Lei nº 10 passa a vigorar com a seguinte redação:\n"
        '"Art. 2º Texto novo."\n'
        "Art. 2º Esta Lei entra em vigor.\nArt. 3º Revogam-se."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-2", "art-3"]
    host = _node(report, "art-2")
    assert text[host["text_start"] : host["text_end"]] == "Esta Lei entra em vigor."
    assert report["closes"]


def test_block_without_quotation_mark_opens_at_the_amending_cue() -> None:
    text = (
        "Art. 1º O § 2º do art. 6º da Lei nº 918 passa a vigorar com a seguinte "
        "redação:\n.............\n§ 2º Os usuários com mais de 65 anos.\n"
        "Art. 2º Esta Lei entra em vigor."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-2"]
    assert _paths(report, "quoted") == ["par-2"]
    (block,) = report["quoted_blocks"]
    assert (block["opened_by"], block["closed"]) == ("cue", False)
    assert report["closes"]


def test_quotation_mark_without_amending_vocabulary_opens_nothing() -> None:
    # A stray mark in the margin must not hide the host's own alíneas.
    text = 'Art. 1º Compete:\nI - um:\n"a) x;\nb) y.\nArt. 2º Fim.'
    report = read_hierarchy(text)
    assert not report["quoted_blocks"]
    assert "art-1-inc-1-ali-a" in _paths(report)
    assert "art-1-inc-1-ali-b" in _paths(report)


# --- closure is conservative ------------------------------------------------------
def test_gap_in_a_scope_keeps_the_level_and_the_norm_open() -> None:
    text = "Art. 1º Compete:\nI - um;\nII - dois;\nIV - quatro.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert report["levels"]["artigo"]["closes"]
    assert not report["levels"]["inciso"]["closes"]
    assert report["levels"]["inciso"]["missing"] == 1
    assert not report["closes"]


def test_leftover_marker_keeps_the_norm_open_even_with_a_full_chain() -> None:
    # A second "I, II" means a paragraph marker was lost: the short chain that ignores
    # it must not count as closed.
    text = (
        "Art. 1º Compete:\nI - um;\nII - dois.\nI - de novo;\nII - outra vez.\n"
        "Art. 2º Fim."
    )
    report = read_hierarchy(text)
    assert _unexplained(report) == ["I -", "II -"]
    assert not report["levels"]["inciso"]["closes"]
    assert not report["closes"]


def test_chain_that_does_not_start_at_one_is_reported_missing() -> None:
    text = "Art. 1º Texto.\n§ 2º Dois.\n§ 3º Três.\nArt. 2º Fim."
    report = read_hierarchy(text)
    (scope,) = [s for s in report["scopes"] if s["kind"] == "paragrafo"]
    assert scope["missing"] == [1]
    assert not report["closes"]


def test_open_article_level_keeps_the_norm_open() -> None:
    text = "Art. 1º A.\nArt. 2º B.\nArt. 4º D.\nArt. 5º E."
    report = read_hierarchy(text)
    assert not report["levels"]["artigo"]["closes"]
    assert report["levels"]["paragrafo"]["closes"]
    assert not report["closes"]


def test_no_articles_closes_nothing() -> None:
    report = read_hierarchy("Texto sem artigos.\nI - solto;\n§ 1º solto.")
    assert not report["nodes"]
    assert not any(level["closes"] for level in report["levels"].values())
    assert not report["closes"]


def test_look_alike_after_the_chain_keeps_the_scope_open() -> None:
    # "11 —" after "I —" and "II —" is III with a stroke lost: it fits no reading, and
    # the chain that stops at II must not close.
    text = "Art. 1º Valor:\nI — um;\nII — dois; e\n11 — três.\nArt. 2º Vigora."
    report = read_hierarchy(text)
    assert _unexplained(report) == ["11 —"]
    assert not report["levels"]["inciso"]["closes"]
    assert not report["closes"]


def test_unreadable_marker_that_continues_a_list_is_read_as_the_next_number() -> None:
    # Was: left over, keeping the scope open. The sub-level tournament (mark reference)
    # reads a lone strong marker after "; e" at the chain's tail as the next number.
    text = "Art. 1º Receitas:\nI — taxas;\nII — doações; e\nWI — outras.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert _unexplained(report) == []
    assert _node(report, "art-1-inc-3")["read_by"] == "gap"


def test_unreadable_marker_with_a_reading_beyond_the_chain_stays_open() -> None:
    text = "Art. 1º Receitas:\nI — taxas;\nII — doações; e\nVI — outras.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert "art-1-inc-3" not in _paths(report)


def test_restarted_list_is_not_read_as_a_dropped_stroke() -> None:
    text = (
        "Art. 1º Compete:\nI - um;\nII - dois.\nI - de novo;\nII - outra vez.\n"
        "Art. 2º Fim."
    )
    assert "art-1-inc-3" not in _paths(read_hierarchy(text))


def test_unreadable_line_opener_outside_a_list_is_ignored() -> None:
    text = (
        "Art. 1º Compete ao Prefeito e ao\nVice-Prefeito:\nI - um;\nII - dois.\n"
        "Art. 2º Vigora."
    )
    report = read_hierarchy(text)
    assert not _unexplained(report)
    assert report["closes"]


def test_leftover_explained_by_a_deeper_level_does_not_count() -> None:
    # "1 -" is an inciso look-alike (I), left over beside the chain; the item reader
    # explains it, so the inciso scope still closes.
    text = (
        "Art. 1º Compete:\nI - listar:\n1 - primeiro;\n2 - segundo;\nII - outro.\n"
        "Art. 2º Vigora."
    )
    report = read_hierarchy(text)
    assert "art-1-inc-1-item-2" in _paths(report)
    assert not _unexplained(report)
    assert report["closes"]


def test_paragraph_look_alikes_left_over_keep_the_scope_open() -> None:
    text = "Art. 1º Caput.\nS 2º Dois.\nS 3º Três.\nArt. 2º Vigora."
    report = read_hierarchy(text)
    assert not report["levels"]["paragrafo"]["closes"]
    assert not report["closes"]


def test_lowercase_paragrafo_unico_in_prose_is_not_a_marker() -> None:
    text = (
        "Art. 1º O art. 3º fica acrescido do § 2º, passando\n"
        "o parágrafo único a ser § 1º.\nArt. 2º Vigora."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-2"]


def test_lost_alinea_letters_are_read_inside_the_list() -> None:
    # "1)" is "i)"; "))" is "j)", read only because it is the one gap in the chain.
    letters = ["a", "b", "c", "d", "e", "f", "g", "h", "1", ")", "l"]
    body = "\n".join(f"{x}) texto;" for x in letters)
    report = read_hierarchy(f"Art. 1º Lista:\n{body}\nArt. 2º Vigora.")
    assert _node(report, "art-1-ali-i")["read_by"] == "confusion"
    assert _node(report, "art-1-ali-j")["read_by"] == "gap"
    assert _node(report, "art-1-ali-l")["read_by"] == "literal"
    assert report["closes"]


def test_read_by_tells_literal_confusion_and_gap_apart() -> None:
    text = (
        "Art. 1º Compete:\nI - um;\nH - dois;\nWI — três;\nIV - quatro.\n"
        "Art. 2º Vigora."
    )
    report = read_hierarchy(text)
    assert [_node(report, f"art-1-inc-{n}")["read_by"] for n in (1, 2, 3, 4)] == [
        "literal",
        "confusion",
        "gap",
        "literal",
    ]


def test_block_opened_by_its_cue_still_closes_at_the_closing_mark() -> None:
    text = (
        "Art. 1º O parágrafo único do art. 34 passa a vigorar com a seguinte "
        "redação:\n........\nParágrafo único. Os proventos serão calculados.”\n"
        "§ 1º Regra do hospedeiro.\n§ 2º Outra.\nArt. 2º Esta Lei entra em vigor."
    )
    report = read_hierarchy(text)
    (block,) = report["quoted_blocks"]
    assert (block["opened_by"], block["closed"]) == ("cue", True)
    assert _paths(report) == ["art-1", "art-1-par-1", "art-1-par-2", "art-2"]
    assert _paths(report, "quoted") == ["par-unico"]
    assert report["closes"]


def test_unclosed_block_at_the_end_of_the_body_keeps_the_norm_open() -> None:
    # The OCR text stops inside the quotation: the host's last articles, if any, are
    # not there to be read.
    text = (
        "Art. 1º O art. 8º da Lei nº 5 passa a vigorar com a seguinte redação:\n"
        '"Art. 8º Licenciar:\na) ferrovias;\nb) portos.'
    )
    report = read_hierarchy(text)
    assert report["open_tail_block"]
    assert not report["levels"]["artigo"]["closes"]
    assert not report["closes"]


def test_final_clause_flags_a_text_cut_short() -> None:
    cut = read_hierarchy("Art. 1º Fica criado.\nArt. 2º Os recursos correrão.")
    whole = read_hierarchy("Art. 1º Fica criado.\nArt. 2º Esta Lei entra em vigor.")
    assert cut["closes"] and not cut["final_clause"]
    assert whole["closes"] and whole["final_clause"]


# --- the last article can be lost, not only the middle of the chain ---------------
SIX_ARTICLES = "".join(
    f"Art. {n}º Texto do artigo {n} com algum conteúdo.\n" for n in range(1, 7)
)


def test_lost_last_marker_before_the_closing_sentence_is_read_by_the_sequence() -> None:
    # Seven articles in print; the seventh marker is unreadable ("Art. T."). The chain
    # 1..6 is perfect and exactly one article word sits right before the closing
    # sentence, so the sequence reads it as Art. 7 (tournament round 2: 14 labelled
    # norms like this agree with the teacher; before, this shape stayed open).
    text = (
        SIX_ARTICLES
        + "Art. T. Esta Lei Complementar entra em vigor na data de sua publicação."
    )
    report = read_hierarchy(text)
    assert report["final_clause"]
    assert _node(report, "art-7")["raw"].startswith("Art. T")
    assert report["final_clause_placed"]
    assert report["closes"]


def test_lost_last_marker_stays_open_when_two_words_compete() -> None:
    # The guard of the tail reading: two unread article words after the chain are
    # ambiguous, and the closing sentence on a bare line is still a lost marker.
    text = (
        SIX_ARTICLES
        + "Art. T. Os recursos correrão à conta do orçamento.\n"
        + "Art. T. Esta Lei Complementar entra em vigor na data de sua publicação."
    )
    report = read_hierarchy(text)
    assert not report["closes"]


def test_split_marker_before_revogacao_is_read_as_article_four() -> None:
    # "A r/t." then "49 - Revogam-se ...": the marker split across two lines. With the
    # chain 1..3 the 49 reads as 4º, so the revogação opens an article the reader read.
    text = (
        "Art. 1º Fica criado.\nArt. 2º Texto dois.\nArt. 3º Texto três.\n"
        "A r/t.\n49 - Revogam-se as disposições em contrário."
    )
    report = read_hierarchy(text)
    assert _node(report, "art-4")["raw"] == "A r/t.\n49"
    assert report["final_clause_placed"]
    assert report["closes"]


def test_unread_article_word_after_the_last_article_keeps_the_norm_open() -> None:
    text = SIX_ARTICLES + "Art. T. Os recursos correrão à conta do orçamento."
    report = read_hierarchy(text)
    assert not report["tail_clean"]
    assert not report["closes"]


def test_numbered_line_for_the_next_article_keeps_the_norm_open() -> None:
    # "7 - " is the next article number, unread; the reader does not read bare numbers.
    text = SIX_ARTICLES + "7 - Revogam-se as disposições em contrário."
    report = read_hierarchy(text)
    assert not report["tail_clean"]
    assert not report["closes"]


def test_numbered_line_that_is_not_the_next_article_is_left_alone() -> None:
    text = SIX_ARTICLES + "9 - Outro item qualquer."
    report = read_hierarchy(text)
    assert report["tail_clean"]
    assert report["closes"]


@pytest.mark.parametrize(
    "closing",
    [
        "Art. 7º Esta Lei entra em vigor na data de sua publicação.",
        "Art. 7º Revogam-se as disposições em contrário.",
        "Art.\n7º - Esta Lei entra em vigor na data de sua publicação.",
        "Art. 7º\nEsta Lei entra em vigor na data de sua publicação.",
        "§ 1º Esta Lei entra em vigor na data de sua publicação.",
        "§ único. Esta Lei entra em vigor na data de sua publicação.",
        "(NR)\nEsta Lei entra em vigor na data de sua publicação.",
    ],
)
def test_closing_sentence_placed_at_an_article_still_closes(closing: str) -> None:
    report = read_hierarchy(SIX_ARTICLES + closing)
    assert report["final_clause_placed"]
    assert report["closes"]


def test_closing_phrase_mid_paragraph_still_closes() -> None:
    # Prose wrapped so that a line opens with a few words before the phrase.
    text = (
        "Art. 1º Fica criado o programa\n"
        "data em que esta Lei entrar em vigor, observado o prazo.\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação."
    )
    report = read_hierarchy(text)
    assert report["final_clause_placed"]
    assert report["closes"]


def test_closing_sentence_inside_a_quoted_block_is_not_judged() -> None:
    # The quoted text of another norm carries a line that would fail the placement
    # check; it belongs to the quotation, not to the host.
    text = (
        "Art. 1º A Lei nº 5 passa a vigorar com a seguinte redação:\n"
        '"Art. 2º Texto citado.\n'
        'Art. T. Esta Lei entra em vigor na data de sua publicação."\n'
        "Art. 2º Os recursos correrão.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação."
    )
    report = read_hierarchy(text)
    assert report["final_clause_placed"]
    assert report["closes"]


# --- articles ---------------------------------------------------------------------
def test_garbled_article_word_is_read_in_a_single_gap() -> None:
    # "Apt." stands in for a garbled word the reader does not recognise ("Ait." is now a
    # marker in its own right, see test_ait_and_alt_at_line_start_are_article_markers).
    text = "Art. 1º Fica.\nApt. 2o. Esta Lei entra em vigor.\nArt. 3º Revogam-se."
    report = read_hierarchy(text)
    second = _node(report, "art-2")
    assert second["raw"].startswith("Apt.")
    assert second["corrected"]
    assert report["closes"]


def test_two_garbled_candidates_in_a_gap_are_left_alone() -> None:
    text = "Art. 1º Fica.\nApt. 2o. Um.\nApt. 20 Outro.\nArt. 3º Revogam-se."
    report = read_hierarchy(text)
    assert not report["levels"]["artigo"]["closes"]


# --- annexes ----------------------------------------------------------------------
def test_annex_after_the_closing_formula_is_outside_the_body() -> None:
    text = (
        "Art. 1º Fica aprovado o Anexo.\nArt. 2º Vigora.\n"
        "Palácio do Governo, 1 de maio de 1990.\nANEXO I\nI - tabela;\nIII - outra;\n"
        "a) x"
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-2"]
    assert not report["leftovers"]
    assert report["closes"]


# --- gold bridge and performance --------------------------------------------------
def test_marker_spans_score_against_gold_with_the_segmenter_arithmetic() -> None:
    spans = marker_spans(CLEAN)
    assert [CLEAN[s["start"] : s["end"]] for s in spans][:4] == [
        "Art. 1º",
        "I -",
        "a)",
        "b)",
    ]
    scores = evaluate_against_gold([(CLEAN, spans)], marker_spans)
    assert all(s["exact_tp"] == s["gold"] == s["pred"] for s in scores.values())
    assert set(scores) == {
        "art_marcador",
        "par_marcador",
        "inc_marcador",
        "ali_marcador",
    }


def test_quoted_nodes_are_not_reported_as_own_markers() -> None:
    text = (
        "Art. 1º O art. 15 passa a vigorar com a seguinte redação:\n"
        '"Art. 15. Novo:\nI - um." (NR)\nArt. 2º Vigora.'
    )
    assert [text[s["start"] : s["end"]] for s in marker_spans(text)] == [
        "Art. 1º",
        "Art. 2º",
    ]


def test_large_document_is_read_in_reasonable_time() -> None:
    article = (
        "Art. {n}. Compete ao órgão, nos termos do § 2º do art. 5º:\n"
        "I - planejar as ações previstas em lei e regulamento;\n"
        "II - executar:\na) o orçamento aprovado;\nb) os convênios firmados;\n"
        "III - prestar contas ao Tribunal.\n"
        "§ 1º O prazo é de trinta dias.\n§ 2º Vencido o prazo, aplica-se multa.\n"
    )
    text = "".join(article.format(n=n) for n in range(1, 2301))
    assert len(text) > 650_000
    started = time.perf_counter()
    report = read_hierarchy(text)
    elapsed = time.perf_counter() - started
    assert report["levels"]["artigo"]["nodes"] == 2300
    assert report["levels"]["alinea"]["nodes"] == 4600
    assert report["closes"]
    assert elapsed < 20, f"{elapsed:.1f}s for {len(text)} characters"


def test_ait_with_unreadable_number_is_read_in_a_single_gap() -> None:
    # "Ait. T" for "Art. 2º": no number to read, but it is the only candidate between
    # 1 and 3, so the sequence reads it (the article reader leaves "T" alone).
    report = read_hierarchy("Art. 1º Fica.\nAit. T Esta Lei.\nArt. 3º Vigora.")
    second = _node(report, "art-2")
    assert second["raw"].startswith("Ait. T")
    assert second["corrected"]


def test_stray_e_over_the_last_article_is_read_as_its_marker() -> None:
    # decreto-lei-00044 and lei-00460: the closing article reads as article 2 / 6 once
    # the stray "e" is no longer taken as a citation.
    report = read_hierarchy(
        "Art. 19. Fica o Governo autorizado a contrair empréstimos.\n"
        "DECRETA:\ne\n\n\nArt. 29. As garantias das operações de créditos.\n"
        "Porto Velho, 31 de dezembro de 1.982."
    )
    assert _node(report, "art-2")["raw"].startswith("Art. 29")
    assert report["closes"]


def test_garbled_article_word_before_revogacao_is_read_as_the_next_article() -> None:
    # lei-00169: "Arte e Revogam-se ..." is the seventh article, its number unread. It
    # is the only garbled opener before the closing sentence, so the chain supplies 7
    # (tournament round 2; this shape used to keep the norm open).
    report = read_hierarchy(
        SIX_ARTICLES + "Arte e Revogam-se as disposições em contrário."
    )
    assert _node(report, "art-7")["raw"].startswith("Arte")
    assert report["final_clause_placed"]
    assert report["closes"]


def test_garbled_word_before_prose_that_is_not_a_closing_sentence_stays_open() -> None:
    report = read_hierarchy(SIX_ARTICLES + "Arte e Os recursos correrão à conta.")
    assert "art-7" not in _paths(report)


def test_lowercase_citation_in_a_gap_is_not_read_as_the_missing_article() -> None:
    # lei-00154: "art. 19 desta Lei" in prose sat between Art. 2 and Art. 4 and was
    # taken as Art. 3, while the real Art. 3 was never read.
    text = (
        "Art. 1º Fica criado o Quadro.\n"
        "Art. 2º O vencimento referido no\n\n\nart. \n19 desta Lei, são os constantes.\n"
        "Art. 4º Os vencimentos fixados.\n"
        "Art. 5º Esta Lei entra em vigor."
    )
    report = read_hierarchy(text)
    own_numbers = [
        n["number"]
        for n in report["nodes"]
        if n["kind"] == "artigo" and n["status"] == "own"
    ]
    assert 3 not in own_numbers
    assert not report["closes"]


# --- tournament round 2: chain logic around quoted blocks and single slots ------------
def _own_numbers(report: HierarchyReport) -> list[int | None]:
    nodes = sorted(report["nodes"], key=lambda n: n["start"])
    return [
        n["number"] for n in nodes if n["kind"] == "artigo" and n["status"] == "own"
    ]


# lc-00279 (9a83f375): the quote opening the amended wording was lost; the closing mark
# ends the block, after the next "own" article, and the host's own Art. 2º follows.
LOST_OPENING_MARK = (
    "Art. 1º Fica acrescido o inciso XXV ao artigo 1º e o artigo 2º da Lei Complementar"
    " nº 220, de 28\nde dezembro de 1999, passa a vigorar com a seguinte redação:\n\n\n"
    "XXV — Associação Rondoniense de Municípios.\n\n"
    "Art. 2º O Conselho Estadual de Desenvolvimento Rural de Rondônia — CEDR/RO,"
    " deliberará, por\nmeio de Resoluções e por maioria simples, com a presença da"
    " maioria absoluta de seus membros, tendo o\nPresidente voto de qualidade, em caso"
    " de empate”.\n\n\n"
    "Art. 2º Esta Lei Complementar entra em vigor na data de sua publicação.\n\n\n"
    "Palácio do Governo do Estado de Rondônia, em 5 de junho de 2003, 115º da República."
)


def test_block_closing_after_a_swallowed_article_hands_back_the_host_number() -> None:
    report = read_hierarchy(LOST_OPENING_MARK)
    assert _own_numbers(report) == [1, 2]
    last = max(
        (n for n in report["nodes"] if n["kind"] == "artigo" and n["status"] == "own"),
        key=lambda n: n["start"],
    )
    assert LOST_OPENING_MARK[last["start"] :].startswith("Art. 2º Esta Lei")
    assert report["closes"]


def test_block_closing_mark_far_before_a_second_run_of_articles_is_not_extended() -> (
    None
):
    # Guard: when the first article after the closing mark is followed by many more
    # markers it is not the norm's closing article but a second run (lc-01079).
    tail = "".join(f"Art. {n}º Texto novo {n}.\n" for n in range(2, 12))
    text = LOST_OPENING_MARK.split("Art. 2º Esta Lei")[0] + tail
    report = read_hierarchy(text)
    assert report["levels"]["artigo"]["nodes"] >= 2


# lc-00363 (529459dd): "registro”." closes a block whose opening mark is lost; the host
# resumes at Art. 2º after the host's Art. 1º.
UNOPENED_BLOCK = (
    "Art. 1º. Ficam alterados os dispositivos da Lei Complementar nº 228, que “Dispõe"
    " sobre o Sistema”.\n\n"
    "Art. 4º. A direção superior do Instituto.\n\n"
    "Art. 5º. O quadro de pessoal.\n\n"
    "Art. 7º. O Presidente, Diretor.\n\n"
    "Art. 67. Os benefícios serão iniciados na Secretaria e, após instruídos, deverão"
    " ser encaminhados para efetivação do registro”.\n\n\n"
    "Art. 2º. O Anexo II da Lei Complementar nº 224 passa a vigorar nos termos do"
    " Anexo.\n\n"
    "Art. 3º. Ficam revogados os §§ 1º e 3º do artigo 7º.\n\n"
    "Art. 4º. Esta Lei Complementar entra em vigor na data de sua publicação.\n"
)


def test_closing_mark_without_opening_quotes_the_articles_back_to_the_host() -> None:
    report = read_hierarchy(UNOPENED_BLOCK)
    assert _own_numbers(report) == [1, 2, 3, 4]
    assert 67 not in _own_numbers(report)


def test_balanced_marks_do_not_open_a_block_that_hides_host_articles() -> None:
    text = (
        "Art. 1º Fica criada a “Comissão” de estudos.\n"
        "Art. 2º O prazo é de “trinta dias”.\n"
        "Art. 3º Esta Lei entra em vigor.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]


# lei-00276 (739d9241): the straight quote opening the block stands alone before "Art.".
def test_lone_straight_quote_after_the_cue_opens_a_quoted_block() -> None:
    text = (
        "Art. 1º Os artigos 1º e 2º da Lei nº 50 passam a vigorar com a seguinte"
        ' redação:\n\n\n" Art. 1º Fica criado o cargo.\n\n'
        'Art. 2º Farão jus à pensão os dependentes, como titulares".\n\n\n'
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2]
    assert report["closes"]


# lei-01311 (c697318b): the previous line ends with a stray "o"; "Art. 2º" opens its line
# and is the only candidate for the missing slot, so it is not a citation.
def test_article_opening_its_line_after_a_stray_connector_fills_the_tail() -> None:
    text = (
        "Art. 1º. Ficam instituídos os dias do Policial Militar, que serão"
        " comemorados, anualmente, em 11 de fevereiro e 02 de dezembro, respectivamen-\n"
        "te. o\n"
        "Art. 2º. Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2]
    assert report["closes"]


def test_citation_after_a_connector_in_prose_stays_a_citation() -> None:
    # Guard: mid-line "do Art. 2º" is a citation, whatever the sequence slot says.
    text = "Art. 1º Fica criado o fundo de que trata o Art. 2º desta Lei.\n"
    assert _own_numbers(read_hierarchy(text)) == [1]


# lei-00628 (24d663e2): "Apito 20 — Esta Lei" is Art. 2º between 1 and 3.
def test_ruined_article_word_with_a_caput_opener_fills_a_single_gap() -> None:
    text = (
        "Art. 1º - Fica declarada de utilidade pública a Sociedade Beneficente.\n"
        "Apito 20 — Esta Lei entra emlvigor na da\nta de sua publicação.\n"
        "Art. 3º - Revogam-se as disposições em contrário.\n"
    )
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2, 3]
    assert report["closes"]


def test_ruined_opener_does_not_fill_a_gap_that_already_has_a_sharper_candidate() -> (
    None
):
    # Guard: one numbered-looking candidate ("Ait. T") already sits in the gap; the
    # looser opener rule is not consulted, so the gap is still filled exactly once.
    text = (
        "Art. 1º Fica criado.\nAit. T Esta Lei vigora.\nArt. 3º Fica revogado.\n"
        "Os recursos serão aplicados.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]


# lei-00422 (d4d672c3): the last article is "Vart. 1º - Revogam-se ...".
def test_garbled_last_article_word_with_a_closing_sentence_takes_the_next_number() -> (
    None
):
    report = read_hierarchy(
        SIX_ARTICLES + "Vart. 1º - Revogam-se as disposições em contrário."
    )
    assert _own_numbers(report)[-1] == 7
    assert report["closes"]


# Round 2: the opening article lost to OCR ("Apt. Lo pica O Governo ...") after the
# enacting formula, with the chain starting at 2.
def test_unreadable_opening_article_after_the_enacting_formula_is_article_one() -> None:
    text = (
        "O GOVERNADOR DO ESTADO DE RONDÔNIA, faço saber que a Assembleia Legislativa"
        " decreta e eu sanciono a se\nguinte Lei:\n\n"
        "Apt. Lo pica O Governo do Estado autorizado a doar o imóvel.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2]
    assert report["closes"]


def test_opening_line_without_a_caput_verb_is_not_article_one() -> None:
    # Guard: the first line after the formula must carry an opening verb.
    text = (
        "decreta e eu sanciono a seguinte Lei:\n\n"
        "Atenção: texto de abertura sem verbo de caput.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [2]


# --- tournament round 3 -----------------------------------------------------------
# lei-00xxx (5e24ca4d): the first letter of "Art." is lost at the start of the line.
def test_truncated_article_word_at_a_line_start_is_a_marker() -> None:
    text = (
        "Art. 1º Fica criado o concurso.\n"
        "/ rt. 2º - As taxas serão pagas.\n"
        "rt. 3º - Esta Lei entra em vigor.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]


def test_truncated_word_inside_a_sentence_is_not_a_marker() -> None:
    text = "Art. 1º Fica criado o conselho, conforme o parecer art. 2º desta Lei.\n"
    assert _own_numbers(read_hierarchy(text)) == [1]


# lei-00154 (10e794f4) / decreto-10219 (55446985): the "Art." is gone, the caput stays.
def test_caput_without_article_word_fills_the_single_gap_when_its_number_fits() -> None:
    text = (
        "Art. 1º Fica criado o quadro.\n"
        "Art. 2º Os cargos são os do anexo.\n"
        "39 - Os vencimentos fixados serão pagos.\n"
        "Art. 4º Esta Lei entra em vigor.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3, 4]


def test_numbered_line_that_does_not_fit_the_gap_is_not_an_article() -> None:
    text = (
        "Art. 1º Fica criado o quadro.\n"
        "Art. 2º Os cargos são os do anexo.\n"
        "77 - Os vencimentos fixados serão pagos.\n"
        "Art. 4º Esta Lei entra em vigor.\n"
    )
    assert 3 not in _own_numbers(read_hierarchy(text))


def test_number_after_a_lost_marker_line_is_not_read_one_line_late() -> None:
    # decreto "Art\\." / "52 - Além das atribuições": the marker word sits on its own
    # line, so the number line is the marker's number, not a second article.
    text = (
        "Art. 1º Primeiro texto.\n"
        "Art. 3º Terceiro texto.\n"
        "Art\\.\n22 - Além das atribuições definidas em lei compete ao Governador.\n"
    )
    nodes = [
        n
        for n in read_hierarchy(text)["nodes"]
        if n["kind"] == "artigo" and n["status"] == "own"
    ]
    assert [n["number"] for n in nodes] == [1, 3]


# lc-00199 (9e73dcf0): the quote opens with an apostrophe, OCR noise unbalances the
# marks, and the closing mark sits right before the host's own Art. 2o.
def test_host_chain_resumes_after_a_closing_mark_despite_noisy_marks() -> None:
    text = (
        "Art. 1º - Os dispositivos da Lei nº 168 passam a vigorar com a seguinte"
        " redação:\n\n"
        "'Art. 8o - Parágrafo único - As despesas correntes.\n\n"
        "«•£ »v\n\n"
        "Art. 9o - Texto citado.\n\n"
        'Art. 15 - Compete à Divisão Fiscal executar tarefas pertinentes à Divisão."\n\n'
        "Art. 2º - Ficam suprimidos os dispositivos.\n\n"
        "Art. 3º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]


def test_bare_number_before_the_closing_sentence_needs_its_ordinal_sign() -> None:
    # "2º Este Decreto entra em vigor" is the closing article; "7 - Revogam-se" is
    # indistinguishable from a list item and keeps the old, open behaviour.
    text = "Art. 1º Fica criado o cargo.\n2º Este Decreto entra em vigor na data."
    assert _own_numbers(read_hierarchy(text)) == [1, 2]


# --- tournament round 4 -------------------------------------------------------------
# lei-00284 (440c8078): a citation ("Art. 42 da Constituição") sits before the enacting
# formula; the opening "Art. Fica instituído" after it is still Art. 1.
def test_citation_before_the_formula_does_not_block_the_unnumbered_opening() -> None:
    text = (
        "A Assembleia, nos termos do § 70, do Art.\n42 da Constituição do Estado,\n"
        "promulgo a seguinte Lei:\n\n\n"
        "Art. Fica instituído o passe escolar, a ser distribuído gratuitamente.\n"
        "Art. 2º O discente que comprovar a condição fará jus ao benefício.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]


# lei-00xxx (fcda3829): "Art.\nI5\n-\nOs recursos" right after "seguinte Lei:".
def test_marker_seen_but_unplaced_right_after_the_formula_is_article_one() -> None:
    text = (
        "decreta e eu sanciono a\nseguinte Lei:\n\n\n"
        "Art.\nI5\n-\nOs\nrecursos do orçamento plurianual são estimados.\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2]


def test_unplaced_marker_far_from_the_formula_is_not_article_one() -> None:
    text = (
        "decreta e eu sanciono a\nseguinte Lei:\n\n\n"
        "Preâmbulo sem artigo algum, com bastante texto corrido antes do primeiro.\n"
        "Art.\nI5\n-\nOs recursos.\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert 1 not in _own_numbers(read_hierarchy(text))


# lei-00858 (c8f92562): two numbers missing, two unreadable markers between them.
def test_two_missing_numbers_and_two_markers_are_matched_in_order() -> None:
    text = (
        "Art. 1º Fica criado o cargo.\nArt. 2º Fica criado o fundo.\n"
        "Art. 3º Fica criado o prazo.\nArt. 4º Fica criado o comitê.\n"
        "Art. 5º Fica criado o cargo.\n"
        "Árt. 6o / aplicação das multas pertinentes.\n"
        "Ait. T Esta Lei vigora.\n"
        "Art. 8º Fica revogado o artigo.\nArt. 9º Esta Lei entra em vigor.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_two_missing_numbers_with_one_marker_stay_open() -> None:
    text = (
        "Art. 1º Fica criado o cargo.\nArt. 2º Fica criado o fundo.\n"
        "Art. 3º Fica criado o prazo.\nArt. 4º Fica criado o comitê.\n"
        "Ait. T Esta Lei vigora.\n"
        "Art. 7º Fica revogado o artigo.\nArt. 8º Esta Lei entra em vigor.\n"
    )
    numbers = _own_numbers(read_hierarchy(text))
    assert 5 not in numbers and 6 not in numbers


# lei-00388 (3ea8b462): "Art. 59-0 Poder" is 5º - O Poder, after a stray line end.
def test_glued_ordinal_marker_opening_its_line_fills_the_gap() -> None:
    text = (
        "Art. 1º Fica criado o fundo.\n"
        "Art. 2º Os recursos virão do Estad o\n"
        "Art. 3º Fica o Poder Executivo autorizado.\n"
        "Art. 4º Os valores serão devolvidos aos cofres do Estado e\n"
        "Art. 59-0 Poder Executivo regulamentará esta Lei.\n"
        "Art. 6º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3, 4, 5, 6]


# lei-00166 (2381d54d): "Art-" then a number made of debris.
def test_lone_marker_over_debris_fills_a_single_gap() -> None:
    text = (
        "Art. 1º Fica criado o fundo.\n"
        "Art-\n2-\n"
        "Fica instituído o prazo de trinta dias.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]


# --- tournament round 6 -------------------------------------------------------------
# lei-00952 / lc-00164 and others: an amending host quotes whole articles without any
# quotation mark; the ones the chain cannot place are quoted text, not lost markers.
def test_unplaced_far_ahead_marker_under_an_amending_host_is_quoted() -> None:
    text = (
        "Art. 1º Os artigos abaixo passam a vigorar com a seguinte redação:\n"
        "Art. 181 - A autoridade que tiver ciência de irregularidade é obrigada a"
        " promover a sua apuração.\n"
        "Art. 182 - Haverá uma Comissão Permanente de Sindicância.\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2]
    assert report["levels"]["artigo"]["unexplained"] == 0
    assert report["levels"]["artigo"]["closes"]


def test_far_ahead_marker_under_a_host_without_amending_words_stays_unexplained() -> (
    None
):
    # Guard: no amendment vocabulary in the host article, so a stray far-ahead marker
    # is still reported as unexplained (a possible lost marker), not hidden.
    text = (
        "Art. 1º Fica criado o conselho.\n"
        "Art. 181 - A autoridade que tiver ciência de irregularidade.\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert report["levels"]["artigo"]["unexplained"] == 1
    assert not report["closes"]


def test_repeated_number_right_after_a_closing_mark_is_still_a_host_article() -> None:
    # Guard (lei-00297): "Art. 2º" repeating a number right after the closing quote is
    # the host's own article, never folded into the quote.
    text = (
        "Art. 1º O decreto passa a vigorar com a seguinte redação:\n"
        "Art. 2º - As promoções serão por merecimento, conforme o conceito"
        " profissional.\n"
        'com aproveitamento".\n\n'
        "Art. 2º - Fica alterado o artigo.\n"
        "Art. 3º - Esta Lei entra em vigor.\n"
    )
    assert _own_numbers(read_hierarchy(text))[-2:] == [2, 3]


# --- tournament round 7 -------------------------------------------------------------
# lei-01723 (31912f7f): an unmarked quote opens at "Art. 3º-A" and closes at "”"; the
# host's own Art. 3º and Art. 4º follow it. The lettered article shares the host number.
def test_unopened_block_starting_with_a_lettered_article_hands_back_the_host_chain() -> (
    None
):
    text = (
        "Art. 1º. Passam a vigorar os dispositivos adiante enumerados da Lei nº 1.558.\n"
        "Art. 2º. Ficam acrescentados os dispositivos adiante enumerados à Lei nº 1.558:\n"
        "Art. 3º-A. O descumprimento de qualquer disposição desta Lei acarretará multa.\n"
        "Art. 3º-B. O crédito presumido utilizado em desacordo será estornado.\n"
        "Art. 4º-B. A presente Lei será regulamentada por Decreto do Poder Executivo.”\n\n"
        "Art. 3º. Fica revogado o parágrafo único do art. 2º da Lei nº 1.558, de 2005.\n"
        "Art. 4º. Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3, 4]


# lei-00633 (78a1ade9): "AME Ão - Esta Lei entra-em vigor" is Art. 4º.
def test_ruined_opener_with_two_letters_of_junk_fills_a_single_gap() -> None:
    text = (
        "Art. 1º - Fica criado o cargo.\nArt. 2º - Fica criado o fundo.\n"
        "Art. 3º - Fica criado o prazo.\n"
        "AME Ão - Esta Lei entra-em vigor na data de sua publicação.\n"
        "Art. 5º - Revogam-se as disposições em contrário.\n"
        "Art. 6º - Fica criado o comitê.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3, 4, 5, 6]


# lei-00248 (fdf69f51): lowercase "art. 1º" right after the enacting formula, with a
# citation of another Artigo in the same paragraph.
def test_lowercase_first_article_after_the_formula_is_article_one() -> None:
    text = (
        "nos termos do § 7º do Art. 42 da Constituição Estadual, promulgo a seguinte\n"
        "Lei:\n\n\n"
        "art. 1º - O valor de referência do cargo, previsto no Artigo 1º, da Lei"
        " Complementar nº 24, fica reajustado.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2]


def test_lowercase_art_inside_prose_is_not_article_one() -> None:
    text = (
        "promulgo a seguinte Lei:\n\nO texto cita o art. 1º da Lei anterior.\n"
        "Art. 2º - Esta Lei entra em vigor.\n"
    )
    assert 1 not in _own_numbers(read_hierarchy(text))


# --- tournament round 8: closure checks and the unread-marker count -----------------
def _closes(text: str) -> bool:
    return bool(read_hierarchy(text)["levels"]["artigo"]["closes"])


_BODY = "Art. 1º - Fica criado o cargo.\nArt. 2º - Fica criado o fundo.\n"


# lei-00351 (740b585a): the ordinal sign of the last article read as "s" ("3s -").
def test_ordinal_sign_read_as_a_letter_does_not_hide_the_last_article() -> None:
    text = (
        _BODY
        + "Art.\n3s - Revogam-se as disposições em contrário.\n\nPalácio do Governo\n"
    )
    assert _closes(text)


def test_ordinal_letter_without_a_marker_still_leaves_the_norm_open() -> None:
    # The marker itself was lost: only "3s -" is left before the closing sentence.
    text = (
        _BODY
        + "\n\n3s - Revogam-se as disposições em contrário.\n\nPalácio do Governo\n"
    )
    assert not _closes(text)


# decreto-lei-00008 (unlabelled): an inciso "III- Somente apos ..." is not a garbled
# article word, whatever caput word follows it.
def test_roman_numeral_item_is_not_read_as_a_garbled_article() -> None:
    text = (
        "Art. 1º - Fica criado o cargo.\nArt. 2º - A promoção obedecerá:\n"
        "II- No caso de merecimento, sera votado lista tríplice;\n\n"
        "III- Somente apos 2 (dois) anos de exercício, podera o Juiz ser promovido.\n"
        "Art. 4º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 4]
    assert not _closes(text)


# 339656dd: "exceto em relação ao\nart. 1º que surtirá efeitos" cites an article.
def test_citation_broken_across_lines_after_the_last_article_is_not_a_lost_marker() -> (
    None
):
    text = _BODY + (
        "Art. 3º Este Decreto entra em vigor na data de sua publicação, exceto em"
        " relação ao\nart. 1º que surtirá efeitos a partir de 1º de janeiro.\n\n"
        "Palácio do Governo do Estado\n"
    )
    assert _closes(text)


# lei-00255 (0d68149f): "Al 15 de dezembro de 1989" is the date of a signature.
def test_signature_date_after_the_last_article_is_not_an_article_marker() -> None:
    text = _BODY + (
        "Art. 3º - Revogam-se as disposições em contrário.\n\n"
        "Al 15 de dezembro de 1989\n\nDeputado\n"
    )
    assert _closes(text)


# lei-00401 (a05e2daf): "4.\n\nPROCESSO" in an annex table is not "4 - Revogam-se".
def test_number_on_its_own_line_before_a_table_header_is_not_a_lost_article() -> None:
    text = _BODY + (
        "Art. 3º - Esta Lei entra em vigor na data de sua publicação.\n\n"
        "4.\n\n\nPROCESSO\nDISCRIMINAÇÃO\n"
    )
    assert _closes(text)


# decreto-lei-00002 (a9d24943): "09. Secretaria de Estado" in a budget table.
def test_zero_padded_table_row_is_not_the_next_article() -> None:
    text = (
        "Art. 1º - Fica criado o cargo.\nArt. 2º - Fica criado o fundo.\n"
        "Art. 3º - Revogam-se as disposições em contrário.\n\n"
        "03. Secretaria de Estado do Trabalho\n"
        "04. Secretaria de Estado da Agricultura\n"
    )
    assert _closes(text)


def test_article_number_opener_after_the_last_article_still_blocks_closure() -> None:
    text = _BODY + "Art. 3º - Fica criado o prazo.\n\n4 - Revogam-se as disposições.\n"
    assert not _closes(text)


# lei-00862 (07edf7c8): the legislative signature line ends the body.
def test_legislative_signature_line_ends_the_articulated_body() -> None:
    text = _BODY + (
        "Art. 3º - Revogam-se as disposições em contrário.\n"
        "ASSEMBLÉIA LEGISLATIVA, 20 de dezembro de 1999.\n\n"
        "À\n\n/\nAL\nMH)\n"
    )
    assert _closes(text)


# lc-00096 (ea427b24): an annex heading cites an article in the middle of a line.
def test_article_cited_inside_an_annex_heading_does_not_leave_the_norm_open() -> None:
    text = _BODY + (
        "Art. 3º - Esta Lei entra em vigor na data de sua publicação.\n\n"
        "Palácio do Governo do Estado de Rondônia\n\n"
        "ANEXO IV\nTABELAS SALARIAIS\nLC No 67/92 - ART. 6o\n"
    )
    assert _closes(text)


def test_article_opening_a_line_after_the_body_still_leaves_the_norm_open() -> None:
    text = _BODY + (
        "Art. 3º - Esta Lei entra em vigor na data de sua publicação.\n\n"
        "Palácio do Governo do Estado de Rondônia\n\nANEXO\n\n"
        "Art. 2° O cargo é privativo de servidor.\n"
    )
    assert not _closes(text)


# lc-01063 (e26a6a32): a message before the enacting formula quotes proposed articles.
def test_marker_before_the_first_own_article_is_not_an_unread_article() -> None:
    text = (
        "MENSAGEM. A proposta prevê o seguinte, que segue:\n\n"
        "Art. 9°. Somente poderão ser credenciadas como consignatárias as associações.\n\n"
        "A ASSEMBLÉIA LEGISLATIVA decreta:\n\n"
        + _BODY
        + "Art. 3º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _closes(text)


# --- tournament round 9 -------------------------------------------------------------
# lei-00740 (43aa8c7c): a stray quotation mark glued to the closing article.
def test_stray_quotation_mark_before_the_closing_article_does_not_open_a_block() -> (
    None
):
    text = (
        "Art. 1º - Fica o Poder Executivo autorizado a adotar as providências.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n\n"
        "“Art. 3º - Revogam-se as disposições em contrário.\n\n"
        "Palácio do Governo do Estado de Rondônia\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2, 3]
    assert _closes(text)


def test_quotation_mark_before_an_article_that_is_closed_stays_a_quote() -> None:
    text = (
        "Art. 1º - Fica alterado o artigo 3º da Lei nº 5, que passa a vigorar com a"
        " seguinte redação:\n“Art. 3º - Revogam-se as disposições em contrário.”\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
    )
    assert _own_numbers(read_hierarchy(text)) == [1, 2]


# lei-00578 (a3ef0197): "Art. 10-0 Art. 69 da Lei nº 435" cites the article it amends.
def test_amended_article_cited_as_the_caput_subject_is_not_an_unread_article() -> None:
    text = (
        "Faço saber que a Assembléia Legislativa decreta e eu sanciono a seguinte"
        " Lei:\n\n\nArt. 10-0 Art. \n69 \nda \nLei \nnQ \n435, \nde \n\n\n"
        "29 de setembro de \n1992, \npassa a vigorar com a seguinte redação: \n\n\n"
        '"Art. \n6Q \n- \nOs membros do Conselho farão jus a uma gratificação.\n\n\n'
        '§ 3Q - Integra, ainda, o Conselho um Secretário-Geral."\n\n\n'
        "Art. \n2° \n- Esta Lei entra em vigor na data de sua publicação.\n\n\n"
        "Art. 3° - Revogam-se as disposições em contrário.\n"
    )
    assert _unexplained(read_hierarchy(text)) == []
    assert _closes(text)


# --- an orphan closing sentence: the last marker lost with the sentence left ---------
# Mutation of the last own article of norms that close and agree with the teacher
# (tournament, seed 9): deleting only the "Art. N" token left the reader closing with
# one article missing in 386 of 400 norms.
VIGENCIA = "Esta Lei entra em vigor na data de sua publicação."
REVOGACAO = "Revogam-se as disposições em contrário."


def _own_numbers(report: HierarchyReport) -> list[int]:
    nodes = sorted(report["nodes"], key=lambda n: n["start"])
    return [
        n["number"]
        for n in nodes
        if n["kind"] == "artigo" and n["status"] == "own" and n["number"] is not None
    ]


def test_orphan_vigencia_after_the_last_article_is_read_as_the_next_article() -> None:
    report = read_hierarchy(SIX_ARTICLES + " " + VIGENCIA)
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7]
    assert report["orphan_closings"]
    assert report["final_clause_placed"]
    assert report["closes"]
    # The recovered article has no marker to point at: nothing to score against gold.
    text = SIX_ARTICLES + " " + VIGENCIA
    assert all(s["end"] > s["start"] for s in marker_spans(text))
    assert len(marker_spans(text)) == 6


def test_orphan_vigencia_then_revogacao_are_the_next_two_articles() -> None:
    report = read_hierarchy(SIX_ARTICLES + " " + VIGENCIA + "\n - " + REVOGACAO)
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert report["closes"]


def test_dash_led_revogacao_after_an_own_vigencia_article_is_the_next_article() -> None:
    # "Art. 7º - Esta Lei ... publicação." then " - Revogam-se ...": lei-00684 shape.
    text = SIX_ARTICLES + "Art. 7º - " + VIGENCIA + "\n - " + REVOGACAO
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert report["closes"]


def test_orphan_vigencia_after_a_paragrafo_unico_is_read_as_the_next_article() -> None:
    # The ambiguous shape, decided: a sentence that is only a closing formula and opens
    # its line after a sentence end is an article, not the paragraph's second sentence
    # (no real norm of the 2,257 read has that shape; four have a lost marker).
    text = SIX_ARTICLES + "Parágrafo único. Fica autorizado o repasse.\n " + VIGENCIA
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7]
    assert report["closes"]


def test_orphan_vigencia_after_a_dash_led_unfinished_vigencia_is_still_read() -> None:
    # OCR scrambled the end of the vigência sentence ("na data / de sua publi"); the
    # dash-led revogação that follows is still an article of its own.
    text = (
        SIX_ARTICLES
        + "Art. 7º - Esta Lei entra em vigor na data\n\nde sua publi\n\n- "
        + REVOGACAO
    )
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert report["closes"]


def test_two_sentences_of_the_same_last_article_are_not_split_but_refuse() -> None:
    # "Art. 7º Revogam-se ...\nEsta Lei entra em vigor": one article with two sentences,
    # or a marker lost in front of the second one; nothing on the line tells them
    # apart. It never becomes an extra article, and the norm does not claim to close.
    text = SIX_ARTICLES + "Art. 7º " + REVOGACAO + "\n" + VIGENCIA
    report = read_hierarchy(text)
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7]
    assert report["closing_ambiguous"]
    assert not report["final_clause_placed"]
    assert not report["closes"]


def test_closing_sentence_after_a_wrapped_line_is_not_an_article() -> None:
    # The previous line stops mid-sentence, or a comma carries the sentence on.
    for lead in (
        "Art. 7º Ficam revogadas as disposições anteriores, nos termos da\n",
        "Art. 7º Esta Lei entra em vigor na data de sua publicação,\n",
    ):
        text = SIX_ARTICLES + lead + "revogadas as disposições em contrário."
        report = read_hierarchy(text)
        assert not report["orphan_closings"], lead
        assert not report["closing_ambiguous"], lead
        assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7], lead
        assert report["closes"], lead


def test_closing_sentence_inside_quoted_text_is_not_an_article() -> None:
    text = (
        SIX_ARTICLES
        + "Art. 7º O art. 9º da Lei nº 5 passa a vigorar com a seguinte redação:\n"
        + "“Art. 9º Texto do artigo nove.\n"
        + VIGENCIA
        + "” (NR)\n"
        + "Art. 8º "
        + VIGENCIA
    )
    report = read_hierarchy(text)
    assert not report["orphan_closings"]
    assert _own_numbers(report) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert report["closes"]


def test_closing_sentence_after_its_own_marker_line_is_not_an_orphan() -> None:
    # "Ait. 3o." alone on a line, then the sentence (lei-00955): the marker is the
    # article; a number line left over from a split marker ("Art.\n42") likewise.
    for marker in ("Ait. 7o.\n", "Art-\n7,.\n"):
        report = read_hierarchy(SIX_ARTICLES + marker + REVOGACAO)
        assert not report["orphan_closings"], marker
        assert not report["closing_ambiguous"], marker


def test_orphan_sentence_with_a_single_word_before_it_is_not_read() -> None:
    # "Art.\n11\ntrarios.\nRevogam-se ...": the scrambled text of one article.
    text = SIX_ARTICLES + "Art. 7º\ntrarios.\n" + REVOGACAO
    assert not read_hierarchy(text)["orphan_closings"]


def test_clean_norm_has_no_orphan_closings() -> None:
    report = read_hierarchy(CLEAN)
    assert report["orphan_closings"] == []
    assert not report["closing_ambiguous"]


# The permanent adversarial test: lose the marker of the closing article of small
# synthetic laws and require the reader never to close with that article missing.
def _law(articles: int, closing: list[str], paragraph: bool) -> tuple[str, list[int]]:
    body = [f"Art. {n}º Texto do artigo {n} com algum conteúdo." for n in range(1, 4)]
    if paragraph:
        body.append("Parágrafo único. Texto do parágrafo do terceiro artigo.")
    total = 3
    for sentence in closing:
        total += 1
        body.append(f"Art. {total}º - {sentence}")
    return "\n".join(body) + "\nPalácio do Governo, 7 de abril de 1997.", list(
        range(1, total + 1)
    )


_LAWS = [
    _law(3, [VIGENCIA], False),
    _law(3, [VIGENCIA, REVOGACAO], False),
    _law(3, [VIGENCIA], True),
    _law(3, [REVOGACAO, "Esta Lei entra em vigor na data de sua publicação."], True),
    _law(3, ["Fica o Poder Executivo autorizado a regulamentar.", VIGENCIA], False),
]


@pytest.mark.parametrize("mutation", ["token", "lead", "garbage", "bare_space"])
@pytest.mark.parametrize("index", range(len(_LAWS)))
def test_losing_the_last_marker_never_closes_with_the_article_missing(
    index: int, mutation: str
) -> None:
    text, original = _LAWS[index]
    assert read_hierarchy(text)["closes"]
    last = f"Art. {original[-1]}º - "
    pos = text.index(last)
    if mutation == "token":
        mutated = text[:pos] + text[pos + len("Art. Xº") :]
    elif mutation == "lead":
        mutated = text[:pos] + text[pos + len(last) :]
    elif mutation == "garbage":
        mutated = text[:pos] + "xq" + text[pos + len("Art. Xº") :]
    else:
        mutated = text[:pos] + text[pos + len("Art. Xº") :].lstrip(" -")
    report = read_hierarchy(mutated)
    numbers = _own_numbers(report)
    if report["closes"]:
        # Closing is only allowed with every article accounted for, never one short.
        assert numbers == original, (mutation, numbers)


# --- sub-level rules from the mark-reference tournament (docs/okf/reader-ratchet.md) --


def test_ocr_dropped_stroke_reads_ii_as_iii_when_the_chain_wants_it() -> None:
    text = (
        "Art. 1º O patrimônio será constituído por:\n"
        "I — bens e direitos próprios;\n"
        "II — bens móveis transferidos;\n"
        "II — por doações e legados.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _paths(report) == [
        "art-1",
        "art-1-inc-1",
        "art-1-inc-2",
        "art-1-inc-3",
        "art-2",
    ]


def test_paragraph_comma_after_ordinal_is_not_a_citation_at_line_start() -> None:
    text = (
        "Art. 1º A Fundação terá sede.\n"
        "$ 1º, A Fundação aplicará recursos.\n"
        "§ 2º A Fundação prestará contas.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert "art-1-par-1" in _paths(read_hierarchy(text))


def test_apostrophe_does_not_close_a_double_quoted_block() -> None:
    text = (
        "Art. 1º O artigo 22 da Lei nº 5 passa a vigorar com a seguinte redação:\n"
        "\"Art. 22 - O servidor receberá cinco quintos de' 5/5 (cinco quintos).\n"
        "§ 1º - Entende-se como gratificação a parcela.\n"
        'Art. 23 - Os demais valores permanecem."\n'
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    quoted = [n for n in report["nodes"] if n["status"] == "quoted" and n["path"]]
    assert any(n["kind"] == "paragrafo" for n in quoted)
    assert "art-1-par-1" not in _paths(report)


def test_unico_paragraph_ocr_variants() -> None:
    for word in (
        "Parágrafo único",
        "Paragrafo úrico",
        "Parâgrafo único",
        "Parágafo único",
    ):
        text = f"Art. 1º Fica criado o fundo.\n{word} - Os eventos serão regulados.\n"
        assert "art-1-par-unico" in _paths(read_hierarchy(text)), word


def test_paragraph_glyph_with_hyphen_or_double_letter() -> None:
    text = (
        "Art. 1º A matrícula será feita.\n"
        "S-1º - No ato serão esclarecidas as vantagens.\n"
        "Ss 2º - A doação será espontânea.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    paths = _paths(read_hierarchy(text))
    assert "art-1-par-1" in paths and "art-1-par-2" in paths


def test_roman_numeral_without_dash_joins_the_chain() -> None:
    text = (
        "Art. 1º A multa será aplicada quando:\n"
        "I - o equipamento for instalado;\n"
        "II  o equipamento emitir choque pulsativo;\n"
        "III - o equipamento for violado.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert "art-1-inc-2" in _paths(read_hierarchy(text))


def test_unreadable_last_inciso_in_an_enumeration_takes_the_next_number() -> None:
    text = (
        "Art. 1º Compete ao Conselho:\n"
        "I — deliberar sobre as contas;\n"
        "II — aprovar o orçamento;\n"
        "NI — ao Conselho Estadual dos Direitos da Mulher.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert "art-1-inc-3" in _paths(read_hierarchy(text))


def test_lone_quoted_paragraph_with_a_glued_ordinal_digit_reads_the_small_number() -> (
    None
):
    text = (
        "Art. 1º O artigo 3º da Lei nº 5 passa a vigorar com a seguinte redação:\n"
        '"Art. 3º - Os servidores terão direito.\n'
        "§ 29 - Os valores serão pagos.\n"
        'Art. 4º - Esta Lei vigora."\n'
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    pars = [n for n in report["nodes"] if n["kind"] == "paragrafo"]
    assert [n["number"] for n in pars] == [2]


def test_quoted_articles_with_glued_ordinals_read_the_climbing_run() -> None:
    text = (
        "Art. 1º O Decreto-Lei passa a vigorar com os seguintes artigos:\n"
        '"ART. 39 — Em garantia ao financiamento, o Estado cederá parcelas.\n'
        'ART. 49 — Este Decreto-Lei entra em vigor."\n'
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    quoted = sorted(
        n["number"]
        for n in report["nodes"]
        if n["kind"] == "artigo" and n["status"] == "quoted"
    )
    assert quoted == [3, 4]


def test_quoted_article_10_before_article_2_reads_as_1() -> None:
    text = (
        "Art. 1º Os artigos passam a vigorar com a seguinte redação:\n"
        '"Art. 10 — VETADO.\n'
        'Art. 2º - A presente gratificação será paga."\n'
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    quoted = sorted(
        n["number"]
        for n in report["nodes"]
        if n["kind"] == "artigo" and n["status"] == "quoted"
    )
    assert quoted == [1, 2]


def test_roman_numeral_one_read_from_l_dot_opens_an_item_list_not_an_inciso() -> None:
    text = (
        "Art. 1º Os valores serão:\n"
        "b) indústrias de pescado:\n"
        "l. até 200 Kg/dia - até 100 UFIR;\n"
        "2. de 201 a 500 Kg/dia - até 400 UFIR;\n"
        "3. acima de 500 Kg/dia - até 1000 UFIR.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    kinds = [(n["kind"], n["number"]) for n in report["nodes"] if n["kind"] != "artigo"]
    assert ("item", 1) in kinds and ("item", 3) in kinds
    assert not any(k == "inciso" for k, _ in kinds)


def test_stray_apostrophe_between_inciso_token_and_dash() -> None:
    text = (
        "Art. 1º Constam do cadastro:\n"
        "I — o nome;\n"
        "II — o endereço;\n"
        "III — o número;\n"
        "IV '— nº 127.537 CAERD;\n"
        "V — outras.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert "art-1-inc-4" in _paths(read_hierarchy(text))


def test_enumeration_cue_tolerates_a_stray_bar_before_the_marker() -> None:
    text = (
        "Art. 1º Para o curso é preciso:\n"
        "I - ter dois anos de serviço;\n"
        "| K - ter cinco anos de serviço.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert "art-1-inc-2" in _paths(read_hierarchy(text))


# --- full-scale tournament, round 1 (docs/okf/reader-ratchet.md) -----------------------
def _numbers(report: HierarchyReport, kind: str, status: str = "own") -> list[str]:
    nodes = sorted(report["nodes"], key=lambda n: n["start"])
    return [
        f"{n['number']}{n['suffix'] or ''}"
        for n in nodes
        if n["kind"] == kind and n["status"] == status
    ]


def test_article_suffix_with_spaced_dash_and_period() -> None:
    text = (
        "Art. 1º Fica alterada a Lei:\n"
        "“Art. 124 - A. Os órgãos e entidades da administração pública.\n"
        "Art. 125 - B. Fica criado o cargo.”\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "artigo", "quoted")[0] == "124A"
    # the spaced form is only for "A.": "Art. 6º - B." is "É" misread, not a suffix
    other = read_hierarchy(
        "Art. 1º Texto.\nArt. 2º - B. vedado ao Conselheiro:\nArt. 3º Fim.\n"
    )
    assert _numbers(other, "artigo") == ["1", "2", "3"]


def test_quoted_article_with_suffix_a_glued_to_the_ordinal() -> None:
    text = (
        "Art. 1º A Lei nº 1 passa a vigorar acrescida do seguinte artigo:\n\n"
        "“Art. 2º-A Constitui de igual modo objetivo do Fundo.”\n\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "artigo", "quoted") == ["2A"]
    assert _numbers(report, "artigo") == ["1", "2"]


def test_overlapping_quoted_spans_do_not_leave_duplicate_nodes() -> None:
    from leizilla import marcacao

    text = (
        "Art. 1º Altera a Lei:\n"
        "“Art. 2º-A Os valores:\n\n"
        "I - um;\n\n"
        "II - dois.”\n"
        "Art. 2º Fim.\n"
    )
    # building the marked document must not raise on nested quoted spans
    marcacao.from_hierarchy(text, read_hierarchy(text), tipo="lei", numero=1)


def test_paragraph_sign_read_as_8_or_4_glued_to_the_ordinal() -> None:
    text = (
        "Art. 1º Texto principal da norma.\n"
        "§ 1º Primeiro paragrafo da norma.\n"
        "82º Segundo paragrafo da norma aqui.\n"
        "43º Terceiro paragrafo da norma aqui.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "paragrafo") == ["1", "2", "3"]


def test_paragraph_twelve_with_a_period_keeps_the_literal_for_the_section_sign() -> (
    None
):
    text = (
        "Art. 1º Altera a Lei nº 1:\n"
        "“Art. 5º Texto:\n"
        "§ 12. Aos servidores no efetivo exercício.”\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "paragrafo", "quoted") == ["12"]


def test_paragraph_suffix_letter_before_lower_case_prose_is_no_suffix() -> None:
    text = (
        "Art. 1º Texto.\n"
        "§ 4º-O exercício das funções do Conselho é gratuito.\n"
        "§ 5º-A Gratificação será paga.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "paragrafo") == ["4", "5A"]


def test_quoted_block_restarts_paragraphs_at_a_lone_first_one() -> None:
    text = (
        "Art. 1º Altera a Lei nº 1:\n"
        "“Art. 5º Texto:\n"
        "§ 1º Primeiro.\n"
        "§ 2º Segundo.\n"
        "II - inciso solto;\n"
        "§ 1º Primeiro do outro artigo, de marca perdida.”\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "paragrafo", "quoted") == ["1", "2", "1"]


def test_bare_inciso_without_separator_completes_a_chain() -> None:
    text = (
        "Art. 1º São diretrizes:\n"
        "I - garantir o acesso;\n"
        "II promover a inclusão;\n"
        "III - respeitar a cultura;\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert _numbers(read_hierarchy(text), "inciso") == ["1", "2", "3"]
    # a conjunction after one space is a citation of the list, not a marker
    cited = "Art. 1º Texto:\nI - um;\nII - dois;\nIII e IV do artigo anterior.\n"
    assert _numbers(read_hierarchy(cited), "inciso") == ["1", "2"]
    # no strong member in the chain: a table of "I TRIMESTRE" rows is no list
    table = "Art. 1º Texto:\nI trimestre 10\nII trimestre 20\nIII trimestre 30\n"
    assert _numbers(read_hierarchy(table), "inciso") == []


def test_inline_quotation_mark_before_lower_case_prose_does_not_close_a_block() -> None:
    text = (
        "Art. 1º Acrescenta artigo:\n"
        '“Art. 3º-A Fica instituída a Campanha “Pontes para Vida" no Estado.\n'
        '§ 2º A Campanha Pontes para Vida" tem por objetivos:\n'
        "I - afixar cartazes;\n"
        "II - divulgar telefones.”\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "inciso", "quoted") == ["1", "2"]
    assert _numbers(report, "inciso") == []


# --- full-scale tournament, rounds 2 and 3 ---------------------------------------------
def test_inciso_glyph_n_is_a_stroke_pair_or_a_single_stroke() -> None:
    text = (
        "Art. 1º Os recursos serão destinados:\n"
        "I - programa de prevenção;\n"
        "N - programa de formação;\n"
        "NI - organizações de apoio;\n"
        "IV - outras ações.\n"
    )
    assert _numbers(read_hierarchy(text), "inciso") == ["1", "2", "3", "4"]
    text_in = (
        "Art. 1º Compõem:\n"
        "I - Tribunal Pleno;\n"
        "IN - Câmara Cível;\n"
        "HI - Câmara Criminal;\n"
        "IV - Câmara Especial.\n"
    )
    assert _numbers(read_hierarchy(text_in), "inciso") == ["1", "2", "3", "4"]


def test_inciso_inverted_exclamation_is_a_stroke() -> None:
    text = (
        "Art. 1º Compõem:\nI - um;\nII - dois;\nIII - tres;\n¡V - quatro;\nV - cinco.\n"
    )
    assert _numbers(read_hierarchy(text), "inciso") == ["1", "2", "3", "4", "5"]


def test_paragraph_number_ending_in_5_or_6_may_be_the_ordinal_sign() -> None:
    text = (
        "Art. 1º Texto principal da norma.\n"
        "§ 15 - Primeiro paragrafo da norma aqui.\n"
        "§ 26 - Segundo paragrafo da norma aqui.\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    assert _numbers(read_hierarchy(text), "paragrafo") == ["1", "2"]


def test_lower_case_art_opening_a_line_with_dash_and_capital_is_a_marker() -> None:
    text = (
        "art. 1º - Fica criado o Fundo de Previdência.\n"
        "art. 2º - Esta Lei entra em vigor.\n"
    )
    assert _numbers(read_hierarchy(text), "artigo") == ["1", "2"]
    # in running prose the lower-case form stays a citation
    prose = "Art. 1º Aplica-se o disposto no art. 5º - Para os fins.\n"
    assert _numbers(read_hierarchy(prose), "artigo") == ["1"]


def test_quoted_article_inserted_with_a_letter_suffix_reads_the_letter() -> None:
    text = (
        "Art. 1º A Lei nº 5 passa a vigorar acrescida dos artigos:\n\n"
        "“Art. 114-A À Superintendência compete:\n\n"
        "I - planejar;\n\n"
        "Art. 9° -B Ao Subdefensor cabe:\n\n"
        "Art. 6º A. As atribuições de cada cargo.”\n\n"
        "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "artigo", "quoted") == ["114A", "9B", "6A"]
    assert _numbers(report, "artigo") == ["1", "2"]
    # without a quoted block the same marker stays a plain separator + word
    own = "Art. 1º Texto.\nArt. 2º A Comissão decide.\nArt. 3º Fim.\n"
    assert _numbers(read_hierarchy(own), "artigo") == ["1", "2", "3"]


def test_article_repeating_the_next_ones_number_across_an_nr_is_quoted() -> None:
    text = (
        "Art. 1º A Lei nº 5 passa a vigorar com as alterações:\n\n"
        "“Art. 2º Texto citado de outra norma.\n\n"
        "Art. 3º A celebração do Termo será feita por escrito.\n\n"
        "§ 1º Primeiro paragrafo citado.\n\n"
        ".. (NR)\n\n"
        "Art. 3º Esta Lei Complementar acresce dispositivos à Lei nº 5.\n\n"
        "Art. 4º Esta Lei Complementar entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    own_arts = [
        (n["number"], text[n["start"] : n["start"] + 20])
        for n in report["nodes"]
        if n["kind"] == "artigo" and n["status"] == "own"
    ]
    assert [n for n, _ in own_arts] == [1, 2, 3, 4] or [n for n, _ in own_arts] == [
        1,
        3,
        4,
    ]
    assert any(t.startswith("Art. 3º Esta Lei") for n, t in own_arts)
    assert _numbers(report, "paragrafo", "quoted") == ["1"]
    assert _numbers(report, "paragrafo") == []


def test_quoted_block_skips_mid_line_citations_of_articles() -> None:
    text = (
        "Art. 1º A Lei nº 5 passa a vigorar com as alterações:\n\n"
        "“Art. 15 - A pontuação segue o disposto no parágrafo único do Art. 11 da Lei "
        "Federal nº 8.666.\n\n"
        "Art. 16 - Fim do bloco.”\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "artigo", "quoted") == ["15", "16"]


def test_misspelled_paragrafo_unico_with_i_for_r() -> None:
    text = "Art. 1º Texto.\nParágiafo único - Todas as unidades dispõem de espaço.\n"
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-1-par-unico"]


def test_lower_case_s_with_ordinal_sign_is_a_paragraph_sign() -> None:
    text = (
        "Art. 1º Fica autorizado o Poder Executivo.\n\n"
        "s lo - Terá preferência o servidor que neles residir.\n\n"
        "s 2o - Feita a avaliação do imóvel.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _paths(report)[:3] == ["art-1", "art-1-par-1", "art-1-par-2"]


def test_lower_case_s_before_a_clock_time_is_no_paragraph_sign() -> None:
    text = (
        "Art. 1º A biblioteca funciona das 8:00 horas às\n\n"
        "s\n22:00 horas, ininterruptamente.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "paragrafo") == []


def test_paragraph_spelled_out_with_a_number_opening_a_line() -> None:
    text = (
        "Art. 1º Os cargos são os seguintes.\n\n"
        "Parágrafo 1º - Serão nomeados pelo Presidente.\n\n"
        "Parágrafo 2º - Serão nomeados pelo Tribunal.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _paths(report)[:3] == ["art-1", "art-1-par-1", "art-1-par-2"]


def test_paragraph_sign_followed_by_a_period_or_a_colon() -> None:
    text = (
        "Art. 1º O orçamento do Estado.\n\n"
        "§. 1º - O orçamento consignará dotação.\n\n"
        "$:2º - As provas serão realizadas.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _paths(report)[:3] == ["art-1", "art-1-par-1", "art-1-par-2"]


def test_roman_numeral_after_a_capitalised_word_is_a_grade_not_an_inciso() -> None:
    text = (
        "Art. 1º Ficam criados cargos de Assessor IV - CDS-04, 25 cargos de Assessor "
        "V - CDS-05.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "inciso") == []


def test_bare_roman_numeral_before_a_capitalised_word_completes_a_chain() -> None:
    text = (
        "Art. 1º Ficam nomeados:\n\n"
        "I - Maria da Silva;\n\n"
        "II Mérito da Diretoria de Atividades;\n\n"
        "III - José de Souza.\n\n"
        "Art. 2º Este Decreto entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "inciso") == ["1", "2", "3"]


def test_quoted_block_restarts_its_chain_after_an_elision_line() -> None:
    text = (
        "Art. 1º Os incisos I, VII e XXIII passam a vigorar com a seguinte redação:\n\n"
        "“Art. 97. .....................\n\n"
        "I - formular a política estadual;\n\n"
        "..........\n\n"
        "VII - atuar com as Secretarias de Estado;\n\n"
        "..........\n\n"
        "XXIII - formular planos e programas.”\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "inciso", "quoted") == ["1", "7", "23"]


def test_quoted_block_paragraphs_and_incisos_may_jump_over_numbers() -> None:
    text = (
        "Art. 1º Os dispositivos abaixo passam a vigorar com a seguinte redação:\n\n"
        "“Art. 134. ...\n\n"
        "§ 1º A direção será constituída por Diretor.\n\n"
        "§ 6º O Diretor indicará um juiz de direito.\n\n"
        "§ 7º A escola funciona na capital.\n\n"
        "Art. 135. Compete ao Diretor:\n\n"
        "I - dirigir a escola;\n\n"
        "V - representar a escola.”\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "paragrafo", "quoted") == ["1", "6", "7"]
    assert _numbers(report, "inciso", "quoted") == ["1", "5"]


def test_paragrafo_unico_with_a_doubled_vowel() -> None:
    text = (
        "Art. 1º Todas as unidades dispõem de espaço.\n"
        "Paraâgrafo único - Será firmado convênio com o Banco.\n"
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-1-par-unico"]


def test_two_unreadable_markers_fill_two_missing_numbers_of_the_chain() -> None:
    text = (
        "Art. 1º Compete ao Conselho:\n\n"
        "I - emitir parecer sobre a proposta;\n\n"
        "II - estabelecer intercâmbio com os Conselhos;\n\n"
        "XQ - emitir parecer sobre assuntos técnicos;\n\n"
        "ym - apreciar os regimentos e currículos;\n\n"
        "V - zelar pelo cumprimento da lei;\n\n"
        "VI - fiscalizar a execução.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "inciso") == ["1", "2", "3", "4", "5", "6"]


def test_digit_one_after_alinea_k_is_the_letter_l() -> None:
    text = (
        "Art. 1º Ficam isentos:\n\n"
        "a) os órgãos;\n\nb) as autarquias;\n\nc) as fundações;\n\nd) os fundos;\n\n"
        "e) os conselhos;\n\nf) as escolas;\n\ng) os hospitais;\n\nh) os museus;\n\n"
        "i) as bibliotecas;\n\nj) os arquivos;\n\nk) os teatros.\n\n"
        "ASSEMBLÉIA LEGISLATIVA\n\n1) os projetos de assentamento;\n\nm) os demais casos.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "alinea")[-2:] == ["12", "13"]


def test_closing_article_keeps_its_printed_number_when_articles_are_missing() -> None:
    text = (
        "Art. 1º Fica criada a gratificação.\n\n"
        "Art. 2º O Poder Executivo enviará projeto de lei.\n\n"
        "4\n\nGOVERNO DO ESTADO\n\n"
        "Art. 6º Esta Lei entra em vigor na data de sua publicação.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "artigo") == ["1", "2", "6"]
    assert not article_closes(report)


def test_pound_sign_is_the_alinea_letter_f() -> None:
    text = (
        "Art. 1º Fica vedado:\n\n"
        "d) vender bens;\n\ne) alienar imóveis.\n\nGOVERNADORIA\n\n£) ceder veículos;\n\n"
        "g) doar valores.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "alinea") == ["4", "5", "6", "7"]


def test_quoted_block_alineas_may_skip_up_to_two_letters() -> None:
    text = (
        "Art. 1º O artigo 5º passa a vigorar com a seguinte redação:\n\n"
        "“Art. 5º Compete ao Conselho:\n\n"
        "I - fiscalizar:\n\n"
        "a) as contas;\n\n"
        "d) os contratos;\n\n"
        "e) os convênios.”\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "alinea", "quoted") == ["1", "4", "5"]


def test_inciso_glyph_q_is_a_stroke_pair() -> None:
    assert 12 in roman_readings("XQ")
    assert 7 in roman_readings("VQ")


def test_inciso_glyph_u_umlaut_is_a_stroke_pair() -> None:
    assert 2 in roman_readings("ü")
    assert 2 in roman_readings("ÍÍ")


def test_alinea_letter_printed_twice_at_a_line_start() -> None:
    text = (
        "Art. 1º Os quadros são:\n\n"
        "a) Quadro de Oficiais;\n\nb) Quadro de Praças.\n\nGOVERNADORIA\n\n"
        "Cc) Quadro de Oficiais Femininos;\n\nd) Quadro de Apoio.\n\n"
        "Art. 2º Esta Lei entra em vigor.\n"
    )
    report = read_hierarchy(text)
    assert _numbers(report, "alinea") == ["1", "2", "3", "4"]


# --------------------------------------------------------------------------
# Implicit single article: a one-provision act with no article marker
# --------------------------------------------------------------------------

_DECREE_HEAD = (
    "GOVERNO DO ESTADO DE RONDÔNIA\n\nGOVERNADORIA\n\nDECRETO Nº 101 DE 30 DE "
    "MARÇO DE 1982.\n\nO GOVERNADOR DO ESTADO DE RONDÔNIA, no uso de suas "
    "atribuições legais,\n\n"
)
_PROVISION = (
    "Conceder afastamento ao servidor JOSÉ PEREIRA DA SILVA, Técnico em "
    "Administração, para se deslocar até a cidade de Recife-PE, de 17 a 21 de abril."
)
_FECHO = "\n\nPorto Velho, em 30 de março de 1982.\n\nJORGE TEIXEIRA\n\nGovernador\n"


def _implicit(report: HierarchyReport) -> list[dict]:
    return [n for n in report["nodes"] if n["read_by"] == "implicit-single"]


def test_implicit_single_article_after_the_enacting_formula() -> None:
    text = _DECREE_HEAD + "RESOLVE:\n\n" + _PROVISION + _FECHO
    report = read_hierarchy(text)
    (art,) = _implicit(report)
    assert (art["kind"], art["number"], art["status"], art["raw"]) == (
        "artigo",
        1,
        "own",
        "",
    )
    assert text[art["start"] : art["end"]] == _PROVISION
    assert art["path"] == "art-1"
    assert article_closes(report)
    assert report["body_end"] == art["end"]


def test_implicit_single_article_from_a_garbled_formula_line() -> None:
    for garbled in ("RES OB VE", "RB SuO E VB:", "RA BES ON aV E:"):
        text = _DECREE_HEAD + garbled + "\n\n" + _PROVISION + _FECHO
        assert len(_implicit(read_hierarchy(text))) == 1, garbled


def test_implicit_single_article_inline_formula_and_signature_fecho() -> None:
    text = (
        "DECRETO Nº 1016\n\nO GOVERNADOR DO ESTADO, usando das atribuições que lhe "
        "confere a Lei, RESOLVE\n\n" + _PROVISION + "\n\nJorge\n\nGovernador\n"
    )
    report = read_hierarchy(text)
    (art,) = _implicit(report)
    assert text[art["start"] : art["end"]].endswith("de 17 a 21 de abril.")
    assert article_closes(report)


def test_implicit_single_article_needs_every_guard() -> None:
    body = _DECREE_HEAD + "RESOLVE:\n\n"
    no_fecho = body + _PROVISION + "\n"
    with_article = body + _PROVISION + "\n\nArt. 2º Esta Lei entra em vigor." + _FECHO
    numbered = (
        body + "1º - Colocar a servidora ANA à disposição.\n2º - Colocar JOSÉ." + _FECHO
    )
    second_article = (
        body + _PROVISION + "\n\nRevogam-se as disposições em contrário." + _FECHO
    )
    amending = (
        body + _PROVISION + " Nova redação: dar ao texto a seguinte redação." + _FECHO
    )
    short = body + "Nomear JOSÉ." + _FECHO
    no_formula = _DECREE_HEAD + _PROVISION + _FECHO
    title_only = (
        "DECRETO\n\nO GOVERNADOR DO ESTADO DE RONDÔNIA, no uso de suas atribuições, "
        "\n\nDECRETO\n\n" + _PROVISION + _FECHO
    )
    for name, text in {
        "no fecho": no_fecho,
        "an article marker exists": with_article,
        "numbered provisions": numbered,
        "a second article (revogação)": second_article,
        "amending wording": amending,
        "too short": short,
        "no enacting formula": no_formula,
        "DECRETO is the title, not the formula": title_only,
    }.items():
        report = read_hierarchy(text)
        assert not _implicit(report), name
        assert not article_closes(report), name


def test_implicit_single_article_marked_document_and_anchors() -> None:
    from leizilla import marcacao
    from leizilla.textlayer import article_anchors

    text = _DECREE_HEAD + "RESOLVE:\n\n" + _PROVISION + _FECHO
    report = read_hierarchy(text)
    xml = marcacao.build(text, marcacao.from_hierarchy(text, report, tipo="decreto"))
    assert '<art n="1" lido-por="implicit-single">Conceder afastamento' in xml
    assert marcacao.verify(xml, text) == []
    anchors, closes, last = article_anchors(text)
    assert closes and last == 1
    start = text.index("Conceder")
    assert anchors == [{"n": 1, "sufixo": None, "ini": start, "fim": start + 8}]


# --- a quoted block closed by a mark next to the full stop, before the host resumes ---
def test_quoted_block_closes_at_a_mark_followed_by_a_full_stop() -> None:
    # "1º" printed as "10", a block opened by a straight apostrophe, closed by '".':
    # the host's chain resumes with the Art. 2º after it (Lei 432/1992 style). The
    # block swallows more articles than a "short run", so only the host's number
    # (read by the chain, not the printed "10") and the resuming marker place its end.
    quoted = "".join(
        f"Art. {n}º - Dispõe sobre o assunto número {n} do Instituto.\n"
        for n in range(3, 10)
    )
    text = (
        "Art. 10 - A Lei nº 132 passa a vigorar conforme segue:\n"
        "'Art. 1º - Fica criado o Instituto de Pesos e Medidas.\n"
        + quoted
        + 'Art. 10 - O Poder Executivo regulamentará a presente Lei".\n'
        "Art. 2º - Ficam revogados os artigos 7º e 8º da Lei nº 132.\n"
        "Art. 3º - Esta Lei entra em vigor na data de sua publicação.\n"
        "Art. 4º - Revogam-se as disposições em contrário."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-2", "art-3", "art-4"]
    assert _paths(report, "quoted") == [
        "art-1",
        *[f"art-{n}" for n in range(3, 11)],
    ]
    assert report["closes"]


# --- a closing mark misplaced to the end of the previous line ---------------------
def test_quoted_block_closes_at_a_mark_a_few_words_before_the_resuming_article() -> (
    None
):
    # Stray marks in OCR noise unbalance the count; the block's mark ended up on the
    # line before the last words of the block ('oficial"' / 'Ajudante de Ordens.').
    text = (
        "Art. 1º - Os artigos 1º e 2º do Decreto-Lei nº 29 passam a vigorar com a "
        "seguinte redação:\n"
        "Art. 1º - A Polícia Militar é força auxiliar do Exército.\n"
        "Art. 2º - Compete à Polícia Militar:\n"
        "I - executar o policiamento ostensivo;\n"
        "II - atuar de maneira preventiva.\n"
        '“ “ ; "” ruído\n'
        "§ 1º - O Comandante-Geral será oficial da ativa.\n"
        '§ 2º - O Comandante-Geral disporá de um oficial"\n'
        "Ajudante de Ordens.\n"
        "Art. 2º - Revogam-se as disposições em contrário.\n"
        "Art. 3º - Este Decreto-Lei entrará em vigor na data de sua publicação."
    )
    report = read_hierarchy(text)
    assert _paths(report) == ["art-1", "art-2", "art-3"]
    assert _paths(report, "quoted")[:2] == ["art-1", "art-2"]
    assert report["closes"]


# --- "c) 11 - Dia ...": the number after an alínea marker is its own text ---------
def test_number_and_dash_after_an_alinea_marker_is_not_an_inciso() -> None:
    text = (
        "Art. 3º Ficam incluídas as seguintes datas no Calendário:\n"
        "I - fevereiro:\n"
        "a) 01 - Dia da Ratificação pela Convenção;\n"
        "b) 06 - Dia Internacional de Tolerância Zero;\n"
        "c) 11 - Dia Internacional de Mulheres e Meninas na Ciência; e\n"
        "d) 24 - Dia da Conquista do Voto Feminino no Brasil.\n"
        "II - março:\n"
        "a) 08 - Dia Internacional das Mulheres.\n"
        "Art. 4º Esta Lei entra em vigor."
    )
    report = read_hierarchy(text)
    paths = _paths(report)
    assert "art-3-inc-1-ali-d" in paths
    assert "art-3-inc-2-ali-a" in paths
    assert [p for p in paths if p.count("-inc-") and "-ali-" not in p] == [
        "art-3-inc-1",
        "art-3-inc-2",
    ]
