"""Tests for the marked document (offline, deterministic)."""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from leizilla import marcacao as M
from leizilla.hierarchy_sequence import (
    HierarchyReport,
    own_articles,
    read_hierarchy,
)
from leizilla.marcacao import Mark

ROOT = Path(__file__).resolve().parent.parent
XSD = ROOT / "docs" / "schemas" / "leizilla-doc-v0.xsd"
FIXTURES = sorted(
    (Path(__file__).parent / "fixtures" / "documento_marcado").glob("*.xml")
)


def _mk(kind: str, start: int, end: int, **attrs: str) -> Mark:
    return Mark(kind, start, end, dict(attrs))


# --- build / strip / parse round trips --------------------------------------------
TEXT = "Art. 1º Caput:\nI - um;\nII - dois.\n§ 1º Parágrafo.\nArt. 2º Fim."


def _simple_marks(text: str = TEXT) -> list[Mark]:
    a1, a2 = text.index("Art. 1"), text.index("Art. 2")
    i1, i2, p1 = text.index("I - um"), text.index("II -"), text.index("§ 1º")
    return [
        _mk("lei", 0, len(text), tipo="lei", numero="1"),
        Mark("art", a1, a2 - 1, {"n": "1"}, (a1, a1 + 7)),
        Mark("inc", i1, i2 - 1, {"n": "1"}, (i1, i1 + 3)),
        Mark("inc", i2, p1 - 1, {"n": "2"}, (i2, i2 + 4)),
        Mark("par", p1, a2 - 1, {"n": "1"}, (p1, p1 + 4)),
        Mark("art", a2, len(text), {"n": "2"}, (a2, a2 + 7)),
    ]


def test_build_strip_parse_roundtrip() -> None:
    marks = _simple_marks()
    xml = M.build(TEXT, marks, texto_id="x-1")
    assert M.strip(xml) == TEXT
    assert M.verify(xml, TEXT) == []
    assert M.parse(xml) == (TEXT, marks)
    attrs = M.root_attributes(xml)
    assert attrs["sha256-texto"] == M.sha256_text(TEXT)
    assert attrs["texto-id"] == "x-1"
    assert '<art n="1"><m>Art. 1º</m> Caput:' in xml


def test_marks_may_be_given_in_any_order() -> None:
    marks = _simple_marks()
    assert M.build(TEXT, list(reversed(marks))) == M.build(TEXT, marks)


def test_no_marks_is_just_the_text() -> None:
    xml = M.build("só texto", [])
    assert M.strip(xml) == "só texto"
    assert M.parse(xml) == ("só texto", [])
    assert M.verify(xml, "só texto") == []


# --- escaping ---------------------------------------------------------------------
def test_escaping_of_markup_controls_and_line_endings() -> None:
    text = "a < b & c > d\f\r\nlinha\x00\x01 fim\ufffe\x7f\x85\t\n]]>"
    marks = [_mk("lei", 0, len(text))]
    xml = M.build(text, marks)
    assert "\f" not in xml and "\r" not in xml and "\x00" not in xml
    assert '<c v="0C"/>' in xml and '<c v="0D"/>' in xml
    assert "&amp;" in xml and "&lt;" in xml and "&gt;" in xml
    # The parsed character data is exactly the text (\r\n kept, \f restored).
    assert M.strip(xml) == text
    assert M.parse(xml) == (text, marks)
    assert M.verify(xml, text) == []
    # A third-party XML parser also sees well-formed XML.
    ET.fromstring(xml.encode("utf-8"))


def test_marker_and_nested_text_with_special_characters() -> None:
    text = "Art. 1º A & B\f\n§ 1º x < y"
    a, p = 0, text.index("§")
    marks = [
        _mk("lei", 0, len(text)),
        Mark("art", a, len(text), {"n": "1"}, (0, 7)),
        Mark("par", p, len(text), {"n": "1"}, (p, p + 4)),
    ]
    xml = M.build(text, marks)
    assert M.parse(xml) == (text, marks)
    assert M.verify(xml, text) == []


def test_attribute_values_are_escaped() -> None:
    text = "x"
    marks = [_mk("lei", 0, 1, tipo='a"b<c&d\ne')]
    xml = M.build(text, marks)
    assert M.parse(xml)[1] == marks


# --- nota -------------------------------------------------------------------------
def test_nota_content_is_ours_and_stripped() -> None:
    text = "Art. 1º Texto."
    marks = [
        _mk("lei", 0, len(text)),
        _mk("art", 0, len(text), n="1"),
        Mark("nota", 8, 8, {"por": "leitor", "tipo": "aviso"}, None, "a<b & \f nota"),
    ]
    xml = M.build(text, marks)
    assert "<nota " in xml and "a&lt;b &amp;" in xml
    assert M.strip(xml) == text
    assert M.verify(xml, text) == []
    assert M.parse(xml)[1] == sorted(marks, key=lambda m: (m.start, -m.end))


def test_nota_may_not_have_width() -> None:
    with pytest.raises(M.MarcacaoError, match="nota"):
        M.build("abc", [Mark("nota", 0, 2, {}, None, "x")])


# --- grammar ----------------------------------------------------------------------
def test_level_grammar_errors_name_both_marks() -> None:
    text = "Art. 1º x\n§ 1º um\nArt. 2º dois"
    marks = [
        _mk("lei", 0, len(text)),
        _mk("art", 0, len(text), n="1"),
        _mk("par", 10, len(text), n="1"),
        _mk("art", 18, len(text), n="2"),
    ]
    with pytest.raises(M.GrammarError) as err:
        M.build(text, marks)
    assert "art" in str(err.value) and "par" in str(err.value)
    assert err.value.a is not None and err.value.a.kind == "par"
    assert err.value.b is not None and err.value.b.kind == "art"


@pytest.mark.parametrize(
    ("parent", "child", "ok"),
    [
        ("art", "par", True),
        ("art", "inc", True),
        ("par", "inc", True),
        ("inc", "ali", True),
        ("ali", "item", True),
        ("art", "alteracao", True),
        ("par", "alteracao", True),
        ("inc", "alteracao", True),
        ("alteracao", "art", True),
        ("par", "art", False),
        ("inc", "par", False),
        ("ali", "inc", False),
        ("item", "ali", False),
        ("lei", "par", False),
        ("lei", "alteracao", False),
        ("documento", "art", False),
        ("cap", "tit", False),
        ("tit", "cap", True),
        ("art", "nota", True),
        ("ali", "ruido", True),
        ("nota", "ruido", False),
    ],
)
def test_children_allowed(parent: str, child: str, ok: bool) -> None:
    assert (child in M.children_allowed(parent)) is ok


def test_device_outside_lei_is_rejected() -> None:
    with pytest.raises(M.GrammarError):
        M.build("Art. 1º x", [_mk("art", 0, 9, n="1")])


def test_marker_must_not_cross_a_child() -> None:
    text = "Art. 1º - texto"
    marks = [
        _mk("lei", 0, len(text)),
        Mark("art", 0, len(text), {"n": "1"}, (0, 7)),
        _mk("ruido", 4, 10),
    ]
    with pytest.raises(M.GrammarError, match="marcador"):
        M.build(text, marks)


def test_marks_outside_the_text_are_rejected() -> None:
    with pytest.raises(M.MarcacaoError, match="fora do texto"):
        M.build("abc", [_mk("lei", 0, 9)])
    with pytest.raises(M.MarcacaoError, match="desconhecido"):
        M.build("abc", [_mk("xx", 0, 1)])


# --- overlap ----------------------------------------------------------------------
def test_partial_overlap_names_the_two_marks() -> None:
    text = "Art. 1º aaaa bbbb Art. 2º cccc"
    marks = [
        _mk("lei", 0, len(text)),
        _mk("art", 0, 17, n="1"),
        _mk("alteracao", 10, 26),  # starts in art 1, ends inside art 2's span
        _mk("art", 18, len(text), n="2"),
    ]
    with pytest.raises(M.OverlapError) as err:
        M.build(text, marks)
    msg = str(err.value)
    assert "art n=1 [0:17]" in msg and "alteracao [10:26]" in msg
    assert err.value.a is not None and err.value.b is not None
    assert {err.value.a.kind, err.value.b.kind} == {"art", "alteracao"}


# --- zero-width and empty elements ------------------------------------------------
def test_zero_width_declared_absence_is_an_empty_element() -> None:
    text = "Art. 1º um.\nArt. 3º tres."
    marks = [
        _mk("lei", 0, len(text)),
        _mk("art", 0, 11, n="1"),
        _mk("art", 12, len(text), n="3"),
        _mk("art", 11, 11, n="2", estado="ausente"),
    ]
    xml = M.build(text, marks)
    assert '<art n="2" estado="ausente"/>' in xml
    assert M.strip(xml) == text
    assert M.verify(xml, text) == []
    assert M.parse(xml)[1] == sorted(marks, key=lambda m: (m.start, -m.end))
    rows = M.to_rows(xml)
    assert [r["path"] for r in rows] == ["art-1", "art-2", "art-3"]
    assert rows[1]["estado"] == "ausente" and rows[1]["start"] == rows[1]["end"]


def test_vetado_on_a_non_empty_element() -> None:
    text = "Art. 1º (vetado)."
    marks = [_mk("lei", 0, len(text)), _mk("art", 0, len(text), n="1", estado="vetado")]
    xml = M.build(text, marks)
    assert M.verify(xml, text) == []


def test_verify_flags_empty_element_without_estado() -> None:
    xml = M.build("x", [_mk("lei", 0, 1), _mk("art", 0, 0, n="1")])
    assert any("sem estado" in p for p in M.verify(xml, "x"))


# --- verify: edited documents -----------------------------------------------------
def test_one_changed_character_fails_verify_with_the_offset() -> None:
    xml = M.build(TEXT, _simple_marks())
    edited = xml.replace("Parágrafo", "Parágrafa")
    problems = M.verify(edited, TEXT)
    offset = TEXT.index("Parágrafo") + len("Parágraf")
    assert any(f"offset {offset}" in p for p in problems)
    assert any("Parágrafa" in p for p in problems)  # 40-character context
    assert any("sha256" in p for p in problems)


def test_verify_flags_a_dropped_character_and_a_changed_hash() -> None:
    xml = M.build(TEXT, _simple_marks())
    short = xml.replace("dois.", "dois")
    assert any("offset" in p for p in M.verify(short, TEXT))
    other = xml.replace(M.sha256_text(TEXT), "0" * 64)
    assert any("sha256-texto da raiz" in p for p in M.verify(other, TEXT))


def test_verify_reports_grammar_and_numbering_problems() -> None:
    xml = M.build(TEXT, _simple_marks())
    bad = xml.replace('<art n="2">', '<art n="dois">').replace(
        '<par n="1">', '<par n="1"><art n="9">x</art>'
    )
    # the hand edit also added text, so the strip differs; the grammar is reported too
    problems = M.verify(bad, TEXT)
    assert any('n="dois"' in p for p in problems)
    assert any("<art> não cabe em <par>" in p for p in problems)


def test_verify_handles_malformed_xml() -> None:
    assert M.verify("<documento>", "x")[0].startswith("XML mal formado")
    assert "DOCTYPE" in M.verify("<!DOCTYPE x [<!ENTITY a 'b'>]><documento/>", "")[0]
    assert "raiz" in M.verify("<lei/>", "")[0]


def test_two_markers_in_one_element_are_a_problem() -> None:
    xml = (
        '<documento versao="0" sha256-texto="'
        + M.sha256_text("Art. 1º - x")
        + '"><lei><art n="1"><m>Art.</m> <m>1º</m> - x</art></lei></documento>'
    )
    assert any("mais de um <m>" in p for p in M.verify(xml, "Art. 1º - x"))


# --- to_rows ----------------------------------------------------------------------
def test_to_rows_gives_the_dispositivos_view() -> None:
    xml = M.build(TEXT, _simple_marks())
    rows = M.to_rows(xml)
    assert [r["path"] for r in rows] == [
        "art-1",
        "art-1-inc-1",
        "art-1-inc-2",
        "art-1-par-1",
        "art-2",
    ]
    inc2 = rows[2]
    assert inc2["kind"] == "inc" and inc2["n"] == "2" and inc2["parent_path"] == "art-1"
    assert inc2["marker"] == "II -" and not inc2["quoted"]
    assert TEXT[inc2["text_start"] : inc2["text_end"]] == "dois."
    assert [r["ordem"] for r in rows] == [0, 1, 2, 3, 4]
    assert TEXT[rows[0]["text_start"] : rows[0]["text_end"]] == "Caput:"


# --- from_hierarchy ---------------------------------------------------------------
def _reader_rows(report: HierarchyReport) -> list[tuple[int, str]]:
    return sorted(
        (n["start"], n["path"] or "")
        for n in report["nodes"]
        if n["kind"] != "quoted_block" and n["status"] in ("own", "quoted")
    )


def _roundtrip(text: str) -> tuple[str, HierarchyReport, list[Mark]]:
    report = read_hierarchy(text)
    marks = M.from_hierarchy(text, report)
    xml = M.build(text, marks, texto_id="t")
    assert M.verify(xml, text) == []
    assert M.parse(xml) == (text, marks)
    rows = M.to_rows(xml)
    assert sorted((r["start"], r["path"]) for r in rows) == _reader_rows(report)
    own = [
        (int(r["n"]), r["sufixo"], r["start"])
        for r in rows
        if r["kind"] == "art" and not r["quoted"]
    ]
    assert own == [(a["number"], a["suffix"], a["start"]) for a in own_articles(report)]
    return xml, report, marks


CLEAN = (
    "Art. 1º Constitui crime:\n"
    "I - constranger alguém:\n"
    "a) com o fim de obter;\n"
    "b) para provocar;\n"
    "II - submeter alguém.\n"
    "Parágrafo único. Regra.\n"
    "Art. 2º Esta Lei entra em vigor.\n"
    "Palácio do Governo, 7 de abril de 1997."
)


def test_from_hierarchy_nests_all_levels_and_ends_the_lei_at_the_body() -> None:
    xml, report, marks = _roundtrip(CLEAN)
    lei = marks[0]
    assert lei.kind == "lei"
    assert CLEAN[lei.start : lei.end].endswith("entra em vigor.")
    assert "Palácio" not in CLEAN[lei.start : lei.end]
    assert '<ali n="a" lido-por="literal"><m>a)</m>' in xml
    assert '<inc n="1"' in xml and '<par n="unico"' in xml
    rows = M.to_rows(xml)
    assert "art-1-par-unico" in [r["path"] for r in rows]
    # Element spans drop trailing whitespace: the gap between devices is the parent's.
    assert "</art>\n<art" in xml


def test_from_hierarchy_with_a_quoted_block() -> None:
    text = (
        "Art. 1º O art. 15 da Lei nº 10 passa a vigorar com a seguinte redação:\n"
        '"Art. 15. Novo texto:\nI - um;\nII - dois.\n§ 3º Outro texto." (NR)\n'
        "Parágrafo único. Regra do hospedeiro.\n"
        "Art. 2º Esta Lei entra em vigor."
    )
    xml, report, marks = _roundtrip(text)
    assert "<alteracao>" in xml
    assert marks.count(next(m for m in marks if m.kind == "alteracao")) == 1
    rows = M.to_rows(xml)
    quoted = [r["path"] for r in rows if r["quoted"]]
    assert quoted == ["art-15", "art-15-inc-1", "art-15-inc-2", "art-15-par-3"]
    assert all(r["read_by"] is None for r in rows if r["quoted"])
    # The quoted devices sit inside the alteracao, the alteracao inside own art 1.
    alt = next(m for m in marks if m.kind == "alteracao")
    art1 = next(m for m in marks if m.kind == "art")
    assert art1.start < alt.start and alt.end <= art1.end
    assert [r["path"] for r in rows if not r["quoted"]] == [
        "art-1",
        "art-1-par-unico",
        "art-2",
    ]


def test_from_hierarchy_zero_width_marker_of_a_recovered_article() -> None:
    six = "".join(
        f"Art. {n}º Texto do artigo {n} com algum conteúdo.\n" for n in range(1, 7)
    )
    text = six + " Esta Lei entra em vigor na data de sua publicação."
    report = read_hierarchy(text)
    assert report["orphan_closings"]
    xml, _, marks = _roundtrip(text)
    arts = [m for m in marks if m.kind == "art"]
    assert len(arts) == 7
    last = arts[-1]
    assert last.marker is None  # no readable marker: no <m>
    assert last.attrs["n"] == "7" and last.attrs["corrigido"] == "true"
    assert last.attrs["lido-por"] == "gap"
    assert text[last.start : last.end].startswith("Esta Lei")
    assert '<art n="7" lido-por="gap" corrigido="true">Esta Lei' in xml
    assert "<m>" not in xml.split('<art n="7"')[1]


def test_from_hierarchy_marks_the_reading_evidence() -> None:
    text = "Art. 1º Um.\nArt. 2º Dois.\nArt. 3º Três.\n"
    _, _, marks = _roundtrip(text.replace("Art. 2º", "Art. Z"))
    assert [m.attrs["n"] for m in marks if m.kind == "art"] == ["1", "2", "3"]
    corrected = [m for m in marks if m.attrs.get("corrigido") == "true"]
    assert corrected and corrected[0].attrs["lido-por"] in ("gap", "confusion")


def test_text_without_own_articles_has_no_lei() -> None:
    text = "Sem artigos aqui.\nSó um aviso."
    report = read_hierarchy(text)
    assert M.from_hierarchy(text, report) == []
    xml = M.marcar(text)
    assert M.strip(xml) == text and "<lei" not in xml


def test_lei_attributes_come_from_the_caller() -> None:
    xml = M.marcar(CLEAN, texto_id="leizilla-raw-ro-x-lei-00001", tipo="lei", numero=1)
    assert '<lei tipo="lei" numero="1">' in xml


def test_overlapping_alteracao_is_dropped_with_its_devices() -> None:
    text = (
        "Art. 1º O art. 15 passa a vigorar com a seguinte redação:\n"
        '"Art. 15. Novo texto:\nI - um;\nII - dois." (NR)\n'
        "Art. 2º Esta Lei entra em vigor."
    )
    report = read_hierarchy(text)
    (block,) = report["quoted_blocks"]
    art2 = next(n for n in report["nodes"] if n["path"] == "art-2")
    # Force the conflict: the quoted block now ends after the next own article starts.
    node = report["nodes"][block["node"]]
    node["end"] = art2["start"] + 5
    ad = M.from_hierarchy_ex(text, report)
    assert len(ad.dropped) == 1
    dropped, other = ad.dropped[0]
    assert dropped.kind == "alteracao"
    assert other.kind in ("art", "lei")
    kinds = [m.kind for m in ad.marks]
    assert "alteracao" not in kinds
    # The quoted devices went with it: only own articles remain.
    assert [m.attrs["n"] for m in ad.marks if m.kind == "art"] == ["1", "2"]
    assert not [m for m in ad.marks if m.kind in ("inc", "par")]
    xml = M.build(text, ad.marks)
    assert M.verify(xml, text) == []


def test_marcar_never_alters_the_text_on_hostile_input() -> None:
    text = CLEAN.replace("\n", "\r\n").replace("I - ", "I - \f")
    xml = M.marcar(text)
    assert M.strip(xml) == text
    assert M.verify(xml, text) == []
    assert M.parse(xml)[0] == text


# --- schema -----------------------------------------------------------------------
def _xsd_children() -> dict[str, set[str]]:
    ns = {"xs": "http://www.w3.org/2001/XMLSchema"}
    tree = ET.parse(XSD)
    out: dict[str, set[str]] = {}
    for ct in tree.findall("xs:complexType", ns):
        name = ct.get("name", "")
        if not name.startswith("t-"):
            continue
        refs = {e.get("ref", "") for e in ct.iterfind(".//xs:element", ns)}
        out[name[2:]] = refs - {"c", "m"}
    return out


def test_xsd_grammar_matches_children_allowed() -> None:
    declared = _xsd_children()
    assert set(declared) == {
        "documento",
        "lei",
        "alteracao",
        *M.ORG,
        *M.DEVICES,
        *M.PARTS,
        "ruido",
        "ref",
    }
    for parent, kids in declared.items():
        assert kids == set(M.children_allowed(parent)), parent


def _xmllint(*files: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["xmllint", "--noout", "--schema", str(XSD), *map(str, files)],
        capture_output=True,
        text=True,
        check=False,
    )


needs_xmllint = pytest.mark.skipif(shutil.which("xmllint") is None, reason="no xmllint")


@needs_xmllint
def test_built_documents_validate_against_the_xsd(tmp_path: Path) -> None:
    quoted = (
        "Art. 1º O art. 15 da Lei nº 10 passa a vigorar com a seguinte redação:\n"
        '"Art. 15. Novo texto:\nI - um;\nII - dois.\n§ 3º Outro." (NR)\n'
        "Art. 2º Esta Lei entra em vigor."
    )
    files = []
    for i, text in enumerate([CLEAN, quoted, CLEAN.replace("\n", "\r\n") + "\f"]):
        path = tmp_path / f"d{i}.xml"
        path.write_bytes(M.marcar(text, texto_id=f"t{i}").encode("utf-8"))
        files.append(path)
    result = _xmllint(*files)
    assert result.returncode == 0, result.stderr


@needs_xmllint
def test_the_xsd_rejects_a_bad_number_and_a_bad_nesting(tmp_path: Path) -> None:
    good = M.marcar(CLEAN)
    bad_n = tmp_path / "n.xml"
    bad_n.write_bytes(good.replace('<art n="1"', '<art n="x1"').encode())
    bad_nest = tmp_path / "nest.xml"
    bad_nest.write_bytes(good.replace("<inc ", '<tit n="1"><inc ', 1).encode())
    assert _xmllint(bad_n).returncode != 0
    assert _xmllint(bad_nest).returncode != 0


def test_fixtures_hold_their_own_invariant() -> None:
    assert FIXTURES, "no fixtures"
    for path in FIXTURES:
        xml = path.read_bytes().decode("utf-8")
        assert M.verify(xml, M.strip(xml)) == [], path.name
        # The fixtures are what the reader produces today, byte for byte.
        text = M.strip(xml)
        attrs = M.root_attributes(xml)
        lei = re.search(r'<lei tipo="([^"]+)" numero="([^"]+)"', xml)
        tipo, numero = (lei.group(1), lei.group(2)) if lei else (None, None)
        assert (
            M.marcar(text, texto_id=attrs.get("texto-id"), tipo=tipo, numero=numero)
            == xml
            or "<nota" in xml
        ), path.name


@needs_xmllint
def test_fixtures_validate_against_the_xsd() -> None:
    result = _xmllint(*FIXTURES)
    assert result.returncode == 0, result.stderr
