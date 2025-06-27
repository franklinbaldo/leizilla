"""
Testes para módulo de storage.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from src import storage


@pytest.fixture
def temp_db():
    """Fixture para banco temporário."""
    with tempfile.NamedTemporaryFile(suffix='.duckdb', delete=False) as f:
        temp_path = Path(f.name)
    
    db = storage.DuckDBStorage(temp_path)
    yield db
    
    db.close()
    temp_path.unlink(missing_ok=True)


def test_create_schema(temp_db):
    """Testa criação do schema."""
    conn = temp_db.connect()
    
    # Verificar se tabela foi criada
    result = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leis'").fetchone()
    assert result is not None


def test_insert_lei(temp_db):
    """Testa inserção de lei."""
    lei_data = {
        'id': 'rondonia-lei-2024-001',
        'titulo': 'Lei de Teste',
        'numero': '001',
        'ano': 2024,
        'origem': 'rondonia',
        'tipo_lei': 'lei',
        'texto_completo': 'Texto da lei de teste'
    }
    
    temp_db.insert_lei(lei_data)
    
    # Verificar se foi inserida
    result = temp_db.get_lei('rondonia-lei-2024-001')
    assert result is not None
    assert result['titulo'] == 'Lei de Teste'
    assert result['ano'] == 2024


def test_search_leis(temp_db):
    """Testa busca de leis."""
    # Inserir algumas leis de teste
    leis_teste = [
        {
            'id': 'rondonia-lei-2024-001',
            'titulo': 'Lei Ambiental',
            'origem': 'rondonia',
            'ano': 2024,
            'tipo_lei': 'lei'
        },
        {
            'id': 'rondonia-decreto-2024-002',
            'titulo': 'Decreto Educacional',
            'origem': 'rondonia',
            'ano': 2024,
            'tipo_lei': 'decreto'
        }
    ]
    
    for lei in leis_teste:
        temp_db.insert_lei(lei)
    
    # Buscar por origem
    results = temp_db.search_leis(origem='rondonia')
    assert len(results) == 2
    
    # Buscar por ano
    results = temp_db.search_leis(ano=2024)
    assert len(results) == 2
    
    # Buscar por tipo (via resultado)
    results = temp_db.search_leis(origem='rondonia')
    tipos = [r.get('tipo_lei') for r in results]
    assert 'lei' in tipos
    assert 'decreto' in tipos


def test_get_stats(temp_db):
    """Testa estatísticas."""
    # Inserir leis de teste
    temp_db.insert_lei({
        'id': 'rondonia-lei-2024-001',
        'titulo': 'Lei 1',
        'origem': 'rondonia',
        'ano': 2024,
        'tipo_lei': 'lei'
    })
    
    temp_db.insert_lei({
        'id': 'federal-lei-2024-002',
        'titulo': 'Lei 2',
        'origem': 'federal',
        'ano': 2024,
        'tipo_lei': 'lei'
    })
    
    stats = temp_db.get_stats()
    
    assert stats['total_leis'] == 2
    assert 'rondonia' in stats['por_origem']
    assert 'federal' in stats['por_origem']
    assert stats['por_origem']['rondonia'] == 1
    assert stats['por_origem']['federal'] == 1