"""Testes unitários para o módulo leizilla.ocr e o comando cmd_fetch_ocr."""

from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from leizilla.cli import app
from leizilla.ocr import clean_ocr_text, normalize_text, fetch_and_clean_ocr

runner = CliRunner()


def test_clean_ocr_text():
    assert clean_ocr_text("Hello\x00 World\r\n") == "Hello World"
    assert clean_ocr_text("") == ""
    assert clean_ocr_text(None) == ""
    # Portuguese characters (Latin-1 range \x80-\xff) must be preserved
    assert clean_ocr_text("ação legislação ônibus") == "ação legislação ônibus"
    assert clean_ocr_text("Art. 5º — são garantidos") == "Art. 5º — são garantidos"


def test_normalize_text():
    # Test accents
    assert normalize_text("Constituição") == "constituicao"
    # Test lowercase and punctuation
    assert normalize_text("Lei Nº 12.345, de 2026!") == "lei no 12345 de 2026"
    # Test spaces and newlines
    assert (
        normalize_text("lei   ordinaria\n\ncomplementar")
        == "lei ordinaria complementar"
    )
    # Empty
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


def test_clean_ocr_text_preserves_portuguese_accents():
    """Regressão do incidente M10.2: regex [\\x7f-\\xff] removia ç/ã/é/õ/ú/â/ê.

    clean_ocr_text deve remover apenas control chars, preservando todo o
    range Latin-1 usado em texto jurídico português.
    """
    accented = "çãéõúâê ÇÃÉÕÚÂÊ àèìòù íóá ü ô"
    assert clean_ocr_text(accented) == accented

    juridico = "revogação São Paulo parágrafo único vigência município"
    assert clean_ocr_text(juridico) == juridico

    # Cada caractere acentuado sobrevive individualmente
    for ch in "çãéõúâê":
        assert clean_ocr_text(f"a{ch}b") == f"a{ch}b", f"perdeu {ch!r}"


def test_clean_ocr_text_removes_control_chars_keeps_newlines():
    assert clean_ocr_text("Art. 1\x00\x08\x0b\x0c\x1f\x7fº") == "Art. 1º"
    # \t \n \r são preservados no meio do texto
    assert clean_ocr_text("linha1\nlinha2\tcol\r\nfim") == "linha1\nlinha2\tcol\r\nfim"


def test_clean_ocr_text_empty_and_whitespace_only():
    assert clean_ocr_text("") == ""
    assert clean_ocr_text("   \n\t  ") == ""


def test_normalize_text_collapses_whitespace():
    assert normalize_text("lei    com   espaços") == "lei com espacos"
    assert normalize_text("linha1\n\n\nlinha2\t\tlinha3") == "linha1 linha2 linha3"
    assert normalize_text("  bordas  ") == "bordas"


def test_normalize_text_empty_and_whitespace_only():
    assert normalize_text("") == ""
    assert normalize_text("   \n\t  ") == ""


def test_normalize_text_hyphenation_current_behavior():
    """normalize_text NÃO junta palavras hifenizadas em quebra de linha.

    Comportamento atual documentado: o hífen é removido como pontuação e a
    quebra vira espaço, então "publi-\\ncação" vira duas palavras.
    """
    assert normalize_text("publi-\ncação") == "publi cacao"
    # Hífen no meio da palavra (sem quebra) também é removido sem juntar
    assert normalize_text("decreto-lei") == "decretolei"


@patch("leizilla.ocr.fetch_ocr")
def test_fetch_and_clean_ocr(mock_fetch):
    mock_fetch.return_value = "raw \x00text"
    assert fetch_and_clean_ocr("ia-item-123") == "raw text"
    mock_fetch.assert_called_once_with("ia-item-123")

    mock_fetch.return_value = None
    assert fetch_and_clean_ocr("ia-item-123") is None


def test_cli_fetch_ocr_no_laws():
    with patch("leizilla.storage.DuckDBStorage") as mock_db_class:
        mock_db = MagicMock()
        mock_db.get_leis_pending_ocr.return_value = []
        mock_db_class.return_value = mock_db

        result = runner.invoke(app, ["fetch-ocr"])
    assert result.exit_code == 0
    assert "Nenhuma lei sem OCR encontrada no banco" in result.output


def test_cli_fetch_ocr_success():
    laws = [
        {
            "id": "ro-casacivil-lei-05120",
            "url_pdf_ia": "https://archive.org/details/leizilla-raw-ro-casacivil-lei-05120",
            "ente": "ro",
        }
    ]

    with (
        patch("leizilla.storage.DuckDBStorage") as mock_db_class,
        patch(
            "leizilla.ocr.fetch_and_clean_ocr", return_value="lei constituicao"
        ) as mock_ocr_fetch,
    ):
        mock_db = MagicMock()
        mock_db.get_leis_pending_ocr.return_value = laws
        mock_db_class.return_value = mock_db

        result = runner.invoke(app, ["fetch-ocr"])

    assert result.exit_code == 0
    assert "Busca de OCR concluída: 1 com sucesso, 0 falhas" in result.output
    mock_ocr_fetch.assert_called_once_with("leizilla-raw-ro-casacivil-lei-05120")
    mock_db.update_lei.assert_called_once_with(
        "ro-casacivil-lei-05120",
        {
            "texto_completo": "lei constituicao",
            "texto_normalizado": "lei constituicao",
        },
    )
