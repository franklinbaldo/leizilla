"""Testes do livro-razão de completude (leizilla.completeness) e da leitura
completa das listas anuais (discovery.parse_casacivil_year_catalog).

Tudo offline: as páginas são fixtures pequenas modeladas nas listas reais do
Consulegis, e todo acesso ao IA passa pelos wrappers públicos de publisher.py,
aqui mockados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from leizilla import completeness as comp
from leizilla import discovery
from leizilla.cli import app
from leizilla.publisher import IndexFetchError

BASE = "https://ditel.casacivil.ro.gov.br/COTEL/Livros/"
_INDEX_HEADER = "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"


def _entry(
    i: int, coddoc: int, title: str, files: list[str], ementa: str = "Ementa."
) -> str:
    downloads = "".join(
        f'<span class="style12">Download:</span>&nbsp;'
        f'<a id="ContentPlaceHolder1_DataList1_HyperLink2_{i}" href="Files/{href}" '
        f'style="color: #006600">{href}</a><br />'
        for href in files
    )
    return f"""<tr><td><div><br />
<a id="ContentPlaceHolder1_DataList1_hlnk0_{i}" href="../Livros/detalhes.aspx?coddoc={coddoc}" style="color: #0000FF; font-size: 14px">{title}</a>
<br />{downloads}
<span id="ContentPlaceHolder1_DataList1_ementadoc1_{i}" style="text-align: justify;">{ementa}</span>
</span></span><br />
<span class="style11">cód.</span>
<span id="ContentPlaceHolder1_DataList1_coddocLabel1_{i}" style="color: #CC0000">{coddoc}</span>
</div></td></tr>"""


def _page(heading: str, ano: int, entries: list[str], declared: Optional[int]) -> str:
    label = f"{declared} resultado(s) encontrado(s)</BR>" if declared else ""
    empty = (
        ""
        if entries
        else '<tr><td><span id="ContentPlaceHolder1_DataList1_lblEmptyData">'
        "Não foi encontrado nenhum registro.</span></td></tr>"
    )
    return f"""<html><body><h1><strong>{heading} de
<span id="ContentPlaceHolder1_lblAno">{ano}</span></strong></h1>
<span id="ContentPlaceHolder1_Label1" style="font-weight: 700">{label}</span>
<table id="ContentPlaceHolder1_DataList1">{"".join(entries)}{empty}</table>
<a href="faleconosco.aspx">Fale conosco</a><span id="lblAno"></span></body></html>"""


LEIS_2026 = _page(
    "Leis Ordinárias",
    2026,
    [
        _entry(
            0,
            45727,
            "Lei n. 6572, de 12-11-2026",
            ["L6572.pdf"],
            "Autoriza o Poder Executivo a alienar\nimóvel &amp; dá outras providências.",
        ),
        _entry(1, 45001, "Lei n.  6.324, de 02-03-2026", ["L6324%20-%20COMPILADA.pdf"]),
        _entry(2, 44356, "Lei n. 6360, de 13-04-2026", ["L6360.pdf"]),
        _entry(3, 44357, "Lei n. 6360, de 13-04-2026", ["L6360.pdf"]),
        _entry(4, 44000, "Lei n. 6300, de 31-02-2026", []),
        _entry(5, 44001, "Sem número", ["avulso.pdf"]),
    ],
    6,
)
LEIS_2025 = _page(
    "Leis Ordinárias",
    2025,
    [
        _entry(0, 43000, "Lei n. 6200, de 10-12-2025", ["L6200.pdf"]),
        _entry(1, 43001, "Lei n. 6199, de 09-12-2025", ["L6199%20-%20REVOGADO.pdf"]),
    ],
    2,
)
DECLEI_1982 = _page(
    "Decretos leis",
    1982,
    [
        _entry(
            0,
            41965,
            "Decreto Lei n. 9A, de 09-03-1982",
            ["DL9A%20-%20COMPILADO_merged.pdf"],
            "Estatuto dos Policiais Militares.",
        ),
        _entry(1, 9, "Decreto Lei n. 9, de 25-01-1982", ["DL9.pdf"]),
        _entry(2, 10, "Decreto Lei n. 10, de 09-03-1982", ["DL10.pdf"]),
    ],
    3,
)
DECLEI_1983_EMPTY = _page("Decretos leis", 1983, [], None)


# ---------------------------------------------------------------------------
# Leitura completa da lista anual
# ---------------------------------------------------------------------------


class TestYearCatalog:
    def test_one_record_per_listed_norm_with_date_ementa_and_coddoc(self) -> None:
        records = discovery.parse_casacivil_year_catalog(
            LEIS_2026, BASE + "listleiord.aspx?ano=2026", "lei"
        )
        assert [r["numero"] for r in records] == [6572, 6324, 6360, 6360, 6300]
        first = records[0]
        assert first == {
            "tipo": "lei",
            "numero": 6572,
            "sufixo": "",
            "titulo": "Lei n. 6572, de 12-11-2026",
            "data": "2026-11-12",
            "ano": 2026,
            "ementa": "Autoriza o Poder Executivo a alienar imóvel & dá outras providências.",
            "coddoc": 45727,
            "arquivos": [
                {
                    "nome": "L6572.pdf",
                    "url": BASE + "Files/L6572.pdf",
                    "rendicao": "original",
                }
            ],
        }

    def test_rendition_comes_from_the_file_suffix(self) -> None:
        records = discovery.parse_casacivil_year_catalog(LEIS_2026, BASE + "x", "lei")
        assert records[1]["arquivos"] == [
            {
                "nome": "L6324 - COMPILADA.pdf",
                "url": BASE + "Files/L6324%20-%20COMPILADA.pdf",
                "rendicao": "compilada",
            }
        ]

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("L6572.pdf", "original"),
            ("L009.pdf", "original"),
            ("D32002_.pdf", "original"),
            ("L6500 - COMPILADA.pdf", "compilada"),
            ("DL9A - COMPILADO_merged.pdf", "compilada"),
            ("DL 9 - COMPILADO.pdf", "compilada"),
            ("LC1300 - REVOGADA.pdf", "revogado"),
            ("D31000 - REVOGADO.pdf", "revogado"),
            ("DEC31990- RETIFICADO.pdf", "retificado"),
            ("DEC31991 - Retificado.pdf", "retificado"),
            ("D31884%20-%20SEM%20EFEITO.pdf", "outra"),
        ],
    )
    def test_rendition_labels(self, name: str, expected: str) -> None:
        assert discovery.year_index_rendicao(name) == expected

    def test_letter_suffix_is_kept_apart_from_the_number(self) -> None:
        records = discovery.parse_casacivil_year_catalog(
            DECLEI_1982, BASE + "x", "decreto-lei"
        )
        assert [(r["numero"], r["sufixo"]) for r in records] == [
            (9, "A"),
            (9, ""),
            (10, ""),
        ]
        assert records[0]["arquivos"][0]["nome"] == "DL9A - COMPILADO_merged.pdf"

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Lei n. 6572, de 12-11-2026", (6572, "")),
            ("Lei n.  6356, de 09-04-2026", (6356, "")),
            ("Decreto n. 31.999, de 01-09-2026", (31999, "")),
            ("Decreto nº 1803, de 03-01-1984", (1803, "")),
            ("Decreto n.1879, de 10-02-1984", (1879, "")),
            ("Decreto n . 4758, de 14-08-1990", (4758, "")),
            ("Decreto n. 4591-C, de 03-04-1990", (4591, "C")),
            ("Decreto Lei n. 9A, de 09-03-1982", (9, "A")),
            ("L946, de 20-12-2000", (946, "")),
            ("D2797, de 22-11-1985", (2797, "")),
        ],
    )
    def test_title_variants_seen_on_the_real_lists(
        self, title: str, expected: tuple[int, str]
    ) -> None:
        page = _page("Lista", 2000, [_entry(0, 1, title, ["x.pdf"])], 1)
        (record,) = discovery.parse_casacivil_year_catalog(page, BASE + "x", "lei")
        assert (record["numero"], record["sufixo"]) == expected
        assert discovery.casacivil_year_unreadable(page) == []

    def test_entry_without_a_number_is_reported_not_dropped_silently(self) -> None:
        assert discovery.casacivil_year_unreadable(LEIS_2026) == [
            {"coddoc": 44001, "titulo": "Sem número"}
        ]

    def test_unreadable_date_is_none_and_entry_without_file_is_kept(self) -> None:
        records = discovery.parse_casacivil_year_catalog(LEIS_2026, BASE + "x", "lei")
        no_file = records[-1]
        assert no_file["numero"] == 6300
        assert no_file["data"] is None  # 31-02 não existe
        assert no_file["ano"] == 2026  # o ano da lista continua valendo
        assert no_file["arquivos"] == []

    def test_page_info_reads_year_and_declared_total(self) -> None:
        assert discovery.year_index_page_info(LEIS_2026) == {
            "ano": 2026,
            "declarados": 6,
        }

    def test_empty_year_is_zero_only_with_the_explicit_marker(self) -> None:
        assert discovery.year_index_page_info(DECLEI_1983_EMPTY) == {
            "ano": 1983,
            "declarados": 0,
        }
        assert discovery.year_index_page_info("<html>Server Error</html>") == {
            "ano": None,
            "declarados": None,
        }

    def test_discovery_view_still_collapses_the_suffix_into_the_number(self) -> None:
        resources = discovery.parse_casacivil_year_index(
            DECLEI_1982, BASE + "x", "decreto-lei", "ro", "casacivil"
        )
        assert [r["chave"] for r in resources] == [
            "decreto-lei-00009",
            "decreto-lei-00009",
            "decreto-lei-00010",
        ]
        assert set(resources[0]) == {
            "url",
            "ente",
            "fonte",
            "tipo_documento",
            "chave",
            "status",
            "wayback_snapshot",
        }


# ---------------------------------------------------------------------------
# Catálogo: busca, snapshot e anos desconhecidos
# ---------------------------------------------------------------------------

_MANIFEST = {
    "ente": "ro",
    "fontes": {
        "casacivil": {
            "discovery": [
                {
                    "strategy": "casacivil-year-index",
                    "tipo": "lei",
                    "url_template": BASE + "listleiord.aspx?ano={ano}",
                    "start_year": 2024,
                    "end_year": 2026,
                },
                {
                    "strategy": "casacivil-year-index",
                    "tipo": "decreto-lei",
                    "url_template": BASE + "listdeclei.aspx?ano={ano}",
                    "start_year": 1982,
                    "end_year": 1983,
                },
                {"strategy": "sequential", "templates": []},
            ]
        },
        "assembleia": {"discovery": [{"strategy": "playwright-crawler"}]},
    },
}

_PAGES = {
    BASE + "listleiord.aspx?ano=2026": LEIS_2026,
    BASE + "listleiord.aspx?ano=2025": LEIS_2025,
    BASE + "listleiord.aspx?ano=2024": None,  # falha de rede
    BASE + "listdeclei.aspx?ano=1982": DECLEI_1982,
    BASE + "listdeclei.aspx?ano=1983": DECLEI_1983_EMPTY,
}


@pytest.fixture
def manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "load_manifest", lambda ente: _MANIFEST)


@pytest.fixture
def fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve ``_PAGES`` pelo ``_fetch`` da estratégia e registra as URLs pedidas."""
    seen: list[str] = []

    def fake_fetch(self: Any, url: str) -> Optional[str]:
        seen.append(url)
        return _PAGES.get(url)

    monkeypatch.setattr(discovery.CasacivilYearIndexDiscovery, "_fetch", fake_fetch)
    return seen


def _status(catalog: comp.Catalog) -> dict[tuple[str, int], str]:
    return {(p.tipo, p.ano): p.status for p in catalog.pages}


class TestFetchCatalog:
    def test_failed_year_is_unknown_not_empty(
        self, manifest: None, fetched: list[str]
    ) -> None:
        catalog = comp.fetch_catalog("ro", "casacivil", current_year=2026)
        assert _status(catalog) == {
            ("lei", 2024): "failed",
            ("lei", 2025): "ok",
            ("lei", 2026): "ok",
            ("decreto-lei", 1982): "ok",
            ("decreto-lei", 1983): "ok",
        }
        assert catalog.live_requests == 5
        assert catalog.complete("decreto-lei") is True
        assert catalog.complete("lei") is False
        empty = next(p for p in catalog.pages if p.ano == 1983)
        assert empty.declarados == 0 and empty.records == []

    def test_newest_year_first(self, manifest: None, fetched: list[str]) -> None:
        comp.fetch_catalog("ro", "casacivil", current_year=2026)
        assert [u[-4:] for u in fetched] == ["2026", "2025", "2024", "1983", "1982"]

    def test_wrong_year_or_error_page_is_failed(
        self, manifest: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            discovery.CasacivilYearIndexDiscovery,
            "_fetch",
            lambda self, url: LEIS_2025 if "listleiord" in url else "<html>erro</html>",
        )
        catalog = comp.fetch_catalog("ro", "casacivil", current_year=2026)
        assert _status(catalog) == {
            ("lei", 2024): "failed",
            ("lei", 2025): "ok",
            ("lei", 2026): "failed",
            ("decreto-lei", 1982): "failed",
            ("decreto-lei", 1983): "failed",
        }

    def test_snapshot_roundtrip_refetches_only_recent_years(
        self, manifest: None, fetched: list[str], tmp_path: Path
    ) -> None:
        first = comp.fetch_catalog("ro", "casacivil", current_year=2026)
        path = tmp_path / "catalog.json.gz"
        assert comp.write_catalog_snapshot(first, path) == 4  # o ano que falhou não

        fetched.clear()
        snapshot = comp.load_catalog_snapshot(path)
        second = comp.fetch_catalog(
            "ro", "casacivil", snapshot=snapshot, refresh_years=1, current_year=2026
        )
        # 2026 é recente (rebuscado); 2024 não estava no snapshot (tenta de novo).
        assert sorted(u[-4:] for u in fetched) == ["2024", "2026"]
        assert _status(second) == {
            ("lei", 2024): "failed",
            ("lei", 2025): "cached",
            ("lei", 2026): "ok",
            ("decreto-lei", 1982): "cached",
            ("decreto-lei", 1983): "cached",
        }
        cached = next(p for p in second.pages if p.ano == 1982)
        assert [r["sufixo"] for r in cached.records] == ["A", "", ""]

    def test_snapshot_bytes_are_deterministic(
        self, manifest: None, fetched: list[str], tmp_path: Path
    ) -> None:
        catalog = comp.fetch_catalog("ro", "casacivil", current_year=2026)
        a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
        comp.write_catalog_snapshot(catalog, a)
        comp.write_catalog_snapshot(catalog, b)
        assert a.read_bytes() == b.read_bytes()

    def test_failed_refresh_falls_back_to_the_snapshot_as_stale(
        self, manifest: None, fetched: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot = {
            (p.tipo, p.ano): p
            for p in comp.fetch_catalog("ro", "casacivil", current_year=2026).pages
            if p.known
        }
        monkeypatch.setattr(
            discovery.CasacivilYearIndexDiscovery, "_fetch", lambda self, url: None
        )
        catalog = comp.fetch_catalog(
            "ro", "casacivil", snapshot=snapshot, refresh_years=1, current_year=2026
        )
        assert _status(catalog)[("lei", 2026)] == "stale"
        assert catalog.complete("decreto-lei") is True
        stale = next(p for p in catalog.pages if p.status == "stale")
        assert len(stale.records) == 5

    def test_max_fetch_and_fetch_years_leave_the_rest_pending(
        self, manifest: None, fetched: list[str]
    ) -> None:
        capped = comp.fetch_catalog("ro", "casacivil", max_fetch=2, current_year=2026)
        assert capped.live_requests == 2
        assert _status(capped)[("lei", 2024)] == "pending"
        assert _status(capped)[("decreto-lei", 1982)] == "pending"

        fetched.clear()
        sliced = comp.fetch_catalog(
            "ro", "casacivil", fetch_years={1982}, current_year=2026
        )
        assert [u[-4:] for u in fetched] == ["1982"]
        assert _status(sliced)[("lei", 2026)] == "pending"

    def test_robots_block_stops_fetching(
        self, manifest: None, fetched: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            discovery.CasacivilYearIndexDiscovery, "_allowed", lambda self, url: False
        )
        catalog = comp.fetch_catalog("ro", "casacivil", current_year=2026)
        assert fetched == []
        assert set(_status(catalog).values()) == {"failed"}

    def test_default_offline_guard_makes_every_year_unknown(
        self, manifest: None
    ) -> None:
        """Sem mock próprio, o conftest mantém a estratégia fora da rede."""
        catalog = comp.fetch_catalog("ro", "casacivil", current_year=2026)
        assert catalog.known_pages == 0

    def test_parse_year_spec(self) -> None:
        assert comp.parse_year_spec("1981-1983, 2026") == {1981, 1982, 1983, 2026}
        with pytest.raises(ValueError):
            comp.parse_year_spec("81")
        with pytest.raises(ValueError):
            comp.parse_year_spec("1990-1980")

    def test_fontes_with_official_index(self, manifest: None) -> None:
        assert comp.fontes_with_official_index("ro") == ["casacivil"]

    def test_real_ro_manifest_has_the_four_official_lists(self) -> None:
        assert comp.fontes_with_official_index("ro") == ["casacivil"]
        assert [c["tipo"] for c in comp.year_index_configs("ro", "casacivil")] == [
            "lei",
            "lc",
            "decreto",
            "decreto-lei",
        ]


# ---------------------------------------------------------------------------
# Acervo + livro-razão
# ---------------------------------------------------------------------------


def _row(tipo: str, numero: int, uuid5: str, name: str, formato: str = "pdf") -> str:
    return (
        f"{tipo},{numero},,{formato},{uuid5},sha-{uuid5},2026-10-03T19:00:00+00:00,"
        f"http://ditel.casacivil.ro.gov.br/cotel/Livros/Files/{name}"
    )


_ITEMS = {
    "leizilla_ro_casacivil_lei_6001-7000": (
        _INDEX_HEADER
        + "\n".join(
            [
                _row("lei", 6572, "aaaa1111", "L6572.pdf"),
                _row("lei", 6324, "bbbb2222", "L6324%20-%20COMPILADA.pdf"),
                _row("lei", 6200, "cccc3333", "L6200.pdf"),
                _row("lei", 6999, "dddd4444", "L6999.pdf"),  # não listada
            ]
        )
        + "\n",
        {"aaaa1111.pdf", "aaaa1111_djvu.txt", "bbbb2222.pdf", "cccc3333.pdf"},
    ),
    "leizilla_ro_casacivil_decreto-lei_0001-1000": (
        _INDEX_HEADER
        + "\n".join(
            [
                _row("decreto-lei", 9, "eeee5555", "DL9A%20-%20COMPILADO_merged.pdf"),
                _row("decreto-lei", 10, "ffff6666", "DL10.pdf"),
            ]
        )
        + "\n",
        {"eeee5555.pdf", "eeee5555_djvu.txt", "ffff6666.pdf", "ffff6666_djvu.txt"},
    ),
    "leizilla_ro_casacivil_ec_0001-1000": (
        _INDEX_HEADER + _row("ec", 3, "9999aaaa", "EC3.pdf") + "\n",
        {"9999aaaa.pdf"},
    ),
    "leizilla_ro_casacivil_unidentified": (
        _INDEX_HEADER + ",,,pdf,0000bbbb,sha-x,2026-10-03T19:00:00+00:00,x\n",
        set(),
    ),
}
_PARSED = {
    "leizilla-raw-ro-casacivil-lei-06572",
    "leizilla-raw-ro-casacivil-decreto-lei-00009",
    "leizilla-raw-ro-assembleia-lei-06572",
}
_TEXTOS: dict[tuple[str, int], str] = {
    ("lei", 6572): "sha-aaaa1111",
    ("decreto-lei", 9): "sha-eeee5555",
    ("decreto-lei", 10): "sha-ffff6666",
}


@pytest.fixture
def ia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "leizilla.publisher.scrape_identifiers", lambda prefix: list(_ITEMS)
    )
    monkeypatch.setattr(
        "leizilla.publisher.fetch_existing_index", lambda item: _ITEMS[item][0]
    )
    monkeypatch.setattr(
        "leizilla.publisher.fetch_item_filenames", lambda item: _ITEMS[item][1]
    )
    monkeypatch.setattr(
        "leizilla.publisher.list_parsed_raw_ids_strict", lambda ente, fonte: _PARSED
    )


def _ledger(
    textos: Optional[dict[tuple[str, int], str]] = _TEXTOS,
) -> tuple[comp.Catalog, comp.Holdings, dict[str, dict[str, Any]]]:
    catalog = comp.fetch_catalog("ro", "casacivil", current_year=2026)
    holdings = comp.collect_holdings("ro", "casacivil", textos)
    rows = comp.build_ledger(catalog, holdings)
    return catalog, holdings, {r["norma_id"]: r for r in rows}


class TestLedger:
    def test_one_row_per_official_norm_with_stage_flags(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        _, _, rows = _ledger()
        full = rows["leizilla-raw-ro-casacivil-lei-06572"]
        assert (
            full["situacao"],
            full["preservada"],
            full["com_texto"],
            full["legivel"],
            full["estruturada"],
        ) == ("listada", True, True, True, True)
        assert full["ia_item"] == "leizilla_ro_casacivil_lei_6001-7000"
        assert full["arquivos_preservados"] == 1

        no_text = rows["leizilla-raw-ro-casacivil-lei-06324"]
        assert (no_text["preservada"], no_text["com_texto"], no_text["legivel"]) == (
            True,
            False,
            False,
        )
        missing = rows["leizilla-raw-ro-casacivil-lei-06360"]
        assert (missing["preservada"], missing["com_texto"]) == (False, False)
        assert missing["ia_item"] is None

    def test_ementa_date_year_and_files_are_exposed(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        _, _, rows = _ledger()
        row = rows["leizilla-raw-ro-casacivil-lei-06572"]
        assert row["titulo"] == "Lei n. 6572, de 12-11-2026"
        assert (row["data"], row["ano"], row["decada"]) == ("2026-11-12", 2026, 2020)
        assert row["ementa"].startswith("Autoriza o Poder Executivo")
        assert row["coddoc"] == 45727
        assert row["texto_id"] == row["norma_id"]  # chave de junção com `textos`
        assert json.loads(row["arquivos"])[0]["rendicao"] == "original"

    def test_duplicate_official_entries_become_one_row(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        _, _, rows = _ledger()
        dup = rows["leizilla-raw-ro-casacivil-lei-06360"]
        assert dup["entradas"] == 2
        assert dup["coddoc"] == 44356
        assert dup["arquivos_listados"] == 1

    def test_suffixed_norm_is_matched_by_file_not_by_number(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        """O acervo guarda só o arquivo do 9A sob (decreto-lei, 9): o 9 falta."""
        _, _, rows = _ledger()
        nine_a = rows["leizilla-raw-ro-casacivil-decreto-lei-00009a"]
        nine = rows["leizilla-raw-ro-casacivil-decreto-lei-00009"]
        assert (nine_a["numero"], nine_a["sufixo"]) == (9, "A")
        assert (nine_a["preservada"], nine_a["com_texto"], nine_a["legivel"]) == (
            True,
            True,
            True,
        )
        assert nine_a["estruturada"] is None  # S4 só conhece (tipo, numero)
        assert nine_a["texto_id"] == nine["norma_id"]
        assert (nine["preservada"], nine["com_texto"], nine["legivel"]) == (
            False,
            False,
            False,
        )
        assert nine["estruturada"] is True

    def test_plain_norm_keeps_captures_no_sibling_claims(
        self, manifest: None, fetched: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        index = _INDEX_HEADER + _row("decreto-lei", 9, "eeee5555", "DL9.pdf") + "\n"
        monkeypatch.setattr(
            "leizilla.publisher.scrape_identifiers", lambda prefix: ["item"]
        )
        monkeypatch.setattr(
            "leizilla.publisher.fetch_existing_index", lambda item: index
        )
        monkeypatch.setattr(
            "leizilla.publisher.fetch_item_filenames", lambda item: {"eeee5555.pdf"}
        )
        monkeypatch.setattr(
            "leizilla.publisher.list_parsed_raw_ids_strict", lambda ente, fonte: set()
        )
        _, _, rows = _ledger(textos={("decreto-lei", 9): "sha-eeee5555"})
        assert rows["leizilla-raw-ro-casacivil-decreto-lei-00009"]["preservada"] is True
        assert rows["leizilla-raw-ro-casacivil-decreto-lei-00009"]["legivel"] is True
        nine_a = rows["leizilla-raw-ro-casacivil-decreto-lei-00009a"]
        assert (nine_a["preservada"], nine_a["legivel"]) == (False, False)

    def test_held_but_unlisted_norms_are_visible(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        _, _, rows = _ledger()
        # lei: o ano de 2024 falhou → não dá para chamar de órfã.
        orphan = rows["leizilla-raw-ro-casacivil-lei-06999"]
        assert orphan["situacao"] == "indice-incompleto"
        assert (orphan["preservada"], orphan["ano"], orphan["titulo"]) == (
            True,
            None,
            "",
        )
        assert rows["leizilla-raw-ro-casacivil-ec-00003"]["situacao"] == (
            "tipo-sem-indice"
        )
        # A área de espera não tem identidade: não vira linha.
        assert all(r["numero"] is not None for r in rows.values())

    def test_orphan_only_when_every_year_of_the_tipo_was_read(
        self, manifest: None, monkeypatch: pytest.MonkeyPatch, ia: None
    ) -> None:
        pages = {
            **_PAGES,
            BASE + "listleiord.aspx?ano=2024": _page("Leis", 2024, [], None),
        }
        monkeypatch.setattr(
            discovery.CasacivilYearIndexDiscovery,
            "_fetch",
            lambda self, url: pages.get(url),
        )
        _, _, rows = _ledger()
        assert rows["leizilla-raw-ro-casacivil-lei-06999"]["situacao"] == (
            "fora-do-indice"
        )

    def test_unmeasured_stages_are_none_never_false(
        self, manifest: None, fetched: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_index(item: str) -> str:
            raise IndexFetchError("timeout")

        monkeypatch.setattr(
            "leizilla.publisher.scrape_identifiers", lambda prefix: ["item"]
        )
        monkeypatch.setattr("leizilla.publisher.fetch_existing_index", broken_index)
        monkeypatch.setattr(
            "leizilla.publisher.list_parsed_raw_ids_strict", lambda ente, fonte: None
        )
        catalog, holdings, rows = _ledger(textos=None)
        row = rows["leizilla-raw-ro-casacivil-lei-06572"]
        assert (
            row["preservada"],
            row["com_texto"],
            row["legivel"],
            row["estruturada"],
        ) == (None, None, None, None)

        summary = comp.summarize(catalog, holdings, list(rows.values()))
        assert summary["medicao"] == {
            "ok_s2_s3": False,
            "ok_s4": False,
            "ok_legivel": False,
        }
        lei = summary["tipos"][0]
        assert lei["listadas"] == 6
        assert (lei["preservadas"], lei["faltantes"], lei["pct_preservadas"]) == (
            None,
            None,
            None,
        )
        assert lei["faltantes_intervalos"] == []

    def test_pdf_without_item_metadata_is_unknown_text(
        self,
        manifest: None,
        fetched: list[str],
        ia: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "leizilla.publisher.fetch_item_filenames", lambda item: None
        )
        _, holdings, rows = _ledger()
        assert holdings.ok_s2_s3 is False
        row = rows["leizilla-raw-ro-casacivil-lei-06572"]
        assert (row["preservada"], row["com_texto"]) == (True, None)


class TestSummary:
    def test_per_tipo_year_and_decade(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        catalog, holdings, rows = _ledger()
        summary = comp.summarize(
            catalog,
            holdings,
            list(rows.values()),
            generated_at="2026-11-15T00:00:00+00:00",
            git_sha="abc123",
        )
        assert summary["leizilla_completeness_version"] == "0.1"
        assert (summary["ente"], summary["fonte"]) == ("ro", "casacivil")
        assert summary["catalogo"]["completo"] is False
        assert summary["catalogo"]["anos_desconhecidos"] == [
            {"tipo": "lei", "ano": 2024, "status": "failed", "erro": "falha de rede"}
        ]
        # A lista de 2026 declara 6 entradas; uma não tem número legível: ela
        # fica visível, e o total declarado fecha com o que foi lido.
        assert summary["catalogo"]["entradas_ilegiveis"] == [
            {"tipo": "lei", "ano": 2026, "coddoc": 44001, "titulo": "Sem número"}
        ]
        assert summary["catalogo"]["divergencias"] == []

        lei, declei = summary["tipos"]
        assert lei["rotulo"] == "Leis ordinárias"
        assert (lei["anos"], lei["anos_lidos"], lei["catalogo_completo"]) == (
            3,
            2,
            False,
        )
        assert (
            lei["listadas"],
            lei["preservadas"],
            lei["com_texto"],
            lei["legiveis"],
            lei["estruturadas"],
            lei["faltantes"],
        ) == (6, 3, 1, 1, 1, 3)
        assert lei["pct_preservadas"] == 50.0
        assert lei["entradas_repetidas"] == 1
        assert lei["faltantes_intervalos"] == [[6199, 6199], [6300, 6300], [6360, 6360]]
        assert (lei["fora_do_indice"], lei["indice_incompleto"]) == (0, 1)

        by_year = {y["ano"]: y for y in lei["por_ano"]}
        assert by_year[2024]["status"] == "failed"
        assert by_year[2024]["listadas"] is None  # desconhecido, não zero
        assert (by_year[2025]["listadas"], by_year[2025]["preservadas"]) == (2, 1)
        assert (by_year[2026]["listadas"], by_year[2026]["preservadas"]) == (4, 2)

        (decade,) = lei["por_decada"]
        assert (decade["decada"], decade["anos"], decade["anos_desconhecidos"]) == (
            2020,
            3,
            1,
        )
        assert decade["completa"] is False
        assert (decade["listadas"], decade["preservadas"]) == (6, 3)

        assert declei["catalogo_completo"] is True
        assert (declei["listadas"], declei["preservadas"], declei["legiveis"]) == (
            3,
            2,
            2,
        )
        assert declei["estruturadas"] == 1  # o 9A não é medível em S4 e não conta
        assert declei["faltantes_intervalos"] == [[9, 9]]
        assert declei["faltantes_com_sufixo"] == []
        empty_year = declei["por_ano"][1]
        assert (empty_year["ano"], empty_year["status"], empty_year["listadas"]) == (
            1983,
            "ok",
            0,
        )
        assert summary["tipos_sem_indice"] == [{"tipo": "ec", "preservadas": 1}]

    def test_decade_with_no_year_read_is_unknown(
        self, manifest: None, fetched: list[str], ia: None
    ) -> None:
        catalog = comp.fetch_catalog(
            "ro", "casacivil", fetch_years={2026}, current_year=2026
        )
        holdings = comp.collect_holdings("ro", "casacivil", _TEXTOS)
        summary = comp.summarize(
            catalog, holdings, comp.build_ledger(catalog, holdings)
        )
        declei = summary["tipos"][1]
        assert declei["listadas"] is None
        assert declei["por_decada"][0]["listadas"] is None
        assert declei["por_decada"][0]["anos_desconhecidos"] == 2

    def test_number_ranges(self) -> None:
        assert comp.number_ranges([7, 1, 2, 3, 3, 10, 11]) == [[1, 3], [7, 7], [10, 11]]
        assert comp.number_ranges([]) == []


class TestParquet:
    def test_missing_numbers_are_derivable_from_the_parquet(
        self, manifest: None, fetched: list[str], ia: None, tmp_path: Path
    ) -> None:
        import duckdb

        _, _, rows = _ledger()
        path = tmp_path / "completeness.parquet"
        comp.write_ledger_parquet(list(rows.values()), path)

        conn = duckdb.connect()
        try:
            cols = [
                d[0]
                for d in conn.execute(
                    "SELECT * FROM read_parquet(?) LIMIT 0", [str(path)]
                ).description
            ]
            missing = conn.execute(
                "SELECT tipo, numero, sufixo FROM read_parquet(?) "
                "WHERE situacao = 'listada' AND NOT preservada ORDER BY 1, 2",
                [str(path)],
            ).fetchall()
            orphans = conn.execute(
                "SELECT norma_id FROM read_parquet(?) WHERE situacao <> 'listada' "
                "ORDER BY 1",
                [str(path)],
            ).fetchall()
        finally:
            conn.close()
        assert cols == list(comp.LEDGER_SCHEMA)
        assert missing == [
            ("decreto-lei", 9, ""),
            ("lei", 6199, ""),
            ("lei", 6300, ""),
            ("lei", 6360, ""),
        ]
        assert orphans == [
            ("leizilla-raw-ro-casacivil-ec-00003",),
            ("leizilla-raw-ro-casacivil-lei-06999",),
        ]

    def test_empty_ledger_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            comp.write_ledger_parquet([], tmp_path / "x.parquet")

    def test_read_textos_keys_filters_by_fonte(self, tmp_path: Path) -> None:
        import duckdb

        path = tmp_path / "textos.parquet"
        conn = duckdb.connect()
        try:
            conn.execute(
                "COPY (SELECT * FROM (VALUES "
                "('ro','casacivil','lei',6572,'sha-a','texto'),"
                "('ro','assembleia','lei',1,'sha-b','texto')) "
                "t(ente,fonte,tipo,numero,sha256_fonte,texto)) "
                f"TO '{path}' (FORMAT parquet)"
            )
        finally:
            conn.close()
        assert comp.read_textos_keys(path, "ro", "casacivil") == {
            ("lei", 6572): "sha-a"
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def _run(self, tmp_path: Path, *extra: str) -> Any:
        return CliRunner().invoke(
            app,
            [
                "completeness",
                "--output",
                str(tmp_path / "completeness.parquet"),
                "--catalog-snapshot",
                str(tmp_path / "completeness_catalog.json.gz"),
                *extra,
            ],
        )

    def test_writes_parquet_summary_and_snapshot(
        self,
        manifest: None,
        fetched: list[str],
        ia: None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(comp, "fetch_published_textos", lambda *a, **k: False)
        result = self._run(tmp_path)
        assert result.exit_code == 0, result.output
        assert "Leis ordinárias: 3 de 6 preservadas" in result.output
        assert "? legíveis" in result.output  # camada de texto indisponível
        assert "1 lista(s) anual(is) desconhecida(s)" in result.output

        summary = json.loads((tmp_path / "completeness.json").read_text("utf-8"))
        assert summary["medicao"]["ok_legivel"] is False
        assert summary["tipos"][0]["legiveis"] is None
        assert (tmp_path / "completeness.parquet").exists()

        # Segunda execução: só os anos recentes e o que falhou voltam à rede.
        fetched.clear()
        again = self._run(tmp_path, "--refresh-years", "1")
        assert again.exit_code == 0, again.output
        assert sorted(u[-4:] for u in fetched) == ["2024", "2026"]

    def test_nothing_readable_exits_nonzero_and_writes_nothing(
        self, manifest: None, ia: None, tmp_path: Path
    ) -> None:
        result = self._run(tmp_path)  # conftest: nenhuma lista é lida
        assert result.exit_code == 1
        assert not (tmp_path / "completeness.parquet").exists()
        assert not (tmp_path / "completeness_catalog.json.gz").exists()

    def test_upload_sends_fixed_names_to_the_latest_pointer(
        self,
        manifest: None,
        fetched: list[str],
        ia: None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(comp, "fetch_published_textos", lambda *a, **k: False)
        monkeypatch.setenv("IA_ACCESS_KEY", "k")
        monkeypatch.setenv("IA_SECRET_KEY", "s")
        calls: list[list[str]] = []

        def fake_upload(self: Any, args: list[str]) -> None:
            calls.append([a if i < 3 else Path(a).name for i, a in enumerate(args)])

        with (
            patch("leizilla.config.IA_ACCESS_KEY", "k"),
            patch("leizilla.config.IA_SECRET_KEY", "s"),
            patch(
                "leizilla.publisher.InternetArchivePublisher._run_ia_upload",
                fake_upload,
            ),
        ):
            result = self._run(
                tmp_path, "--summary", str(tmp_path / "resumo.json"), "--upload"
            )
        assert result.exit_code == 0, result.output
        assert calls == [
            [
                "ia",
                "upload",
                "leizilla-dataset-ro-v0-latest",
                "completeness.parquet",
                "completeness.json",
                "completeness_catalog.json.gz",
            ]
        ]

    def test_unknown_fonte_and_bad_year_spec(
        self, manifest: None, tmp_path: Path
    ) -> None:
        assert self._run(tmp_path, "--fonte", "assembleia").exit_code == 1
        assert self._run(tmp_path, "--fetch-years", "abc").exit_code == 1
