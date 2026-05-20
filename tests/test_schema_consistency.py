"""Tests for scripts/check_schema_consistency.py.

Each test crafts a minimal invalid XML that should trigger ONE invariant
from docs/SCHEMA.md §7. The positive fixtures (tests/fixtures/leizilla_xml/*.xml)
are also re-validated to ensure the checker doesn't false-positive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_schema_consistency as csc  # noqa: E402


FIXTURES = REPO_ROOT / "tests" / "fixtures" / "leizilla_xml"


def _write(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "lei.xml"
    f.write_text(content, encoding="utf-8")
    return f


def _wrap(
    body: str, urn_lex: str = "urn:lex:br;estado:rondonia;lei:2000-01-01;1234"
) -> str:
    """Wrap dispositivo body in a minimal <lei> envelope."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="{urn_lex}" vigente-em="2026-05-20">
{body}
</lei>"""


# ---------------------------------------------------------------------------
# Positive fixtures pass cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.xml")))
def test_positive_fixtures_pass(fixture: Path) -> None:
    violations = csc.check_file(fixture)
    assert violations == [], "\n".join(str(v) for v in violations)


# ---------------------------------------------------------------------------
# Negative cases — one per invariant
# ---------------------------------------------------------------------------


def test_inv01_diverge_true_without_texto(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      <fonte ia-id="leizilla-raw-ro-diario-2000-01-01-p0001" diverge="true"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 1 and "sem <texto>" in x.message for x in v)


def test_inv01_no_diverge_with_texto(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001">
        <texto>divergente sem flag</texto>
      </fonte>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 1 and "sem diverge" in x.message for x in v)


def test_inv02_revogacao_total_excludes_partial(tmp_path: Path) -> None:
    xml = _wrap(
        """  <revogacao em="2020-01-01" tipo="expressa" por="urn:lex:br;estado:rondonia;lei:2020-01-01;9999">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
  </revogacao>
  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <revogacao em="2019-01-01" tipo="expressa" por="urn:lex:br;estado:rondonia;lei:2019-01-01;8888">
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-08888"/>
    </revogacao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 2 for x in v)


def test_inv03_caducidade_with_por(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <revogacao em="2005-01-01" tipo="caducidade" por="urn:lex:br;estado:rondonia;lei:2005-01-01;5555">
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </revogacao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 3 and "caducidade" in x.message for x in v)


def test_inv03_expressa_without_por(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <revogacao em="2005-01-01" tipo="expressa">
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </revogacao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 3 and 'tipo="expressa"' in x.message for x in v)


def test_inv04_unknown_token(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="blarg-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 4 for x in v)


def test_inv06_inicio_required(tmp_path: Path) -> None:
    """versao em ≠ data-publicacao, sem alterado-por, sem <inicio>."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao em="2005-06-15">
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 6 for x in v)


def test_inv07_versions_out_of_order(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao em="2010-01-01" alterado-por="urn:lex:br;estado:rondonia;lei:2010-01-01;4321">
      <texto>X1</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-04321"/>
    </versao>
    <versao em="2005-01-01" alterado-por="urn:lex:br;estado:rondonia;lei:2005-01-01;5555">
      <texto>X2</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-05555"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 7 for x in v)


def test_inv08_bad_ia_id(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="not-a-valid-leizilla-id"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 8 for x in v)


def test_inv09_quality_on_normal_path(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1" quality="raw">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 9 for x in v)


def test_inv13_duplicate_path(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>A</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>
  <dispositivo path="art-1">
    <versao>
      <texto>B</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 13 for x in v)


def test_inv14_urn_zero_pad(tmp_path: Path) -> None:
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00042"/>
    </versao>
  </dispositivo>""",
        urn_lex="urn:lex:br;estado:rondonia;lei:1985-11-20;0042",
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 14 for x in v)


def test_inv14_no_zero_pad_for_5plus_digits(tmp_path: Path) -> None:
    """Number with 5+ digits doesn't trigger zero-pad rule."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-12345"/>
    </versao>
  </dispositivo>""",
        urn_lex="urn:lex:br;estado:rondonia;lei:2020-01-01;12345",
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert not any(x.invariant == 14 for x in v)


# ---------------------------------------------------------------------------
# Token map edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("titulo-lei", "titulo-lei"),
        ("ementa", "ementa"),
        ("preambulo", "preambulo"),
        ("art-1", "artigo"),
        ("art-5-par-2", "paragrafo"),
        ("art-5-par-2-inc-3", "inciso"),
        ("art-5-par-2-inc-3-ali-a", "alinea"),
        ("art-5-a", "artigo"),
        ("par-unico", "paragrafo"),
        ("art-1-par-unico", "paragrafo"),
        ("anexo-1", "anexo"),
        ("ocr-ruim", "bloco-ocr-ruim"),
        ("ocr-ruim-3", "bloco-ocr-ruim"),
        ("tit-1", "titulo"),
        ("tit-2-cap-1", "capitulo"),
        ("tit-2-cap-1-sec-3", "secao"),
        ("blarg", None),
        ("art", None),
        ("", None),
    ],
)
def test_token_map(path: str, expected: str | None) -> None:
    assert csc._path_tipo(path) == expected
