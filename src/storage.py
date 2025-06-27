"""
Módulo de storage DuckDB para Leizilla.

Gerencia operações de banco de dados local, schema e queries.
"""

import duckdb
from pathlib import Path
from typing import Optional, Dict, Any, List
import json
import hashlib
from datetime import datetime

import config


class DuckDBStorage:
    """Gerenciador de storage DuckDB para leis."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DUCKDB_PATH
        self.conn: Optional[duckdb.DuckDBPyConnection] = None
    
    def connect(self) -> duckdb.DuckDBPyConnection:
        """Conecta ao banco DuckDB."""
        if self.conn is None:
            self.conn = duckdb.connect(str(self.db_path))
            self._create_schema()
        return self.conn
    
    def _create_schema(self) -> None:
        """Cria schema inicial conforme ADR-0003."""
        conn = self.connect()
        
        # Tabela principal de leis
        conn.execute("""
        CREATE TABLE IF NOT EXISTS leis (
            id VARCHAR PRIMARY KEY,
            titulo TEXT NOT NULL,
            numero VARCHAR,
            ano INTEGER,
            data_publicacao DATE,
            tipo_lei VARCHAR,
            origem VARCHAR NOT NULL,
            texto_completo TEXT,
            texto_normalizado TEXT,
            metadados JSON,
            url_original VARCHAR,
            url_pdf_ia VARCHAR,
            hash_conteudo VARCHAR,
            status VARCHAR DEFAULT 'ativo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Índices principais
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_origem ON leis(origem)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_ano ON leis(ano)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_data ON leis(data_publicacao)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_tipo ON leis(tipo_lei)")
    
    def insert_lei(self, lei_data: Dict[str, Any]) -> None:
        """Insere uma lei no banco."""
        conn = self.connect()
        
        # Gerar hash do conteúdo
        if 'texto_completo' in lei_data and lei_data['texto_completo']:
            content_hash = hashlib.sha256(
                lei_data['texto_completo'].encode('utf-8')
            ).hexdigest()
            lei_data['hash_conteudo'] = content_hash
        
        # Preparar metadados JSON
        if 'metadados' in lei_data and isinstance(lei_data['metadados'], dict):
            lei_data['metadados'] = json.dumps(lei_data['metadados'])
        
        # Timestamp de update
        lei_data['updated_at'] = datetime.now()
        
        # Montar query
        columns = ', '.join(lei_data.keys())
        placeholders = ', '.join(['?' for _ in lei_data])
        
        conn.execute(
            f"INSERT OR REPLACE INTO leis ({columns}) VALUES ({placeholders})",
            list(lei_data.values())
        )
    
    def get_lei(self, lei_id: str) -> Optional[Dict[str, Any]]:
        """Busca uma lei por ID."""
        conn = self.connect()
        result = conn.execute(
            "SELECT * FROM leis WHERE id = ?", [lei_id]
        ).fetchone()
        
        if result:
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        return None
    
    def search_leis(self, 
                   origem: Optional[str] = None,
                   ano: Optional[int] = None,
                   texto: Optional[str] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
        """Busca leis com filtros."""
        conn = self.connect()
        
        where_clauses = []
        params = []
        
        if origem:
            where_clauses.append("origem = ?")
            params.append(origem)
        
        if ano:
            where_clauses.append("ano = ?")
            params.append(ano)
        
        if texto:
            where_clauses.append("texto_normalizado LIKE ?")
            params.append(f"%{texto}%")
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        results = conn.execute(f"""
        SELECT id, titulo, ano, data_publicacao, tipo_lei, origem
        FROM leis 
        WHERE {where_sql}
        ORDER BY data_publicacao DESC
        LIMIT ?
        """, params + [limit]).fetchall()
        
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]
    
    def export_parquet(self, 
                      output_path: Path,
                      origem: Optional[str] = None,
                      ano: Optional[int] = None) -> None:
        """Exporta dados para Parquet."""
        conn = self.connect()
        
        where_clauses = []
        params = []
        
        if origem:
            where_clauses.append("origem = ?")
            params.append(origem)
        
        if ano:
            where_clauses.append("ano = ?")
            params.append(ano)
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        conn.execute(f"""
        COPY (SELECT * FROM leis WHERE {where_sql}) 
        TO '{output_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do banco."""
        conn = self.connect()
        
        stats = {}
        
        # Total de leis
        result = conn.execute("SELECT COUNT(*) FROM leis").fetchone()
        stats['total_leis'] = result[0] if result else 0
        
        # Por origem
        results = conn.execute("""
        SELECT origem, COUNT(*) as count 
        FROM leis 
        GROUP BY origem 
        ORDER BY count DESC
        """).fetchall()
        stats['por_origem'] = {row[0]: row[1] for row in results}
        
        # Por ano
        results = conn.execute("""
        SELECT ano, COUNT(*) as count 
        FROM leis 
        WHERE ano IS NOT NULL
        GROUP BY ano 
        ORDER BY ano DESC
        LIMIT 10
        """).fetchall()
        stats['por_ano'] = {row[0]: row[1] for row in results}
        
        return stats
    
    def close(self) -> None:
        """Fecha conexão com banco."""
        if self.conn:
            self.conn.close()
            self.conn = None


# Instância global do storage
storage = DuckDBStorage()