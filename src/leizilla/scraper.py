"""Pipeline de scraping: robots → wayback save/fetch → upload_raw (ADR-0004, ADR-0005).

Princípio #9: Wayback como caminho primário; fallback direto se Wayback falhar.
Princípio #10: robots.txt é permanente (sem retry em URL bloqueada); rate-limit
               em fallback direto, por host (não global).
"""

import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from leizilla import robots, wayback
from leizilla.discovery import load_manifest
from leizilla.parser import fetch_html
from leizilla.publisher import InternetArchivePublisher
from leizilla.ratelimit import make_rate_limiter
from leizilla.storage import DuckDBStorage


def scrape_one(
    fonte_url: str,
    pdf_url: str,
    lei_data: Dict[str, Any],
    publisher: InternetArchivePublisher,
    rate_limiter: Optional[Callable[[str], None]] = None,
    index_cache: Optional[Dict[str, str]] = None,
    wayback_snapshot: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape um PDF: robots check → wayback save → fetch → upload_raw.

    Retorna dict com 'success' + ('ia_id', 'ia_url') ou ('reason') em falha.
    Robots bloqueado é permanente — caller NÃO deve re-tentar a mesma URL.
    rate_limiter recebe a URL do fallback para tracking por host.
    ``index_cache`` (acumulador por item do lote) repassa-se ao ``upload_raw``
    para evitar lost-update do index.csv entre uploads ao mesmo item de range.
    ``wayback_snapshot`` é um snapshot pré-descoberto (ex.: CDX) usado preferencialmente
    — preserva capturas http-keyed que ``check_available`` (scheme-sensitive) perderia
    na URL normalizada https; o timestamp da captura serve de chave de versão (ADR-0004).
    """
    if not robots.is_allowed(fonte_url):
        return {"success": False, "reason": "robots-blocked", "url": fonte_url}
    if not robots.is_allowed(pdf_url):
        return {"success": False, "reason": "robots-blocked", "url": pdf_url}

    # Wayback save do índice/fonte — fire-and-forget; exceções swallowadas para que
    # falhas de rede não abortem fetch+upload. A captura do PDF em si é feita por
    # ensure_archived abaixo (que lê o snapshot da resposta do save).
    try:
        wayback.save_page(fonte_url)
    except Exception:
        pass

    # Resolução do snapshot com proveniência: um snapshot pré-descoberto (CDX) tem
    # prioridade; senão ensure_archived (SPN-first, dual-scheme, lê a resposta do save —
    # não a re-consulta imediata que o SPN assíncrono não satisfaz). Vale também para o
    # caminho sequencial/não-arquivado da CLI, não só para itens já no CDX.
    wb_url: Optional[str]
    if wayback_snapshot:
        wb_url = wayback_snapshot
    else:
        snap = wayback.ensure_archived(pdf_url)
        wb_url = snap[0] if snap is not None else None
    fetched_from: str
    pdf_bytes: Optional[bytes]

    if wb_url:
        pdf_bytes = wayback.fetch_bytes(wb_url)
        fetched_from = "wayback"
        # Wayback pode retornar HTML de erro para snapshots de redirect — fallback direto.
        if pdf_bytes is not None and pdf_bytes[:4] != b"%PDF":
            pdf_bytes = None
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

    if pdf_bytes[:4] != b"%PDF":
        print(
            f"[WARN] not a valid PDF for {lei_data.get('chave')} ({pdf_url}): header={pdf_bytes[:32]!r}",
            file=sys.stderr,
        )
        return {"success": False, "reason": "not-pdf", "url": pdf_url}

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
            index_cache=index_cache,
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
    index_cache: Optional[Dict[str, str]] = None,
    wayback_snapshot: Optional[str] = None,
) -> dict:
    """Scrape de uma página HTML: robots → wayback save → fetch → upload_raw_html.

    Para fontes sem PDF (ex: Planalto federal) que servem HTML compilado vigente.
    Retorna dict com 'success' + ('ia_id', 'ia_url') ou ('reason') em falha.
    Robots bloqueado é permanente — caller NÃO deve re-tentar a mesma URL.
    ``index_cache`` (acumulador por item do lote) repassa-se ao ``upload_raw_html``.
    ``wayback_snapshot`` é um snapshot pré-descoberto (ex.: PlanaltoDiscovery via
    ``closest_snapshot``, sem limite de idade) usado preferencialmente — sem ele,
    esta função caía em ``check_available`` (exige captura < 24h), quase sempre
    ``None`` para páginas arquivadas há mais tempo, forçando um fallback direto
    a hosts que bloqueiam requisições de runners do GitHub Actions (issue #262).
    """
    if not robots.is_allowed(fonte_url):
        return {"success": False, "reason": "robots-blocked", "url": fonte_url}

    try:
        wayback.save_page(fonte_url)
    except Exception:
        pass

    # Snapshot pré-descoberto (qualquer idade) tem prioridade; senão, tenta um
    # snapshot recente via check_available (exige < 24h).
    wb_url = wayback_snapshot or wayback.check_available(fonte_url)
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
            index_cache=index_cache,
        )
    except Exception as exc:
        return {"success": False, "reason": "upload-failed", "error": str(exc)}


def _resolve_tipo_ingestion(
    ente: str, fonte: str, manifest_cache: Dict[str, Dict[str, Any]]
) -> str:
    """Lê `tipo_ingestion` do manifesto de `ente`/`fonte` (default "pdf").

    Issue #248: `discovered_resources` não carrega `tipo_ingestion` (é metadado
    do manifesto, não do recurso descoberto), então `harvest_pending_resources`
    precisa reconsultar o manifesto por linha. `manifest_cache` evita reler o
    JSON do disco a cada recurso do mesmo ente dentro do mesmo batch.
    Fail-open: manifesto ausente/malformado ou fonte não declarada nele
    preserva o comportamento pré-existente (caminho PDF).
    """
    if ente not in manifest_cache:
        try:
            manifest_cache[ente] = load_manifest(ente)
        except (FileNotFoundError, ValueError):
            manifest_cache[ente] = {}
    fontes_cfg = manifest_cache[ente].get("fontes", {})
    fonte_cfg = fontes_cfg.get(fonte, {})
    tipo_ingestion = fonte_cfg.get("tipo_ingestion", "pdf")
    return str(tipo_ingestion)


# make_rate_limiter moved to leizilla.ratelimit (re-imported above) so
# publisher.py can reuse it for IA upload pacing without an import cycle
# (this module already imports InternetArchivePublisher from publisher.py).


def harvest_pending_resources(
    storage: DuckDBStorage,
    publisher: InternetArchivePublisher,
    limit: int = 100,
    ente: Optional[str] = None,
    tipo: Optional[str] = None,
) -> Dict[str, Any]:
    """Processa recursos pendentes da tabela discovered_resources.

    Faz download (preferencialmente de snapshot Wayback), upload pro IA,
    e insere/atualiza o status no banco de dados.
    Se `ente` for fornecido, processa apenas recursos desse ente.
    Se `tipo` for fornecido, processa apenas recursos desse tipo de documento.
    """
    pending = storage.get_pending_resources(limit=limit, ente=ente, tipo=tipo)
    stats: Dict[str, Any] = {
        "success": 0,
        "failed": 0,
        "robots-blocked": 0,
        "items": [],
    }
    rate_limiter = make_rate_limiter()
    # Índice acumulado por item de range neste lote: vários recursos do mesmo
    # (ente, fonte, tipo) caem no mesmo item; sem isto cada upload releria do IA
    # (sem read-after-write) e sobrescreveria a linha do upload anterior.
    index_cache: Dict[str, str] = {}
    manifest_cache: Dict[str, Dict[str, Any]] = {}

    for res in pending:
        url = res["url"]
        ente = res["ente"]
        fonte = res["fonte"]
        tipo = res["tipo_documento"]
        chave = res["chave"]
        wb_url = res["wayback_snapshot"]

        # Fontes HTML (ex.: federal/planalto) não têm bytes %PDF para validar —
        # despacham para scrape_one_html em vez do caminho PDF abaixo (#248).
        if _resolve_tipo_ingestion(ente, fonte, manifest_cache) == "html":
            lei_data_html = {
                "id": f"{ente}-{fonte}-{chave}",
                "ente": ente,
                "fonte": fonte,
                "chave": chave,
                "titulo": f"{tipo.upper()} {chave} ({ente.upper()})",
                "url_original": url,
            }
            html_result = scrape_one_html(
                url,
                lei_data_html,
                publisher,
                rate_limiter=rate_limiter,
                index_cache=index_cache,
                wayback_snapshot=wb_url,
            )
            if not html_result.get("success"):
                reason = html_result.get("reason", "fetch-failed")
                if reason == "robots-blocked":
                    # Permanente (princípio #10): nunca re-selecionado por
                    # get_pending_resources() já que seu status deixa de ser
                    # 'pending'.
                    storage.update_resource_status(url, "robots-blocked")
                    stats["robots-blocked"] += 1
                    item_status = "robots-blocked"
                else:
                    # scrape_one_html não distingue falha permanente de
                    # transiente (diferente de fetch_bytes_detailed no caminho
                    # PDF) — fica 'pending' para ser re-tentado (#121).
                    storage.update_resource_status(url, "pending")
                    stats["failed"] += 1
                    item_status = "failed"
                stats["items"].append(
                    {"status": item_status, "chave": chave, "reason": reason}
                )
                continue

            storage.update_resource_status(url, "downloaded")
            storage.insert_lei(
                {
                    "id": lei_data_html["id"],
                    "titulo": lei_data_html["titulo"],
                    "numero": chave.split("-")[-1] if "-" in chave else chave,
                    "ente": ente,
                    "tipo_lei": tipo,
                    "url_original": url,
                    "url_pdf_ia": html_result.get("ia_url"),
                }
            )
            stats["success"] += 1
            stats["items"].append(
                {
                    "status": "ok",
                    "chave": chave,
                    "ia_id": html_result.get("ia_id"),
                    "ia_url": html_result.get("ia_url"),
                }
            )
            continue

        # Robots check
        if not robots.is_allowed(url):
            storage.update_resource_status(url, "robots-blocked")
            stats["robots-blocked"] += 1
            stats["items"].append(
                {"status": "robots-blocked", "chave": chave, "reason": "robots-blocked"}
            )
            continue

        # Resolve via Wayback com proveniência: SPN-first, reusa QUALQUER captura
        # existente (ensure_archived). O timestamp do snapshot é a chave de versão
        # imutável (ADR-0004, docs/ditel-ingestion.md) — preservado explicitamente, não
        # descartado: vem do par (url, ts) quando resolvido agora, ou é extraído da URL
        # do snapshot pré-descoberto no ledger.
        wb_ts: Optional[str] = wayback.snapshot_timestamp(wb_url) if wb_url else None
        if not wb_url:
            snap = wayback.ensure_archived(url)
            if snap is not None:
                wb_url, wb_ts = snap

        pdf_bytes = None
        fetched_from = "source-fallback"
        # Só uma falha CONFIRMADA (404/410 no fetch direto) é permanente; qualquer
        # outra (429/5xx esgotado, timeout, erro de rede) é transitória e não deve
        # virar 'failed' terminal — get_pending_resources() só re-seleciona
        # status='pending', então 'failed' nunca mais é reprocessado (#121).
        permanent_failure = False

        if wb_url:
            pdf_bytes = wayback.fetch_bytes(wb_url)
            fetched_from = "wayback"
            # Wayback pode retornar uma página HTML de erro para snapshots que
            # capturaram um redirect/erro (status 200 no CDX mas conteúdo HTML).
            # Trata como fetch falho para acionar o fallback direto.
            if pdf_bytes is not None and pdf_bytes[:4] != b"%PDF":
                pdf_bytes = None

        if pdf_bytes is None:
            # Fallback direto com rate-limit; retry/backoff em 429/5xx já
            # acontece dentro de fetch_bytes_detailed.
            rate_limiter(url)
            pdf_bytes, permanent_failure = wayback.fetch_bytes_detailed(url)
            fetched_from = "source-fallback"
            wb_url = None
            wb_ts = None

        if pdf_bytes is None:
            print(f"[WARN] fetch returned None for {chave} ({url})", file=sys.stderr)
            status = "failed" if permanent_failure else "pending"
            storage.update_resource_status(url, status)
            stats["failed"] += 1
            stats["items"].append(
                {
                    "status": "failed",
                    "chave": chave,
                    "reason": "fetch-failed"
                    if permanent_failure
                    else "fetch-failed-transient",
                }
            )
            continue

        # Validate PDF magic bytes — source may serve HTML error pages with .pdf URLs
        if not pdf_bytes[:4] == b"%PDF":
            print(
                f"[WARN] not a valid PDF for {chave} ({url}): "
                f"header={pdf_bytes[:32]!r}",
                file=sys.stderr,
            )
            storage.update_resource_status(url, "not-pdf")
            stats["failed"] += 1
            stats["items"].append(
                {"status": "failed", "chave": chave, "reason": "not-pdf"}
            )
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
            "url_original": url,  # proveniência: mapeia o arquivo → fonte (ADR-0010)
            # chave de versão de proveniência (ADR-0004): o instante da captura Wayback
            # que materializa "a norma como estava" naquela data.
            "wayback_timestamp": wb_ts,
        }

        try:
            result = publisher.upload_raw(
                tmp_path,
                lei_data,
                pdf_bytes,
                fetched_from=fetched_from,
                wayback_url=wb_url,
                index_cache=index_cache,
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
                stats["items"].append(
                    {
                        "status": "ok",
                        "chave": chave,
                        "ia_id": result.get("ia_id"),
                        "ia_url": result.get("ia_url"),
                    }
                )
            else:
                print(
                    f"[WARN] upload failed for {chave}: {result.get('error', '?')}",
                    file=sys.stderr,
                )
                storage.update_resource_status(url, "failed")
                stats["failed"] += 1
                stats["items"].append(
                    {"status": "failed", "chave": chave, "reason": "upload-failed"}
                )
        except Exception as exc:
            print(
                f"[ERROR] exception for {chave}: {exc}",
                file=sys.stderr,
            )
            storage.update_resource_status(url, "failed")
            stats["failed"] += 1
            stats["items"].append(
                {"status": "failed", "chave": chave, "reason": f"exception: {exc}"}
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    return stats
