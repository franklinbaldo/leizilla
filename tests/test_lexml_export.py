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


def _xslt(fixture: Path, output_dir: Path | None = None) -> str:
    """Apply XSLT to fixture, return LexML XML do principal como string.

    `output_dir` (opcional): se a lei tem `<dispositivo path="anexo-N">`,
    o XSLT escreve `{output_dir}/anexo-N.lexml.xml` (via exsl:document).
    Default: cwd. Caller que precisa coletar anexos deve passar tmp_path.
    """
    args = ["xsltproc"]
    if output_dir is not None:
        args.extend(["--param", "output-dir", f"'{output_dir}'"])
    args.extend([str(XSLT), str(fixture)])
    result = subprocess.run(args, capture_output=True, text=True, check=True)
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
def test_xslt_produces_valid_lexml(fixture: Path, tmp_path: Path) -> None:
    """Every Leizilla fixture, after XSLT, must validate against the
    official LexML XSD (lexml-br-rigido.xsd, bundled in tests/fixtures/lexml/).

    tmp_path isola output-dir — fixtures com anexos geram arquivos
    separados que não devem poluir o cwd nem o repo."""
    lexml_xml = _xslt(fixture, output_dir=tmp_path)
    code, stderr = _validate_lexml(lexml_xml)
    assert code == 0, f"LexML validation failed for {fixture.name}:\n{stderr}"


def test_xslt_output_is_well_formed_xml(tmp_path: Path) -> None:
    """Independent of XSD: every output must at least be well-formed XML.
    Catches XSLT regressions that produce malformed output (which would
    fail the LexML validation upstream)."""
    for fixture in FIXTURES.glob("*.xml"):
        lexml_xml = _xslt(fixture, output_dir=tmp_path)
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


def test_xslt_emits_lexml_root_element(tmp_path: Path) -> None:
    """Smoke: every output has <LexML> as root in the official namespace.
    Tests the basic shape of the conversion without parsing structure."""
    for fixture in FIXTURES.glob("*.xml"):
        lexml_xml = _xslt(fixture, output_dir=tmp_path)
        assert 'xmlns="http://www.lexml.gov.br/1.0"' in lexml_xml, (
            f"{fixture.name} output missing LexML namespace"
        )
        assert "<LexML" in lexml_xml, f"{fixture.name} output missing <LexML> root"


def test_xslt_emits_identificacao_urn(tmp_path: Path) -> None:
    """Smoke: every output has <Identificacao URN="...">. URN content
    correctness is the responsibility of the Leizilla checker (§7.10);
    here we only confirm the LexML envelope wires it through."""
    for fixture in FIXTURES.glob("*.xml"):
        lexml_xml = _xslt(fixture, output_dir=tmp_path)
        assert "<Identificacao" in lexml_xml
        assert "URN=" in lexml_xml


def test_xslt_emits_anexo_as_separate_document(tmp_path: Path) -> None:
    """Anexos no Leizilla XML (path='anexo-N') viram:
    (a) <ReferenciaAnexo AlvoURN='{lei.urn}!anexo-N'/> no documento
        principal, dentro de <Norma>/<Anexos>.
    (b) Arquivo LexML separado `{output_dir}/anexo-N.lexml.xml` com
        <Anexo><DocumentoGenerico><PartePrincipal><p>{texto}</p>.

    Modelo LexML: anexos são documentos linkados via URN, não estruturas
    inline. Documentado em SCHEMA.md §6 e no XSLT header.
    """
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
      <texto>Tabela do Anexo 1 — conteúdo aqui.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01234"/>
    </versao>
  </dispositivo>
</lei>
""",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lexml_main = _xslt(fixture, output_dir=out_dir)

    # (a) Principal contém ReferenciaAnexo, NÃO contém o texto do anexo.
    assert "Corpo da lei." in lexml_main
    assert "<ReferenciaAnexo" in lexml_main, (
        f"Principal deveria conter <ReferenciaAnexo>:\n{lexml_main}"
    )
    assert (
        'AlvoURN="urn:lex:br;estado:rondonia;lei:2000-01-01;1234!anexo-1"' in lexml_main
    ), f"AlvoURN incorreta:\n{lexml_main}"
    assert "Tabela do Anexo" not in lexml_main, (
        f"texto do anexo não deveria vazar pro principal:\n{lexml_main}"
    )
    # Principal valida.
    code, stderr = _validate_lexml(lexml_main)
    assert code == 0, f"Principal inválido:\n{stderr}"

    # (b) Arquivo separado existe, tem o texto, URN bate, valida.
    anexo_file = out_dir / "anexo-1.lexml.xml"
    assert anexo_file.exists(), f"arquivo do anexo não gerado em {out_dir}"
    anexo_content = anexo_file.read_text(encoding="utf-8")
    assert "Tabela do Anexo 1" in anexo_content
    assert (
        'URN="urn:lex:br;estado:rondonia;lei:2000-01-01;1234!anexo-1"' in anexo_content
    )
    assert "<Anexo>" in anexo_content
    assert "<DocumentoGenerico" in anexo_content
    code, stderr = _validate_lexml(anexo_content)
    assert code == 0, f"Anexo inválido:\n{stderr}"


def test_xslt_emits_multiple_anexos_as_separate_files(tmp_path: Path) -> None:
    """Lei com 2 anexos → 2 arquivos separados + 2 <ReferenciaAnexo>."""
    fixture = tmp_path / "with-2-anexos.xml"
    fixture.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="urn:lex:br;estado:rondonia;lei:2010-01-01;5555"
     vigente-em="2026-05-20">
  <dispositivo path="art-1">
    <versao>
      <texto>Corpo.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-05555"/>
    </versao>
  </dispositivo>
  <dispositivo path="anexo-1">
    <versao>
      <texto>Primeiro anexo.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-05555"/>
    </versao>
  </dispositivo>
  <dispositivo path="anexo-2">
    <versao>
      <texto>Segundo anexo.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-05555"/>
    </versao>
  </dispositivo>
</lei>
""",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lexml_main = _xslt(fixture, output_dir=out_dir)

    # 2 ReferenciaAnexo no principal.
    assert lexml_main.count("<ReferenciaAnexo") == 2
    # 2 arquivos separados, ambos validam.
    for n, txt in ((1, "Primeiro anexo."), (2, "Segundo anexo.")):
        f = out_dir / f"anexo-{n}.lexml.xml"
        assert f.exists(), f"anexo-{n}.lexml.xml não gerado"
        content = f.read_text(encoding="utf-8")
        assert txt in content
        code, stderr = _validate_lexml(content)
        assert code == 0, f"anexo-{n} inválido:\n{stderr}"
