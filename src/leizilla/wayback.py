"""Cliente Wayback Machine — fetch via snapshot com fallback direto (ADR-0004).

Princípio #9: dispara Wayback save + fetch do snapshot. Fail-open para download
direto se Wayback falhar.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Set

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


def save_page_spn2(
    url: str,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout: int = 60,
) -> bool:
    """Submete URL ao SPN2 da Wayback Machine via POST com auth IA opcional.

    Com auth: maior rate limit (100+ req/min). Sem auth: cai no SPN1 básico.
    Retorna True se aceito (200/302). Fail-open.
    """
    if access_key and secret_key:
        # SPN2 API com IA credentials
        data = urllib.parse.urlencode({"url": url}).encode()
        req = urllib.request.Request(
            "https://web.archive.org/save/",
            data=data,
            method="POST",
        )
        req.add_header("User-Agent", _USER_AGENT)
        req.add_header("Authorization", f"LOW {access_key}:{secret_key}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    else:
        save_url = _SAVE_URL_TMPL.format(urllib.parse.quote(url, safe=":/"))
        req = urllib.request.Request(save_url)
        req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 302)
    except Exception:
        return False


def fetch_cdx_archived_urls(prefix: str, timeout: int = 90) -> Set[str]:
    """Retorna conjunto de URLs originais com status=200 no CDX para o prefixo dado."""
    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(prefix)}&matchType=prefix&output=json&fl=original,statuscode"
    )
    req = urllib.request.Request(cdx_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return set()
    if not data or len(data) <= 1:
        return set()
    # data[0] = cabeçalho ["original","statuscode"], data[1:] = registros
    return {row[0] for row in data[1:] if row[1] == "200"}


def fetch_bytes(url: str, timeout: int = 60) -> Optional[bytes]:
    """Baixa conteúdo de um URL (Wayback ou direto) e retorna bytes. None em falha."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return bytes(resp.read())
    except Exception:
        return None
