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
