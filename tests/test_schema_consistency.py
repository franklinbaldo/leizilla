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
# CLI exit codes (per docstring contract)
# ---------------------------------------------------------------------------


def test_cli_exit_0_on_clean_files(tmp_path: Path) -> None:
    """All clean fixtures → exit 0."""
    args = ["check_schema_consistency.py"] + [
        str(f) for f in sorted(FIXTURES.glob("*.xml"))
    ]
    assert csc.main(args) == 0


def test_cli_exit_1_on_consistency_violation(tmp_path: Path) -> None:
    """Consistency violation → exit 1, distinct from parse error."""
    xml = _wrap(
        """  <dispositivo path="blarg-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
    )
    f = _write(tmp_path, xml)
    assert csc.main(["check_schema_consistency.py", str(f)]) == 1


def test_cli_exit_2_on_xml_parse_error(tmp_path: Path) -> None:
    """Malformed XML → exit 2 (Codex P2)."""
    f = tmp_path / "broken.xml"
    f.write_text("<not-xml<", encoding="utf-8")
    assert csc.main(["check_schema_consistency.py", str(f)]) == 2


def test_cli_exit_2_on_directory_input(tmp_path: Path) -> None:
    """Codex P2: passing a directory (IsADirectoryError) → exit 2,
    not an uncaught traceback."""
    d = tmp_path / "subdir"
    d.mkdir()
    assert csc.main(["check_schema_consistency.py", str(d)]) == 2


def test_cli_exit_2_on_unreadable_file(tmp_path: Path) -> None:
    """Codex P2: permission denied (PermissionError) → exit 2."""
    import os

    f = tmp_path / "locked.xml"
    f.write_text(
        "<lei xmlns='https://leizilla.org/lei/0.1' schema-version='0.1' vigente-em='2026-05-20'/>"
    )
    os.chmod(f, 0o000)
    try:
        # Skip when running as root (chmod 000 doesn't block reads).
        if os.access(f, os.R_OK):
            pytest.skip("running as root; chmod 000 has no effect")
        assert csc.main(["check_schema_consistency.py", str(f)]) == 2
    finally:
        os.chmod(f, 0o644)


def test_cli_exit_2_on_missing_file(tmp_path: Path) -> None:
    assert csc.main(["check_schema_consistency.py", str(tmp_path / "nope.xml")]) == 2


def test_cli_exit_2_on_no_args() -> None:
    assert csc.main(["check_schema_consistency.py"]) == 2


def test_inv15_wrong_root_element_is_violation_not_parse_error(
    tmp_path: Path,
) -> None:
    """Codex P2: XML bem-formado com root != <lei> é §7.15 (consistency
    violation, exit 1), não parse error (exit 2)."""
    f = tmp_path / "wrong-root.xml"
    f.write_text('<?xml version="1.0"?>\n<foo/>', encoding="utf-8")
    violations = csc.check_file(f)
    assert any(v.invariant == 15 for v in violations)
    assert not any(v.invariant == 0 for v in violations)
    # CLI deve retornar 1 (violation), não 2 (parse error).
    assert csc.main(["check_schema_consistency.py", str(f)]) == 1


def test_cli_exit_2_takes_priority_over_violations(tmp_path: Path) -> None:
    """When some files have violations AND others have parse errors,
    exit 2 takes priority (broken input is more urgent than rule violations)."""
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<not-xml<", encoding="utf-8")
    violation_xml = _write(
        tmp_path,
        _wrap(
            """  <dispositivo path="unknown-token">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
        ),
    )
    assert (
        csc.main(["check_schema_consistency.py", str(bad_xml), str(violation_xml)]) == 2
    )


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


@pytest.mark.parametrize("diverge_value", ["true", "1", " true ", "  1  "])
def test_inv01_accepts_xs_boolean_true_variants(
    tmp_path: Path, diverge_value: str
) -> None:
    """Codex P2: xs:boolean aceita true|1|whitespace-collapsed.
    diverge="1" com <texto> filho deve passar (não acusar §7.1 falso positivo)."""
    xml = _wrap(
        f"""  <dispositivo path="art-1">
    <versao>
      <texto>canonico</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      <fonte ia-id="leizilla-raw-ro-diario-2000-01-01-p0001" diverge="{diverge_value}">
        <texto>divergente</texto>
      </fonte>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert not any(x.invariant == 1 for x in v), (
        f"diverge='{diverge_value}' com <texto> deveria passar; got: {[str(x) for x in v]}"
    )


@pytest.mark.parametrize("diverge_value", ["false", "0", " false "])
def test_inv01_accepts_xs_boolean_false_variants(
    tmp_path: Path, diverge_value: str
) -> None:
    """diverge="0" sem <texto> filho é válido (equivalente a false)."""
    xml = _wrap(
        f"""  <dispositivo path="art-1">
    <versao>
      <texto>canonico</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001" diverge="{diverge_value}"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert not any(x.invariant == 1 for x in v)


def test_inv01_diverge_one_without_texto_still_violation(tmp_path: Path) -> None:
    """diverge="1" (xs:boolean true) sem <texto> filho → §7.1."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>canonico</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      <fonte ia-id="leizilla-raw-ro-diario-2000-01-01-p0001" diverge="1"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 1 for x in v)


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


def test_inv04_normativo_must_compose_from_parent(tmp_path: Path) -> None:
    """Codex P1: child com path normativo aninhado em parent normativo
    deve compor do path do parent. art-2-par-1 dentro de art-1 é
    inconsistente — par-1 pertence a art-2, não a art-1."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>caput art-1</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <dispositivo path="art-2-par-1">
      <versao>
        <texto>par-1 — mas pendurado em art-1!</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      </versao>
    </dispositivo>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 4 and "compõe" in x.message for x in v), (
        f"esperava §7.4 composition violation; got: {[str(x) for x in v]}"
    )


def test_inv04_organizacional_must_compose_from_parent(tmp_path: Path) -> None:
    """tit-3-cap-1 aninhado em tit-1 é inconsistente."""
    xml = _wrap(
        """  <dispositivo path="tit-1">
    <versao>
      <texto>TÍTULO I</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <dispositivo path="tit-3-cap-1">
      <versao>
        <texto>cap-1 pendurado errado</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      </versao>
    </dispositivo>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 4 and "compõe" in x.message for x in v)


def test_inv04_normative_in_organizational_keeps_global(tmp_path: Path) -> None:
    """Normativo aninhado em organizacional NÃO compõe — path permanece global.
    art-5 dentro de tit-2-cap-1 é correto."""
    xml = _wrap(
        """  <dispositivo path="tit-2">
    <versao>
      <texto>TÍTULO II</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <dispositivo path="tit-2-cap-1">
      <versao>
        <texto>CAP I</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      </versao>
      <dispositivo path="art-5">
        <versao>
          <texto>art global, não compõe com tit-2-cap-1</texto>
          <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
        </versao>
      </dispositivo>
    </dispositivo>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert not any(x.invariant == 4 for x in v), (
        f"normativo em organizacional não deve disparar §7.4; got: {[str(x) for x in v]}"
    )


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


def test_inv08_rejects_non_raw_ia_id(tmp_path: Path) -> None:
    """Codex P2: <fonte> só aceita raw IA identifiers (§5.1).
    Parsed/dataset/bundle/fallback patterns devem ser rejeitados."""
    for bad in (
        "leizilla-ro-lei-01234-2003",  # parsed canônico
        "leizilla-dataset-ro-v1",  # dataset
        "leizilla-bundle-ro-casacivil-2026-W20",  # bundle ZIP
        "leizilla-ro-lei-fallback-casacivil-00042",  # parsed fallback
    ):
        xml = _wrap(
            f"""  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="{bad}"/>
    </versao>
  </dispositivo>"""
        )
        v = csc.check_file(_write(tmp_path, xml))
        assert any(x.invariant == 8 for x in v), (
            f"<fonte ia-id='{bad}'> deveria ser rejeitado (não é raw); "
            f"got: {[str(x) for x in v]}"
        )


def test_inv08_accepts_raw_variants(tmp_path: Path) -> None:
    """Raw IA identifiers válidos (§5.1) passam por §7.8."""
    for good in (
        "leizilla-raw-ro-casacivil-coddoc-00042",
        "leizilla-raw-federal-planalto-constituicao-1988",
        "leizilla-raw-ro-diario-2003-06-15-p0012",
        "leizilla-raw-sp-sao-paulo-camara-2020-001",
    ):
        xml = _wrap(
            f"""  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="{good}"/>
    </versao>
  </dispositivo>"""
        )
        v = csc.check_file(_write(tmp_path, xml))
        assert not any(x.invariant == 8 for x in v), (
            f"<fonte ia-id='{good}'> deveria ser aceito; got: {[str(x) for x in v]}"
        )


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
        # PR #9 follow-up: token "ocr-ruim" removido — qualidade de parse
        # não vive no XML (§4.7). Paths antigos como "ocr-ruim" devem
        # rejeitar (None) como qualquer token desconhecido.
        ("ocr-ruim", None),
        ("ocr-ruim-3", None),
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


def test_inherited_em_skips_invalid_dates(tmp_path: Path) -> None:
    """Kilo: _inherited_em deve pular ValueError e continuar buscando.
    Aqui o parent tem 1ª versão com em calendar-invalid + 2ª versão com
    em válido. Inheritance deveria retornar a segunda data, não None."""
    # Build a chain manually to isolate _inherited_em behavior.
    import xml.etree.ElementTree as ET

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="urn:lex:br;estado:rondonia;lei:2000-01-01;1234"
     vigente-em="2026-05-20">
  <dispositivo path="art-3">
    <versao em="2020-13-01">
      <texto>data invalida</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <versao em="2018-04-10" alterado-por="urn:lex:br;estado:rondonia;lei:2018-04-10;4321">
      <texto>data valida</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-04321"/>
    </versao>
  </dispositivo>
</lei>"""
    root = ET.fromstring(xml)
    art3 = root.find("{https://leizilla.org/lei/0.1}dispositivo")
    result = csc._inherited_em([art3])
    assert result is not None, (
        "deveria pular a 1ª versao com em invalido e retornar 2018-04-10"
    )
    assert result.isoformat() == "2018-04-10"


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


def test_inv04_normative_parent_with_organizational_child_rejected(
    tmp_path: Path,
) -> None:
    """Codex P2: organizational dentro de normative (e.g. capitulo dentro de
    artigo) é inversão hierárquica — §4.2 só permite org → norm."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>caput art-1</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <dispositivo path="cap-1">
      <versao>
        <texto>capitulo dentro de artigo — inversão</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
      </versao>
    </dispositivo>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 4 and "inversão" in x.message for x in v), (
        f"esperava §7.4 inversion violation; got: {[str(x) for x in v]}"
    )


def test_inv10_canonical_filename_without_urn(tmp_path: Path) -> None:
    """Codex P2: filename canônico (§5.3) sem urn-lex é identity drift —
    parsed item canônico requer URN. Fallback (§5.4) é exempto."""
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>"""
    xml_no_urn = f"""<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     vigente-em="2026-05-20">
{body}
</lei>"""
    f = _write_named(tmp_path, "leizilla-ro-lei-09999-1999", xml_no_urn)
    v = csc.check_file(f)
    assert any(x.invariant == 10 and "canônico" in x.message for x in v)

    # Fallback filename: exempto.
    f_fb = _write_named(tmp_path, "leizilla-ro-lei-fallback-casacivil-00042", xml_no_urn)
    v_fb = csc.check_file(f_fb)
    assert not any(x.invariant == 10 for x in v_fb), (
        f"fallback filename sem urn-lex deveria passar; got: {[str(x) for x in v_fb]}"
    )


def test_inv01_diverge_in_inicio_rejected(tmp_path: Path) -> None:
    """Codex P2: diverge é semanticamente válido apenas em <fonte> filha
    de <versao>. Em <inicio>, reportar violação independente do valor."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao em="2010-01-01">
      <inicio tipo="vacatio-legis">
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001" diverge="true">
          <texto>diverge num inicio — sem sentido</texto>
        </fonte>
      </inicio>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(
        x.invariant == 1 and "<inicio>" in x.message for x in v
    ), f"esperava §7.1 sobre diverge em <inicio>; got: {[str(x) for x in v]}"


def test_inv01_diverge_in_revogacao_rejected(tmp_path: Path) -> None:
    """Mesma regra que test_inv01_diverge_in_inicio_rejected, mas em
    <revogacao>."""
    xml = _wrap(
        """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
    <revogacao em="2020-01-01" tipo="expressa" por="urn:lex:br;estado:rondonia;lei:2020-01-01;9999">
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999" diverge="true">
        <texto>diverge numa revogacao</texto>
      </fonte>
    </revogacao>
  </dispositivo>"""
    )
    v = csc.check_file(_write(tmp_path, xml))
    assert any(
        x.invariant == 1 and "<revogacao>" in x.message for x in v
    ), f"esperava §7.1 sobre diverge em <revogacao>; got: {[str(x) for x in v]}"


def _write_named(tmp_path: Path, stem: str, content: str) -> Path:
    f = tmp_path / f"{stem}.xml"
    f.write_text(content, encoding="utf-8")
    return f


def test_inv10_filename_matches_urn_canonical(tmp_path: Path) -> None:
    """Codex P1: filename canônico (§5.3) deve bater tipo/ano/numero com urn-lex."""
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>"""
    f = _write_named(
        tmp_path,
        "leizilla-ro-lei-09999-1999",
        _wrap(body, urn_lex="urn:lex:br;estado:rondonia;lei:1999-06-15;9999"),
    )
    assert csc.check_file(f) == []


def test_inv10_filename_numero_mismatch(tmp_path: Path) -> None:
    """Filename 09999 mas URN 7777 → §7.10."""
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>"""
    f = _write_named(
        tmp_path,
        "leizilla-ro-lei-09999-1999",
        _wrap(body, urn_lex="urn:lex:br;estado:rondonia;lei:1999-06-15;7777"),
    )
    v = csc.check_file(f)
    assert any(x.invariant == 10 and "numero" in x.message for x in v)


def test_inv10_filename_ano_mismatch(tmp_path: Path) -> None:
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>"""
    f = _write_named(
        tmp_path,
        "leizilla-ro-lei-09999-1999",
        _wrap(body, urn_lex="urn:lex:br;estado:rondonia;lei:2020-06-15;9999"),
    )
    v = csc.check_file(f)
    assert any(x.invariant == 10 and "ano" in x.message for x in v)


def test_inv10_filename_tipo_mismatch(tmp_path: Path) -> None:
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>"""
    f = _write_named(
        tmp_path,
        "leizilla-ro-decreto-09999-1999",
        _wrap(body, urn_lex="urn:lex:br;estado:rondonia;lei:1999-06-15;9999"),
    )
    v = csc.check_file(f)
    assert any(x.invariant == 10 and "tipo" in x.message for x in v)


def test_inv10_filename_canonical_but_urn_lacks_numero(tmp_path: Path) -> None:
    """Canonical filename has numero, but URN omits it (CF style) → §7.10."""
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-federal-planalto-constituicao-1988"/>
    </versao>
  </dispositivo>"""
    f = _write_named(
        tmp_path,
        "leizilla-federal-constituicao-00000-1988",
        _wrap(body, urn_lex="urn:lex:br;federal;constituicao:1988-10-05"),
    )
    v = csc.check_file(f)
    assert any(x.invariant == 10 and "sem ;numero" in x.message for x in v)


def test_inv10_arbitrary_filename_skips_crosscheck(tmp_path: Path) -> None:
    """Fixtures (simple.xml etc.) têm filename arbitrário — cross-check
    deve ser pulado, só o regex check roda."""
    body = """  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>"""
    # arbitrary stem — não casa _RE_IA_PARSED
    f = _write_named(
        tmp_path,
        "simple",
        _wrap(body, urn_lex="urn:lex:br;estado:rondonia;lei:1999-06-15;7777"),
    )
    # urn-lex válido, filename não casa pattern → §7.10 silent.
    assert csc.check_file(f) == []


def test_inv10_empty_urn_fires_violation(tmp_path: Path) -> None:
    """Codex P2: urn-lex="" (present-but-empty) deve disparar §7.10,
    não ser confundido com urn-lex ausente."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="" vigente-em="2026-05-20">
  <dispositivo path="art-1">
    <versao>
      <texto>X</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>
</lei>"""
    v = csc.check_file(_write(tmp_path, xml))
    assert any(x.invariant == 10 for x in v), (
        f"empty urn-lex deveria disparar §7.10; got: {[str(x) for x in v]}"
    )


def test_inv05_no_urn_is_exempt(tmp_path: Path) -> None:
    """Lei sem urn-lex (caso fallback, data não-extraível): §7.5 NÃO
    reporta — vigência genuinamente não tem âncora."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     vigente-em="2026-05-20">
  <dispositivo path="art-1">
    <versao>
      <texto>texto sem ancora de vigencia</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/>
    </versao>
  </dispositivo>
</lei>"""
    v = csc.check_file(_write(tmp_path, xml))
    assert not any(x.invariant == 5 for x in v)
