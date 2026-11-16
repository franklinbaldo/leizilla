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
