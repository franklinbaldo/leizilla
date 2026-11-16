"""Tests for the sequence-aware hierarchy reader (offline, deterministic)."""

import time

import pytest

from leizilla.hierarchy_sequence import (
    HierarchyReport,
    alinea_readings,
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


def test_unreadable_marker_that_continues_a_list_keeps_the_scope_open() -> None:
    text = "Art. 1º Receitas:\nI — taxas;\nII — doações; e\nWI — outras.\nArt. 2º Fim."
    report = read_hierarchy(text)
    assert _unexplained(report) == ["WI —"]
    assert not report["closes"]


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
        "Art. 1º Compete:\nI - um;\nH - dois;\nNI — três;\nIV - quatro.\n"
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
