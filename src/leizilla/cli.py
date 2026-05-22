"""Leizilla CLI — interface de linha de comando."""

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

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
    start_coddoc: int = typer.Option(1, help="ID inicial do documento"),
    end_coddoc: int = typer.Option(10, help="ID final do documento"),
    crawler_type: str = typer.Option(
        "playwright", help="Tipo de crawler (playwright, simple)"
    ),
) -> None:
    """Descobrir leis nos portais oficiais."""
    echo(f"Descobrindo leis de {ente} (coddoc: {start_coddoc}-{end_coddoc})")

    try:
        from leizilla.crawler import LeisCrawler
        from leizilla.storage import DuckDBStorage

        async def run() -> None:
            crawler = LeisCrawler(crawler_type=crawler_type)
            db = DuckDBStorage()

            if ente == "ro":
                laws = await crawler.discover_rondonia_laws(
                    start_coddoc=start_coddoc,
                    end_coddoc=end_coddoc,
                )
                for law in laws:
                    db.insert_lei(law)
                    echo(f"  Salvou: {law.get('titulo', 'N/A')}")
                echo(f"Descobriu {len(laws)} leis de {ente}")
            else:
                echo(f"Ente '{ente}' ainda não implementado")
                raise typer.Exit(1)

        asyncio.run(run())
    except Exception as e:
        echo(f"Erro: {e}")
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
        for law in to_upload[:limit]:
            try:
                pdf_path = Path(law["local_pdf_path"])
                if not pdf_path.exists():
                    continue
                pdf_bytes = pdf_path.read_bytes()
                result = publisher.upload_raw(
                    pdf_path, law, pdf_bytes, fetched_from="source-fallback"
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
    fonte: str = typer.Option("assembleia", help="Fonte (assembleia, casacivil)"),
    start_coddoc: int = typer.Option(
        1, help="ID inicial (coddoc para assembleia; número de lei para casacivil)"
    ),
    end_coddoc: int = typer.Option(10, help="ID final"),
    tipo: str = typer.Option(
        "lei", help="Tipo de lei para casacivil: lei (ordinária) ou lc (complementar)"
    ),
) -> None:
    """Scrape leis: discover → robots → wayback → upload_raw para IA."""
    if tipo != "lei" and fonte != "casacivil":
        echo(
            f"--tipo só é válido com --fonte casacivil (recebido: --tipo {tipo} --fonte {fonte})"
        )
        raise typer.Exit(1)

    echo(f"Scraping {ente}/{fonte} {start_coddoc}–{end_coddoc}")

    try:
        from leizilla.crawler import LeisCrawler, discover_casacivil_laws
        from leizilla.publisher import InternetArchivePublisher
        from leizilla.scraper import make_rate_limiter, scrape_one

        publisher = InternetArchivePublisher()
        rate_limiter = make_rate_limiter()

        async def run() -> None:
            if ente == "ro" and fonte == "assembleia":
                crawler = LeisCrawler(crawler_type="playwright")
                laws = await crawler.discover_rondonia_laws(
                    start_coddoc=start_coddoc,
                    end_coddoc=end_coddoc,
                )
            elif ente == "ro" and fonte == "casacivil":
                laws = discover_casacivil_laws(
                    tipo=tipo,
                    start_num=start_coddoc,
                    end_num=end_coddoc,
                )
            else:
                echo(f"Fonte '{fonte}' para '{ente}' ainda não implementada")
                raise typer.Exit(1)

            ok = 0
            for law in laws:
                pdf_url = law.get("url_pdf_original")
                fonte_url = law.get("url_original")
                if not pdf_url or not fonte_url:
                    echo(f"  Sem URL PDF: {law.get('id', 'N/A')}")
                    continue
                result = scrape_one(fonte_url, pdf_url, law, publisher, rate_limiter)
                if result.get("success"):
                    echo(f"  OK: {result.get('ia_id', '?')}")
                    ok += 1
                else:
                    echo(
                        f"  Falha [{result.get('reason', '?')}]: {law.get('id', 'N/A')}"
                    )

            echo(f"Scraping concluído: {ok}/{len(laws)} com sucesso")

        asyncio.run(run())
    except Exception as e:
        echo(f"Erro: {e}")
        raise typer.Exit(1)


@app.command("release-dataset")
def cmd_release_dataset(
    parquet: Path = typer.Argument(..., help="Arquivo versoes.parquet (saída de consolidate)"),
    ente: str = typer.Option("ro", "--ente", help="Ente federativo"),
    version: int = typer.Option(0, "--version", help="Versão do dataset (0 = pré-M5)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Reporta stats sem fazer upload"),
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
        row_count: int = conn.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(parquet)]
        ).fetchone()[0]  # type: ignore[index]

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
            echo("  2+ gatilhos → RFC sobre split de tabelas obrigatório antes de fechar M5")

    if dry_run:
        echo("Dry-run: nenhum upload realizado.")
        return

    from leizilla.publisher import InternetArchivePublisher, build_dataset_meta

    git_sha = None
    try:
        import subprocess as _sp
        git_sha = _sp.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip() or None
    except Exception:
        pass

    publisher = InternetArchivePublisher()
    result = publisher.upload_dataset(parquet, ente, version, row_count, git_sha)
    if result.get("success"):
        echo(f"Dataset publicado: {result['ia_url']} ({result.get('row_count', '?')} linhas)")
    else:
        echo(f"Upload falhou: {result.get('error', 'erro desconhecido')}")


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
        echo(f"  Aviso: {read_errors}/{len(xml_files)} arquivo(s) ignorado(s) por erro de leitura.")
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
def cmd_stats() -> None:
    """Mostrar estatísticas do banco de dados."""
    echo("Estatísticas do banco:")

    try:
        from leizilla.storage import DuckDBStorage

        db = DuckDBStorage()
        stats = db.get_stats()
        echo(f"  Total de leis: {stats.get('total_leis', 0)}")
        echo("  Por ente:")
        for ente, count in stats.get("por_ente", {}).items():
            echo(f"    {ente}: {count}")
        echo("  Por ano:")
        for year, count in sorted(stats.get("por_ano", {}).items()):
            echo(f"    {year}: {count}")
    except Exception as e:
        echo(f"Erro: {e}")
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


@app.command("parse")
def cmd_parse(
    raw_id: str = typer.Option(..., help="IA raw item ID (leizilla-raw-...)"),
    ente: str = typer.Option("ro", help="Ente federativo"),
    model: str = typer.Option("claude-haiku-4-5", help="Claude model para parse"),
    output: Optional[Path] = typer.Option(
        None, help="Salvar XML em arquivo (default: stdout)"
    ),
    upload: bool = typer.Option(
        False, "--upload/--no-upload", help="Upload para IA após parse"
    ),
) -> None:
    """Parsear OCR de raw IA item → Leizilla XML via LLM (Etapa 2)."""
    try:
        from leizilla.parser import fetch_ocr, parse_law

        echo(f"Buscando OCR para {raw_id}...")
        ocr = fetch_ocr(raw_id)
        if not ocr:
            echo(
                f"OCR não disponível para {raw_id} (IA ainda processando ou item inexistente)"
            )
            raise typer.Exit(1)

        echo(f"Parseando com {model} ({len(ocr)} chars de OCR)...")
        result = parse_law(ocr, raw_id, ente, model=model)
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
    fonte: str = typer.Option("assembleia", help="Fonte (assembleia, casacivil, ...)"),
    start_coddoc: int = typer.Option(1, help="Primeiro coddoc"),
    end_coddoc: int = typer.Option(100, help="Último coddoc"),
    model: str = typer.Option("claude-haiku-4-5", help="Claude model para parse"),
    upload: bool = typer.Option(
        True, "--upload/--no-upload", help="Upload para IA após parse"
    ),
    limit: Optional[int] = typer.Option(None, help="Máx de itens a processar"),
) -> None:
    """Batch parse: coddoc range → OCR → LLM → (upload para IA).

    Itera leizilla-raw-{ente}-{fonte}-coddoc-NNNNN para cada coddoc no range.
    Items sem OCR disponível são pulados silenciosamente (IA ainda processando).
    Items com parse falho são contados como falha mas não abortam o batch.
    """
    try:
        from leizilla.parser import fetch_ocr, parse_law
        from leizilla.publisher import InternetArchivePublisher

        pub = InternetArchivePublisher() if upload else None
        coddocs = range(start_coddoc, end_coddoc + 1)
        if limit is not None:
            coddocs = coddocs[:limit]

        parsed_ok = 0
        parsed_fail = 0
        uploaded_ok = 0
        upload_fail = 0

        for coddoc in coddocs:
            raw_id = f"leizilla-raw-{ente}-{fonte}-coddoc-{coddoc:05d}"
            echo(f"[{coddoc}] {raw_id}")

            try:
                ocr = fetch_ocr(raw_id)
                if not ocr:
                    echo("  OCR indisponível — skip")
                    continue

                result = parse_law(ocr, raw_id, ente, model=model)
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
            + (f", {uploaded_ok} uploaded" if upload else "")
            + (f", {upload_fail} erros de upload" if upload and upload_fail else "")
        )
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


@app.command("pipeline")
def cmd_pipeline(
    ente: str = typer.Option("ro", help="Ente federativo"),
    start_coddoc: int = typer.Option(1, help="ID inicial"),
    end_coddoc: int = typer.Option(10, help="ID final"),
    crawler_type: str = typer.Option("playwright", help="Tipo de crawler"),
    limit: int = typer.Option(5, help="Limite por etapa"),
) -> None:
    """Executar pipeline completo."""
    echo(f"Pipeline completo para {ente}")

    try:
        echo("\nEtapa 1/4: Descobrir leis")
        cmd_discover(
            ente=ente,
            start_coddoc=start_coddoc,
            end_coddoc=end_coddoc,
            crawler_type=crawler_type,
        )
        echo("\nEtapa 2/4: Baixar PDFs")
        cmd_download(ente=ente, limit=limit)
        echo("\nEtapa 3/4: Upload para IA")
        cmd_upload(limit=limit)
        echo("\nEtapa 4/4: Exportar dataset")
        cmd_export(ente=ente, year=None)
        echo("\nPipeline concluído!")
    except Exception as e:
        echo(f"Pipeline falhou: {e}")
        raise typer.Exit(1)


@dev_app.command("setup")
def dev_setup() -> None:
    """Configurar ambiente de desenvolvimento."""
    echo("Configurando ambiente...")
    try:
        subprocess.run(["uv", "sync", "--dev"], check=True)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
