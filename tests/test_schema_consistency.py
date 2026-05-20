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
        ("art-5-a-par-2", "paragrafo"),
        ("par-unico", "paragrafo"),
        ("art-1-par-unico", "paragrafo"),
        ("anexo-1", "anexo"),
        ("ocr-ruim", "bloco-ocr-ruim"),
        ("ocr-ruim-3", "bloco-ocr-ruim"),
        ("tit-1", "titulo"),
        ("tit-2-cap-1", "capitulo"),
        ("tit-2-cap-1-sec-3", "secao"),
        ("disp-transitoria-3", "disposicao-transitoria"),
        ("disp-transitoria-3-par-2", "paragrafo"),
        ("blarg", None),
        ("art", None),
        ("", None),
        # Codex P1 #1: garbage prefix must not classify by suffix.
        ("foo-art-1", None),
        ("art-5-foo", None),
        ("xxx-tit-1-cap-1", None),
        ("art-1-blarg-2", None),
    ],
)
def test_token_map(path: str, expected: str | None) -> None:
    assert csc._path_tipo(path) == expected


# ---------------------------------------------------------------------------
# Codex P2 #3: invalid calendar dates don't crash
# ---------------------------------------------------------------------------


def test_invalid_calendar_date_in_urn_does_not_crash(tmp_path: Path) -> None:
    """URN regex accepts `2020-13-01` (digit-shape only) but it's not a
    real date. Checker must not crash."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>""",
        urn_lex="urn:lex:br;estado:rondonia;lei:2020-13-01;1234",
    )
    # Should complete without raising.
    violations = csc.check_file(_write(tmp_path, xml))
    # Doesn't matter which invariants fire — just that we didn't crash.
    assert isinstance(violations, list)


# ---------------------------------------------------------------------------
# Codex P1 #2: vigência irresolvível
# ---------------------------------------------------------------------------


def test_inv05_urn_present_but_undecodable(tmp_path: Path) -> None:
    """URN presente mas regex §5.6 falha → vigência irresolvível."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>""",
        urn_lex="urn:lex:br;malformed",
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 5 for x in v)


def test_inv07_inherited_em_catches_out_of_order(tmp_path: Path) -> None:
    """Codex P1: sub-dispositivo cuja primeira versão herda `em` do parent
    e a segunda versão declara `em` ANTERIOR — out of order que o checker
    antigo perdia (comparava com pub em vez de com o em herdado)."""
    xml = _wrap(
        """  <dispositivo path="art-3">
    <versao em="2018-04-10" alterado-por="urn:lex:br;estado:rondonia;lei:2018-04-10;4321">
      <texto>v1 art-3</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-04321"/>
    </versao>
    <dispositivo path="art-3-par-1">
      <versao>
        <texto>v1 par-1 (herda em=2018-04-10 do parent)</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-04321"/>
      </versao>
      <versao em="2010-01-01" alterado-por="urn:lex:br;estado:rondonia;lei:2010-01-01;5555">
        <texto>v2 par-1 — out of order! 2010 antes de 2018</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-05555"/>
      </versao>
    </dispositivo>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 7 for x in v), (
        f"esperava §7.7 violation; got: {[str(x) for x in v]}"
    )


def test_inv04_mixed_org_normative_rejected(tmp_path: Path) -> None:
    """Codex P1: tit-1-art-2 e art-2-cap-1 são paths mistos — §4.2 proíbe."""
    for bad in ("tit-1-art-2", "art-2-cap-1", "art-5-tit-3", "tit-1-cap-2-art-1"):
        assert csc._path_tipo(bad) is None, f"mixed path '{bad}' should be rejected"


def test_inv05_no_urn_is_exempt(tmp_path: Path) -> None:
    """Lei sem urn-lex (caso fallback OCR-ruim): §7.5 NÃO reporta —
    vigência genuinamente não tem âncora."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     vigente-em="2026-05-20">
  <dispositivo path="ocr-ruim" quality="raw">
    <versao>
      <texto>texto ilegível</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>
</lei>"""
    v = csc.check_file(_write(tmp_path, xml))
    assert not any(x.invariant == 5 for x in v)
