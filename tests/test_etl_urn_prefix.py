from __future__ import annotations

import pytest

from leizilla.etl import xml_to_rows


def _xml(urn: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1" '
        f'urn-lex="{urn}" vigente-em="2026-05-20">'
        '<dispositivo path="ementa"><versao><texto>Texto.</texto>'
        '<fonte ia-id="leizilla-raw-ro-casacivil-lei-00072"/>'
        '</versao></dispositivo></lei>'
    )


def test_literal_null_urn_is_rejected_at_etl_boundary() -> None:
    with pytest.raises(ValueError, match="Invalid URN-LEX prefix"):
        xml_to_rows(_xml("null"), "leizilla-ro-lei-00072-a-1999", "ro")


def test_foreign_identifier_is_rejected_at_etl_boundary() -> None:
    with pytest.raises(ValueError, match="Invalid URN-LEX prefix"):
        xml_to_rows(_xml("law:ro:72-a"), "leizilla-ro-lei-00072-a-1999", "ro")


def test_mis_cased_brazilian_prefix_keeps_existing_id_fallback() -> None:
    rows = xml_to_rows(
        _xml("URN:LEX:BR;rondonia:estadual:lei:1999-06-15;72-a"),
        "leizilla-ro-lei-00072-a-1999",
        "ro",
    )
    assert rows[0]["numero_lei"] == "72-a"
    assert rows[0]["tipo_lei"] == "lei"
    assert rows[0]["ano_lei"] == 1999
