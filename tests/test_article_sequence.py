"""Tests for the sequence-aware article reader (offline, deterministic)."""

import pytest

from leizilla.article_sequence import ArticleRead, read_articles


def _numbers(text: str) -> list[int | None]:
    return [a["number"] for a in read_articles(text)["articles"]]


def test_clean_sequence_closes() -> None:
    text = (
        "Art. 1º Fica criado.\nArt. 2º Os recursos.\nArt. 3º Esta Lei entra em vigor."
    )
    report = read_articles(text)
    assert _numbers(text) == [1, 2, 3]
    assert report["closes"]
    assert report["corrected"] == 0


def test_ordinal_glued_as_digit_is_read_by_sequence() -> None:
    # "42" between 3 and 5 is "4º"; "Io" is "1º"; "2Q" is "2º".
    text = (
        "Art. Io. Fica.\nArt. 2Q - Os.\nArt. 3^ - Caberá.\n"
        "Art.\n42 - Esta Lei.\nArt. 5- - Revogam-se."
    )
    report = read_articles(text)
    assert _numbers(text) == [1, 2, 3, 4, 5]
    assert report["closes"]
    assert report["corrected"] == 1


def test_genuine_two_digit_article_is_kept() -> None:
    text = "\n".join(f"Art. {n}. Texto." for n in range(1, 44))
    report = read_articles(text)
    assert report["last"] == 43
    assert report["corrected"] == 0
    assert report["closes"]


def test_in_sentence_citation_is_a_reference() -> None:
    text = (
        "nos termos do Art. 42 da Constituição Estadual, promulgo:\n"
        "Art. 1º Fica.\nArt. 2º Esta Lei entra em vigor."
    )
    report = read_articles(text)
    assert [a["status"] for a in report["articles"]] == ["reference", "own", "own"]
    assert report["closes"]


def test_quoted_article_of_amended_law_does_not_break_the_chain() -> None:
    text = (
        "Art. 1º O art. 15 da Lei nº 10 passa a vigorar com a seguinte redação:\n"
        '"Art. 15. Novo texto."\n'
        "Art. 2º Esta Lei entra em vigor."
    )
    report = read_articles(text)
    assert [a["status"] for a in report["articles"]] == ["own", "quoted", "own"]
    assert report["closes"]


def test_unquoted_leftover_keeps_the_norm_open() -> None:
    text = "Art. 1º Fica.\nArt. 2º Vigora.\nArt. 2º Repetido."
    report = read_articles(text)
    assert report["unexplained"] == 1
    assert not report["closes"]


def test_gap_is_reported_as_missing() -> None:
    report = read_articles("Art. 1º A.\nArt. 2º B.\nArt. 4º D.\nArt. 5º E.")
    assert report["missing"] == [3]
    assert not report["closes"]


def test_letter_suffix_repeats_the_number() -> None:
    report = read_articles("Art. 1º A.\nArt. 1º-A. B.\nArt. 2º C.")
    assert [a["number"] for a in report["articles"]] == [1, 1, 2]
    assert report["closes"]


def test_no_articles_does_not_close() -> None:
    report = read_articles("Texto sem artigos.")
    assert report["last"] == 0
    assert not report["closes"]


# --- prefix forms (Defect A) ----------------------------------------------------------


def _single(line: str) -> ArticleRead:
    """The one candidate of a line read on its own (article 1 reads without context)."""
    articles = read_articles(line)["articles"]
    assert len(articles) == 1, articles
    return articles[0]


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("ART. 19 —- O Decreto-Lei fica revogado.", 1),
        ("Artigo 19 - É assegurada a publicidade.", 1),
        ("Alt Io. Oquadro dispõe sobre a estrutura.", 1),
        ("Ait. Io - Fica alterado o quadro.", 1),
        ("ARTIGO 1º Fica criado o conselho.", 1),
        ("Artigo 2º Os recursos correm.", 2),
    ],
)
def test_prefix_forms_are_read_as_article_starts(line: str, number: int) -> None:
    article = _single(line)
    assert article["status"] == "own"
    assert article["number"] == number


def test_ait_with_ocr_eight_is_read_in_sequence() -> None:
    body = "\n".join(f"Art. {n}º Fica." for n in range(1, 8))
    report = read_articles(body + "\nAit. 8o Esta Lei entra em vigor.")
    assert report["articles"][-1]["raw"] == "Ait. 8o"
    assert report["articles"][-1]["number"] == 8
    assert report["closes"]


def test_a_r_t_on_its_own_line_takes_the_number_on_the_next_line() -> None:
    text = (
        "Art. 1º Fica.\nArt. 2º Fica.\nArt. 3º Fica.\n"
        "A r/t.\n49 - Revogam-se as disposições em contrário."
    )
    report = read_articles(text)
    assert report["articles"][-1]["raw"].startswith("A r/t.")
    assert report["articles"][-1]["number"] == 4
    assert report["closes"]


def test_ait_and_alt_at_line_start_are_article_markers() -> None:
    text = "Ait. Io - Caput.\nAlt 2 - Outro.\nArt. 3º Vigora."
    report = read_articles(text)
    assert [a["number"] for a in report["articles"]] == [1, 2, 3]
    assert [a["status"] for a in report["articles"]] == ["own", "own", "own"]


@pytest.mark.parametrize(
    "text",
    [
        "Alto Paraíso e Alta Floresta são municípios de Rondônia.",
        "Alto Paraíso fica no Estado.\nArt. 1º Fica criado o conselho.",
        "Alta Floresta 10 anos depois.\nArt. 1º Fica criado o conselho.",
    ],
)
def test_alto_and_alta_at_line_start_are_not_articles(text: str) -> None:
    articles = read_articles(text)["articles"]
    assert all(a["raw"].startswith("Art") for a in articles)


def test_lowercase_art_in_a_sentence_is_still_a_citation_not_a_marker() -> None:
    text = "Art. 1º Fica revogado o art. 5º da Lei.\nArt. 2º Vigora."
    report = read_articles(text)
    assert [a["number"] for a in report["articles"]] == [1, 2]
    assert report["closes"]


def test_mid_sentence_alt_and_ait_are_not_markers() -> None:
    text = "Art. 1º Fica mantido o Alt. 5 do regimento.\nArt. 2º Vigora."
    report = read_articles(text)
    assert [a["raw"][:3] for a in report["articles"]] == ["Art", "Art"]


# --- letter suffix (Defect B) ---------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Art. 2º - A Comissão decide.",
        "Art. 25-O Tesoureiro recebe.",
        "Art. 12-B Fica criado.",
        "Art. 2º - A lei vale.",
    ],
)
def test_separator_or_word_after_the_number_is_not_a_suffix(line: str) -> None:
    assert _single(line)["suffix"] is None


@pytest.mark.parametrize(
    ("line", "suffix"),
    [
        ("Art. 5º-A. Texto.", "A"),
        ("Art. 5-A - Texto.", "A"),
        ("Art. 5-B:", "B"),
        ("Art. 5-C\nTexto.", "C"),
        ("Art. 5-D — Texto.", "D"),
    ],
)
def test_glued_letter_before_punctuation_or_line_end_is_a_suffix(
    line: str, suffix: str
) -> None:
    assert _single(line)["suffix"] == suffix


def test_suffix_candidate_does_not_invent_a_chain_break() -> None:
    text = "Art. 1º Fica.\nArt. 2º - A Comissão decide.\nArt. 3º Vigora."
    report = read_articles(text)
    assert [a["number"] for a in report["articles"]] == [1, 2, 3]
    assert all(a["suffix"] is None for a in report["articles"])
    assert report["closes"]


def test_stray_e_opening_a_line_does_not_make_a_citation_of_the_article() -> None:
    # lei-00460 and decreto-lei-00044: a lone "e" glyph above the last article. Read as
    # a citation, "Art. 6º" was dropped and the norm closed one article short.
    text = "Art. 1º Fica.\nArt. 2º Vigora.\n\ne Art. 3º - Revogam-se as disposições."
    report = read_articles(text)
    assert [a["status"] for a in report["articles"]] == ["own", "own", "own"]
    assert report["closes"]


def test_stray_e_before_a_blank_gap_is_read_as_the_article() -> None:
    # decreto-lei-00044: "e" on its own line, two blank lines, then "Art. 29." (2º).
    text = "Art. 19. Fica autorizado.\ne\n\n\nArt. 29. As garantias das operações."
    report = read_articles(text)
    assert [a["number"] for a in report["articles"]] == [1, 2]


def test_citation_after_a_word_on_the_same_line_is_still_a_reference() -> None:
    text = (
        "Art. 1º Fica.\nAs regras do Art. 5º e Art. 6º da Constituição.\n"
        "Art. 2º Esta Lei entra em vigor."
    )
    report = read_articles(text)
    assert [a["status"] for a in report["articles"]] == [
        "own",
        "reference",
        "reference",
        "own",
    ]
    assert report["closes"]


def test_bare_article_word_with_number_three_digits_glued_ordinal() -> None:
    # lei-00054: "Art." on its own line, then "109" for "10º" (the º read as a 9).
    lines = [f"Art. {n}º Texto {n}." for n in range(1, 10)]
    text = "\n".join(lines) + "\nArt.\n\n109 - Esta Lei entra em vigor."
    report = read_articles(text)
    assert report["articles"][-1]["number"] == 10
    assert report["closes"]


def test_three_digit_article_with_glued_ordinal_pair_is_the_one_digit_article() -> None:
    # lei-00325 and lei-00426: "Art. 220" and "Art. 290" are "Art. 2º".
    for number in ("220", "290"):
        text = f"Art. 1º Fica.\n Art. {number} - Esta Lei entra em vigor."
        report = read_articles(text)
        assert [a["number"] for a in report["articles"]] == [1, 2], number
        assert report["closes"], number


def test_article_word_with_separator_glyph_is_a_marker() -> None:
    # lei-00086: "Art»" then the number on the next line.
    text = "Art. 1º Fica.\nArt»\n2º Vigora.\nArt. 3º Esta Lei entra em vigor."
    report = read_articles(text)
    assert [a["number"] for a in report["articles"]] == [1, 2, 3]
    assert report["closes"]


def _after_chain(line: str, number: int) -> str:
    """Ordinary articles 1..number-1 followed by ``line``, so the chain can reach it."""
    head = "".join(f"Art. {n}º Fica.\n" for n in range(1, number))
    return head + line


def test_dash_glued_article_marker_is_read_in_sequence() -> None:
    # Round 1 (a1d6e070, 9f411c76, d55d3c7a): "Art- 13-0 débito" after article 12.
    report = read_articles(_after_chain("Art- 13-O débito bancário.", 13))
    assert report["articles"][-1]["raw"] == "Art- 13"
    assert report["articles"][-1]["number"] == 13
    assert report["articles"][-1]["status"] == "own"


def test_dash_marker_with_space_or_no_digit_is_not_an_article() -> None:
    assert read_articles("Art-Gastro do projeto.")["articles"] == []
    assert read_articles("Art - 5 do projeto.")["articles"] == []


def test_dash_marker_cited_inside_a_sentence_stays_a_reference() -> None:
    report = read_articles("Nos termos do Art-5 da Lei, o servidor responde.")
    assert report["articles"][0]["status"] == "reference"


@pytest.mark.parametrize(
    ("line", "number"),
    [
        # Round 1 (9dd8b414, ab54e259): "Arto", "Arts", "Arte" for "Art." before a number.
        ("Arto 6º - As alíquotas do IPVA são:", 6),
        ("Arts 7º - O imposto de que trata esta Lei é", 7),
        ("Arte 5º - A base de cálculo do imposto é o valor", 5),
    ],
)
def test_garbled_article_word_before_a_number_is_a_marker(
    line: str, number: int
) -> None:
    article = read_articles(_after_chain(line, number))["articles"][-1]
    assert article["status"] == "own"
    assert article["number"] == number


def test_garbled_article_word_without_a_number_is_not_a_marker() -> None:
    # d8978969: "Arte e Revogam-se as disposições em contrário." is prose.
    assert (
        read_articles("Arte e Revogam-se as disposições em contrário.")["articles"]
        == []
    )
    assert read_articles("Parte 3 do Edital de licitação.")["articles"] == []


def test_ar_dot_and_ari_dot_garbles_are_article_markers() -> None:
    # aa1b8e1e: "Ar. Io - Fica criada"; fe38326a: "Ari. 1° Ficaacrescido".
    first = read_articles("Ar. Io - Fica criada a Agência de Defesa Sanitária.")
    assert first["articles"][0]["number"] == 1
    assert first["articles"][0]["status"] == "own"
    second = read_articles(_after_chain("Ari. 4° Fica acrescido o § 3o.", 4))
    assert second["articles"][-1]["number"] == 4
    assert second["articles"][-1]["status"] == "own"


def test_ar_word_without_number_or_a_longer_name_is_not_a_marker() -> None:
    assert read_articles("Ariquemes tem 3 distritos.")["articles"] == []
    assert read_articles("Ar. Fica criada a Agência.")["articles"] == []


def test_slash_garbled_article_marker_is_read_in_sequence() -> None:
    # aa1b8e1e "\Art/12" and c954a4b2 "X rt/4º Este Decreto entra em vigor".
    report = read_articles(_after_chain("X rt/4º Este Decreto entra em vigor.", 4))
    assert report["articles"][-1]["number"] == 4
    assert report["articles"][-1]["status"] == "own"
    report = read_articles(_after_chain("\\Art/12 Compreendem as seguintes.", 12))
    assert report["articles"][-1]["number"] == 12
    assert report["articles"][-1]["status"] == "own"


def test_slash_without_a_number_is_not_a_marker() -> None:
    assert read_articles("Consulte o Art/Doc anexo ao processo.")["articles"] == []


def test_mixed_case_art_word_with_number_on_next_line_is_a_marker() -> None:
    # lei-00315 441ee8c7: "ARt." then "9 - Revogam-se" on the next line.
    text = _after_chain("ARt.\n9 - Revogam-se as disposições em contrário.", 9)
    report = read_articles(text)
    assert report["articles"][-1]["raw"].startswith("ARt.")
    assert report["articles"][-1]["number"] == 9
    assert report["articles"][-1]["status"] == "own"


def test_mixed_case_art_inside_a_word_is_not_a_marker() -> None:
    assert read_articles("PARt. 5 do regimento interno.")["articles"] == []


# --- tournament round 5: words and citations that are not markers -------------------
@pytest.mark.parametrize(
    "line",
    [
        "ARTIFÍCIOS DE FOGOS 2,0 8.1.7.2",
        "ARTICULAÇÃO COM A UNIÃO",
        "ARTISTICO E ARQUEOLÓGICO 80.000",
    ],
)
def test_capitalised_word_starting_with_art_is_not_a_marker(line: str) -> None:
    # lei-00701, lc-00042, lei-00137: "ART" + "I" read as article 1 of a table heading.
    assert read_articles(f"Art. 1º Fica criado.\n{line}\n")["articles"][1:] == []


def test_capitalised_article_word_with_roman_or_digit_is_still_a_marker() -> None:
    report = read_articles("ARTIGO 1º Fica criado.\nART. 2º Fica revogado.\n")
    assert [a["number"] for a in report["articles"]] == [1, 2]


@pytest.mark.parametrize(
    "text",
    [
        # lei-00xxx: the enacting formula cites the Constitution after a paragraph sign.
        "nos termos do § 29, Artigo 48, da Constituição do Estado, a seguinte Lei:\n",
        "nos termos do §70, do Art. 42 da Constituição do Estado, promulgo\n",
    ],
)
def test_citation_after_a_paragraph_sign_is_a_reference(text: str) -> None:
    articles = read_articles(text)["articles"]
    assert articles and all(a["status"] == "reference" for a in articles)


@pytest.mark.parametrize(
    "citation",
    [
        "(Artigo 4º, § 2º, II, da Lei Complementar Federal n. 101/2000)",
        "(Art. 4º, $ 1º, da Lei Complementar Federal)",
        "Art. 42 da Constituição Estadual.",
        "Art. 37, IX, Constituição Federal",
    ],
)
def test_marker_followed_by_a_cited_norm_is_a_reference(citation: str) -> None:
    text = f"Art. 1º Fica criado o fundo.\nAnexo de metas fiscais {citation}\n"
    statuses = [a["status"] for a in read_articles(text)["articles"]]
    assert statuses == ["own", "reference"]


def test_amending_caput_subject_citation_is_left_to_the_chain() -> None:
    # "Art. 1º - 0 Art. 2º da Lei nº 104 passa a ter" (OCR zero) is not rewritten as a reference:
    # the guard keeps the earlier reading of the subject of an amending caput.
    text = "Art. 1º - 0 Art. 2º da Lei nº 104, de 20/05/86, passa a ter a seguinte.\n"
    statuses = [a["status"] for a in read_articles(text)["articles"]]
    assert "reference" not in statuses[1:]


def test_article_opening_with_da_in_its_caput_text_is_kept() -> None:
    text = "Art. 1º Fica criado o cargo.\nArt. 2º Esta Lei entra em vigor.\n"
    assert [a["status"] for a in read_articles(text)["articles"]] == ["own", "own"]


def test_paragraph_sign_ending_a_sentence_does_not_make_the_next_article_a_citation() -> (
    None
):
    # "...a ser § 1º.\nArt. 2º Vigora." — the period closes the sentence.
    text = "Art. 1º O art. 3º passa a ser § 1º.\nArt. 2º Vigora.\n"
    statuses = [a["status"] for a in read_articles(text)["articles"]]
    assert statuses[-1] == "own"


def test_truncated_article_word_with_number_on_the_next_line_is_a_marker() -> None:
    # lei-00433 (4f773c3e): "rt." alone on its line, the number below.
    text = "Art. 1º Fica criado o fundo.\nrt.\n2º - Esta Lei entra em vigor.\n"
    assert [a["number"] for a in read_articles(text)["articles"]] == [1, 2]


def test_suffixed_article_is_not_read_ahead_of_the_plain_one_after_it() -> None:
    text = (
        "Art. 1º Fica criada a Turma.\n\n"
        "Art. 2º Ficam acrescidos os arts.:\n\n"
        "Art. 3º Fica criado o cargo.\n\n"
        "Art. 49-A. Compõem o Sistema.\n\n"
        "Art.49-B. A Turma de Uniformização.\n\n"
        "Art. 49-C. As Turmas Recursais têm sede.\n\n"
        "Art. 4° Esta Lei entra em vigor.\n"
    )
    report = read_articles(text)
    own = [
        (a["number"], a["suffix"]) for a in report["articles"] if a["status"] == "own"
    ]
    assert (4, None) in own
    assert not any(n == 4 and sfx for n, sfx in own)
