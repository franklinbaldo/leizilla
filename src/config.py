"""
Configuração do Leizilla.

Centraliza configurações de ambiente, paths e constantes.
"""

import os
from pathlib import Path
from typing import Optional

# Paths do projeto
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TEMP_DIR = DATA_DIR / "temp"

# DuckDB
DUCKDB_PATH = DATA_DIR / "leizilla.duckdb"

# Internet Archive
IA_ACCESS_KEY: Optional[str] = os.getenv("IA_ACCESS_KEY")
IA_SECRET_KEY: Optional[str] = os.getenv("IA_SECRET_KEY")

# Crawler configuração
CRAWLER_DELAY = int(os.getenv("CRAWLER_DELAY", "2000"))  # ms
CRAWLER_RETRIES = int(os.getenv("CRAWLER_RETRIES", "3"))
CRAWLER_TIMEOUT = int(os.getenv("CRAWLER_TIMEOUT", "30000"))  # ms

# Garantir que diretórios existem
DATA_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# Diretório de Logs
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
