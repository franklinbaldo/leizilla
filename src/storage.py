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
            url_torrent_ia VARCHAR,
            magnet_link_ia VARCHAR,
            hash_conteudo VARCHAR,
            local_pdf_path VARCHAR,        -- Path to the locally downloaded PDF
            ia_item_id VARCHAR,            -- Internet Archive item identifier
            status_geral VARCHAR,          -- Overall status (e.g., descoberto, pdf_local, publicado_ia)
            status_download VARCHAR,       -- Status of PDF download attempt (e.g., sucesso, falha, pendente)
            status_upload VARCHAR,         -- Status of IA upload attempt (e.g., sucesso, falha, pendente)
            erro_download_info TEXT,       -- Detailed error if download failed
            erro_upload_info TEXT,         -- Detailed error if upload failed
            descoberto_em_cli TIMESTAMP,   -- Timestamp of discovery via CLI command
            descoberto_em_monitor TIMESTAMP, -- Timestamp of discovery via monitor command
            ultima_tentativa_download_em TIMESTAMP, -- Timestamp of last download attempt
            ultima_tentativa_upload_em TIMESTAMP,   -- Timestamp of last upload attempt
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Índices principais
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_origem ON leis(origem)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_status_geral ON leis(status_geral)") # Index for new status
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_ano ON leis(ano)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leis_data ON leis(data_publicacao)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_tipo ON leis(tipo_lei)")

        # Tabela para estado do monitoramento
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_state (
            origem VARCHAR PRIMARY KEY,
            last_processed_marker TEXT,
            last_successful_run_at TIMESTAMP,
            last_items_discovered INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

    def insert_lei(self, lei_data: Dict[str, Any]) -> None:
        """Insere ou atualiza uma lei no banco (baseado no ID)."""
        conn = self.connect()

        # Gerar hash do conteúdo
        if "texto_completo" in lei_data and lei_data["texto_completo"]:
            content_hash = hashlib.sha256(
                lei_data["texto_completo"].encode("utf-8")
            ).hexdigest()
            lei_data["hash_conteudo"] = content_hash

        # Preparar metadados JSON
        if "metadados" in lei_data and isinstance(lei_data["metadados"], dict):
            lei_data["metadados"] = json.dumps(lei_data["metadados"])

        # Timestamp de update
        lei_data["updated_at"] = datetime.now()

        # Montar query
        columns = ", ".join(lei_data.keys())
        placeholders = ", ".join(["?" for _ in lei_data])

        conn.execute(
            f"INSERT OR REPLACE INTO leis ({columns}) VALUES ({placeholders})",
            list(lei_data.values()),
        )

    def get_lei(self, lei_id: str) -> Optional[Dict[str, Any]]:
        """Busca uma lei por ID."""
        conn = self.connect()
        result = conn.execute("SELECT * FROM leis WHERE id = ?", [lei_id]).fetchone()

        if result:
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        return None

    def search_leis(
        self,
        origem: Optional[str] = None,
        ano: Optional[int] = None,
        texto: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
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

        results = conn.execute(
            f"""
        SELECT id, titulo, ano, data_publicacao, tipo_lei, origem
        FROM leis 
        WHERE {where_sql}
        ORDER BY data_publicacao DESC
        LIMIT ?
        """,
            params + [limit],
        ).fetchall()

        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]

    def export_parquet(
        self, output_path: Path, origem: Optional[str] = None, ano: Optional[int] = None
    ) -> None:
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
        stats["total_leis"] = result[0] if result else 0

        # Por origem
        results = conn.execute(
            "SELECT origem, COUNT(*) as count FROM leis GROUP BY origem ORDER BY count DESC"
        ).fetchall()
        stats["por_origem"] = {row[0]: row[1] for row in results}

        # Por ano (top 10)
        results = conn.execute(
            "SELECT ano, COUNT(*) as count FROM leis WHERE ano IS NOT NULL GROUP BY ano ORDER BY ano DESC LIMIT 10"
        ).fetchall()
        stats["por_ano"] = {row[0]: row[1] for row in results}

        # Por status_geral
        results = conn.execute(
            "SELECT status_geral, COUNT(*) as count FROM leis WHERE status_geral IS NOT NULL GROUP BY status_geral ORDER BY count DESC"
        ).fetchall()
        stats["por_status_geral"] = {row[0]: row[1] for row in results}

        # Por status_download
        results = conn.execute(
            "SELECT status_download, COUNT(*) as count FROM leis WHERE status_download IS NOT NULL GROUP BY status_download ORDER BY count DESC"
        ).fetchall()
        stats["por_status_download"] = {row[0]: row[1] for row in results}

        # Por status_upload
        results = conn.execute(
            "SELECT status_upload, COUNT(*) as count FROM leis WHERE status_upload IS NOT NULL GROUP BY status_upload ORDER BY count DESC"
        ).fetchall()
        stats["por_status_upload"] = {row[0]: row[1] for row in results}

        # Data da última execução bem-sucedida do monitor (geral e por origem)
        # Geral: Mais recente `last_successful_run_at` de qualquer origem
        geral_last_run_result = conn.execute(
            "SELECT MAX(last_successful_run_at) FROM monitor_state"
        ).fetchone()
        stats["monitor_geral_ultima_execucao_sucesso"] = (
            geral_last_run_result[0]
            if geral_last_run_result and geral_last_run_result[0]
            else None
        )

        # Por origem:
        monitor_por_origem_results = conn.execute("""
            SELECT origem, last_successful_run_at, last_items_discovered, last_processed_marker
            FROM monitor_state
            ORDER BY origem
        """).fetchall()
        stats["monitor_por_origem"] = [
            {
                "origem": row[0],
                "last_successful_run_at": row[1],
                "last_items_discovered": row[2],
                "last_processed_marker": row[3],
            }
            for row in monitor_por_origem_results
        ]

        return stats

    def get_monitor_state(self, origem: str) -> Optional[Dict[str, Any]]:
        """Busca o estado de monitoramento para uma origem."""
        conn = self.connect()
        result = conn.execute(
            "SELECT last_processed_marker, last_successful_run_at, last_items_discovered, updated_at FROM monitor_state WHERE origem = ?",
            [origem],
        ).fetchone()

        if result:
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        return None

    def update_monitor_state(
        self,
        origem: str,
        marker: Optional[str] = None,
        last_successful_run_at: Optional[datetime] = None,
        last_items_discovered: Optional[int] = None,
    ) -> None:
        """Atualiza o estado de monitoramento para uma origem."""
        conn = self.connect()

        update_fields: Dict[str, Any] = {"updated_at": datetime.now()}
        if marker is not None:
            update_fields["last_processed_marker"] = marker
        if last_successful_run_at is not None:
            update_fields["last_successful_run_at"] = last_successful_run_at
        if last_items_discovered is not None:
            update_fields["last_items_discovered"] = last_items_discovered

        # Montar query de update ou insert
        # Usar INSERT OR REPLACE para simplicidade, ou fazer SELECT e depois INSERT/UPDATE

        # Obter o estado atual para não sobrescrever campos não fornecidos com None
        current_state = self.get_monitor_state(origem) or {}

        # Campos que podem ser atualizados
        final_marker = (
            marker if marker is not None else current_state.get("last_processed_marker")
        )
        final_run_at = (
            last_successful_run_at
            if last_successful_run_at is not None
            else current_state.get("last_successful_run_at")
        )
        final_items_discovered = (
            last_items_discovered
            if last_items_discovered is not None
            else current_state.get("last_items_discovered")
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO monitor_state
            (origem, last_processed_marker, last_successful_run_at, last_items_discovered, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                origem,
                final_marker,
                final_run_at,
                final_items_discovered,
                datetime.now(),
            ],
        )

    def search_leis_para_download(
        self, origem: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Busca leis que precisam de download (têm url_pdf_original mas não local_pdf_path nem url_pdf_ia)."""
        conn = self.connect()
        # Esta query pode ser mais elaborada, verificando status, etc.
        results = conn.execute(
            """
            SELECT * FROM leis
            WHERE origem = ?
              AND url_pdf_original IS NOT NULL
              AND local_pdf_path IS NULL
              AND url_pdf_ia IS NULL
            ORDER BY data_publicacao DESC, id
            LIMIT ?
            """,
            [origem, limit],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]

    def search_leis_para_upload(
        self, origem: Optional[str], limit: int, com_url_ia: Optional[bool] = False
    ) -> List[Dict[str, Any]]:
        """Busca leis que precisam de upload (têm local_pdf_path mas não url_pdf_ia, ou se com_url_ia é None/True)."""
        conn = self.connect()

        base_query = "SELECT * FROM leis WHERE local_pdf_path IS NOT NULL AND local_pdf_path != ''"
        params: list = []

        if origem:
            base_query += " AND origem = ?"
            params.append(origem)

        if com_url_ia is False:  # Apenas os que NÃO têm url_pdf_ia
            base_query += " AND url_pdf_ia IS NULL"
        elif com_url_ia is True:  # Apenas os que TÊM url_pdf_ia (para overwrite_ia)
            base_query += " AND url_pdf_ia IS NOT NULL"
        # Se com_url_ia is None, não adiciona filtro sobre url_pdf_ia (pega ambos)

        base_query += " ORDER BY updated_at ASC, id LIMIT ?"  # Prioriza os mais antigos não atualizados
        params.append(limit)

        results = conn.execute(base_query, params).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]

    def get_lei_by_id(self, lei_id: str) -> Optional[Dict[str, Any]]:
        """Busca uma lei específica pelo seu ID completo."""
        return self.get_lei(lei_id)  # Reutiliza o método get_lei já existente

    def get_latest_published_law(
        self, origem: str, ano: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Busca a lei mais recentemente publicada/atualizada no IA para uma origem e ano (opcional).
        "Publicada" aqui significa que tem url_pdf_ia.
        Retorna os campos necessários para o manifesto, incluindo links de torrent.
        """
        conn = self.connect()

        query = """
            SELECT id, url_pdf_ia, url_torrent_ia, magnet_link_ia, ia_item_id, titulo, origem, ano
            FROM leis
            WHERE origem = ?
              AND url_pdf_ia IS NOT NULL
        """
        params: list[Any] = [origem]

        if ano is not None:
            query += " AND ano = ?"
            params.append(ano)

        # Ordenar por updated_at para pegar a mais recente processada, ou data_publicacao
        # Usar updated_at pode ser mais relevante para "última versão no IA"
        query += " ORDER BY updated_at DESC LIMIT 1"

        result = conn.execute(query, params).fetchone()

        if result:
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        return None

    def search_leis_para_download_ou_upload(
        self, origem: str, limit: int
    ) -> List[Dict[str, Any]]:
        """
        Busca leis de uma origem que podem precisar de download ou upload.
        Prioriza leis que não têm PDF local. Depois, leis que têm PDF local mas não URL do IA.
        """
        conn = self.connect()
        query = """
        SELECT * FROM leis
        WHERE origem = ? AND (
            (url_pdf_original IS NOT NULL AND local_pdf_path IS NULL AND url_pdf_ia IS NULL) OR -- Precisa de download
            (local_pdf_path IS NOT NULL AND url_pdf_ia IS NULL) -- Precisa de upload
        )
        ORDER BY
            CASE
                WHEN url_pdf_original IS NOT NULL AND local_pdf_path IS NULL THEN 1 -- Prioridade 1: Precisa download
                WHEN local_pdf_path IS NOT NULL AND url_pdf_ia IS NULL THEN 2 -- Prioridade 2: Precisa upload
                ELSE 3
            END,
            updated_at ASC, -- Processar mais antigos primeiro
            id
        LIMIT ?;
        """
        results = conn.execute(query, [origem, limit]).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in results]

    def close(self) -> None:
        """Fecha conexão com banco."""
        if self.conn:
            self.conn.close()
            self.conn = None


# Instância global do storage
storage = DuckDBStorage()
# A conexão será estabelecida no primeiro uso, não na importação.
# storage.connect() # Removido para evitar problemas de lock com pytest e múltiplas instâncias.
