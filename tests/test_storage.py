"""
Testes para módulo de storage.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime  # Adicionado

# from src import storage # Removido - F401
from src.storage import DuckDBStorage


@pytest.fixture
def temp_db():
    """Fixture para banco temporário."""
    tf = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
    temp_path = Path(tf.name)
    tf.close()
    if temp_path.exists():
        temp_path.unlink()

    db = DuckDBStorage(db_path=temp_path)
    db.connect()
    yield db
    db.close()
    temp_path.unlink(missing_ok=True)


def test_create_schema(temp_db: DuckDBStorage):
    """Testa criação do schema (tabela leis e monitor_state)."""
    conn = temp_db.connect()
    result_leis = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='leis'"
    ).fetchone()
    assert result_leis is not None, "Tabela 'leis' não foi criada."
    result_monitor_state = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_state'"
    ).fetchone()
    assert result_monitor_state is not None, "Tabela 'monitor_state' não foi criada."


def test_insert_lei(temp_db: DuckDBStorage):
    """Testa inserção de lei."""
    lei_data = {
        "id": "rondonia-lei-2024-001",
        "titulo": "Lei de Teste",
        "numero": "001",
        "ano": 2024,
        "origem": "rondonia",
        "tipo_lei": "lei",
        "texto_completo": "Texto da lei de teste",
        "url_torrent_ia": "http://example.com/lei.torrent",
        "magnet_link_ia": "magnet:?xt=urn:btih:examplehash",
    }
    temp_db.insert_lei(lei_data)
    result = temp_db.get_lei("rondonia-lei-2024-001")
    assert result is not None
    assert result["titulo"] == "Lei de Teste"
    assert result["ano"] == 2024
    assert result["url_torrent_ia"] == "http://example.com/lei.torrent"


def test_search_leis(temp_db: DuckDBStorage):
    """Testa busca de leis."""
    leis_teste = [
        {
            "id": "rondonia-lei-2024-001",
            "titulo": "Lei Ambiental",
            "origem": "rondonia",
            "ano": 2024,
            "tipo_lei": "lei",
            "status_geral": "publicado_ia",
        },
        {
            "id": "rondonia-decreto-2024-002",
            "titulo": "Decreto Educacional",
            "origem": "rondonia",
            "ano": 2024,
            "tipo_lei": "decreto",
            "status_geral": "descoberto",
        },
    ]
    for lei in leis_teste:
        temp_db.insert_lei(lei)
    results = temp_db.search_leis(origem="rondonia")
    assert len(results) == 2
    results = temp_db.search_leis(ano=2024)
    assert len(results) == 2
    results = temp_db.search_leis(origem="rondonia")
    tipos = [r.get("tipo_lei") for r in results]
    assert "lei" in tipos
    assert "decreto" in tipos


def test_get_stats(temp_db: DuckDBStorage):
    """Testa estatísticas."""
    temp_db.insert_lei(
        {
            "id": "rondonia-lei-2024-001",
            "titulo": "Lei 1",
            "origem": "rondonia",
            "ano": 2024,
            "tipo_lei": "lei",
            "status_geral": "publicado_ia",
            "status_download": "sucesso",
            "status_upload": "sucesso",
        }
    )
    temp_db.insert_lei(
        {
            "id": "federal-lei-2024-002",
            "titulo": "Lei 2",
            "origem": "federal",
            "ano": 2024,
            "tipo_lei": "lei",
            "status_geral": "descoberto_monitor",
            "status_download": "pendente",
        }
    )
    temp_db.update_monitor_state(
        "rondonia", "marker1", datetime.now(), 5
    )  # Corrigido F821
    stats = temp_db.get_stats()
    assert stats["total_leis"] == 2
    assert stats["por_origem"].get("rondonia") == 1
    assert stats["por_origem"].get("federal") == 1
    assert stats["por_status_geral"].get("publicado_ia") == 1
    assert stats["por_status_geral"].get("descoberto_monitor") == 1
    assert stats["por_status_download"].get("sucesso") == 1
    assert stats["por_status_download"].get("pendente") == 1
    assert stats["por_status_upload"].get("sucesso") == 1
    assert stats["monitor_geral_ultima_execucao_sucesso"] is not None
    assert len(stats["monitor_por_origem"]) == 1
    assert stats["monitor_por_origem"][0]["origem"] == "rondonia"
    assert stats["monitor_por_origem"][0]["last_items_discovered"] == 5


def test_monitor_state_operations(temp_db: DuckDBStorage):
    """Testa as operações da tabela monitor_state."""
    origem_teste = "test_origem"
    assert temp_db.get_monitor_state(origem_teste) is None
    marker1 = "2024-07-01"
    run_time1 = datetime.now()  # Corrigido F821
    items1 = 10
    temp_db.update_monitor_state(origem_teste, marker1, run_time1, items1)
    state1 = temp_db.get_monitor_state(origem_teste)
    assert state1 is not None
    assert state1["last_processed_marker"] == marker1
    assert state1["last_successful_run_at"] is not None
    assert state1["last_items_discovered"] == items1
    marker2 = "2024-07-02"
    temp_db.update_monitor_state(
        origem_teste, marker=marker2, last_items_discovered=None
    )
    state2 = temp_db.get_monitor_state(origem_teste)
    assert state2 is not None
    assert state2["last_processed_marker"] == marker2
    assert state2["last_successful_run_at"] is not None
    assert state2["last_items_discovered"] == items1
    run_time2 = datetime.now()  # Corrigido F821
    temp_db.update_monitor_state(origem_teste, last_successful_run_at=run_time2)
    state3 = temp_db.get_monitor_state(origem_teste)
    assert state3 is not None
    assert state3["last_processed_marker"] == marker2
    assert state3["last_successful_run_at"] >= run_time2
    assert state3["last_items_discovered"] == items1
