"""Testes para leizilla.storage."""

import pytest

from leizilla import storage


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.duckdb"
    db = storage.DuckDBStorage(db_path)
    yield db
    db.close()


def test_create_schema(temp_db):
    conn = temp_db.connect()
    result = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'leis'"
    ).fetchone()
    assert result is not None


def test_insert_lei(temp_db):
    lei_data = {
        "id": "ro-lei-2024-001",
        "titulo": "Lei de Teste",
        "numero": "001",
        "ano": 2024,
        "ente": "ro",
        "tipo_lei": "lei",
        "texto_completo": "Texto da lei de teste",
    }
    temp_db.insert_lei(lei_data)
    result = temp_db.get_lei("ro-lei-2024-001")
    assert result is not None
    assert result["titulo"] == "Lei de Teste"
    assert result["ano"] == 2024


def test_search_leis(temp_db):
    leis = [
        {
            "id": "ro-lei-2024-001",
            "titulo": "Lei Ambiental",
            "ente": "ro",
            "ano": 2024,
            "tipo_lei": "lei",
        },
        {
            "id": "ro-decreto-2024-002",
            "titulo": "Decreto Educacional",
            "ente": "ro",
            "ano": 2024,
            "tipo_lei": "decreto",
        },
    ]
    for lei in leis:
        temp_db.insert_lei(lei)

    results = temp_db.search_leis(ente="ro")
    assert len(results) == 2

    results = temp_db.search_leis(ano=2024)
    assert len(results) == 2

    tipos = [r.get("tipo_lei") for r in temp_db.search_leis(ente="ro")]
    assert "lei" in tipos
    assert "decreto" in tipos


def test_url_parsed_ia_column_exists(temp_db):
    conn = temp_db.connect()
    result = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'leis' AND column_name = 'url_parsed_ia'"
    ).fetchone()
    assert result is not None


def test_get_leis_pending_parse_empty(temp_db):
    assert temp_db.get_leis_pending_parse() == []


def test_get_leis_pending_parse_filters_correctly(temp_db):
    # has url_pdf_ia but no url_parsed_ia → should appear
    temp_db.insert_lei(
        {
            "id": "ro-lei-2024-001",
            "titulo": "Lei 1",
            "ente": "ro",
            "url_pdf_ia": "https://archive.org/details/leizilla-raw-ro-assembleia-coddoc-00001",
        }
    )
    # has both → should NOT appear
    temp_db.insert_lei(
        {
            "id": "ro-lei-2024-002",
            "titulo": "Lei 2",
            "ente": "ro",
            "url_pdf_ia": "https://archive.org/details/leizilla-raw-ro-assembleia-coddoc-00002",
            "url_parsed_ia": "https://archive.org/details/leizilla-ro-lei-00042-2024",
        }
    )
    # no url_pdf_ia → should NOT appear
    temp_db.insert_lei(
        {
            "id": "ro-lei-2024-003",
            "titulo": "Lei 3",
            "ente": "ro",
        }
    )

    pending = temp_db.get_leis_pending_parse()
    assert len(pending) == 1
    assert pending[0]["id"] == "ro-lei-2024-001"


def test_get_leis_pending_parse_ente_filter(temp_db):
    temp_db.insert_lei(
        {
            "id": "ro-lei-001",
            "titulo": "Lei RO",
            "ente": "ro",
            "url_pdf_ia": "https://archive.org/details/leizilla-raw-ro-assembleia-coddoc-00001",
        }
    )
    temp_db.insert_lei(
        {
            "id": "sp-lei-001",
            "titulo": "Lei SP",
            "ente": "sp",
            "url_pdf_ia": "https://archive.org/details/leizilla-raw-sp-assembleia-coddoc-00001",
        }
    )

    ro_pending = temp_db.get_leis_pending_parse(ente="ro")
    assert len(ro_pending) == 1
    assert ro_pending[0]["ente"] == "ro"


def test_get_leis_pending_parse_limit(temp_db):
    for i in range(5):
        temp_db.insert_lei(
            {
                "id": f"ro-lei-{i:03d}",
                "titulo": f"Lei {i}",
                "ente": "ro",
                "url_pdf_ia": f"https://archive.org/details/leizilla-raw-ro-assembleia-coddoc-{i:05d}",
            }
        )

    pending = temp_db.get_leis_pending_parse(limit=3)
    assert len(pending) == 3


def test_get_stats(temp_db):
    temp_db.insert_lei(
        {
            "id": "ro-lei-2024-001",
            "titulo": "Lei 1",
            "ente": "ro",
            "ano": 2024,
            "tipo_lei": "lei",
        }
    )
    temp_db.insert_lei(
        {
            "id": "federal-lei-2024-002",
            "titulo": "Lei 2",
            "ente": "federal",
            "ano": 2024,
            "tipo_lei": "lei",
        }
    )

    stats = temp_db.get_stats()
    assert stats["total_leis"] == 2
    assert "ro" in stats["por_ente"]
    assert "federal" in stats["por_ente"]
    assert stats["por_ente"]["ro"] == 1
    assert stats["por_ente"]["federal"] == 1
