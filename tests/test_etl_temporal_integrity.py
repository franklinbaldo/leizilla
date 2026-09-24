"""Regression tests for issue #120 — temporal version integrity in xml_to_rows.

Two related bugs:

1. Null/ambiguous ``em``: when a dispositivo has multiple <versao> elements
   and one or more can't be assigned a real effective date (no explicit
   ``em=`` and no ancestor/act-date fallback), xml_to_rows must fail closed
   with a ValueError instead of silently emitting versões with `em=None`
   that collide as "vigente" at the same query date.
2. Document order != chronological order: `ate` for version N must be
   derived from versions sorted by `em`, not by their order in the XML.

These fixtures are deliberately not under tests/fixtures/leizilla_xml/:
that directory doubles as the invariant-clean corpus scanned by
test_schema_consistency.py, and out-of-order / dateless <versao> shapes
violate SCHEMA.md §7.07 by construction (same pattern used by the
versao_id-collision fixture in test_etl.py for issue #151 item 2).
"""

from __future__ import annotations

import datetime

import pytest

from leizilla.etl import xml_to_rows

# Two <versao> in document order newest-first; only chronological sorting
# (not document order) produces a correct em/ate chain.
_OUT_OF_ORDER = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2010-03-01;4243">
  <dispositivo path="art-1">
    <versao em="2020-01-01"><texto>nova redação</texto></versao>
    <versao em="2018-01-01"><texto>redação original</texto></versao>
  </dispositivo>
</lei>
"""

# Three versoes, fully scrambled, to confirm chaining beyond a simple swap.
_OUT_OF_ORDER_THREE = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2010-03-01;4246">
  <dispositivo path="art-1">
    <versao em="2022-06-01"><texto>terceira</texto></versao>
    <versao em="2018-01-01"><texto>primeira</texto></versao>
    <versao em="2020-01-01"><texto>segunda</texto></versao>
  </dispositivo>
</lei>
"""

# urn-lex date is year-only, so _extract_data_ato -> None; neither <versao>
# has an explicit `em`, so there is genuinely no date info anywhere for
# either version of this dispositivo.
_UNKNOWN_DATES = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2010;4244">
  <dispositivo path="art-1">
    <versao><texto>primeira</texto></versao>
    <versao><texto>segunda</texto></versao>
  </dispositivo>
</lei>
"""

# One <versao> has an explicit `em`, the other has none and there is no
# ancestor/act-date fallback (year-only URN) — still ambiguous: the dateless
# version's position relative to the dated one can't be determined.
_PARTIALLY_UNKNOWN_DATES = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2010;4245">
  <dispositivo path="art-1">
    <versao em="2015-05-01"><texto>com data</texto></versao>
    <versao><texto>sem data</texto></versao>
  </dispositivo>
</lei>
"""

# A single dateless <versao> on a dateless act is unambiguous (nothing to
# order against) and must keep working exactly as before.
_SINGLE_UNKNOWN_DATE = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2010;4247">
  <dispositivo path="art-1">
    <versao><texto>única versão, sem data</texto></versao>
  </dispositivo>
</lei>
"""


class TestOutOfOrderVersionsNormalized:
    def test_two_versions_reordered_chronologically(self) -> None:
        rows = xml_to_rows(_OUT_OF_ORDER, "leizilla-ro-lei-04243-2010", "ro")
        art1 = [r for r in rows if r["dispositivo_path"] == "art-1"]
        assert len(art1) == 2
        assert [r["em"] for r in art1] == [
            datetime.date(2018, 1, 1),
            datetime.date(2020, 1, 1),
        ]
        assert [r["texto"] for r in art1] == ["redação original", "nova redação"]
        # `ate` chains from the chronologically-next version, not the
        # document-order-next one.
        assert art1[0]["ate"] == datetime.date(2020, 1, 1)
        assert art1[1]["ate"] is None
        # No inverted interval (em > ate).
        for r in art1:
            assert r["ate"] is None or r["em"] <= r["ate"]

    def test_three_scrambled_versions_reordered_chronologically(self) -> None:
        rows = xml_to_rows(_OUT_OF_ORDER_THREE, "leizilla-ro-lei-04246-2010", "ro")
        art1 = [r for r in rows if r["dispositivo_path"] == "art-1"]
        assert [r["em"] for r in art1] == [
            datetime.date(2018, 1, 1),
            datetime.date(2020, 1, 1),
            datetime.date(2022, 6, 1),
        ]
        assert [r["texto"] for r in art1] == ["primeira", "segunda", "terceira"]
        assert [r["ate"] for r in art1] == [
            datetime.date(2020, 1, 1),
            datetime.date(2022, 6, 1),
            None,
        ]
        for r in art1:
            assert r["ate"] is None or r["em"] <= r["ate"]


class TestAmbiguousTimelineFailsClosed:
    def test_multiple_versions_without_any_effective_date_raises(self) -> None:
        with pytest.raises(ValueError, match="art-1"):
            xml_to_rows(_UNKNOWN_DATES, "leizilla-ro-lei-04244-2010", "ro")

    def test_multiple_versions_with_partial_dates_raises(self) -> None:
        with pytest.raises(ValueError, match="art-1"):
            xml_to_rows(_PARTIALLY_UNKNOWN_DATES, "leizilla-ro-lei-04245-2010", "ro")

    def test_single_version_without_date_still_allowed(self) -> None:
        # Not a regression target: single-version dispositivos with no
        # resolvable date have nothing to order and must keep working.
        rows = xml_to_rows(_SINGLE_UNKNOWN_DATE, "leizilla-ro-lei-04247-2010", "ro")
        art1 = [r for r in rows if r["dispositivo_path"] == "art-1"]
        assert len(art1) == 1
        assert art1[0]["em"] is None
        assert art1[0]["ate"] is None
