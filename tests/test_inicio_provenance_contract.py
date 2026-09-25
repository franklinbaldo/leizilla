"""Regression contract for #157: URN act dates are not publication evidence."""

from leizilla.etl import xml_to_rows

NS = "https://leizilla.org/lei/0.1"


def _xml(inicio: str = "") -> str:
    return f"""<lei xmlns=\"{NS}\" urn-lex=\"urn:lex:br;rondonia:estadual:lei:2020-01-02;123\">
  <dispositivo path=\"art-1\">
    <versao>
      {inicio}
      <texto>Texto.</texto>
    </versao>
  </dispositivo>
</lei>"""


def test_urn_fallback_is_act_date_not_publication() -> None:
    row = xml_to_rows(_xml(), "leizilla-ro-lei-123-2020", "ro")[0]

    assert row["em"].isoformat() == "2020-01-02"
    assert row["inicio_tipo"] == "data-ato"


def test_explicit_publication_provenance_is_preserved() -> None:
    row = xml_to_rows(
        _xml('<inicio tipo="data-publicacao"/>'),
        "leizilla-ro-lei-123-2020",
        "ro",
    )[0]

    assert row["inicio_tipo"] == "data-publicacao"


def test_no_inicio_element_has_no_inicio_fontes() -> None:
    row = xml_to_rows(_xml(), "leizilla-ro-lei-123-2020", "ro")[0]

    assert row["inicio_fontes"] is None


def test_inicio_fonte_evidence_reaches_the_row() -> None:
    """Issue #229: <inicio>'s <fonte> evidence must not be dropped before the row."""
    import json

    row = xml_to_rows(
        _xml(
            '<inicio tipo="data-publicacao">'
            '<fonte ia-id="leizilla-raw-ro-casacivil-lei-00123"/>'
            "</inicio>"
        ),
        "leizilla-ro-lei-123-2020",
        "ro",
    )[0]

    assert json.loads(row["inicio_fontes"]) == [
        {"ia_id": "leizilla-raw-ro-casacivil-lei-00123"}
    ]


def test_inicio_fonte_without_ia_id_fails_closed() -> None:
    import pytest

    with pytest.raises(ValueError, match="ia-id"):
        xml_to_rows(
            _xml('<inicio tipo="data-publicacao"><fonte/></inicio>'),
            "leizilla-ro-lei-123-2020",
            "ro",
        )
