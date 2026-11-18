"""Leizilla CLI — interface de linha de comando."""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, cast

import typer
from typer import echo

app = typer.Typer(
    name="leizilla",
    help="O dinossauro que devora PDFs jurídicos e cospe dados abertos",
    add_completion=False,
)
dev_app = typer.Typer(name="dev", help="Comandos de desenvolvimento")
app.add_typer(dev_app, name="dev")


@app.command("discover")
def cmd_discover(
    ente: str = typer.Option("ro", help="Ente federativo (ro, sp, federal, ...)"),
    fonte: Optional[str] = typer.Option(
        None, help="Fonte específica do manifesto (None = todas as fontes)"
    ),
    tipo: Optional[str] = typer.Option(
        None,
        help=(
            "Tipo de documento a descobrir (lei, lc, decreto, ec, resolucao, "
            "portaria, decreto-lei, ...). None = todos os tipos da fonte. "
            "Escopa só as estratégias sequential/planalto (as únicas cujo "
            "tipo-alvo é determinável); índices/CDX amplos sempre rodam."
        ),
    ),
) -> None:
    """Descobrir leis nos portais oficiais usando manifestos."""
    alvo = f"{ente}/{fonte}" if fonte else ente
    if tipo:
        alvo += f" (tipo={tipo})"
    echo(f"Descobrindo leis para: {alvo}...")
    try:
        from leizilla.discovery import run_discovery
        from leizilla.storage import DuckDBStorage

        db = DuckDBStorage()
        added = run_discovery(ente, db, fonte=fonte, tipo=tipo)
        echo(f"Descoberta concluída. Adicionados/ignorados recursos: {added} total.")
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("reconcile")
def cmd_reconcile(
    ente: str = typer.Option("ro", help="Ente federativo"),
    fonte: Optional[str] = typer.Option(
        None, help="Fonte específica (None = todas as fontes do manifesto)"
    ),
) -> None:
    """Promove recursos da área de espera `_unidentified` para o item de range.

    Re-roda a descoberta com os extratores atuais (ADR-0011 §1, re-derivação por
    contexto), monta o mapa URL→(tipo, número) e promove os arquivos preservados
    cuja identidade agora é conhecida — sem re-baixar do portal de origem.
    """
    echo(f"Reconciliando área de espera para {ente}" + (f"/{fonte}" if fonte else ""))
    try:
        from leizilla.discovery import discover_resources
        from leizilla.ia_utils import parse_identity
        from leizilla.publisher import InternetArchivePublisher

        resources = discover_resources(ente, fonte)
        # Mapa de identidade por URL de origem, só para recursos agora identificáveis.
        identity_by_source: dict[str, tuple[str, int]] = {}
        fontes_seen: set[str] = set()
        for res in resources:
            fontes_seen.add(res["fonte"])
            ident = parse_identity(res.get("chave", ""))
            if ident is not None:
                identity_by_source[res["url"]] = ident

        pub = InternetArchivePublisher()
        total_promoted = 0
        total_remaining = 0
        failed_fontes: list[str] = []
        for f in sorted(fontes_seen):
            by_source = {
                r["url"]: identity_by_source[r["url"]]
                for r in resources
                if r["fonte"] == f and r["url"] in identity_by_source
            }
            result = pub.reconcile_unidentified(ente, f, by_source)
            if not result.get("success"):
                echo(f"  {f}: erro — {result.get('error')}")
                failed_fontes.append(f)
                continue
            total_promoted += result["promoted"]
            total_remaining += result["remaining"]
            echo(
                f"  {f}: {result['promoted']} promovidos, "
                f"{result['remaining']} ainda na espera"
            )
        echo(
            f"Reconciliação concluída: {total_promoted} promovidos, "
            f"{total_remaining} aguardando."
        )
        if failed_fontes:
            # Sai nonzero para a automação detectar a limpeza parcial (rows
            # promovidas podem seguir na espera).
            echo(f"Falha em: {', '.join(failed_fontes)}")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


def _echo_harvest_summary(stats: Dict[str, Any], partial: bool = False) -> None:
    """Resumo da colheita. ``partial`` = a colheita levantou antes de terminar."""
    echo(
        "Colheita parcial (levantou antes do fim):"
        if partial
        else "Colheita concluída:"
    )
    echo(f"  Sucesso: {stats.get('success', 0)}")
    echo(f"  Falhas: {stats.get('failed', 0)}")
    requeued = stats.get("requeued", 0)
    if requeued:
        # Limite da conta no IA ou prazo do job: o documento está bom, só não subiu.
        echo(
            f"  Devolvidas à fila (pending, não são falhas dos documentos): {requeued}"
        )
    echo(f"  Robots bloqueado: {stats.get('robots-blocked', 0)}")
    echo(f"  Já preservados no IA (pulados): {stats.get('already-preserved', 0)}")
    # ADR-0016: lotes, derive único, PDFs recusados e Save Page Now assíncrono.
    echo(
        "  Recusados pelo IA (PDF inválido, não serão retentados): "
        f"{stats.get('ia-rejected', 0)} "
        f"(spam: {stats.get('ia-rejected-spam', 0)})"
    )
    for reason, count in sorted((stats.get("ia-rejected-reasons") or {}).items()):
        if reason != "spam":
            echo(f"    - {reason}: {count}")
    derive_failed = stats.get("derive-failed") or []
    echo(
        f"  Lotes enviados ao IA: {stats.get('flushes', 0)} | derive pedido: "
        f"{stats.get('derive-requested', 0)} item(ns), "
        f"sem derive: {len(derive_failed)}"
    )
    for item_id in derive_failed:
        echo(f"    - sem derive: {item_id} (ia tasks {item_id} --cmd derive.php)")
    spn = stats.get("wayback-save")
    if spn:
        echo(
            "  Wayback Save Page Now (best-effort): "
            f"{spn.get('requested', 0)} pedidos, {spn.get('accepted', 0)} aceitos, "
            f"{spn.get('failed', 0)} falhas, {spn.get('dropped', 0)} descartados"
        )
    postponed = stats.get("derive-postponed") or []
    if postponed:
        echo(f"  derive adiado: {len(postponed)} item(ns) ainda com pendências")
        for item_id in postponed:
            echo(f"    - derive adiado: {item_id}")
    deferred = stats.get("deferred", 0)
    if deferred:
        deferred_items = stats.get("deferred-items") or []
        echo(
            f"  adiados (item com fila cheia no IA): {deferred} em "
            f"{len(deferred_items)} item(ns)"
        )
        for item_id in deferred_items:
            echo(f"    - adiado: {item_id}")
    if stats.get("from-spool"):
        echo(
            f"  Reaproveitadas da reserva local (sem novo download): "
            f"{stats['from-spool']}"
        )
    if stats.get("spooled"):
        echo(
            f"  Guardadas na reserva local para a próxima execução: {stats['spooled']}"
        )
    if stats.get("aborted"):
        echo(f"  Colheita interrompida cedo: {stats['aborted']}")
    if stats.get("ration-skip"):
        echo(f"  Sonda do IA: {stats['ration-skip']}")
    if stats.get("failed"):
        # Issue #297: o resumo dos motivos sai aqui, depois do laço, onde a saída
        # já se provou confiável em CI (per-item prints não apareceram).
        from collections import Counter

        reasons = Counter(
            item.get("reason", "?")
            for item in stats.get("items", [])
            if item.get("status") == "failed"
        )
        for reason, count in reasons.most_common():
            echo(f"    - {reason}: {count}")


def _harvest_postponed_message(stats: Dict[str, Any]) -> Optional[str]:
    """Mensagem de "adiado" se a colheita terminou só por ração do IA, senão ``None``.

    Só vale sem nenhuma captura preservada (com ao menos uma já era verde). Cobre: a
    sonda acima da ração antes de baixar (``ia-account-ration-skip``), a recusa da conta
    no flush (``ia-account-throttled``). Item com fila cheia (``deferred``) segue sendo falha.
    Qualquer outra causa de "nada preservado" continua falha.
    """
    if stats.get("success"):
        return None
    aborted = stats.get("aborted")
    if aborted == "ia-account-ration-skip":
        return (
            "adiado: cota da conta no Internet Archive acima da ração; "
            "nada foi baixado da fonte"
        )
    if aborted == "ia-account-throttled" and not stats.get("failed"):
        n = stats.get("requeued", 0)
        kept = stats.get("spooled", 0)
        return (
            "adiado: cota da conta no Internet Archive; "
            f"{n} capturas devolvidas à fila ({kept} guardadas na reserva local)"
        )
    return None


def _announce_postponed(message: str) -> None:
    """Imprime o aviso e o grava no resumo do job do GitHub Actions, se houver."""
    echo(message)
    echo(f"::notice title=Colheita adiada::{message}")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(f"**Colheita adiada.** {message}\n")
        except OSError:
            pass


@app.command("harvest")
def cmd_harvest(
    ente: Optional[str] = typer.Option(
        None, help="Filtrar por ente federativo (None = todos os entes)"
    ),
    tipo: Optional[str] = typer.Option(
        None,
        help="Filtrar por tipo de documento (lei, lc, decreto, ec, resolucao, portaria, decreto-lei)",
    ),
    limit: int = typer.Option(100, help="Limite de recursos a processar por execução"),
    job_deadline: Optional[float] = typer.Option(
        None,
        help=(
            "Instante Unix (s) em que o job do runner morre. A colheita para de "
            "buscar 20 min antes, para o flush, o derive e o resumo caberem."
        ),
    ),
) -> None:
    """Consome a fila de resources pendentes no banco e realiza a colheita (harvest)."""
    echo("Iniciando colheita (harvesting) de recursos pendentes...")
    stats: Dict[str, Any] = {}
    try:
        from leizilla.publisher import InternetArchivePublisher
        from leizilla.scraper import harvest_pending_resources
        from leizilla.storage import DuckDBStorage

        from leizilla.spool import DownloadSpool

        db = DuckDBStorage()
        pub = InternetArchivePublisher()

        stats = harvest_pending_resources(
            db,
            pub,
            limit=limit,
            ente=ente,
            tipo=tipo,
            stats=stats,
            job_deadline_epoch=job_deadline,
            spool=DownloadSpool(),
        )
    except Exception as e:
        # O resumo sai mesmo se a colheita levantar: o que já foi feito precisa ser
        # visível no log do job.
        _echo_harvest_summary(stats, partial=True)
        echo(f"Erro: {e}")
        raise typer.Exit(1)
    _echo_harvest_summary(stats)
    # Ração do IA: adiar não é falha (ADR-0016, adendo 2026-11-18 (2)). A conta é
    # compartilhada com os outros workflows; o que não subiu volta a ``pending`` (e os
    # bytes já baixados ficam na reserva local), e a próxima execução refaz. Sai 0 e
    # escreve o motivo no resumo do job — sem issue de falha.
    postponed = _harvest_postponed_message(stats)
    if postponed:
        _announce_postponed(postponed)
        return
    # Uma colheita em que nada foi capturado e houve falha que não é "a fonte
    # confirmou que o documento não existe" não é sucesso: sem isto o job fica
    # verde por semanas sem preservar nada. Um 404 confirmado ("fetch-failed") é
    # resultado esperado ao sondar a fronteira da numeração e não conta.
    unexpected = [
        item
        for item in stats["items"]
        if item.get("status") == "failed" and item.get("reason") != "fetch-failed"
    ]
    if unexpected and not stats["success"]:
        echo(
            f"Erro: nenhuma captura bem-sucedida e {len(unexpected)} falha(s) "
            "inesperada(s) nesta colheita."
        )
        raise typer.Exit(1)
    if stats.get("deferred") and not stats["success"]:
        # Tudo adiado por fila cheia no IA e nada capturado: não é sucesso.
        echo("Erro: nenhuma captura; recursos adiados por limite de taxa do IA.")
        raise typer.Exit(1)
    if stats.get("requeued") and not stats["success"]:
        # Limite da conta (ia-account-throttled) ou prazo (flush-timeout) sem nenhuma
        # captura preservada. Com ao menos uma captura a execução é verde: um throttle
        # não quebra a colheita, só a encerra cedo (o resumo diz o motivo).
        echo(
            "Erro: nenhuma captura preservada; "
            f"{stats['requeued']} devolvida(s) à fila ({stats.get('aborted')})."
        )
        raise typer.Exit(1)


@app.command("bundle-raw")
def cmd_bundle_raw(
    ente: str = typer.Option("ro", help="Ente federativo (ro, sp, ...)"),
    fonte: str = typer.Option("casacivil", help="Fonte (casacivil, assembleia, ...)"),
    limit: int = typer.Option(100, help="Limite de recursos a processar por execução"),
) -> None:
    """Consolida os PDFs baixados de um ente/fonte em um único item do Internet Archive para habilitar Torrent."""
    echo(f"Iniciando consolidação (bundling) de resources de {ente}/{fonte}...")
    try:
        from leizilla.publisher import InternetArchivePublisher
        from leizilla.storage import DuckDBStorage
        from leizilla import wayback

        db = DuckDBStorage()
        pub = InternetArchivePublisher()

        downloaded = db.get_downloaded_resources(ente, fonte, limit=limit)
        if not downloaded:
            echo("Nenhum recurso com status 'downloaded' encontrado.")
            return

        archive_ia_id = f"leizilla-archive-{ente}-{fonte}-raw"
        success_count = 0
        failed_count = 0

        for res in downloaded:
            url = res["url"]
            chave = res["chave"]
            tipo = res["tipo_documento"]
            wb_url = res["wayback_snapshot"]

            echo(f"Processando {chave}...")

            # Baixa o PDF
            pdf_bytes = None
            if wb_url:
                pdf_bytes = wayback.fetch_bytes(wb_url)
            if pdf_bytes is None:
                pdf_bytes = wayback.fetch_bytes(url)

            if pdf_bytes is None:
                echo(f"  Falha ao baixar PDF para {chave}")
                failed_count += 1
                continue

            # Nome do arquivo dentro do arquivo unificado (ex: lei-05120.pdf)
            filename = (
                f"{tipo}-{chave.split('-')[-1] if '-' in chave else chave}.pdf".lower()
            )

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_bytes)
                tmp_path = Path(f.name)

            try:
                result = pub.upload_to_archive(
                    archive_ia_id=archive_ia_id,
                    file_path=tmp_path,
                    filename_in_archive=filename,
                    ente=ente,
                    fonte=fonte,
                )
                if result.get("success"):
                    db.update_resource_status(url, "bundled")
                    echo(f"  Adicionado ao item {archive_ia_id} com nome {filename}")
                    success_count += 1
                else:
                    echo(
                        f"  Falha ao enviar para o arquivo consolidado: {result.get('error')}"
                    )
                    failed_count += 1
            except Exception as e:
                echo(f"  Erro ao consolidar {chave}: {e}")
                failed_count += 1
            finally:
                tmp_path.unlink(missing_ok=True)

        echo(
            f"Consolidação concluída: {success_count} com sucesso, {failed_count} falhas."
        )
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("fetch-ocr")
def cmd_fetch_ocr(
    ente: Optional[str] = typer.Option(None, help="Filtrar por ente federativo"),
    limit: int = typer.Option(100, help="Limite de leis a processar"),
) -> None:
    """Busca os textos de OCR no Internet Archive e popula a base local."""
    echo("Buscando textos de OCR pendentes...")
    try:
        from leizilla.storage import DuckDBStorage
        from leizilla.ocr import fetch_and_clean_ocr, normalize_text

        db = DuckDBStorage()
        pending = db.get_leis_pending_ocr(ente=ente, limit=limit)

        if not pending:
            echo("Nenhuma lei sem OCR encontrada no banco.")
            return

        echo(f"Encontradas {len(pending)} leis sem OCR. Iniciando busca...")
        success = 0
        failed = 0

        for lei in pending:
            lei_id = lei["id"]
            url_pdf_ia = lei.get("url_pdf_ia") or ""

            # Determina o ia_id
            ia_id = None
            if url_pdf_ia:
                match = re.search(
                    r"archive\.org/(?:details|download)/([^/]+)", url_pdf_ia
                )
                if match:
                    ia_id = match.group(1)

            if not ia_id:
                ia_id = f"leizilla-raw-{lei_id}"

            echo(f"Buscando OCR para {lei_id} (IA ID: {ia_id})...")
            text = fetch_and_clean_ocr(ia_id)

            if text:
                norm = normalize_text(text)
                db.update_lei(
                    lei_id,
                    {
                        "texto_completo": text,
                        "texto_normalizado": norm,
                    },
                )
                echo(f"  Sucesso: {len(text)} caracteres salvos.")
                success += 1
            else:
                echo("  Não foi possível obter o OCR do Internet Archive.")
                failed += 1

        echo(f"Busca de OCR concluída: {success} com sucesso, {failed} falhas.")
    except Exception as e:
        echo(f"Erro ao buscar OCR: {e}")
        raise typer.Exit(1)


@app.command("download")
def cmd_download(
    ente: str = typer.Option("ro", help="Ente federativo"),
    limit: int = typer.Option(10, help="Limite de downloads"),
) -> None:
    """Baixar PDFs das leis descobertas."""
    echo(f"Baixando até {limit} PDFs de {ente}")

    try:
        from leizilla.crawler import LeisCrawler
        from leizilla.storage import DuckDBStorage

        async def run() -> None:
            crawler = LeisCrawler(crawler_type="simple")
            db = DuckDBStorage()
            laws = db.search_leis(ente=ente, limit=limit)
            to_download = [law for law in laws if not law.get("url_pdf_ia")]

            if not to_download:
                echo("Todos os PDFs já foram baixados")
                return

            downloaded = 0
            for law in to_download[:limit]:
                if not law.get("url_original"):
                    continue
                import tempfile as _tmp

                with _tmp.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    dest = Path(f.name)
                success = await crawler.download_pdf(law["url_original"], dest)
                if success:
                    db.update_lei(law["id"], {"local_pdf_path": str(dest)})
                    downloaded += 1
                    echo(f"  Baixou: {law.get('titulo', 'N/A')}")
                else:
                    echo(f"  Falha: {law.get('titulo', 'N/A')}")

            echo(f"Baixou {downloaded} PDFs")

        asyncio.run(run())
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("upload")
def cmd_upload(
    limit: int = typer.Option(5, help="Limite de uploads"),
) -> None:
    """Upload PDFs para Internet Archive."""
    echo(f"Fazendo upload de até {limit} PDFs")

    try:
        from leizilla.publisher import InternetArchivePublisher
        from leizilla.storage import DuckDBStorage

        publisher = InternetArchivePublisher()
        db = DuckDBStorage()
        laws = db.search_leis(limit=limit * 2)
        to_upload = [
            law
            for law in laws
            if law.get("local_pdf_path") and not law.get("url_pdf_ia")
        ]

        if not to_upload:
            echo("Todos os PDFs já foram enviados para IA")
            return

        uploaded = 0
        # Índice acumulado por item de range no lote (evita lost-update do
        # index.csv entre uploads ao mesmo item — IA não tem read-after-write).
        index_cache: Dict[str, str] = {}
        for law in to_upload[:limit]:
            try:
                pdf_path = Path(law["local_pdf_path"])
                if not pdf_path.exists():
                    continue
                pdf_bytes = pdf_path.read_bytes()
                result = publisher.upload_raw(
                    pdf_path,
                    law,
                    pdf_bytes,
                    fetched_from="source-fallback",
                    index_cache=index_cache,
                )
                if result.get("success"):
                    db.update_lei(law["id"], {"url_pdf_ia": result["ia_url"]})
                    uploaded += 1
                    echo(f"  Upload: {law.get('titulo', 'N/A')}")
                else:
                    echo(f"  Falha: {law.get('titulo', 'N/A')}")
            except Exception as e:
                echo(f"  Erro em {law.get('titulo', 'N/A')}: {e}")

        echo(f"Fez upload de {uploaded} PDFs")
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("scrape")
def cmd_scrape(
    ente: str = typer.Option("ro", help="Ente federativo"),
    fonte: str = typer.Option(
        "assembleia", help="Fonte (assembleia, casacivil, planalto)"
    ),
    start: Optional[int] = typer.Option(
        None,
        "--start",
        help="ID inicial (número de lei p/ casacivil/planalto; coddoc p/ assembleia)",
    ),
    end: Optional[int] = typer.Option(None, "--end", help="ID final"),
    tipo: Optional[str] = typer.Option(
        None,
        "--tipo",
        help="Tipo: lei (ordinária), lc (complementar, casacivil), decreto (planalto)",
    ),
    skip_existing: bool = typer.Option(
        True,
        "--skip-existing/--no-skip-existing",
        help="Pula itens cujo raw IA item já existe (consulta IA antes do loop)",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Limite de novos itens a processar (itens pulados não contam)",
    ),
) -> None:
    """Scrape leis: discover → robots → wayback → upload_raw/upload_raw_html para IA."""

    _VALID_TIPOS = {"lei", "lc", "lcp", "decreto", "decreto-lei", "emc", "mpv"}

    if tipo and tipo not in _VALID_TIPOS:
        echo(f"--tipo inválido: {tipo!r}. Valores suportados: {sorted(_VALID_TIPOS)}")
        raise typer.Exit(1)
    if tipo and tipo == "lc" and fonte != "casacivil":
        echo(f"--tipo lc só é válido com --fonte casacivil (recebido: --fonte {fonte})")
        raise typer.Exit(1)
    if tipo and tipo in {"lcp", "decreto-lei", "emc", "mpv"} and fonte != "planalto":
        echo(
            f"--tipo {tipo} só é válido com --fonte planalto (recebido: --fonte {fonte})"
        )
        raise typer.Exit(1)
    if tipo and tipo == "decreto" and fonte not in ("planalto", "casacivil"):
        echo(
            f"--tipo decreto só é válido com --fonte planalto/casacivil "
            f"(recebido: --fonte {fonte})"
        )
        raise typer.Exit(1)

    start_desc = str(start) if start is not None else "1"
    end_desc = str(end) if end is not None else "cdx_max"
    tipo_desc = tipo if tipo else "todos"
    echo(f"Scraping {ente}/{fonte} {start_desc}–{end_desc} (tipo={tipo_desc})")

    try:
        from leizilla.publisher import InternetArchivePublisher, list_raw_ids
        from leizilla.scraper import make_rate_limiter

        publisher = InternetArchivePublisher()
        rate_limiter = make_rate_limiter()

        already_scraped: set[str] = set()
        if skip_existing:
            echo(f"Consultando IA para itens já scrapeados ({ente}/{fonte})...")
            already_scraped = list_raw_ids(ente, fonte)
            echo(f"  {len(already_scraped)} itens existentes encontrados")

        if ente == "federal" and fonte == "planalto":
            from leizilla.fontes.federal import discover_planalto_laws
            from leizilla.scraper import scrape_one_html

            planalto_tipos = (
                [tipo]
                if tipo
                else ["lei", "lcp", "decreto", "decreto-lei", "emc", "mpv"]
            )
            ok = 0
            skipped_ok = 0
            processed = 0
            total_laws_count = 0
            index_cache: Dict[str, str] = {}

            for p_tipo in planalto_tipos:
                s_start = start if start is not None else 1
                s_end = end if end is not None else 10
                laws = discover_planalto_laws(
                    tipo=p_tipo,
                    start_num=s_start,
                    end_num=s_end,
                )
                total_laws_count += len(laws)
                for law in laws:
                    if limit is not None and processed >= limit:
                        break
                    fonte_url = law.get("url_original")
                    if not fonte_url:
                        continue
                    if skip_existing:
                        chave = str(law.get("chave", ""))
                        ia_id = f"leizilla-raw-{ente}-{fonte}-{chave}"
                        if ia_id in already_scraped:
                            skipped_ok += 1
                            continue
                    processed += 1
                    result = scrape_one_html(
                        fonte_url, law, publisher, rate_limiter, index_cache
                    )
                    if result.get("success"):
                        ia_id = result.get("ia_id", "?")
                        ia_url = result.get("ia_url", "?")
                        echo(f"  OK: {ia_id} → {ia_url}")
                        ok += 1
                    else:
                        detail = result.get("reason") or result.get("error") or "?"
                        echo(f"  Falha [{detail}]: {law.get('chave', 'N/A')}")
            suffix = f", {skipped_ok} pulados (já existem)" if skip_existing else ""
            echo(f"Scraping concluído: {ok}/{total_laws_count} com sucesso{suffix}")
            return

        # Fontes PDF (ro/assembleia, ro/casacivil)
        from leizilla.scraper import scrape_one

        async def run() -> None:
            if ente == "ro" and fonte == "assembleia":
                from leizilla.crawler import LeisCrawler

                crawler = LeisCrawler(crawler_type="playwright")
                s_start = start if start is not None else 1
                s_end = end if end is not None else 10
                laws = await crawler.discover_rondonia_laws(
                    start_coddoc=s_start,
                    end_coddoc=s_end,
                )
            elif ente == "ro" and fonte == "casacivil":
                from leizilla.crawler import discover_casacivil_laws
                from leizilla.discovery import WaybackCdxDiscovery
                from leizilla.discovery import load_manifest, parse_filename

                manifest = load_manifest(ente)
                fontes = manifest.get("fontes", {})
                if fonte not in fontes:
                    echo(f"Fonte '{fonte}' não encontrada no manifesto de '{ente}'.")
                    raise typer.Exit(1)
                fonte_cfg = fontes[fonte]

                # 1. Fetch CDX snapshots (single request)
                snapshot_by_chave: Dict[str, str] = {}
                cdx_max_by_tipo: Dict[str, int] = {}
                try:
                    echo(
                        f"Consultando API CDX da Wayback Machine para {ente}/{fonte}..."
                    )
                    cdx_cfg = {
                        "prefix": "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/"
                    }
                    discovery_results = list(
                        WaybackCdxDiscovery(cdx_cfg, ente, fonte).run()
                    )
                    for item in discovery_results:
                        item_chave = item.get("chave")
                        snap = item.get("wayback_snapshot")
                        doc_type = item.get("tipo_documento")
                        if item_chave and snap and doc_type:
                            snapshot_by_chave[item_chave] = snap
                            try:
                                num = int(item_chave.split("-")[-1])
                                cdx_max_by_tipo[doc_type] = max(
                                    cdx_max_by_tipo.get(doc_type, 0), num
                                )
                            except ValueError:
                                pass
                except Exception as e:
                    echo(
                        f"  Erro ao consultar CDX ({e}); seguindo sem snapshots pré-descobertos."
                    )

                # 2. Determine types to process
                probe_strategies = fonte_cfg.get("probe", [])
                laws = []
                for strat in probe_strategies:
                    templates = strat["templates"]
                    sample_url = templates[0].format(num=1)
                    strat_tipo, _ = parse_filename(sample_url.split("/")[-1])

                    if strat_tipo is None:
                        echo(
                            f"  Aviso: não foi possível identificar o tipo do "
                            f"template {templates[0]!r}; pulando."
                        )
                        continue

                    if tipo and strat_tipo != tipo:
                        continue

                    # Calculate range bounds
                    cdx_hi = cdx_max_by_tipo.get(strat_tipo, 0)
                    s_start = start if start is not None else int(strat.get("start", 1))
                    s_end = end if end is not None else (cdx_hi if cdx_hi > 0 else 10)

                    echo(
                        f"  Tipo '{strat_tipo}': faixa {s_start} a {s_end} (cdx_max={cdx_hi})"
                    )
                    if s_start <= s_end:
                        tmpl = templates[0]
                        prefix = tmpl.split("/")[-1].split("{num}")[0]
                        strat_laws = discover_casacivil_laws(
                            tipo=strat_tipo,
                            start_num=s_start,
                            end_num=s_end,
                            prefix=prefix,
                        )
                        for law in strat_laws:
                            snap = snapshot_by_chave.get(law["chave"])
                            if snap:
                                law["wayback_snapshot"] = snap
                        laws.extend(strat_laws)
            else:
                echo(f"Fonte '{fonte}' para '{ente}' ainda não implementada")
                raise typer.Exit(1)

            ok = 0
            skipped_ok = 0
            processed = 0
            index_cache: Dict[str, str] = {}
            for law in laws:
                if limit is not None and processed >= limit:
                    break
                pdf_url = law.get("url_pdf_original")
                fonte_url = law.get("url_original")
                if not pdf_url or not fonte_url:
                    echo(f"  Sem URL PDF: {law.get('id', 'N/A')}")
                    continue
                if skip_existing:
                    chave = str(law.get("chave", ""))
                    ia_id = f"leizilla-raw-{ente}-{fonte}-{chave}"
                    if ia_id in already_scraped:
                        skipped_ok += 1
                        continue
                processed += 1
                result = scrape_one(
                    fonte_url,
                    pdf_url,
                    law,
                    publisher,
                    rate_limiter,
                    index_cache,
                    wayback_snapshot=law.get("wayback_snapshot"),
                )
                if result.get("success"):
                    ia_id = result.get("ia_id", "?")
                    ia_url = result.get("ia_url", "?")
                    echo(f"  OK: {ia_id} → {ia_url}")
                    ok += 1
                else:
                    detail = result.get("reason") or result.get("error") or "?"
                    echo(f"  Falha [{detail}]: {law.get('id', 'N/A')}")

            suffix = f", {skipped_ok} pulados (já existem)" if skip_existing else ""
            echo(f"Scraping concluído: {ok}/{len(laws)} com sucesso{suffix}")

        asyncio.run(run())
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("release-dataset")
def cmd_release_dataset(
    parquet: Path = typer.Argument(
        ..., help="Arquivo versoes.parquet (saída de consolidate)"
    ),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    version: int = typer.Option(0, "--version", help="Versão do dataset (0 = pré-M5)"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Reporta stats sem fazer upload"
    ),
    allow_lower_count: bool = typer.Option(
        False,
        "--allow-lower-count",
        help=(
            "Ignora o piso de contagem de linhas (issue #118) quando a queda é "
            "esperada e já verificada — ex.: issue #308's supersession markers "
            "tirando duplicatas conhecidas do Parquet consolidado. NUNCA default: "
            "sem esta flag, uma queda continua recusada fail-closed como proteção "
            "contra perda de dado não intencional."
        ),
    ),
) -> None:
    """Publicar Parquet no IA (M4 restante; releases imutáveis, issue #175).

    Cada chamada publica um release imutável e citável
    (leizilla-dataset-{ente}-v{version}-{revision}) e atualiza o ponteiro
    mutável leizilla-dataset-{ente}-v{version}-latest usado por padrão pelos
    consumidores (frontend inclusive) para descobrir a release corrente.
    """
    import time

    import duckdb

    if not parquet.exists():
        echo(f"Arquivo não encontrado: {parquet}")
        raise typer.Exit(1)

    if version < 0:
        echo(f"--version deve ser >= 0 (recebido: {version})")
        raise typer.Exit(1)

    conn = duckdb.connect()
    try:
        row_count: int = (
            conn.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(parquet)]
            ).fetchone()
            or (0,)
        )[0]

        # Benchmark gatilhos §3.4 — aproximação local (DuckDB-WASM em M5)
        t0 = time.perf_counter()
        conn.execute(
            "SELECT lei_id, dispositivo_path FROM read_parquet(?) "
            "WHERE texto_normalizado LIKE '%transparência%' AND ate IS NULL LIMIT 10",
            [str(parquet)],
        ).fetchall()
        search_ms = (time.perf_counter() - t0) * 1000
    finally:
        conn.close()

    file_mb = parquet.stat().st_size / 1_048_576
    echo(f"Stats: {row_count} linhas, {file_mb:.2f} MB, busca {search_ms:.0f}ms")

    gatilhos: list[str] = []
    if file_mb > 100:
        gatilhos.append(f"file > 100 MB ({file_mb:.1f} MB)")
    if row_count > 2_000_000:
        gatilhos.append(f"rows > 2M ({row_count:,})")
    if search_ms > 1000:
        gatilhos.append(f"search > 1s P95 ({search_ms:.0f}ms)")

    if gatilhos:
        echo(f"  Gatilhos §3.4 atingidos: {'; '.join(gatilhos)}")
        if len(gatilhos) >= 2:
            echo(
                "  2+ gatilhos → RFC sobre split de tabelas obrigatório antes de fechar M5"
            )

    if dry_run:
        echo("Dry-run: nenhum upload realizado.")
        return

    from leizilla.publisher import (
        DatasetFloorCheckError,
        InternetArchivePublisher,
        fetch_published_dataset_row_count,
    )

    # Issue #118: do not replace the public latest pointer with a smaller
    # dataset. If the current floor cannot be proven, fail closed.
    try:
        published_row_count = fetch_published_dataset_row_count(ente, version)
    except DatasetFloorCheckError as e:
        echo(f"Gate de release falhou: não foi possível verificar o piso atual ({e})")
        raise typer.Exit(1)
    if published_row_count is not None and row_count < published_row_count:
        if not allow_lower_count:
            echo(
                "Gate de release falhou: dataset candidato tem "
                f"{row_count} linhas, abaixo do piso publicado de {published_row_count}."
            )
            raise typer.Exit(1)
        echo(
            "Gate de release ignorado (--allow-lower-count): dataset candidato tem "
            f"{row_count} linhas, abaixo do piso publicado de {published_row_count} "
            "— queda aceita como esperada e verificada."
        )

    git_sha = None
    try:
        import subprocess as _sp

        git_sha = (
            _sp.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
            or None
        )
    except Exception:
        pass

    publisher = InternetArchivePublisher()
    try:
        result = publisher.upload_dataset(parquet, ente, version, row_count, git_sha)
    except ValueError as e:
        echo(f"Upload falhou: {e}")
        raise typer.Exit(1)
    if result.get("success"):
        echo(
            f"Dataset publicado: {result['ia_url']} ({result.get('row_count', '?')} linhas)"
        )
        latest_pointer = result.get("latest_pointer")
        if latest_pointer is not None:
            if latest_pointer.get("success"):
                echo(f"Ponteiro latest atualizado: {latest_pointer['ia_url']}")
            else:
                echo(
                    "Aviso: ponteiro latest falhou "
                    f"({latest_pointer.get('error', 'erro desconhecido')}) — "
                    "release imutável publicada normalmente."
                )
    else:
        echo(f"Upload falhou: {result.get('error', 'erro desconhecido')}")
        raise typer.Exit(1)


@app.command("build-textos")
def cmd_build_textos(
    output: Path = typer.Option(..., "--output", help="Arquivo textos.parquet"),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    fontes: Optional[str] = typer.Option(
        None,
        help="Fontes separadas por vírgula (default: todas as fontes do manifesto)",
    ),
    previous: Optional[Path] = typer.Option(
        None,
        "--previous",
        help=(
            "textos.parquet anterior: linhas cujo arquivo de origem e OCR não "
            "mudaram são reaproveitadas sem novo download"
        ),
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Máximo de normas (amostra; resultado é parcial)"
    ),
    sleep_s: float = typer.Option(
        0.4, "--sleep", help="Pausa em segundos entre downloads do IA"
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Grava o Parquet e sai com 0 mesmo com falhas de leitura ou --limit",
    ),
    reocr_path: Optional[Path] = typer.Option(
        None,
        "--reocr",
        help=(
            "reocr.parquet (ADR-0019): o texto de um re-OCR aceito substitui o do "
            "IA. Ausente ou ilegível: sem sobreposição (fail-open)"
        ),
    ),
) -> None:
    """Construir a camada de texto (tabela textos, ADR-0015) a partir do IA.

    Uma linha por norma com OCR (`_djvu.txt`): texto verbatim, proveniência e
    âncoras de artigo derivadas. Só leitura no IA, sequencial e com pausa.
    """
    from leizilla import textlayer
    from leizilla.discovery import load_manifest

    if fontes:
        fonte_list = [f.strip() for f in fontes.split(",") if f.strip()]
    else:
        fonte_list = list(load_manifest(ente).get("fontes", {}).keys())
    if not fonte_list:
        echo("Nenhuma fonte encontrada (--fontes vazio e manifesto sem fontes)")
        raise typer.Exit(1)

    prev_rows = None
    if previous is not None:
        if not previous.exists():
            echo(f"Arquivo não encontrado: {previous}")
            raise typer.Exit(1)
        prev_rows = textlayer.read_textos_parquet(previous)

    accepted = None
    if reocr_path is not None:
        if reocr_path.exists():
            from leizilla import reocr as reocr_mod

            accepted = reocr_mod.load_accepted(reocr_path)
            echo(f"Re-OCR: {len(accepted)} texto(s) aceito(s) em {reocr_path}")
        else:
            echo(f"Re-OCR indisponível ({reocr_path}) — sem sobreposição.")

    echo(f"Construindo textos: ente={ente} fontes={','.join(fonte_list)}...")
    rows, stats = textlayer.build_textos(
        ente,
        fonte_list,
        sleep_s=sleep_s,
        limit=limit,
        previous=prev_rows,
        reocr=accepted,
    )
    echo(
        f"  {stats.itens} itens · {stats.identidades} identidades · "
        f"{stats.com_texto} com texto · {stats.baixados} baixados · "
        f"{stats.reaproveitados} reaproveitados · {stats.mantidos} mantidos "
        f"(OCR em refação) · {stats.reocr_aplicados} com re-OCR · "
        f"{len(rows)} linhas · "
        f"{sum(1 for r in rows if r['artigos_fecham'])} com artigos fechando"
    )
    for failure in stats.failures[:20]:
        echo(f"  Falha: {failure}")
    if len(stats.failures) > 20:
        echo(f"  ... e mais {len(stats.failures) - 20} falha(s)")

    if not stats.complete and not allow_partial:
        echo(
            "Construção parcial (falhas de leitura ou --limit) — Parquet não "
            "gravado. Use --allow-partial para gravar mesmo assim."
        )
        raise typer.Exit(1)
    if not rows:
        echo("Nenhuma norma com texto encontrada — nada a gravar.")
        raise typer.Exit(1)
    textlayer.write_textos_parquet(rows, output)
    echo(f"Parquet escrito em {output}")


@app.command("release-textos")
def cmd_release_textos(
    parquet: Path = typer.Argument(..., help="textos.parquet (saída de build-textos)"),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    version: int = typer.Option(0, "--version", help="Versão do dataset"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Valida e reporta stats sem fazer upload"
    ),
    allow_lower_count: bool = typer.Option(
        False,
        "--allow-lower-count",
        help=(
            "Ignora o piso de linhas da tabela textos quando a queda é esperada "
            "e já verificada. Nunca default."
        ),
    ),
) -> None:
    """Publicar a camada de texto no IA (ADR-0015), com gates próprios.

    Itens `leizilla-textos-{ente}-v{version}-{revision}` (imutável) e `-latest`
    (ponteiro). Não lê nem altera os itens nem o piso do dataset `versoes`.
    """
    from leizilla import textlayer
    from leizilla.publisher import (
        DatasetFloorCheckError,
        InternetArchivePublisher,
        _dataset_revision,
        fetch_published_textos_row_count,
        get_git_sha,
    )

    if not parquet.exists():
        echo(f"Arquivo não encontrado: {parquet}")
        raise typer.Exit(1)
    if version < 0:
        echo(f"--version deve ser >= 0 (recebido: {version})")
        raise typer.Exit(1)

    problems = textlayer.validate_textos_parquet(parquet)
    if problems:
        for problem in problems[:20]:
            echo(f"  Violação: {problem}")
        echo(f"Gate de release falhou: {len(problems)} violação(ões) do contrato.")
        raise typer.Exit(1)

    meta = textlayer.build_textos_meta(
        parquet, ente, version, _dataset_revision(), get_git_sha()
    )
    row_count = int(meta["row_count"])
    echo(
        f"Stats: {row_count} normas com texto, "
        f"{meta['rows_artigos_fecham']} com artigos fechando, "
        f"{meta['file_size_bytes'] / 1_048_576:.2f} MB"
    )
    if row_count == 0:
        echo("Gate de release falhou: tabela textos vazia.")
        raise typer.Exit(1)
    if dry_run:
        echo("Dry-run: nenhum upload realizado.")
        return

    try:
        published = fetch_published_textos_row_count(ente, version)
    except DatasetFloorCheckError as e:
        echo(f"Gate de release falhou: não foi possível verificar o piso atual ({e})")
        raise typer.Exit(1)
    if published is not None and row_count < published:
        if not allow_lower_count:
            echo(
                "Gate de release falhou: textos candidato tem "
                f"{row_count} linhas, abaixo do piso publicado de {published}."
            )
            raise typer.Exit(1)
        echo(
            "Gate de release ignorado (--allow-lower-count): textos candidato tem "
            f"{row_count} linhas, abaixo do piso publicado de {published}."
        )

    try:
        result = InternetArchivePublisher().upload_textos(parquet, meta, ente, version)
    except ValueError as e:
        echo(f"Upload falhou: {e}")
        raise typer.Exit(1)
    if not result.get("success"):
        echo(f"Upload falhou: {result.get('error', 'erro desconhecido')}")
        raise typer.Exit(1)
    echo(f"Textos publicados: {result['ia_url']} ({row_count} linhas)")
    latest_pointer = result.get("latest_pointer") or {}
    if latest_pointer.get("success"):
        echo(f"Ponteiro latest atualizado: {latest_pointer['ia_url']}")
    else:
        echo(
            "Aviso: ponteiro latest falhou "
            f"({latest_pointer.get('error', 'erro desconhecido')}) — "
            "release imutável publicada normalmente."
        )


def _publish_reocr(output: Path, ente: str, version: int, wait_minutes: float) -> None:
    """Valida (gate de release) e publica ``reocr.parquet`` no IA; sai 1 se falhar."""
    from leizilla import publisher, reocr

    problems = reocr.validate_reocr_parquet(output)
    if problems:
        for problem in problems[:20]:
            echo(f"  Violação: {problem}")
        echo(f"Gate de release falhou: {len(problems)} violação(ões) do contrato.")
        raise typer.Exit(1)
    meta = reocr.build_reocr_meta(
        output, ente, version, publisher._dataset_revision(), publisher.get_git_sha()
    )
    try:
        result = publisher.InternetArchivePublisher().upload_reocr(
            output,
            meta,
            ente,
            version,
            queue_wait_minutes=wait_minutes,
        )
    except ValueError as e:
        echo(f"Upload falhou: {e}")
        raise typer.Exit(1)
    if not result.get("success"):
        echo(f"Upload falhou: {result.get('error', 'erro desconhecido')}")
        raise typer.Exit(1)
    echo(f"Re-OCR publicado: {result['ia_url']} ({meta['row_count']} linhas)")
    latest_pointer = result.get("latest_pointer") or {}
    if latest_pointer.get("success"):
        echo(f"Ponteiro latest atualizado: {latest_pointer['ia_url']}")
    else:
        # O -latest é o que o build-textos lê: sem ele o run não está concluído.
        echo(
            "Upload incompleto: o ponteiro latest não foi atualizado "
            f"({latest_pointer.get('error', 'erro desconhecido')}). A release "
            f"imutável {result['ia_url']} existe, mas o build-textos continua "
            "lendo o latest anterior; rode de novo para atualizá-lo."
        )
        raise typer.Exit(1)


@app.command("reocr")
def cmd_reocr(
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Máximo de normas a tentar nesta execução (total das duas filas)",
    ),
    max_pages: int = typer.Option(
        40, "--max-pages", help="PDFs com mais páginas são pulados (e contados)"
    ),
    queue_name: str = typer.Option(
        "ambas",
        "--queue",
        help=(
            "nao-fecha (há texto do IA que o leitor não fecha) | sem-texto (PDF "
            "preservado sem texto do IA) | ambas. Com --limit, sem-texto leva até "
            "2/3 e o que sobrar de uma fila passa para a outra"
        ),
    ),
    shard: Optional[str] = typer.Option(
        None,
        "--shard",
        help=(
            "i/n: só as normas da fatia i de n (hash do texto_id). A saída traz só "
            "as tentativas desta execução; publique com `reocr-merge`"
        ),
    ),
    output: Path = typer.Option(
        Path("reocr.parquet"), "--output", help="reocr.parquet"
    ),
    version: int = typer.Option(0, "--version", help="Versão do dataset"),
    textos: Optional[Path] = typer.Option(
        None,
        "--textos",
        help="textos.parquet local (default: baixa o publicado no IA)",
    ),
    previous: Optional[Path] = typer.Option(
        None,
        "--previous",
        help="reocr.parquet anterior (default: baixa o publicado no IA, se houver)",
    ),
    catalogo: Optional[Path] = typer.Option(
        None,
        "--catalogo",
        help=(
            "completeness.parquet local, só para ordenar a fila sem-texto por ano "
            "(default: baixa o publicado; sem ele, ordena pelo número)"
        ),
    ),
    fontes: Optional[str] = typer.Option(
        None,
        "--fontes",
        help="Fontes da fila sem-texto, separadas por vírgula (default: manifesto)",
    ),
    sleep_s: float = typer.Option(
        1.0, "--sleep", help="Pausa entre downloads de PDF do IA (mínimo 1 s)"
    ),
    upload: bool = typer.Option(
        False, "--upload", help="Publica reocr.parquet no IA (precisa de IA_*_KEY)"
    ),
    upload_wait_minutes: float = typer.Option(
        45.0,
        "--upload-wait-minutes",
        help="Com a fila de tarefas do IA cheia, espera até este total (min, somando "
        "os dois itens) antes de desistir; 0 = recuo curto de sempre",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Só calcula e mostra a fila: não baixa PDF, não faz OCR, não grava",
    ),
) -> None:
    """Re-OCR direcionado (ADR-0019): OCR próprio onde o IA não entrega texto útil.

    Duas filas. `nao-fecha`: normas com texto no `textos` publicado cujo
    `read_hierarchy` não fecha os artigos; o OCR novo só vale se fechar e não
    perder artigos. `sem-texto`: PDFs preservados que o IA ainda não derivou e que
    não estão em `textos`; o OCR vale se não for trivial (nada a comparar). Para
    cada norma: PDF do IA → poppler → Kreuzberg+PaddleOCR → portão determinístico.
    Aceito ou rejeitado, a tentativa vira uma linha de `reocr.parquet` (coluna
    `fila`); o texto do IA nunca é alterado. Requer o extra `reocr`
    (`uv sync --extra reocr`) e poppler-utils.
    """
    from leizilla import completeness, reocr, textlayer
    from leizilla.discovery import load_manifest

    if sleep_s < reocr.MIN_SLEEP_S:
        echo(f"--sleep deve ser >= {reocr.MIN_SLEEP_S} s (recebido: {sleep_s})")
        raise typer.Exit(1)
    if max_pages < 1 or (limit is not None and limit < 1) or version < 0:
        echo("--max-pages/--limit devem ser >= 1 e --version >= 0")
        raise typer.Exit(1)
    if upload_wait_minutes < 0:
        echo("--upload-wait-minutes deve ser >= 0")
        raise typer.Exit(1)
    if queue_name not in ("nao-fecha", "sem-texto", "ambas"):
        echo(f"--queue deve ser nao-fecha, sem-texto ou ambas (recebido: {queue_name})")
        raise typer.Exit(1)
    shard_spec: Optional[tuple[int, int]] = None
    if shard is not None:
        try:
            shard_spec = reocr.parse_shard(shard)
        except ValueError as e:
            echo(str(e))
            raise typer.Exit(1)
        if upload:
            echo("--shard não publica: junte as fatias com `reocr-merge --upload`.")
            raise typer.Exit(1)
    want_nao = queue_name in ("nao-fecha", "ambas")
    want_sem = queue_name in ("sem-texto", "ambas")

    with tempfile.TemporaryDirectory() as tmp:
        textos_path = textos
        if textos_path is None:
            textos_path = Path(tmp) / "textos.parquet"
            if not completeness.fetch_published_textos(ente, version, textos_path):
                echo("textos.parquet publicado indisponível — nada a fazer.")
                raise typer.Exit(1)
        elif not textos_path.exists():
            echo(f"Arquivo não encontrado: {textos_path}")
            raise typer.Exit(1)

        attempts: list[dict[str, Any]] = []
        previous_path = previous
        if previous_path is None:
            previous_path = Path(tmp) / "reocr-previous.parquet"
            try:
                if not reocr.fetch_published_reocr(ente, version, previous_path):
                    previous_path = None  # nunca publicado: histórico vazio
            except OSError as e:
                echo(f"reocr.parquet anterior ilegível ({e}) — abortando.")
                raise typer.Exit(1)
        elif not previous_path.exists():
            echo(f"Arquivo não encontrado: {previous_path}")
            raise typer.Exit(1)
        if previous_path is not None:
            attempts = reocr.read_reocr_parquet(previous_path)

        stats = reocr.ReocrStats()
        text_rows = list(textlayer.read_textos_parquet(textos_path).values())
        kz_version = reocr.installed_kreuzberg_version()

        nao_queue: list[dict[str, Any]] = []
        if want_nao:
            nao_queue = reocr.select_queue(
                text_rows,
                attempts,
                kreuzberg_version=kz_version,
                max_pages=max_pages,
                stats=stats,
            )
            echo(
                f"Fila nao-fecha: {stats.examinadas} normas com texto · "
                f"{stats.nao_fecham} não fecham · {stats.ja_tentadas} já tentadas · "
                f"{stats.na_fila} na fila "
                f"({stats.fila_com_artigos} com artigos lidos primeiro · "
                f"{stats.fila_sem_artigos} sem artigos)"
            )
        sem_queue: list[dict[str, Any]] = []
        if want_sem:
            if fontes:
                fonte_list = [f.strip() for f in fontes.split(",") if f.strip()]
            else:
                fonte_list = list(load_manifest(ente).get("fontes", {}).keys())
            candidates, failures = reocr.enumerate_sem_texto(
                ente, fonte_list, text_rows
            )
            for failure in failures[:10]:
                echo(f"  Falha ao listar o acervo: {failure}")
            if catalogo is not None:
                years = reocr.read_years(catalogo)
            else:
                years = reocr.fetch_published_years(ente, version)
            sem_queue = reocr.select_sem_texto(
                candidates,
                attempts,
                kreuzberg_version=kz_version,
                max_pages=max_pages,
                years=years,
                stats=stats,
            )
            echo(
                f"Fila sem-texto: {stats.sem_texto_enumeradas} PDFs preservados sem "
                f"texto · {stats.sem_texto_ja_tentadas} já tentados · "
                f"{stats.sem_texto_na_fila} na fila (mais recentes primeiro; "
                f"{sum(1 for r in sem_queue if r['texto_id'] in years)} com ano)"
            )
        if shard_spec is not None:
            nao_queue = reocr.in_shard(nao_queue, shard_spec)
            sem_queue = reocr.in_shard(sem_queue, shard_spec)
            echo(
                f"Fatia {shard}: {len(sem_queue)} sem-texto · "
                f"{len(nao_queue)} nao-fecha"
            )
        if dry_run:
            take_sem, take_nao = reocr.split_limit(
                limit, len(sem_queue), len(nao_queue)
            )
            shown = limit or 20
            for item in sem_queue[: min(take_sem, shown)]:
                echo(f"  [sem-texto] {item['texto_id']}")
            for item in nao_queue[: min(take_nao, shown)]:
                echo(
                    f"  [nao-fecha] {item['texto_id']} "
                    f"(artigos lidos: {item['_artigos_ia']})"
                )
            echo("Dry-run: nenhum PDF baixado, nenhum OCR, nada gravado.")
            return
        if not sem_queue and not nao_queue:
            echo("Fila vazia — nada a fazer.")
            return
        if kz_version == "ausente":
            echo("Kreuzberg não instalado — rode `uv sync --extra reocr`.")
            raise typer.Exit(1)

        new_rows = reocr.run_queues(
            sem_queue,
            nao_queue,
            stats=stats,
            limit=limit,
            max_pages=max_pages,
            sleep_s=sleep_s,
        )
        echo(
            f"Tentadas {stats.tentadas}: {stats.aceitas} aceitas · "
            f"{stats.rejeitadas} rejeitadas ({stats.grandes} acima de "
            f"{max_pages} páginas)"
        )
        for row in new_rows:
            echo(
                f"  [{row['fila']}] {row['texto_id']}: {row['motivo']} "
                f"(artigos {row['artigos_ia']} -> {row['artigos_novo']}, "
                f"fecha {row['fecha_novo']}, {row['paginas']} pág., "
                f"{row['segundos']} s)"
            )
        for failure in stats.failures[:20]:
            echo(f"  Falha: {failure}")
        if not new_rows:
            echo("Nenhuma tentativa registrada — nada a gravar.")
            if stats.failures:
                raise typer.Exit(1)
            return

        if shard_spec is not None:
            # Fatia: só as tentativas novas; `reocr-merge` junta com o histórico.
            reocr.write_reocr_parquet(new_rows, output)
            echo(f"Parquet da fatia escrito em {output} ({len(new_rows)} tentativas)")
        else:
            merged = reocr.merge_attempts(attempts, new_rows)
            reocr.write_reocr_parquet(merged, output)
            echo(f"Parquet escrito em {output} ({len(merged)} tentativas no histórico)")

    if upload:
        _publish_reocr(output, ente, version, upload_wait_minutes)


@app.command("reocr-merge")
def cmd_reocr_merge(
    shards: list[Path] = typer.Argument(
        ..., help="reocr.parquet de cada fatia (`reocr --shard i/n`)"
    ),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    version: int = typer.Option(0, "--version", help="Versão do dataset"),
    output: Path = typer.Option(
        Path("reocr.parquet"), "--output", help="reocr.parquet unido"
    ),
    previous: Optional[Path] = typer.Option(
        None,
        "--previous",
        help="reocr.parquet anterior (default: baixa o publicado no IA, se houver)",
    ),
    upload: bool = typer.Option(
        False, "--upload", help="Publica reocr.parquet no IA (precisa de IA_*_KEY)"
    ),
    upload_wait_minutes: float = typer.Option(
        45.0,
        "--upload-wait-minutes",
        help="Espera total (min) pela fila de tarefas do IA antes de desistir",
    ),
) -> None:
    """Junta as fatias do re-OCR com o histórico e publica uma vez (ADR-0019).

    As fatias só fazem OCR; o upload é um só, sem corrida pelo mesmo item do IA.
    """
    from leizilla import reocr

    missing = [p for p in shards if not p.exists()]
    if missing:
        echo(f"Arquivo não encontrado: {missing[0]}")
        raise typer.Exit(1)
    if upload_wait_minutes < 0:
        echo("--upload-wait-minutes deve ser >= 0")
        raise typer.Exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        attempts: list[dict[str, Any]] = []
        previous_path = previous
        if previous_path is None:
            previous_path = Path(tmp) / "reocr-previous.parquet"
            try:
                if not reocr.fetch_published_reocr(ente, version, previous_path):
                    previous_path = None
            except OSError as e:
                echo(f"reocr.parquet anterior ilegível ({e}) — abortando.")
                raise typer.Exit(1)
        elif not previous_path.exists():
            echo(f"Arquivo não encontrado: {previous_path}")
            raise typer.Exit(1)
        if previous_path is not None:
            attempts = reocr.read_reocr_parquet(previous_path)
        new_rows: list[dict[str, Any]] = []
        for path in shards:
            new_rows.extend(reocr.read_reocr_parquet(path))
        echo(
            f"{len(new_rows)} tentativa(s) novas em {len(shards)} fatia(s) · "
            f"{len(attempts)} no histórico"
        )
        merged = reocr.merge_attempts(attempts, new_rows)
        reocr.write_reocr_parquet(merged, output)
    echo(f"Parquet escrito em {output} ({len(merged)} tentativas no histórico)")
    if upload:
        _publish_reocr(output, ente, version, upload_wait_minutes)


@app.command("consolidate")
def cmd_consolidate(
    xml_dir: Path = typer.Argument(..., help="Diretório com arquivos {lei_id}.xml"),
    output: Path = typer.Option(..., "--output", help="Arquivo Parquet de saída"),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
) -> None:
    """Consolidar XMLs Leizilla em Parquet v0.1 (tabela versoes)."""
    from leizilla.etl import consolidate_xmls, write_parquet

    xml_files = sorted(xml_dir.glob("*.xml"))
    if not xml_files:
        echo(f"Nenhum arquivo .xml encontrado em {xml_dir}")
        raise typer.Exit(1)

    items = []
    read_errors = 0
    for f in xml_files:
        lei_id = f.stem
        try:
            xml_content = f.read_text(encoding="utf-8")
        except OSError as e:
            echo(f"  Erro ao ler {f.name}: {e}")
            read_errors += 1
            continue
        # Issue #118: the parse step already runs the XSD gate before writing
        # its own output, but consolidate reads whatever is in xml_dir — it
        # may include files that never went through `parse` (manual edits,
        # older batches). Gate here too so a structurally invalid XML can't
        # reach the published Parquet just because it skipped that step.
        if not _xsd_gate(xml_content, warn_prefix=f"  {f.name}: "):
            read_errors += 1
            continue
        items.append((lei_id, ente, xml_content))

    if not items:
        echo("Nenhum XML pôde ser lido.")
        raise typer.Exit(1)

    if read_errors:
        echo(
            f"  Aviso: {read_errors}/{len(xml_files)} arquivo(s) ignorado(s) por erro de leitura."
        )
    rows = consolidate_xmls(items)
    echo(f"Convertidos {len(items)}/{len(xml_files)} XMLs → {len(rows)} linhas")
    write_parquet(rows, output)
    echo(f"Parquet escrito em {output}")
    if read_errors:
        raise typer.Exit(1)


@app.command("export")
def cmd_export(
    ente: str = typer.Option("ro", help="Ente federativo"),
    year: Optional[int] = typer.Option(None, help="Ano específico"),
    format: str = typer.Option("parquet", help="Formato (parquet)"),
) -> None:
    """Exportar dataset de leis."""
    echo(f"Exportando dataset de {ente}" + (f" do ano {year}" if year else ""))

    try:
        from leizilla.publisher import InternetArchivePublisher

        publisher = InternetArchivePublisher()
        output_dir = Path("data/exports")
        output_dir.mkdir(exist_ok=True)

        if format == "parquet":
            output_path = publisher.export_dataset_parquet(ente, output_dir, year)
            echo(f"Dataset exportado: {output_path}")
        else:
            echo(f"Formato '{format}' não implementado")
            raise typer.Exit(1)
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("search")
def cmd_search(
    text: Optional[str] = typer.Option(None, help="Buscar por texto"),
    ente: Optional[str] = typer.Option(None, help="Filtrar por ente federativo"),
    year: Optional[int] = typer.Option(None, help="Filtrar por ano"),
    limit: int = typer.Option(20, help="Limite de resultados"),
) -> None:
    """Buscar leis no banco de dados."""
    echo("Buscando leis...")

    try:
        from leizilla.storage import DuckDBStorage

        db = DuckDBStorage()
        laws = db.search_leis(ente=ente, ano=year, texto=text, limit=limit)

        if not laws:
            echo("Nenhuma lei encontrada")
            return

        echo(f"Encontradas {len(laws)} leis:")
        for law in laws:
            title = law.get("titulo", "N/A")
            year_str = f"({law.get('ano', 'N/A')})" if law.get("ano") else ""
            ente_str = law.get("ente", "N/A")
            echo(f"  {title} {year_str} — {ente_str}")
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("stats")
def cmd_stats(
    ente: str = typer.Option("ro", help="Ente federativo (ro, federal, sp, ...)"),
    ia: bool = typer.Option(
        True,
        "--ia/--no-ia",
        help="Consultar Internet Archive (desabilite com --no-ia para uso offline)",
    ),
) -> None:
    """Mostrar estatísticas do pipeline: itens raw/parsed/dataset no IA."""
    from leizilla.publisher import count_ia_items

    echo(f"=== Leizilla Stats: {ente} ===\n")

    if ia:
        echo("Internet Archive:")
        # Raw items são range buckets identity-keyed com underscore (ADR-0011):
        # leizilla_{ente}_{fonte}_{tipo}_{range}. Parsed/dataset usam hífen, então
        # o prefixo underscore casa só com raw, e leizilla-{ente}- só com parsed.
        raw_count = count_ia_items(f"leizilla_{ente}_")
        parsed_count = count_ia_items(f"leizilla-{ente}-")
        dataset_count = count_ia_items(f"leizilla-dataset-{ente}-")

        echo(
            f"  Raw items:     {raw_count if raw_count is not None else 'erro de rede'}"
        )
        echo(
            f"  Parsed items:  {parsed_count if parsed_count is not None else 'erro de rede'}"
        )
        echo(
            f"  Dataset items: {dataset_count if dataset_count is not None else 'erro de rede'}"
        )
    else:
        echo("Consulta IA desabilitada (use sem --no-ia para ver contagens).")


@app.command("coverage")
def cmd_coverage(
    ente: str = typer.Option("ro", help="Ente federativo (ro, federal, sp, ...)"),
    fontes: Optional[str] = typer.Option(
        None,
        help="Fontes separadas por vírgula (default: todas as fontes do manifesto)",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emitir o relatório como JSON (machine-readable)"
    ),
    output: Optional[Path] = typer.Option(
        None, help="Grava o relatório JSON neste arquivo (implica --json)"
    ),
    upload: bool = typer.Option(
        False,
        "--upload",
        help="Publica coverage.json no item IA do dataset (leizilla-dataset-{ente}-v{version})",
    ),
    version: int = typer.Option(
        0, "--version", help="Versão do dataset alvo do upload (ver --upload)"
    ),
) -> None:
    """Medir cobertura S1 (arquivado) -> S4 (estruturado) — issue #174.

    Contadores reproduzíveis por fonte e tipo normativo, direto do Internet
    Archive (sem heurística manual). Um contador ausente (null no JSON) significa
    "não foi possível medir" — nunca um 0 real silencioso.
    """
    import json as _json

    from leizilla.coverage import compute_coverage
    from leizilla.discovery import load_manifest

    if fontes:
        fonte_list = [f.strip() for f in fontes.split(",") if f.strip()]
    else:
        manifest = load_manifest(ente)
        fonte_list = list(manifest.get("fontes", {}).keys())

    if not fonte_list:
        echo("Nenhuma fonte encontrada (--fontes vazio e manifesto sem fontes)")
        raise typer.Exit(1)

    echo(f"Medindo cobertura S1-S4: ente={ente} fontes={','.join(fonte_list)}...")
    report = compute_coverage(ente, fonte_list)
    payload = report.to_dict()

    if output is not None:
        output.write_text(
            _json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        echo(f"Relatório gravado em {output}")

    if upload:
        from leizilla.publisher import InternetArchivePublisher

        pub = InternetArchivePublisher()
        result = pub.upload_coverage(payload, ente, version)
        if result.get("success"):
            echo(f"coverage.json publicado: {result['ia_url']}")
        else:
            echo(f"Upload de coverage.json falhou: {result.get('error')}")
            raise typer.Exit(1)

    if json_output or output is not None:
        echo(_json.dumps(payload, indent=2, ensure_ascii=False))
        return

    for fc in report.fontes:
        echo(
            f"  {fc.fonte}: {fc.s1_total} arquivadas · {fc.s2_total} identificadas · "
            f"{fc.s3_total} com texto · {fc.s4_total} estruturadas"
        )
        if not fc.ok_s1_s3:
            echo(
                "    (S1-S3: erro de rede em parte da medição — números abaixo são parciais)"
            )
        if not fc.ok_s4:
            echo("    (S4: erro de rede — não confiar no número acima)")
        for t in fc.por_tipo.values():
            echo(
                f"    {t.tipo}: S1={t.s1_arquivadas} S2={t.s2_identificadas} "
                f"S3={t.s3_com_texto} S4={t.s4_estruturadas}"
            )


@app.command("completeness")
def cmd_completeness(
    output: Path = typer.Option(
        ..., "--output", help="Parquet do livro-razão (ex.: completeness.parquet)"
    ),
    summary: Optional[Path] = typer.Option(
        None,
        "--summary",
        help="Resumo JSON (default: completeness.json ao lado de --output)",
    ),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    fonte: Optional[str] = typer.Option(
        None,
        "--fonte",
        help="Fonte com índice oficial (default: a única do manifesto que tem)",
    ),
    catalog_snapshot: Optional[Path] = typer.Option(
        None,
        "--catalog-snapshot",
        help=(
            "Snapshot do catálogo oficial (.json ou .json.gz): lido se existir e "
            "regravado ao final — só os anos recentes são rebuscados"
        ),
    ),
    refresh_years: int = typer.Option(
        2,
        "--refresh-years",
        help="Quantos anos recentes rebuscar sempre, mesmo se estiverem no snapshot",
    ),
    max_fetch: Optional[int] = typer.Option(
        None,
        "--max-fetch",
        help="Máximo de listas anuais buscadas ao vivo (o resto fica 'pending')",
    ),
    fetch_years: Optional[str] = typer.Option(
        None,
        "--fetch-years",
        help="Restringe a busca ao vivo a estes anos (ex.: '1981-1990,2026')",
    ),
    textos: Optional[Path] = typer.Option(
        None,
        "--textos",
        help="textos.parquet local (default: baixa o publicado no IA)",
    ),
    upload: bool = typer.Option(
        False,
        "--upload",
        help="Publica resumo, Parquet e snapshot no item IA do dataset (-latest)",
    ),
    version: int = typer.Option(
        0, "--version", help="Versão do dataset (textos publicado e alvo do upload)"
    ),
    relations: Optional[Path] = typer.Option(
        None,
        "--relations",
        help="Parquet das relações entre normas (default: relacoes.parquet ao lado de --output)",
    ),
    sem_ia: bool = typer.Option(
        False,
        "--sem-ia",
        help=(
            "Não consulta o Internet Archive: as flags de estágio ficam sem medição "
            "(NULL). Basta para o catálogo oficial e as relações; não use com --upload"
        ),
    ),
) -> None:
    """Livro-razão de completude: o acervo contra o índice oficial da fonte.

    Uma linha por norma das listas anuais oficiais (Casa Civil/RO), com as flags
    preservada / com texto / legível / estruturada, mais as normas que o acervo
    guarda e o índice não lista. Ano que não pôde ser lido fica desconhecido —
    nunca conta como "zero normas".
    """
    import json as _json
    from leizilla import completeness as comp
    from leizilla.publisher import get_git_sha

    if fonte is None:
        candidates = comp.fontes_with_official_index(ente)
        if len(candidates) != 1:
            echo(
                f"Informe --fonte: {len(candidates)} fonte(s) com índice oficial "
                f"no manifesto de {ente} ({', '.join(candidates) or 'nenhuma'})"
            )
            raise typer.Exit(1)
        fonte = candidates[0]
    elif not comp.year_index_configs(ente, fonte):
        echo(f"A fonte {ente}/{fonte} não declara índice oficial no manifesto")
        raise typer.Exit(1)

    years: Optional[set[int]] = None
    if fetch_years is not None:
        try:
            years = comp.parse_year_spec(fetch_years)
        except ValueError as e:
            echo(str(e))
            raise typer.Exit(1)

    snapshot = None
    if catalog_snapshot is not None and catalog_snapshot.exists():
        snapshot = comp.load_catalog_snapshot(catalog_snapshot)
        echo(f"Snapshot do catálogo: {len(snapshot)} lista(s) anual(is)")

    echo(f"Lendo o índice oficial: ente={ente} fonte={fonte}...")
    catalog = comp.fetch_catalog(
        ente,
        fonte,
        snapshot=snapshot,
        refresh_years=refresh_years,
        max_fetch=max_fetch,
        fetch_years=years,
    )
    echo(
        f"  {catalog.known_pages}/{len(catalog.pages)} listas anuais lidas "
        f"({catalog.live_requests} requisição(ões) ao vivo)"
    )
    if catalog.known_pages == 0:
        echo("Nenhuma lista anual pôde ser lida — nada a gravar.")
        raise typer.Exit(1)
    if catalog_snapshot is not None:
        saved = comp.write_catalog_snapshot(catalog, catalog_snapshot)
        echo(f"  Snapshot regravado: {saved} lista(s) em {catalog_snapshot}")

    textos_keys = None
    if sem_ia and upload:
        echo("--sem-ia não pode ser combinado com --upload (estágios sem medição)")
        raise typer.Exit(1)
    with tempfile.TemporaryDirectory() as tmp:
        textos_path = textos
        if sem_ia:
            textos_path = None
        elif textos_path is None:
            candidate = Path(tmp) / "textos.parquet"
            if comp.fetch_published_textos(ente, version, candidate):
                textos_path = candidate
        elif not textos_path.exists():
            echo(f"Arquivo não encontrado: {textos_path}")
            raise typer.Exit(1)
        if textos_path is not None:
            textos_keys = comp.read_textos_keys(textos_path, ente, fonte)
    if textos_keys is None:
        echo("  Camada de texto indisponível — 'legível' fica sem medição")

    if sem_ia:
        holdings = comp.Holdings(ok_s2_s3=False)
    else:
        echo("Lendo o acervo no Internet Archive...")
        holdings = comp.collect_holdings(ente, fonte, textos_keys)
    rows = comp.build_ledger(catalog, holdings)
    payload = comp.summarize(catalog, holdings, rows, git_sha=get_git_sha())

    from leizilla import catalogo, relacoes

    relation_rows = relacoes.construir_relacoes(rows)
    payload["relacoes"] = catalogo.resumo_relacoes(relation_rows)
    comp.write_ledger_parquet(rows, output)
    relations_path = relations or output.with_name(relacoes.RELACOES_FILENAME)
    relacoes.write_relacoes_parquet(relation_rows, relations_path)
    summary_path = summary or output.with_name(comp.SUMMARY_FILENAME)
    summary_path.write_text(
        _json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    echo(f"Livro-razão: {len(rows)} linhas em {output}; resumo em {summary_path}")
    echo(
        f"Relações: {len(relation_rows)} em {relations_path} "
        f"({payload['relacoes']['por_confianca']})"
    )

    def show(value: Optional[int]) -> str:
        return "?" if value is None else str(value)

    for t in payload["tipos"]:
        echo(
            f"  {t['rotulo']}: {show(t['preservadas'])} de {show(t['listadas'])} "
            f"preservadas · {show(t['com_texto'])} com texto do IA · "
            f"{show(t['legiveis'])} legíveis · {show(t['estruturadas'])} "
            f"estruturadas · {show(t['faltantes'])} faltantes "
            f"(índice lido em {t['anos_lidos']}/{t['anos']} anos)"
        )
    unknown = payload["catalogo"]["anos_desconhecidos"]
    if unknown:
        echo(
            f"  {len(unknown)} lista(s) anual(is) desconhecida(s) — não contam "
            "como zero; rode de novo para completá-las"
        )
    if not holdings.ok_s2_s3:
        echo("  (IA: medição de preservação incompleta — '?' não é zero)")

    if upload:
        from leizilla.publisher import InternetArchivePublisher

        with tempfile.TemporaryDirectory() as tmp:
            # Nomes fixos no item, quaisquer que sejam os caminhos locais.
            staged = [
                (output, comp.LEDGER_FILENAME),
                (summary_path, comp.SUMMARY_FILENAME),
                (relations_path, relacoes.RELACOES_FILENAME),
            ]
            if catalog_snapshot is not None and catalog_snapshot.suffix == ".gz":
                staged.append((catalog_snapshot, comp.CATALOG_FILENAME))
            files = []
            for src, name in staged:
                dst = Path(tmp) / name
                dst.write_bytes(src.read_bytes())
                files.append(dst)
            result = InternetArchivePublisher().upload_completeness(
                files, ente, version
            )
        if result.get("success"):
            echo(f"Livro-razão publicado: {result['ia_url']}")
        else:
            echo(f"Upload do livro-razão falhou: {result.get('error')}")
            raise typer.Exit(1)


@app.command("release-catalogo")
def cmd_release_catalogo(
    ledger: Path = typer.Argument(
        ..., help="completeness.parquet (catálogo estendido)"
    ),
    relations: Path = typer.Argument(..., help="relacoes.parquet"),
    summary: Path = typer.Option(..., "--summary", help="completeness.json"),
    catalog_snapshot: Optional[Path] = typer.Option(
        None, "--catalog-snapshot", help="completeness_catalog.json.gz (opcional)"
    ),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    version: int = typer.Option(0, "--version", help="Versão do dataset"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Valida e reporta sem fazer upload"
    ),
    allow_lower_count: bool = typer.Option(
        False,
        "--allow-lower-count",
        help="Ignora o piso de normas listadas quando a queda é esperada. Nunca default.",
    ),
) -> None:
    """Publicar o catálogo oficial e as relações no IA (ADR-0017), com gates próprios.

    Valida o contrato dos dois Parquets e o piso de normas listadas (o
    ``completeness.json`` já publicado) antes de enviar ao item `-latest` do dataset.
    """
    import json as _json
    from leizilla import catalogo, relacoes
    from leizilla import completeness as comp
    from leizilla.publisher import InternetArchivePublisher

    for path in (ledger, relations, summary):
        if not path.exists():
            echo(f"Arquivo não encontrado: {path}")
            raise typer.Exit(1)
    problems = catalogo.validate_catalogo_files(ledger, relations)
    if problems:
        for problem in problems[:20]:
            echo(f"  Violação: {problem}")
        echo(f"Gate de release falhou: {len(problems)} violação(ões) do contrato.")
        raise typer.Exit(1)

    candidate = catalogo.published_floor(_json.loads(summary.read_text("utf-8")))
    if candidate is None or candidate == 0:
        echo("Gate de release falhou: o resumo não declara normas listadas.")
        raise typer.Exit(1)
    echo(f"Catálogo: {candidate} normas listadas; relações validadas.")
    if dry_run:
        echo("Dry-run: nenhum upload realizado.")
        return

    try:
        floor = catalogo.fetch_published_floor(ente, version)
    except RuntimeError as e:
        echo(f"Gate de release falhou: não foi possível verificar o piso atual ({e})")
        raise typer.Exit(1)
    if floor is not None and candidate < floor:
        if not allow_lower_count:
            echo(
                f"Gate de release falhou: o candidato tem {candidate} normas listadas, "
                f"abaixo do piso publicado de {floor}."
            )
            raise typer.Exit(1)
        echo(f"Gate de release ignorado (--allow-lower-count): {candidate} < {floor}.")

    staged = [
        (ledger, comp.LEDGER_FILENAME),
        (summary, comp.SUMMARY_FILENAME),
        (relations, relacoes.RELACOES_FILENAME),
    ]
    if catalog_snapshot is not None and catalog_snapshot.exists():
        staged.append((catalog_snapshot, comp.CATALOG_FILENAME))
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for src, name in staged:
            dst = Path(tmp) / name
            dst.write_bytes(src.read_bytes())
            files.append(dst)
        result = InternetArchivePublisher().upload_completeness(files, ente, version)
    if not result.get("success"):
        echo(f"Upload do catálogo falhou: {result.get('error')}")
        raise typer.Exit(1)
    echo(f"Catálogo publicado: {result['ia_url']}")


@app.command("catalog-snapshot-pick")
def cmd_catalog_snapshot_pick(
    candidates: list[Path] = typer.Argument(
        ..., help="Snapshots candidatos (.json ou .json.gz), na ordem de desempate"
    ),
    output: Path = typer.Option(..., "--output", help="Onde gravar o escolhido"),
) -> None:
    """Escolher o snapshot do catálogo com mais listas anuais e copiá-lo para ``--output``.

    Candidatos inexistentes ou ilegíveis são ignorados. Empate fica com o primeiro
    dado. Sem nenhum candidato utilizável, nada é gravado e o comando sai com 0.
    """
    import shutil

    from leizilla import completeness as comp

    usable: list[tuple[int, int, Path]] = []
    for index, candidate in enumerate(candidates):
        if not candidate.exists():
            echo(f"  {candidate}: ausente — ignorado")
            continue
        try:
            years = comp.count_catalog_snapshot_years(candidate)
        except (OSError, ValueError, KeyError, TypeError) as e:
            echo(f"  {candidate}: ilegível ({type(e).__name__}) — ignorado")
            continue
        echo(f"  {candidate}: {years} lista(s)")
        usable.append((years, index, candidate))

    if not usable:
        echo("Nenhum snapshot do catálogo utilizável — leitura a partir do zero.")
        return

    years, _, chosen = max(usable, key=lambda item: (item[0], -item[1]))
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chosen, output)
    echo(f"Snapshot escolhido: {chosen} ({years} lista(s)) -> {output}")


@app.command("doctor")
def cmd_doctor() -> None:
    """Verificar pré-requisitos de produção (RFC-0004): credenciais, dados, rede.

    Exit code 0 quando todos os checks essenciais passam; 1 quando falta algum
    pré-requisito essencial. Falhas de conectividade são apenas avisos
    (fail-open) e não afetam o exit code.
    """
    from leizilla.doctor import format_results, run_doctor

    echo("=== Leizilla Doctor ===\n")
    results, essencial_ok = run_doctor()
    for line in format_results(results, essencial_ok):
        echo(line)
    if not essencial_ok:
        raise typer.Exit(1)


def _xsd_gate(xml_content: str, warn_prefix: str = "") -> bool:
    """Valida XML contra leizilla-v0.1.xsd via xmllint.

    Fail-open localmente: sem `xmllint` instalado, avisa e segue (não trava
    desenvolvimento). Fail-closed em CI (`GITHUB_ACTIONS=true`): `xmllint`
    ausente ali é falha de setup do runner, não motivo para publicar um
    dataset sem o único gate de integridade estrutural do pipeline.
    """
    schema = Path(__file__).parents[2] / "docs" / "schemas" / "leizilla-v0.1.xsd"
    if not schema.exists():
        echo(f"{warn_prefix}XSD schema não encontrado — skip validação")
        return True
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(xml_content)
            tmp_path = Path(tmp.name)
        result = subprocess.run(
            ["xmllint", "--schema", str(schema), "--noout", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            echo(f"{warn_prefix}XSD aviso: {result.stderr.strip()}")
            return False
        return True
    except FileNotFoundError:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError(
                "xmllint não disponível em CI — gate XSD não pode fail-open aqui"
                " (instale libxml2-utils no job)"
            ) from None
        echo(f"{warn_prefix}xmllint não disponível — skip validação XSD")
        return True
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _write_step_summary(
    parsed_ok: int,
    parsed_fail: int,
    uploaded_ok: int,
    upload_fail: int,
    skipped_ok: int,
    error_threshold: float,
) -> None:
    """Escreve resumo Markdown no GitHub Step Summary se rodando em CI."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    total = parsed_ok + parsed_fail
    rate = (parsed_fail / total * 100.0) if total > 0 else 0.0
    over = error_threshold > 0 and total > 0 and rate > error_threshold
    status = "❌" if over or upload_fail > 0 else "✅"
    lines = [
        f"## {status} Leizilla parse-all",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Parseados OK | {parsed_ok} |",
        f"| Falhas de parse | {parsed_fail} |",
        f"| Taxa de falhas | {rate:.1f}% |",
        f"| Uploaded | {uploaded_ok} |",
        f"| Erros de upload | {upload_fail} |",
        f"| Pulados (já publicados) | {skipped_ok} |",
    ]
    if error_threshold > 0:
        lines.append(f"| Limite de falhas configurado | {error_threshold:.0f}% |")
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass  # fail-open: CI summary não é crítico


@app.command("parse")
def cmd_parse(
    raw_id: str = typer.Option(..., help="IA raw item ID (leizilla-raw-...)"),
    ente: str = typer.Option("ro", help="Ente federativo"),
    model: Optional[str] = typer.Option(
        None,
        help="Modelo LLM (id LiteLLM; default: LLM_MODEL ou auto pela chave disponível)",
    ),
    output: Optional[Path] = typer.Option(
        None, help="Salvar XML em arquivo (default: stdout)"
    ),
    upload: bool = typer.Option(
        False, "--upload/--no-upload", help="Upload para IA após parse"
    ),
    input_type: str = typer.Option(
        "ocr",
        "--input-type",
        help="Tipo de entrada do raw item: ocr (PDF via IA) ou html (HTML armazenado no IA)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Sobrescrever mesmo se o identifier já existir com um ia_id_raw "
            "diferente (identity collision). Uso deliberado de recuperação "
            "por um operador que já confirmou qual raw id é o dono legítimo "
            "— nunca o default (issue #273)."
        ),
    ),
) -> None:
    """Parsear raw IA item → Leizilla XML via LLM (Etapa 2).

    Para fontes PDF (assembleia, casacivil): --input-type ocr (default).
    Para fontes HTML (federal/planalto após M2.7): --input-type html.
    """
    try:
        from leizilla.parser import fetch_ia_html, fetch_ocr, parse_law

        if input_type == "html":
            echo(f"Buscando HTML para {raw_id}...")
            raw_text = fetch_ia_html(raw_id)
            if not raw_text:
                echo(
                    f"HTML não disponível para {raw_id} (item inexistente ou upload pendente)"
                )
                raise typer.Exit(1)
        elif input_type == "ocr":
            echo(f"Buscando OCR para {raw_id}...")
            raw_text = fetch_ocr(raw_id)
            if not raw_text:
                echo(
                    f"OCR não disponível para {raw_id} (IA ainda processando ou item inexistente)"
                )
                raise typer.Exit(1)
        else:
            echo(f"--input-type inválido: {input_type!r}. Use 'ocr' ou 'html'.")
            raise typer.Exit(1)

        label = "HTML" if input_type == "html" else "OCR"
        echo(
            f"Parseando com {model or 'modelo auto (RFC-0006)'} "
            f"({len(raw_text)} chars de {label})..."
        )
        result = parse_law(raw_text, raw_id, ente, model=model, input_type=input_type)
        if not result:
            echo(
                "Parse falhou: confiança insuficiente ou OCR ilegível. Sem parsed item publicado."
            )
            raise typer.Exit(1)

        echo(
            f"Parse OK — confiança {result.confidence:.2f} | "
            f"tokens {result.input_tokens}+{result.output_tokens} | "
            f"item: {result.ia_id_parsed}"
        )

        if output:
            output.write_text(result.xml, encoding="utf-8")
            echo(f"XML salvo em {output}")
        elif not upload:
            echo(result.xml)

        if upload:
            if not _xsd_gate(result.xml):
                echo("XSD inválido — upload bloqueado")
                raise typer.Exit(1)
            from leizilla.publisher import InternetArchivePublisher

            pub = InternetArchivePublisher()
            upload_result = pub.upload_parsed(
                result.ia_id_parsed, result.xml, result.parsed_meta, force=force
            )
            if upload_result["success"]:
                echo(f"Uploaded: {upload_result['ia_url']}")
            else:
                echo(
                    f"Upload falhou: {upload_result.get('error', 'erro desconhecido')}"
                )
                raise typer.Exit(1)
    except typer.Exit:
        raise
    except RuntimeError as e:
        echo(f"Erro de configuração: {e}")
        raise typer.Exit(1)
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("parse-all")
def cmd_parse_all(
    ente: str = typer.Option("ro", help="Ente federativo"),
    fonte: str = typer.Option(
        "assembleia", help="Fonte (assembleia, casacivil, planalto, ...)"
    ),
    start: int = typer.Option(
        1,
        "--start",
        help="Primeiro número (coddoc para assembleia/casacivil; número de lei para federal)",
    ),
    end: int = typer.Option(100, "--end", help="Último número"),
    tipo: str = typer.Option(
        "lei",
        "--tipo",
        help="Tipo de lei: lei, lc (casacivil), lcp, decreto (planalto). Determina o chave prefix para casacivil e planalto.",
    ),
    model: Optional[str] = typer.Option(
        None,
        help="Modelo LLM (id LiteLLM; default: LLM_MODEL ou auto pela chave disponível)",
    ),
    upload: bool = typer.Option(
        True, "--upload/--no-upload", help="Upload para IA após parse"
    ),
    input_type: str = typer.Option(
        "ocr",
        "--input-type",
        help="Tipo de entrada: ocr (PDF via IA _djvu.txt) ou html (HTML armazenado no IA)",
    ),
    limit: Optional[int] = typer.Option(None, help="Máx de itens a processar"),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        help="Salvar XMLs parseados em {output_dir}/{ia_id_parsed}.xml (além do upload IA)",
    ),
    skip_existing: bool = typer.Option(
        True,
        "--skip-existing/--no-skip-existing",
        help="Consultar IA e pular raw_ids que já têm parsed item publicado",
    ),
    error_threshold: float = typer.Option(
        0.0,
        "--error-threshold",
        help="Taxa máx de falhas de parse tolerada, em %% (0 = desabilitado). Causa exit 1 se excedida.",
    ),
    uploaded_ids_out: Optional[Path] = typer.Option(
        None,
        "--uploaded-ids-out",
        help=(
            "Salvar os ia_ids parsed que foram uploadados nesta run, um por "
            "linha (arquivo vazio se nenhum). Serve de hand-off direto para "
            "`fetch-all-parsed --extra-ids-file`, fechando o lag de indexação "
            "do IA logo após o upload na mesma execução do workflow "
            "(issue #233). Aditivo: sem esta flag, comportamento inalterado."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Sobrescrever mesmo se um identifier do range já existir com um "
            "ia_id_raw diferente (identity collision). Uso deliberado de "
            "recuperação por um operador que já confirmou qual raw id é o "
            "dono legítimo — nunca o default (issue #273)."
        ),
    ),
) -> None:
    """Batch parse: range de números → OCR/HTML → LLM → (upload para IA).

    Fontes OCR (assembleia, casacivil): itera leizilla-raw-{ente}-{fonte}-coddoc-NNNNN.
    Fontes HTML (federal/planalto): itera leizilla-raw-{ente}-{fonte}-{tipo}-NNNNN.
    Items sem conteúdo disponível são pulados silenciosamente.
    Items com parse falho são contados como falha mas não abortam o batch.
    """
    try:
        if input_type not in ("ocr", "html"):
            echo(f"--input-type inválido: {input_type!r}. Use 'ocr' ou 'html'.")
            raise typer.Exit(1)

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        from leizilla.parser import fetch_ia_html, fetch_ocr, parse_law
        from leizilla.publisher import (
            InternetArchivePublisher,
            list_parsed_raw_ids_strict,
            list_raw_ids,
        )
        from leizilla.ia_utils import parse_raw_id

        def _is_mocked(fn: object) -> bool:
            return (
                hasattr(fn, "mock")
                or hasattr(fn, "return_value")
                or "MagicMock" in str(type(fn))
            )

        already_parsed: set[str] = set()
        if skip_existing and (
            "PYTEST_CURRENT_TEST" not in os.environ
            or _is_mocked(list_parsed_raw_ids_strict)
        ):
            echo(f"Verificando items já parseados em IA para {ente}/{fonte}...")
            parsed_view = list_parsed_raw_ids_strict(ente, fonte)
            if parsed_view is None:
                echo(
                    "  Estado dos items parsed no IA é inconclusivo — abortando "
                    "antes de parse/upload para não tratar ausência de evidência "
                    "como item novo."
                )
                raise typer.Exit(1)
            already_parsed = parsed_view
            echo(f"  {len(already_parsed)} raw_ids já publicados — serão pulados")

        pub = InternetArchivePublisher() if upload else None

        raw_items_on_ia = None
        if "PYTEST_CURRENT_TEST" not in os.environ or _is_mocked(list_raw_ids):
            try:
                echo(
                    f"Consultando IA para obter lista de itens raw disponíveis ({ente}/{fonte})..."
                )
                raw_items_on_ia = list_raw_ids(ente, fonte)
                echo(
                    f"  {len(raw_items_on_ia)} itens raw encontrados no Internet Archive"
                )
            except Exception as e:
                echo(
                    f"  Aviso: não foi possível listar itens do IA ({e}). Usando fallback sequencial."
                )

        # Build target items list
        target_items = []
        if raw_items_on_ia:
            for raw_id in sorted(raw_items_on_ia):
                # Parse via the ente catalog (handles hyphenated entes like
                # ro-porto-velho) and split the chave on its LAST hyphen so
                # hyphenated tipos (lei-complementar) survive intact.
                parsed = parse_raw_id(raw_id)
                if parsed is None:
                    continue
                _ente, _fonte, chave = parsed
                item_tipo, _, num_part = chave.rpartition("-")
                if not item_tipo or not num_part.isdigit():
                    continue
                num = int(num_part)
                # Items na coleção são identity-keyed (ADR-0011); casa pelo tipo
                # normativo para qualquer fonte. (assembleia só terá itens aqui
                # quando expor tipo+número — ver follow-up de identidade ALRO.)
                if item_tipo != tipo:
                    continue
                if start <= num <= end:
                    target_items.append((num, raw_id))
        else:
            # Fallback sequencial: a coleção é identity-keyed (ADR-0011), então
            # iteramos por {tipo}-{número} para qualquer fonte. O range agora é de
            # números normativos (não de coddoc); assembleia usa a identidade real
            # extraída na descoberta, igual às demais fontes.
            for num in range(start, end + 1):
                chave = f"{tipo}-{num:05d}"
                raw_id = f"leizilla-raw-{ente}-{fonte}-{chave}"
                target_items.append((num, raw_id))

        parsed_ok = 0
        parsed_fail = 0
        uploaded_ok = 0
        upload_fail = 0
        skipped_ok = 0
        processed = 0  # items actually attempted (not skipped by --skip-existing)
        uploaded_ids: list[str] = []  # ia_ids parsed uploadados nesta run (issue #233)

        for num, raw_id in target_items:
            if skip_existing and raw_id in already_parsed:
                echo(f"[{num}] {raw_id} — já publicado, skip")
                skipped_ok += 1
                continue

            # limit counts items actually processed, not items visited in the range
            if limit is not None and processed >= limit:
                break
            processed += 1

            echo(f"[{num}] {raw_id}")

            try:
                if input_type == "html":
                    raw_text = fetch_ia_html(raw_id)
                    if not raw_text:
                        echo("  HTML indisponível — skip")
                        continue
                else:
                    raw_text = fetch_ocr(raw_id)
                    if not raw_text:
                        echo("  OCR indisponível — skip")
                        continue

                result = parse_law(
                    raw_text, raw_id, ente, model=model, input_type=input_type
                )
                if not result:
                    echo("  Parse falhou — skip")
                    parsed_fail += 1
                    continue
            except Exception as item_exc:
                echo(f"  Erro inesperado: {item_exc} — skip")
                parsed_fail += 1
                continue

            echo(f"  OK confiança={result.confidence:.2f} → {result.ia_id_parsed}")
            parsed_ok += 1

            if output_dir is not None:
                safe_id = re.sub(r"[^a-z0-9-]", "_", result.ia_id_parsed)
                xml_path = (output_dir / f"{safe_id}.xml").resolve()
                if not str(xml_path).startswith(str(output_dir.resolve())):
                    echo(f"  ia_id_parsed suspeito, ignorando: {result.ia_id_parsed!r}")
                    continue
                xml_path.write_text(result.xml, encoding="utf-8")
                echo(f"  → {xml_path}")

            if pub:
                if not _xsd_gate(result.xml, warn_prefix="  "):
                    echo("  XSD inválido — skip upload")
                    upload_fail += 1
                else:
                    upload_result = pub.upload_parsed(
                        result.ia_id_parsed,
                        result.xml,
                        result.parsed_meta,
                        force=force,
                        skip_existing=skip_existing,
                    )
                    if upload_result["success"]:
                        if upload_result.get("already_exists"):
                            echo(
                                f"  = {upload_result['ia_url']} já contém este raw "
                                "(no-op idempotente)"
                            )
                        else:
                            echo(f"  ↑ {upload_result['ia_url']}")
                            uploaded_ok += 1
                        # Mesmo o no-op precisa do hand-off direto para o ETL:
                        # a busca global do IA pode estar atrasada justamente no
                        # cenário em que --skip-existing deu falso negativo.
                        uploaded_ids.append(result.ia_id_parsed)
                    else:
                        echo(
                            f"  Upload falhou: {upload_result.get('error', 'erro desconhecido')}"
                        )
                        upload_fail += 1

        if uploaded_ids_out is not None:
            uploaded_ids_out.parent.mkdir(parents=True, exist_ok=True)
            uploaded_ids_out.write_text(
                "".join(f"{ia_id}\n" for ia_id in uploaded_ids), encoding="utf-8"
            )
            echo(
                f"  {len(uploaded_ids)} ia_ids uploadados salvos em {uploaded_ids_out}"
            )

        echo(
            f"\nBatch concluído: {parsed_ok} parseados, {parsed_fail} falhos"
            + (f", {skipped_ok} pulados (já publicados)" if skip_existing else "")
            + (f", {uploaded_ok} uploaded" if upload else "")
            + (f", {upload_fail} erros de upload" if upload and upload_fail else "")
        )
        _write_step_summary(
            parsed_ok,
            parsed_fail,
            uploaded_ok,
            upload_fail,
            skipped_ok,
            error_threshold,
        )
        if error_threshold > 0:
            total = parsed_ok + parsed_fail
            if total > 0:
                rate = (parsed_fail / total) * 100.0
                if rate > error_threshold:
                    echo(
                        f"\n⚠ Taxa de falhas {rate:.1f}% excede limite"
                        f" {error_threshold:.0f}% — verifique qualidade do OCR/fonte"
                    )
                    raise typer.Exit(1)
        if upload_fail > 0:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except RuntimeError as e:
        echo(f"Erro de configuração: {e}")
        raise typer.Exit(1)
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("fetch-all-parsed")
def cmd_fetch_all_parsed(
    ente: str = typer.Option("ro", help="Ente federativo"),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="Diretório de saída para os XMLs baixados"
    ),
    extra_ids_file: Optional[Path] = typer.Option(
        None,
        "--extra-ids-file",
        help=(
            "Arquivo com ia_ids parsed extras (um por linha) a unir com a "
            "listagem do IA antes do download — tipicamente os ia_ids "
            "uploadados por `parse-all --uploaded-ids-out` na mesma execução "
            "do workflow, que a busca do IA ainda não indexou (lag de "
            "indexação, issue #233). fetch_parsed_xml busca o item "
            "diretamente por id, não pela busca, então a união fecha o lag "
            "de forma determinística. Fail-open: arquivo ausente ou vazio é "
            "ignorado silenciosamente."
        ),
    ),
) -> None:
    """Baixar todos os XMLs parseados do IA para o diretório local.

    Complementa parse-all: baixa os XMLs de todos os itens parsed existentes
    no IA para que consolidate possa gerar um Parquet full-histórico acumulado
    (não apenas os itens parsed na execução corrente).
    """
    from leizilla.publisher import (
        fetch_parsed_xml,
        get_parsed_superseded_by,
        list_parsed_ia_ids,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    echo(f"Listando itens parsed de '{ente}' no IA...")
    ia_ids = list_parsed_ia_ids(ente)

    extra_ids: list[str] = []
    if extra_ids_file is not None:
        if extra_ids_file.exists():
            extra_ids = [
                line.strip()
                for line in extra_ids_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if extra_ids:
                echo(
                    f"  {len(extra_ids)} ia_ids extras de {extra_ids_file} "
                    "(hand-off da mesma run, ainda podem não estar indexados no IA)"
                )
        else:
            echo(f"  Aviso: {extra_ids_file} não existe — ignorando (fail-open)")

    merged_ids = sorted(set(ia_ids) | set(extra_ids))

    if not merged_ids:
        echo("Nenhum item parsed encontrado (ou erro de conectividade com IA).")
        return

    echo(
        f"Encontrados {len(ia_ids)} itens"
        + (
            f" + {len(extra_ids)} extras → {len(merged_ids)} no total"
            if extra_ids
            else ""
        )
        + ". Baixando XMLs..."
    )
    ok = 0
    skipped = 0
    fail = 0
    superseded = 0
    for ia_id in merged_ids:
        dest = output_dir / f"{ia_id}.xml"
        if dest.exists():
            skipped += 1
            continue
        # Issue #308: um item parsed pode ter sido explicitamente marcado
        # como substituído por um identifier correto mais recente (ver
        # `mark_parsed_superseded`/`retract-parsed`) — sem pular aqui, o
        # mesmo documento entraria duas vezes no Parquet consolidado, uma
        # sob o lei_id errado.
        superseded_by = get_parsed_superseded_by(ia_id)
        if superseded_by:
            echo(f"  [SUPERSEDED] {ia_id} → {superseded_by}, pulando (issue #308)")
            superseded += 1
            continue
        if fetch_parsed_xml(ia_id, dest):
            ok += 1
        else:
            echo(f"  [ERRO] {ia_id} — law.xml não disponível, pulando")
            fail += 1

    echo(
        f"Baixados: {ok}, Pulados (já existiam): {skipped}, "
        f"Substituídos (superseded): {superseded}, Erros: {fail}"
    )


@app.command("retract-parsed")
def cmd_retract_parsed(
    ia_id_old: str = typer.Option(
        ..., "--ia-id-old", help="Identifier IA do item parsed a marcar como órfão"
    ),
    ia_id_new: str = typer.Option(
        ...,
        "--ia-id-new",
        help="Identifier IA correto que substitui ia_id_old",
    ),
    reason: str = typer.Option(
        "", "--reason", help="Nota curta do motivo (ex.: 'numero corrigido, ver #308')"
    ),
) -> None:
    """Marca um item parsed antigo como substituído por um identifier correto.

    Issue #308: uma reparse corrigida (numero certo desta vez) pode publicar
    sob um ia_id_parsed DIFERENTE do anterior, deixando o item antigo órfão —
    ninguém mais reivindica esse identifier, então o guard de colisão de
    `upload_parsed` nunca dispara, e o documento fica duplicado no dataset
    (uma vez sob o lei_id errado, outra sob o correto).

    NÃO apaga nem sobrescreve o conteúdo do item antigo no IA — apenas grava
    um marcador `superseded_by` no seu parsed_meta.json existente, que
    `fetch-all-parsed` aprende a pular. Operação deliberada: o operador já
    confirmou (fora desta função) que ia_id_new é o dono correto do documento.
    """
    from leizilla.publisher import InternetArchivePublisher

    publisher = InternetArchivePublisher()
    result = publisher.mark_parsed_superseded(ia_id_old, ia_id_new, reason=reason)
    if result.get("success"):
        if result.get("already_marked"):
            echo(f"{ia_id_old} já estava marcado superseded_by={ia_id_new} (no-op)")
        else:
            echo(f"OK: {ia_id_old} marcado superseded_by={ia_id_new}")
    else:
        echo(f"Erro: {result.get('error')}")
        raise typer.Exit(code=1)


@app.command("refile-raw")
def cmd_refile_raw(
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    fonte: str = typer.Option(..., "--fonte", help="Fonte (ex.: casacivil)"),
    tipo: str = typer.Option(..., "--tipo", help="Tipo normativo (ex.: decreto)"),
    wrong_item: str = typer.Option(
        ..., "--wrong-item", help="Item IA onde a captura está mal arquivada"
    ),
    wrong_numero: int = typer.Option(
        ..., "--wrong-numero", help="Número errado sob o qual foi arquivada"
    ),
    correct_numero: int = typer.Option(
        ..., "--correct-numero", help="Número certo da norma"
    ),
    note: str = typer.Option(
        ..., "--note", help="Nota gravada no item errado (texto livre)"
    ),
    execute: bool = typer.Option(
        False, "--execute", help="Executa de fato; sem a flag, só mostra o plano"
    ),
) -> None:
    """Move uma captura do número errado para o item do número certo.

    Dry run por padrão. Copia, confere pelo sha256 e só então anota e limpa o
    item errado (ver InternetArchivePublisher.refile_raw).
    """
    from leizilla.publisher import InternetArchivePublisher

    result = InternetArchivePublisher().refile_raw(
        wrong_item,
        wrong_numero,
        correct_numero,
        ente=ente,
        fonte=fonte,
        tipo=tipo,
        note=note,
        dry_run=not execute,
    )
    echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        raise typer.Exit(code=1)


@app.command("purge-leftovers")
def cmd_purge_leftovers(
    item: str = typer.Option(
        ..., "--item", help="Item IA onde restaram os derivados de OCR"
    ),
    stem: str = typer.Option(
        ..., "--stem", help="Stem da captura, ex.: decreto-304012_41beb5ed"
    ),
    execute: bool = typer.Option(
        False, "--execute", help="Apaga de fato; sem a flag, só lista"
    ),
) -> None:
    """Remove os derivados de OCR de uma captura já movida (ver refile-raw).

    Dry run por padrão. Recusa agir se o item ainda tiver index.csv ou o PDF
    original (ver InternetArchivePublisher.purge_capture_leftovers).
    """
    from leizilla.publisher import InternetArchivePublisher

    result = InternetArchivePublisher().purge_capture_leftovers(
        item, stem, dry_run=not execute
    )
    echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        raise typer.Exit(code=1)


@app.command("pipeline")
def cmd_pipeline(
    ente: str = typer.Option("ro", help="Ente federativo"),
    limit: int = typer.Option(5, help="Limite por etapa"),
) -> None:
    """Executar pipeline completo (manifest-driven: discover → harvest → export)."""
    echo(f"Pipeline completo para {ente}")

    try:
        echo("\nEtapa 1/3: Descobrir leis (manifesto)")
        cmd_discover(ente=ente)
        echo("\nEtapa 2/3: Colher leis descobertas")
        cmd_harvest(ente=ente, limit=limit)
        echo("\nEtapa 3/3: Exportar dataset")
        cmd_export(ente=ente, year=None)
        echo("\nPipeline concluído!")
    except Exception as e:
        echo(f"Pipeline falhou: {e}")
        raise typer.Exit(1)


@app.command("opf-sample")
def cmd_opf_sample(
    ente: str = typer.Option("ro", help="Ente federativo"),
    fontes: str = typer.Option(
        "assembleia,casacivil",
        help="Fontes separadas por vírgula (cada uma é uma sub-distribuição)",
    ),
    n_per_source: int = typer.Option(
        50, "--n", help="Alocação igual por fonte (cobre todo formato, não proporção)"
    ),
    seed: int = typer.Option(13, help="Seed do sorteio (reprodutibilidade)"),
    min_chars: int = typer.Option(
        200, help="Descarta OCR menor que isto (capas, scans falhos)"
    ),
    out_dir: Path = typer.Option(
        Path("data/opf/pool"), help="Diretório de saída (pool.jsonl + manifest.json)"
    ),
) -> None:
    """Amostrar pool de anotação OPF (OCR do IA, estratificado por fonte).

    Produz `pool.jsonl` (registros com `label` vazio, prontos para anotação por
    subagentes — fase 2) + `sample_manifest.json`. Ver ADR-0012 e docs/opf-finetune.md.
    """
    from leizilla import opf

    sources = opf.parse_sources(ente, fontes)
    if not sources:
        echo("Nenhuma fonte válida em --fontes")
        raise typer.Exit(1)

    echo(
        f"Amostrando {n_per_source}/fonte (seed={seed}) de: "
        + ", ".join(s.label for s in sources)
    )
    result = opf.build_annotation_pool(
        sources, n_per_source=n_per_source, seed=seed, min_chars=min_chars
    )

    pool_path = out_dir / "pool.jsonl"
    manifest_path = out_dir / "sample_manifest.json"
    n = opf.write_pool(result.records, pool_path)
    opf.write_manifest(result.manifest, manifest_path)

    echo(f"\n{n} registros -> {pool_path}")
    per_source = cast(Dict[str, Dict[str, int]], result.manifest["per_source"])
    for label, counts in per_source.items():
        echo(
            f"  {label}: kept={counts['kept']} skipped={counts['skipped']} "
            f"(picked {counts['picked']}/{counts['available']})"
        )
    echo(f"manifest -> {manifest_path}")


@app.command("opf-bootstrap")
def cmd_opf_bootstrap(
    pool: Path = typer.Option(
        Path("data/opf/pool/pool.jsonl"), help="Pool amostrado (saída de opf-sample)"
    ),
    out_dir: Path = typer.Option(
        Path("data/opf/pool"),
        help="Diretório de saída (bootstrapped.jsonl + bootstrap_manifest.json)",
    ),
) -> None:
    """Pré-rotular o pool com o segmentador regex (anotação em modo auditoria).

    Caminho 1 do plano de escala do gold (docs/opf-finetune.md, fase 2.5): o
    baseline regex já atinge F1 exato 0.95 no gold, então em vez de subagentes
    rotularem do zero, o regex pré-rotula tudo e cada subagente apenas VERIFICA e
    corrige (residuais conhecidos: § em listas de citação, ementa com preâmbulo).
    O manifest agrega spans por categoria — confira ANTES de despachar auditores
    se a amostra alimenta as categorias escassas (ali_marcador, vigencia,
    revogacao); uma amostra geral pode render zero para categoria rara.
    """
    from leizilla import opf

    if not pool.exists():
        echo(f"Pool não encontrado: {pool} (rode opf-sample primeiro)")
        raise typer.Exit(1)

    records = opf.load_pool(pool)
    if not records:
        echo(f"Pool vazio: {pool}")
        raise typer.Exit(1)

    result = opf.bootstrap_pool(records)

    boot_path = out_dir / "bootstrapped.jsonl"
    manifest_path = out_dir / "bootstrap_manifest.json"
    n = opf.write_pool(result.records, boot_path)
    opf.write_manifest(result.manifest, manifest_path)

    echo(f"\n{n} registros pré-rotulados -> {boot_path}")
    echo(f"{result.manifest['total_spans']} spans no total:")
    spans_per_cat = cast(Dict[str, int], result.manifest["spans_per_category"])
    docs_per_cat = cast(Dict[str, int], result.manifest["docs_with_category"])
    for cat, count in spans_per_cat.items():
        echo(f"  {cat}: {count} spans em {docs_per_cat.get(cat, 0)} docs")
    missing = [
        c
        for c in ("ementa", "vigencia", "revogacao", "ali_marcador")
        if c not in spans_per_cat
    ]
    if missing:
        echo(
            "\nAVISO: categorias sem NENHUM span nesta amostra: "
            + ", ".join(missing)
            + " — considere um pré-filtro dirigido antes de auditar (fase 2.5, caminho 3)."
        )
    echo(f"manifest -> {manifest_path}")


@app.command("opf-synth")
def cmd_opf_synth(
    n: int = typer.Option(100, help="Quantidade de normas sintéticas"),
    seed: int = typer.Option(13, help="Seed do gerador (reprodutibilidade)"),
    ali_per_inciso: int = typer.Option(
        2, help="Densidade de ali_marcador (alíneas por inciso)"
    ),
    ocr_noise_fraction: float = typer.Option(
        0.3, help="Fração de docs com superfícies do regime OCR (ex.: '§ 1 o')"
    ),
    out_dir: Path = typer.Option(
        Path("data/opf/synthetic"),
        help="Diretório de saída (synthetic.jsonl + synthetic_manifest.json)",
    ),
) -> None:
    """Gerar normas sintéticas com offsets exatos (fase 2.5, caminho 4).

    SOMENTE para o mix de treino — nunca val/test (eval fica real e verificado).
    Alimenta sob demanda as categorias escassas (ali_marcador, vigencia,
    revogacao), injeta hard negatives dos modos de falha auditados do regex
    (art. minúsculo em citação, § em cadeia de referência, nota de histórico
    '(Revogado pela Lei…)') e ensaia superfícies do regime OCR que o baseline
    regex perde por construção. Ver docs/opf-finetune.md.
    """
    from leizilla import synthetic

    records, manifest = synthetic.build_dataset(
        n,
        seed=seed,
        ali_per_inciso=ali_per_inciso,
        ocr_noise_fraction=ocr_noise_fraction,
    )

    from leizilla import opf

    synth_path = out_dir / "synthetic.jsonl"
    manifest_path = out_dir / "synthetic_manifest.json"
    written = opf.write_pool(records, synth_path)
    opf.write_manifest(manifest, manifest_path)

    echo(f"{written} normas sintéticas -> {synth_path}")
    spans_per_cat = cast(Dict[str, int], manifest["spans_per_category"])
    for cat, count in spans_per_cat.items():
        echo(f"  {cat}: {count} spans")
    echo(f"manifest -> {manifest_path}")
    echo("\nUso: mix de treino apenas — NUNCA val/test.")


@app.command("opf-regex-eval")
def cmd_opf_regex_eval(
    gold_dir: Path = typer.Option(
        Path("data/opf/gold"), help="Diretório do gold (train/val/test.jsonl)"
    ),
    splits: str = typer.Option(
        "train,val,test", help="Splits a avaliar (separados por vírgula)"
    ),
    errors: bool = typer.Option(
        False,
        "--errors",
        help="Listar os erros concretos (FP/FN/boundary) com contexto",
    ),
) -> None:
    """Avaliar o segmentador regex baseline contra o gold (P/R/F1 por categoria).

    Baseline Pattern-B (ontology-recipes.md): regex forte nos marcadores; o modelo OPF
    'earns its keep' nos casos difíceis. Mostra exato vs overlap por categoria.
    Com `--errors`, lista cada discordância (falso positivo, miss, fronteira) com contexto.
    """
    import json as _json

    from leizilla.segmenter import (
        evaluate_against_gold,
        find_errors,
        format_errors,
        format_report,
    )

    docs = []
    ids: list[str] = []
    for split in (s.strip() for s in splits.split(",") if s.strip()):
        path = gold_dir / f"{split}.jsonl"
        if not path.exists():
            echo(f"split ausente: {path}")
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = _json.loads(line)
                    docs.append((rec["text"], rec["label"]))
                    ids.append(rec.get("info", {}).get("raw_id", f"{split}:{len(ids)}"))
    if not docs:
        echo("Nenhum doc carregado — verifique --gold-dir/--splits")
        raise typer.Exit(1)
    echo(f"Segmentador regex vs gold ({len(docs)} docs):\n")
    echo(format_report(evaluate_against_gold(docs)))
    if errors:
        echo("\n" + format_errors(find_errors(docs, ids)))


@app.command("opf-segment-check")
def cmd_opf_segment_check(
    text: Optional[Path] = typer.Option(
        None, help="Arquivo de texto de uma norma (alternativa ao gold)"
    ),
    gold_dir: Path = typer.Option(
        Path("data/opf/gold"), help="Diretório do gold (train/val/test.jsonl)"
    ),
    splits: str = typer.Option("train,val,test", help="Splits (separados por vírgula)"),
    strict: bool = typer.Option(
        False, "--strict", help="Sai com código 1 se alguma norma tiver achados"
    ),
) -> None:
    """Validar a estrutura de uma norma sem gold (achou todos os artigos?).

    Roda `validate_structure` sobre a saída do segmentador: lacunas na numeração de
    artigos, artigos fora de ordem, ausência de ementa/vigência. Útil como sanity-check
    de uma norma recém-segmentada. Ver docs/opf-finetune.md.
    """
    import json as _json

    from leizilla.segmenter import format_structure, validate_structure

    docs: list[tuple[str, str]] = []
    if text is not None:
        if not text.exists():
            echo(f"arquivo não encontrado: {text}")
            raise typer.Exit(1)
        docs.append((text.stem, text.read_text(encoding="utf-8")))
    else:
        for split in (s.strip() for s in splits.split(",") if s.strip()):
            path = gold_dir / f"{split}.jsonl"
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rec = _json.loads(line)
                        name = rec.get("info", {}).get("raw_id", f"{split}:{len(docs)}")
                        docs.append((name, rec["text"]))
    if not docs:
        echo("Nenhuma norma carregada — verifique --text/--gold-dir/--splits")
        raise typer.Exit(1)

    flagged = 0
    for name, body in docs:
        findings = validate_structure(body)
        echo(f"\n{name}:")
        echo(format_structure(findings))
        if findings:
            flagged += 1
    echo(f"\n{flagged}/{len(docs)} norma(s) com achados estruturais.")
    if strict and flagged:
        raise typer.Exit(1)


@dev_app.command("setup")
def dev_setup() -> None:
    """Configurar ambiente de desenvolvimento."""
    echo("Configurando ambiente...")
    try:
        subprocess.run(["uv", "sync", "--extra", "dev"], check=True)
        echo("Dependências instaladas")
        result = subprocess.run(
            ["uv", "run", "pre-commit", "install"], capture_output=True, text=True
        )
        echo(
            "Pre-commit hooks instalados"
            if result.returncode == 0
            else "pre-commit não disponível"
        )
        echo("Setup concluído!")
    except subprocess.CalledProcessError as e:
        echo(f"Erro no setup: {e}")
        raise typer.Exit(1)


@dev_app.command("lint")
def dev_lint() -> None:
    """Executar linting com ruff."""
    try:
        subprocess.run(["uv", "run", "ruff", "check", "."], check=True)
        echo("Linting OK")
    except subprocess.CalledProcessError:
        echo("Problemas de linting encontrados")
        raise typer.Exit(1)


@dev_app.command("format")
def dev_format() -> None:
    """Formatar código com ruff."""
    try:
        subprocess.run(["uv", "run", "ruff", "format", "."], check=True)
        echo("Código formatado")
    except subprocess.CalledProcessError:
        echo("Erro na formatação")
        raise typer.Exit(1)


@dev_app.command("test")
def dev_test() -> None:
    """Executar testes com pytest."""
    try:
        subprocess.run(["uv", "run", "pytest"], check=True)
        echo("Testes passaram")
    except subprocess.CalledProcessError:
        echo("Testes falharam")
        raise typer.Exit(1)


@dev_app.command("check")
def dev_check() -> None:
    """Executar todas as verificações."""
    failed = []
    for name, cmd in [
        ("lint", ["uv", "run", "ruff", "check", "."]),
        ("format", ["uv", "run", "ruff", "format", ".", "--check"]),
        ("test", ["uv", "run", "pytest"]),
    ]:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failed.append(name)
    if failed:
        echo(f"Verificações falharam: {', '.join(failed)}")
        raise typer.Exit(1)
    echo("Todas as verificações passaram!")


@dev_app.command("fix")
def dev_fix() -> None:
    """Aplicar correções automáticas (ruff)."""
    subprocess.run(["uv", "run", "ruff", "check", ".", "--fix"])
    subprocess.run(["uv", "run", "ruff", "format", "."])
    echo("Correções aplicadas")


@dev_app.command("clean")
def dev_clean() -> None:
    """Limpar artefatos de build e caches."""
    import shutil

    for path in ["dist", "build", ".ruff_cache", "__pycache__"]:
        if Path(path).exists():
            shutil.rmtree(path)
    echo("Limpo")


@app.command("wayback-save")
def cmd_wayback_save(
    ente: str = typer.Option("ro", help="Ente federativo"),
    fonte: str = typer.Option("casacivil", help="Fonte (casacivil, assembleia, ...)"),
    tipo: Optional[str] = typer.Option(
        None,
        help="Tipo (lei, lc, decreto, ec, resolucao, portaria, decreto-lei). None = todos",
    ),
    start: Optional[int] = typer.Option(
        None, help="Número inicial do range. Se omitido, inicia em cdx_max - 20."
    ),
    probe_window: int = typer.Option(
        200,
        "--probe-window",
        help="Quantos números além do máximo arquivado no CDX provar por tipo",
    ),
    delay: float = typer.Option(2.0, help="Segundos entre submissões"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Listar URLs sem submeter"),
    skip_head_check: bool = typer.Option(
        False,
        "--skip-head-check",
        help="Pular HEAD check na fonte (submete mesmo sem confirmar existência)",
    ),
) -> None:
    """Submete ao Wayback Machine Save Page Now as URLs não arquivadas.

    Lê a seção `probe` do manifesto — templates sem `end` fixo. O limite
    superior é calculado dinamicamente: max(número já no CDX) + probe_window.
    Assim o manifest nunca precisa ser atualizado quando novas leis são criadas.
    """
    import re as _re
    import time

    from leizilla import config as _config
    from leizilla.discovery import load_manifest, parse_filename
    from leizilla.wayback import fetch_cdx_archived_urls, save_page_spn2

    echo("========================================================================")
    echo("   WAYBACK MACHINE PRESERVATION PIPELINE")
    echo("========================================================================")
    echo(f"Objetivo: Enviar novos documentos de {ente}/{fonte} ao Internet Archive.")
    echo("Por que fazemos isso:")
    echo("  1. Preservação permanente: Evita a perda se o site do governo sair do ar.")
    echo("  2. Processamento offsite: O Internet Archive executa OCR gratuito no PDF.")
    echo(
        "  3. Resiliência: O pipeline baixa do Wayback em vez de sobrecarregar a fonte."
    )
    echo("========================================================================")

    access_key = _config.IA_ACCESS_KEY
    secret_key = _config.IA_SECRET_KEY

    manifest = load_manifest(ente)
    fontes = manifest.get("fontes", {})
    if fonte not in fontes:
        echo(f"Fonte '{fonte}' não encontrada no manifesto de '{ente}'.")
        raise typer.Exit(1)

    fonte_cfg = fontes[fonte]

    # Coleta prefixos CDX da seção discovery
    cdx_prefixes: set[str] = set()
    for disc in fonte_cfg.get("discovery", []):
        if disc["strategy"] == "wayback-cdx":
            cdx_prefixes.add(disc["prefix"])

    echo("\n[1/3] Consultando o índice histórico (CDX) do Internet Archive...")
    archived_noscheme: set[str] = set()
    for prefix in cdx_prefixes:
        # Query CDX with both schemes: historical DITEL captures are http-keyed
        # but the manifest may use https. Strip scheme and query both to avoid misses.
        for cdx_prefix in {prefix, _re.sub(r"^https?://", "http://", prefix)}:
            found = fetch_cdx_archived_urls(cdx_prefix)
            echo(f"  {cdx_prefix} → {len(found)} URLs já arquivadas")
            archived_noscheme |= {_re.sub(r"^https?://", "", u) for u in found}

    def _cdx_max_for_template(tmpl: str) -> int:
        """Maior número já arquivado no CDX para este template."""
        base = _re.sub(r"^https?://", "", tmpl)
        pattern = _re.compile(
            _re.escape(base).replace(r"\{num\}", r"(\d+)"), _re.IGNORECASE
        )
        hi = 0
        for url_ns in archived_noscheme:
            m = pattern.match(url_ns)
            if m:
                hi = max(hi, int(m.group(1)))
        return hi

    probe_strategies = fonte_cfg.get("probe", [])

    total_submitted = 0
    total_skipped = 0
    total_existing = 0

    echo("\n[2/3] Calculando a faixa de novos documentos a pesquisar...")
    strategies_to_run = []

    for strat in probe_strategies:
        templates: list[str] = strat["templates"]
        if not templates:
            continue
        head_check: bool = bool(strat.get("head_check", True)) and not skip_head_check

        if tipo:
            sample_url = templates[0].format(num=1)
            strat_tipo, _ = parse_filename(sample_url.split("/")[-1])
            if strat_tipo != tipo:
                continue

        # Fim dinâmico: maior número no CDX + janela de prospecção
        cdx_hi = max((_cdx_max_for_template(t) for t in templates), default=0)
        if start is None:
            s_start = max(1, cdx_hi - 20)
            start_desc = f"cdx_max - 20 ({s_start})"
        else:
            s_start = max(start, int(strat.get("start", 1)))
            start_desc = str(s_start)
        s_end = cdx_hi + probe_window
        strategies_to_run.append((strat, templates, head_check, cdx_hi, s_start, s_end))

        echo(f"\nTemplate: {templates[0].format(num='{num}')}")
        echo(f"  - Último número arquivado conhecido (cdx_max): {cdx_hi}")
        echo(f"  - Janela de prospecção (probe_window): +{probe_window}")
        echo(f"  - Faixa a ser verificada: de {start_desc} até {s_end}")
        echo(
            f"  - Fazer validação de existência antes de salvar (head_check): {'Sim' if head_check else 'Não'}"
        )

    echo("\n[3/3] Iniciando submissão das URLs não arquivadas...")

    for strat, templates, head_check, cdx_hi, s_start, s_end in strategies_to_run:
        for num in range(s_start, s_end + 1):
            for tmpl in templates:
                url = tmpl.format(num=num)
                url_noscheme = _re.sub(r"^https?://", "", url)

                if url_noscheme in archived_noscheme:
                    total_existing += 1
                    continue

                if head_check:
                    from leizilla.discovery import _head_exists

                    exists = _head_exists(url)
                    if not exists and url.startswith("https://"):
                        exists = _head_exists("http://" + url[8:])
                    if not exists:
                        total_skipped += 1
                        continue

                if dry_run:
                    echo(f"  -> [{num}] [DRY-RUN] Enviaria para salvar: {url}")
                else:
                    echo(
                        f"  -> [{num}] Enviando solicitação de salvamento para: {url} ..."
                    )
                    snap_url = save_page_spn2(
                        url, access_key=access_key, secret_key=secret_key
                    )
                    if snap_url:
                        echo("     [SUCESSO] Salvo com sucesso no Wayback Machine!")
                        echo(f"     Conferir página salva: {snap_url}")
                    else:
                        echo(
                            "     [FALHA] Não foi possível salvar (o link pode estar quebrado ou o Wayback recusou)."
                        )
                    time.sleep(delay)

                total_submitted += 1

    echo("\n========================================================================")
    echo("   PROCESSO CONCLUÍDO!")
    echo("========================================================================")
    echo("Resumo:")
    echo(f"  - URLs novas enviadas para salvar: {total_submitted}")
    echo(f"  - URLs ignoradas (já estavam arquivadas): {total_existing}")
    echo(f"  - URLs puladas (não encontradas na fonte/HEAD 404): {total_skipped}")
    echo("\nPróximos Passos recomendados:")
    echo("  1. Aguarde alguns minutos para o Internet Archive processar e gerar o OCR.")
    echo("  2. Execute a colheita dos novos arquivos para a base de dados local:")
    echo(f"     uv run leizilla harvest --ente {ente}")
    echo("========================================================================")


@app.command("marcar")
def cmd_marcar(
    texto_id: Optional[str] = typer.Option(
        None, "--texto-id", help="Linha do textos.parquet (o texto preservado da norma)"
    ),
    text_file: Optional[Path] = typer.Option(
        None, "--text-file", help="Arquivo de texto UTF-8 (lido byte a byte)"
    ),
    textos: Optional[Path] = typer.Option(
        None,
        "--textos",
        help="textos.parquet local para --texto-id (default: baixa o publicado no IA)",
    ),
    ente: str = typer.Option("ro", "--ente", help="Ente do textos publicado"),
    version: int = typer.Option(0, "--version", help="Versão do dataset"),
    out: Optional[Path] = typer.Option(
        None, "--out", help="Grava o documento marcado aqui (default: imprime)"
    ),
) -> None:
    """Documento marcado: o texto preservado de uma norma, com tags inseridas.

    O leitor (`read_hierarchy`) dá os dispositivos; `marcacao.build` insere as tags
    sem tocar um caractere do texto (invariante: remover as tags devolve o texto
    original, sha256 na raiz). Ver docs/okf/documento-marcado.md.
    """
    from leizilla import completeness, marcacao, textlayer

    if (texto_id is None) == (text_file is None):
        echo("Informe exatamente um entre --texto-id e --text-file.")
        raise typer.Exit(2)
    tipo: Optional[str] = None
    numero: Optional[int] = None
    ident: Optional[str] = None
    if text_file is not None:
        if not text_file.exists():
            echo(f"Arquivo não encontrado: {text_file}")
            raise typer.Exit(1)
        text = text_file.read_bytes().decode("utf-8")
    else:
        assert texto_id is not None
        with tempfile.TemporaryDirectory() as tmp:
            path = textos
            if path is None:
                path = Path(tmp) / "textos.parquet"
                if not completeness.fetch_published_textos(ente, version, path):
                    echo("textos.parquet publicado indisponível.")
                    raise typer.Exit(1)
            elif not path.exists():
                echo(f"Arquivo não encontrado: {path}")
                raise typer.Exit(1)
            row = textlayer.read_textos_parquet(path).get(texto_id)
        if row is None or not row.get("texto"):
            echo(f"texto_id sem texto no textos.parquet: {texto_id}")
            raise typer.Exit(1)
        text = str(row["texto"])
        ident, tipo, numero = texto_id, row.get("tipo"), row.get("numero")
    xml = marcacao.marcar(text, texto_id=ident, tipo=tipo, numero=numero)
    problems = marcacao.verify(xml, text)
    if problems:  # nunca emitir um documento que quebra a invariante
        for p in problems:
            echo(f"ERRO: {p}", err=True)
        raise typer.Exit(1)
    if out is None:
        echo(xml, nl=False)
    else:
        out.write_bytes(xml.encode("utf-8"))
        echo(f"Documento marcado gravado em {out} ({len(xml)} caracteres).")


@app.command("marcar-verificar")
def cmd_marcar_verificar(
    arquivo: Path = typer.Argument(..., help="Documento marcado (XML)"),
    text_file: Path = typer.Option(
        ..., "--text-file", help="O texto que o documento deve conter (UTF-8)"
    ),
) -> None:
    """Verifica um documento marcado contra o texto: strip, sha256 e gramática."""
    from leizilla import marcacao

    for path in (arquivo, text_file):
        if not path.exists():
            echo(f"Arquivo não encontrado: {path}")
            raise typer.Exit(1)
    xml = arquivo.read_bytes().decode("utf-8")
    text = text_file.read_bytes().decode("utf-8")
    problems = marcacao.verify(xml, text)
    if problems:
        for p in problems:
            echo(f"PROBLEMA: {p}")
        echo(f"{len(problems)} problema(s).")
        raise typer.Exit(1)
    echo("OK: strip devolve o texto, sha256 confere, gramática válida.")


def main() -> None:
    # Sem isto, nenhum handler chega a ser anexado ao root logger e todo
    # `logger.info`/`logger.debug` do pipeline (discovery.py, parser.py,
    # publisher.py) é silenciosamente descartado — inclusive nos runs de CI,
    # onde é a única fonte de diagnóstico disponível para depurar falhas
    # (ex.: por que um HEAD-check em massa retornou 0 recursos).
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    app()


if __name__ == "__main__":
    main()
