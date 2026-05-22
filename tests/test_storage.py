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
