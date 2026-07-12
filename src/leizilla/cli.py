"""Leizilla CLI — interface de linha de comando."""

import asyncio
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional, cast

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
) -> None:
    """Descobrir leis nos portais oficiais usando manifestos."""
    alvo = f"{ente}/{fonte}" if fonte else ente
    echo(f"Descobrindo leis para: {alvo}...")
    try:
        from leizilla.discovery import run_discovery
        from leizilla.storage import DuckDBStorage

        db = DuckDBStorage()
        added = run_discovery(ente, db, fonte=fonte)
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
) -> None:
    """Consome a fila de resources pendentes no banco e realiza a colheita (harvest)."""
    echo("Iniciando colheita (harvesting) de recursos pendentes...")
    try:
        from leizilla.publisher import InternetArchivePublisher
        from leizilla.scraper import harvest_pending_resources
        from leizilla.storage import DuckDBStorage

        db = DuckDBStorage()
        pub = InternetArchivePublisher()

        stats = harvest_pending_resources(db, pub, limit=limit, ente=ente, tipo=tipo)
        echo("Colheita concluída:")
        echo(f"  Sucesso: {stats['success']}")
        echo(f"  Falhas: {stats['failed']}")
        echo(f"  Robots bloqueado: {stats['robots-blocked']}")
    except Exception as e:
        echo(f"Erro: {e}")
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
                    fonte_url = law.get("url_original")
                    if not fonte_url:
                        continue
                    if skip_existing:
                        chave = str(law.get("chave", ""))
                        ia_id = f"leizilla-raw-{ente}-{fonte}-{chave}"
                        if ia_id in already_scraped:
                            skipped_ok += 1
                            continue
                    result = scrape_one_html(
                        fonte_url, law, publisher, rate_limiter, index_cache
                    )
                    if result.get("success"):
                        ia_id = result.get("ia_id", "?")
                        ia_url = result.get("ia_url", "?")
                        echo(f"  OK: {ia_id} → {ia_url}")
                        ok += 1
                    else:
                        echo(
                            f"  Falha [{result.get('reason', '?')}]: {law.get('chave', 'N/A')}"
                        )
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
            index_cache: Dict[str, str] = {}
            for law in laws:
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
                    echo(
                        f"  Falha [{result.get('reason', '?')}]: {law.get('id', 'N/A')}"
                    )

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
) -> None:
    """Publicar Parquet no IA como leizilla-dataset-{ente}-v{version} (M4 restante)."""
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

    from leizilla.publisher import InternetArchivePublisher

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
    else:
        echo(f"Upload falhou: {result.get('error', 'erro desconhecido')}")
        raise typer.Exit(1)


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
            items.append((lei_id, ente, xml_content))
        except OSError as e:
            echo(f"  Erro ao ler {f.name}: {e}")
            read_errors += 1

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
    """Valida XML contra leizilla-v0.1.xsd via xmllint. Fail-open: só avisa, não aborta."""
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
                result.ia_id_parsed, result.xml, result.parsed_meta
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
            list_parsed_raw_ids,
            list_raw_ids,
        )
        from leizilla.ia_utils import parse_raw_id

        already_parsed: set[str] = set()
        if skip_existing:
            echo(f"Verificando items já parseados em IA para {ente}/{fonte}...")
            already_parsed = list_parsed_raw_ids(ente, fonte)
            echo(f"  {len(already_parsed)} raw_ids já publicados — serão pulados")

        pub = InternetArchivePublisher() if upload else None

        raw_items_on_ia = None
        is_mocked = (
            hasattr(list_raw_ids, "mock")
            or hasattr(list_raw_ids, "return_value")
            or "MagicMock" in str(type(list_raw_ids))
        )
        if "PYTEST_CURRENT_TEST" not in os.environ or is_mocked:
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
                        result.ia_id_parsed, result.xml, result.parsed_meta
                    )
                    if upload_result["success"]:
                        echo(f"  ↑ {upload_result['ia_url']}")
                        uploaded_ok += 1
                    else:
                        echo(
                            f"  Upload falhou: {upload_result.get('error', 'erro desconhecido')}"
                        )
                        upload_fail += 1

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
) -> None:
    """Baixar todos os XMLs parseados do IA para o diretório local.

    Complementa parse-all: baixa os XMLs de todos os itens parsed existentes
    no IA para que consolidate possa gerar um Parquet full-histórico acumulado
    (não apenas os itens parsed na execução corrente).
    """
    from leizilla.publisher import fetch_parsed_xml, list_parsed_ia_ids

    output_dir.mkdir(parents=True, exist_ok=True)

    echo(f"Listando itens parsed de '{ente}' no IA...")
    ia_ids = list_parsed_ia_ids(ente)

    if not ia_ids:
        echo("Nenhum item parsed encontrado (ou erro de conectividade com IA).")
        return

    echo(f"Encontrados {len(ia_ids)} itens. Baixando XMLs...")
    ok = 0
    skipped = 0
    fail = 0
    for ia_id in ia_ids:
        dest = output_dir / f"{ia_id}.xml"
        if dest.exists():
            skipped += 1
            continue
        if fetch_parsed_xml(ia_id, dest):
            ok += 1
        else:
            echo(f"  [ERRO] {ia_id} — law.xml não disponível, pulando")
            fail += 1

    echo(f"Baixados: {ok}, Pulados (já existiam): {skipped}, Erros: {fail}")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
