"""Cliente Wayback Machine — fetch via snapshot com fallback direto (ADR-0004).

Princípio #9: dispara Wayback save + fetch do snapshot. Fail-open para download
direto se Wayback falhar.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Tuple

_AVAILABILITY_API = "https://archive.org/wayback/available"
_SAVE_URL_TMPL = "https://web.archive.org/save/{}"
_USER_AGENT = (
    "leizilla-crawler/0.1 (legal-indexer; https://github.com/franklinbaldo/leizilla)"
)
_MAX_AGE_SECONDS = 24 * 3600


def check_available(url: str, max_age_seconds: int = _MAX_AGE_SECONDS) -> Optional[str]:
    """Retorna URL do snapshot Wayback mais recente se fresco (< max_age_seconds).

    None se não existe snapshot, se expirou, ou se a API falhar (fail-open).
    """
    try:
        api_url = f"{_AVAILABILITY_API}?url={urllib.parse.quote(url, safe='')}"
        req = urllib.request.Request(api_url)
        req.add_header("User-Agent", _USER_AGENT)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    snapshot = data.get("archived_snapshots", {}).get("closest", {})
    if not snapshot or snapshot.get("status") != "200":
        return None

    timestamp_str: str = snapshot.get("timestamp", "")
    if not timestamp_str:
        return None

    try:
        snapshot_dt = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        age = (datetime.now(tz=timezone.utc) - snapshot_dt).total_seconds()
        if age <= max_age_seconds:
            return str(snapshot.get("url", ""))
    except ValueError:
        pass
    return None


def closest_snapshot(url: str) -> Optional[Tuple[str, str]]:
    """Retorna ``(snapshot_url, timestamp)`` da captura 200 mais próxima — **qualquer idade**.

    Diferente de :func:`check_available` (que exige um snapshot fresco, < 24 h), serve à
    **proveniência**: reusa uma captura já existente (mesmo antiga) como chave de versão
    imutável (ADR-0004). O ``timestamp`` é a string ``YYYYMMDDHHMMSS`` do Wayback. Retorna
    ``None`` se não há captura 200 ou a API falha (fail-open).
    """
    try:
        api_url = f"{_AVAILABILITY_API}?url={urllib.parse.quote(url, safe='')}"
        req = urllib.request.Request(api_url)
        req.add_header("User-Agent", _USER_AGENT)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    snapshot = data.get("archived_snapshots", {}).get("closest", {})
    if not snapshot or snapshot.get("status") != "200":
        return None
    snap_url = str(snapshot.get("url", ""))
    timestamp = str(snapshot.get("timestamp", ""))
    if not snap_url or not timestamp:
        return None
    return snap_url, timestamp


def ensure_archived(url: str, timeout: int = 60) -> Optional[Tuple[str, str]]:
    """Garante uma captura Wayback e devolve ``(snapshot_url, timestamp)``, ou ``None``.

    Política **SPN-first, reusa qualquer snapshot** (decisão de proveniência da DITEL,
    docs/ditel-ingestion.md): se já há captura, reusa-a (sem re-arquivar); senão, dispara
    Save Page Now e re-consulta. Fail-open: ``None`` se nada puder ser arquivado/encontrado
    — o chamador cai no fetch direto (princípio #9).
    """
    existing = closest_snapshot(url)
    if existing is not None:
        return existing
    save_page(url, timeout=timeout)
    return closest_snapshot(url)


def save_page(url: str, timeout: int = 60) -> bool:
    """Dispara Wayback save para url. Retorna True se aceito (200/302).

    Fail-open: retorna False sem exceção se Wayback não responder.
    """
    save_url = _SAVE_URL_TMPL.format(urllib.parse.quote(url, safe=":/"))
    req = urllib.request.Request(save_url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 302)
    except Exception:
        return False


def fetch_bytes(url: str, timeout: int = 60) -> Optional[bytes]:
    """Baixa conteúdo de um URL (Wayback ou direto) e retorna bytes. None em falha."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return bytes(resp.read())
    except Exception:
        return None
