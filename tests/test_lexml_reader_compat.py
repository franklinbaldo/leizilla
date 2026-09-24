"""Regression guard for the LexML reader/producer boundary in issue #127.

The Leizilla parser intentionally produces a narrow legal-number subset
(digits plus an optional single-letter suffix), but readers must keep accepting
the broader LexML descriptor forms documented in docs/SCHEMA.md §5.6.
"""

from __future__ import annotations

import runpy
from pathlib import Path

from leizilla.etl import _RE_URN_LEX as ETL_URN_RE


ROOT = Path(__file__).resolve().parents[1]
CHECKER_URN_RE = runpy.run_path(
    str(ROOT / "scripts" / "check_schema_consistency.py")
)["_RE_URN_LEX"]


def _urn(numero: str) -> str:
    return f"urn:lex:br;rondonia:estadual:lei:1999-06-15;{numero}"


def test_etl_reader_keeps_general_lexml_descriptor_forms() -> None:
    for numero in ("72-a", "lex-16", "estatuto.idoso"):
        assert ETL_URN_RE.fullmatch(_urn(numero)), numero


def test_consistency_checker_keeps_general_lexml_descriptor_forms() -> None:
    for numero in ("72-a", "lex-16", "estatuto.idoso"):
        assert CHECKER_URN_RE.fullmatch(_urn(numero)), numero
