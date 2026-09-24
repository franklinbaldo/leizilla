"""TDD regressions for issue #120 temporal version ordering."""

import datetime

import pytest

from leizilla.etl import xml_to_rows


_OUT_OF_ORDER = """<lei xmlns="https://leizilla.org/lei/0.1"
  schema-version="0.1"
  urn-lex="urn:lex:br;rondonia:estadual:lei:2010-03-01;4243">
  <dispositivo path="art-1">
    <versao em="2020-01-01"><texto>nova</texto></versao>
    <versao em="2018-01-01"><texto>antiga</texto></versao>
  </dispositivo>
</lei>"""

_UNKNOWN_DATES = """<lei xmlns="https://leizilla.org/lei/0.1"
  schema-version="0.1"
  urn-lex="urn:lex:br;rondonia:estadual:lei:2010;4244">
  <dispositivo path="art-1">
    <versao><texto>primeira</texto></versao>
    <versao><texto>segunda</texto></versao>
  </dispositivo>
</lei>"""


def test_out_of_order_versions_are_normalized_chronologically():
    rows = xml_to_rows(_OUT_OF_ORDER, "leizilla-ro-lei-04243-2010", "ro")
    art1 = [r for r in rows if r["dispositivo_path"] == "art-1"]
    assert [r["em"] for r in art1] == [
        datetime.date(2018, 1, 1),
        datetime.date(2020, 1, 1),
    ]
    assert art1[0]["ate"] == datetime.date(2020, 1, 1)
    assert art1[1]["ate"] is None


def test_multiple_versions_without_effective_dates_fail_closed():
    with pytest.raises(ValueError, match="effective date|timeline|version"):
        xml_to_rows(_UNKNOWN_DATES, "leizilla-ro-lei-04244-2010", "ro")
