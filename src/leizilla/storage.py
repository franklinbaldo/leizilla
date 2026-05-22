"""Storage DuckDB para Leizilla — schema e operações CRUD."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from leizilla import config


class DuckDBStorage:
    """Gerenciador de storage DuckDB para leis."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DUCKDB_PATH
        self.conn: Optional[duckdb.DuckDBPyConnection] = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self.conn is None:
            self.conn = duckdb.connect(str(self.db_path))
            self._create_schema()
        return self.conn

    def _create_schema(self) -> None:
        conn = self.connect()
        conn.execute("""
        CREATE TABLE IF NOT EXISTS leis (
            id VARCHAR PRIMARY KEY,
            titulo TEXT NOT NULL,
            numero VARCHAR,
            ano INTEGER,
            data_publicacao DATE,
            tipo_lei VARCHAR,
            ente VARCHAR NOT NULL,
            texto_completo TEXT,
            texto_normalizado TEXT,
            metadados JSON,
            url_original VARCHAR,
            local_pdf_path VARCHAR,
            url_pdf_ia VARCHAR,
            url_parsed_ia VARCHAR,
            hash_conteudo VARCHAR,
            status VARCHAR DEFAULT 'ativo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_ente ON leis(ente)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_ano ON leis(ano)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leis_data ON leis(data_publicacao)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_tipo ON leis(tipo_lei)")
        # Migrate existing DBs that predate url_parsed_ia column
        try:
            conn.execute("ALTER TABLE leis ADD COLUMN url_parsed_ia VARCHAR")
        except Exception:
            pass

    def insert_lei(self, lei_data: Dict[str, Any]) -> None:
        conn = self.connect()
        if "texto_completo" in lei_data and lei_data["texto_completo"]:
            lei_data["hash_conteudo"] = hashlib.sha256(
                lei_data["texto_completo"].encode("utf-8")
            ).hexdigest()
        if "metadados" in lei_data and isinstance(lei_data["metadados"], dict):
            lei_data["metadados"] = json.dumps(lei_data["metadados"])
        lei_data["updated_at"] = datetime.now()
        columns = ", ".join(lei_data.keys())
        placeholders = ", ".join(["?" for _ in lei_data])
        conn.execute(
            f"INSERT OR REPLACE INTO leis ({columns}) VALUES ({placeholders})",
            list(lei_data.values()),
        )

    def get_lei(self, lei_id: str) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        result = conn.execute("SELECT * FROM leis WHERE id = ?", [lei_id]).fetchone()
        if result:
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        return None

    def update_lei(self, lei_id: str, updates: Dict[str, Any]) -> None:
        conn = self.connect()
        updates["updated_at"] = datetime.now()
        set_clause = ", ".join([f"{k} = ?" for k in updates])
        conn.execute(
            f"UPDATE leis SET {set_clause} WHERE id = ?",
            list(updates.values()) + [lei_id],
        )

    def search_leis(
        self,
        ente: Optional[str] = None,
        ano: Optional[int] = None,
        texto: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conn = self.connect()
        where_clauses = []
        params: List[Any] = []
        if ente:
            where_clauses.append("ente = ?")
            params.append(ente)
        if ano:
            where_clauses.append("ano = ?")
            params.append(ano)
        if texto:
            where_clauses.append("texto_normalizado LIKE ?")
            params.append(f"%{texto}%")
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        results = conn.execute(
            f"""
            SELECT id, titulo, ano, data_publicacao, tipo_lei, ente
            FROM leis
            WHERE {where_sql}
            ORDER BY data_publicacao DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]

    def get_leis_pending_parse(
        self,
        ente: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Retorna leis com raw IA item mas sem parsed IA item."""
        conn = self.connect()
        where_clauses = ["url_pdf_ia IS NOT NULL", "url_parsed_ia IS NULL"]
        params: List[Any] = []
        if ente:
            where_clauses.append("ente = ?")
            params.append(ente)
        where_sql = " AND ".join(where_clauses)
        results = conn.execute(
            f"""
            SELECT id, titulo, ano, ente, url_pdf_ia
            FROM leis
            WHERE {where_sql}
            ORDER BY created_at ASC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]

    def export_parquet(
        self,
        output_path: Path,
        ente: Optional[str] = None,
        ano: Optional[int] = None,
    ) -> None:
        conn = self.connect()
        where_clauses = []
        params: List[Any] = []
        if ente:
            where_clauses.append("ente = ?")
            params.append(ente)
        if ano:
            where_clauses.append("ano = ?")
            params.append(ano)
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        conn.execute(
            f"COPY (SELECT * FROM leis WHERE {where_sql}) "
            f"TO '{output_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)",
            params,
        )

    def get_stats(self) -> Dict[str, Any]:
        conn = self.connect()
        stats: Dict[str, Any] = {}
        result = conn.execute("SELECT COUNT(*) FROM leis").fetchone()
        stats["total_leis"] = result[0] if result else 0
        results = conn.execute(
            "SELECT ente, COUNT(*) FROM leis GROUP BY ente ORDER BY 2 DESC"
        ).fetchall()
        stats["por_ente"] = {row[0]: row[1] for row in results}
        results = conn.execute(
            "SELECT ano, COUNT(*) FROM leis WHERE ano IS NOT NULL "
            "GROUP BY ano ORDER BY ano DESC LIMIT 10"
        ).fetchall()
        stats["por_ano"] = {row[0]: row[1] for row in results}
        return stats

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


# Backward-compat alias
DatabaseManager = DuckDBStorage
