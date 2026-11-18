"""Reserva local de capturas baixadas e ainda não enviadas ao IA (ADR-0016, 2026-11-18).

Quando a colheita termina cedo (ração da conta no IA, prazo do job), as capturas que
estavam no buffer voltam à fila ``pending``. Sem esta reserva, a próxima execução
baixaria os mesmos arquivos da fonte do governo outra vez. Aqui elas ficam em disco
(``data/spool/``, guardado entre execuções por ``actions/cache``) e a próxima colheita
as usa no lugar do download.

Regras:

* endereçamento por conteúdo (ADR-0010): o arquivo se chama ``<sha256>.pdf``; o índice
  ``index.json`` mapeia ``url`` → sha256 + a proveniência da captura original
  (``fetched_from``, ``captured_at``, ``wayback_url``);
* todo arquivo é **revalidado** ao sair da reserva (existe, ``%PDF``, sha256 confere);
  o que falha é descartado e a colheita baixa da fonte como se a reserva não existisse;
* tetos: arquivos, bytes e idade (``config.HARVEST_SPOOL_*``). Acima do teto a captura
  simplesmente não é guardada (continua ``pending``, como hoje);
* nunca levanta por causa de disco/índice corrompido: reserva é otimização, não estado.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from leizilla import config

logger = logging.getLogger(__name__)

INDEX_NAME = "index.json"


class DownloadSpool:
    """Reserva de PDFs baixados, indexada por URL da fonte."""

    def __init__(
        self,
        root: Optional[Path] = None,
        max_files: Optional[int] = None,
        max_bytes: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> None:
        self.root = Path(root) if root is not None else config.HARVEST_SPOOL_DIR
        self.max_files = (
            config.HARVEST_SPOOL_MAX_FILES if max_files is None else max_files
        )
        self.max_bytes = (
            config.HARVEST_SPOOL_MAX_BYTES if max_bytes is None else max_bytes
        )
        self.max_age_s = (
            config.HARVEST_SPOOL_MAX_AGE_DAYS if max_age_days is None else max_age_days
        ) * 86400.0
        self.entries: Dict[str, Dict[str, Any]] = {}
        self.dirty = False
        self._load()

    @property
    def enabled(self) -> bool:
        return self.max_files > 0 and self.max_bytes > 0

    def _path(self, sha256: str) -> Path:
        return self.root / f"{sha256}.pdf"

    def _load(self) -> None:
        """Lê o índice, descartando o que expirou ou perdeu o arquivo."""
        index = self.root / INDEX_NAME
        try:
            raw = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        now = time.time()
        for url, entry in raw.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
                self.dirty = True
                continue
            stored_at = entry.get("stored_at")
            fresh = isinstance(stored_at, (int, float)) and (
                now - float(stored_at) <= self.max_age_s
            )
            if fresh and self._path(entry["sha256"]).is_file():
                self.entries[str(url)] = entry
            else:
                self.dirty = True
        self._collect_orphans()

    def _collect_orphans(self) -> None:
        """Apaga PDFs que nenhuma entrada referencia (restos de execuções antigas)."""
        wanted = {f"{e['sha256']}.pdf" for e in self.entries.values()}
        try:
            for path in self.root.glob("*.pdf"):
                if path.name not in wanted:
                    path.unlink(missing_ok=True)
        except OSError:
            logger.warning("spool: não consegui limpar órfãos em %s", self.root)

    def total_bytes(self) -> int:
        total = 0
        for entry in self.entries.values():
            try:
                total += self._path(entry["sha256"]).stat().st_size
            except OSError:
                continue
        return total

    def put(
        self,
        url: str,
        content: bytes,
        *,
        fetched_from: str,
        wayback_url: Optional[str],
        captured_at: str,
    ) -> bool:
        """Guarda uma captura. ``False`` se desligada, no teto ou se o disco falhar."""
        if not self.enabled or url in self.entries:
            return url in self.entries
        if len(self.entries) >= self.max_files:
            return False
        if self.total_bytes() + len(content) > self.max_bytes:
            return False
        sha = hashlib.sha256(content).hexdigest()
        path = self._path(sha)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(content)
            os.replace(tmp, path)
        except OSError:
            logger.warning("spool: falha ao gravar %s", path)
            return False
        self.entries[url] = {
            "sha256": sha,
            "stored_at": time.time(),
            "captured_at": captured_at,
            "fetched_from": fetched_from,
            "wayback_url": wayback_url,
        }
        self.dirty = True
        return True

    def get(self, url: str) -> Optional[tuple[bytes, Dict[str, Any]]]:
        """Bytes + proveniência de ``url``, **revalidados**; ``None`` se não servem."""
        entry = self.entries.get(url)
        if entry is None:
            return None
        try:
            content = self._path(entry["sha256"]).read_bytes()
        except OSError:
            content = b""
        if content[:4] != b"%PDF" or (
            hashlib.sha256(content).hexdigest() != entry["sha256"]
        ):
            logger.warning("spool: %s não passou na revalidação; descartado", url)
            self.discard(url)
            return None
        return content, entry

    def discard(self, url: str) -> None:
        """Remove a entrada (o PDF só se nenhuma outra URL aponta para o mesmo sha)."""
        entry = self.entries.pop(url, None)
        if entry is None:
            return
        self.dirty = True
        if not any(e["sha256"] == entry["sha256"] for e in self.entries.values()):
            self._path(entry["sha256"]).unlink(missing_ok=True)

    def save(self) -> None:
        """Grava o índice (sempre que a reserva existe, mesmo vazia: ver o workflow)."""
        if not self.enabled:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / (INDEX_NAME + ".tmp")
            tmp.write_text(
                json.dumps(self.entries, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, self.root / INDEX_NAME)
            self.dirty = False
        except OSError:
            logger.warning("spool: falha ao gravar o índice em %s", self.root)
