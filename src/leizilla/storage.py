"""Storage DuckDB para Leizilla — schema e operações CRUD."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from leizilla import config
from leizilla.rendicao import RENDICAO_ORIGINAL, rendicao_para_fila


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
            data_ato DATE,
            tipo_lei VARCHAR,
            ente VARCHAR NOT NULL,
            texto_completo TEXT,
            texto_normalizado TEXT,
            metadados JSON,
            url_original VARCHAR,
            local_pdf_path VARCHAR,
            url_pdf_ia VARCHAR,
            hash_conteudo VARCHAR,
            status VARCHAR DEFAULT 'ativo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        self._migrate_legacy_schema(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_ente ON leis(ente)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_ano ON leis(ano)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_data ON leis(data_ato)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leis_tipo ON leis(tipo_lei)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS discovered_resources (
            url VARCHAR PRIMARY KEY,
            ente VARCHAR NOT NULL,
            fonte VARCHAR NOT NULL,
            tipo_documento VARCHAR,
            chave VARCHAR,
            status VARCHAR DEFAULT 'pending',
            data_descoberta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ultima_tentativa TIMESTAMP,
            wayback_snapshot VARCHAR,
            motivo VARCHAR
        )
        """)
        # Bancos antigos (cache do workflow) não têm a coluna de motivo.
        conn.execute(
            "ALTER TABLE discovered_resources ADD COLUMN IF NOT EXISTS motivo VARCHAR"
        )
        # Rendição do arquivo (original|compilada|revogado|retificado|outra), derivada
        # do nome — a fila de colheita a usa como prioridade (get_pending_resources).
        conn.execute(
            "ALTER TABLE discovered_resources ADD COLUMN IF NOT EXISTS rendicao VARCHAR"
        )
        self._backfill_rendicao(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_status ON discovered_resources(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resources_ente ON discovered_resources(ente)"
        )

    @staticmethod
    def _backfill_rendicao(conn: duckdb.DuckDBPyConnection) -> None:
        """Preenche ``rendicao`` das linhas de bancos antigos (cache do workflow).

        Só as poucas linhas não originais são atualizadas uma a uma; o resto (a
        imensa maioria) recebe ``original`` num único UPDATE.
        """
        missing = [
            row[0]
            for row in conn.execute(
                "SELECT url FROM discovered_resources WHERE rendicao IS NULL"
            ).fetchall()
        ]
        if not missing:
            return
        for url in missing:
            rendicao = rendicao_para_fila(url)
            if rendicao != RENDICAO_ORIGINAL:
                conn.execute(
                    "UPDATE discovered_resources SET rendicao = ? WHERE url = ?",
                    [rendicao, url],
                )
        conn.execute(
            "UPDATE discovered_resources SET rendicao = ? WHERE rendicao IS NULL",
            [RENDICAO_ORIGINAL],
        )

    @staticmethod
    def _migrate_legacy_schema(conn: duckdb.DuckDBPyConnection) -> None:
        """Rename the legacy act-date column without creating two semantic truths."""
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info('leis')").fetchall()
        }
        has_old = "data_publicacao" in columns
        has_new = "data_ato" in columns
        if has_old and has_new:
            raise RuntimeError(
                "leis contains both data_publicacao and data_ato; refusing ambiguous migration"
            )
        if has_old:
            conn.execute("ALTER TABLE leis RENAME COLUMN data_publicacao TO data_ato")

    def insert_resource(self, resource_data: Dict[str, Any]) -> None:
        conn = self.connect()
        if "rendicao" not in resource_data and resource_data.get("url"):
            resource_data = {
                **resource_data,
                "rendicao": rendicao_para_fila(str(resource_data["url"])),
            }
        columns = ", ".join(resource_data.keys())
        placeholders = ", ".join(["?" for _ in resource_data])
        conn.execute(
            f"INSERT OR IGNORE INTO discovered_resources ({columns}) VALUES ({placeholders})",
            list(resource_data.values()),
        )

    def get_pending_resources(
        self,
        limit: int = 100,
        ente: Optional[str] = None,
        tipo: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conn = self.connect()
        conditions = ["k.status = 'pending'"]
        params: list = []
        if ente:
            conditions.append("k.ente = ?")
            params.append(ente)
        if tipo:
            conditions.append("k.tipo_documento = ?")
            params.append(tipo)
        where = " AND ".join(conditions)
        params.append(limit)
        # Never-tried resources first (ultima_tentativa IS NULL), then
        # least-recently-retried — sem isto, um LIMIT pequeno sempre
        # reseleciona os MESMOS itens no topo do scan (ex.: os N primeiros
        # 'pending' de um tipo/fonte que falha persistentemente), travando
        # candidatos novos descobertos depois deles fora de todo batch
        # (achado de produção: discover-harvest-federal/mpv falhando os
        # mesmos 10 itens em toda rodada, issue #297) — não resolve uma
        # falha persistente em si, mas garante que ela não monopolize
        # `limit` para sempre em detrimento de recursos nunca tentados.
        #
        # Dentro do mesmo degrau de justiça, o maior número primeiro: as normas
        # mais recentes são as mais consultadas e as que ainda não têm cópia em
        # lugar nenhum, então são preservadas antes do acervo antigo (ADR-0016).
        # O número é o sufixo numérico da chave ("decreto-31250" → 31250); chave
        # sem número (área de espera) vai por último, e a URL desempata para a
        # ordem ser determinística.
        # Intercalado entre os buckets de 1000 números (os itens do IA): dentro de
        # cada degrau de justiça e tipo, a posição `rn` é a ordem do recurso no seu
        # bucket (mais novo = 1). Ordenar por `rn` antes do bucket pega o mais novo
        # de cada bucket em rodízio, do bucket mais alto ao mais baixo, em vez de
        # esgotar um item (e estourar a ração por item do IA) antes de abrir o
        # próximo. Chave sem número fica sem bucket e vai por último.
        # Prioridade por norma (degrau ``_prio``), logo após o degrau de justiça e
        # antes do rodízio por bucket: o que a colheita ainda não tem e é mais
        # consultado vai primeiro, sem mudar o ritmo por host nem o lote do IA.
        #   0 — a norma não lista arquivo original (só compilada/revogado/outra):
        #       sem esta captura a norma inteira some do acervo (ex.: LC 68/1992);
        #   1 — a norma tem uma rendição compilada (situação ``tem-compilada``): é a
        #       versão viva, com as alterações, e o original que a acompanha;
        #   2 — demais rendições não originais (revogado, retificado, outra);
        #   3 — originais.
        # O agregado por norma olha **todos** os status: um original já preservado
        # não rebaixa a compilada que ainda falta. O ``_rn`` do rodízio é por degrau.
        results = conn.execute(
            "WITH n AS (SELECT ente, fonte, tipo_documento, chave, "
            "bool_or(rendicao = 'original') AS _has_orig, "
            "bool_or(rendicao = 'compilada') AS _has_comp "
            "FROM discovered_resources WHERE chave IS NOT NULL GROUP BY ALL), "
            "p AS (SELECT k.*, "
            "TRY_CAST(NULLIF(regexp_extract(k.chave, '(\\d+)$', 1), '') AS BIGINT) "
            "AS _num, CASE WHEN NOT coalesce(n._has_orig, true) THEN 0 "
            "WHEN coalesce(n._has_comp, false) THEN 1 "
            "WHEN coalesce(k.rendicao, 'original') <> 'original' THEN 2 "
            "ELSE 3 END AS _prio "
            "FROM discovered_resources k LEFT JOIN n "
            "ON k.ente = n.ente AND k.fonte = n.fonte "
            "AND k.tipo_documento IS NOT DISTINCT FROM n.tipo_documento "
            "AND k.chave = n.chave WHERE " + where + "), "
            "b AS (SELECT *, CASE WHEN _num > 0 THEN (_num - 1) // 1000 "
            "WHEN _num IS NOT NULL THEN 0 END AS _bucket FROM p), "
            "r AS (SELECT *, row_number() OVER (PARTITION BY ente, fonte, "
            "tipo_documento, _bucket, (ultima_tentativa IS NULL), _prio "
            "ORDER BY _num DESC NULLS LAST, url ASC) AS _rn FROM b) "
            "SELECT * EXCLUDE (_num, _bucket, _rn, _prio) FROM r "
            "ORDER BY ultima_tentativa ASC NULLS FIRST, "
            "CASE WHEN _num IS NULL THEN 1 ELSE 0 END, _prio ASC, _rn ASC, "
            "_bucket DESC NULLS LAST, _num DESC NULLS LAST, url ASC LIMIT ?",
            params,
        ).fetchall()
        columns = [desc[0] for desc in (conn.description or [])]
        return [dict(zip(columns, row)) for row in results]

    def count_pending_in_range(
        self, ente: str, fonte: str, tipo: str, start: int, end: int
    ) -> int:
        """Recursos ``pending`` que mapeiam para o item de range ``[start, end]``.

        O item do IA é função de ``(ente, fonte, tipo, número)``; a chave
        ``{tipo}-{número}`` e a mesma extração numérica da ordenação de
        :meth:`get_pending_resources` definem a pertença.
        """
        row = (
            self.connect()
            .execute(
                "SELECT count(*) FROM discovered_resources WHERE status = 'pending' "
                "AND ente = ? AND fonte = ? AND regexp_matches(chave, ?) "
                "AND TRY_CAST(NULLIF(regexp_extract(chave, '(\\d+)$', 1), '') "
                "AS BIGINT) BETWEEN ? AND ?",
                [ente, fonte, f"^{re.escape(tipo)}-\\d+$", start, end],
            )
            .fetchone()
        )
        return int(row[0]) if row else 0

    def get_downloaded_resources(
        self, ente: str, fonte: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        conn = self.connect()
        results = conn.execute(
            "SELECT * FROM discovered_resources WHERE status = 'downloaded' AND ente = ? AND fonte = ? LIMIT ?",
            [ente, fonte, limit],
        ).fetchall()
        columns = [desc[0] for desc in (conn.description or [])]
        return [dict(zip(columns, row)) for row in results]

    def update_resource_status(
        self,
        url: str,
        status: str,
        wayback_snapshot: Optional[str] = None,
        motivo: Optional[str] = None,
    ) -> None:
        """Atualiza status/tentativa; ``motivo`` (ex.: ``spam``) guarda o porquê."""
        conn = self.connect()
        now = datetime.now()
        if motivo is not None:
            conn.execute(
                "UPDATE discovered_resources SET status = ?, motivo = ?, "
                "ultima_tentativa = ? WHERE url = ?",
                [status, motivo, now, url],
            )
            return
        if wayback_snapshot:
            conn.execute(
                "UPDATE discovered_resources SET status = ?, wayback_snapshot = ?, ultima_tentativa = ? WHERE url = ?",
                [status, wayback_snapshot, now, url],
            )
        else:
            conn.execute(
                "UPDATE discovered_resources SET status = ?, ultima_tentativa = ? WHERE url = ?",
                [status, now, url],
            )

    def set_wayback_snapshot(self, url: str, wayback_snapshot: str) -> None:
        """Registra um snapshot Wayback conhecido sem mexer em status/tentativa.

        Usado pelo Save Page Now assíncrono da colheita (ADR-0016): o snapshot
        chega depois da captura, quando o recurso já foi marcado.
        """
        self.connect().execute(
            "UPDATE discovered_resources SET wayback_snapshot = ? WHERE url = ?",
            [wayback_snapshot, url],
        )

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
            columns = [desc[0] for desc in (conn.description or [])]
            return dict(zip(columns, result))
        return None

    def get_leis_pending_ocr(
        self, ente: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        conn = self.connect()
        query = (
            "SELECT * FROM leis WHERE (texto_completo IS NULL OR texto_completo = '')"
        )
        params: list[str | int] = []
        if ente:
            query += " AND ente = ?"
            params.append(ente)
        query += " LIMIT ?"
        params.append(limit)
        results = conn.execute(query, params).fetchall()
        columns = [desc[0] for desc in (conn.description or [])]
        return [dict(zip(columns, row)) for row in results]

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
            SELECT id, titulo, ano, data_ato, tipo_lei, ente
            FROM leis
            WHERE {where_sql}
            ORDER BY data_ato DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        columns = [desc[0] for desc in (conn.description or [])]
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
