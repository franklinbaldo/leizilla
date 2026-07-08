"""Configuração centralizada do Leizilla."""

import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
TEMP_DIR = DATA_DIR / "temp"

DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", str(DATA_DIR / "leizilla.duckdb")))

IA_ACCESS_KEY: Optional[str] = os.getenv("IA_ACCESS_KEY") or os.getenv(
    "IAS3_ACCESS_KEY"
)
IA_SECRET_KEY: Optional[str] = os.getenv("IA_SECRET_KEY") or os.getenv(
    "IAS3_SECRET_KEY"
)
ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv(
    "GOOGLE_API_KEY"
)
LLM_MODEL: Optional[str] = os.getenv("LLM_MODEL")

CRAWLER_DELAY = int(os.getenv("CRAWLER_DELAY", "2000"))
CRAWLER_RETRIES = int(os.getenv("CRAWLER_RETRIES", "3"))
CRAWLER_TIMEOUT = int(os.getenv("CRAWLER_TIMEOUT", "30000"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
