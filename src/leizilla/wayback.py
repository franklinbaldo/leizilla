"""Cliente Wayback Machine — fetch via snapshot com fallback direto (ADR-0004).

Princípio #9: dispara Wayback save + fetch do snapshot. Fail-open para download
direto se Wayback falhar.
"""

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

_AVAILABILITY_API = "https://archive.org/wayback/available"
_SAVE_URL_TMPL = "https://web.archive.org/save/{}"
_USER_AGENT = (
    "leizilla-crawler/0.1 (legal-indexer; https://github.com/franklinbaldo/leizilla)"
)
_MAX_AGE_SECONDS = 24 * 3600

# A Wayback snapshot URL embeds its capture timestamp: …/web/<YYYYMMDDhhmmss>/<orig>.
_SNAPSHOT_TS_RE = re.compile(r"/web/(\d{14})(?:[a-z_]*)?/")


def _is_retryable_status(status_code: int) -> bool:
    """True for HTTP statuses worth retrying with backoff: 429 (rate limit) or 5xx.

    Shared by every HTTP call in this module that retries — :func:`save_page_spn2`
    and :func:`fetch_bytes` — so the retry *policy* (which statuses are transient)
    lives in one place even though they use different HTTP clients (``requests``
    vs ``urllib``).
    """
    return status_code == 429 or status_code >= 500


def _backoff_delay(attempt: int, base_seconds: float = 5.0) -> float:
    """Exponential backoff delay for retry attempt ``attempt`` (0-indexed)."""
    return float(2**attempt) * base_seconds


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
            if _is_retryable_status(resp.status_code):
                time.sleep(_backoff_delay(attempt))
                continue
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(_backoff_delay(attempt))
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


def fetch_bytes_detailed(
    url: str, timeout: int = 60, retries: int = 3
) -> Tuple[Optional[bytes], bool]:
    """Baixa conteúdo de um URL (Wayback ou direto). ``(bytes, permanent_failure)``.

    Retry exponencial em 429/5xx (mirrors :func:`save_page_spn2` — issue #121: o
    caminho primário de fetch do harvest não tinha retry/inspeção de status,
    então um 429 virava ``failed`` terminal na primeira tentativa em vez de algo
    retryable).

    ``permanent_failure`` distingue um desfecho definitivo — 404/410 confirmado
    pelo servidor — de qualquer outra falha (429/5xx esgotado, timeout, erro de
    rede, DNS), que é transitória: o chamador deve manter o recurso
    retryable/re-enfileirável (``get_pending_resources`` só re-seleciona
    ``status = 'pending'`` — um estado ``failed`` nunca mais é reprocessado) em
    vez de gravar um estado terminal para algo que pode só precisar de uma nova
    tentativa mais tarde.
    """
    url = to_raw_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return bytes(resp.read()), False
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return None, True  # confirmado: recurso não existe mais
            if _is_retryable_status(exc.code) and attempt < retries - 1:
                time.sleep(_backoff_delay(attempt))
                continue
            return None, False  # outro 4xx (401/403/…): não confirmado, transitório
        except Exception:
            if attempt < retries - 1:
                time.sleep(_backoff_delay(attempt))
                continue
            return None, False  # timeout/rede esgotado: transitório
    return None, False


def fetch_bytes(url: str, timeout: int = 60, retries: int = 3) -> Optional[bytes]:
    """Baixa conteúdo de um URL (Wayback ou direto) e retorna bytes. None em falha.

    Retry exponencial em 429/5xx — ver :func:`fetch_bytes_detailed`, que também
    expõe se a falha foi permanente (404/410) ou transitória, para quem precisa
    decidir se o recurso deve continuar retryable.
    """
    content, _permanent = fetch_bytes_detailed(url, timeout=timeout, retries=retries)
    return content


def _background_save(
    url: str,
    access_key: Optional[str],
    secret_key: Optional[str],
    timeout: int,
) -> Optional[str]:
    """Um pedido de Save Page Now, sem retry: o que :class:`BackgroundSaver` executa.

    Ponto único de saída de rede do salvamento assíncrono (os testes o substituem).
    """
    return save_page_spn2(url, access_key, secret_key, timeout=timeout, retries=1)


class BackgroundSaver:
    """Pede Save Page Now fora do caminho crítico da colheita (ADR-0016).

    A colheita baixa o PDF direto da fonte e só **avisa** o Wayback; a captura do
    Wayback vira testemunha independente quando acontecer, sem segurar o upload.
    Uma única thread consome uma fila limitada:

    - **limitado**: fila cheia descarta o pedido (contado em ``dropped``) em vez de
      crescer ou de bloquear a colheita;
    - **educado**: cada pedido faz o robô do Wayback bater uma vez na fonte, então
      passa pelo ``source_limiter`` — o mesmo orçamento por host do fetch direto
      (ADR-0008) — além do intervalo próprio contra o Wayback (``min_interval``);
    - **fail-open**: erro de rede ou resposta inesperada só incrementa ``failed``.

    ``snapshots`` guarda apenas URLs de snapshot reais (com timestamp de captura);
    a página de histórico que ``save_page_spn2`` devolve como fallback não é
    proveniência e fica de fora.
    """

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        *,
        min_interval: float = 5.0,
        max_pending: int = 200,
        timeout: int = 60,
        source_limiter: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._min_interval = min_interval
        self._timeout = timeout
        self._source_limiter = source_limiter
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=max_pending)
        self._thread: Optional[threading.Thread] = None
        self._abort = threading.Event()
        self._closed = False
        self._lock = threading.Lock()
        self._last_save: Optional[float] = None
        self.snapshots: Dict[str, str] = {}
        self.stats: Dict[str, int] = {
            "requested": 0,
            "accepted": 0,
            "failed": 0,
            "dropped": 0,
        }

    def submit(self, url: str) -> bool:
        """Enfileira ``url`` sem bloquear. ``False`` se o pedido foi descartado."""
        with self._lock:
            if self._closed:
                self.stats["dropped"] += 1
                return False
            try:
                self._queue.put_nowait(url)
            except queue.Full:
                self.stats["dropped"] += 1
                return False
            self.stats["requested"] += 1
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="wayback-save", daemon=True
                )
                self._thread.start()
        return True

    def _run(self) -> None:
        while not self._abort.is_set():
            url = self._queue.get()
            if url is None:
                return
            if self._abort.is_set():
                self._count("dropped")
                return
            try:
                if self._source_limiter is not None:
                    self._source_limiter(url)
                if self._last_save is not None:
                    wait = self._min_interval - (time.monotonic() - self._last_save)
                    if wait > 0 and self._abort.wait(wait):
                        self._count("dropped")
                        return
                self._last_save = time.monotonic()
                result = _background_save(
                    url, self._access_key, self._secret_key, self._timeout
                )
            except Exception:
                result = None
            if result is None:
                self._count("failed")
                continue
            self._count("accepted")
            if snapshot_timestamp(result):
                with self._lock:
                    self.snapshots[url] = result

    def _count(self, key: str) -> None:
        with self._lock:
            self.stats[key] += 1

    def close(self, grace: float = 30.0) -> Dict[str, int]:
        """Para de aceitar pedidos, espera até ``grace`` s e devolve as contagens.

        O que ainda estiver na fila ao fim do prazo é abandonado e contado em
        ``dropped`` — a colheita nunca fica presa esperando o Wayback.
        """
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            thread.join(timeout=max(0.0, grace))
            if thread.is_alive():
                self._abort.set()
        abandoned = 0
        while True:
            try:
                if self._queue.get_nowait() is not None:
                    abandoned += 1
            except queue.Empty:
                break
        if thread is not None and thread.is_alive():
            # Acorda a thread (se estiver parada na fila vazia) para ela encerrar.
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        with self._lock:
            self.stats["dropped"] += abandoned
            return dict(self.stats)
