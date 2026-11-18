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

# Colheita em lote (ADR-0016): capturas por `ia upload` (um por item de range) e
# pedido assíncrono de Save Page Now. HARVEST_WAYBACK_SAVE=0 desliga o SPN.
HARVEST_BATCH_SIZE = max(1, int(os.getenv("HARVEST_BATCH_SIZE", "25")))
HARVEST_WAYBACK_SAVE = os.getenv("HARVEST_WAYBACK_SAVE", "1") not in ("0", "false", "")
# HARVEST_DERIVE=0 não pede o derive ao fim (os PDFs ficam no item sem OCR até um
# `ia tasks <item> --cmd derive.php`). HARVEST_MAX_SECONDS > 0 faz a colheita parar
# de baixar ao estourar o orçamento e encerrar com flush + derive, em vez de ser
# morta pelo teto do job com capturas no buffer.
HARVEST_DERIVE = os.getenv("HARVEST_DERIVE", "1") not in ("0", "false", "")
HARVEST_MAX_SECONDS = float(os.getenv("HARVEST_MAX_SECONDS", "0") or 0)
# Intervalo mínimo (s) entre batidas da colheita no mesmo host da fonte (ADR-0008:
# ~1 req/s). Com N jobs paralelos no mesmo host, use N x 1.0 para manter ~1 req/s no
# total (ADR-0016, adendo).
HARVEST_HOST_INTERVAL_S = max(
    0.1, float(os.getenv("HARVEST_HOST_INTERVAL_S", "1.0") or 1.0)
)

# Capturas baixadas e ainda não enviadas ao IA (ADR-0016, adendo 2026-11-18 (2)): o
# primeiro flush sai com HARVEST_FIRST_FLUSH capturas no total (testa a ração da conta
# gastando poucos downloads) e, depois, o item mais cheio sobe sempre que o total no
# buffer chega a HARVEST_MAX_UNFLUSHED, não importa como as capturas se espalhem.
HARVEST_FIRST_FLUSH = max(1, int(os.getenv("HARVEST_FIRST_FLUSH", "5")))
HARVEST_MAX_UNFLUSHED = max(1, int(os.getenv("HARVEST_MAX_UNFLUSHED", "100")))
# Capturas que sobraram de uma colheita encerrada cedo (ração da conta, prazo) ficam
# aqui para a próxima execução subir sem baixar da fonte de novo. Tetos: arquivos,
# bytes e idade. HARVEST_SPOOL_MAX_FILES=0 desliga.
HARVEST_SPOOL_DIR = Path(os.getenv("HARVEST_SPOOL_DIR", "") or str(DATA_DIR / "spool"))
HARVEST_SPOOL_MAX_FILES = max(0, int(os.getenv("HARVEST_SPOOL_MAX_FILES", "200")))
HARVEST_SPOOL_MAX_BYTES = max(
    0, int(os.getenv("HARVEST_SPOOL_MAX_BYTES", str(100 * 1024 * 1024)))
)
HARVEST_SPOOL_MAX_AGE_DAYS = max(1, int(os.getenv("HARVEST_SPOOL_MAX_AGE_DAYS", "7")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
