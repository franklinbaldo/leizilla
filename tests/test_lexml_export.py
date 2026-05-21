"""Tests for scripts/leizilla-to-lexml.xsl.

For each Leizilla XML fixture in tests/fixtures/leizilla_xml/, applies
the XSLT and validates the output against the official LexML brasileiro
XSD bundled in tests/fixtures/lexml/.

CI gate (SCHEMA.md §6): LexML is reduced representation generated on
demand for gov interop. Round-trip (LexML → Leizilla XML) is NOT a
goal. Known losses documented inline in the XSLT and in SCHEMA.md §6.2.

Requires `xsltproc` and `xmllint` (libxml2-utils). The CI workflow
installs both via apt.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "leizilla_xml"
XSLT = REPO_ROOT / "scripts" / "leizilla-to-lexml.xsl"
LEXML_XSD = REPO_ROOT / "tests" / "fixtures" / "lexml" / "lexml-br-rigido.xsd"


pytestmark = pytest.mark.skipif(
    shutil.which("xsltproc") is None or shutil.which("xmllint") is None,
    reason="xsltproc and xmllint required (apt install libxml2-utils xsltproc)",
)


def _xslt(fixture: Path) -> str:
    """Apply XSLT to fixture, return LexML XML as string."""
    result = subprocess.run(
        ["xsltproc", str(XSLT), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _validate_lexml(xml_str: str) -> tuple[int, str]:
    """Validate XML string against LexML XSD. Returns (exit_code, stderr)."""
    result = subprocess.run(
        ["xmllint", "--noout", "--schema", str(LEXML_XSD), "-"],
        input=xml_str,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.xml")))
def test_xslt_produces_valid_lexml(fixture: Path) -> None:
    """Every Leizilla fixture, after XSLT, must validate against the
    official LexML XSD (lexml-br-rigido.xsd, bundled in tests/fixtures/lexml/)."""
    lexml_xml = _xslt(fixture)
    code, stderr = _validate_lexml(lexml_xml)
    assert code == 0, f"LexML validation failed for {fixture.name}:\n{stderr}"


def test_xslt_output_is_well_formed_xml() -> None:
    """Independent of XSD: every output must at least be well-formed XML.
    Catches XSLT regressions that produce malformed output (which would
    fail the LexML validation upstream)."""
    for fixture in FIXTURES.glob("*.xml"):
        lexml_xml = _xslt(fixture)
        # xmllint with --noout but no --schema = just well-formedness check.
        result = subprocess.run(
            ["xmllint", "--noout", "-"],
            input=lexml_xml,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"XSLT produced malformed XML for {fixture.name}:\n{result.stderr}"
        )


def test_xslt_emits_lexml_root_element() -> None:
    """Smoke: every output has <LexML> as root in the official namespace.
    Tests the basic shape of the conversion without parsing structure."""
    for fixture in FIXTURES.glob("*.xml"):
        lexml_xml = _xslt(fixture)
        assert 'xmlns="http://www.lexml.gov.br/1.0"' in lexml_xml, (
            f"{fixture.name} output missing LexML namespace"
        )
        assert "<LexML" in lexml_xml, f"{fixture.name} output missing <LexML> root"


def test_xslt_emits_identificacao_urn() -> None:
    """Smoke: every output has <Identificacao URN="...">. URN content
    correctness is the responsibility of the Leizilla checker (§7.10);
    here we only confirm the LexML envelope wires it through."""
    for fixture in FIXTURES.glob("*.xml"):
        lexml_xml = _xslt(fixture)
        assert "<Identificacao" in lexml_xml
        assert "URN=" in lexml_xml


def test_xslt_drops_ocr_ruim_dispositivos(tmp_path: Path) -> None:
    """XSLT pula <dispositivo path="ocr-ruim*"> — LexML não tem
    equivalente. Documentado em SCHEMA.md §6.2 + XSLT header.

    Constrói fixture inline com 1 dispositivo válido + 1 ocr-ruim e
    confirma que o LexML resultante contém apenas o primeiro.
    """
    fixture = tmp_path / "with-ocr-ruim-inline.xml"
    fixture.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="urn:lex:br;estado:rondonia;lei:1990-03-20;500"
     vigente-em="2026-05-20">
  <dispositivo path="art-1">
    <versao>
      <texto>Texto parseado normal.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00500"/>
    </versao>
  </dispositivo>
  <dispositivo path="ocr-ruim-1">
    <versao>
      <texto>Tre|ho i||egí|el n0 OCR</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00500"/>
    </versao>
  </dispositivo>
</lei>
""",
        encoding="utf-8",
    )
    lexml_xml = _xslt(fixture)

    # XSLT deve produzir LexML com art-1 mas SEM ocr-ruim.
    assert "Texto parseado normal." in lexml_xml, (
        "dispositivo regular deveria estar no LexML"
    )
    assert "Tre|ho" not in lexml_xml, (
        f"ocr-ruim NÃO deveria vazar pro LexML:\n{lexml_xml}"
    )
    assert "ocr-ruim" not in lexml_xml, (
        f"id/path ocr-ruim NÃO deveria aparecer no LexML:\n{lexml_xml}"
    )

    # Sanity: validação contra XSD ainda passa.
    code, stderr = _validate_lexml(lexml_xml)
    assert code == 0, f"LexML inválido:\n{stderr}"


def test_xslt_drops_anexos(tmp_path: Path) -> None:
    """Anexos no Leizilla XML (path="anexo-N") não viram <Articulacao>
    em LexML — LexML modela anexos via <ReferenciaAnexo> em documentos
    separados. Documentado em SCHEMA.md §6.2."""
    fixture = tmp_path / "with-anexo-inline.xml"
    fixture.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="urn:lex:br;estado:rondonia;lei:2000-01-01;1234"
     vigente-em="2026-05-20">
  <dispositivo path="art-1">
    <versao>
      <texto>Corpo da lei.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01234"/>
    </versao>
  </dispositivo>
  <dispositivo path="anexo-1">
    <versao>
      <texto>Tabela ANEXA — não deveria aparecer no LexML export.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01234"/>
    </versao>
  </dispositivo>
</lei>
""",
        encoding="utf-8",
    )
    lexml_xml = _xslt(fixture)
    assert "Corpo da lei." in lexml_xml
    assert "Tabela ANEXA" not in lexml_xml, (
        f"anexo NÃO deveria vazar pro LexML:\n{lexml_xml}"
    )
    code, _ = _validate_lexml(lexml_xml)
    assert code == 0
