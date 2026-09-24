"""Regression contract for issue #129: act date is not DOE publication evidence."""

import datetime

import duckdb

from leizilla import storage
from leizilla.etl import xml_to_rows


def test_urn_representative_date_is_exposed_as_data_ato() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2024-05-10;123">
  <dispositivo path="art-1">
    <versao><texto>Art. 1º Teste.</texto></versao>
  </dispositivo>
</lei>"""
    rows = xml_to_rows(xml, "leizilla-ro-lei-00123-2024", "ro")

    assert rows
    assert rows[0]["data_ato"] == datetime.date(2024, 5, 10)
    assert "data_publicacao" not in rows[0]


def test_legacy_duckdb_data_publicacao_migrates_losslessly(tmp_path) -> None:
    """A database created by the pre-#129 schema migrates in place without loss."""
    db_path = tmp_path / "legacy.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE leis (
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
            hash_conteudo VARCHAR,
            status VARCHAR DEFAULT 'ativo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO leis (id, titulo, numero, ano, data_publicacao, tipo_lei, ente)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "ro-lei-123",
            "Lei 123",
            "123",
            2024,
            datetime.date(2024, 5, 10),
            "lei",
            "ro",
        ],
    )
    conn.close()

    db = storage.DuckDBStorage(db_path)
    try:
        migrated = db.connect()
        columns = {
            row[1] for row in migrated.execute("PRAGMA table_info('leis')").fetchall()
        }
        assert "data_ato" in columns
        assert "data_publicacao" not in columns
        assert migrated.execute(
            "SELECT data_ato FROM leis WHERE id = 'ro-lei-123'"
        ).fetchone() == (datetime.date(2024, 5, 10),)
    finally:
        db.close()
