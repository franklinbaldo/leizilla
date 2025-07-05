"""
End-to-end test for Leizilla using real Rondônia laws data from pge-ro/cotel_scrap.

This test validates the complete pipeline:
1. Discovery of laws from cotel_scrap data
2. Database storage operations
3. Text search functionality
4. Export capabilities

Using sample laws from pge-ro/cotel_scrap/markdown_laws/ as test data.
"""

import pytest
import tempfile
import os
from pathlib import Path
import shutil
import duckdb
import json
import hashlib
from datetime import datetime

from src.storage import DuckDBStorage
from src import config


class TestLeisillaE2ERondonia:
    """End-to-end tests using real Rondônia laws data."""
    
    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_leizilla.duckdb"
            storage = DuckDBStorage(db_path)
            yield storage
            storage.close()
    
    @pytest.fixture
    def sample_rondonia_laws(self):
        """Sample laws data extracted from pge-ro/cotel_scrap."""
        return [
            {
                "id": "rondonia_dl_2_1981",
                "titulo": "DECRETO LEI n. 2",
                "numero": "2",
                "ano": 1981,
                "data_publicacao": "1981-12-31",
                "tipo_lei": "decreto-lei",
                "origem": "rondonia",
                "texto_completo": """DECRETO-LEI N° 2, DE 31 DE DEZEMBRO DE 1981

Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.

O GOVERNADOR DO ESTADO DE RONDÔNIA, no uso de suas atribuições legais,

DECRETA:

Artigo 1° - O Orçamento-Programa do Estado para o exercício de 1982, discriminado nos quadros de número I a XI que integram este Decreto-Lei, orça a Receita e fixa a Despesa em valores iguais a Cr$ 19.071.229.000,00 (dezenove bilhões, setenta e um milhões, duzentos e vinte e nove mil cruzeiros).

Artigo 2° - Arrecadar-se-á a Receita na conformidade da legislação em vigor e das especificações dos quadros integrantes desta lei.

Artigo 3° - A Despesa será realizada de acordo com o seguinte desdobramento por Categoria Econômica, Órgãos e Categorias de Programação.

Artigo 4° - O Poder Executivo tomará as medidas necessárias para ajustar o fluxo dos dispêndios ao dos ingressos, a fim de manter o equilíbrio orçamentário.

Artigo 5° - No curso da execução orçamentária o Poder Executivo poderá realizar operações de crédito, respeitados os limites da legislação em vigor.

Artigo 6° - O Poder Executivo poderá abrir, durante o exercício, créditos suplementares até o limite de 20% (vinte por cento) do total da Despesa fixada nesta lei.

Artigo 7° - No curso da execução orçamentária, fica ainda o Poder Executivo autorizado a suplementar automaticamente categorias de programação e promover alocações.

Artigo 8° - Este Decreto-Lei entrará em vigor na data de sua publicação.

Porto Velho, 31 de dezembro de 1981.
JORGE TEIXEIRA
GOVERNADOR DO ESTADO""",
                "texto_normalizado": "decreto lei 2 1981 orça receita despesa orçamento programa estado exercício 1982 governador rondônia",
                "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx?coddoc=2",
                "metadados": {
                    "coddoc": "2",
                    "ementa": "Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.",
                    "fonte": "cotel_scrap"
                }
            },
            {
                "id": "rondonia_lei_3_1982",
                "titulo": "LEI n. 3",
                "numero": "3",
                "ano": 1982,
                "data_publicacao": "1982-01-01", 
                "tipo_lei": "lei",
                "origem": "rondonia",
                "texto_completo": "Texto de exemplo da Lei 3 de Rondônia para teste do sistema Leizilla.",
                "texto_normalizado": "lei 3 rondônia teste sistema leizilla",
                "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx?coddoc=3",
                "metadados": {
                    "coddoc": "3",
                    "ementa": "Lei de exemplo para teste",
                    "fonte": "cotel_scrap"
                }
            }
        ]
    
    def test_complete_pipeline_rondonia_laws(self, temp_storage, sample_rondonia_laws):
        """Test complete pipeline with real Rondônia laws data."""
        storage = temp_storage
        
        # 1. Test database initialization
        assert storage.db_path.exists()
        
        # 2. Test inserting sample laws (simulating discovery + download)
        for law in sample_rondonia_laws:
            storage.insert_lei(law)
        
        # 3. Test retrieval functionality
        decree_law_2 = storage.get_lei("rondonia_dl_2_1981")
        assert decree_law_2 is not None
        assert decree_law_2["titulo"] == "DECRETO LEI n. 2"
        assert "orçamento" in decree_law_2["texto_completo"].lower()
        assert "1982" in decree_law_2["texto_completo"]
        
        # 4. Test search functionality
        search_results = storage.search_leis(origem="rondonia", texto="orçamento")
        assert len(search_results) >= 1
        assert any("DECRETO LEI n. 2" in result["titulo"] for result in search_results)
        
        search_receita = storage.search_leis(texto="receita")
        assert len(search_receita) >= 1
        
        search_governador = storage.search_leis(texto="governador")
        assert len(search_governador) >= 1
        
        # 5. Test filtering by origem and year
        rondonia_laws = storage.search_leis(origem="rondonia")
        assert len(rondonia_laws) == 2
        
        laws_1981 = storage.search_leis(ano=1981)
        assert len(laws_1981) == 1
        assert laws_1981[0]["ano"] == 1981
        
        # 6. Test stats functionality
        stats = storage.get_stats()
        assert stats["total_leis"] == 2
        assert "rondonia" in stats["por_origem"]
        assert stats["por_origem"]["rondonia"] == 2
        
    def test_real_world_search_scenarios(self, temp_storage, sample_rondonia_laws):
        """Test real-world search scenarios using Rondônia law content."""
        storage = temp_storage
        
        # Insert test data
        for law in sample_rondonia_laws:
            storage.insert_lei(law)
        
        # Test legal term searches (common in legal research)
        legal_terms = [
            "decreto",
            "artigo", 
            "orçamento",
            "receita",
            "despesa",
            "estado",
            "governador"
        ]
        
        for term in legal_terms:
            results = storage.search_leis(texto=term)
            # At least some results should be found for common legal terms present in our data
            if term in ["decreto", "orçamento", "receita", "estado", "governador"]:
                assert len(results) >= 1, f"Search for '{term}' should return results"
    
    def test_data_export_formats(self, temp_storage, sample_rondonia_laws):
        """Test data export functionality with real data."""
        storage = temp_storage
        
        # Insert test data
        for law in sample_rondonia_laws:
            storage.insert_lei(law)
        
        # Test export to different formats
        with tempfile.TemporaryDirectory() as export_dir:
            export_path = Path(export_dir)
            
            # Test Parquet export
            parquet_file = export_path / "rondonia_laws.parquet"
            storage.export_parquet(parquet_file, origem="rondonia")
            assert parquet_file.exists()
    
    def test_data_integrity_and_validation(self, temp_storage, sample_rondonia_laws):
        """Test data integrity and validation with real content."""
        storage = temp_storage
        
        # Test with the complete DECRETO LEI n. 2 data
        law_data = sample_rondonia_laws[0]  # DECRETO LEI n. 2
        
        storage.insert_lei(law_data)
        
        # Retrieve and verify all fields
        retrieved = storage.get_lei("rondonia_dl_2_1981")
        
        assert retrieved["numero"] == "2"
        assert retrieved["titulo"] == "DECRETO LEI n. 2"
        assert "GOVERNADOR DO ESTADO DE RONDÔNIA" in retrieved["texto_completo"]
        assert retrieved["ano"] == 1981
        assert retrieved["origem"] == "rondonia"
        assert retrieved["tipo_lei"] == "decreto-lei"
        
        # Test stats
        stats = storage.get_stats()
        assert stats["total_leis"] == 1
    
    def test_performance_with_real_content(self, temp_storage, sample_rondonia_laws):
        """Test performance with realistic content sizes."""
        storage = temp_storage
        
        import time
        
        # Test insertion performance
        start_time = time.time()
        for law in sample_rondonia_laws:
            storage.insert_lei(law)
        insertion_time = time.time() - start_time
        
        # Should complete within reasonable time
        assert insertion_time < 1.0, "Insertion should be fast"
        
        # Test search performance
        start_time = time.time()
        results = storage.search_leis(texto="orçamento")
        search_time = time.time() - start_time
        
        assert search_time < 0.5, "Search should be fast"
        assert len(results) > 0, "Should find relevant results"


class TestLeisillaIntegrationWithCotelScrap:
    """Integration tests that validate compatibility with cotel_scrap data format."""
    
    def test_cotel_scrap_markdown_compatibility(self, tmp_path):
        """Test compatibility with cotel_scrap markdown format."""
        # Simulate cotel_scrap markdown structure
        markdown_content = """---
title: "DECRETO LEI n. 2"
coddoc: "2"
summary: |
  Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.
---

# DECRETO LEI n. 2

## Ementa

Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.

## Texto Integral dos Documentos Anexos

GOVERNO DO ESTADO DE RONDÔNIA
Gabinete do Governador
DECRETO-LEI N° 2, DE 31 DE DEZEMBRO DE 1981

Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.
"""
        
        # Test parsing frontmatter and content
        lines = markdown_content.split('\n')
        in_frontmatter = False
        frontmatter = {}
        content_lines = []
        
        for line in lines:
            if line.strip() == '---':
                in_frontmatter = not in_frontmatter
                continue
            
            if in_frontmatter:
                if ':' in line:
                    key, value = line.split(':', 1)
                    frontmatter[key.strip()] = value.strip().strip('"')
            else:
                content_lines.append(line)
        
        # Verify parsed data
        assert frontmatter["title"] == "DECRETO LEI n. 2"
        assert frontmatter["coddoc"] == "2" 
        assert "orçamento" in frontmatter["summary"].lower()
        
        full_content = '\n'.join(content_lines)
        assert "GOVERNO DO ESTADO DE RONDÔNIA" in full_content
        assert "1981" in full_content
        
    def test_url_pattern_compatibility(self):
        """Test URL pattern compatibility with cotel_scrap source."""
        base_url = "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx"
        
        # Test coddoc URL generation
        coddocs = ["2", "3", "4", "5", "100", "1000"]
        
        for coddoc in coddocs:
            url = f"{base_url}?coddoc={coddoc}"
            assert url.startswith("http://ditel.casacivil.ro.gov.br")
            assert f"coddoc={coddoc}" in url
            assert "COTEL/Livros" in url