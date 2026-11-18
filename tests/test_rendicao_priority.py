"""Rendições não originais na colheita (ADR-0010/0011): classificar, gravar, priorizar.

Offline. O catálogo publicado de 2026-11-18 mostrou que as normas cuja lista oficial
só oferece uma rendição não original (``LC68 - COMPILADA.pdf``) estavam muito menos
preservadas que as demais; o diagnóstico é de ordem da fila (as originais foram
varridas antes por nome canônico). Estes testes fixam o que a colheita agora faz.
"""

import csv
import io
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest

from leizilla import discovery
from leizilla.rendicao import rendicao_da_url, rendicao_para_fila
from leizilla.scraper import harvest_pending_resources
from leizilla.storage import DuckDBStorage

from harvest_fakes import batch_ok, uploaded_captures

BASE = "https://fonte.example/COTEL/Livros/Files/"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[DuckDBStorage]:
    storage = DuckDBStorage(tmp_path / "t.duckdb")
    yield storage
    storage.close()


def _res(nome: str, tipo: str, numero: int, **extra: Any) -> Dict[str, Any]:
    return {
        "url": BASE + nome,
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": tipo,
        "chave": f"{tipo}-{numero:05d}",
        "status": "pending",
        **extra,
    }


def _order(db: DuckDBStorage, **kw: Any) -> list[str]:
    return [r["url"].rsplit("/", 1)[-1] for r in db.get_pending_resources(**kw)]


# ------------------------------------------------------------------ classificação


@pytest.mark.parametrize(
    "name, expected",
    [
        ("L1865_compressed.pdf", "original"),  # o original recomprimido
        ("LC999_merged.pdf", "original"),
        ("15597.pdf", "original"),  # número puro
        ("DEC15816 - COMP.pdf", "compilada"),  # abreviatura
        ("DEC24131 - COMP..pdf", "compilada"),
        ("DL9A - COMPILADO_merged.pdf", "compilada"),
        ("L6500 - COMPILADA.pdf", "compilada"),
        ("D13385-REPUB.pdf", "outra"),
        ("LC1096 ADI.pdf", "outra"),
        ("D31884%20-%20SEM%20EFEITO.pdf", "outra"),
        ("LC333-A.pdf", "outra"),
    ],
)
def test_rendition_labels_for_the_filename_shapes_seen_in_the_catalog(
    name: str, expected: str
) -> None:
    assert discovery.year_index_rendicao(name) == expected


def test_a_compressed_original_is_not_filed_under_outra() -> None:
    # 257 dos 466 arquivos "outra" do catálogo eram ``L{n}_compressed.pdf``
    assert discovery.year_index_rendicao("L1865_compressed.pdf") == "original"


@pytest.mark.parametrize(
    "url, expected",
    [
        (BASE + "LC68%20-%20COMPILADA.pdf", "compilada"),
        (BASE + "ESTRUTURA-LC224-Compilada.pdf", "compilada"),
        (BASE + "L6572.pdf", "original"),
        # fora do padrão da lista oficial: sem rendição declarada
        ("https://alro.example/Download?coddoc=123", ""),
        ("https://planalto.example/ccivil_03/leis/lei-1.htm", ""),
        ("https://alro.example/arquivo-revisto.pdf", ""),
    ],
)
def test_url_rendition_only_applies_to_official_listing_names(
    url: str, expected: str
) -> None:
    assert rendicao_da_url(url) == expected


def test_queue_rendition_defaults_to_original() -> None:
    assert rendicao_para_fila("https://alro.example/Download?coddoc=1") == "original"


# ------------------------------------------------------------------ fila de colheita


def test_norm_listing_only_a_compiled_file_goes_first(db: DuckDBStorage) -> None:
    # LC 68: o índice oficial só oferece a compilada. Mesmo sendo bem mais antiga
    # que as demais, vem antes de qualquer original pendente do tipo.
    for n in (1100, 1099, 1098):
        db.insert_resource(_res(f"LC{n}.pdf", "lc", n))
    db.insert_resource(_res("LC68%20-%20COMPILADA.pdf", "lc", 68))

    assert _order(db)[0] == "LC68%20-%20COMPILADA.pdf"


def test_tem_compilada_norms_precede_plain_originals_and_keep_both_files(
    db: DuckDBStorage,
) -> None:
    for n in (6500, 6501, 6502):
        db.insert_resource(_res(f"L{n}.pdf", "lei", n))
    db.insert_resource(_res("L120%20-%20COMPILADA.pdf", "lei", 120))
    db.insert_resource(_res("L120.pdf", "lei", 120))

    order = _order(db)

    assert set(order[:2]) == {"L120.pdf", "L120%20-%20COMPILADA.pdf"}
    assert order[2:] == ["L6502.pdf", "L6501.pdf", "L6500.pdf"]


def test_only_listed_non_original_comes_before_tem_compilada(
    db: DuckDBStorage,
) -> None:
    db.insert_resource(_res("L10%20-%20COMPILADA.pdf", "lei", 10))
    db.insert_resource(_res("L10.pdf", "lei", 10))
    db.insert_resource(_res("L5%20-%20REVOGADO.pdf", "lei", 5))  # sem original

    assert _order(db)[0] == "L5%20-%20REVOGADO.pdf"


def test_other_non_original_renditions_precede_originals_only(
    db: DuckDBStorage,
) -> None:
    db.insert_resource(_res("L900.pdf", "lei", 900))
    db.insert_resource(_res("L800.pdf", "lei", 800))
    db.insert_resource(_res("L800%20-%20ADI.pdf", "lei", 800))

    # a anotação ADI (tier 2) vai antes dos originais (tier 3), que seguem newest-first
    assert _order(db) == ["L800%20-%20ADI.pdf", "L900.pdf", "L800.pdf"]


def test_a_preserved_original_does_not_demote_the_missing_compiled(
    db: DuckDBStorage,
) -> None:
    db.insert_resource(_res("L120.pdf", "lei", 120, status="downloaded"))
    db.insert_resource(_res("L120%20-%20COMPILADA.pdf", "lei", 120))
    for n in (6500, 6501):
        db.insert_resource(_res(f"L{n}.pdf", "lei", n))

    assert _order(db)[0] == "L120%20-%20COMPILADA.pdf"


def test_priority_never_overrides_the_fairness_step(db: DuckDBStorage) -> None:
    # uma compilada já tentada (e ainda pending) continua depois de tudo que nunca
    # foi tentado — o degrau do ADR-0016/#297 vem antes da prioridade.
    db.insert_resource(_res("L10%20-%20COMPILADA.pdf", "lei", 10))
    db.insert_resource(_res("L6500.pdf", "lei", 6500))
    db.connect().execute(
        "UPDATE discovered_resources SET ultima_tentativa = '2026-11-14 00:00:00' "
        "WHERE url LIKE '%COMPILADA%'"
    )

    assert _order(db) == ["L6500.pdf", "L10%20-%20COMPILADA.pdf"]


def test_priority_keeps_the_bucket_rotation_inside_the_tier(
    db: DuckDBStorage,
) -> None:
    for n in (31250, 31249, 30010):
        db.insert_resource(_res(f"D{n}.pdf", "decreto", n))
    for n in (2100, 2101, 50):
        db.insert_resource(_res(f"D{n}%20-%20COMPILADO.pdf", "decreto", n))

    order = _order(db)

    # tier compilada primeiro, rodízio entre buckets (2001-3000 antes de 1-1000)
    assert order[:3] == [
        "D2101%20-%20COMPILADO.pdf",
        "D50%20-%20COMPILADO.pdf",
        "D2100%20-%20COMPILADO.pdf",
    ]
    assert order[3:] == ["D31250.pdf", "D30010.pdf", "D31249.pdf"]


def test_rendition_column_is_filled_on_insert_and_backfilled_on_old_dbs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.duckdb"
    first = DuckDBStorage(path)
    first.insert_resource(_res("L1%20-%20COMPILADA.pdf", "lei", 1))
    first.insert_resource(_res("L2.pdf", "lei", 2))
    assert dict(
        first.connect()
        .execute("SELECT chave, rendicao FROM discovered_resources")
        .fetchall()
    ) == {"lei-00001": "compilada", "lei-00002": "original"}
    # banco do cache do workflow, anterior à coluna
    first.connect().execute("UPDATE discovered_resources SET rendicao = NULL")
    first.close()

    reopened = DuckDBStorage(path)
    got = dict(
        reopened.connect()
        .execute("SELECT chave, rendicao FROM discovered_resources")
        .fetchall()
    )
    reopened.close()
    assert got == {"lei-00001": "compilada", "lei-00002": "original"}


# ------------------------------------------------------------------ colheita grava a rendição


def test_harvest_records_the_rendition_in_the_capture_but_not_for_originals(
    db: DuckDBStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "leizilla.scraper.make_rate_limiter", lambda *a, **k: lambda _url: None
    )
    db.insert_resource(_res("LC68%20-%20COMPILADA.pdf", "lc", 68))
    db.insert_resource(_res("LC1100.pdf", "lc", 1100))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed",
            side_effect=lambda url: (f"%PDF-1.4 {url}".encode(), False),
        ),
    ):
        stats = harvest_pending_resources(db, pub, limit=5, batch_size=25)

    assert stats["success"] == 2
    got = {c.target.numero: c.lei_data["rendicao"] for c in uploaded_captures(pub)}
    assert got == {68: "compilada", 1100: ""}


def test_rendition_reaches_the_index_csv_and_original_bytes_stay_apart() -> None:
    # A rendição é coluna do índice (ADR-0010): a mesma norma tem uma linha por
    # (rendição, bytes) e a compilada não substitui a linha do original.
    from leizilla.ia_utils import INDEX_COLUMNS, merge_index_row

    base = dict(tipo="lc", numero=68, formato="pdf")
    csv1 = merge_index_row(
        None,
        rendicao="",
        uuid5="aaaa1111",
        sha256="a" * 64,
        source="s/LC68.pdf",
        **base,
    )
    csv2 = merge_index_row(
        csv1,
        rendicao="compilada",
        uuid5="bbbb2222",
        sha256="b" * 64,
        source="s/LC68%20-%20COMPILADA.pdf",
        **base,
    )
    rows = list(csv.DictReader(io.StringIO(csv2)))
    assert [(r["rendicao"], r["uuid5"]) for r in rows] == [
        ("", "aaaa1111"),
        ("compilada", "bbbb2222"),
    ]
    assert "rendicao" in INDEX_COLUMNS


def test_text_layer_today_prefers_the_most_recent_capture_whatever_its_rendition() -> (
    None
):
    """Caracteriza (não muda) a seleção da camada de texto.

    ``captures_by_identity`` ordena por ``captured_at`` decrescente e a camada usa a
    primeira captura com ``_djvu.txt``: uma compilada capturada depois do original
    passa à frente dele. Com a coluna ``rendicao`` agora gravada pela colheita, a
    escolha entre as duas deixa de ser cega — ver a recomendação em
    ``docs/okf/project-dag.md`` (folha das rendições não originais).
    """
    from leizilla.textlayer import captures_by_identity

    index_csv = (
        "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"
        "lc,68,,pdf,aaaa1111,a,2026-06-26T00:00:00+00:00,s/LC68.pdf\n"
        "lc,68,compilada,pdf,bbbb2222,b,2026-11-18T00:00:00+00:00,s/LC68%20-%20C.pdf\n"
    )

    candidates = captures_by_identity(index_csv)[("lc", 68)]

    assert [c["rendicao"] for c in candidates] == ["compilada", ""]
