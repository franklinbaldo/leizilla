"""Tests for the sequence-aware article reader (offline, deterministic)."""

from leizilla.article_sequence import read_articles


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
    report = read_articles("Art. 1º A.\nArt. 1º-A B.\nArt. 2º C.")
    assert [a["number"] for a in report["articles"]] == [1, 1, 2]
    assert report["closes"]


def test_no_articles_does_not_close() -> None:
    report = read_articles("Texto sem artigos.")
    assert report["last"] == 0
    assert not report["closes"]
