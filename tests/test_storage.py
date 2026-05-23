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


def test_create_schema_discovered_resources(temp_db):
    conn = temp_db.connect()
    result = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'discovered_resources'"
    ).fetchone()
    assert result is not None


def test_insert_and_get_pending_resources(temp_db):
    res_data = {
        "url": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": "lei",
        "chave": "L5120",
    }
    temp_db.insert_resource(res_data)
    pending = temp_db.get_pending_resources()
    assert len(pending) == 1
    assert (
        pending[0]["url"]
        == "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf"
    )
    assert pending[0]["status"] == "pending"


def test_update_resource_status(temp_db):
    res_data = {
        "url": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": "lei",
        "chave": "L5120",
    }
    temp_db.insert_resource(res_data)
    temp_db.update_resource_status(
        "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf",
        "downloaded",
        "https://web.archive.org/web/20260523/http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf",
    )
    pending = temp_db.get_pending_resources()
    assert len(pending) == 0

    conn = temp_db.connect()
    row = conn.execute(
        "SELECT * FROM discovered_resources WHERE url = ?", [res_data["url"]]
    ).fetchone()
    assert row is not None
    assert row[5] == "downloaded"  # status
    assert (
        row[8]
        == "https://web.archive.org/web/20260523/http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf"
    )  # wayback_snapshot


def test_get_downloaded_resources(temp_db):
    res_data = {
        "url": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": "lei",
        "chave": "L5120",
    }
    temp_db.insert_resource(res_data)
    # Status is 'pending' initially
    downloaded = temp_db.get_downloaded_resources("ro", "casacivil")
    assert len(downloaded) == 0

    # Update to 'downloaded'
    temp_db.update_resource_status(res_data["url"], "downloaded")
    downloaded = temp_db.get_downloaded_resources("ro", "casacivil")
    assert len(downloaded) == 1
    assert downloaded[0]["url"] == res_data["url"]


def test_get_leis_pending_ocr(temp_db):
    lei_data = {
        "id": "ro-casacivil-lei-05120",
        "titulo": "Lei 5120",
        "ente": "ro",
        "texto_completo": None,
    }
    temp_db.insert_lei(lei_data)

    pending = temp_db.get_leis_pending_ocr("ro")
    assert len(pending) == 1
    assert pending[0]["id"] == "ro-casacivil-lei-05120"

    # Set texto_completo
    temp_db.update_lei("ro-casacivil-lei-05120", {"texto_completo": "conteudo da lei"})
    pending = temp_db.get_leis_pending_ocr("ro")
    assert len(pending) == 0
