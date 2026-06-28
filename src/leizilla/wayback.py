"""Cliente Wayback Machine — fetch via snapshot com fallback direto (ADR-0004).

Princípio #9: dispara Wayback save + fetch do snapshot. Fail-open para download
direto se Wayback falhar.
"""

import json
import re
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

# A Wayback snapshot URL embeds its capture timestamp: …/web/<YYYYMMDDhhmmss>/<orig>.
_SNAPSHOT_TS_RE = re.compile(r"/web/(\d{14})(?:[a-z_]*)?/")


def snapshot_timestamp(snapshot_url: str) -> Optional[str]:
    """Extrai o timestamp ``YYYYMMDDHHMMSS`` de uma URL de snapshot Wayback, ou ``None``.

    Permite recuperar a chave de versão de proveniência quando só se tem a URL do snapshot
    (ex.: pré-descoberta no ledger ``discovered_resources``), sem nova consulta à API.
    """
    m = _SNAPSHOT_TS_RE.search(snapshot_url or "")
    return m.group(1) if m else None


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


def _flip_scheme(url: str) -> Optional[str]:
    """http↔https variant of ``url`` (or ``None`` if it has no http(s) scheme)."""
    if url.startswith("https://"):
        return "http://" + url[len("https://") :]
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return None


def _query_available(url: str) -> Optional[Tuple[str, str]]:
    """One availability-API call → ``(snapshot_url, timestamp)`` for a 200 closest, or None."""
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


def closest_snapshot(url: str) -> Optional[Tuple[str, str]]:
    """Retorna ``(snapshot_url, timestamp)`` da captura 200 mais próxima — **qualquer idade**.

    Diferente de :func:`check_available` (que exige um snapshot fresco, < 24 h), serve à
    **proveniência**: reusa uma captura já existente (mesmo antiga) como chave de versão
    imutável (ADR-0004). O ``timestamp`` é ``YYYYMMDDHHMMSS``. ``None`` se não há captura.

    A API de disponibilidade é **sensível ao esquema** (http vs https são chaves distintas);
    as capturas históricas da DITEL são chaveadas em ``http`` enquanto o download ao vivo
    exige ``https`` (WAF). Por isso consultamos **ambos os esquemas** e reusamos a primeira
    captura 200 encontrada — senão perderíamos os snapshots históricos (Codex P1).
    """
    for candidate in (url, _flip_scheme(url)):
        if candidate:
            found = _query_available(candidate)
            if found is not None:
                return found
    return None


def save_and_locate(url: str, timeout: int = 90) -> Optional[Tuple[str, str]]:
    """Dispara Save Page Now e devolve ``(snapshot_url, timestamp)`` da captura recém-feita.

    Save Page Now **expõe o snapshot de forma assíncrona** — uma re-consulta imediata à API
    de disponibilidade quase sempre retorna ``None`` (Codex P1). Em vez de poll, lemos a
    própria resposta do SPN: o snapshot recém-criado aparece no header ``Content-Location``
    (``/web/<ts>/<orig>``) ou na URL final após o redirect. ``None`` se o save falhar ou não
    expuser um snapshot (fail-open).
    """
    save_url = _SAVE_URL_TMPL.format(urllib.parse.quote(url, safe=":/"))
    req = urllib.request.Request(save_url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_location = resp.headers.get("Content-Location", "") or ""
            final_url = resp.geturl() or ""
    except Exception:
        return None

    for candidate in (content_location, final_url):
        ts = snapshot_timestamp(candidate)
        if ts:
            snap_url = (
                candidate
                if candidate.startswith("http")
                else f"https://web.archive.org{candidate}"
            )
            return snap_url, ts
    return None


def ensure_archived(url: str, timeout: int = 90) -> Optional[Tuple[str, str]]:
    """Garante uma captura Wayback e devolve ``(snapshot_url, timestamp)``, ou ``None``.

    Política **SPN-first, reusa qualquer snapshot** (decisão de proveniência da DITEL,
    docs/ditel-ingestion.md):
    1. reusa uma captura existente (qualquer idade, **ambos os esquemas**) sem re-arquivar;
    2. senão, dispara Save Page Now e lê o snapshot **da resposta do save**
       (:func:`save_and_locate`) — sem depender de re-consulta imediata, que o SPN
       assíncrono não satisfaz (Codex P1);
    3. último recurso, re-consulta a disponibilidade.
    Fail-open: ``None`` → o chamador cai no fetch direto (princípio #9).
    """
    existing = closest_snapshot(url)
    if existing is not None:
        return existing
    located = save_and_locate(url, timeout=timeout)
    if located is not None:
        return located
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


def save_page_spn2(
    url: str,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout: int = 60,
    retries: int = 3,
) -> Optional[str]:
    """Submete URL ao SPN2 via POST com auth IA opcional, usando requests (sem SSL bug no Windows).

    Com auth (Authorization: LOW key:secret): rate limit maior. Sem auth: SPN1 básico.
    Retry exponencial em falhas de rede ou 5xx/429. Fail-open.
    Retorna a URL do snapshot arquivado (ou a página de histórico) em caso de sucesso, ou None.
    """
    import time

    import requests

    headers = {"User-Agent": _USER_AGENT}
    if access_key and secret_key:
        headers["Authorization"] = f"LOW {access_key}:{secret_key}"

    for attempt in range(retries):
        try:
            if access_key and secret_key:
                resp = requests.post(
                    "https://web.archive.org/save/",
                    data={"url": url},
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                )
            else:
                save_url = _SAVE_URL_TMPL.format(urllib.parse.quote(url, safe=":/"))
                resp = requests.get(
                    save_url, headers=headers, timeout=timeout, allow_redirects=True
                )
            if resp.status_code in (200, 302):
                content_location = resp.headers.get("Content-Location", "") or ""
                final_url = resp.url or ""
                for candidate in (content_location, final_url):
                    ts = snapshot_timestamp(candidate)
                    if ts:
                        if candidate.startswith("http"):
                            return candidate
                        return f"https://web.archive.org{candidate}"
                # Fallback: link para a página de histórico de capturas da URL
                return f"https://web.archive.org/web/*/{url}"
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2**attempt * 5)
                continue
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2**attempt * 5)
                continue
    return None


def fetch_cdx_archived_urls(prefix: str, timeout: int = 90) -> "set[str]":
    """Retorna conjunto de URLs originais com status 200/301/302 no CDX para o prefixo dado."""
    import requests

    cdx_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={urllib.parse.quote(prefix)}&matchType=prefix&output=json&fl=original,statuscode"
    )
    try:
        resp = requests.get(
            cdx_url, headers={"User-Agent": _USER_AGENT}, timeout=timeout
        )
        data = resp.json()
    except Exception:
        return set()
    if not data or len(data) <= 1:
        return set()
    # Inclui 301/302: URLs capturadas como redirecionamento (http→https) já estão no Wayback
    return {row[0] for row in data[1:] if row[1] in ("200", "301", "302")}


def to_raw_url(url: str) -> str:
    """Garante que a URL do Wayback aponta para a versão crua (raw) usando o modificador 'id_'.

    Se for uma URL do Wayback, insere ou substitui o modificador após o timestamp de 14 dígitos.
    Exemplo: .../web/20241208215859/http://... -> .../web/20241208215859id_/http://...
    """
    if "web.archive.org/web/" in url:
        return re.sub(r"/web/(\d{14})(?:[a-zA-Z_]*)?/", r"/web/\1id_/", url)
    return url


def fetch_bytes(url: str, timeout: int = 60) -> Optional[bytes]:
    """Baixa conteúdo de um URL (Wayback ou direto) e retorna bytes. None em falha."""
    url = to_raw_url(url)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        import ssl

        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return bytes(resp.read())
    except Exception:
        return None
