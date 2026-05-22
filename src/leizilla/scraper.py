"""Pipeline de scraping: robots → wayback save/fetch → upload_raw (ADR-0004, ADR-0005).

Princípio #9: Wayback como caminho primário; fallback direto se Wayback falhar.
Princípio #10: robots.txt é permanente (sem retry em URL bloqueada); rate-limit
               em fallback direto, por host (não global).
"""

import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from leizilla import robots, wayback
from leizilla.publisher import InternetArchivePublisher

_RATE_LIMIT_S = 1.0


def scrape_one(
    fonte_url: str,
    pdf_url: str,
    lei_data: Dict[str, Any],
    publisher: InternetArchivePublisher,
    rate_limiter: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Scrape um PDF: robots check → wayback save → fetch → upload_raw.

    Retorna dict com 'success' + ('ia_id', 'ia_url') ou ('reason') em falha.
    Robots bloqueado é permanente — caller NÃO deve re-tentar a mesma URL.
    rate_limiter recebe a URL do fallback para tracking por host.
    """
    if not robots.is_allowed(fonte_url):
        return {"success": False, "reason": "robots-blocked", "url": fonte_url}
    if not robots.is_allowed(pdf_url):
        return {"success": False, "reason": "robots-blocked", "url": pdf_url}

    # Wayback save — fire-and-forget; exceções swallowadas explicitamente
    # para que falhas de rede (DNS, timeout) não abortem o scrape
    # das URLs que importam (fetch + upload).
    try:
        wayback.save_page(fonte_url)
        wayback.save_page(pdf_url)
    except Exception:
        pass

    # Wayback fetch (primário)
    wb_url = wayback.check_available(pdf_url)
    fetched_from: str
    pdf_bytes: Optional[bytes]

    if wb_url:
        pdf_bytes = wayback.fetch_bytes(wb_url)
        fetched_from = "wayback"
    else:
        pdf_bytes = None
        wb_url = None

    if pdf_bytes is None:
        # Fallback direto com rate-limit por host (princípio #10)
        if rate_limiter is not None:
            rate_limiter(pdf_url)
        pdf_bytes = wayback.fetch_bytes(pdf_url)
        fetched_from = "source-fallback"
        wb_url = None

    if pdf_bytes is None:
        return {"success": False, "reason": "fetch-failed", "url": pdf_url}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = Path(f.name)

    try:
        return publisher.upload_raw(
            tmp_path,
            lei_data,
            pdf_bytes,
            fetched_from=fetched_from,
            wayback_url=wb_url,
        )
    except Exception as exc:
        return {"success": False, "reason": "upload-failed", "error": str(exc)}
    finally:
        tmp_path.unlink(missing_ok=True)


def scrape_one_html(
    fonte_url: str,
    lei_data: dict,
    publisher: InternetArchivePublisher,
    rate_limiter: Optional[Callable[[str], None]] = None,
) -> dict:
    """Scrape de uma página HTML: robots → wayback save → fetch → upload_raw_html.

    Para fontes sem PDF (ex: Planalto federal) que servem HTML compilado vigente.
    Retorna dict com 'success' + ('ia_id', 'ia_url') ou ('reason') em falha.
    Robots bloqueado é permanente — caller NÃO deve re-tentar a mesma URL.
    """
    from leizilla.parser import fetch_html

    if not robots.is_allowed(fonte_url):
        return {"success": False, "reason": "robots-blocked", "url": fonte_url}

    try:
        wayback.save_page(fonte_url)
    except Exception:
        pass

    # Tenta primeiro Wayback (snapshot recente)
    wb_url = wayback.check_available(fonte_url)
    fetched_from: str
    html_content: Optional[str]

    if wb_url:
        html_content = fetch_html(wb_url)
        fetched_from = "wayback"
    else:
        html_content = None
        wb_url = None

    if html_content is None:
        # Fallback direto com rate-limit por host (princípio #10)
        if rate_limiter is not None:
            rate_limiter(fonte_url)
        html_content = fetch_html(fonte_url)
        fetched_from = "source-fallback"
        wb_url = None

    if html_content is None:
        return {"success": False, "reason": "fetch-failed", "url": fonte_url}

    try:
        return publisher.upload_raw_html(
            html_content,
            lei_data,
            fetched_from=fetched_from,
            wayback_url=wb_url,
        )
    except Exception as exc:
        return {"success": False, "reason": "upload-failed", "error": str(exc)}


def make_rate_limiter(min_interval: float = _RATE_LIMIT_S) -> Callable[[str], None]:
    """Rate limiter por host: garante >= min_interval entre baterias diretas no mesmo host.

    Hosts diferentes não bloqueiam uns aos outros — permite scraping paralelo
    de múltiplas fontes (assembleia + casacivil + ...) sem serializar por fonte.
    """
    last: Dict[str, float] = {}

    def limiter(url: str) -> None:
        host = urlparse(url).hostname or ""
        elapsed = time.monotonic() - last.get(host, 0.0)
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        last[host] = time.monotonic()

    return limiter
