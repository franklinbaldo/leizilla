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
from leizilla.parser import fetch_html
from leizilla.publisher import InternetArchivePublisher
from leizilla.storage import DuckDBStorage

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


def harvest_pending_resources(
    storage: DuckDBStorage,
    publisher: InternetArchivePublisher,
    limit: int = 100,
    ente: Optional[str] = None,
) -> Dict[str, Any]:
    """Processa recursos pendentes da tabela discovered_resources.

    Faz download (preferencialmente de snapshot Wayback), upload pro IA,
    e insere/atualiza o status no banco de dados.
    Se `ente` for fornecido, processa apenas recursos desse ente.
    """
    pending = storage.get_pending_resources(limit=limit, ente=ente)
    stats = {"success": 0, "failed": 0, "robots-blocked": 0}
    rate_limiter = make_rate_limiter()

    for res in pending:
        url = res["url"]
        ente = res["ente"]
        fonte = res["fonte"]
        tipo = res["tipo_documento"]
        chave = res["chave"]
        wb_url = res["wayback_snapshot"]

        # Robots check
        if not robots.is_allowed(url):
            storage.update_resource_status(url, "robots-blocked")
            stats["robots-blocked"] += 1
            continue

        # Se não temos snapshot pré-descoberto, tenta Wayback Machine
        if not wb_url:
            wb_url = wayback.check_available(url)

        pdf_bytes = None
        fetched_from = "source-fallback"

        if wb_url:
            pdf_bytes = wayback.fetch_bytes(wb_url)
            fetched_from = "wayback"

        if pdf_bytes is None:
            # Fallback direto com rate-limit
            rate_limiter(url)
            pdf_bytes = wayback.fetch_bytes(url)
            fetched_from = "source-fallback"
            wb_url = None

        if pdf_bytes is None:
            storage.update_resource_status(url, "failed")
            stats["failed"] += 1
            continue

        # Salva em arquivo temporário para upload
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = Path(f.name)

        lei_data = {
            "id": f"{ente}-{fonte}-{chave}",
            "ente": ente,
            "fonte": fonte,
            "chave": chave,
            "titulo": f"{tipo.upper()} {chave} ({ente.upper()})",
        }

        try:
            result = publisher.upload_raw(
                tmp_path,
                lei_data,
                pdf_bytes,
                fetched_from=fetched_from,
                wayback_url=wb_url,
            )
            if result.get("success"):
                storage.update_resource_status(
                    url, "downloaded", wayback_snapshot=wb_url
                )
                # Salva na tabela principal 'leis'
                lei_record = {
                    "id": f"{ente}-{fonte}-{chave}",
                    "titulo": lei_data["titulo"],
                    "numero": chave.split("-")[-1] if "-" in chave else chave,
                    "ente": ente,
                    "tipo_lei": tipo,
                    "url_original": url,
                    "url_pdf_ia": result.get("ia_url"),
                }
                storage.insert_lei(lei_record)
                stats["success"] += 1
            else:
                storage.update_resource_status(url, "failed")
                stats["failed"] += 1
        except Exception:
            storage.update_resource_status(url, "failed")
            stats["failed"] += 1
        finally:
            tmp_path.unlink(missing_ok=True)

    return stats
