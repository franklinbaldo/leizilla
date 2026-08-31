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
    db_path = tmp_path / "legacy.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE leis (
            id VARCHAR PRIMARY KEY,
            titulo TEXT NOT NULL,
            data_publicacao DATE,
            ente VARCHAR NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO leis VALUES (?, ?, ?, ?)",
        ["ro-lei-123", "Lei 123", datetime.date(2024, 5, 10), "ro"],
    )
    conn.close()

    db = storage.DuckDBStorage(db_path)
    try:
        migrated = db.connect()
        columns = {
            row[1]
            for row in migrated.execute("PRAGMA table_info('leis')").fetchall()
        }
        assert "data_ato" in columns
        assert "data_publicacao" not in columns
        assert migrated.execute(
            "SELECT data_ato FROM leis WHERE id = 'ro-lei-123'"
        ).fetchone() == (datetime.date(2024, 5, 10),)
    finally:
        db.close()
