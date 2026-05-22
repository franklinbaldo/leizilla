import logging
import os
from pathlib import Path
from datetime import datetime

from leizilla.publisher import InternetArchivePublisher
from leizilla.config import DUCKDB_PATH, IA_ACCESS_KEY, IA_SECRET_KEY
from leizilla.storage import storage as duckdb_storage

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration for database backup
DB_FILE_PATH = DUCKDB_PATH
IA_DB_COLLECTION = "leizilla-database-backups"
IA_DB_IDENTIFIER_PREFIX = "leizilla-duckdb-backup"

def backup_duckdb_to_ia():
    """
    Backs up the DuckDB database file to the Internet Archive.
    """
    logger.info(f"Starting DuckDB backup process for {DB_FILE_PATH}...")

    if not IA_ACCESS_KEY or not IA_SECRET_KEY:
        logger.error("Internet Archive API keys (IA_ACCESS_KEY, IA_SECRET_KEY) are not set.")
        logger.error("Cannot proceed with database backup.")
        return

    if not DB_FILE_PATH.exists():
        logger.error(f"Database file not found at {DB_FILE_PATH}. Cannot proceed with backup.")
        return

    publisher = InternetArchivePublisher()

    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    backup_metadata_for_publisher = {
        'titulo': f"Leizilla DuckDB Backup {timestamp}",
        'ente': "leizilla-system",
        'tipo_lei': "database-backup",
        'ano': datetime.now().year,
        'numero': timestamp,
    }

    logger.info(f"Preparing to upload {DB_FILE_PATH.name} to Internet Archive.")
    logger.info(f"Target IA Collection: {IA_DB_COLLECTION}")

    upload_result = publisher.upload_pdf(
        pdf_path=DB_FILE_PATH,
        lei_data=backup_metadata_for_publisher,
    )

    if upload_result.get('success'):
        logger.info(f"Successfully uploaded database backup {DB_FILE_PATH.name} to IA.")
        logger.info(f"IA URL: {upload_result.get('url')}")
    else:
        logger.error(f"Failed to upload database backup {DB_FILE_PATH.name} to IA.")
        logger.error(f"Error: {upload_result.get('error')}")

if __name__ == "__main__":
    # Note: DuckDB should ideally be closed or checkpointed before backup
    # for maximum safety, especially if there are concurrent writes.
    # For a GitHub Action that runs sequentially, this might be less of an issue
    # as the DB operations from the crawler script should be finished.
    # However, explicitly closing connections or checkpointing would be best practice.
    # For now, we assume the DB file is in a consistent state.

    try:
        logger.info(f"Attempting to connect to DuckDB at {DB_FILE_PATH} and perform checkpoint.")
        conn = duckdb_storage.connect()
        conn.execute("CHECKPOINT;")
        logger.info("DuckDB CHECKPOINT command executed.")
        duckdb_storage.close() # Closes the connection and flushes WAL
        logger.info("DuckDB connection closed, WAL flushed.")
    except Exception as e:
        logger.warning(f"Could not perform DuckDB checkpoint or close connection: {e}. Proceeding with backup anyway.")

    backup_duckdb_to_ia()
