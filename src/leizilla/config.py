"""Configuração centralizada do Leizilla."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load workspace-level .env first (lower priority), then project .env (higher priority)
load_dotenv(PROJECT_ROOT.parent / ".env")
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
TEMP_DIR = DATA_DIR / "temp"

DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", str(DATA_DIR / "leizilla.duckdb")))

# Suporta IAS3_ACCESS_KEY (nome no workspace .env) e IA_ACCESS_KEY (alias)
IA_ACCESS_KEY: Optional[str] = os.getenv("IA_ACCESS_KEY") or os.getenv("IAS3_ACCESS_KEY")
IA_SECRET_KEY: Optional[str] = os.getenv("IA_SECRET_KEY") or os.getenv("IAS3_SECRET_KEY")

# LLM provider keys — LiteLLM reads these from env automatically
ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")

# Default LiteLLM model — override via LITELLM_MODEL env var
LITELLM_MODEL: str = os.getenv("LITELLM_MODEL", "gemini/gemini-2.5-flash")

CRAWLER_DELAY = int(os.getenv("CRAWLER_DELAY", "2000"))
CRAWLER_RETRIES = int(os.getenv("CRAWLER_RETRIES", "3"))
CRAWLER_TIMEOUT = int(os.getenv("CRAWLER_TIMEOUT", "30000"))

DATA_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
